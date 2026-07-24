"""
Auto-update checker for UnityScraper
Checks for new versions and notifies user
"""

import logging
import requests
import json
import hashlib
import platform
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
                asset = self.select_asset(data.get("assets", []))
                return {
                    'version': latest_version,
                    'name': data.get('name'),
                    'body': data.get('body'),
                    'download_url': asset.get("browser_download_url") if asset else data.get('html_url'),
                    'asset': asset,
                    'published_at': data.get('published_at'),
                    'source': 'github'
                }
        except Exception as e:
            logger.debug(f"GitHub API check failed: {e}")
        
        return None

    @staticmethod
    def select_asset(assets: list[Dict], system: str | None = None) -> Optional[Dict]:
        """Choose the packaged release matching the current desktop platform."""
        current = (system or platform.system()).casefold()
        machine = platform.machine().casefold()
        preferred = []
        if current == "windows":
            preferred = ["windows-x64.zip", "windows"]
        elif current == "linux":
            preferred = ["linux-x86_64.tar.gz", "linux"]
        elif current == "darwin":
            preferred = ["macos", "darwin"]
        for suffix in preferred:
            for asset in assets:
                name = str(asset.get("name", "")).casefold()
                if suffix in name and not name.endswith(".sha256"):
                    if "arm" not in name or "arm" in machine or "aarch64" in machine:
                        return asset
        return None

    def download_verified_update(
        self, update_info: Dict, destination: str | Path
    ) -> Path:
        """Download a selected package and require its published SHA-256 sidecar."""
        asset = update_info.get("asset")
        if not asset or not asset.get("browser_download_url"):
            raise ValueError("No packaged update is available for this platform")
        target_dir = Path(destination)
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / asset["name"]
        self._download(asset["browser_download_url"], target)

        checksum_url = asset["browser_download_url"] + ".sha256"
        checksum_response = requests.get(checksum_url, timeout=self.timeout)
        checksum_response.raise_for_status()
        expected = checksum_response.text.strip().split()[0].lower()
        if len(expected) != 64:
            target.unlink(missing_ok=True)
            raise ValueError("Release checksum is malformed")
        hasher = hashlib.sha256()
        with target.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                hasher.update(chunk)
        digest = hasher.hexdigest()
        if digest != expected:
            target.unlink(missing_ok=True)
            raise ValueError("Downloaded update failed SHA-256 verification")
        return target

    def _download(self, url: str, target: Path) -> None:
        temporary = target.with_suffix(target.suffix + ".partial")
        with requests.get(url, timeout=self.timeout, stream=True) as response:
            response.raise_for_status()
            with temporary.open("wb") as handle:
                for chunk in response.iter_content(1024 * 1024):
                    if chunk:
                        handle.write(chunk)
        temporary.replace(target)
    
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
