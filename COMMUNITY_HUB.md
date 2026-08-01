# Community Hub

The Community Hub brings the wider Xbox and preservation workflows into one
source-attributed, offline-capable workspace. Open it from the desktop sidebar
or press `Ctrl+K` to focus unified search.

## Twenty Integrated Capabilities

1. Unified local search across games, identifiers, wiki knowledge, profiles,
   saves, achievements, files, and structured reference records.
2. Structured extraction of motherboards, DVD drives, dashboards, exploits,
   errors, formats, repairs, and tools from cached source documents.
3. Guided PC-to-console comparison using a captured, read-only console
   inventory and Aurora, Freestyle Dash, XeXMenu, or stock layouts.
4. Explicit queueing of revalidated uploads into the existing persistent,
   resumable transfer queue. A preview never starts a transfer by itself.
5. Profile dashboards summarizing saves, played titles, achievements, and
   gamerscore from local data.
6. Read-only STFS package inspection and auditable package workspaces that keep
   an untouched original and manifest.
7. Ownership-migration previews that record intended profile, console, and
   device changes without changing or signing the package.
8. Block-level save comparisons with SHA-256 results and durable audit history.
9. XDBF/GPD played-title history and bounded embedded-image discovery.
10. Validated export of an embedded GPD image without modifying its source.
11. Preferred artwork selection with Aurora, Freestyle Dash, and preservation
    archive export layouts plus checksum manifests.
12. Multi-disc completeness audits based on scanned disc number and count.
13. Duplicate previews using size grouping and SHA-256 verification.
14. Selectable, recoverable duplicate actions that quarantine the original,
    optionally create a verified hardlink, and restore from the interface.
15. Read-only FATX partition geometry, Xbox 360 USB container, and mounted-storage audits.
16. Original Xbox `default.xbe` discovery alongside Xbox 360 collections.
17. Plugin discovery, checksums, permission display, enable/disable state, and
    bounded ZIP installation or update with rollback.
18. Recovery scans for partial files, interrupted jobs, incomplete snapshots,
    and failed operations, with conservative retry or quarantine actions.
19. Dashboard compatibility probes for login, content-root access, resume, and
    advertised remote hash support on a trusted local FTP network.
20. Cross-platform accessibility and packaging: scalable text, high contrast,
    reduced-motion preferences, keyboard hints, and Windows, Linux, and macOS
    build paths.

## Safety Rules

- Sync plans are previews until the user confirms queueing. Queued jobs still
  run through the normal transfer controls.
- Duplicate cleanup never deletes the only retained copy. Quarantined files
  remain under `.unityscraper-dedup-quarantine` and can be restored from the
  Preservation tab after checksum and path validation.
- FATX images are detected read-only. Raw-device and raw-image writes are not
  implemented.
- Package workspaces and ownership changes are previews. CON/LIVE/PIRS rebuild,
  rehash, signature, and ownership mutation remain disabled until independent
  verification and recovery are complete.
- Traditional console FTP is unencrypted and is intended only for a trusted
  local network.
- XboxUnity remains HTTP-only. This application does not invent or prefer an
  HTTPS endpoint for XboxUnity.

## Data and Provenance

Migration 8 adds durable records for structured knowledge, sync plans, profile
previews, played titles, embedded images, save comparisons, artwork exports,
disc audits, dedup plans, storage audits, original Xbox records, plugin state,
recovery events, dashboard tests, and accessibility preferences. It is additive
and preserves existing databases.

Migration 9 adds plugin collection audits and duplicate-recovery records. Enabled
plugins run during normal metadata collection only while their approved entrypoint
checksum still matches. Long Community Hub operations run in a background worker;
search results can be opened with Enter or a double-click.

Imported ConsoleMods, XenonLibrary, Free60, Redump, and No-Intro information
continues to retain source, revision, citation, licensing, and conflict data.
Redump and No-Intro DAT files remain user-supplied; copyrighted game content is
never included.

## Platform Notes

Windows and Linux remain the primary tested release targets. macOS CI builds an
unsigned Apple Silicon application bundle and checksum. The macOS artifact is
not notarized, and the documentation does not ask users to disable Gatekeeper.
See [MACOS.md](MACOS.md) for current limitations.
