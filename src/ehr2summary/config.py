"""Settings from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping


class ConfigError(ValueError):
    pass


def _get(env: Mapping[str, str], name: str, default: str) -> str:
    v = env.get(name, "")
    return v.strip() if v and v.strip() else default


def _int(env, name, default, low, high) -> int:
    raw = _get(env, name, str(default))
    try:
        v = int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer, got {raw!r}") from exc
    if not low <= v <= high:
        raise ConfigError(f"{name} must be between {low} and {high}")
    return v


def _float(env, name, default, low, high) -> float:
    raw = _get(env, name, str(default))
    try:
        v = float(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be a number, got {raw!r}") from exc
    if not low <= v <= high:
        raise ConfigError(f"{name} must be between {low} and {high}")
    return v


def _bool(env, name, default: bool) -> bool:
    raw = _get(env, name, "true" if default else "false").lower()
    if raw not in {"true", "false", "1", "0", "yes", "no"}:
        raise ConfigError(f"{name} must be true or false")
    return raw in {"true", "1", "yes"}


@dataclass(frozen=True)
class ModelSettings:
    """One chat model endpoint: the generator or the judge."""

    provider: str = "offline"  # offline | openai | hf
    model: str = ""
    base_url: str = "http://localhost:11434/v1"
    api_key: str = ""
    timeout_s: float = 120.0

    @property
    def identity(self) -> str:
        return f"{self.provider}:{self.model or 'default'}"


@dataclass(frozen=True)
class Settings:
    data_dir: Path = Path("data/mimic-iii-demo")
    work_dir: Path = Path("runs")
    seed: int = 0
    n_records: int = 50
    max_items_per_section: int = 25
    max_labs: int = 12
    generator: ModelSettings = field(default_factory=ModelSettings)
    judge: ModelSettings = field(default_factory=ModelSettings)
    judge_samples: int = 1
    judge_temperature: float = 0.0
    allow_self_judge: bool = False
    allow_remote_records: bool = False
    id_salt: str = "ehr2summary"

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Settings":
        env = os.environ if env is None else env

        def model(prefix: str) -> ModelSettings:
            provider = _get(env, f"{prefix}_PROVIDER", "offline").lower()
            if provider not in {"offline", "openai", "hf"}:
                raise ConfigError(f"{prefix}_PROVIDER must be offline, openai or hf")
            return ModelSettings(
                provider=provider,
                model=_get(env, f"{prefix}_MODEL", ""),
                base_url=_get(env, f"{prefix}_BASE_URL", ModelSettings.base_url),
                api_key=_get(env, f"{prefix}_API_KEY", ""),
                timeout_s=_float(env, f"{prefix}_TIMEOUT_S", 120.0, 1, 1200),
            )

        return cls(
            data_dir=Path(_get(env, "EHR2SUMMARY_DATA_DIR", str(cls.data_dir))),
            work_dir=Path(_get(env, "EHR2SUMMARY_WORK_DIR", str(cls.work_dir))),
            seed=_int(env, "EHR2SUMMARY_SEED", 0, 0, 2**31 - 1),
            n_records=_int(env, "EHR2SUMMARY_N_RECORDS", 50, 1, 100000),
            max_items_per_section=_int(env, "EHR2SUMMARY_MAX_ITEMS", 25, 1, 500),
            max_labs=_int(env, "EHR2SUMMARY_MAX_LABS", 12, 0, 200),
            generator=model("EHR2SUMMARY_GENERATOR"),
            judge=model("EHR2SUMMARY_JUDGE"),
            judge_samples=_int(env, "EHR2SUMMARY_JUDGE_SAMPLES", 1, 1, 20),
            judge_temperature=_float(env, "EHR2SUMMARY_JUDGE_TEMPERATURE", 0.0, 0.0, 2.0),
            allow_self_judge=_bool(env, "EHR2SUMMARY_ALLOW_SELF_JUDGE", False),
            allow_remote_records=_bool(env, "EHR2SUMMARY_ALLOW_REMOTE_RECORDS", False),
            id_salt=_get(env, "EHR2SUMMARY_ID_SALT", cls.id_salt),
        )
