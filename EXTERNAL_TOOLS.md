# Tool Center

UnityScraper's **Tool Center** provides one place to discover, configure, and
run trusted Xbox 360 community utilities. Except for the documented XeXTool
copy, users provide their own lawfully obtained executables. UnityScraper does
not download tools, pass commands through a shell, or hide the command that is
about to run.

## Supported Tools

| Tool | Integration | Platforms | Credit |
| --- | --- | --- | --- |
| XeXTool | XEX information presets and custom arguments | Windows | xorloser |
| extract-xiso | List, extract, create, and guarded rewrite operations | Windows, Linux, macOS | XboxDev |
| Xenia | Launch a selected game or open the emulator | Windows | Xenia Project |
| Xenia Canary | Launch a selected game or open the emulator | Windows | Xenia Canary Project |
| Velocity | Detect, configure, verify, and launch | Windows | Velocity contributors |
| Iso2God | Detect, configure, verify, and launch | Windows | Iso2God contributors |
| God2ISO | Detect, configure, verify, and launch | Windows | Community utility |
| Xbox Image Browser | Detect, configure, verify, and launch | Windows | Community utility |
| Le Fluffie | Detect, configure, verify, and launch | Windows | Dalavin / DJ SkunkieButt |
| Custom CLI tool | User-defined argument vector with input/output placeholders | Current native platform | User supplied |

Legacy GUI utilities are launch-managed because their command-line contracts
are not stable or publicly documented. UnityScraper deliberately does not
invent arguments for them. Native operation presets are only supplied where a
reviewable command-line interface exists.

FATXplorer and J-Runner are intentionally not integrated.

## Setup

Open **Tool Center**, choose a tool, then select **Detect**. Discovery checks a
saved path, bundled resources where applicable, the system path, and a small
set of conventional tool folders. Use **Browse** when a tool is elsewhere.

The selected executable path is saved in the normal application configuration.
Its SHA-256 checksum is displayed after selection so the same binary can be
identified later. UnityScraper never treats that checksum as a publisher
signature or proof that an executable is safe.

## Native Workflows

### XeXTool

The Windows build includes XeXTool 6.3 by **xorloser** and provides basic and
extended XEX information presets. A different lawfully obtained build can be
selected. Output and errors remain visible in Tool Center.

### extract-xiso

The XboxDev command-line tool receives structured argument vectors for:

- listing image contents;
- extracting an image to a selected folder;
- creating an image from a selected folder; and
- rewriting an image only after a destructive-operation confirmation.

Keep a backup before any rewrite. The desktop asks for confirmation and the
CLI requires `--tool-allow-modify`.

### Xenia and Xenia Canary

Tool Center can launch either emulator with a selected game path or open it
without a game. Existing Profiles & Saves migration features remain separate:
they preview mappings, create a verified snapshot, and avoid overwriting
different save files.

## Command Line

List integrations and their operation IDs:

```powershell
python main.py --list-tools
```

Run a configured operation:

```powershell
python main.py --tool-id extract-xiso --tool-operation list --tool-input game.iso
```

Select and remember an executable explicitly:

```powershell
python main.py --tool-id xenia --tool-operation launch-game `
  --tool-executable C:\Tools\Xenia\xenia.exe --tool-input default.xex
```

`--tool-arg` may be repeated to replace a preset with an advanced argument
vector and requires `--tool-allow-modify`. `{input}` and `{output}` placeholders
are resolved as individual arguments. No PowerShell, Command Prompt, Bash, or
other shell interprets them. Reviewed built-in presets are locked in the GUI;
choose a custom operation when an editable argument vector is required.

## Safety and Platform Boundaries

- Use only software and content you are legally entitled to use.
- Obtain third-party tools from a source you trust and review their licenses.
- Keep backups before conversion or modification operations.
- Review the displayed executable, checksum, operation, and command.
- Cancellation stops a captured command-line process but cannot undo changes
  the external program already made.
- Windows executables are not automatically installed or run through Wine on
  Linux or macOS. Choose a native build where one exists.
- UnityScraper does not bundle game images, keys, firmware, SDK material, or
  closed-source legacy utilities.

See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for project links,
licenses, provenance, and the exact bundled XeXTool checksum.
