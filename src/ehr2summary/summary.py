"""The summary schema: fixed sections, each a list of statements that cite record items."""

from __future__ import annotations

import json
import re

from pydantic import BaseModel, ConfigDict, Field, ValidationError

SECTIONS = ("diagnoses", "procedures", "hospital_course", "medications", "follow_up")
NOT_DOCUMENTED = "Not documented in the record."


class Statement(BaseModel):
    model_config = ConfigDict(extra="ignore")

    text: str = Field(min_length=1, max_length=1200)
    refs: list[str] = Field(default_factory=list)


class Summary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    record_id: str
    system: str
    sections: dict[str, list[Statement]]

    def statements(self) -> list[tuple[str, Statement]]:
        return [(s, st) for s in SECTIONS for st in self.sections.get(s, [])]

    def text(self) -> str:
        parts = []
        for s in SECTIONS:
            body = " ".join(st.text for st in self.sections.get(s, [])) or NOT_DOCUMENTED
            parts.append(f"{s.replace('_', ' ').title()}: {body}")
        return "\n".join(parts)


class SummaryFormatError(ValueError):
    pass


def extract_json_object(text: str) -> dict:
    text = re.sub(r"```(?:json)?", "", text)
    dec = json.JSONDecoder()
    for m in re.finditer(r"\{", text):
        try:
            obj, _ = dec.raw_decode(text[m.start():])
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            return obj
    raise SummaryFormatError("no JSON object in the reply")


def parse_summary(reply: str, record_id: str, system: str) -> Summary:
    """Read a model reply into a Summary. Unknown section names are an error, missing ones are empty."""
    obj = extract_json_object(reply)
    sections = obj.get("sections", obj)
    if not isinstance(sections, dict):
        raise SummaryFormatError("'sections' must be an object")
    unknown = set(sections) - set(SECTIONS)
    if unknown:
        raise SummaryFormatError(f"unknown sections {sorted(unknown)}")
    norm: dict[str, list] = {}
    for name in SECTIONS:
        value = sections.get(name, [])
        if isinstance(value, str):
            value = [{"text": value, "refs": []}]
        norm[name] = value
    try:
        return Summary(record_id=record_id, system=system, sections=norm)
    except ValidationError as exc:
        raise SummaryFormatError(str(exc).splitlines()[0]) from exc
