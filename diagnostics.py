"""Create a privacy-conscious diagnostics ZIP for bug reports."""

from __future__ import annotations

import json
import os
import platform
import shutil
import sqlite3
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app_paths import (
    BASE_DIR,
    CONFIG_PATH,
    DATABASE_PATH,
    DIAGNOSTICS_DIR,
    GUI_LOG_PATH,
    CLI_LOG_PATH,
    describe_storage,
    ensure_app_dirs,
    portable_mode_enabled,
)


SENSITIVE_CONFIG_KEYS = {
    "output_dir",
    "download_dir",
    "path",
    "proxy",
    "username",
    "password",
    "token",
    "api_key",
}


def _sanitize_config(value: Any) -> Any:
    """Remove paths, credentials, and other sensitive configuration values."""
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for key, child in value.items():
            lowered = key.lower()
            if any(sensitive in lowered for sensitive in SENSITIVE_CONFIG_KEYS):
                cleaned[key] = "<redacted>"
            else:
                cleaned[key] = _sanitize_config(child)
        return cleaned

    if isinstance(value, list):
        return [_sanitize_config(item) for item in value]

    return value


def _database_summary() -> dict[str, Any]:
    """Read schema and record counts without copying the user's full database."""
    if not DATABASE_PATH.exists():
        return {"exists": False}

    result: dict[str, Any] = {
        "exists": True,
        "size_bytes": DATABASE_PATH.stat().st_size,
        "tables": {},
    }

    with sqlite3.connect(DATABASE_PATH) as connection:
        tables = connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
            ORDER BY name
            """
        ).fetchall()

        for (table_name,) in tables:
            # Table names come from sqlite_master rather than user input.
            count = connection.execute(
                f'SELECT COUNT(*) FROM "{table_name}"'
            ).fetchone()[0]
            result["tables"][table_name] = count

        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        result["integrity_check"] = integrity

    return result


def create_diagnostics_bundle() -> Path:
    """Create and return a ZIP suitable for attaching to a bug report."""
    ensure_app_dirs()
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    destination = DIAGNOSTICS_DIR / f"UnityScraper-Diagnostics-{timestamp}.zip"

    system_info = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "python": sys.version,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "executable": Path(sys.executable).name,
        "frozen": bool(getattr(sys, "frozen", False)),
        "portable_mode": portable_mode_enabled(),
        "storage": describe_storage(),
        "database": _database_summary(),
    }

    with tempfile.TemporaryDirectory(prefix="unityscraper-diagnostics-") as temp_name:
        temp = Path(temp_name)
        (temp / "system.json").write_text(
            json.dumps(system_info, indent=2, default=str),
            encoding="utf-8",
        )

        if CONFIG_PATH.exists():
            try:
                config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
                sanitized = _sanitize_config(config)
                (temp / "config-sanitized.json").write_text(
                    json.dumps(sanitized, indent=2, default=str),
                    encoding="utf-8",
                )
            except (OSError, json.JSONDecodeError) as exc:
                (temp / "config-error.txt").write_text(str(exc), encoding="utf-8")

        for source in (GUI_LOG_PATH, CLI_LOG_PATH):
            if source.exists():
                # Keep the final 500 KiB so diagnostics do not become enormous.
                with source.open("rb") as stream:
                    stream.seek(max(0, source.stat().st_size - 500_000))
                    data = stream.read()
                (temp / source.name).write_bytes(data)

        with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in temp.iterdir():
                archive.write(path, path.name)

    return destination
