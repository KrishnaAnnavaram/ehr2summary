import json

import pytest

from ehr2summary.records import Record, age_group, build_record, pseudonym, read_records, select_admissions, write_jsonl
from ehr2summary.tables import TableError, load_tables, read_table


def test_icd9_codes_keep_leading_zeros(tables):
    assert "0389" in set(tables.diagnoses["icd9_code"])
    assert "0389" in set(tables.d_diagnoses["icd9_code"])


def test_upper_case_columns_are_accepted(tmp_path):
    (tmp_path / "D_ICD_DIAGNOSES.csv").write_text("ICD9_CODE,SHORT_TITLE,LONG_TITLE\n0389,Septicemia NOS,Unspecified septicemia\n")
    df = read_table(tmp_path, "D_ICD_DIAGNOSES", {"icd9_code", "long_title"})
    assert list(df["icd9_code"]) == ["0389"]


def test_missing_table_and_missing_columns(tmp_path, data_dir):
    with pytest.raises(TableError, match="not found"):
        load_tables(tmp_path)
    (tmp_path / "PATIENTS.csv").write_text("subject_id,gender\n1,M\n")
    with pytest.raises(TableError, match="lacks columns"):
        read_table(tmp_path, "PATIENTS", {"subject_id", "gender", "dob"})


def test_records_use_descriptions_and_procedure_codes(records):
    rec = next(r for r in records if r.procedures)
    assert all(not d.text.isdigit() for d in rec.diagnoses)
    assert rec.procedures[0].ref == "px1" and rec.procedures[0].code
    assert any(r.medications for r in records) and any(r.labs for r in records)
    assert any(r.reference_note for r in records)


def test_unknown_code_is_kept_and_flagged(tables):
    hadm = int(tables.diagnoses.loc[tables.diagnoses["icd9_code"] == "7999", "hadm_id"].iloc[0])
    rec = build_record(tables, hadm, salt="s", synthetic=True, max_items=25, max_labs=5)
    assert "7999" in rec.unknown_codes
    assert any("no description" in d.text for d in rec.diagnoses)


def test_prompt_view_has_no_identifiers_dates_or_reference(records, tables):
    rec = records[0]
    text = rec.prompt_json()
    assert rec.record_id.startswith("r-")
    assert "2150" not in text and "admittime" not in text
    for sid in tables.admissions["subject_id"].astype(str):
        assert f'"{sid}"' not in text
    assert "reference_note" not in json.loads(text)


def test_pseudonym_is_stable_and_salted():
    assert pseudonym(100007, "a") == pseudonym(100007, "a")
    assert pseudonym(100007, "a") != pseudonym(100007, "b")


@pytest.mark.parametrize("years, group", [(10, "<18"), (30, "18-39"), (50, "40-64"), (70, "65-79"), (85, "80+"),
                                          (300, "80+")])
def test_age_groups(years, group):
    assert age_group(years) == group


def test_selection_is_seeded_and_truncation_is_recorded(tables):
    a, b, c = (select_admissions(tables, 5, s) for s in (1, 1, 2))
    assert a == b and a != c and a == sorted(a)
    hadm = int(tables.admissions["hadm_id"].iloc[0])
    rec = build_record(tables, hadm, salt="s", synthetic=True, max_items=1, max_labs=0)
    assert len(rec.diagnoses) == 1 and rec.truncated["diagnoses"] >= 1 and rec.labs == []


def test_records_round_trip(tmp_path, records):
    write_jsonl(tmp_path / "r.jsonl", records)
    back = read_records(tmp_path / "r.jsonl")
    assert back == records and isinstance(back[0], Record)
