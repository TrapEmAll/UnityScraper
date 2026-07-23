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
    ensure_app_dirs,
    ensure_user_titleids_file,
)
from database import DatabaseManager
from plugins import PluginManager
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
    ):
        self.config = config
        self.rate_limiter = RateLimiter(config.rate_limit)
        self.session = self._create_session()
        self.db = database or DatabaseManager()
        self.plugin_manager = PluginManager()  # Initialize plugin system
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
        
        # Update database with scrape info
        self.db.update_scrape_info(validated_titleid)
        
        logger.info(f"[OK] Collected metadata for TitleID: {titleid}")
        return True
    
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
        '--import-dat',
        type=str,
        help='Import a local Redump or No-Intro XML DAT file'
    )
    parser.add_argument(
        '--dat-source',
        choices=['redump', 'no-intro'],
        help='Source type for --import-dat'
    )
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
