# REST API

The optional REST API supports local automation. It is not required for the
desktop application.

## Start

Localhost mode:

```powershell
python main.py --api-mode
```

The default base URL is:

```text
http://127.0.0.1:8000/api
```

Remote binds require a token:

```powershell
$env:UNITYSCRAPER_API_TOKEN = "replace-with-a-long-random-token"
python main.py --api-mode --api-host 0.0.0.0 --api-port 8000
```

`--api-token` is also supported, but environment variables avoid exposing a
token in command history and process listings.

Send credentials using either header:

```text
Authorization: Bearer <token>
X-API-Key: <token>
```

The health endpoint does not require authentication. All other endpoints do
when a token is configured.

For separate automation clients, `UNITYSCRAPER_API_TOKENS` accepts a JSON object
mapping tokens to `read`, `write`, or `transfer` scopes. A legacy single token
has all scopes. Requests are limited per client to 120 per minute by default.

## Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/health` | Version, readiness, and authentication status |
| `GET` | `/api/titleids` | List library TitleIDs |
| `GET` | `/api/titleid/<TitleID>` | Get one library record |
| `GET` | `/api/search?q=` | Search the library |
| `GET` | `/api/community/search?q=` | Search all local domains; repeat `category` to filter |
| `GET` | `/api/preservation/dedup/actions` | List duplicate actions from the latest or selected plan |
| `POST` | `/api/preservation/dedup/preview` | Create a read-only duplicate preview for JSON `root` |
| `POST` | `/api/preservation/dedup/<id>/apply` | Apply `quarantine` or `hardlink` mode |
| `POST` | `/api/preservation/dedup/<id>/restore` | Revalidate and restore a quarantined original |
| `GET` | `/api/plugins` | List managed plugins and checksum trust state |
| `GET` | `/api/library/audit` | Find incomplete names, publishers, covers, updates, and MediaIDs |
| `POST` | `/api/metadata-snapshots/export` | Export a non-personal `.usmeta` snapshot |
| `POST` | `/api/metadata-snapshots/import` | Merge a validated `.usmeta` snapshot |
| `POST` | `/api/packages/extract` | Extract supported STFS files read-only |
| `POST` | `/api/reports/preservation` | Create a privacy-conscious HTML report |
| `GET` | `/api/hardware` | List local console hardware notes |
| `POST` | `/api/hardware` | Add a local console hardware record |
| `POST` | `/api/metadata/<TitleID>` | Collect metadata |
| `POST` | `/api/download/<TitleID>` | Process downloads |
| `GET` | `/api/statistics` | Library statistics |
| `GET` | `/api/failed-items` | Failed downloads |
| `POST` | `/api/retry-failed` | Retry failed downloads |
| `GET` | `/api/verify-integrity` | Verify recorded files |
| `GET` | `/api/export?format=json` | Export JSON or CSV under the exports directory |
| `GET` | `/api/config` | Read safe runtime settings |
| `POST` | `/api/config` | Update allowlisted runtime settings |

TitleID routes require exactly eight hexadecimal characters.
Duplicate apply and restore endpoints change local files and therefore require
an explicit action ID created by a prior preview. They retain a recovery copy
until restoration and use the same path and checksum validation as the desktop.

## Configuration

Mutable keys:

- `workers`
- `rate_limit`
- `timeout`
- `max_retries`
- `retry_backoff`
- `bandwidth_limit`
- `verify_checksums`
- `dry_run`
- `refresh_interval_days`

Types and ranges are validated. `base_url`, `use_https`, filesystem paths, and
arbitrary object attributes cannot be changed through the API. XboxUnity
remains fixed to `http://xboxunity.net`.

Example:

```powershell
$headers = @{ Authorization = "Bearer $env:UNITYSCRAPER_API_TOKEN" }
$body = @{ workers = 4; rate_limit = 0.5 } | ConvertTo-Json
Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:8000/api/config `
  -Headers $headers `
  -ContentType application/json `
  -Body $body
```

## Network Safety

- The built-in server uses HTTP, not TLS.
- Use localhost whenever possible.
- For remote use, keep the service on a trusted private network or place it
  behind an authenticated TLS reverse proxy.
- Browser CORS is restricted to localhost origins unless the API is embedded
  programmatically with an explicit origin list.
- Responses disable caching and include basic content and frame protections.
- Tokens can be separated by read, write, and transfer scope, and each client
  has a bounded request window.
