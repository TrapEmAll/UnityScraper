"""
Plugin System for UnityScraper
Allows custom metadata collectors and extensions
"""

import json
import logging
import hashlib
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from abc import ABC, abstractmethod
from pathlib import Path
from typing import List, Dict, Any, Optional, Mapping
import importlib.util
import sys
import threading
import subprocess
import tempfile

logger = logging.getLogger(__name__)
PLUGIN_API_VERSION = 1
PLUGIN_RESULT_LIMIT = 2 * 1024 * 1024
PLUGIN_TIMEOUT_SECONDS = 30


@dataclass(frozen=True)
class PluginManifest:
    """Stable v1 plugin contract. Plugin code is only loaded when enabled."""

    plugin_id: str
    name: str
    version: str
    api_version: int
    entrypoint: str
    permissions: tuple[str, ...] = ()

    @classmethod
    def load(cls, path: Path) -> "PluginManifest":
        data = json.loads(path.read_text(encoding="utf-8"))
        manifest = cls(
            plugin_id=str(data["id"]),
            name=str(data["name"]),
            version=str(data["version"]),
            api_version=int(data["api_version"]),
            entrypoint=str(data["entrypoint"]),
            permissions=tuple(str(value) for value in data.get("permissions", [])),
        )
        if manifest.api_version != PLUGIN_API_VERSION:
            raise ValueError(
                f"Plugin API {manifest.api_version} is unsupported; expected {PLUGIN_API_VERSION}"
            )
        if "/" in manifest.entrypoint or "\\" in manifest.entrypoint:
            raise ValueError("Plugin entrypoint must be a file in its plugin directory")
        return manifest


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_enabled_plugin_configuration(
    db_path: str | Path, plugin_dir: str | Path
) -> tuple[list[str], dict[str, str]]:
    """Return enabled plugin IDs whose entrypoint still matches its trusted hash."""
    database = Path(db_path)
    root = Path(plugin_dir)
    if not database.is_file() or not root.is_dir():
        return [], {}
    try:
        with closing(sqlite3.connect(database)) as connection:
            rows = connection.execute(
                "SELECT plugin_id, trusted_sha256 FROM plugin_states WHERE enabled=1"
            ).fetchall()
    except sqlite3.Error:
        return [], {}
    enabled: list[str] = []
    trusted: dict[str, str] = {}
    for plugin_id, expected_hash in rows:
        try:
            manifest = PluginManifest.load(root / plugin_id / "plugin.json")
            entry = root / plugin_id / manifest.entrypoint
            actual_hash = file_sha256(entry)
        except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
            logger.warning("Enabled plugin %s could not be validated: %s", plugin_id, exc)
            continue
        expected = str(expected_hash or "").casefold()
        if manifest.plugin_id != plugin_id or not expected or actual_hash.casefold() != expected:
            logger.warning("Enabled plugin %s changed after approval and was not loaded", plugin_id)
            continue
        enabled.append(plugin_id)
        trusted[plugin_id] = actual_hash
    return enabled, trusted


class MetadataCollectorPlugin(ABC):
    """Base class for custom metadata collector plugins"""
    
    def __init__(self):
        self.name = "Unknown Plugin"
        self.version = "1.0.0"
        self.description = "Custom metadata collector"
    
    @abstractmethod
    def collect(self, titleid: str) -> Dict[str, Any]:
        """
        Collect metadata for a TitleID
        
        Returns:
            Dictionary with 'covers' and 'updates' keys
        """
        pass
    
    @abstractmethod
    def validate_titleid(self, titleid: str) -> bool:
        """Check if TitleID is valid for this plugin"""
        pass


