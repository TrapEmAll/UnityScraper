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

## Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/health` | Version, readiness, and authentication status |
| `GET` | `/api/titleids` | List library TitleIDs |
| `GET` | `/api/titleid/<TitleID>` | Get one library record |
| `GET` | `/api/search?q=` | Search the library |
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
