"""Load MIMIC-III style CSV tables with a column check.

- Column names are made lower case (the demo uses lower case, the full release upper case).
- ICD-9 codes are read as text, so leading zeros stay ('0389' is not 389).
- A required table that is missing, or a table without its required columns, is an error.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

REQUIRED: dict[str, set[str]] = {
    "ADMISSIONS": {"subject_id", "hadm_id", "admittime", "dischtime", "admission_type", "discharge_location"},
    "PATIENTS": {"subject_id", "gender", "dob"},
    "DIAGNOSES_ICD": {"hadm_id", "seq_num", "icd9_code"},
    "D_ICD_DIAGNOSES": {"icd9_code", "short_title", "long_title"},
    "PROCEDURES_ICD": {"hadm_id", "seq_num", "icd9_code"},
    "D_ICD_PROCEDURES": {"icd9_code", "short_title", "long_title"},
}
OPTIONAL: dict[str, set[str]] = {
    "PRESCRIPTIONS": {"hadm_id", "drug", "route"},
    "LABEVENTS": {"hadm_id", "itemid", "charttime", "valuenum", "valueuom", "flag"},
    "D_LABITEMS": {"itemid", "label"},
    "NOTEEVENTS": {"hadm_id", "category", "text"},
}
TEXT_COLUMNS = {"icd9_code", "drug", "route", "flag", "category", "text", "label", "valueuom", "dose_val_rx",
                "dose_unit_rx", "short_title", "long_title", "admission_type", "discharge_location", "gender"}


class TableError(ValueError):
    pass


@dataclass
class Tables:
    admissions: pd.DataFrame
    patients: pd.DataFrame
    diagnoses: pd.DataFrame
    d_diagnoses: pd.DataFrame
    procedures: pd.DataFrame
    d_procedures: pd.DataFrame
    prescriptions: pd.DataFrame | None = None
    labevents: pd.DataFrame | None = None
    d_labitems: pd.DataFrame | None = None
    notes: pd.DataFrame | None = None


def _find(folder: Path, name: str) -> Path | None:
    for candidate in (f"{name}.csv", f"{name.lower()}.csv", f"{name}.csv.gz", f"{name.lower()}.csv.gz"):
        p = folder / candidate
        if p.exists():
            return p
    return None


def read_table(folder: Path, name: str, required: set[str]) -> pd.DataFrame:
    path = _find(folder, name)
    if path is None:
        raise TableError(f"table {name} not found in {folder}")
    head = pd.read_csv(path, nrows=0)
    cols = {c: c.lower() for c in head.columns}
    dtypes = {orig: str for orig, low in cols.items() if low in TEXT_COLUMNS}
    df = pd.read_csv(path, dtype=dtypes, keep_default_na=True).rename(columns=cols)
    missing = required - set(df.columns)
    if missing:
        raise TableError(f"table {name} lacks columns {sorted(missing)}")
    if "icd9_code" in df.columns:
        df["icd9_code"] = df["icd9_code"].astype("string").str.strip()
    return df


def load_tables(folder: Path) -> Tables:
    folder = Path(folder)
    req = {name: read_table(folder, name, cols) for name, cols in REQUIRED.items()}
    opt = {}
    for name, cols in OPTIONAL.items():
        opt[name] = read_table(folder, name, cols) if _find(folder, name) else None
    return Tables(
        admissions=req["ADMISSIONS"], patients=req["PATIENTS"], diagnoses=req["DIAGNOSES_ICD"],
        d_diagnoses=req["D_ICD_DIAGNOSES"], procedures=req["PROCEDURES_ICD"], d_procedures=req["D_ICD_PROCEDURES"],
        prescriptions=opt["PRESCRIPTIONS"], labevents=opt["LABEVENTS"], d_labitems=opt["D_LABITEMS"],
        notes=opt["NOTEEVENTS"],
    )
