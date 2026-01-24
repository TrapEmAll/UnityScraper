"""
Download Queue Manager
Persist and restore download queues across sessions
"""

import json
import logging
from pathlib import Path
from typing import List, Dict, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class DownloadQueue:
    """Manage persistent download queue"""
    
    def __init__(self, queue_file: str = "download_queue.json"):
        self.queue_file = Path(queue_file)
        self.queue: List[Dict] = []
        self.load_queue()
    
    def add_item(self, titleid: str, item_type: str, url: str, 
                 destination: str, priority: int = 0) -> bool:
        """Add item to queue"""
        try:
            item = {
                'id': f"{titleid}_{item_type}_{len(self.queue)}",
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
    
    def mark_failed(self, item_id: str, error: str = None) -> bool:
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
                item['retry_count'] += 1
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
        """Save queue to JSON file"""
        try:
            with open(self.queue_file, 'w') as f:
                json.dump(self.queue, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save queue: {e}")
    
    def load_queue(self):
        """Load queue from JSON file"""
        try:
            if self.queue_file.exists():
                with open(self.queue_file, 'r') as f:
                    self.queue = json.load(f)
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
