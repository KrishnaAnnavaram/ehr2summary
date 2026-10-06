"""Rule-based faithfulness check: every diagnosis, procedure and medicine named in a summary must be in the record.

The check matches the summary text against a lexicon of all titles and drug names of the data set
(longest phrase first). A matched term that is not an item of this record is unsupported. The check
also finds references to record items that do not exist and ICD-9 codes that are not in the record.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

from .records import Record
from .summary import Summary

_CODE = re.compile(r"\bICD-?9(?:-CM)?(?: code)?:?\s*([VE]?\d{2,4}(?:\.\d{1,2})?)", re.I)
KINDS = ("diagnosis", "procedure", "medication")


def norm(text: str) -> str:
    text = re.sub(r"[^a-z0-9]+", " ", text.lower())
    return f" {text.strip()} "


@dataclass
class FaithfulnessReport:
    record_id: str
    system: str
    mentions: int
    supported: int
    unsupported_terms: list[str] = field(default_factory=list)
    invalid_refs: list[str] = field(default_factory=list)
    unknown_codes: list[str] = field(default_factory=list)
    covered_items: int = 0
    record_items: int = 0

    @property
    def precision(self) -> float:
        """Share of named clinical entities that the record supports (1.0 if the summary names none)."""
        return self.supported / self.mentions if self.mentions else 1.0

    @property
    def recall(self) -> float:
        """Share of record diagnoses, procedures and medicines that the summary covers."""
        return self.covered_items / self.record_items if self.record_items else 1.0

    @property
    def hallucinated(self) -> bool:
        return bool(self.unsupported_terms or self.invalid_refs or self.unknown_codes)

    def to_dict(self) -> dict:
        d = asdict(self)
        d.update(precision=round(self.precision, 4), recall=round(self.recall, 4), hallucinated=self.hallucinated)
        return d


class FaithfulnessChecker:
    def __init__(self, lexicon: dict[str, set[str]], min_term_chars: int = 4):
        terms: dict[str, str] = {}
        for kind in KINDS:
            for t in lexicon.get(kind, set()):
                n = norm(t)
                if len(n.strip()) >= min_term_chars:
                    terms.setdefault(n, kind)
        # Longest first, so "acute on chronic heart failure" wins over "heart failure".
        self._terms = sorted(terms, key=len, reverse=True)

    def find_terms(self, text: str) -> list[str]:
        t = norm(text)
        found = []
        for term in self._terms:
            if term in t:
                found.append(term.strip())
                t = t.replace(term, " # ")
        return found

    def check(self, record: Record, summary: Summary) -> FaithfulnessReport:
        if summary.record_id != record.record_id:
            raise ValueError(f"summary {summary.record_id} does not belong to record {record.record_id}")
        items = record.items()
        record_terms = {norm(i.text).strip(): i.ref for i in items.values() if i.kind != "lab"}
        record_codes = {(i.code or "").replace(".", "") for i in items.values() if i.code}
        rep = FaithfulnessReport(record.record_id, summary.system, 0, 0)
        covered: set[str] = set()
        for _, st in summary.statements():
            for ref in st.refs:
                if ref not in items:
                    rep.invalid_refs.append(ref)
            for term in self.find_terms(st.text):
                rep.mentions += 1
                if term in record_terms:
                    rep.supported += 1
                    covered.add(record_terms[term])
                else:
                    rep.unsupported_terms.append(term)
            for code in _CODE.findall(st.text):
                if code.replace(".", "") not in record_codes:
                    rep.unknown_codes.append(code)
        clinical = [i for i in items.values() if i.kind != "lab"]
        rep.record_items = len(clinical)
        rep.covered_items = sum(1 for i in clinical if i.ref in covered)
        return rep
