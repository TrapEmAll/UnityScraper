# Plugin API v1

Metadata collectors use a manifest-based, opt-in API. Disabled plugin code is
discovered but never imported.

```text
plugins/
  example/
    plugin.json
    collector.py
```

```json
{
  "id": "org.example.collector",
  "name": "Example Collector",
  "version": "1.0.0",
  "api_version": 1,
  "entrypoint": "collector.py",
  "permissions": ["network"]
}
```

The entrypoint exports a `MetadataCollectorPlugin` subclass. Desktop installs
live in the managed application plugin directory and begin disabled. Enabling a
plugin records its SHA-256 checksum; normal metadata collection loads it only
while the manifest ID and approved checksum still match. Each result is limited
to 2 MiB, cover/update counts are bounded, failures are isolated, and every run
is audited in SQLite. Known title and publisher values are never replaced by a
plugin fallback.

Requested access is disclosure metadata, not an operating-system sandbox.
Plugin code executes with the user's account permissions, so only enable source
and publishers you trust. Editing an enabled entrypoint automatically prevents
it from loading until it is reviewed and enabled again.

Root-level legacy Python plugins load only with `allow_legacy=True`.
