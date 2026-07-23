# Xbox 360 Knowledge Foundation

UnityScraper now has a normalized knowledge layer for Xbox 360 reference data.
The first adapters import ConsoleMods TitleID and Multi-ID game data; the schema
is designed for later XenonLibrary, Free60, Redump DAT, and No-Intro DAT
adapters without mixing untraceable facts into the legacy `titleids.metadata`
blob.

## Import Command

```powershell
python main.py --sync-knowledge
```

The command:

- fetches ConsoleMods source documents with rate limiting;
- caches raw source snapshots under the application data directory;
- records source, document, revision, citation, import run, and conflict data;
- imports game entities, TitleID identifiers, publisher facts, title facts,
  region facts, alternate-title facts, and related TitleID facts;
- enriches existing library rows only when `name` or `publisher` is blank,
  `Unknown`, or `Unknown Publisher`.

Known user-entered or XboxUnity-provided title and publisher values are not
overwritten.

## Schema

The database migration adds these normalized tables:

- `knowledge_sources`
- `source_documents`
- `source_revisions`
- `knowledge_entities`
- `entity_names`
- `entity_identifiers`
- `knowledge_facts`
- `fact_citations`
- `entity_relationships`
- `knowledge_import_runs`
- `knowledge_conflicts`

Facts are source-attributed claims. If two sources disagree, both claims can
exist and the disagreement is recorded in `knowledge_conflicts`.

## Source And Licensing Notes

ConsoleMods is imported as community reference data with citations back to the
original pages. ConsoleMods states its wiki content is Creative Commons
Attribution unless otherwise noted, so derived displays should preserve
attribution and source links.

Future source adapters should keep their source data separable:

- XenonLibrary: hardware, prototype, board, component, and development-kit
  reference data. Its CC BY-NC-SA content should stay clearly attributed and
  should not be silently blended into project-authored documentation.
- Free60: system internals, formats, boot process, Linux, LibXenon, and
  homebrew-development reference material. Preserve warnings and freshness
  context because some material is historical or outdated.
- Redump DAT: physical-disc identifiers and hashes only. Do not download or
  distribute disc images.
- No-Intro DAT: digital/package identifiers and hashes where available. Keep
  adapter access and supported set names configurable because DAT availability
  changes over time.

## XboxUnity Transport Constraint

XboxUnity API endpoints remain HTTP-only in UnityScraper. Knowledge-source
adapters may use HTTPS for non-XboxUnity websites, but they do not change
XboxUnity transport behavior.

## Next Steps

1. Add a source-management UI for sync status, source licenses, and conflicts.
2. Add XenonLibrary adapters for hardware entities and board/component facts.
3. Add Free60 adapters for technical articles and system-format entities.
4. Add Redump DAT import for disc identities, serials, and hashes.
5. Add No-Intro DAT import for digital/package identities and hashes.
6. Add full-text indexing for cached wiki articles.
7. Add explicit relationship records for multi-ID groups once the UI can show
   grouped releases.
