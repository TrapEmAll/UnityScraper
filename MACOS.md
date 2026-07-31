# macOS Support

UnityScraper supports macOS 11 or newer from source on Intel and Apple silicon
through the same Tk desktop application and native Application Support, Caches,
and Logs paths.

Current preview release archives are built for Apple silicon and contain
`UnityScraper.app` plus a SHA-256 checksum. They are currently unsigned and not
notarized, so macOS may require an explicit **Open** confirmation from Finder.
The project does not ask users to disable Gatekeeper. Intel users should run
from source until a universal release artifact is available.

## Source setup

Install Python 3.10 or newer with Tk support, then run:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python desktop_app.py
```

## Build

```sh
chmod +x build_macos.sh
./build_macos.sh
```

Signing and notarization can be enabled by a release maintainer when an Apple
Developer ID certificate and notarization credentials are configured as
repository secrets. Those credentials are never stored in the repository.
