# UnityScraper Documentation

## Start Here

- [README.md](README.md) - installation, launch, and core workflows
- [PROJECT_STATUS.md](PROJECT_STATUS.md) - current implementation and boundaries
- [KNOWLEDGE_SOURCES.md](KNOWLEDGE_SOURCES.md) - knowledge adapters, provenance,
  caching, source licenses, and DAT imports
- [BACKUP_MANAGER.md](BACKUP_MANAGER.md) - local inventory, STFS installation,
  exports, verification, FTP, and external conversion

## Additional Reference

- [ADVANCED_FEATURES.md](ADVANCED_FEATURES.md) - legacy scraper and download tools
- [INTEGRATION_SUMMARY.md](INTEGRATION_SUMMARY.md) - original feature integration
- [BACKGROUND_INSTALL.md](BACKGROUND_INSTALL.md) - dark-theme background packaging

## Developer Map

| Area | Primary modules |
| --- | --- |
| XboxUnity collection | `main.py`, `database.py`, `resume.py` |
| Desktop shell | `desktop_app.py`, `modern_gui.py` |
| Knowledge model | `knowledge_base.py`, `knowledge_service.py` |
| Source adapters | `consolemods_adapters.py`, `wiki_adapters.py`, `dat_adapters.py` |
| Source synchronization | `knowledge_sources.py`, `knowledge_sync.py` |
| Backup engine | `backup_manager.py`, `backup_service.py` |
| Backup desktop page | `backup_gui.py` |
| Tests | `tests.py` |

Run the complete offline test suite with:

```powershell
python tests.py
```

Build the Windows executable with:

```powershell
powershell -ExecutionPolicy Bypass -File .\build_windows.ps1
```
