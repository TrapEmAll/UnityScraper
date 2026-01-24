"""
Plugin System for UnityScraper
Allows custom metadata collectors and extensions
"""

import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import List, Dict, Any, Optional
import importlib.util
import sys

logger = logging.getLogger(__name__)


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
    
    def __init__(self, plugin_dir: str = "plugins"):
        self.plugin_dir = Path(plugin_dir)
        self.plugins: Dict[str, MetadataCollectorPlugin] = {}
        self._load_plugins()
    
    def _load_plugins(self):
        """Load all plugins from plugin directory"""
        if not self.plugin_dir.exists():
            logger.debug(f"Plugin directory not found: {self.plugin_dir}")
            return
        
        for plugin_file in self.plugin_dir.glob("*.py"):
            if plugin_file.name.startswith("_"):
                continue
            
            try:
                self._load_plugin_file(plugin_file)
            except Exception as e:
                logger.warning(f"Failed to load plugin {plugin_file.name}: {e}")
    
    def _load_plugin_file(self, file_path: Path):
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
                    self.plugins[instance.name] = instance
                    logger.info(f"Loaded plugin: {instance.name} v{instance.version}")
    
    def get_plugin(self, name: str) -> Optional[MetadataCollectorPlugin]:
        """Get a plugin by name"""
        return self.plugins.get(name)
    
    def list_plugins(self) -> List[str]:
        """List all loaded plugins"""
        return list(self.plugins.keys())
    
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
