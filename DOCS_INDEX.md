# Documentation

## Users

- [README](README.md) - product overview, installation, core workflows, and CLI
- [Backup Manager](BACKUP_MANAGER.md) - layouts, installation, exports, FTP,
  verification, and external conversion
- [Knowledge Sources](KNOWLEDGE_SOURCES.md) - imports, provenance, caching, and
  source licensing
- [Advanced Features](ADVANCED_FEATURES.md) - rate limits, resume, diagnostics,
  portable mode, API, and conversion
- [REST API](API.md) - authentication, endpoints, configuration, and safety
- [Linux Support](LINUX.md) - installation, XDG storage, desktop integration,
  uninstallation, and troubleshooting
- [Project Status](PROJECT_STATUS.md) - completed work, boundaries, and roadmap
- [Changelog](CHANGELOG.md) - release history

## Contributors

- [Architecture](ARCHITECTURE.md) - modules, layers, schemas, data flows, and
  packaging
- [Contributing](CONTRIBUTING.md) - environment, tests, PR expectations, and
  adapter rules
- [Security](SECURITY.md) - private reporting and operational boundaries
- [Community Standards](CODE_OF_CONDUCT.md) - participation expectations

## Validation

```powershell
python -m pip install -r requirements.txt -r requirements-dev.txt
python -m ruff check .
python -m compileall -q .
python tests.py
```

Windows packaging:

```powershell
powershell -ExecutionPolicy Bypass -File .\build_windows.ps1
```

Linux packaging:

```bash
./build_linux.sh
```
