"""
Resume Module for UnityScraper
Implements resumable downloads with checksums and progress tracking
"""

import hashlib
import logging
import os
import time
from pathlib import Path
from typing import Optional, Callable, Dict
import requests

logger = logging.getLogger(__name__)


class DownloadProgress:
    """Track download progress"""
    def __init__(self, total_size: int, filepath: Path):
        self.total_size = total_size
        self.filepath = filepath
        self.downloaded = 0
        self.start_time = time.time()
        self.last_update = time.time()
        self.speed_samples = []  # Track speed over time
        self.peak_speed = 0.0
        self.avg_speed = 0.0
    
    def update(self, chunk_size: int):
        """Update progress"""
        self.downloaded += chunk_size
        self.last_update = time.time()
        
        # Calculate instant speed
        elapsed_total = time.time() - self.start_time
        if elapsed_total > 0:
            instant_speed = (self.downloaded / (1024 * 1024)) / elapsed_total
            self.speed_samples.append(instant_speed)
            
            if instant_speed > self.peak_speed:
                self.peak_speed = instant_speed
            
            if self.speed_samples:
                self.avg_speed = sum(self.speed_samples) / len(self.speed_samples)
    
    @property
    def percentage(self) -> float:
        """Get download percentage"""
        if self.total_size == 0:
            return 0.0
        return (self.downloaded / self.total_size) * 100
    
    @property
    def speed_mbps(self) -> float:
        """Get download speed in MB/s"""
        elapsed = time.time() - self.start_time
        if elapsed == 0:
            return 0.0
        return (self.downloaded / (1024 * 1024)) / elapsed
    
    @property
    def eta_seconds(self) -> Optional[float]:
        """Estimate time remaining in seconds"""
        if self.downloaded == 0:
            return None
        elapsed = time.time() - self.start_time
        if elapsed <= 0:
            return 0.0 if self.downloaded >= self.total_size else None
        rate = self.downloaded / elapsed
        remaining = max(self.total_size - self.downloaded, 0)
        return remaining / rate if rate > 0 else None
    
    def get_stats(self) -> Dict[str, float]:
        """Get comprehensive speed statistics"""
        return {
            'current_speed': self.speed_mbps,
            'peak_speed': self.peak_speed,
            'average_speed': self.avg_speed,
            'percentage': self.percentage,
            'eta_seconds': self.eta_seconds or 0
        }
    
    def __str__(self) -> str:
        eta = self.eta_seconds
        eta_str = f"{int(eta)}s" if eta else "N/A"
        return (f"{self.filepath.name}: {self.percentage:.1f}% "
                f"({self.downloaded}/{self.total_size} bytes) "
                f"Speed: {self.speed_mbps:.2f} MB/s (Peak: {self.peak_speed:.2f} MB/s) ETA: {eta_str}")


