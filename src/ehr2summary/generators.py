"""Summary generators.

- ``TemplateGenerator``: offline, deterministic baseline. Every statement comes from a record item.
- ``LLMGenerator``: any chat model, temperature 0, fixed seed, JSON reply, one retry with the error.
- ``HallucinationInjector`` and ``OmissionInjector``: controlled errors on top of another generator.
  They give known-bad summaries, so you can check that the evaluation finds the errors.
"""

from __future__ import annotations

import logging
import random
from typing import Protocol

from .llm import ChatModel, LLMError, check_privacy
from .prompts import generator_messages
from .records import Record
from .summary import NOT_DOCUMENTED, SECTIONS, Statement, Summary, SummaryFormatError, parse_summary

log = logging.getLogger(__name__)


class Generator(Protocol):
    name: str

    def generate(self, record: Record) -> Summary: ...


def _join(texts: list[str]) -> str:
    if len(texts) <= 1:
        return "".join(texts)
    return ", ".join(texts[:-1]) + " and " + texts[-1]


class TemplateGenerator:
    name = "template"

    def generate(self, record: Record) -> Summary:
        s: dict[str, list[Statement]] = {k: [] for k in SECTIONS}
        if record.diagnoses:
            main = record.diagnoses[0]
            s["diagnoses"].append(Statement(text=f"The principal diagnosis was {main.text.lower()}.", refs=[main.ref]))
            for d in record.diagnoses[1:]:
                s["diagnoses"].append(Statement(text=f"Secondary diagnosis: {d.text.lower()}.", refs=[d.ref]))
        for p in record.procedures:
            s["procedures"].append(Statement(text=f"Procedure: {p.text.lower()}.", refs=[p.ref]))
        course = (f"The patient, a {record.sex} in the age group {record.age_group}, had a "
                  f"{record.admission_type} admission of {record.length_of_stay_days:g} days.")
        s["hospital_course"].append(Statement(text=course, refs=[]))
        for lab in record.labs:
            s["hospital_course"].append(Statement(text=f"{lab.text}: {lab.detail}.", refs=[lab.ref]))
        if record.medications:
            s["medications"].append(Statement(
                text="Medicines given during the stay: " + _join([m.text for m in record.medications]) + ".",
                refs=[m.ref for m in record.medications]))
        if record.died_in_hospital:
            s["follow_up"].append(Statement(text="The patient died in hospital.", refs=[]))
        else:
            s["follow_up"].append(Statement(text=f"Discharge location: {record.discharge_location}.", refs=[]))
            if record.labs:
                s["follow_up"].append(Statement(text="Repeat the abnormal tests: " + _join([x.text for x in record.labs]) + ".",
                                                refs=[x.ref for x in record.labs]))
        for k in SECTIONS:
            if not s[k]:
                s[k].append(Statement(text=NOT_DOCUMENTED, refs=[]))
        return Summary(record_id=record.record_id, system=self.name, sections=s)


class LLMGenerator:
    def __init__(self, model: ChatModel, *, seed: int = 0, max_attempts: int = 2, allow_remote: bool = False):
        self.model = model
        self.name = f"llm:{model.identity}"
        self.seed, self.max_attempts, self.allow_remote = seed, max_attempts, allow_remote

    def generate(self, record: Record) -> Summary:
        check_privacy(self.model, record.synthetic, self.allow_remote)
        msgs = generator_messages(record)
        last = ""
        for attempt in range(1, self.max_attempts + 1):
            reply = self.model.complete(msgs, temperature=0.0, seed=self.seed, json_mode=True)
            try:
                # The record id comes from the record, never from the reply.
                return parse_summary(reply, record.record_id, self.name)
            except SummaryFormatError as exc:
                last = str(exc)
                log.info("summary reply not valid (attempt %d): %s", attempt, last)
                msgs = msgs + [{"role": "assistant", "content": reply[:6000]},
                               {"role": "user", "content": f"The reply was not valid: {last}. Reply with the JSON only."}]
        raise LLMError(f"no valid summary for {record.record_id} after {self.max_attempts} attempts: {last}")


class HallucinationInjector:
    """Adds ``n`` statements about diagnoses or medicines that are not in the record."""

    def __init__(self, base: Generator, lexicon: dict[str, set[str]], n: int = 2, seed: int = 0):
        self.base, self.lexicon, self.n, self.seed = base, lexicon, n, seed
        self.name = f"{base.name}+hallucination"

    def generate(self, record: Record) -> Summary:
        summary = self.base.generate(record)
        present = {i.text.lower() for i in record.items().values()}
        rng = random.Random(f"{self.seed}:{record.record_id}")
        pool = [("diagnoses", t) for t in sorted(self.lexicon.get("diagnosis", set())) if t.lower() not in present]
        pool += [("medications", t) for t in sorted(self.lexicon.get("medication", set())) if t.lower() not in present]
        for section, text in rng.sample(pool, k=min(self.n, len(pool))):
            ref = record.diagnoses[0].ref if record.diagnoses else ""
            sentence = (f"Secondary diagnosis: {text.lower()}." if section == "diagnoses"
                        else f"The patient also received {text}.")
            summary.sections[section].append(Statement(text=sentence, refs=[ref] if ref else []))
        summary.system = self.name
        return summary


class OmissionInjector:
    """Keeps only the first statement of each section."""

    def __init__(self, base: Generator):
        self.base = base
        self.name = f"{base.name}+omission"

    def generate(self, record: Record) -> Summary:
        summary = self.base.generate(record)
        summary.sections = {k: v[:1] for k, v in summary.sections.items()}
        if summary.sections.get("medications"):
            st = summary.sections["medications"][0]
            if st.refs:
                first = record.items()[st.refs[0]]
                summary.sections["medications"] = [Statement(text=f"Medicines given during the stay: {first.text}.",
                                                             refs=[first.ref])]
        summary.system = self.name
        return summary
