# Release Toolkit

The **Community Hub > Toolkit** page groups portable metadata, collection
attention, reporting, correction, and hardware workflows.

## Metadata snapshots

`.usmeta` files are compressed JSON snapshots containing the XboxUnity title
catalog and normalized knowledge entities, identifiers, facts, citations, source
names, and licenses. They explicitly exclude profiles, saves, download history,
credentials, local paths, console identifiers, and game content.

Imports validate the archive shape, schema, expanded size, TitleIDs, and fact
records. Existing source-attributed claims can coexist; the normal preference and
conflict rules choose display values.

## Library intelligence

The audit highlights unknown game names or publishers, available but unarchived
covers and updates, and updates whose MediaID compatibility still needs evidence.
It records only a summary in SQLite and does not automatically download content.

## Preservation reports

The HTML report summarizes library attention and knowledge-source provenance.
Personal profile identifiers and filesystem paths are deliberately excluded.

## Correction packages

Correction exports contain reviewed local metadata overrides. They are suitable
for manual community review and do not publish or upload anything automatically.

## Hardware records

Users can keep local notes for motherboard, DVD drive, NAND, dashboard, and
console type. Serial numbers and keys are not requested.

## Command line

```powershell
python main.py --metadata-snapshot-export xbox360.usmeta
python main.py --metadata-snapshot-import xbox360.usmeta
python main.py --library-audit
python main.py --preservation-report preservation.html
python main.py --corrections-export corrections.json
python main.py --extract-stfs save.con --extract-destination extracted
```

STFS extraction currently supports files stored in consecutive blocks. A
fragmented file is reported and skipped until block-chain traversal and hash-tree
verification have independent real-package test vectors.
