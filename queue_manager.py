"""
Download Queue Manager
Persist and restore download queues across sessions
"""

import json
import logging
import os
import uuid
from pathlib import Path
from typing import List, Dict, Optional
from datetime import datetime
from app_paths import DATA_DIR, ensure_app_dirs

logger = logging.getLogger(__name__)


class DownloadQueue:
    """Manage persistent download queue"""
    
    def __init__(self, queue_file: str | Path | None = None):
        if queue_file is None:
            ensure_app_dirs()
            self.queue_file = DATA_DIR / "download_queue.json"
        else:
            self.queue_file = Path(queue_file)
        self.queue: List[Dict] = []
        self.load_queue()
    
    def add_item(self, titleid: str, item_type: str, url: str, 
                 destination: str, priority: int = 0) -> bool:
        """Add item to queue"""
        try:
            item = {
                'id': uuid.uuid4().hex,
                'titleid': titleid,
                'type': item_type,  # 'cover' or 'update'
                'url': url,
                'destination': destination,
                'priority': priority,
                'status': 'queued',  # queued, downloading, completed, failed
                'added_at': datetime.now().isoformat(),
                'started_at': None,
                'completed_at': None,
                'error': None,
                'retry_count': 0
            }
            self.queue.append(item)
            self.save_queue()
            logger.info(f"Added {item_type} {titleid} to queue (priority: {priority})")
            return True
        except Exception as e:
            logger.error(f"Failed to add queue item: {e}")
            return False
    
    def get_next_item(self) -> Optional[Dict]:
        """Get next item to download (by priority, then FIFO)"""
        # Filter queued items, sort by priority (high to low), then by date added
        queued = [item for item in self.queue if item['status'] == 'queued']
        if not queued:
            return None
        
        queued.sort(key=lambda x: (-x['priority'], x['added_at']))
        return queued[0]
    
    def mark_downloading(self, item_id: str) -> bool:
        """Mark item as currently downloading"""
        item = self._find_item(item_id)
        if item:
            item['status'] = 'downloading'
            item['started_at'] = datetime.now().isoformat()
            self.save_queue()
            return True
        return False
    
    def mark_completed(self, item_id: str) -> bool:
        """Mark item as completed"""
        item = self._find_item(item_id)
        if item:
            item['status'] = 'completed'
            item['completed_at'] = datetime.now().isoformat()
            self.save_queue()
            logger.info(f"Completed queue item: {item_id}")
            return True
        return False
    
    def mark_failed(self, item_id: str, error: Optional[str] = None) -> bool:
        """Mark item as failed"""
        item = self._find_item(item_id)
        if item:
            item['status'] = 'failed'
            item['error'] = error
            item['retry_count'] += 1
            self.save_queue()
            logger.warning(f"Failed queue item: {item_id} - {error}")
            return True
        return False
    
    def retry_failed(self, max_retries: int = 3) -> int:
        """Reset failed items to queued (up to max retries)"""
        retried = 0
        for item in self.queue:
            if item['status'] == 'failed' and item['retry_count'] < max_retries:
                item['status'] = 'queued'
                retried += 1
        if retried > 0:
            self.save_queue()
            logger.info(f"Retried {retried} failed items")
        return retried
    
    def remove_item(self, item_id: str) -> bool:
        """Remove item from queue"""
        for i, item in enumerate(self.queue):
            if item['id'] == item_id:
                self.queue.pop(i)
                self.save_queue()
                return True
        return False
    
    def clear_completed(self) -> int:
        """Clear all completed items from queue"""
        original_len = len(self.queue)
        self.queue = [item for item in self.queue if item['status'] != 'completed']
        removed = original_len - len(self.queue)
        if removed > 0:
            self.save_queue()
            logger.info(f"Cleared {removed} completed items from queue")
        return removed
    
    def get_queue_stats(self) -> Dict:
        """Get queue statistics"""
        return {
            'total': len(self.queue),
            'queued': sum(1 for item in self.queue if item['status'] == 'queued'),
            'downloading': sum(1 for item in self.queue if item['status'] == 'downloading'),
            'completed': sum(1 for item in self.queue if item['status'] == 'completed'),
            'failed': sum(1 for item in self.queue if item['status'] == 'failed'),
        }
    
    def get_queue_info(self) -> List[Dict]:
        """Get all queue items"""
        return self.queue.copy()
    
    def _find_item(self, item_id: str) -> Optional[Dict]:
        """Find item by ID"""
        for item in self.queue:
            if item['id'] == item_id:
                return item
        return None
    
    def save_queue(self):
        """Save the queue atomically so a crash cannot truncate it."""
        try:
            self.queue_file.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.queue_file.with_suffix(self.queue_file.suffix + ".tmp")
            with temporary.open("w", encoding="utf-8") as handle:
                json.dump(self.queue, handle, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            temporary.replace(self.queue_file)
        except Exception as e:
            logger.error(f"Failed to save queue: {e}")
    
    def load_queue(self):
        """Load queue from JSON file"""
        try:
            if self.queue_file.exists():
                with self.queue_file.open("r", encoding="utf-8") as f:
                    self.queue = json.load(f)
                recovered = 0
                for item in self.queue:
                    if item.get("status") == "downloading":
                        item["status"] = "queued"
                        item["error"] = "Recovered after an interrupted session"
                        recovered += 1
                if recovered:
                    self.save_queue()
                    logger.info(f"Recovered {recovered} interrupted queue items")
                logger.info(f"Loaded {len(self.queue)} items from queue file")
            else:
                self.queue = []
        except Exception as e:
            logger.error(f"Failed to load queue: {e}")
            self.queue = []
    
    def clear_queue(self) -> int:
        """Clear entire queue"""
        count = len(self.queue)
        self.queue = []
        self.save_queue()
        logger.info(f"Cleared {count} items from queue")
        return count


# Example usage
if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    
    queue = DownloadQueue()
    
    # Add items
    queue.add_item('555308C5', 'cover', 'http://example.com/cover.jpg', '/path/to/cover.jpg', priority=2)
    queue.add_item('555308C5', 'update', 'http://example.com/update.bin', '/path/to/update.bin', priority=1)
    
    # Get next item
    next_item = queue.get_next_item()
    print(f"Next item: {next_item}")
    
    # Process item
    if next_item:
        queue.mark_downloading(next_item['id'])
        # ... download ...
        queue.mark_completed(next_item['id'])
    
    # Get stats
    stats = queue.get_queue_stats()
    print(f"Queue stats: {stats}")
