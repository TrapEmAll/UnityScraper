"""
Auto-update checker for UnityScraper
Checks for new versions and notifies user
"""

import logging
import requests
import json
from pathlib import Path
from typing import Optional, Dict, Tuple
from packaging import version
from app_version import APP_VERSION

logger = logging.getLogger(__name__)

CURRENT_VERSION = APP_VERSION

# GitHub release API endpoint
GITHUB_API_URL = "https://api.github.com/repos/TrapEmAll/UnityScraper/releases/latest"

# Alternative: version file URL (simpler, doesn't require GitHub API)
VERSION_FILE_URL = "https://raw.githubusercontent.com/TrapEmAll/UnityScraper/main/VERSION"


class VersionChecker:
    """Check for new versions of UnityScraper"""
    
    def __init__(self, timeout: int = 5):
        self.timeout = timeout
        self.current_version = CURRENT_VERSION
    
    def check_for_updates(self) -> Tuple[bool, Optional[Dict]]:
        """
        Check if newer version is available
        Returns (has_update, version_info)
        """
        try:
            # Try GitHub API first
            update_info = self._check_github_api()
            if update_info:
                return True, update_info
            
            # Fallback to version file
            update_info = self._check_version_file()
            if update_info:
                return True, update_info
            
            logger.info("Already on latest version")
            return False, None
            
        except Exception as e:
            logger.warning(f"Failed to check for updates: {e}")
            return False, None
    
    def _check_github_api(self) -> Optional[Dict]:
        """Check GitHub releases API"""
        try:
            response = requests.get(GITHUB_API_URL, timeout=self.timeout)
            response.raise_for_status()
            
            data = response.json()
            latest_version = data.get('tag_name', '').lstrip('v')
            
            if not latest_version:
                return None
            
            if version.parse(latest_version) > version.parse(self.current_version):
                return {
                    'version': latest_version,
                    'name': data.get('name'),
                    'body': data.get('body'),
                    'download_url': data.get('html_url'),
                    'published_at': data.get('published_at'),
                    'source': 'github'
                }
        except Exception as e:
            logger.debug(f"GitHub API check failed: {e}")
        
        return None
    
    def _check_version_file(self) -> Optional[Dict]:
        """Check version file from repository"""
        try:
            response = requests.get(VERSION_FILE_URL, timeout=self.timeout)
            response.raise_for_status()
            
            data = response.json()
            latest_version = data.get('version')
            
            if not latest_version:
                return None
            
            if version.parse(latest_version) > version.parse(self.current_version):
                return {
                    'version': latest_version,
                    'name': data.get('name'),
                    'changes': data.get('changes'),
                    'download_url': data.get('download_url'),
                    'release_date': data.get('release_date'),
                    'source': 'version_file'
                }
        except Exception as e:
            logger.debug(f"Version file check failed: {e}")
        
        return None
    
    def get_current_version(self) -> str:
        """Get current installed version"""
        return self.current_version
    
    @staticmethod
    def format_update_message(update_info: Dict) -> str:
        """Format update notification message"""
        msg = f"New version {update_info['version']} available!\n\n"
        if update_info.get('name'):
            msg += f"Name: {update_info['name']}\n"
        if update_info.get('body'):
            msg += f"Changes:\n{update_info['body'][:500]}...\n\n"
        elif update_info.get('changes'):
            msg += f"Changes:\n{update_info['changes'][:500]}...\n\n"
        msg += f"Download: {update_info.get('download_url', 'N/A')}"
        return msg


# Example usage for command-line
if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    
    checker = VersionChecker()
    has_update, info = checker.check_for_updates()
    
    if has_update and info is not None:
        print(VersionChecker.format_update_message(info))
    else:
        print(f"Running latest version: {checker.get_current_version()}")
