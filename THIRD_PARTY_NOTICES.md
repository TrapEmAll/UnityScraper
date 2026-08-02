# Third-Party Notices

UnityScraper includes and interoperates with software and community data from
other projects. This file records bundled components that require prominent
credit or separate provenance.

## XeXTool 6.3

- **Creator:** xorloser
- **Purpose:** Inspecting and transforming Xbox 360 XEX executables
- **Bundled file:** `assets/tools/xextool/xextool.exe`
- **Source:** [XboxChef/XexToolGUI](https://github.com/XboxChef/XexToolGUI)
- **Source project license:** GNU General Public License version 3
- **SHA-256:** `D93C1B814AD6FF124834F4235BF8AAC9F09DBA8D69C335EBECC8D6EFE8D5A062`

The source project describes the bundled executable as xorloser's XeXTool 6.3
and credits xorloser as the original XeXTool developer. Its GPL-3.0 license is
preserved at
`assets/tools/xextool/XexToolGUI-GPL-3.0.txt`.

UnityScraper's GUI integration is independent code. Users may select a
different lawfully obtained XeXTool build or another command-line utility.

## X360 Library and Le Fluffie

- **Creator:** Dalavin, also known as DJ SkunkieButt and DJ Shepherd
- **Purpose:** Historical Xbox 360 STFS, SVOD, FATX, GPD, profile, and account
  research and tooling
- **Archived source:** [mtolly/X360](https://github.com/mtolly/X360)
- **License:** GNU General Public License version 3

UnityScraper's profile and save implementation is new Python code informed by
the public package/profile model and field layout documented in the X360
library and Le Fluffie source. The original GPL text is preserved at
`assets/references/lefluffie/X360-GPL-3.0.txt`.

UnityScraper does not include Le Fluffie's executable, updater, embedded key
resources, account-modification code, or artwork. The application credits
Dalavin prominently and links to the archived corresponding source.

## Tool Center Interoperability

The following projects are supported through user-selected executables. Their
binaries and licenses are not bundled by UnityScraper:

- **extract-xiso**, XboxDev: <https://github.com/XboxDev/extract-xiso>
- **Xenia**, Xenia Project: <https://github.com/xenia-project/xenia>
- **Xenia Canary**, Xenia Canary Project:
  <https://github.com/xenia-canary/xenia-canary>
- **Velocity**, Velocity contributors:
  <https://github.com/Gualdimar/Velocity> (archived GPL-3.0 project)
- **Iso2God**, Iso2God contributors: <https://github.com/r4dius/Iso2God>

Tool Center can also launch user-supplied God2ISO and Xbox Image Browser
installations. These legacy utilities have varied distribution histories, so
UnityScraper does not bundle them or claim a canonical download. Users are
responsible for obtaining lawful copies and reviewing the terms that accompany
their chosen builds.

An integration means that UnityScraper can locate or launch a program; it does
not imply endorsement by, affiliation with, or redistribution permission from
the program's authors.

