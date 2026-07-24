"""Generate a minimal CycloneDX SBOM from the active Python environment."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app_version import APP_VERSION  # noqa: E402


def build_sbom() -> dict:
    components = []
    for distribution in sorted(
        importlib.metadata.distributions(),
        key=lambda item: (item.metadata.get("Name") or "").casefold(),
    ):
        name = distribution.metadata.get("Name")
        if not name:
            continue
        components.append(
            {
                "type": "library",
                "name": name,
                "version": distribution.version,
                "purl": f"pkg:pypi/{name.casefold().replace('_', '-')}@{distribution.version}",
            }
        )
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "version": 1,
        "metadata": {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "component": {
                "type": "application",
                "name": "UnityScraper",
                "version": APP_VERSION,
            },
        },
        "components": components,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("UnityScraper-SBOM.cdx.json"))
    args = parser.parse_args()
    args.output.write_text(json.dumps(build_sbom(), indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
