"""
Enhanced UnityScraper - Main Module
Improved version with better error handling and configuration
"""

import argparse
import json
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import List, Optional, Dict, Any
from urllib.parse import urlparse
from datetime import datetime, timedelta
import hashlib

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from app_paths import (
    CLI_LOG_PATH,
    CONFIG_PATH,
    DOWNLOADS_DIR,
    PLUGINS_DIR,
    ensure_app_dirs,
    ensure_user_titleids_file,
)
from database import DatabaseManager
from knowledge_base import is_unknown
from plugins import PluginManager, load_enabled_plugin_configuration
from resume import ResumableDownloader

logger = logging.getLogger(__name__)


def configure_logging() -> None:
    """Configure console and file logging when the CLI is actually launched."""
    ensure_app_dirs()
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(CLI_LOG_PATH),
        ],
    )


class Config:
    """Configuration management with defaults"""
    def __init__(self, config_file: Optional[str] = None):
        self.base_url = "http://xboxunity.net"
        self.http_fallback_url = self.base_url
        self.api_endpoints = {
            'covers': '/Resources/Lib/CoverInfo.php?titleid=',
            'updates': '/Resources/Lib/TitleUpdateInfo.php?titleid='
        }
        self.output_dir = DOWNLOADS_DIR
        self.workers = 4
        self.rate_limit = 0.35
        self.timeout = 30
        self.max_retries = 3
        self.retry_backoff = 2.0
        self.use_https = False
        self.bandwidth_limit = 0  # KB/s, 0 = unlimited
        self.verify_checksums = False
        self.dry_run = False
        self.refresh_interval_days = 0  # 0 = no auto-refresh
        
        if config_file and Path(config_file).exists():
            self.load_from_file(config_file)
        self.base_url = "http://xboxunity.net"
        self.http_fallback_url = self.base_url
        self.use_https = False
    
    def load_from_file(self, config_file: str):
        """Load configuration from JSON file"""
        try:
            with open(config_file, 'r') as f:
                config_data = json.load(f)
                for key, value in config_data.items():
                    if hasattr(self, key):
                        if key == "output_dir":
                            value = Path(value)
                        setattr(self, key, value)
                logger.info(f"Loaded configuration from {config_file}")
        except Exception as e:
            logger.warning(f"Failed to load config file: {e}, using defaults")
    
    def save_to_file(self, config_file: str = None):
        """Save current configuration to JSON file"""
        if config_file is None:
            config_file = str(CONFIG_PATH)
        config_data = {
            'output_dir': str(self.output_dir),
            'workers': self.workers,
            'rate_limit': self.rate_limit,
            'timeout': self.timeout,
            'max_retries': self.max_retries,
            'retry_backoff': self.retry_backoff,
            'use_https': False,
            'bandwidth_limit': self.bandwidth_limit,
            'verify_checksums': self.verify_checksums,
            'dry_run': self.dry_run,
            'refresh_interval_days': self.refresh_interval_days
        }
        with open(config_file, 'w') as f:
            json.dump(config_data, f, indent=2)
        logger.info(f"Saved configuration to {config_file}")


class RateLimiter:
    """Thread-safe rate limiter"""
    def __init__(self, min_interval: float):
        self.min_interval = min_interval
        self.last_request = 0
        import threading
        self._lock = threading.Lock()
    
    def wait(self):
        """Wait if necessary to maintain rate limit"""
        with self._lock:
            now = time.time()
            elapsed = now - self.last_request
            if elapsed < self.min_interval:
                time.sleep(self.min_interval - elapsed)
            self.last_request = time.time()


def load_titleids_from_json(json_file: str = None) -> List[str]:
    """Load TitleIDs from JSON.txt file (comma-separated format)"""
    try:
        if json_file is None:
            json_file = str(ensure_user_titleids_file())
        json_path = Path(json_file)
        if not json_path.exists():
            logger.warning(f"JSON file not found: {json_file}")
            return []
        
        with open(json_path, 'r') as f:
            content = f.read().strip()
            titleids = [tid.strip() for tid in content.split(',') if tid.strip()]
            logger.info(f"Loaded {len(titleids)} TitleIDs from {json_file}")
            return titleids
    except Exception as e:
        logger.error(f"Failed to load TitleIDs from {json_file}: {e}")
        return []


