# Modularization Plan

UnityScraper is moving toward a modular monolith: one local desktop-first
application, with feature domains that own their models, services, schema,
commands, tests, and UI adapters.

The current top-level modules remain supported while code moves into the
`unityscraper` package incrementally.

## Target Shape

```text
unityscraper/
  app/
    desktop/
    cli/
    api/
  core/
    db/
    jobs.py
    paths.py
  domains/
    library/
    knowledge/
    backups/
    profiles/
    packages/
    collections/
    console_sync/
    tools/
    plugins/
```

## Boundaries

- `unityscraper.app` adapts desktop, CLI, and REST entry points.
- `unityscraper.core` holds shared infrastructure that has no Xbox-specific
  product behavior.
- `unityscraper.domains` holds feature behavior and should avoid importing UI
  modules.
- Top-level modules are compatibility shims or legacy implementations until
  their behavior is moved behind domain packages.

## Domain Rules

Each domain should grow toward this internal layout:

```text
domain/
  models.py
  service.py
  repository.py
  commands.py
  api.py
  migrations.py
  ui.py
```

- `models.py` contains dataclasses, enums, and validation types.
- `service.py` owns business workflows.
- `repository.py` owns SQLite access for that domain.
- `commands.py` exposes UI-neutral use cases for CLI, REST, and desktop jobs.
- `api.py` adapts use cases to HTTP only.
- `ui.py` adapts use cases to Tk only.
- `migrations.py` registers additive schema changes through
  `unityscraper.core.db.MigrationRegistry`.

## Migration Order

1. Keep existing entry points working.
2. Add package-facing adapters for existing services.
3. Move pure models and parsing helpers first.
4. Move repositories and schema ownership next.
5. Move command handlers after services are UI-neutral.
6. Split large UI pages only after their services are stable.

## Current Progress

- `unityscraper.core.paths` owns application storage and resource resolution;
  `app_paths.py` is a compatibility wrapper.
- `unityscraper.core.version` owns version constants; `app_version.py` is a
  compatibility wrapper.
- `unityscraper.core.metadata` exposes app name, slug, and version metadata for
  UI, CLI, API, diagnostics, and packaging.
- `unityscraper.app.cli` has a command registry and lazy legacy CLI adapter so
  package command discovery does not import the full scraper runtime.
- `unityscraper.domains.packages` exposes read-only package models and
  inspectors.
- `unityscraper.domains.packages.commands` exposes the first UI-neutral
  package use cases for STFS inspection and file-table inventory.
- `unityscraper.domains.backups` exposes backup models and operations.
- `unityscraper.domains.backups.migrations` owns the backup schema function;
  `backup_service.ensure_backup_schema` remains import-compatible.
- `unityscraper.domains.profiles` exposes profile/save models and helpers.

## Feature Ownership

| Domain | Owns |
| --- | --- |
| `library` | XboxUnity titles, covers, title updates, local library search |
| `knowledge` | source-attributed facts, citations, conflicts, offline archive |
| `backups` | owned-content inventory, import, export, verification, FTP-safe flows |
| `profiles` | profile/save discovery, snapshots, restore, achievement inspection |
| `packages` | STFS, XEX, XBE inspection and read-only extraction |
| `collections` | preservation matching, DAT checks, health reports, repair previews |
| `console_sync` | console inventories, durable transfer plans, dashboard capabilities |
| `tools` | external executable catalog, argument templates, captured execution |
| `plugins` | opt-in collectors, trust state, isolated plugin runs |

## Long-Term AIO Rule

New Xbox 360 capabilities should enter as domain use cases first. Desktop
buttons, REST routes, and CLI flags should call those use cases rather than
owning file, database, FTP, or package logic themselves.
