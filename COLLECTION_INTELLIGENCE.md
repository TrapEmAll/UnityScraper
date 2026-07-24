# Collection Intelligence

UnityScraper 1.0 beta inventories Xbox 360 collections, retains snapshots in
SQLite, compares TitleIDs and MediaIDs with catalogued Title Updates, and
produces preservation-oriented reports.

## Sources and Identification

The **Collections** workspace accepts content trees, extracted `Games`
directories, mounted USB/archive folders, and user-selected Aurora SQLite
databases. Aurora databases are opened in immutable read-only mode.

Mounted-storage discovery checks Windows drive roots, Linux `/media`,
`/run/media`, and `/mnt`, and macOS `/Volumes`. XEX2 parsing reads the public
header fields for TitleID, MediaID, versions, module flags, and disc position.
It does not decrypt or extract executable content.

Title Update status is conservative:

- `compatible`: TitleID and MediaID both match
- `media-id-required`: updates exist but the collection MediaID is unknown
- `incompatible`: the TitleID exists but no MediaID matches
- `none`: no update is catalogued
- `unknown`: the TitleID could not be identified

## Preservation and Repair

Files can be hashed with CRC32, MD5, SHA-1, and SHA-256 and matched against
user-imported Redump or No-Intro DAT metadata. UnityScraper stores metadata,
hashes, and matches, never game content.

Exports include JSON manifests, offline HTML collection reports, and fact
provenance with sources and citations. Metadata overrides are stored
separately from imported facts.

A repair plan is a preview in `repair_plans` and `repair_actions`. Creating
one does not delete, replace, download, or transfer anything.

## Command Line

```powershell
python main.py --analyze-collection D:\Xbox360 `
  --collection-manifest collection.json `
  --collection-html collection.html `
  --create-repair-plan

python main.py --aurora-db content.db --collection-manifest aurora.json
python main.py --match-file game.iso
python main.py --export-provenance provenance.json
python main.py --backup-database unityscraper-backup.db
```
