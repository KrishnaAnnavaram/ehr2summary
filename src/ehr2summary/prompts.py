"""Prompt text for the generator and the judge. The generator prompt has no rubric in it."""

from __future__ import annotations

from .records import Record
from .summary import SECTIONS, Summary

_SHAPE = "{\"sections\": {" + ", ".join(f'"{s}": [...]' for s in SECTIONS) + "}}"
GENERATOR_SYSTEM = (
    "You write hospital discharge summaries from a structured, de-identified record.\n"
    "Rules:\n"
    "- Use only facts in the record. Do not add diagnoses, procedures, medicines, test results or events.\n"
    '- If the record has no information for a section, write one statement: "Not documented in the record."\n'
    '- Each statement lists the ids of the record items that support it in "refs" (for example ["dx1", "med2"]).\n'
    "- Use the descriptions in the record. Do not show ICD-9 codes without their description.\n"
    f"- Reply with JSON only: {_SHAPE}\n"
    '  where each list item is {"text": "...", "refs": ["..."]}.'
)

RUBRIC: dict[str, str] = {
    "clinical_accuracy": (
        "Are all diagnoses, procedures, medicines and results in the summary supported by the record? "
        "10 = every fact is supported. 7 = one minor unsupported detail. 4 = an unsupported diagnosis or medicine. "
        "0 = mostly unsupported."
    ),
    "completeness": (
        "Does the summary cover the important record items: main diagnoses, procedures, medicines and abnormal "
        "results? 10 = all important items. 5 = about half. 0 = almost none."
    ),
    "readability": (
        "Is the summary clear, well organized and in correct clinical English? 10 = clear and concise. "
        "5 = understandable but repetitive or badly ordered. 0 = hard to read."
    ),
    "actionability": (
        "Does the summary give a receiving clinician what they need: discharge location, medicines to continue, "
        "results that need follow-up? 10 = all of these. 5 = some. 0 = none."
    ),
}
CRITERIA = tuple(RUBRIC)


def generator_messages(record: Record) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": GENERATOR_SYSTEM},
        {"role": "user", "content": f"Record:\n{record.prompt_json()}"},
    ]


def _judge_context(record: Record, summary: Summary) -> str:
    return f"Source record:\n{record.prompt_json()}\n\nSummary to evaluate:\n{summary.text()}"


def judge_messages(record: Record, summary: Summary) -> list[dict[str, str]]:
    rubric = "\n".join(f"- {k}: {v}" for k, v in RUBRIC.items())
    system = (
        "You are a clinical reviewer. Compare the summary with the source record and score it on each criterion "
        "from 0 to 10.\n" + rubric + "\nReply with JSON only: "
        '{"clinical_accuracy": {"score": <0-10>, "reason": "..."}, "completeness": {...}, '
        '"readability": {...}, "actionability": {...}}'
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": _judge_context(record, summary)}]


def single_criterion_messages(record: Record, summary: Summary, criterion: str) -> list[dict[str, str]]:
    system = (
        "You are a clinical reviewer. Compare the summary with the source record.\n"
        f"Criterion: {criterion}. {RUBRIC[criterion]}\nReply with one integer from 0 to 10 and nothing else."
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": _judge_context(record, summary)}]
