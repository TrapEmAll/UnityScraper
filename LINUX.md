# Linux Support

UnityScraper supports 64-bit Linux desktops through a packaged PyInstaller
bundle or Python 3.10 and newer. The primary interface, command-line tools,
knowledge imports, backup manager, FTP transfer, REST API, and portable mode
use the same code and database format as Windows.

## Supported Environment

The release bundle is built on Ubuntu 22.04 for x86_64 systems. It should run
on current glibc-based distributions with an X11 desktop or XWayland available
under Wayland, including:

- Ubuntu 22.04 and newer
- Debian 12 and newer
- Fedora Workstation
- current Arch Linux
- openSUSE Leap and Tumbleweed

Native ARM64 packages and musl-only distributions are not currently produced.
Running from source remains possible when a compatible Python and Tk are
available.

## Install the Release Bundle

Download the Linux tarball and checksum from GitHub Releases:

```text
UnityScraper-Linux-x86_64.tar.gz
UnityScraper-Linux-x86_64.tar.gz.sha256
```

Verify, extract, and install for the current user:

```bash
sha256sum --check UnityScraper-Linux-x86_64.tar.gz.sha256
tar -xzf UnityScraper-Linux-x86_64.tar.gz
cd UnityScraper-Linux-x86_64
./install.sh
```

The installer places the application under `~/.local/lib/unityscraper`, adds a
`~/.local/bin/unityscraper` command, and installs an application-menu entry and
icon. It does not require root access.

## Run From Source

Install Python, virtual-environment support, and Tk:

```bash
# Debian or Ubuntu
sudo apt install python3 python3-venv python3-tk

# Fedora
sudo dnf install python3 python3-tkinter

# Arch Linux
sudo pacman -S python tk

# openSUSE
sudo zypper install python311 python311-tk
```

Then run:

```bash
./setup.sh
./run-unityscraper.sh
```

The command-line interface does not require a graphical session:

```bash
.venv/bin/python main.py --help
```

## Linux Storage

Installed mode follows the XDG Base Directory specification:

| Purpose | Default location | Override |
| --- | --- | --- |
| Database, downloads, exports | `~/.local/share/unityscraper` | `XDG_DATA_HOME` |
| Configuration | `~/.config/unityscraper` | `XDG_CONFIG_HOME` |
| Source cache | `~/.cache/unityscraper` | `XDG_CACHE_HOME` |
| Logs | `~/.local/state/unityscraper/logs` | `XDG_STATE_HOME` |

Set `UNITYSCRAPER_PORTABLE=1` or create `portable.mode` beside the executable
to place all writable files under `UnityScraperData` beside the application.
The marker must be created before UnityScraper starts.

## Storage Devices

Select mounted USB drives and archive folders from the Backup Manager. Common
desktop mount locations include `/run/media/$USER` and `/media/$USER`.
UnityScraper operates on normal mounted paths and does not mount filesystems or
request elevated privileges itself.

FATX filesystems require a compatible external driver or mount tool.
UnityScraper does not bundle kernel modules, filesystem drivers, or privilege
helpers.

## Uninstall

From the installed application:

```bash
~/.local/lib/unityscraper/uninstall.sh
```

The uninstaller removes the application but deliberately retains user data.
Remove retained data manually only after confirming it is no longer needed:

```bash
rm -rf "${XDG_DATA_HOME:-$HOME/.local/share}/unityscraper"
rm -rf "${XDG_CONFIG_HOME:-$HOME/.config}/unityscraper"
rm -rf "${XDG_CACHE_HOME:-$HOME/.cache}/unityscraper"
rm -rf "${XDG_STATE_HOME:-$HOME/.local/state}/unityscraper"
```

## Troubleshooting

`Tkinter is required`

: Install the distribution's Tk package listed above. Recreate `.venv` if
  Python was upgraded after the environment was created.

`could not connect to a graphical desktop`

: Launch UnityScraper from an active desktop session. For remote systems, use
  the CLI or configure trusted X11 forwarding.

Folders do not open from the Help page

: Install `xdg-utils` or GLib's `gio` command. UnityScraper supports either.

The packaged binary does not start

: Run `./unityscraper` from a terminal to view the startup message, then include
  the output and a diagnostics bundle in a bug report.
