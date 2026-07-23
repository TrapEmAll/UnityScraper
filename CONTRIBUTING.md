# Contributing to UnityScraper

Thank you for helping improve Xbox 360 preservation tooling.

## Before You Start

- Search existing issues and pull requests.
- Use an issue for substantial behavior or schema changes.
- Keep commercial game content, firmware, encryption keys, leaked SDK
  material, and circumvention tooling outside the project.
- Confirm that any imported text, metadata, images, or code can legally be
  redistributed and preserve its attribution.

## Development Setup

UnityScraper requires Python 3.10 or newer.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements-dev.txt
```

Linux:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt -r requirements-dev.txt
```

Run the desktop application:

```powershell
.\.venv\Scripts\python.exe desktop_app.py
```

On Linux:

```bash
.venv/bin/python desktop_app.py
```

Run validation:

```powershell
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m compileall -q .
.\.venv\Scripts\python.exe tests.py
```

Replace `.\.venv\Scripts\python.exe` with `.venv/bin/python` on Linux. Validate
changed shell scripts with `sh -n`.

## Pull Requests

- Branch from the current `main`.
- Keep changes focused and retain existing user data compatibility.
- Add tests for parsing, migrations, filesystem operations, and failure paths.
- Do not make live XboxUnity or wiki requests in unit tests.
- Treat database migrations as additive unless a documented migration safely
  preserves existing data.
- Keep XboxUnity URLs HTTP-only; this reflects the service endpoints.
- Update user documentation when commands, storage, schemas, or UI workflows
  change.

## Source Adapters

Every knowledge adapter should:

1. Identify its source and stated license.
2. Rate-limit requests and cache raw responses.
3. Preserve source URL, revision, retrieval time, and citations.
4. Isolate partial failures in import-run records.
5. Retain conflicting claims instead of silently overwriting them.
6. Avoid downloading or redistributing copyrighted payloads.

## Reporting Security Problems

Do not open public issues for vulnerabilities involving arbitrary file writes,
archive traversal, credential exposure, or remote API access. Follow
[SECURITY.md](SECURITY.md).