class ResumableDownloader:
    """Handles resumable downloads with progress tracking and checksums"""
    
    def __init__(self, session: requests.Session, timeout: int = 30, bandwidth_limit: int = 0):
        self.session = session
        self.timeout = timeout
        self.chunk_size = 8192
        self.bandwidth_limit = bandwidth_limit  # KB/s, 0 = unlimited
        self.last_chunk_time = 0
    
    def supports_resume(self, url: str) -> bool:
        """Check if server supports resume (Accept-Ranges header)"""
        try:
            response = self.session.head(url, timeout=self.timeout)
            return response.headers.get('Accept-Ranges') == 'bytes'
        except Exception as e:
            logger.warning(f"Could not check resume support: {e}")
            return False
    
    def get_remote_size(self, url: str) -> Optional[int]:
        """Get remote file size"""
        try:
            response = self.session.head(url, timeout=self.timeout)
            content_length = response.headers.get('Content-Length')
            return int(content_length) if content_length else None
        except Exception as e:
            logger.error(f"Could not get remote file size: {e}")
            return None
    
    def apply_bandwidth_limit(self, chunk_size: int):
        """Apply bandwidth throttling if configured"""
        if self.bandwidth_limit <= 0:
            return
        
        # Calculate sleep time: chunk_size (bytes) / bandwidth_limit (KB/s)
        target_time = chunk_size / (self.bandwidth_limit * 1024)
        elapsed = time.time() - self.last_chunk_time
        
        if elapsed < target_time:
            time.sleep(target_time - elapsed)
        
        self.last_chunk_time = time.time()
    
    def calculate_checksum(self, filepath: Path, algorithm: str = 'sha256') -> str:
        """Calculate file checksum"""
        hash_func = hashlib.new(algorithm)
        
        with open(filepath, 'rb') as f:
            while chunk := f.read(self.chunk_size):
                hash_func.update(chunk)
        
        return hash_func.hexdigest()
    
    def verify_checksum(self, filepath: Path, expected_checksum: str, 
                       algorithm: str = 'sha256') -> bool:
        """Verify file checksum"""
        actual = self.calculate_checksum(filepath, algorithm)
        return actual.lower() == expected_checksum.lower()
    
    def get_temp_filepath(self, dest_path: Path) -> Path:
        """Get temporary file path for incomplete downloads"""
        return dest_path.parent / f"{dest_path.name}.partial"
    
    def get_metadata_filepath(self, dest_path: Path) -> Path:
        """Get metadata file path"""
        return dest_path.parent / f"{dest_path.name}.meta"
    
    def save_metadata(self, dest_path: Path, url: str, total_size: int, 
                     checksum: Optional[str] = None):
        """Save download metadata"""
        import json
        metadata = {
            'url': url,
            'total_size': total_size,
            'checksum': checksum,
            'algorithm': 'sha256',
            'timestamp': time.time()
        }
        
        meta_path = self.get_metadata_filepath(dest_path)
        with open(meta_path, 'w') as f:
            json.dump(metadata, f)
    
    def load_metadata(self, dest_path: Path) -> Optional[dict]:
        """Load download metadata"""
        import json
        meta_path = self.get_metadata_filepath(dest_path)
        
        if not meta_path.exists():
            return None
        
        try:
            with open(meta_path, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Could not load metadata: {e}")
            return None
    
    def cleanup_temp_files(self, dest_path: Path):
        """Remove temporary and metadata files"""
        temp_path = self.get_temp_filepath(dest_path)
        meta_path = self.get_metadata_filepath(dest_path)
        
        for path in [temp_path, meta_path]:
            if path.exists():
                try:
                    path.unlink()
                except Exception as e:
                    logger.warning(f"Could not remove {path}: {e}")
    
    def download(self, url: str, dest_path: Path, 
                expected_checksum: Optional[str] = None,
                progress_callback: Optional[Callable[[DownloadProgress], None]] = None,
                resume: bool = True) -> bool:
        """
        Download file with resume support
        
        Args:
            url: Download URL
            dest_path: Destination file path
            expected_checksum: Optional SHA256 checksum to verify
            progress_callback: Optional callback for progress updates
            resume: Whether to attempt resuming partial downloads
            
        Returns:
            True if download successful, False otherwise
        """
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.get_temp_filepath(dest_path)
        
        # Check if file already exists and is valid
        if dest_path.exists():
            if expected_checksum:
                logger.info(f"Verifying existing file: {dest_path.name}")
                if self.verify_checksum(dest_path, expected_checksum):
                    logger.info(f"✓ File already exists and is valid: {dest_path.name}")
                    return True
                else:
                    logger.warning(f"Existing file checksum mismatch, re-downloading")
                    dest_path.unlink()
            else:
                logger.info(f"✓ File already exists: {dest_path.name}")
                return True
        
        # Get remote file size
        remote_size = self.get_remote_size(url)
        if remote_size is None:
            logger.error("Could not determine remote file size")
            return False
        
        # Check for partial download
        start_byte = 0
        if resume and temp_path.exists():
            metadata = self.load_metadata(dest_path)
            
            if metadata and metadata.get('url') == url:
                partial_size = temp_path.stat().st_size
                
                # Verify partial size is reasonable
                if partial_size < remote_size:
                    start_byte = partial_size
                    logger.info(f"Resuming download from byte {start_byte}")
                else:
                    logger.warning("Partial file larger than remote, starting over")
                    temp_path.unlink()
            else:
                logger.info("Metadata mismatch, starting fresh download")
                temp_path.unlink()
        
        # Save metadata
        self.save_metadata(dest_path, url, remote_size, expected_checksum)
        
        # Prepare headers for resume
        headers = {}
        if start_byte > 0 and self.supports_resume(url):
            headers['Range'] = f'bytes={start_byte}-'
            logger.info(f"Server supports resume, requesting from byte {start_byte}")
        else:
            start_byte = 0
        
        # Download file
        try:
            response = self.session.get(
                url, 
                headers=headers, 
                stream=True, 
                timeout=self.timeout
            )
            response.raise_for_status()
            
            # Verify range request was honored
            if start_byte > 0 and response.status_code != 206:
                logger.warning("Server did not honor range request, starting over")
                start_byte = 0
                temp_path.unlink() if temp_path.exists() else None
            
            # Get actual total size
            if response.status_code == 206:
                content_range = response.headers.get('Content-Range')
                if content_range:
                    total_size = int(content_range.split('/')[-1])
                else:
                    total_size = remote_size
            else:
                total_size = int(response.headers.get('Content-Length', remote_size))
            
            # Create progress tracker
            progress = DownloadProgress(total_size, dest_path)
            progress.downloaded = start_byte
            
            # Download chunks
            mode = 'ab' if start_byte > 0 else 'wb'
            with open(temp_path, mode) as f:
                for chunk in response.iter_content(chunk_size=self.chunk_size):
                    if chunk:
                        f.write(chunk)
                        progress.update(len(chunk))
                        self.apply_bandwidth_limit(len(chunk))
                        
                        # Call progress callback
                        if progress_callback and time.time() - progress.last_update > 0.5:
                            progress_callback(progress)
            
            # Final progress update
            if progress_callback:
                progress_callback(progress)
            
            # Verify checksum if provided
            if expected_checksum:
                logger.info(f"Verifying checksum for {dest_path.name}...")
                if not self.verify_checksum(temp_path, expected_checksum):
                    logger.error("Checksum verification failed!")
                    return False
                logger.info("✓ Checksum verified")
            
            # Move temp file to final destination
            if dest_path.exists():
                dest_path.unlink()
            temp_path.rename(dest_path)
            
            # Cleanup
            self.cleanup_temp_files(dest_path)
            
            logger.info(f"✓ Downloaded successfully: {dest_path.name}")
            return True
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Download failed: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error during download: {e}")
            return False


class BatchDownloadManager:
    """Manages multiple resumable downloads"""
    
    def __init__(self, downloader: ResumableDownloader):
        self.downloader = downloader
        self.active_downloads = {}
        self.completed = []
        self.failed = []
    
    def add_download(self, url: str, dest_path: Path, 
                    checksum: Optional[str] = None) -> str:
        """Add download to queue"""
        download_id = f"{dest_path.name}_{time.time()}"
        self.active_downloads[download_id] = {
            'url': url,
            'dest_path': dest_path,
            'checksum': checksum,
            'status': 'queued',
            'progress': None
        }
        return download_id
    
    def download_all(self, progress_callback: Optional[Callable] = None) -> dict:
        """Download all queued files"""
        results = {
            'completed': 0,
            'failed': 0,
            'total': len(self.active_downloads)
        }
        
        for download_id, info in self.active_downloads.items():
            logger.info(f"Starting download: {info['dest_path'].name}")
            info['status'] = 'downloading'
            
            success = self.downloader.download(
                info['url'],
                info['dest_path'],
                info['checksum'],
                progress_callback
            )
            
            if success:
                info['status'] = 'completed'
                self.completed.append(download_id)
                results['completed'] += 1
            else:
                info['status'] = 'failed'
                self.failed.append(download_id)
                results['failed'] += 1
        
        return results
    
    def get_status(self) -> dict:
        """Get current download status"""
        return {
            'total': len(self.active_downloads),
            'completed': len(self.completed),
            'failed': len(self.failed),
            'active': len([d for d in self.active_downloads.values() 
                          if d['status'] == 'downloading'])
        }


# Example usage
if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    
    # Create session
    session = requests.Session()
    
    # Create downloader
    downloader = ResumableDownloader(session)
    
    # Progress callback
    def on_progress(progress: DownloadProgress):
        print(f"\r{progress}", end='', flush=True)
    
    # Download with resume support
    success = downloader.download(
        url='http://example.com/large_file.bin',
        dest_path=Path('downloads/large_file.bin'),
        progress_callback=on_progress,
        resume=True
    )
    
    print(f"\nDownload {'successful' if success else 'failed'}")
