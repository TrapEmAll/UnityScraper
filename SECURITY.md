# Security Policy

## Supported Versions

Security fixes are developed for the current `main` branch and the latest
published beta or stable release.

## Reporting a Vulnerability

Use GitHub's private vulnerability reporting feature for this repository when
available. If it is unavailable, contact the maintainer privately through the
contact method shown on the repository owner's GitHub profile.

Please include:

- UnityScraper version or commit
- Operating system and Python version
- Affected workflow
- Minimal reproduction steps
- Expected and observed behavior
- Whether untrusted files, ZIP archives, FTP servers, or API requests are
  involved

Do not include copyrighted game data, credentials, encryption keys, or private
filesystem contents in a report.

## Security Boundaries

- The REST API binds to localhost by default. Remote binds require an explicit
  API token.
- API tokens and FTP passwords are not stored in the UnityScraper database.
- Traditional FTP is unencrypted and should only be used on a trusted local
  network.
- ZIP imports reject traversal paths, symlinks, excessive entries, and
  unreasonable expanded sizes.
- Package copies use temporary files, verification, and atomic publication.
- Profile and save identifiers are masked in the GUI by default.
- Profile scans are read-only. Snapshot restores preserve different existing
  files and write the restored copy alongside them.
- GPD parsing validates bounded entry tables and file offsets and never writes
  achievement, setting, sync, or image records.
- GPD image export validates the selected bounded payload and publishes through
  a temporary file without changing the source GPD.
- Duplicate actions revalidate both hashes and retain the removed path in a
  local quarantine; hardlinks are created only after quarantine succeeds.
- FATX image support is detection-only. Raw image and device writes are not
  available.
- Package ownership changes and signed-package rebuilds remain preview-only.
- Plugin ZIPs have entry and expanded-size limits, reject traversal paths, and
  are installed disabled for explicit review.
- Xenia migrations require a preview and verified snapshot, publish through
  partial files, and never overwrite different destination data.
- Optional remote hashes use read-only FTP commands and fail closed when the
  selected dashboard does not expose a supported SHA-256 response.
- Profiles, saves, gamertags, XUIDs, console IDs, and device IDs are not sent
  to metadata sources.
- External converters run only when explicitly configured by the user.
- UnityScraper does not provide game images, firmware, keys, SDK files, or
  copy-protection bypass tools.
- UnityScraper does not request Xbox Live credentials or store CPU keys,
  account keys, or profile-signing material.
