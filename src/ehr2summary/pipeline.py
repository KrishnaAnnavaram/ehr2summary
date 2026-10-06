"""Benchmark runner: records -> summaries for each system -> faithfulness, judge scores, ROUGE -> report."""

from __future__ import annotations

import csv
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from .faithfulness import FaithfulnessChecker
from .generators import Generator
from .judge import JudgeResult
from .llm import LLMError
from .metrics import bootstrap_ci, kendall_tau_b, rouge_l, rouge_n, spearman
from .prompts import CRITERIA
from .records import Record
from .summary import Summary

log = logging.getLogger(__name__)


@dataclass
class Row:
    record_id: str
    system: str
    summary: Summary
    faithfulness: dict
    judge: JudgeResult | None
    rouge: dict | None = None

    def to_dict(self) -> dict:
        return {"record_id": self.record_id, "system": self.system, "summary": self.summary.model_dump(),
                "faithfulness": self.faithfulness, "judge": self.judge.to_dict() if self.judge else None,
                "rouge": self.rouge}


@dataclass
class RunResult:
    rows: list[Row] = field(default_factory=list)
    failures: list[dict] = field(default_factory=list)


def run_benchmark(records: list[Record], generators: list[Generator], checker: FaithfulnessChecker,
                  judge=None) -> RunResult:
    result = RunResult()
    for gen in generators:
        for rec in records:
            try:
                summary = gen.generate(rec)
            except LLMError as exc:
                result.failures.append({"record_id": rec.record_id, "system": gen.name, "error": str(exc)})
                log.warning("generation failed for %s with %s: %s", rec.record_id, gen.name, exc)
                continue
            if summary.record_id != rec.record_id:  # never attach a summary to another record
                raise RuntimeError(f"{gen.name} returned a summary for {summary.record_id}, not {rec.record_id}")
            faith = checker.check(rec, summary).to_dict()
            scores = judge.score(rec, summary) if judge is not None else None
            rouge = None
            if rec.reference_note:
                text = summary.text()
                rouge = {"rouge1": round(rouge_n(text, rec.reference_note, 1), 4),
                         "rouge2": round(rouge_n(text, rec.reference_note, 2), 4),
                         "rougeL": round(rouge_l(text, rec.reference_note), 4)}
            result.rows.append(Row(rec.record_id, gen.name, summary, faith, scores, rouge))
    return result


def _ci(values: list[float], seed: int) -> dict:
    mean, lo, hi = bootstrap_ci(values, seed=seed)
    return {"mean": round(mean, 3), "ci95": [round(lo, 3), round(hi, 3)], "n": len(values)}


def summarize(result: RunResult, seed: int = 0) -> dict:
    systems = sorted({r.system for r in result.rows})
    report: dict = {"systems": {}, "failures": len(result.failures)}
    for s in systems:
        rows = [r for r in result.rows if r.system == s]
        entry = {
            "summaries": len(rows),
            "entity_precision": _ci([r.faithfulness["precision"] for r in rows], seed),
            "entity_recall": _ci([r.faithfulness["recall"] for r in rows], seed),
            "hallucination_rate": _ci([float(r.faithfulness["hallucinated"]) for r in rows], seed),
        }
        with_rouge = [r for r in rows if r.rouge]
        if with_rouge:
            entry["rougeL"] = _ci([r.rouge["rougeL"] for r in with_rouge], seed)
        judged = [r for r in rows if r.judge]
        if judged:
            entry["judge"] = {c: _ci([r.judge.scores[c] for r in judged], seed) for c in CRITERIA}
        report["systems"][s] = entry
    return report


def write_outputs(result: RunResult, report: dict, out_dir: Path) -> None:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "rows.jsonl").open("w", encoding="utf-8") as fh:
        for r in result.rows:
            fh.write(json.dumps(r.to_dict()) + "\n")
    (out_dir / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    if result.failures:
        (out_dir / "failures.json").write_text(json.dumps(result.failures, indent=2), encoding="utf-8")


# ------------------------------------------------------------------ judge-human agreement

RATING_COLUMNS = {"record_id", "system", "criterion", "rating"}


def read_ratings(path: Path) -> dict[tuple[str, str, str], float]:
    """Human ratings CSV: record_id, system, criterion, rating (0-10). Several raters are averaged."""
    acc: dict[tuple[str, str, str], list[float]] = {}
    with Path(path).open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        missing = RATING_COLUMNS - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"ratings file lacks columns {sorted(missing)}")
        for row in reader:
            if row["criterion"] not in CRITERIA:
                raise ValueError(f"unknown criterion {row['criterion']!r}")
            value = float(row["rating"])
            if not 0 <= value <= 10:
                raise ValueError(f"rating out of range: {value}")
            acc.setdefault((row["record_id"], row["system"], row["criterion"]), []).append(value)
    return {k: sum(v) / len(v) for k, v in acc.items()}


def agreement(rows: list[dict], ratings: dict[tuple[str, str, str], float]) -> dict:
    """Spearman and Kendall tau-b between judge scores and human ratings, for each criterion."""
    out = {}
    for c in CRITERIA:
        judge_vals, human_vals = [], []
        for r in rows:
            key = (r["record_id"], r["system"], c)
            if r.get("judge") and key in ratings:
                judge_vals.append(r["judge"]["scores"][c])
                human_vals.append(ratings[key])
        if len(judge_vals) >= 3:
            out[c] = {"n": len(judge_vals), "spearman": round(spearman(judge_vals, human_vals), 3),
                      "kendall_tau_b": round(kendall_tau_b(judge_vals, human_vals), 3)}
        else:
            out[c] = {"n": len(judge_vals), "spearman": None, "kendall_tau_b": None}
    return out
