"""Record builder: one admission -> one structured, de-identified record with code descriptions.

The record is the only input of the generator and of the judge. Each item has a reference id
(``dx1``, ``px2``, ``med3``, ``lab1``) that a summary statement cites.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

from .tables import Tables

Kind = Literal["diagnosis", "procedure", "medication", "lab"]
PREFIX = {"diagnosis": "dx", "procedure": "px", "medication": "med", "lab": "lab"}
ABNORMAL_FLAGS = {"abnormal", "delta"}


class Item(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ref: str
    kind: Kind
    code: str | None = None
    text: str
    detail: str = ""


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid")

    record_id: str = Field(pattern=r"^r-[0-9a-f]{12}$")
    synthetic: bool
    admission_type: str
    discharge_location: str
    sex: str
    age_group: str
    length_of_stay_days: float
    died_in_hospital: bool
    diagnoses: list[Item] = Field(default_factory=list)
    procedures: list[Item] = Field(default_factory=list)
    medications: list[Item] = Field(default_factory=list)
    labs: list[Item] = Field(default_factory=list)
    truncated: dict[str, int] = Field(default_factory=dict)
    unknown_codes: list[str] = Field(default_factory=list)
    reference_note: str | None = None

    def items(self) -> dict[str, Item]:
        return {i.ref: i for i in [*self.diagnoses, *self.procedures, *self.medications, *self.labs]}

    def prompt_view(self) -> dict:
        """The fields that a model sees: no reference note, no source ids, no dates."""
        return self.model_dump(exclude={"reference_note", "synthetic", "unknown_codes"})

    def prompt_json(self) -> str:
        return json.dumps(self.prompt_view(), indent=1)


def pseudonym(hadm_id: int, salt: str) -> str:
    return "r-" + hashlib.sha256(f"{salt}:{int(hadm_id)}".encode()).hexdigest()[:12]


def age_group(years: float) -> str:
    if years >= 89 or years < 0:  # MIMIC shifts the birth date of patients over 89
        return "80+"
    if years < 18:
        return "<18"
    if years < 40:
        return "18-39"
    if years < 65:
        return "40-64"
    if years < 80:
        return "65-79"
    return "80+"


def select_admissions(tables: Tables, n: int, seed: int) -> list[int]:
    """A seeded sample of admissions that have at least one diagnosis code, in a stable order."""
    with_dx = set(tables.diagnoses["hadm_id"].dropna().astype(int))
    ids = sorted(int(h) for h in tables.admissions["hadm_id"].dropna().astype(int) if int(h) in with_dx)
    if n >= len(ids):
        return ids
    rng = np.random.default_rng(seed)
    return sorted(int(x) for x in rng.choice(ids, size=n, replace=False))


def _coded(rows: pd.DataFrame, dictionary: pd.DataFrame, kind: Kind, limit: int) -> tuple[list[Item], int, list[str]]:
    titles = dict(zip(dictionary["icd9_code"].astype(str), dictionary["long_title"].astype(str)))
    rows = rows.sort_values("seq_num")
    items, unknown = [], []
    seen: set[str] = set()
    for code in rows["icd9_code"].dropna().astype(str):
        if code in seen:
            continue
        seen.add(code)
        text = titles.get(code)
        if text is None:
            unknown.append(code)
            text = f"ICD-9 code {code} (no description in the dictionary)"
        items.append(Item(ref=f"{PREFIX[kind]}{len(items) + 1}", kind=kind, code=code, text=text))
    dropped = max(0, len(items) - limit)
    return items[:limit], dropped, unknown


def _medications(tables: Tables, hadm_id: int, limit: int) -> tuple[list[Item], int]:
    if tables.prescriptions is None:
        return [], 0
    rx = tables.prescriptions[tables.prescriptions["hadm_id"] == hadm_id]
    if "startdate" in rx.columns:
        rx = rx.sort_values("startdate", kind="stable")
    items: list[Item] = []
    seen: dict[str, Item] = {}
    for _, r in rx.iterrows():
        drug = str(r["drug"]).strip()
        if not drug or drug.lower() == "nan":
            continue
        key = drug.lower()
        route = str(r.get("route", "") or "").strip()
        route = "" if route.lower() == "nan" else route
        if key in seen:
            if route and route not in seen[key].detail:
                seen[key].detail = ", ".join(x for x in [seen[key].detail, route] if x)
            continue
        item = Item(ref=f"med{len(items) + 1}", kind="medication", text=drug, detail=route)
        seen[key] = item
        items.append(item)
    dropped = max(0, len(items) - limit)
    return items[:limit], dropped


def _labs(tables: Tables, hadm_id: int, limit: int) -> tuple[list[Item], int]:
    if tables.labevents is None or tables.d_labitems is None or limit == 0:
        return [], 0
    ev = tables.labevents[(tables.labevents["hadm_id"] == hadm_id)]
    ev = ev[ev["flag"].astype(str).str.lower().isin(ABNORMAL_FLAGS) & ev["valuenum"].notna()]
    if ev.empty:
        return [], 0
    labels = dict(zip(tables.d_labitems["itemid"], tables.d_labitems["label"].astype(str)))
    last = ev.sort_values("charttime").groupby("itemid").tail(1).sort_values("itemid")
    items = []
    for _, r in last.iterrows():
        unit = "" if pd.isna(r["valueuom"]) else str(r["valueuom"])
        items.append(Item(ref=f"lab{len(items) + 1}", kind="lab", text=labels.get(r["itemid"], f"lab item {r['itemid']}"),
                          detail=f"last abnormal value {float(r['valuenum']):g} {unit}".strip()))
    dropped = max(0, len(items) - limit)
    return items[:limit], dropped


def build_record(tables: Tables, hadm_id: int, *, salt: str, synthetic: bool, max_items: int, max_labs: int) -> Record:
    adm = tables.admissions[tables.admissions["hadm_id"] == hadm_id]
    if adm.empty:
        raise KeyError(f"admission {hadm_id} not found")
    a = adm.iloc[0]
    pat = tables.patients[tables.patients["subject_id"] == a["subject_id"]]
    admit, disch = pd.to_datetime(a["admittime"]), pd.to_datetime(a["dischtime"])
    sex, years = "unknown", -1.0
    if not pat.empty:
        sex = {"M": "male", "F": "female"}.get(str(pat.iloc[0]["gender"]).upper(), "unknown")
        dob = pd.to_datetime(pat.iloc[0]["dob"])
        years = (admit.year - dob.year) - ((admit.month, admit.day) < (dob.month, dob.day))
    dx, dx_drop, dx_unknown = _coded(tables.diagnoses[tables.diagnoses["hadm_id"] == hadm_id], tables.d_diagnoses,
                                     "diagnosis", max_items)
    px, px_drop, px_unknown = _coded(tables.procedures[tables.procedures["hadm_id"] == hadm_id], tables.d_procedures,
                                     "procedure", max_items)
    meds, med_drop = _medications(tables, hadm_id, max_items)
    labs, lab_drop = _labs(tables, hadm_id, max_labs)
    note = None
    if tables.notes is not None:
        n = tables.notes[(tables.notes["hadm_id"] == hadm_id) &
                         (tables.notes["category"].astype(str).str.lower() == "discharge summary")]
        if not n.empty:
            note = str(n.iloc[0]["text"])
    died = bool(int(a.get("hospital_expire_flag", 0) or 0)) if "hospital_expire_flag" in a else False
    truncated = {k: v for k, v in {"diagnoses": dx_drop, "procedures": px_drop, "medications": med_drop,
                                   "labs": lab_drop}.items() if v}
    return Record(
        record_id=pseudonym(hadm_id, salt), synthetic=synthetic,
        admission_type=str(a["admission_type"]).lower(), discharge_location=str(a["discharge_location"]).lower(),
        sex=sex, age_group=age_group(years), length_of_stay_days=round((disch - admit).total_seconds() / 86400, 1),
        died_in_hospital=died, diagnoses=dx, procedures=px, medications=meds, labs=labs, truncated=truncated,
        unknown_codes=dx_unknown + px_unknown, reference_note=note,
    )


def build_records(tables: Tables, hadm_ids: list[int], *, salt: str, synthetic: bool, max_items: int,
                  max_labs: int) -> list[Record]:
    return [build_record(tables, h, salt=salt, synthetic=synthetic, max_items=max_items, max_labs=max_labs)
            for h in hadm_ids]


def lexicon(tables: Tables) -> dict[str, set[str]]:
    """All diagnosis titles, procedure titles and drug names of the data set, for the hallucination check."""
    def titles(df: pd.DataFrame) -> set[str]:
        return {str(t) for t in df["long_title"].dropna()}

    drugs = set()
    if tables.prescriptions is not None:
        drugs = {str(d).strip() for d in tables.prescriptions["drug"].dropna() if str(d).strip()}
    return {"diagnosis": titles(tables.d_diagnoses), "procedure": titles(tables.d_procedures), "medication": drugs}


def write_jsonl(path: Path, rows: list[BaseModel]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(r.model_dump_json() + "\n" for r in rows), encoding="utf-8")


def read_records(path: Path) -> list[Record]:
    return [Record.model_validate_json(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]
