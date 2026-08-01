"""Out-of-process metadata plugin worker used by PluginManager."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

from plugins import MetadataCollectorPlugin


MAX_RESULT_BYTES = 2 * 1024 * 1024


def _limits() -> None:
    if os.name == "nt":
        return
    try:
        import resource

        resource.setrlimit(resource.RLIMIT_CPU, (20, 20))
        resource.setrlimit(resource.RLIMIT_AS, (256 * 1024 * 1024, 256 * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_FSIZE, (4 * 1024 * 1024, 4 * 1024 * 1024))
    except (ImportError, OSError, ValueError):
        pass


def run(entrypoint: Path, titleid: str, output_path: Path) -> None:
    _limits()
    spec = importlib.util.spec_from_file_location("unityscraper_isolated_plugin", entrypoint)
    if spec is None or spec.loader is None:
        raise RuntimeError("Plugin entrypoint could not be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    plugin_type = next(
        (
            value for value in vars(module).values()
            if isinstance(value, type)
            and issubclass(value, MetadataCollectorPlugin)
            and value is not MetadataCollectorPlugin
        ),
        None,
    )
    if plugin_type is None:
        raise RuntimeError("Plugin exports no MetadataCollectorPlugin subclass")
    plugin = plugin_type()
    if not plugin.validate_titleid(titleid):
        payload = {"status": "skipped"}
    else:
        result = plugin.collect(titleid)
        if not isinstance(result, dict):
            raise TypeError("Plugin collect() must return a dictionary")
        payload = {"status": "completed", "data": result}
    encoded = json.dumps(payload, default=str).encode("utf-8")
    if len(encoded) > MAX_RESULT_BYTES:
        raise ValueError("Plugin result exceeds the 2 MiB safety limit")
    temporary = output_path.with_suffix(".partial")
    temporary.write_bytes(encoded)
    temporary.replace(output_path)


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if len(arguments) != 3:
        return 2
    entrypoint, titleid, output = arguments
    try:
        run(Path(entrypoint).resolve(), titleid, Path(output).resolve())
    except Exception as exc:
        encoded = json.dumps({"status": "failed", "error": str(exc)}).encode("utf-8")
        if len(encoded) <= MAX_RESULT_BYTES:
            Path(output).write_bytes(encoded)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
