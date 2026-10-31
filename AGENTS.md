# AGENTS.md

UnityScraper is a desktop-first Python 3.10+ application that manages an Xbox 360
library: XboxUnity title updates and covers, a sourced knowledge base, local and
FTP backups, profiles and saves, and package (STFS/SVOD/GDF/XISO) tooling. SQLite
is the durable local store. See [ARCHITECTURE.md](ARCHITECTURE.md) for the full
module map and data flows.

## Setup

```bash
python -m venv .venv
.venv/bin/python -m pip install -r requirements.txt -r requirements-dev.txt
```

On Windows use `.\.venv\Scripts\python.exe`. `make install` does the same on
Linux and macOS.

## Validate a change

Run these from the repository root (the tests import top-level modules, so the
root must be the working directory):

```bash
python -m ruff check .
python -m compileall -q .
python scripts/check_version.py
python -m tests.test_unityscraper
python -m tests.test_integration
```

`make check` runs all five. CI runs the same steps on Windows, Linux and macOS
with Python 3.10 and 3.12. Run `sh -n` on any shell script you change.

## Layout

- `desktop_app.py`, `main.py`, `GUI.py`, `api.py`: supported top-level entry points.
- `unityscraper/app`: desktop, CLI and API adapters.
- `unityscraper/core`: paths, jobs, database contracts, version metadata.
- `unityscraper/domains`: feature-owned library, knowledge, backup, profile,
  package, collection, sync, tool and plugin modules. New code goes here.
- Top-level `*_service.py`, `*_manager.py` and `*_gui.py` modules are the legacy
  layer being moved into the package; keep their public names working.
- `tests/`: unittest suites. Each suite lists its test classes in `run_tests()`;
  add new classes there.

## Rules

- GUI pages, REST routes and CLI commands call domain use cases; they do not own
  filesystem, FTP, package or database behaviour.
- Schema migrations are additive and idempotent; existing user data must survive.
- Unit tests make no live XboxUnity or wiki requests; mock the network.
- XboxUnity URLs stay HTTP-only (that is what the service serves).
- File writes go to a `.partial` file, are verified with SHA-256, then published
  atomically. ZIP imports reject traversal, symlinks and oversized archives.
- Never add commercial game content, firmware, keys, leaked SDK material or
  circumvention tooling. Imported knowledge keeps its source, license and citations.
- Update the user documentation when commands, storage, schemas or UI workflows change.
- The version lives in `VERSION`, `unityscraper/core/version.py` and `pyproject.toml`;
  `scripts/check_version.py` enforces that they match.
