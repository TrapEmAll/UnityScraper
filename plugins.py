"""
Plugin System for UnityScraper
Allows custom metadata collectors and extensions
"""

import json
import logging
from dataclasses import dataclass
from abc import ABC, abstractmethod
from pathlib import Path
from typing import List, Dict, Any, Optional
import importlib.util
import sys

logger = logging.getLogger(__name__)
PLUGIN_API_VERSION = 1


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
        allow_legacy: bool = False,
    ):
        self.plugin_dir = Path(plugin_dir)
        self.plugins: Dict[str, MetadataCollectorPlugin] = {}
        self.manifests: Dict[str, PluginManifest] = {}
        self.enabled_plugins = set(enabled_plugins or [])
        self.allow_legacy = allow_legacy
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
                    self._load_plugin_file(manifest_path.parent / manifest.entrypoint, manifest)
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
        spec = importlib.util.spec_from_file_location(file_path.stem, file_path)
        if spec and spec.loader:
            module = importlib.util.module_from_spec(spec)
            sys.modules[file_path.stem] = module
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
                    self.plugins[instance.name] = instance
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
