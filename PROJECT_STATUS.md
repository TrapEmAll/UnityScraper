# UnityScraper Project Status

UnityScraper is an Xbox 360 library, title-update, artwork, archive-health,
backup-management, and source-attributed knowledge application.

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
- Cloudflare-aware diagnostics, stale-cache recovery, browser-saved page
  import, and a self-contained offline Knowledge reading library.
- User-selected Redump and No-Intro XML DAT import for release identity, serial,
  size, status, and checksum metadata.
- Desktop knowledge browser with source status, licenses, citations, import
  actions, and conflict review.
- Cross-platform packaging rules that include the full visual asset set and
  dynamically loaded knowledge adapters.
- Local inventory for Xbox content roots, USB drives, archive folders, Games on
  Demand, XBLA, DLC, title updates, and extracted Xbox/Xbox 360 games.
- Public STFS, XBE, and XEX2 header inspection for TitleID, MediaID, versions,
  content type, disc, and display metadata.
- Mounted-storage discovery, read-only Aurora database import, exact MediaID
  Title Update comparison, collection health scoring, and repair previews.
- Preservation hash matching against imported DAT metadata, offline HTML
  reports, manifests, provenance exports, and separate local overrides.
- Safe bare-package and ZIP installation with path validation, `.partial`
  staging, SHA-256 verification, and atomic final placement.
- Verified archive export with portable JSON manifests and per-file checksums.
- Persistent resumable FTP upload/download jobs, partial-file recovery,
  bandwidth limits, verified final sizes, read-only console snapshots, and no
  stored passwords.
- Explicit external converter integration for user-owned ISO images.
- Read-only profile and save discovery with public STFS ownership metadata,
  masked identifiers, cached game-name resolution, duplicate and mismatch
  reporting, verified snapshots, manifests, and conflict-safe restore.
- Credited GPLv3 technical lineage from Dalavin / DJ SkunkieButt's X360
  library and Le Fluffie without bundling its updater, keys, or executable.
- Bounded read-only XDBF/GPD achievement inspection, profile comparison, and
  snapshot-first Xenia migration with non-overwriting verified copies.
- Per-property knowledge source priorities, recorded conflict decisions, and
  opt-in scheduled app-start refreshes.
- Feature-detected, opt-in remote SHA-256 verification for console FTP servers
  that expose a compatible read-only command.
- Local-by-default REST API with token-required remote binding, restricted
  browser origins, validated settings, and current version reporting.
- Cross-platform CI, Windows packaging checks, tagged release archives,
  SHA-256 checksums, CycloneDX SBOMs, and build-provenance attestations.
- Linux x86_64 packaging, XDG storage, application-menu integration, source
  launch scripts, and release artifacts.
- Repository contribution, security, architecture, API, and release
  documentation.
- Community Hub with unified search, typed knowledge extraction, guided console
  upload plans, package/profile workspaces, artwork and disc management,
  recoverable deduplication, storage audits, original Xbox discovery, plugin
  controls, recovery actions, dashboard probes, and accessibility preferences.
- Additive schema migration 8 and local audit history for every new workspace.
- Additive schema migration 9 for audited plugin collection and reversible
  duplicate actions, plus selectable restore controls.
- Additive schema migration 10 for metadata snapshots, library audits,
  preservation reports, correction exports, hardware records, and package extraction.
- Additive schema migration 11 for offline archive builds, rendered document
  state, and saved-page import history.
- Visual Studio 2010-inspired shared desktop theme, classic menus, scoped API
  tokens, out-of-process plugin execution, and bounded community language packs.
- Read-only consecutive STFS extraction, direct Xenia launch controls, and
  portable non-personal metadata distribution.
- Background Community Hub jobs, actionable unified-search navigation, CLI/API
  parity for search and preservation, FATX geometry reports, and bounded STFS
  file-table inventory.
- Windows, Linux, and unsigned Apple Silicon macOS CI packaging.

## Validation

- Offline tests cover scraper configuration, database behavior, ConsoleMods parsing,
  DAT parsing, wiki parsing, knowledge search/provenance, downloads, queueing,
  blocked-source recovery, saved-page rendering, STFS/XBE inspection, safe
  archives, backup scanning, atomic copies, and an end-to-end local workflow.
- Network-backed source syncs remain dependent on each source's availability and
  access policy. Cached copies are used when available.
- Windows, Linux, and macOS artifacts are generated by CI and releases
  rather than committed to the source tree.

## Deliberate Boundaries

- No commercial game images, firmware, keys, leaked SDK files, or other
  copyrighted payloads are bundled or downloaded.
- Redump and No-Intro DAT files must be obtained by the user from their source.
- Imported facts retain their source and conflicts are shown rather than silently
  discarded.
- Known local or XboxUnity title/publisher data is not replaced by fallback
  knowledge values.
- ISO conversion remains an external-tool boundary. UnityScraper does not
  implement copy-protection bypass or bundle third-party converter binaries.
- Traditional FTP is intended for trusted local networks. Passwords are kept in
  memory and omitted from database records.
- Remote API access requires a token but the built-in server does not provide
  TLS. Remote deployments need a trusted network or TLS reverse proxy.
- Profile editing, achievement modification, ownership rewriting, and CON
  re-signing remain disabled until complete package verification and reliable
  cross-platform signing support are available.
- FATX and raw-device access remains read-only. Duplicate actions retain a
  tracked quarantine copy with validated restoration, and console plans require
  explicit queue confirmation.

## Future Work

- Validate console resume and optional hash behavior against a broader matrix
  of real dashboard FTP servers.
- Add notarization and universal binaries after macOS signing infrastructure is
  available.
- Complete fragmented STFS block-chain traversal and hash-tree verification
  against independent real-package test vectors before considering mutation.
- Consider package mutation only after complete extraction, rehashing, signing,
  verification, and automatic recovery have independent test vectors.
