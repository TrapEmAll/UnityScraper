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
- Profiles, saves, gamertags, XUIDs, console IDs, and device IDs are not sent
  to metadata sources.
- External converters run only when explicitly configured by the user.
- UnityScraper does not provide game images, firmware, keys, SDK files, or
  copy-protection bypass tools.
- UnityScraper does not request Xbox Live credentials or store CPU keys,
  account keys, or profile-signing material.
