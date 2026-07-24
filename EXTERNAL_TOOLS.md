# External Tools

UnityScraper can run trusted Xbox command-line utilities from the desktop
interface. Open **External Tools** from the sidebar.

## XeXTool

The Windows build includes XeXTool 6.3, created by **xorloser**, so the XeXTool
preset works without separate setup. The executable was sourced from the
GPL-3.0-licensed
[XboxChef/XexToolGUI](https://github.com/XboxChef/XexToolGUI) project.
UnityScraper preserves its source license and records the exact binary checksum
in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

Use **Browse** to select a different lawfully obtained build at any time. A
missing or invalid saved path automatically falls back to the bundled copy.

The XeXTool preset provides:

- **Extended information** using `-l "{input}"`
- **Basic information** using `"{input}"`
- **Custom arguments** for advanced users

Choose an XEX file, review the command shown in the output panel, and select
**Run Tool**. Standard output and standard error remain visible in UnityScraper.

## Other CLI Tools

Choose **Custom CLI tool**, select an executable, and enter its argument
template. Two placeholders are supported:

```text
{input}   selected input file
{output}  selected output path
```

Each placeholder becomes part of one argument after parsing. UnityScraper
starts the executable directly with `shell=False`; it does not send the command
through PowerShell, Command Prompt, Bash, or another command shell.

Custom XeXTool and CLI paths are stored in the normal application
configuration. The bundled executable remains inside UnityScraper's packaged
resources and is not copied into the user data folder.

## Safety

- Use tools and files you are legally entitled to use.
- Keep backups before running commands that modify content.
- Prefer the read-only information presets when inspecting an unfamiliar XEX.
- Review custom arguments before running them.
- Do not run executables from an untrusted source.
- Cancellation requests terminate the active process, but a tool may already
  have changed its output before termination.

## Platform Notes

The external tool must be executable on the current operating system.
The bundled XeXTool executable is enabled on Windows. Windows `.exe` files do
not run natively on Linux, so Linux users can select a native tool or a trusted
wrapper they configured themselves. UnityScraper does not automatically
install or invoke Wine.
