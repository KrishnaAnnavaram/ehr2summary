"""Judges that score a summary against its source record on four criteria (0 to 10).

- ``LLMJudge``: G-Eval style. The judge sees the record AND the summary. Scores are parsed JSON,
  averaged over ``samples`` calls, or weighted by the score-token probabilities (``mode="logprob"``).
- ``RuleJudge``: offline heuristic from the faithfulness check and simple text statistics.
  It is a baseline and a test double, not a validated clinical judge.
"""

from __future__ import annotations

import logging
import re
import statistics
from dataclasses import dataclass, field

from .faithfulness import FaithfulnessChecker
from .llm import ChatModel, LLMError, check_privacy
from .prompts import CRITERIA, judge_messages, single_criterion_messages
from .records import Record
from .summary import NOT_DOCUMENTED, Summary, SummaryFormatError, extract_json_object

log = logging.getLogger(__name__)


class JudgeIndependenceError(ValueError):
    """The judge is the same model as the generator."""


@dataclass
class JudgeResult:
    record_id: str
    system: str
    judge: str
    scores: dict[str, float]
    spread: dict[str, float] = field(default_factory=dict)
    reasons: dict[str, str] = field(default_factory=dict)
    samples: int = 1

    def to_dict(self) -> dict:
        return {"record_id": self.record_id, "system": self.system, "judge": self.judge, "scores": self.scores,
                "spread": self.spread, "reasons": self.reasons, "samples": self.samples}


def ensure_independent(generator_identity: str, judge_identity: str, allow_self: bool) -> None:
    if not allow_self and generator_identity.removeprefix("llm:") == judge_identity:
        raise JudgeIndependenceError(
            f"the judge {judge_identity} is also the generator. Use a different judge model or set "
            "EHR2SUMMARY_ALLOW_SELF_JUDGE=true (self-scores are biased)."
        )


def parse_scores(reply: str) -> tuple[dict[str, float], dict[str, str]]:
    obj = extract_json_object(reply)
    scores, reasons = {}, {}
    for c in CRITERIA:
        v = obj.get(c)
        if v is None:
            # accept "Clinical Accuracy" or "clinical accuracy" keys
            v = next((val for key, val in obj.items() if re.sub(r"[^a-z]", "_", key.lower()) == c), None)
        if isinstance(v, dict):
            reasons[c] = str(v.get("reason", ""))[:500]
            v = v.get("score")
        if isinstance(v, str):
            m = re.search(r"\d+(?:\.\d+)?", v)
            v = float(m.group()) if m else None
        if not isinstance(v, (int, float)):
            raise SummaryFormatError(f"no numeric score for {c}")
        if not 0 <= float(v) <= 10:
            raise SummaryFormatError(f"score for {c} is out of range: {v}")
        scores[c] = float(v)
    return scores, reasons


class LLMJudge:
    def __init__(self, model: ChatModel, *, samples: int = 1, temperature: float = 0.0, seed: int = 0,
                 mode: str = "json", allow_remote: bool = False, max_attempts: int = 2):
        if mode not in {"json", "logprob"}:
            raise ValueError("mode must be 'json' or 'logprob'")
        if samples > 1 and temperature == 0.0 and mode == "json":
            log.warning("several judge samples at temperature 0 give the same scores")
        self.model, self.samples, self.temperature, self.seed = model, samples, temperature, seed
        self.mode, self.allow_remote, self.max_attempts = mode, allow_remote, max_attempts
        self.name = f"llm-judge:{model.identity}:{mode}"

    def _one_sample(self, record: Record, summary: Summary, seed: int) -> tuple[dict[str, float], dict[str, str]]:
        msgs = judge_messages(record, summary)
        last = ""
        for _ in range(self.max_attempts):
            reply = self.model.complete(msgs, temperature=self.temperature, seed=seed, json_mode=True, max_tokens=600)
            try:
                return parse_scores(reply)
            except SummaryFormatError as exc:
                last = str(exc)
                msgs = msgs + [{"role": "assistant", "content": reply[:3000]},
                               {"role": "user", "content": f"Not valid: {last}. Reply with the JSON only."}]
        raise LLMError(f"judge reply not valid after {self.max_attempts} attempts: {last}")

    def score(self, record: Record, summary: Summary) -> JudgeResult:
        check_privacy(self.model, record.synthetic, self.allow_remote)
        if self.mode == "logprob":
            dist_fn = getattr(self.model, "score_distribution", None)
            if dist_fn is None:
                raise LLMError(f"{self.model.identity} gives no logprobs. Use mode 'json'.")
            scores = {}
            for c in CRITERIA:
                dist = dist_fn(single_criterion_messages(record, summary, c), seed=self.seed)
                scores[c] = round(sum(k * p for k, p in dist.items()), 3)
            return JudgeResult(record.record_id, summary.system, self.name, scores)
        runs = [self._one_sample(record, summary, self.seed + i) for i in range(self.samples)]
        scores = {c: round(statistics.fmean(r[0][c] for r in runs), 3) for c in CRITERIA}
        spread = {c: round(statistics.pstdev([r[0][c] for r in runs]), 3) for c in CRITERIA} if self.samples > 1 else {}
        return JudgeResult(record.record_id, summary.system, self.name, scores, spread, runs[0][1], self.samples)


class RuleJudge:
    name = "rule-judge"

    def __init__(self, checker: FaithfulnessChecker):
        self.checker = checker

    def score(self, record: Record, summary: Summary) -> JudgeResult:
        f = self.checker.check(record, summary)
        accuracy = 10 * f.precision - 2 * len(f.invalid_refs) - 2 * len(f.unknown_codes)
        completeness = 10 * f.recall
        texts = [st.text for _, st in summary.statements() if st.text != NOT_DOCUMENTED]
        words = [len(t.split()) for t in texts] or [0]
        mean_len = statistics.fmean(words)
        readability = 10 - max(0.0, mean_len - 25) * 0.4 - max(0.0, 5 - mean_len) * 1.0
        follow = " ".join(st.text for st in summary.sections.get("follow_up", []))
        meds = summary.sections.get("medications", [])
        actionability = 0.0
        actionability += 4 if ("discharge location" in follow.lower() or "died" in follow.lower()) else 0
        actionability += 3 if any(st.refs for st in meds) or not record.medications else 0
        actionability += 3 if (not record.labs or any(r.startswith("lab") for st in summary.sections.get("follow_up", [])
                                                      for r in st.refs)) else 0
        clamp = lambda x: round(min(10.0, max(0.0, x)), 3)  # noqa: E731
        scores = {"clinical_accuracy": clamp(accuracy), "completeness": clamp(completeness),
                  "readability": clamp(readability), "actionability": clamp(actionability)}
        return JudgeResult(record.record_id, summary.system, self.name, scores)
