from pathlib import Path

import pytest

from ehr2summary.faithfulness import FaithfulnessChecker
from ehr2summary.records import build_records, lexicon, select_admissions
from ehr2summary.synthetic import write_synthetic
from ehr2summary.tables import load_tables


@pytest.fixture(scope="session")
def data_dir(tmp_path_factory) -> Path:
    return write_synthetic(tmp_path_factory.mktemp("mimic"), n_admissions=24, seed=7)


@pytest.fixture(scope="session")
def tables(data_dir):
    return load_tables(data_dir)


@pytest.fixture(scope="session")
def records(tables):
    ids = select_admissions(tables, 24, seed=0)
    return build_records(tables, ids, salt="test", synthetic=True, max_items=25, max_labs=12)


@pytest.fixture(scope="session")
def checker(tables):
    return FaithfulnessChecker(lexicon(tables))
