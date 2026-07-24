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

The entrypoint exports a `MetadataCollectorPlugin` subclass. The caller must
pass the plugin ID in `enabled_plugins` before code is loaded. Permissions
are disclosure metadata, not an operating-system sandbox, so only enable
plugins whose source and publisher you trust.

Root-level legacy Python plugins load only with `allow_legacy=True`.
