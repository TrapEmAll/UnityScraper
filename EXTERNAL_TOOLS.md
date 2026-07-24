# External Tools

UnityScraper can run trusted Xbox command-line utilities from the desktop
interface. Open **External Tools** from the sidebar.

## XeXTool

XeXTool is not distributed with UnityScraper. Its redistribution terms are not
clear enough for this project to package the executable. Obtain it lawfully,
review it with your usual security tools, and select your local copy using
**Browse**.

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

The configured XeXTool path is stored in the normal application configuration.
Tool binaries are never copied into UnityScraper's data folder.

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
Windows `.exe` files do not run natively on Linux. UnityScraper does not
automatically install or invoke Wine. Linux users can select native tools or a
trusted wrapper executable they configured themselves.
