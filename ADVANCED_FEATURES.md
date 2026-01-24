# UnityScraper Advanced Features - Quick Reference

## 🚀 Quick Start

### GUI Mode
```bash
python GUI.py
```
- Full visual interface with all new features
- Language selector for 5 languages
- Filters, queue viewer, integrity checker

### API Mode
```bash
python main.py --api-mode --api-port 8000
```
- REST API available at `http://127.0.0.1:8000/api/`
- 12 endpoints for full control

### CLI Mode
```bash
python main.py [--options]
```

---

## 🌍 Feature Quick Reference

| Feature | How to Use | Where |
|---------|-----------|-------|
| **Multi-Language** | Click language dropdown | GUI dropdown |
| **File Verification** | Click "Verify Files" button | GUI button |
| **Check Updates** | Click "Check Updates" button | GUI button |
| **Download Queue** | Click "View Queue" button | GUI button |
| **Filters** | Use status/date dropdowns | GUI filter section |
| **API Server** | `python main.py --api-mode` | Terminal |

---

## 🔧 Configuration

### Via GUI:
- Workers: Spinbox (1-16)
- Rate Limit: Spinbox (0.1-5.0 seconds)
- Timeout: Spinbox (5-120 seconds)
- Bandwidth: Spinbox (0-10000 KB/s)
- Language: Dropdown (en/es/fr/de/ja)

### Via CLI:
```bash
python main.py --workers 8 --rate 0.5 --bandwidth-limit 1000
```

### Via API:
```bash
curl -X POST http://127.0.0.1:8000/api/config \
  -H "Content-Type: application/json" \
  -d '{"workers": 8, "rate_limit": 0.5}'
```

---

## 📊 API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/health` | GET | Server health check |
| `/api/titleids` | GET | List all TitleIDs |
| `/api/titleid/{id}` | GET | Get TitleID details |
| `/api/search?q=query` | GET | Search TitleIDs |
| `/api/metadata/{id}` | POST | Collect metadata |
| `/api/download/{id}` | POST | Download content |
| `/api/statistics` | GET | Database statistics |
| `/api/failed-items` | GET | List failed downloads |
| `/api/retry-failed` | POST | Retry failed items |
| `/api/verify-integrity` | GET | Check file integrity |
| `/api/export?format=json\|csv` | GET | Export database |
| `/api/config` | GET/POST | Get/update configuration |

---

## 🧪 Testing

### Run All Tests:
```bash
python integration_tests.py
```

### Run Specific Test Class:
```bash
python -m unittest integration_tests.TestI18nModule -v
```

### Test Classes Available:
- `TestI18nModule` - Language support (5 tests)
- `TestUpdaterModule` - Version checking (3 tests)
- `TestQueueManager` - Download queue (8 tests)
- `TestSpeedMonitoring` - Speed tracking (5 tests)
- `TestDatabaseIntegrity` - File verification (6 tests)
- `TestAPIIntegration` - REST API (2 tests)
- `TestFeatureIntegration` - Feature integration (3 tests)

**Total**: 32 comprehensive integration tests

---

## 📦 Dependencies

### Required:
- `requests>=2.31.0` - HTTP client
- `urllib3>=2.0.0` - URL library

### Optional (for new features):
- `flask>=2.3.0` - REST API server
- `flask-cors>=4.0.0` - CORS support
- `packaging>=23.0` - Version parsing

### Install All:
```bash
pip install -r requirements.txt
```

---

## 🔐 Security Notes

1. **API**: Default localhost only (`127.0.0.1`)
   - Change with `--api-host 0.0.0.0` for network access
   - Consider adding authentication for production

2. **Queue**: Stored in JSON file
   - Location: `download_queue.json` in current directory
   - Contains URLs and download status

3. **Database**: SQLite with indexes
   - Location: `unityscraper.db`
   - Contains metadata and history

4. **Checksums**: SHA256 by default
   - Automatic verification if enabled
   - CLI: `python main.py --verify-checksums`

---

## 🌍 Language Support

### Supported Languages:
- 🇺🇸 **English** (en)
- 🇪🇸 **Spanish** (es)
- 🇫🇷 **French** (fr)
- 🇩🇪 **German** (de)
- 🇯🇵 **Japanese** (ja)

### Switching Languages:
1. **GUI**: Click language dropdown
2. **Code**: `translator.set_language('es')`

---

## 🐛 Troubleshooting

| Issue | Solution |
|-------|----------|
| Flask not found | `pip install flask flask-cors` |
| Import error | Check all modules in same directory |
| API won't start | Check port (default 8000) not in use |
| Queue not persisting | Check write permissions in directory |
| Integrity check fails | Verify file checksums with `--verify-checksums` |
| Language not changing | Restart GUI and reselect language |

---

## 📚 File Structure

```
UnityScraper/
├── main.py                 # Core scraper
├── GUI.py                  # Tkinter GUI with all features
├── database.py             # SQLite + integrity checking
├── resume.py               # Downloads + speed monitor
├── api.py                  # REST API server
├── i18n.py                 # Multi-language support
├── updater.py              # Version checking
├── queue_manager.py        # Persistent queue
├── integration_tests.py    # 32 comprehensive tests
├── requirements.txt        # Dependencies
└── INTEGRATION_SUMMARY.md  # Full documentation
```

---

## 🎯 Common Tasks

### Check file integrity
```bash
# CLI
python main.py --verify-integrity

# GUI
Click "Verify Files" button

# API
curl http://127.0.0.1:8000/api/verify-integrity
```

### Check for updates
```bash
# GUI
Click "Check Updates" button

# API
GET http://127.0.0.1:8000/api/health
```

### View download queue
```bash
# GUI
Click "View Queue" button

# API
curl http://127.0.0.1:8000/api/statistics
```

### Filter items by status
```bash
# GUI
Select status from dropdown (all/pending/downloaded/failed)
Select date from dropdown (any/7d/30d/custom)
```

### Export database
```bash
# CLI
python main.py --export json --export-file backup.json

# GUI
Click "Export DB" button

# API
GET http://127.0.0.1:8000/api/export?format=json
```

---

## 💡 Pro Tips

1. **Speed**: Increase workers but respect rate limiting
2. **Reliability**: Use `--verify-checksums` for critical downloads
3. **Persistence**: Queue survives app crashes
4. **Languages**: Switch without restarting GUI
5. **API**: Run in background while using GUI
6. **Testing**: Run integration tests after code changes

---

**Version**: 1.1.0 with Advanced Features  
**Date**: January 24, 2026  
**Status**: ✅ Production Ready
