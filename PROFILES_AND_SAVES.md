# Profiles and Saves

The **Profiles & Saves** workspace inventories and protects Xbox 360 profile
data from an extracted `Content` directory. It is designed around read-only
discovery and snapshot-before-change workflows.

## Supported Sources

Choose any of these:

- a `Content` directory
- a folder containing `Content`
- an extracted `Hdd1` folder containing `Hdd1/Content`
- a modern FAT32 Xbox 360 USB drive whose content is directly visible

For FATX-formatted disks or older Xbox 360 USB system drives, mount or extract
the content using a trusted filesystem tool first. UnityScraper does not write
raw disks or mount FATX volumes.

## Inventory

UnityScraper recognizes non-public 16-character profile directories and scans:

```text
Content/
  <ProfileID>/
    FFFE07D1/00010000/   profile package
    <TitleID>/00000001/  saved games
```

For supported STFS packages it records:

- package signature type (`CON`, `LIVE`, or `PIRS`)
- content type
- TitleID and cached game name
- save-game ID
- embedded profile ID
- creator console ID
- device ID
- package display name
- size, modified time, and SHA-256

Package fields are compared with their containing profile and TitleID folders.
Mismatches are reported and never rewritten automatically. Identical hashes are
reported as duplicates.

The UI masks profile identifiers by default. Select **Reveal profile
identifiers** only when needed. Profile and save data stays local and is never
sent to UnityScraper metadata sources.

## Snapshots

**Back Up Profile** copies every file in the selected profile directory.
**Back Up Selected Saves** copies only the selected save packages.

Each snapshot contains:

- the original relative directory layout
- SHA-256 for every file
- source metadata
- an atomic JSON manifest
- database operation history

Files are copied through a temporary `.partial` file, verified, and then
published atomically. Snapshots are stored in the application data directory
under `profile_backups`.

## Restore

Select a complete snapshot and choose **Restore to Folder**. Every snapshot
file is verified before it is copied.

UnityScraper never overwrites a different existing file. Matching files are
skipped; conflicts are restored alongside the existing file with a
`.restored-N` suffix. This lets the user compare both copies before deciding
which one belongs on a console.

Restore currently targets an ordinary folder. Use Backup Manager or your
preferred filesystem tool to transfer verified output to the console or USB
device.

## Current Safety Boundary

This release deliberately does not:

- edit achievements, GPD records, gamertags, or account blocks
- change profile, console, or device ownership fields
- rehash or resign modified CON packages
- authenticate to Xbox Live or Microsoft accounts
- store CPU keys, account credentials, or signing material
- write raw FATX disks

Those operations can make a profile or save unusable when implemented
incorrectly. Future editing and migration support should only ship with
complete package verification, automatic pre-change snapshots, and
well-tested cross-platform signing support.

## Le Fluffie Attribution

The profile/STFS field model is informed by Dalavin, also known as
**DJ SkunkieButt** and **DJ Shepherd**, through the GPLv3 X360 library and Le
Fluffie source archived at
[mtolly/X360](https://github.com/mtolly/X360).

UnityScraper uses a new Python implementation suited to its existing
cross-platform architecture. It does not bundle Le Fluffie's executable,
updater, embedded key resources, account-modification code, or artwork. The
archived GPL text is preserved with the application and the corresponding
source remains linked from About and the third-party notices.

