"""
Database Module for UnityScraper
SQLite-based indexing and metadata storage for TitleIDs
"""

import sqlite3
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Any
from contextlib import contextmanager

logger = logging.getLogger(__name__)


class DatabaseManager:
    """Manages SQLite database for TitleID indexing and metadata"""
    
    def __init__(self, db_path: str = "unityscraper.db"):
        self.db_path = Path(db_path)
        self.init_database()
    
    @contextmanager
    def get_connection(self):
        """Context manager for database connections"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"Database error: {e}")
            raise
        finally:
            conn.close()
    
    def init_database(self):
        """Initialize database schema"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # TitleIDs table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS titleids (
                    titleid TEXT PRIMARY KEY,
                    name TEXT,
                    publisher TEXT,
                    release_date TEXT,
                    first_scraped TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_scraped TIMESTAMP,
                    scrape_count INTEGER DEFAULT 0,
                    metadata TEXT,
                    notes TEXT
                )
            ''')
            
            # Title Updates table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS title_updates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    titleid TEXT NOT NULL,
                    media_id TEXT,
                    version TEXT,
                    download_url TEXT,
                    file_size INTEGER,
                    file_path TEXT,
                    download_date TIMESTAMP,
                    status TEXT DEFAULT 'pending',
                    checksum TEXT,
                    metadata TEXT,
                    FOREIGN KEY (titleid) REFERENCES titleids(titleid),
                    UNIQUE(titleid, media_id, version)
                )
            ''')
            
            # Covers table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS covers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    titleid TEXT NOT NULL,
                    cover_url TEXT,
                    cover_type TEXT,
                    file_path TEXT,
                    download_date TIMESTAMP,
                    resolution TEXT,
                    file_size INTEGER,
                    status TEXT DEFAULT 'pending',
                    metadata TEXT,
                    FOREIGN KEY (titleid) REFERENCES titleids(titleid)
                )
            ''')
            
            # Download history table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS download_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    titleid TEXT NOT NULL,
                    item_type TEXT NOT NULL,
                    item_id TEXT,
                    status TEXT,
                    error_message TEXT,
                    download_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    duration_seconds REAL,
                    FOREIGN KEY (titleid) REFERENCES titleids(titleid)
                )
            ''')
            
            # Search index table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS search_index (
                    titleid TEXT PRIMARY KEY,
                    search_text TEXT,
                    FOREIGN KEY (titleid) REFERENCES titleids(titleid)
                )
            ''')
            
            # Create indexes
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_updates_titleid 
                ON title_updates(titleid)
            ''')
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_covers_titleid 
                ON covers(titleid)
            ''')
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_history_titleid 
                ON download_history(titleid)
            ''')
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_history_date 
                ON download_history(download_date)
            ''')
            
            logger.info(f"Database initialized at {self.db_path}")
    
    def add_titleid(self, titleid: str, name: str = None, 
                    publisher: str = None, metadata: Dict = None) -> bool:
        """Add or update a TitleID entry"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                metadata_json = json.dumps(metadata) if metadata else None
                
                cursor.execute('''
                    INSERT INTO titleids (titleid, name, publisher, metadata)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(titleid) DO UPDATE SET
                        name = COALESCE(excluded.name, name),
                        publisher = COALESCE(excluded.publisher, publisher),
                        metadata = COALESCE(excluded.metadata, metadata)
                ''', (titleid, name, publisher, metadata_json))
                
                # Update search index
                self._update_search_index(conn, titleid, name, publisher, metadata)
                
                logger.info(f"Added/updated TitleID: {titleid}")
                return True
                
        except Exception as e:
            logger.error(f"Failed to add TitleID {titleid}: {e}")
            return False
    
    def _update_search_index(self, conn, titleid: str, name: str = None, 
                            publisher: str = None, metadata: Dict = None):
        """Update full-text search index"""
        search_parts = [titleid]
        if name:
            search_parts.append(name)
        if publisher:
            search_parts.append(publisher)
        if metadata:
            search_parts.extend(str(v) for v in metadata.values() if v)
        
        search_text = ' '.join(search_parts).lower()
        
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO search_index (titleid, search_text)
            VALUES (?, ?)
            ON CONFLICT(titleid) DO UPDATE SET search_text = excluded.search_text
        ''', (titleid, search_text))
    
    def update_scrape_info(self, titleid: str):
        """Update scrape timestamp and count"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    UPDATE titleids 
                    SET last_scraped = CURRENT_TIMESTAMP,
                        scrape_count = scrape_count + 1
                    WHERE titleid = ?
                ''', (titleid,))
                logger.debug(f"Updated scrape info for {titleid}")
                return True
        except Exception as e:
            logger.error(f"Failed to update scrape info: {e}")
            return False
    
    def add_title_update(self, titleid: str, media_id: str, version: str,
                        download_url: str, file_path: str = None,
                        file_size: int = None, status: str = 'pending',
                        metadata: Dict = None) -> bool:
        """Add a title update entry"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                metadata_json = json.dumps(metadata) if metadata else None
                
                cursor.execute('''
                    INSERT INTO title_updates 
                    (titleid, media_id, version, download_url, file_path, 
                     file_size, download_date, status, metadata)
                    VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, ?, ?)
                    ON CONFLICT(titleid, media_id, version) DO UPDATE SET
                        file_path = COALESCE(excluded.file_path, file_path),
                        file_size = COALESCE(excluded.file_size, file_size),
                        download_date = CURRENT_TIMESTAMP,
                        status = excluded.status
                ''', (titleid, media_id, version, download_url, file_path, 
                      file_size, status, metadata_json))
                
                logger.info(f"Added update: {titleid} - {media_id} v{version} with status: {status}")
                return True
                
        except Exception as e:
            logger.error(f"Failed to add title update: {e}")
            return False
    
    def add_cover(self, titleid: str, cover_url: str, file_path: str = None,
                  cover_type: str = None, resolution: str = None,
                  file_size: int = None, status: str = 'pending', 
                  metadata: Dict = None) -> bool:
        """Add a cover entry"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                metadata_json = json.dumps(metadata) if metadata else None
                
                cursor.execute('''
                    INSERT INTO covers 
                    (titleid, cover_url, cover_type, file_path, resolution,
                     file_size, status, download_date, metadata)
                    VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, ?)
                ''', (titleid, cover_url, cover_type, file_path, resolution,
                      file_size, status, metadata_json))
                
                logger.info(f"Added cover for {titleid} with status: {status}")
                return True
                
        except Exception as e:
            logger.error(f"Failed to add cover: {e}")
            return False
    
    def add_download_history(self, titleid: str, item_type: str, 
                            status: str, item_id: str = None,
                            error_message: str = None, 
                            duration: float = None) -> bool:
        """Add download history entry"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO download_history 
                    (titleid, item_type, item_id, status, error_message, duration_seconds)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (titleid, item_type, item_id, status, error_message, duration))
                return True
        except Exception as e:
            logger.error(f"Failed to add history: {e}")
            return False
    
    def get_titleid_info(self, titleid: str) -> Optional[Dict[str, Any]]:
        """Get complete information about a TitleID"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                # Get basic info
                cursor.execute('SELECT * FROM titleids WHERE titleid = ?', (titleid,))
                row = cursor.fetchone()
                if not row:
                    return None
                
                info = dict(row)
                
                # Get updates
                cursor.execute('''
                    SELECT * FROM title_updates 
                    WHERE titleid = ? 
                    ORDER BY version DESC
                ''', (titleid,))
                info['updates'] = [dict(row) for row in cursor.fetchall()]
                
                # Get covers
                cursor.execute('''
                    SELECT * FROM covers 
                    WHERE titleid = ?
                    ORDER BY download_date DESC
                ''', (titleid,))
                info['covers'] = [dict(row) for row in cursor.fetchall()]
                
                return info
                
        except Exception as e:
            logger.error(f"Failed to get TitleID info: {e}")
            return None
    
    def search_titleids(self, query: str) -> List[Dict[str, Any]]:
        """Search for TitleIDs by name, publisher, or titleid"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                search_term = f"%{query.lower()}%"
                
                cursor.execute('''
                    SELECT t.* FROM titleids t
                    JOIN search_index s ON t.titleid = s.titleid
                    WHERE s.search_text LIKE ?
                    ORDER BY t.last_scraped DESC
                ''', (search_term,))
                
                return [dict(row) for row in cursor.fetchall()]
                
        except Exception as e:
            logger.error(f"Search failed: {e}")
            return []
    
    def get_all_titleids(self, limit: int = None) -> List[str]:
        """Get all TitleIDs in database"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                query = 'SELECT titleid FROM titleids ORDER BY last_scraped DESC'
                if limit:
                    query += f' LIMIT {limit}'
                
                cursor.execute(query)
                return [row['titleid'] for row in cursor.fetchall()]
                
        except Exception as e:
            logger.error(f"Failed to get titleids: {e}")
            return []
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get database statistics"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                stats = {}
                
                # Total TitleIDs
                cursor.execute('SELECT COUNT(*) as count FROM titleids')
                stats['total_titleids'] = cursor.fetchone()['count']
                
                # Total updates
                cursor.execute('SELECT COUNT(*) as count FROM title_updates')
                stats['total_updates'] = cursor.fetchone()['count']
                
                # Total covers
                cursor.execute('SELECT COUNT(*) as count FROM covers')
                stats['total_covers'] = cursor.fetchone()['count']
                
                # Recent downloads
                cursor.execute('''
                    SELECT COUNT(*) as count FROM download_history
                    WHERE download_date > datetime('now', '-7 days')
                ''')
                stats['downloads_last_week'] = cursor.fetchone()['count']
                
                # Most scraped
                cursor.execute('''
                    SELECT titleid, name, scrape_count 
                    FROM titleids 
                    ORDER BY scrape_count DESC 
                    LIMIT 5
                ''')
                stats['most_scraped'] = [dict(row) for row in cursor.fetchall()]
                
                # Recent activity
                cursor.execute('''
                    SELECT titleid, name, last_scraped 
                    FROM titleids 
                    WHERE last_scraped IS NOT NULL
                    ORDER BY last_scraped DESC 
                    LIMIT 10
                ''')
                stats['recent_activity'] = [dict(row) for row in cursor.fetchall()]
                
                return stats
                
        except Exception as e:
            logger.error(f"Failed to get statistics: {e}")
            return {}
    
    def cleanup_old_history(self, days: int = 90) -> int:
        """Remove download history older than specified days"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    DELETE FROM download_history
                    WHERE download_date < datetime('now', ? || ' days')
                ''', (f'-{days}',))
                deleted = cursor.rowcount
                logger.info(f"Cleaned up {deleted} old history entries")
                return deleted
        except Exception as e:
            logger.error(f"Failed to cleanup history: {e}")
            return 0
    
    def export_to_json(self, output_file: str) -> bool:
        """Export entire database to JSON"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                export_data = {
                    'export_date': datetime.now().isoformat(),
                    'titleids': [],
                    'statistics': self.get_statistics()
                }
                
                # Get all titleids with their data
                cursor.execute('SELECT titleid FROM titleids')
                for row in cursor.fetchall():
                    titleid = row['titleid']
                    info = self.get_titleid_info(titleid)
                    if info:
                        export_data['titleids'].append(info)
                
                with open(output_file, 'w') as f:
                    json.dump(export_data, f, indent=2, default=str)
                
                logger.info(f"Exported database to {output_file}")
                return True
                
        except Exception as e:
            logger.error(f"Export failed: {e}")
            return False
    
    def vacuum(self):
        """Optimize database"""
        try:
            with self.get_connection() as conn:
                conn.execute('VACUUM')
                logger.info("Database optimized")
        except Exception as e:
            logger.error(f"Vacuum failed: {e}")


# Example usage and testing
if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    
    # Initialize database
    db = DatabaseManager()
    
    # Add sample data
    db.add_titleid(
        'TESTID00',
        name='Test Game',
        publisher='Microsoft',
        metadata={'genre': 'FPS', 'year': 2007}
    )
    
    db.add_title_update(
        'TESTID00',
        media_id='12345678',
        version='3',
        download_url='http://example.com/update.bin',
        file_path='/path/to/update.bin',
        file_size=1024000
    )
    
    db.add_cover(
        'TESTID00',
        cover_url='http://example.com/cover.jpg',
        file_path='/path/to/cover.jpg',
        cover_type='front',
        resolution='1920x1080'
    )
    
    # Test search
    results = db.search_titleids('test')
    print(f"Search results: {results}")
    
    # Get statistics
    stats = db.get_statistics()
    print(f"Statistics: {json.dumps(stats, indent=2, default=str)}")
    
    # Export
    db.export_to_json('export.json')