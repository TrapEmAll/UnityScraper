# Advanced Features

This guide covers optional operational features. Start with the
[README](README.md) for installation and normal desktop use.

## Rate and Worker Controls

```powershell
python main.py 4D5307E6 --metadata-only --workers 4 --rate 0.5
```

- `--workers` controls concurrent tasks.
- `--rate` sets the minimum interval between service requests.
- `--bandwidth-limit` limits downloads in KB/s; `0` means unlimited.
- `--timeout`, retries, and refresh behavior can also be stored in config.

Be conservative with community services. More workers do not always improve
throughput and can make rate limiting worse.

## Resumable Downloads

UnityScraper writes partial downloads separately and keeps resume metadata.
Completed files are published only after the transfer and configured
verification finish. Failed records remain available for:

```powershell
python main.py --retry-failed
```

## Integrity and Exports

```powershell
python main.py --verify-integrity
python main.py --export json --export-file library.json
python main.py --export csv --export-file library.csv
```

Archive Health in the desktop app adds missing-file and database consistency
checks. Backup Manager verification covers Xbox content layouts and abandoned
partial files.

## Diagnostics

Use **Help & About > Export Diagnostics** to create a sanitized support bundle.
Review it before sharing. Downloaded content and secrets are not intentionally
included, but filesystem paths can still be sensitive.

## Portable Mode

Create `portable.mode` beside the application before launch. Runtime data then
lives under `UnityScraperData` beside the application. Remove the marker to
return to normal per-user storage; existing data is not moved automatically.

## REST API

The API is intended for local automation. It binds to `127.0.0.1` by default,
uses restricted browser origins, validates mutable settings, and requires a
token for non-loopback binds. See [API.md](API.md).

## External Conversion

Backup Manager can invoke a converter selected by the user:

```powershell
python main.py --convert-iso game.iso `
  --converter C:\Tools\converter.exe `
  --converter-arg "{input}" `
  --converter-arg "{output}" `
  --converter-output D:\Converted
```

UnityScraper does not bundle a converter or implement copy-protection bypass.
