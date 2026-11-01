"""Read and update the JSON application config."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from unityscraper.core.paths import CONFIG_PATH


def read_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    """Return the config, or an empty dict when it is missing or unreadable."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def update_config(updates: dict[str, Any], path: Path = CONFIG_PATH) -> dict[str, Any]:
    """Merge ``updates`` into the config and write it atomically; returns the result."""
    config = read_config(path)
    config.update(updates)
    path.parent.mkdir(parents=True, exist_ok=True)
    staging = path.with_suffix(path.suffix + ".tmp")
    staging.write_text(json.dumps(config, indent=2), encoding="utf-8")
    staging.replace(path)
    return config
