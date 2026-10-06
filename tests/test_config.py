import tomllib
from pathlib import Path

import pytest

from ehr2summary.config import ConfigError, Settings


def test_settings_from_env():
    s = Settings.from_env({"EHR2SUMMARY_JUDGE_PROVIDER": "openai", "EHR2SUMMARY_JUDGE_MODEL": "llama3.1:70b",
                           "EHR2SUMMARY_JUDGE_SAMPLES": "3", "EHR2SUMMARY_ALLOW_SELF_JUDGE": "yes"})
    assert s.judge.identity == "openai:llama3.1:70b" and s.judge_samples == 3 and s.allow_self_judge
    assert s.generator.provider == "offline" and not s.allow_remote_records


@pytest.mark.parametrize("env", [{"EHR2SUMMARY_JUDGE_PROVIDER": "magic"}, {"EHR2SUMMARY_SEED": "x"},
                                 {"EHR2SUMMARY_JUDGE_SAMPLES": "0"}, {"EHR2SUMMARY_ALLOW_SELF_JUDGE": "maybe"}])
def test_bad_settings(env):
    with pytest.raises(ConfigError):
        Settings.from_env(env)


def test_heavy_frameworks_are_extras_only():
    meta = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text(encoding="utf-8"))
    core = " ".join(meta["project"]["dependencies"])
    assert "torch" not in core and "transformers" not in core
    assert "torch>=2.1" in meta["project"]["optional-dependencies"]["hf"]