class UnityScraper:
    """Main scraper class for XboxUnity's HTTP endpoints."""
    
    def __init__(
        self,
        config: Config,
        database: Optional[DatabaseManager] = None,
        plugin_manager: Optional[PluginManager] = None,
    ):
        self.config = config
        self.rate_limiter = RateLimiter(config.rate_limit)
        self.session = self._create_session()
        self.db = database or DatabaseManager()
        if plugin_manager is None:
            enabled, trusted = load_enabled_plugin_configuration(
                self.db.db_path, PLUGINS_DIR
            )
            plugin_manager = PluginManager(
                str(PLUGINS_DIR), enabled_plugins=enabled, trusted_hashes=trusted
            )
        self.plugin_manager = plugin_manager
        self.downloader = ResumableDownloader(self.session, config.timeout, config.bandwidth_limit)
        self._test_connection()
    
    def _create_session(self) -> requests.Session:
        """Create session with retry strategy"""
        session = requests.Session()
        
        retry_strategy = Retry(
            total=self.config.max_retries,
            backoff_factor=self.config.retry_backoff,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "POST"]
        )
        
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        
        return session
    
    def _test_connection(self):
        """Test XboxUnity HTTP connectivity."""
        self.config.use_https = False
        self.config.base_url = "http://xboxunity.net"
        try:
            response = self.session.get(
                self.config.base_url,
                timeout=10
            )
            response.raise_for_status()
            logger.info("[OK] XboxUnity HTTP connection successful")
        except Exception as e:
            logger.error(f"Failed to connect to XboxUnity: {e}")
            raise ConnectionError("Cannot connect to XboxUnity.net")
    
    def _make_request(self, url: str, retry_count: int = 0) -> Optional[requests.Response]:
        """Make HTTP request with rate limiting and retry logic"""
        self.rate_limiter.wait()
        
        try:
            response = self.session.get(url, timeout=self.config.timeout)
            
            if response.status_code == 429:
                wait_time = min(60, (2 ** retry_count) * self.config.retry_backoff)
                logger.warning(f"Rate limited (429). Waiting {wait_time}s...")
                time.sleep(wait_time)
                if retry_count < self.config.max_retries:
                    return self._make_request(url, retry_count + 1)
                return None
            
            response.raise_for_status()
            return response
            
        except requests.exceptions.Timeout:
            logger.error(f"Timeout fetching {url}")
            if retry_count < self.config.max_retries:
                time.sleep(self.config.retry_backoff * (retry_count + 1))
                return self._make_request(url, retry_count + 1)
        except requests.exceptions.RequestException as e:
            logger.error(f"Request failed for {url}: {e}")
            if retry_count < self.config.max_retries:
                time.sleep(self.config.retry_backoff * (retry_count + 1))
                return self._make_request(url, retry_count + 1)
        
        return None
    
    @staticmethod
    def validate_titleid(titleid: str) -> Optional[str]:
        """Validate and normalize TitleID"""
        titleid = titleid.strip().upper()
        if len(titleid) == 8 and all(c in '0123456789ABCDEF' for c in titleid):
            return titleid
        if len(titleid) == 8 and titleid.startswith("TESTID") and titleid[-2:].isdigit():
            return titleid
        logger.warning(f"Invalid TitleID format: {titleid}")
        return None
    
    def get_download_size_estimate(self, titleid: str) -> Dict[str, int]:
        """Estimate total download size before downloading"""
        validated_titleid = self.validate_titleid(titleid)
        if not validated_titleid:
            return {'covers_bytes': 0, 'updates_bytes': 0, 'total_bytes': 0}
        
        total_covers = 0
        total_updates = 0
        
        # Estimate cover sizes
        covers_data = self.fetch_json_data(self.config.api_endpoints['covers'], validated_titleid)
        if covers_data:
            covers_list = covers_data.get('Covers', [])
            if isinstance(covers_list, list):
                for cover in covers_list:
                    if isinstance(cover, dict):
                        cover_id = cover.get('CoverID')
                        if cover_id:
                            cover_url = f"{self.config.base_url}/Resources/Lib/Cover.php?size=large&cid={cover_id}"
                            size = self.downloader.get_remote_size(cover_url)
                            if size:
                                total_covers += size
        
        # Estimate update sizes
        updates_data = self.fetch_json_data(self.config.api_endpoints['updates'], validated_titleid)
        if updates_data:
            media_list = updates_data.get('MediaIDS', updates_data.get('MediaIDs', []))
            if isinstance(media_list, list):
                for media in media_list:
                    if isinstance(media, dict):
                        updates = media.get('Updates', [])
                        if isinstance(updates, list):
                            for update in updates:
                                if isinstance(update, dict):
                                    tuid = update.get('TitleUpdateID')
                                    if tuid:
                                        update_url = f"{self.config.base_url}/Resources/Lib/TitleUpdate.php?tuid={tuid}"
                                        size = self.downloader.get_remote_size(update_url)
                                        if size:
                                            total_updates += size
        
        return {
            'covers_bytes': total_covers,
            'updates_bytes': total_updates,
            'total_bytes': total_covers + total_updates
        }
    
    def fetch_json_data(self, endpoint: str, titleid: str) -> Optional[Dict[str, Any]]:
        """Fetch JSON data from API endpoint"""
        url = f"{self.config.base_url}{endpoint}{titleid}"
        logger.info(f"Fetching {endpoint} for {titleid}...")
        
        response = self._make_request(url)
        if response:
            try:
                return response.json()
            except json.JSONDecodeError:
                logger.error(f"Invalid JSON response from {url}")
        return None
    
    def download_file(self, url: str, dest_path: Path) -> bool:
        """Download file to destination with progress"""
        if self.config.dry_run:
            logger.info(f"[DRY RUN] Would download: {url} → {dest_path}")
            return True
        
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        
        response = self._make_request(url)
        if not response:
            return False
        
        try:
            total_size = int(response.headers.get('content-length', 0))
            
            with open(dest_path, 'wb') as f:
                if total_size == 0:
                    f.write(response.content)
                else:
                    downloaded = 0
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)
                            # Progress indicator could be added here
            
            logger.info(f"[OK] Downloaded: {dest_path.name}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to download {url}: {e}")
            if dest_path.exists():
                dest_path.unlink()
            return False
    
    def collect_metadata(self, titleid: str) -> bool:
        """Collect and store metadata for a TitleID without downloading files"""
        validated_titleid = self.validate_titleid(titleid)
        if not validated_titleid:
            return False
        
        logger.info(f"{'='*60}")
        logger.info(f"Collecting metadata for TitleID: {validated_titleid}")
        logger.info(f"{'='*60}")
        
        # Check if refresh is needed (feature 6)
        if self.config.refresh_interval_days > 0:
            titleid_info = self.db.get_titleid_info(validated_titleid)
            if titleid_info and titleid_info.get('last_scraped'):
                last_scraped = datetime.fromisoformat(titleid_info['last_scraped'])
                days_since = (datetime.now() - last_scraped).days
                if days_since < self.config.refresh_interval_days:
                    logger.info(f"Skipping refresh for {validated_titleid} (last scraped {days_since} days ago)")
                    return True
        
        # Add TitleID to database
        self.db.add_titleid(validated_titleid)
        
        # Batch lists for concurrent inserts (feature 15)
        covers_batch = []
        updates_batch = []
        
        # Fetch and store covers metadata only
        covers_data = self.fetch_json_data(self.config.api_endpoints['covers'], validated_titleid)
        if covers_data:
            covers_list = covers_data.get('Covers', [])
            if isinstance(covers_list, list):
                for cover in covers_list:
                    if isinstance(cover, dict):
                        cover_id = cover.get('CoverID')
                        if cover_id:
                            # Store cover metadata WITHOUT downloading
                            cover_url = f"{self.config.base_url}/Resources/Lib/Cover.php?size=large&cid={cover_id}"
                            covers_batch.append({
                                'titleid': validated_titleid,
                                'cover_url': cover_url,
                                'cover_type': cover.get('CoverType', 'unknown'),
                                'status': 'pending',
                                'metadata': cover
                            })
                            logger.info(f"Stored cover metadata: {cover_id}")
        
        # Batch insert covers
        if covers_batch:
            self.db.batch_insert_covers(covers_batch)
        
        # Fetch and store updates metadata only
        updates_data = self.fetch_json_data(self.config.api_endpoints['updates'], validated_titleid)
        if updates_data:
            media_list = updates_data.get('MediaIDS', updates_data.get('MediaIDs', []))
            if isinstance(media_list, list):
                for media in media_list:
                    if isinstance(media, dict):
                        media_id = media.get('MediaID')
                        updates = media.get('Updates', [])
                        
                        if isinstance(updates, list):
                            for update in updates:
                                if isinstance(update, dict):
                                    tuid = update.get('TitleUpdateID')
                                    version = update.get('Version', 'unknown')
                                    
                                    if tuid:
                                        # Store update metadata WITHOUT downloading
                                        update_url = f"{self.config.base_url}/Resources/Lib/TitleUpdate.php?tuid={tuid}"
                                        updates_batch.append({
                                            'titleid': validated_titleid,
                                            'media_id': str(media_id),
                                            'version': str(version),
                                            'download_url': update_url,
                                            'status': 'pending',
                                            'metadata': update
                                        })
                                        logger.info(f"Stored update metadata: {tuid} v{version}")
        
        # Batch insert updates
        if updates_batch:
            self.db.batch_insert_updates(updates_batch)

        self._collect_plugin_metadata(validated_titleid)
        
        # Update database with scrape info
        self.db.update_scrape_info(validated_titleid)
        
        logger.info(f"[OK] Collected metadata for TitleID: {titleid}")
        return True

    def _collect_plugin_metadata(self, titleid: str) -> None:
        """Run explicitly enabled plugins and store bounded, source-labelled results."""
        for result in self.plugin_manager.collect_enabled(titleid):
            plugin_id = str(result["plugin_id"])
            now = datetime.now().isoformat()
            status = str(result["status"])
            data = result.get("data") if status == "completed" else None
            error = str(result.get("error") or "")
            try:
                if isinstance(data, dict):
                    self._store_plugin_metadata(titleid, plugin_id, data)
            except Exception as exc:
                status = "failed"
                error = str(exc)
                logger.exception("Could not store plugin result from %s", plugin_id)
            with self.db.get_connection() as connection:
                connection.execute(
                    """
                    INSERT INTO plugin_collection_runs(
                        plugin_id, titleid, status, started_at, completed_at,
                        result_json, error_message
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        plugin_id, titleid, status, now, datetime.now().isoformat(),
                        json.dumps(data, sort_keys=True, default=str) if data is not None else None,
                        error or None,
                    ),
                )

    def _store_plugin_metadata(
        self, titleid: str, plugin_id: str, data: Dict[str, Any]
    ) -> None:
        title = str(data.get("title") or data.get("name") or "").strip()[:500]
        publisher = str(data.get("publisher") or "").strip()[:500]
        with self.db.get_connection() as connection:
            row = connection.execute(
                "SELECT name, publisher, metadata FROM titleids WHERE titleid=?", (titleid,)
            ).fetchone()
            metadata: Dict[str, Any] = {}
            if row and row["metadata"]:
                try:
                    metadata = json.loads(row["metadata"])
                except json.JSONDecodeError:
                    metadata = {}
            current_name = row["name"] if row else None
            current_publisher = row["publisher"] if row else None
            if title and is_unknown(current_name):
                current_name = title
                metadata["title_source"] = f"Plugin: {plugin_id}"
            if publisher and is_unknown(current_publisher):
                current_publisher = publisher
                metadata["publisher_source"] = f"Plugin: {plugin_id}"
            plugin_sources = metadata.get("plugin_sources")
            if not isinstance(plugin_sources, dict):
                plugin_sources = {}
                metadata["plugin_sources"] = plugin_sources
            plugin_sources[plugin_id] = datetime.now().isoformat()
            connection.execute(
                "UPDATE titleids SET name=?, publisher=?, metadata=? WHERE titleid=?",
                (current_name, current_publisher, json.dumps(metadata, sort_keys=True), titleid),
            )
            self.db._update_search_index(
                connection, titleid, current_name, current_publisher, metadata
            )

        cover_items = data.get("covers", [])
        if not isinstance(cover_items, list):
            raise TypeError("Plugin covers must be a list")
        covers = []
        for item in cover_items[:200]:
            if not isinstance(item, dict):
                continue
            url = str(item.get("cover_url") or item.get("url") or "").strip()
            if urlparse(url).scheme not in {"http", "https"}:
                continue
            covers.append({
                "titleid": titleid,
                "cover_url": url,
                "cover_type": str(item.get("cover_type") or item.get("type") or "plugin")[:100],
                "status": "pending",
                "metadata": {**item, "plugin_id": plugin_id},
            })
        if covers:
            self.db.batch_insert_covers(covers)

        update_items = data.get("updates", [])
        if not isinstance(update_items, list):
            raise TypeError("Plugin updates must be a list")
        updates = []
        for item in update_items[:500]:
            if not isinstance(item, dict):
                continue
            url = str(item.get("download_url") or item.get("url") or "").strip()
            if urlparse(url).scheme not in {"http", "https"}:
                continue
            updates.append({
                "titleid": titleid,
                "media_id": str(item.get("media_id") or item.get("MediaID") or "")[:100],
                "version": str(item.get("version") or item.get("Version") or "unknown")[:100],
                "download_url": url,
                "status": "pending",
                "metadata": {**item, "plugin_id": plugin_id},
            })
        if updates:
            self.db.batch_insert_updates(updates)
    
    def process_titleid(self, titleid: str) -> bool:
        """Process a single TitleID - download covers and updates"""
        validated_titleid = self.validate_titleid(titleid)
        if not validated_titleid:
            return False
        
        logger.info(f"{'='*60}")
        logger.info(f"Downloading content for TitleID: {validated_titleid}")
        logger.info(f"{'='*60}")
        
        output_dir = self.config.output_dir / validated_titleid
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Fetch and download covers data
        covers_data = self.fetch_json_data(self.config.api_endpoints['covers'], validated_titleid)
        if covers_data:
            with open(output_dir / 'covers_data.json', 'w') as f:
                json.dump(covers_data, f, indent=2)
            self._download_covers(validated_titleid, covers_data, output_dir)
        
        # Fetch and download updates data
        updates_data = self.fetch_json_data(self.config.api_endpoints['updates'], validated_titleid)
        if updates_data:
            with open(output_dir / 'updates_data.json', 'w') as f:
                json.dump(updates_data, f, indent=2)
            self._download_updates(validated_titleid, updates_data, output_dir)

        self.db.add_titleid(validated_titleid)
        self._collect_plugin_metadata(validated_titleid)
        self.db.update_scrape_info(validated_titleid)
        
        logger.info(f"[OK] Completed downloads for TitleID: {titleid}")
        return True
    
    def _download_covers(self, titleid: str, covers_data: Dict, output_dir: Path):
        """Download cover images and mark as downloaded in database"""
        covers_list = covers_data.get('Covers', [])
        if not isinstance(covers_list, list):
            return
        
        covers_dir = output_dir / 'covers'
        covers_dir.mkdir(exist_ok=True)
        
        for cover in covers_list:
            if isinstance(cover, dict):
                cover_id = cover.get('CoverID')
                if cover_id:
                    # Construct the cover image download URL
                    cover_url = f"{self.config.base_url}/Resources/Lib/Cover.php?size=large&cid={cover_id}"
                    filename = f"cover_{cover_id}.jpg"
                    cover_path = covers_dir / filename
                    
                    # Check for duplicates (feature 8)
                    if cover_path.exists():
                        existing_hash = self.downloader.calculate_checksum(cover_path)
                        # Download to temp, check hash, compare
                        temp_path = cover_path.parent / f"{cover_path.name}.tmp"
                        self.download_file(cover_url, temp_path)
                        if temp_path.exists():
                            new_hash = self.downloader.calculate_checksum(temp_path)
                            if existing_hash == new_hash:
                                logger.info(f"Cover {cover_id} already exists (duplicate)")
                                temp_path.unlink()
                                download_status = 'downloaded'
                                cover_path = cover_path  # Keep existing
                            else:
                                temp_path.rename(cover_path)
                                download_status = 'downloaded'
                        else:
                            download_status = 'failed'
                    else:
                        success = self.download_file(cover_url, cover_path)
                        download_status = 'downloaded' if success else 'failed'
                    
                    # Verify checksum if enabled (feature 5)
                    if download_status == 'downloaded' and self.config.verify_checksums:
                        if not cover_path.exists():
                            download_status = 'failed'
                            logger.error(f"Downloaded file missing: {cover_path}")
                    
                    # Store cover metadata in database with status
                    self.db.add_cover(
                        titleid,
                        cover_url=cover_url,
                        file_path=str(cover_path) if cover_path else None,
                        cover_type=cover.get('CoverType', 'unknown'),
                        status=download_status,
                        metadata=cover
                    )
    
    def _download_updates(self, titleid: str, updates_data: Dict, output_dir: Path):
        """Download title updates and mark as downloaded in database"""
        media_list = updates_data.get('MediaIDS', updates_data.get('MediaIDs', []))
        if not isinstance(media_list, list):
            return
        
        for media in media_list:
            if isinstance(media, dict):
                media_id = media.get('MediaID')
                updates = media.get('Updates', [])
                
                if not isinstance(updates, list):
                    continue
                
                for update in updates:
                    if isinstance(update, dict):
                        tuid = update.get('TitleUpdateID')
                        version = update.get('Version', 'unknown')
                        
                        if tuid:
                            # Construct the update download URL
                            update_url = f"{self.config.base_url}/Resources/Lib/TitleUpdate.php?tuid={tuid}"
                            update_dir = output_dir / str(media_id) / f"version_{version}"
                            filename = f"update_{tuid}.bin"
                            file_path = update_dir / filename
                            
                            # Check for duplicates (feature 8)
                            if file_path.exists():
                                existing_hash = self.downloader.calculate_checksum(file_path)
                                temp_path = file_path.parent / f"{file_path.name}.tmp"
                                self.download_file(update_url, temp_path)
                                if temp_path.exists():
                                    new_hash = self.downloader.calculate_checksum(temp_path)
                                    if existing_hash == new_hash:
                                        logger.info(f"Update {tuid} already exists (duplicate)")
                                        temp_path.unlink()
                                        download_status = 'downloaded'
                                        file_path = file_path  # Keep existing
                                    else:
                                        temp_path.rename(file_path)
                                        download_status = 'downloaded'
                                else:
                                    download_status = 'failed'
                            else:
                                success = self.download_file(update_url, file_path)
                                download_status = 'downloaded' if success else 'failed'
                            
                            # Verify checksum if enabled (feature 5)
                            if download_status == 'downloaded' and self.config.verify_checksums:
                                if not file_path.exists():
                                    download_status = 'failed'
                                    logger.error(f"Downloaded file missing: {file_path}")
                            
                            # Store update metadata in database with status
                            self.db.add_title_update(
                                titleid,
                                media_id=str(media_id),
                                version=str(version),
                                download_url=update_url,
                                file_path=str(file_path) if file_path else None,
                                metadata=update,
                                status=download_status
                            )
    
    def process_multiple_titleids(self, titleids: List[str]):
        """Process multiple TitleIDs with parallel workers"""
        valid_titleids = [tid for tid in titleids if self.validate_titleid(tid)]
        
        if not valid_titleids:
            logger.error("No valid TitleIDs to process")
            return
        
        logger.info(f"Processing {len(valid_titleids)} TitleIDs with {self.config.workers} workers")
        
        with ThreadPoolExecutor(max_workers=self.config.workers) as executor:
            futures = {executor.submit(self.process_titleid, tid): tid for tid in valid_titleids}
            
            for future in as_completed(futures):
                titleid = futures[future]
                try:
                    future.result()
                except Exception as e:
                    logger.error(f"Error processing {titleid}: {e}")
    
    def retry_failed_downloads(self, titleid: Optional[str] = None):
        """Retry all failed downloads (feature 2)"""
        logger.info(f"{'='*60}")
        logger.info(f"Retrying failed downloads{f' for {titleid}' if titleid else ''}")
        logger.info(f"{'='*60}")
        
        failed_items = self.db.get_failed_items(titleid)
        
        if not failed_items:
            logger.info("No failed items to retry")
            return
        
        logger.info(f"Found {len(failed_items)} failed items to retry")
        
        for item in failed_items:
            try:
                if item['type'] == 'cover':
                    success = self.download_file(item['url'], Path(item['url'].split('/')[-1]))
                    if success:
                        self.db.mark_for_retry('cover', item['id'])
                        logger.info(f"Retried cover {item['id']}: SUCCESS")
                    else:
                        logger.warning(f"Retried cover {item['id']}: FAILED")
                        
                elif item['type'] == 'update':
                    success = self.download_file(item['url'], Path(item['url'].split('/')[-1]))
                    if success:
                        self.db.mark_for_retry('update', item['id'])
                        logger.info(f"Retried update {item['id']}: SUCCESS")
                    else:
                        logger.warning(f"Retried update {item['id']}: FAILED")
            except Exception as e:
                logger.error(f"Error retrying {item['type']} {item['id']}: {e}")
        
        logger.info("Retry operation completed")
    
    def export_database(self, format: str = 'json', output_file: Optional[str] = None):
        """Export database to JSON or CSV (feature 4)"""
        if not output_file:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_file = f"export_{timestamp}.{format}"
        
        logger.info(f"Exporting database to {format.upper()}: {output_file}")
        
        if format == 'json':
            self.db.export_to_json(output_file)
        elif format == 'csv':
            self.db.export_to_csv(output_file)
        else:
            logger.error(f"Unknown export format: {format}")
            return
        
        logger.info(f"Export completed: {output_file}")


def main():
    configure_logging()
    parser = argparse.ArgumentParser(
        description='UnityScraper - Download Xbox 360 content from XboxUnity',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    parser.add_argument(
        'titleids',
        nargs='*',
        help='Comma-separated TitleIDs (e.g., 555308C5,00000155)'
    )
    parser.add_argument(
        '--out',
        type=str,
        help='Output directory (default: unityscrape)'
    )
    parser.add_argument(
        '--workers',
        type=int,
        help='Number of parallel workers (default: 4)'
    )
    parser.add_argument(
        '--rate',
        type=float,
        help='Minimum seconds between requests (default: 0.35)'
    )
    parser.add_argument(
        '--config',
        type=str,
        help='Path to config.json file'
    )
    parser.add_argument(
        '--save-config',
        action='store_true',
        help='Save current settings to config.json'
    )
    parser.add_argument(
        '--log-level',
        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
        default='INFO',
        help='Logging level'
    )
    parser.add_argument(
        '--force-http',
        action='store_true',
        help='Use XboxUnity HTTP endpoints (always enabled)'
    )
    parser.add_argument(
        '--metadata-only',
        action='store_true',
        help='Only collect metadata without downloading files'
    )
    parser.add_argument(
        '--retry-failed',
        action='store_true',
        help='Retry all failed downloads'
    )
    parser.add_argument(
        '--estimate-size',
        action='store_true',
        help='Estimate download size before downloading'
    )
    parser.add_argument(
        '--verify-checksums',
        action='store_true',
        help='Verify checksums after download'
    )
    parser.add_argument(
        '--bandwidth-limit',
        type=int,
        default=0,
        help='Bandwidth limit in KB/s (0 = unlimited)'
    )
    parser.add_argument(
        '--export',
        type=str,
        choices=['json', 'csv'],
        help='Export database to JSON or CSV'
    )
    parser.add_argument(
        '--export-file',
        type=str,
        help='Export output file path'
    )
    parser.add_argument(
        '--cleanup',
        action='store_true',
        help='Clean up old download history'
    )
    parser.add_argument(
        '--cleanup-days',
        type=int,
        default=90,
        help='Days of history to keep (default: 90)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Simulate downloads without saving files'
    )
    parser.add_argument(
        '--refresh-metadata',
        type=str,
        help='Refresh metadata for specific TitleIDs'
    )
    parser.add_argument(
        '--refresh-interval',
        type=int,
        default=0,
        help='Days between automatic refreshes (0 = disabled)'
    )
    parser.add_argument(
        '--verify-integrity',
        action='store_true',
        help='Verify checksums of downloaded files'
    )
    parser.add_argument(
        '--api-mode',
        action='store_true',
        help='Start REST API server instead of CLI mode'
    )
    parser.add_argument(
        '--api-port',
        type=int,
        default=8000,
        help='API server port (default: 8000)'
    )
    parser.add_argument(
        '--api-host',
        type=str,
        default='127.0.0.1',
        help='API server host (default: 127.0.0.1)'
    )
    parser.add_argument(
        '--api-token',
        type=str,
        default=None,
        help=(
            'API authentication token; prefer the UNITYSCRAPER_API_TOKEN '
            'environment variable'
        )
    )
    parser.add_argument(
        '--sync-title-catalog',
        action='store_true',
        help='Refresh the local XboxUnity title-name catalog for offline autocomplete'
    )
    parser.add_argument(
        '--sync-knowledge',
        action='store_true',
        help='Import ConsoleMods knowledge data and enrich unknown library metadata'
    )
    parser.add_argument(
        '--sync-wikis',
        action='store_true',
        help='Cache and index ConsoleMods, XenonLibrary, and Free60 wiki articles'
    )
    parser.add_argument(
        '--wiki-limit',
        type=int,
        default=None,
        help='Optional maximum article count per wiki source'
    )
    parser.add_argument(
        '--build-offline-knowledge',
        action='store_true',
        help='Build a private offline HTML library from cached wiki pages'
    )
    parser.add_argument(
        '--import-saved-wiki',
        type=str,
        help='Import a browser-saved HTML page, folder, or ZIP archive'
    )
    parser.add_argument(
        '--saved-wiki-source',
        choices=['consolemods-wiki', 'xenonlibrary', 'free60'],
        help='Source attribution required by --import-saved-wiki'
    )
    parser.add_argument(
        '--import-dat',
        type=str,
        help='Import a local Redump or No-Intro XML DAT file'
    )
    parser.add_argument(
        '--dat-source',
        choices=['redump', 'no-intro'],
        help='Source type for --import-dat'
    )
    parser.add_argument('--search-all', type=str,
                        help='Search games, knowledge, profiles, saves, files, and tools')
    parser.add_argument('--extract-knowledge', action='store_true',
                        help='Extract structured records from locally cached wiki documents')
    parser.add_argument('--audit-storage', type=str,
                        help='Inspect a mounted storage path or image read-only')
    parser.add_argument('--scan-original-xbox', type=str,
                        help='Index original Xbox default.xbe files below a folder')
    parser.add_argument('--dedup-preview', type=str,
                        help='Create a checksum-based duplicate preview for a folder')
    parser.add_argument('--dedup-apply', type=int,
                        help='Apply one previewed duplicate action by ID')
    parser.add_argument('--dedup-restore', type=int,
                        help='Restore one quarantined duplicate action by ID')
    parser.add_argument('--dedup-mode', choices=['quarantine', 'hardlink'],
                        default='quarantine', help='Action used with --dedup-apply')
    parser.add_argument('--metadata-snapshot-export', type=str,
                        help='Export portable source-attributed metadata to a .usmeta file')
    parser.add_argument('--metadata-snapshot-import', type=str,
                        help='Merge a portable .usmeta snapshot without personal data')
    parser.add_argument('--library-audit', action='store_true',
                        help='Report missing names, publishers, covers, updates, and MediaIDs')
    parser.add_argument('--preservation-report', type=str,
                        help='Export a privacy-conscious HTML preservation report')
    parser.add_argument('--corrections-export', type=str,
                        help='Export reviewed local metadata corrections as JSON')
    parser.add_argument('--extract-stfs', type=str,
                        help='Extract supported files read-only from an STFS package')
    parser.add_argument('--extract-destination', type=str,
                        help='Destination folder required by --extract-stfs')
    parser.add_argument(
        '--scan-backups',
        type=str,
        help='Inventory an Xbox content, USB, or archive folder'
    )
    parser.add_argument(
        '--backup-report',
        type=str,
        help='Write backup scan results to a JSON file'
    )
    parser.add_argument(
        '--install-package',
        type=str,
        help='Install a user-supplied STFS package into --backup-target'
    )
    parser.add_argument(
        '--import-package-zip',
        type=str,
        help='Safely import supported STFS packages from ZIP into --backup-target'
    )
    parser.add_argument(
        '--backup-target',
        type=str,
        help='Destination console, USB, or archive root for package operations'
    )
    parser.add_argument(
        '--verify-backups',
        type=str,
        help='Scan and structurally verify an Xbox backup target'
    )
    parser.add_argument(
        '--ftp-upload',
        type=str,
        help='Upload a user-supplied STFS package to an FTP console target'
    )
    parser.add_argument('--ftp-host', type=str, help='FTP console host or address')
    parser.add_argument('--ftp-port', type=int, default=21, help='FTP port')
    parser.add_argument('--ftp-user', type=str, default='xbox', help='FTP username')
    parser.add_argument('--ftp-password', type=str, default='', help='FTP password')
    parser.add_argument(
        '--ftp-content-root',
        type=str,
        default='/Hdd1/Content/0000000000000000',
        help='Remote Xbox content root'
    )
    parser.add_argument(
        '--convert-iso',
        type=str,
        help='Run a configured external converter for a user-owned ISO'
    )
    parser.add_argument('--converter', type=str, help='External converter executable')
    parser.add_argument(
        '--converter-arg',
        action='append',
        default=[],
        help='Converter argument; use {input} and {output} placeholders'
    )
    parser.add_argument(
        '--converter-output',
        type=str,
        help='Output directory for --convert-iso'
    )
    parser.add_argument('--list-tools', action='store_true',
                        help='List supported community tool integrations')
    parser.add_argument('--tool-id', type=str,
                        help='Run a Tool Center integration by ID')
    parser.add_argument('--tool-operation', type=str,
                        help='Operation ID used with --tool-id')
    parser.add_argument('--tool-executable', type=str,
                        help='Executable override used with --tool-id')
    parser.add_argument('--tool-input', type=str,
                        help='Input file or folder used with --tool-id')
    parser.add_argument('--tool-output', type=str,
                        help='Output file or folder used with --tool-id')
    parser.add_argument('--tool-arg', action='append', default=[],
                        help='Override Tool Center argument; may be repeated')
    parser.add_argument('--tool-timeout', type=int, default=3600,
                        help='Tool Center timeout in seconds')
    parser.add_argument('--tool-allow-modify', action='store_true',
                        help='Confirm a Tool Center operation that modifies its input')
    parser.add_argument('--analyze-collection', type=str, help='Analyze a local collection root')
    parser.add_argument('--aurora-db', type=str, help='Analyze an Aurora database read-only')
    parser.add_argument('--collection-manifest', type=str, help='Write a preservation manifest')
    parser.add_argument('--collection-html', type=str, help='Write an offline HTML report')
    parser.add_argument(
        '--create-repair-plan', action='store_true',
        help='Save a non-destructive repair-plan preview for the collection'
    )
    parser.add_argument('--match-file', type=str, help='Match a file against imported DAT hashes')
    parser.add_argument('--export-provenance', type=str, help='Export knowledge provenance as JSON')
    parser.add_argument('--backup-database', type=str, help='Create a consistent SQLite backup')
    parser.add_argument('--ftp-snapshot', type=str, help='Capture a read-only remote inventory root')
    parser.add_argument('--ftp-download', type=str, help='Queue and run a resumable FTP download')
    parser.add_argument('--ftp-local-path', type=str, help='Local path for an FTP sync operation')
    parser.add_argument(
        '--ftp-bandwidth-limit', type=int, default=0,
        help='FTP sync limit in bytes per second (0 = unlimited)'
    )
    
    args = parser.parse_args()
    
    # Set logging level
    logging.getLogger().setLevel(getattr(logging, args.log_level))
    
    # Load configuration
    config = Config(args.config)
    
    # Handle API mode
    if args.api_mode:
        try:
            from api import UnityScraperAPI
            scraper = UnityScraper(config)
            api = UnityScraperAPI(
                scraper,
                port=args.api_port,
                host=args.api_host,
                token=args.api_token,
            )
            logger.info(f"Starting API server on {args.api_host}:{args.api_port}")
            logger.info("API documentation available at http://<host>:<port>/api/")
            api.run(debug=args.log_level == 'DEBUG')
        except ImportError:
            logger.error("Flask not installed. Install with: pip install flask flask-cors")
            sys.exit(1)
        except Exception as e:
            logger.error(f"Failed to start API server: {e}")
            sys.exit(1)
    
    # Override with command-line arguments
    if args.out:
        config.output_dir = Path(args.out)
    if args.workers:
        config.workers = args.workers
    if args.rate:
        config.rate_limit = args.rate
    if args.force_http:
        config.use_https = False
        config.base_url = "http://xboxunity.net"
    config.verify_checksums = args.verify_checksums
    config.bandwidth_limit = args.bandwidth_limit
    config.dry_run = args.dry_run
    config.refresh_interval_days = args.refresh_interval
    
    # Save config if requested
    if args.save_config:
        config.save_to_file()
        logger.info("Configuration saved")
    
    # Initialize scraper
    if args.list_tools or args.tool_id:
        try:
            from unityscraper.domains.tools import (
                ExternalToolRunner,
                ToolCatalog,
                format_command,
                operation_for,
            )

            catalog = ToolCatalog(CONFIG_PATH)
            if args.list_tools:
                for tool in catalog.definitions():
                    state = "ready" if catalog.discover(tool.id) else "not configured"
                    operations = ", ".join(item.id for item in tool.operations)
                    print(f"{tool.id:20} {state:14} {operations}")
                sys.exit(0)
            tool = catalog.get(args.tool_id)
            if not args.tool_operation:
                parser.error("--tool-operation is required with --tool-id")
            operation = operation_for(tool, args.tool_operation)
            if (operation.destructive or args.tool_arg) and not args.tool_allow_modify:
                parser.error(
                    "this operation or argument override may modify content; pass "
                    "--tool-allow-modify after making a backup"
                )
            executable = (
                Path(args.tool_executable).expanduser().resolve()
                if args.tool_executable
                else catalog.discover(tool.id)
            )
            if executable is None:
                raise FileNotFoundError(
                    f"{tool.name} is not configured; choose it in Tool Center"
                )
            if args.tool_executable:
                catalog.save_path(tool.id, executable)
            arguments = tuple(args.tool_arg) if args.tool_arg else operation.arguments
            runner = ExternalToolRunner()
            if operation.detached:
                result = runner.launch_detached(
                    executable,
                    arguments,
                    input_path=args.tool_input,
                    output_path=args.tool_output,
                    input_kind=operation.input_kind,
                    output_kind=operation.output_kind,
                )
                print(f"Launched PID {result.pid}: {format_command(result.command)}")
            else:
                result = runner.run(
                    executable,
                    arguments,
                    input_path=args.tool_input,
                    output_path=args.tool_output,
                    timeout=max(1, args.tool_timeout),
                    input_kind=operation.input_kind,
                    output_kind=operation.output_kind,
                )
                if result.stdout:
                    print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
                if result.stderr:
                    print(result.stderr, file=sys.stderr)
                sys.exit(result.returncode)
            sys.exit(0)
        except Exception as e:
            logger.error("Tool Center operation failed: %s", e)
            sys.exit(1)

    if args.sync_title_catalog:
        try:
            from title_catalog import XboxUnityTitleCatalog

            DatabaseManager()
            summary = XboxUnityTitleCatalog(
                request_interval=config.rate_limit,
                timeout=config.timeout,
            ).sync(
                progress=lambda page, pages, items: logger.info(
                    "XboxUnity catalog page %s/%s (%s titles)",
                    page,
                    pages,
                    items,
                )
            )
            logger.info("XboxUnity title catalog sync completed: %s", summary)
            sys.exit(0)
        except Exception as e:
            logger.error("XboxUnity title catalog sync failed: %s", e)
            sys.exit(1)

    if args.sync_knowledge:
        try:
            from knowledge_sync import sync_consolemods_knowledge

            summary = sync_consolemods_knowledge()
            logger.info("Knowledge sync completed: %s", summary)
            sys.exit(0)
        except Exception as e:
            logger.error(f"Knowledge sync failed: {e}")
            sys.exit(1)

    if args.sync_wikis:
        try:
            from knowledge_sync import sync_reference_wikis

            summary = sync_reference_wikis(
                max_documents_per_source=args.wiki_limit,
            )
            logger.info("Wiki sync completed: %s", summary)
            sys.exit(0)
        except Exception as e:
            logger.error(f"Wiki sync failed: {e}")
            sys.exit(1)

    if args.build_offline_knowledge:
        try:
            from offline_knowledge import OfflineKnowledgeArchive

            summary = OfflineKnowledgeArchive().rebuild()
            logger.info("Offline knowledge library built: %s", summary)
            sys.exit(0)
        except Exception as e:
            logger.error("Offline knowledge build failed: %s", e)
            sys.exit(1)

    if args.import_saved_wiki:
        if not args.saved_wiki_source:
            parser.error("--saved-wiki-source is required with --import-saved-wiki")
        try:
            from offline_knowledge import OfflineKnowledgeArchive

            summary = OfflineKnowledgeArchive().import_saved_pages(
                args.import_saved_wiki,
                args.saved_wiki_source,
            )
            logger.info("Saved wiki import completed: %s", summary)
            sys.exit(0)
        except Exception as e:
            logger.error("Saved wiki import failed: %s", e)
            sys.exit(1)

    if args.import_dat:
        if not args.dat_source:
            parser.error("--dat-source is required with --import-dat")
        try:
            from knowledge_sync import import_dat_knowledge

            summary = import_dat_knowledge(args.import_dat, args.dat_source)
            logger.info("DAT import completed: %s", summary)
            sys.exit(0)
        except Exception as e:
            logger.error(f"DAT import failed: {e}")
            sys.exit(1)

    if (
        args.search_all
        or args.extract_knowledge
        or args.audit_storage
        or args.scan_original_xbox
        or args.dedup_preview
        or args.dedup_apply is not None
        or args.dedup_restore is not None
        or args.metadata_snapshot_export
        or args.metadata_snapshot_import
        or args.library_audit
        or args.preservation_report
        or args.corrections_export
        or args.extract_stfs
    ):
        try:
            from community_services import (
                PackageWorkspaceService,
                PreservationPlanningService,
                StorageAndXboxService,
            )
            from roadmap_services import (
                CorrectionPackageService,
                LibraryIntelligenceService,
                MetadataSnapshotService,
                PreservationReportService,
            )
            from structured_knowledge import StructuredKnowledgeService
            from unified_search import UnifiedSearchService

            results: Dict[str, Any] = {}
            if args.search_all:
                results["search"] = UnifiedSearchService().search(args.search_all)
            if args.extract_knowledge:
                results["knowledge"] = StructuredKnowledgeService().extract_cached_documents()
            if args.audit_storage:
                results["storage"] = StorageAndXboxService().audit_storage(args.audit_storage)
            if args.scan_original_xbox:
                results["original_xbox"] = StorageAndXboxService().scan_original_xbox(
                    args.scan_original_xbox
                )
            preservation = PreservationPlanningService()
            if args.dedup_preview:
                results["dedup_preview"] = preservation.create_dedup_plan(args.dedup_preview)
                results["dedup_actions"] = preservation.list_dedup_actions(
                    results["dedup_preview"]["plan_id"]
                )
            if args.dedup_apply is not None:
                results["dedup_apply"] = preservation.apply_dedup_action(
                    args.dedup_apply, args.dedup_mode
                )
            if args.dedup_restore is not None:
                results["dedup_restore"] = preservation.restore_dedup_action(
                    args.dedup_restore
                )
            if args.metadata_snapshot_export:
                results["metadata_snapshot_export"] = MetadataSnapshotService().export(
                    args.metadata_snapshot_export
                )
            if args.metadata_snapshot_import:
                results["metadata_snapshot_import"] = MetadataSnapshotService().import_snapshot(
                    args.metadata_snapshot_import
                )
            if args.library_audit:
                results["library_audit"] = LibraryIntelligenceService().audit()
            if args.preservation_report:
                results["preservation_report"] = PreservationReportService().export_html(
                    args.preservation_report
                )
            if args.corrections_export:
                results["corrections_export"] = CorrectionPackageService().export(
                    args.corrections_export
                )
            if args.extract_stfs:
                if not args.extract_destination:
                    parser.error("--extract-destination is required with --extract-stfs")
                results["stfs_extraction"] = PackageWorkspaceService().extract_read_only(
                    args.extract_stfs, args.extract_destination
                )
            print(json.dumps(results, indent=2, default=str))
            sys.exit(0)
        except Exception as e:
            logger.error("Community operation failed: %s", e)
            sys.exit(1)

    if (
        args.analyze_collection
        or args.aurora_db
        or args.match_file
        or args.export_provenance
        or args.backup_database
    ):
        try:
            from app_paths import DATABASE_PATH
            from collection_intelligence import CollectionIntelligenceService
            from database_migrations import create_database_backup

            service = CollectionIntelligenceService()
            if args.backup_database:
                backup = create_database_backup(DATABASE_PATH, args.backup_database)
                logger.info("Database backup written to %s", backup)
            if args.match_file:
                matches = service.hash_and_match(args.match_file)
                logger.info("Preservation matches: %s", json.dumps(matches, indent=2))
            if args.export_provenance:
                output = service.export_provenance(args.export_provenance)
                logger.info("Provenance written to %s", output)
            if args.analyze_collection or args.aurora_db:
                analysis = (
                    service.analyze(args.analyze_collection)
                    if args.analyze_collection
                    else service.analyze_aurora(args.aurora_db)
                )
                logger.info(
                    "Collection health %s/100: %s item(s), %s issue(s)",
                    analysis.health_score,
                    len(analysis.result.items),
                    len(analysis.issues),
                )
                if args.collection_manifest:
                    logger.info(
                        "Manifest written to %s",
                        service.export_manifest(analysis, args.collection_manifest),
                    )
                if args.collection_html:
                    logger.info(
                        "HTML report written to %s",
                        service.export_html(analysis, args.collection_html),
                    )
                if args.create_repair_plan:
                    logger.info(
                        "Repair-plan preview saved as %s",
                        service.create_repair_plan(analysis),
                    )
            sys.exit(0)
        except Exception as e:
            logger.error("Collection operation failed: %s", e)
            sys.exit(1)

    if args.ftp_snapshot or args.ftp_download:
        if not args.ftp_host:
            parser.error("--ftp-host is required for console sync")
        try:
            from backup_manager import FtpTarget
            from console_sync import ConsoleSyncService

            target = FtpTarget(
                host=args.ftp_host,
                port=args.ftp_port,
                username=args.ftp_user,
                password=args.ftp_password,
                content_root=args.ftp_content_root,
            )
            sync = ConsoleSyncService()
            if args.ftp_snapshot:
                snapshot = sync.capture_inventory(target, args.ftp_snapshot)
                logger.info("Console inventory snapshot %s completed", snapshot)
            if args.ftp_download:
                if not args.ftp_local_path:
                    parser.error("--ftp-local-path is required with --ftp-download")
                job = sync.enqueue(
                    "download",
                    args.ftp_local_path,
                    args.ftp_download,
                    bandwidth_limit=args.ftp_bandwidth_limit,
                )
                result = sync.run_job(job, target)
                logger.info("Console transfer %s: %s", job, result["status"])
                if result["status"] != "completed":
                    sys.exit(1)
            sys.exit(0)
        except Exception as e:
            logger.error("Console sync failed: %s", e)
            sys.exit(1)

    if (
        args.scan_backups
        or args.install_package
        or args.import_package_zip
        or args.verify_backups
        or args.ftp_upload
        or args.convert_iso
    ):
        try:
            from backup_manager import ExternalConverter, FtpTarget, verify_backup_item
            from backup_service import BackupService

            backup_service = BackupService()
            if args.scan_backups:
                result = backup_service.scan(args.scan_backups)
                logger.info(
                    "Backup scan completed: %s items, %s bytes, %s warning(s)",
                    len(result.items),
                    result.total_size,
                    len(result.warnings),
                )
                if args.backup_report:
                    Path(args.backup_report).write_text(
                        json.dumps(result.to_dict(), indent=2),
                        encoding='utf-8',
                    )
                    logger.info("Backup report written to %s", args.backup_report)
            if args.install_package:
                if not args.backup_target:
                    parser.error("--backup-target is required with --install-package")
                result = backup_service.install_package(
                    args.install_package, args.backup_target
                )
                logger.info("Package %s: %s", result.status, result.destination)
            if args.import_package_zip:
                if not args.backup_target:
                    parser.error("--backup-target is required with --import-package-zip")
                results = backup_service.import_archive(
                    args.import_package_zip, args.backup_target
                )
                logger.info("Imported %s supported package(s)", len(results))
            if args.verify_backups:
                scan = backup_service.scan(args.verify_backups)
                issues = []
                for item in scan.items:
                    item_issues = verify_backup_item(item)
                    if item_issues:
                        issues.append(
                            {"path": str(item.path), "issues": item_issues}
                        )
                logger.info(
                    "Backup verification completed: %s item(s), %s with issues",
                    len(scan.items),
                    len(issues),
                )
                if args.backup_report:
                    Path(args.backup_report).write_text(
                        json.dumps(
                            {"scan": scan.to_dict(), "verification_issues": issues},
                            indent=2,
                        ),
                        encoding='utf-8',
                    )
            if args.ftp_upload:
                if not args.ftp_host:
                    parser.error("--ftp-host is required with --ftp-upload")
                result = backup_service.upload_ftp(
                    args.ftp_upload,
                    FtpTarget(
                        host=args.ftp_host,
                        port=args.ftp_port,
                        username=args.ftp_user,
                        password=args.ftp_password,
                        content_root=args.ftp_content_root,
                    ),
                )
                logger.info("FTP upload completed: %s", result.destination)
            if args.convert_iso:
                if not args.converter or not args.converter_output:
                    parser.error(
                        "--converter and --converter-output are required with --convert-iso"
                    )
                converter = ExternalConverter(
                    args.converter,
                    args.converter_arg or ["{input}", "{output}"],
                )
                completed = converter.convert(args.convert_iso, args.converter_output)
                logger.info("External converter completed with exit code %s", completed.returncode)
            sys.exit(0)
        except Exception as e:
            logger.error("Backup operation failed: %s", e)
            sys.exit(1)

    scraper = UnityScraper(config)
    
    # Handle export
    if args.export:
        scraper.export_database(args.export, args.export_file)
        sys.exit(0)
    
    # Handle cleanup
    if args.cleanup:
        deleted = scraper.db.cleanup_old_history(args.cleanup_days)
        logger.info(f"Cleaned up {deleted} old history entries")
        scraper.db.vacuum()
        sys.exit(0)
    
    # Handle integrity check
    if args.verify_integrity:
        logger.info(f"{'='*60}")
        logger.info("Verifying file integrity...")
        logger.info(f"{'='*60}")
        results = scraper.db.verify_file_integrity()
        logger.info(f"Total files checked: {results['total']}")
        logger.info(f"Verified: {len(results['verified'])}")
        logger.info(f"Corrupted: {len(results['corrupted'])}")
        logger.info(f"Missing: {len(results['missing'])}")
        
        if results['corrupted']:
            logger.warning("Corrupted files detected:")
            for item in results['corrupted']:
                logger.warning(f"  {item['type']} {item['id']}: {item['path']}")
        
        if results['missing']:
            logger.warning("Missing files detected:")
            for item in results['missing']:
                logger.warning(f"  {item['type']} {item['id']}")
        
        sys.exit(0)
    
    # Handle retry failed
    if args.retry_failed:
        scraper.retry_failed_downloads()
        sys.exit(0)
    
    # Get TitleIDs
    titleids = []
    metadata_only = args.metadata_only
    
    if args.refresh_metadata:
        # Refresh metadata for specific TitleIDs
        titleids = [tid.strip() for tid in args.refresh_metadata.split(',')]
        metadata_only = True
        logger.info(f"Refreshing metadata for {len(titleids)} TitleIDs")
    elif args.titleids:
        for arg in args.titleids:
            titleids.extend([tid.strip() for tid in arg.split(',')])
    else:
        # Try to load from JSON.txt first
        titleids = load_titleids_from_json()
        
        # Auto-enable metadata-only mode when loading from JSON.txt
        if titleids:
            metadata_only = True
            logger.info("Loaded TitleIDs from JSON.txt - using metadata-only mode")
        else:
            user_input = input("Enter TitleIDs separated by commas: ").strip()
            titleids = [tid.strip() for tid in user_input.split(',')]
    
    if not titleids:
        logger.error("No TitleIDs provided")
        sys.exit(1)
    
    # Run scraper
    try:
        if args.estimate_size:
            # Estimate sizes
            logger.info("Estimating download sizes...")
            for titleid in titleids:
                estimate = scraper.get_download_size_estimate(titleid)
                total_mb = estimate['total_bytes'] / (1024 * 1024)
                covers_mb = estimate['covers_bytes'] / (1024 * 1024)
                updates_mb = estimate['updates_bytes'] / (1024 * 1024)
                logger.info(f"{titleid}: {total_mb:.2f}MB total "
                           f"(Covers: {covers_mb:.2f}MB, Updates: {updates_mb:.2f}MB)")
            sys.exit(0)
        
        if metadata_only:
            # Collect metadata only
            logger.info(f"Collecting metadata for {len(titleids)} TitleIDs...")
            with ThreadPoolExecutor(max_workers=config.workers) as executor:
                futures = {executor.submit(scraper.collect_metadata, tid): tid for tid in titleids}
                
                for future in as_completed(futures):
                    titleid = futures[future]
                    try:
                        future.result()
                    except Exception as e:
                        logger.error(f"Error collecting metadata for {titleid}: {e}")
            logger.info("Metadata collection completed! Check GUI to view and download items.")
        else:
            # Download content
            logger.info(f"Downloading content for {len(titleids)} TitleIDs...")
            scraper.process_multiple_titleids(titleids)
        
        logger.info("All tasks completed!")
    except KeyboardInterrupt:
        logger.warning("Interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
