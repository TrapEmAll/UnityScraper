"""Verify that every release-version source agrees."""

from __future__ import annotations

import argparse
import json
import re
import xml.etree.ElementTree as element_tree
from pathlib import Path

from packaging.version import Version

ROOT = Path(__file__).resolve().parents[1]


def read_versions() -> dict[str, str]:
    app_text = (ROOT / "unityscraper/core/version.py").read_text(encoding="utf-8")
    app_match = re.search(r'^APP_VERSION\s*=\s*"([^"]+)"', app_text, re.MULTILINE)
    if not app_match:
        raise RuntimeError("APP_VERSION was not found in unityscraper/core/version.py")

    version_data = json.loads((ROOT / "VERSION").read_text(encoding="utf-8"))
    pyproject_text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    project_match = re.search(
        r'^\s*version\s*=\s*"([^"]+)"',
        pyproject_text,
        re.MULTILINE,
    )
    if not project_match:
        raise RuntimeError("project.version was not found in pyproject.toml")

    metainfo = element_tree.parse(
        ROOT / "packaging/linux/io.github.trapemall.UnityScraper.metainfo.xml"
    ).getroot()
    release = metainfo.find("./releases/release")
    if release is None or not release.get("version"):
        raise RuntimeError("A release version was not found in Linux AppStream metadata")

    return {
        "unityscraper/core/version.py": app_match.group(1),
        "VERSION": str(version_data["version"]),
        "pyproject.toml": project_match.group(1),
        "Linux AppStream metadata": str(release.get("version")),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--tag",
        help="Optional release tag to compare, such as v0.10.0-beta.1",
    )
    args = parser.parse_args()

    versions = read_versions()
    normalized = {name: Version(value) for name, value in versions.items()}
    expected = next(iter(normalized.values()))
    mismatches = {
        name: versions[name]
        for name, value in normalized.items()
        if value != expected
    }
    if mismatches:
        details = ", ".join(f"{name}={value}" for name, value in versions.items())
        raise SystemExit(f"Version sources disagree: {details}")

    if args.tag and Version(args.tag.removeprefix("v")) != expected:
        raise SystemExit(
            f"Release tag {args.tag} does not match application version {expected}"
        )

    print(f"Version sources agree: {expected}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
