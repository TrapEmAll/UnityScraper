# Profile Intelligence and Xenia

The **Profiles & Saves** workspace includes read-only profile intelligence and
a snapshot-first bridge for Xenia save folders.

## GPD and Achievements

UnityScraper reads standalone or already-extracted Xbox 360 XDBF/GPD files.
Choose **Import GPD** for one file or **Scan Extracted Folder** to find files
whose first four bytes are the `XDBF` signature.

The bounded parser validates:

- XDBF magic, version, table capacity, and active counts;
- every entry offset and size before reading it;
- achievement record minimum sizes;
- variable-length setting sizes;
- a 512 MiB per-file safety limit.

For game GPDs, the application displays achievement ID, title, gamerscore,
locked/unlocked state, and a valid online unlock timestamp when present. It
also records totals for unlocked achievements and earned/possible gamerscore.

The parser never writes to the source file. It does not unlock achievements,
alter sync records, extract images, edit account settings, or repair malformed
databases.

UnityScraper currently reads standalone or extracted GPD files. It does not
silently unpack or rewrite the profile's STFS container.

## Profile Comparison

Choose two indexed profiles on the **Compare** tab. The report identifies:

- save TitleIDs present on only one profile;
- TitleIDs whose indexed save hashes differ;
- TitleIDs with identical indexed save hashes;
- imported achievements unlocked by only one profile;
- achievements unlocked by both profiles.

Comparison history is stored locally. Profile identifiers remain masked in the
normal inventory interface and no profile information is uploaded.

## Xenia Migration

Xenia normally keeps saves in a `content` directory. Common locations are
suggested on Windows and Linux, and any Xenia folder or content root can be
selected manually.

The migration workflow is:

1. Select an indexed source profile.
2. Choose the Xenia folder and target profile ID.
3. Preview every destination and conflict.
4. Create an automatic verified snapshot.
5. Copy only new files through `.partial` staging.
6. Verify each copied file with SHA-256.

Identical destination files are skipped. Different files and non-file
destinations are conflicts and are never overwritten. Migration runs, counts,
plans, and their pre-change snapshot IDs are recorded in SQLite.

Xenia's folder guidance is based on the official
[Xenia Canary FAQ](https://github.com/xenia-canary/xenia-canary/wiki/FAQ) and
[Quickstart](https://github.com/xenia-canary/xenia-canary/wiki/Quickstart).
UnityScraper does not bundle or modify the emulator.

## Deliberate Boundary

This release still does not:

- edit GPD achievements, settings, gamertags, or account blocks;
- rewrite ownership identifiers;
- rehash or resign a modified CON package;
- store signing material, CPU keys, passwords, or Xbox Live credentials;
- write raw FATX devices.

Those operations require complete package extraction, mutation, rehashing,
signature verification, and recovery testing across real profiles before they
can be offered responsibly.
