# UnityScraper Project Status

UnityScraper is an Xbox 360 library, title-update, artwork, archive-health, and
source-attributed knowledge application.

## Completed

- Library-first dark desktop interface with portable storage support.
- XboxUnity cover and title-update collection using its required HTTP endpoints.
- Persistent SQLite library, queue, retries, resumable downloads, diagnostics,
  archive health checks, JSON/CSV exports, and advanced tools.
- Normalized knowledge schema for sources, documents, revisions, entities,
  identifiers, names, facts, citations, relationships, import runs, and
  conflicts.
- ConsoleMods TitleID and Multi-ID parsing with safe publisher/title enrichment.
- Searchable ConsoleMods, XenonLibrary, and Free60 wiki article ingestion using
  MediaWiki API or sitemap discovery, local caching, attribution, and per-source
  failure isolation.
- User-selected Redump and No-Intro XML DAT import for release identity, serial,
  size, status, and checksum metadata.
- Desktop knowledge browser with source status, licenses, citations, import
  actions, and conflict review.
- Windows packaging rules that include the full visual asset set and dynamically
  loaded knowledge adapters.

## Validation

- Unit tests cover scraper configuration, database behavior, ConsoleMods parsing,
  DAT parsing, wiki parsing, knowledge search/provenance, downloads, queueing,
  and an end-to-end local workflow.
- Network-backed source syncs remain dependent on each source's availability and
  access policy. Cached copies are used when available.

## Deliberate Boundaries

- No commercial game images, firmware, keys, leaked SDK files, or other
  copyrighted payloads are bundled or downloaded.
- Redump and No-Intro DAT files must be obtained by the user from their source.
- Imported facts retain their source and conflicts are shown rather than silently
  discarded.
- Known local or XboxUnity title/publisher data is not replaced by fallback
  knowledge values.

## Future Work

- Parse user-owned XEX and STFS files and link their identifiers to knowledge
  entities.
- Add field-specific source-priority controls and conflict resolution actions.
- Add optional scheduled knowledge refreshes and offline HTML reports.
