# Console Sync

Console Sync provides a persistent FTP queue for consoles and dashboards
whose FTP server the user explicitly configures.

## Behavior

- Upload and download jobs survive restarts in SQLite.
- Interrupted transfers return as paused.
- `.partial` files are retained for resume.
- FTP `REST` is used when the server supports ranged transfer.
- Uploads are published by renaming the completed partial file.
- Final sizes are verified; downloads can also require a SHA-256.
- Uploads can optionally require a remote SHA-256 when the dashboard exposes a
  compatible read-only hash command.
- Each job can have a bytes-per-second bandwidth limit.
- Passwords remain in memory and are never stored.

Some console FTP servers do not implement ranged uploads correctly. Those
servers may reject resume; the job retains its state and reports the error.

**Snapshot Console** recursively reads remote metadata without changing
files. A snapshot can be compared with a local directory to find files only
on the PC, only on the console, different-sized files, and matching files.
Discovery has a default 100,000-entry safety limit.

Remote hash verification probes `XSHA256`, standardized `HASH`, and compatible
`SITE SHA256` commands. When the option is enabled, a server without one of
those commands fails verification instead of silently falling back to size
only.

```powershell
python main.py --ftp-host 192.168.1.50 --ftp-user xbox --ftp-snapshot /Hdd1

python main.py --ftp-host 192.168.1.50 --ftp-user xbox `
  --ftp-download /Hdd1/Content/file `
  --ftp-local-path D:\Xbox360\file `
  --ftp-bandwidth-limit 1048576
```

Standard FTP is unencrypted. Use it only on a trusted local network.
