"""Lab Charter thresholds: one YAML file the gates, the Skeptic and the room document share."""

from __future__ import annotations

import copy
import shutil
from pathlib import Path
from typing import Any

import yaml

from stratlab.config import get_stratlab_home

DEFAULT_CHARTER = Path(__file__).with_name("charter_default.yaml")


def charter_path() -> Path:
    return get_stratlab_home() / "charter.yaml"


def ensure_charter() -> Path:
    p = charter_path()
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(DEFAULT_CHARTER, p)
    return p


def load_charter(path: Path | str | None = None, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    """Defaults, then the user's charter file, then `section.key=value` overrides."""
    charter = yaml.safe_load(DEFAULT_CHARTER.read_text())
    src = Path(path) if path else charter_path()
    if src.exists():
        user = yaml.safe_load(src.read_text()) or {}
        for section, values in user.items():
            if isinstance(values, dict):
                charter.setdefault(section, {}).update(values)
    charter = copy.deepcopy(charter)
    for key, value in (overrides or {}).items():
        section, _, field = key.partition(".")
        if section not in charter or field not in charter[section]:
            raise ValueError(f"unknown charter setting '{key}'")
        charter[section][field] = type(charter[section][field])(value)
    return charter
