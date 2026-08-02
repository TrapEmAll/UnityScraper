# Xbox 360 Knowledge Foundation

UnityScraper now has a normalized knowledge layer for Xbox 360 reference data.
The knowledge layer imports ConsoleMods TitleID and Multi-ID game data, caches
Xbox 360 wiki articles from ConsoleMods, XenonLibrary, and Free60, and accepts
user-selected Redump and No-Intro XML DAT files. Imported claims remain separate
from the legacy `titleids.metadata` blob and retain source provenance.

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

## Whole-Wiki Sync

```powershell
python main.py --sync-wikis
```

ConsoleMods and XenonLibrary pages are discovered through MediaWiki's paginated
all-pages API, with XML sitemap discovery as an additional path. Free60 uses
its XML sitemap. Seed pages and URLs from successful earlier cache entries are
always retained, so a temporary discovery failure does not hide known pages.

Every fetched article is cached locally and imported as a searchable knowledge
entity with its source URL, revision snapshot, summary, and visible article
text. Pages containing words such as `outdated`, `historical`, or `obsolete`
receive a freshness warning.

Use `--wiki-limit N` to restrict each source during testing or a first sync.

## Browser Verification And Offline Use

ConsoleMods and XenonLibrary currently may place Cloudflare browser
verification in front of wiki and API requests. A normal browser can work while
the same URL returns HTTP 403 to UnityScraper. The application deliberately
does not imitate a browser session, solve challenges, or bypass source access
controls.

When this happens UnityScraper:

- reports that browser verification blocked the refresh;
- uses a prior cached page when one exists without changing its original fetch
  timestamp;
- records the stale-cache state and refresh error with the source document;
- continues importing other available sources;
- rebuilds the offline library from every usable cached page.

In the desktop **Knowledge** workspace, choose a source and use **Import Saved
Wiki Pages**. You can select individual `.html`/`.htm` files, a folder, or a ZIP
containing saved pages. For command-line use:

```powershell
python main.py --import-saved-wiki "C:\Saved Wikis" --saved-wiki-source consolemods-wiki
python main.py --import-saved-wiki "C:\Saved Wikis\xenon.zip" --saved-wiki-source xenonlibrary
python main.py --build-offline-knowledge
```

The importer accepts at most 5,000 pages, 10 MB per page, and 250 MB total per
operation. It never executes imported HTML. Canonical URLs are accepted only
when they match the selected source. A saved ConsoleMods TitleID or Multi-ID
list also runs through the structured game metadata parser and still enriches
only unknown local names or publishers.

The generated `offline_knowledge/index.html` is a private, self-contained,
dark-theme reading library. It contains readable article text, cache status,
source links, timestamps, and license attribution. Remote scripts, styles,
trackers, and images are not copied into rendered pages. Raw source snapshots
remain in the application cache for provenance and future reprocessing.

## Preservation DAT Import

Download DATs directly from their source and import them locally:

```powershell
python main.py --import-dat "C:\path\xbox360.dat" --dat-source redump
python main.py --import-dat "C:\path\xbox360-digital.dat" --dat-source no-intro
```

The importer reads common Logiqx-style XML and stores release names, regions,
languages, versions, serials, file names, sizes, status values, CRC32, MD5,
SHA-1, and SHA-256 identifiers when present. It never downloads or copies game
content.

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
- `offline_archive_runs`
- `offline_archive_documents`
- `offline_page_import_runs`

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

## Desktop Experience

The **Knowledge** page includes:

- global entity, identifier, and fact search;
- details with source names and citation URLs;
- source license, document count, fact count, and latest import status;
- ConsoleMods ID sync and whole-wiki sync;
- saved-page import, offline-library rebuild, and local-browser access;
- Redump and No-Intro file import;
- per-property source priorities, where lower numbers are preferred for
  display;
- conflicting-claim review with recorded prefer-existing, prefer-incoming,
  and dismiss decisions;
- an opt-in app-start refresh schedule with a minimum six-hour interval.

## Remaining Boundaries

- Source availability, access controls, and licenses can change. Failed syncs
  are isolated per source and previously cached or manually imported pages
  remain available.
- Redump and No-Intro DATs are not bundled. Users obtain them from the source.
- Wiki content is reference material, not automatically trusted repair advice.
- Commercial game images, firmware, keys, and leaked SDK files are never
  imported or distributed.