class PluginManager:
    """Manages loading and executing plugins"""
    
    def __init__(
        self,
        plugin_dir: str = "plugins",
        enabled_plugins: Optional[List[str]] = None,
        trusted_hashes: Optional[Mapping[str, str]] = None,
        allow_legacy: bool = False,
        isolated: bool = True,
    ):
        self.plugin_dir = Path(plugin_dir)
        self.plugins: Dict[str, MetadataCollectorPlugin] = {}
        self.manifests: Dict[str, PluginManifest] = {}
        self.plugin_ids_by_name: Dict[str, str] = {}
        self.plugin_locks: Dict[str, threading.Lock] = {}
        self.isolated_entries: Dict[str, tuple[PluginManifest, Path]] = {}
        self.enabled_plugins = set(enabled_plugins or [])
        self.trusted_hashes = dict(trusted_hashes or {})
        self.allow_legacy = allow_legacy
        self.isolated = isolated
        self._load_plugins()
    
    def _load_plugins(self):
        """Load all plugins from plugin directory"""
        if not self.plugin_dir.exists():
            logger.debug(f"Plugin directory not found: {self.plugin_dir}")
            return
        
        for manifest_path in self.plugin_dir.glob("*/plugin.json"):
            try:
                manifest = PluginManifest.load(manifest_path)
                self.manifests[manifest.plugin_id] = manifest
                if manifest.plugin_id in self.enabled_plugins:
                    entry = manifest_path.parent / manifest.entrypoint
                    expected = self.trusted_hashes.get(manifest.plugin_id)
                    if not expected or file_sha256(entry).casefold() != expected.casefold():
                        raise ValueError("Plugin entrypoint does not match its approved checksum")
                    if self.isolated:
                        self.isolated_entries[manifest.name] = (manifest, entry.resolve())
                        self.plugin_ids_by_name[manifest.name] = manifest.plugin_id
                        self.plugin_locks[manifest.name] = threading.Lock()
                    else:
                        self._load_plugin_file(entry, manifest)
            except Exception as e:
                logger.warning(f"Failed to load plugin {manifest_path}: {e}")
        if self.allow_legacy:
            for plugin_file in self.plugin_dir.glob("*.py"):
                if not plugin_file.name.startswith("_"):
                    self._load_plugin_file(plugin_file)
    
    def _load_plugin_file(
        self, file_path: Path, manifest: Optional[PluginManifest] = None
    ):
        """Load a single plugin file"""
        module_name = (
            "unityscraper_plugin_" + manifest.plugin_id.replace(".", "_").replace("-", "_")
            if manifest else file_path.stem
        )
        spec = importlib.util.spec_from_file_location(module_name, file_path)
        if spec and spec.loader:
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
            
            # Find and register MetadataCollectorPlugin subclasses
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if (isinstance(attr, type) and 
                    issubclass(attr, MetadataCollectorPlugin) and 
                    attr is not MetadataCollectorPlugin):
                    
                    instance = attr()
                    if manifest:
                        instance.name = manifest.name
                        instance.version = manifest.version
                        self.plugin_ids_by_name[instance.name] = manifest.plugin_id
                    self.plugins[instance.name] = instance
                    self.plugin_locks[instance.name] = threading.Lock()
                    logger.info(f"Loaded plugin: {instance.name} v{instance.version}")
    
    def get_plugin(self, name: str) -> Optional[MetadataCollectorPlugin]:
        """Get a plugin by name"""
        return self.plugins.get(name)
    
    def list_plugins(self) -> List[str]:
        """List all loaded plugins"""
        return list(self.plugins.keys())

    def list_available_plugins(self) -> List[Dict[str, Any]]:
        """List discovered plugins without importing disabled code."""
        return [
            {
                "id": manifest.plugin_id,
                "name": manifest.name,
                "version": manifest.version,
                "api_version": manifest.api_version,
                "permissions": list(manifest.permissions),
                "enabled": manifest.plugin_id in self.enabled_plugins,
                "loaded": manifest.name in self.plugins,
                "isolated": manifest.name in self.isolated_entries,
            }
            for manifest in self.manifests.values()
        ]
    
    def collect_from_plugin(self, plugin_name: str, titleid: str) -> Optional[Dict[str, Any]]:
        """Collect metadata using specific plugin"""
        plugin = self.get_plugin(plugin_name)
        if not plugin:
            logger.error(f"Plugin not found: {plugin_name}")
            return None
        
        if not plugin.validate_titleid(titleid):
            logger.warning(f"Plugin {plugin_name} does not support TitleID: {titleid}")
            return None
        
        try:
            return plugin.collect(titleid)
        except Exception as e:
            logger.error(f"Plugin {plugin_name} failed: {e}")
            return None

    def collect_enabled(self, titleid: str) -> List[Dict[str, Any]]:
        """Run enabled collectors independently and retain success/failure details."""
        results: List[Dict[str, Any]] = []
        names = list(dict.fromkeys([*self.plugins, *self.isolated_entries]))
        for name in names:
            plugin_id = self.plugin_ids_by_name.get(name, name)
            try:
                with self.plugin_locks[name]:
                    if name in self.isolated_entries:
                        isolated = self._collect_isolated(name, titleid)
                        if isolated["status"] != "completed":
                            results.append({"plugin_id": plugin_id, "name": name, **isolated})
                            continue
                        data = isolated["data"]
                    else:
                        plugin = self.plugins[name]
                        if not plugin.validate_titleid(titleid):
                            results.append({"plugin_id": plugin_id, "name": name,
                                            "status": "skipped"})
                            continue
                        data = plugin.collect(titleid)
                if not isinstance(data, dict):
                    raise TypeError("Plugin collect() must return a dictionary")
                encoded = json.dumps(data, default=str)
                if len(encoded.encode("utf-8")) > PLUGIN_RESULT_LIMIT:
                    raise ValueError("Plugin result exceeds the 2 MiB safety limit")
            except Exception as exc:
                logger.exception("Plugin %s failed for %s", plugin_id, titleid)
                results.append({"plugin_id": plugin_id, "name": name,
                                "status": "failed", "error": str(exc)})
            else:
                results.append({"plugin_id": plugin_id, "name": name,
                                "status": "completed", "data": data})
        return results

    def _collect_isolated(self, name: str, titleid: str) -> Dict[str, Any]:
        manifest, entry = self.isolated_entries[name]
        worker = Path(__file__).resolve().with_name("plugin_worker.py")
        if getattr(sys, "frozen", False):
            command = [
                sys.executable, "--plugin-worker", str(entry), titleid,
            ]
        else:
            command = [
                sys.executable, str(worker), str(entry), titleid,
            ]
        with tempfile.TemporaryDirectory(prefix="unityscraper-plugin-") as temp:
            output = Path(temp) / "result.json"
            command.append(str(output))
            try:
                subprocess.run(
                    command,
                    cwd=str(entry.parent),
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=PLUGIN_TIMEOUT_SECONDS,
                    check=False,
                )
            except subprocess.TimeoutExpired:
                return {"status": "failed", "error": "Plugin execution timed out"}
            if not output.is_file():
                return {"status": "failed", "error": "Plugin worker returned no result"}
            if output.stat().st_size > PLUGIN_RESULT_LIMIT:
                return {"status": "failed", "error": "Plugin result exceeds safety limit"}
            try:
                payload = json.loads(output.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                return {"status": "failed", "error": f"Invalid plugin result: {exc}"}
            if not isinstance(payload, dict) or payload.get("status") not in {
                "completed", "skipped", "failed"
            }:
                return {"status": "failed", "error": "Plugin returned an invalid status"}
            if payload.get("status") == "failed":
                payload["error"] = str(payload.get("error", "Plugin failed"))[:1000]
            payload["worker"] = "isolated-process"
            payload["plugin_id"] = manifest.plugin_id
            return payload


# Example plugin template (to be saved in plugins/example.py)
EXAMPLE_PLUGIN_TEMPLATE = '''
"""Example custom metadata collector plugin"""
from plugins import MetadataCollectorPlugin
import logging

logger = logging.getLogger(__name__)


class CustomCollector(MetadataCollectorPlugin):
    """Example custom metadata collector"""
    
    def __init__(self):
        super().__init__()
        self.name = "CustomCollector"
        self.version = "1.0.0"
        self.description = "Collects metadata from custom sources"
    
    def validate_titleid(self, titleid: str) -> bool:
        """Check if TitleID format is valid"""
        return len(titleid) == 8 and titleid.isalnum()
    
    def collect(self, titleid: str):
        """Collect metadata for TitleID"""
        # Your custom implementation here
        return {
            "covers": [],
            "updates": []
        }
'''
