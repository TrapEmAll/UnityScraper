"""
Integration Tests for UnityScraper Advanced Features
Tests for i18n, updater, queue_manager, speed monitoring, and API modes
"""

import unittest
import json
import tempfile
from pathlib import Path
from datetime import datetime, timedelta
import sys
import logging

# Suppress logging during tests
logging.disable(logging.CRITICAL)


class TestI18nModule(unittest.TestCase):
    """Test multi-language support"""
    
    def setUp(self):
        from i18n import init_translator, get_translator
        self.init_translator = init_translator
        self.get_translator = get_translator
    
    def test_translator_initialization(self):
        """Test translator initialization"""
        self.init_translator('en')
        translator = self.get_translator()
        self.assertIsNotNone(translator)
    
    def test_language_switching(self):
        """Test switching between languages"""
        self.init_translator('en')
        translator = self.get_translator()
        
        # Test English
        translator.set_language('en')
        self.assertEqual(translator.language, 'en')
        
        # Test Spanish
        translator.set_language('es')
        self.assertEqual(translator.language, 'es')
        
        # Test French
        translator.set_language('fr')
        self.assertEqual(translator.language, 'fr')
    
    def test_string_translation(self):
        """Test translating strings"""
        from i18n import t
        self.init_translator('en')
        
        # Test getting a translated string
        result = t('button_start')
        self.assertIsNotNone(result)
        self.assertIsInstance(result, str)
    
    def test_all_languages_loaded(self):
        """Test all languages are available"""
        from i18n import Translator
        translator = Translator()
        
        # Check translations dict
        for lang in ['en', 'es', 'fr', 'de', 'ja']:
            self.assertIn(lang, translator.translations)
            self.assertGreater(len(translator.translations[lang]), 0)
    
    def test_fallback_to_key(self):
        """Test fallback when key not found"""
        from i18n import t
        self.init_translator('en')
        
        # Non-existent key should return the key itself
        result = t('nonexistent_key_xyz')
        self.assertIsNotNone(result)


class TestUpdaterModule(unittest.TestCase):
    """Test version checking and update functionality"""
    
    def setUp(self):
        from updater import VersionChecker
        self.VersionChecker = VersionChecker
    
    def test_version_checker_initialization(self):
        """Test VersionChecker initialization"""
        checker = self.VersionChecker()
        self.assertIsNotNone(checker)
        self.assertTrue(hasattr(checker, 'check_for_updates'))
    
    def test_version_format_message(self):
        """Test version message formatting"""
        checker = self.VersionChecker()
        
        update_info = {
            'version': '1.2.0',
            'name': 'Release 1.2.0',
            'changes': 'New features and fixes',
            'download_url': 'https://github.com/example/releases/v1.2.0'
        }
        
        message = checker.format_update_message(update_info)
        self.assertIsNotNone(message)
        self.assertIn('1.2.0', message)
        self.assertIn('New features', message)
    
    def test_version_comparison(self):
        """Test version comparison logic"""
        from packaging import version
        
        v1 = version.parse('1.2.0')
        v2 = version.parse('1.2.1')
        self.assertLess(v1, v2)
        
        v3 = version.parse('2.0.0')
        self.assertLess(v2, v3)


class TestQueueManager(unittest.TestCase):
    """Test persistent download queue"""
    
    def setUp(self):
        from queue_manager import DownloadQueue
        self.DownloadQueue = DownloadQueue
        
        # Use temporary file for testing
        self.temp_file = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json')
        self.temp_file.close()
        self.queue_path = self.temp_file.name
    
    def tearDown(self):
        # Cleanup
        if Path(self.queue_path).exists():
            Path(self.queue_path).unlink()
    
    def test_queue_initialization(self):
        """Test queue initialization"""
        queue = self.DownloadQueue(queue_file=self.queue_path)
        self.assertIsNotNone(queue)
        self.assertTrue(hasattr(queue, 'add_item'))
        self.assertTrue(hasattr(queue, 'get_next_item'))
    
    def test_add_and_retrieve_item(self):
        """Test adding and retrieving items"""
        queue = self.DownloadQueue(queue_file=self.queue_path)
        
        # Add item
        item_id = queue.add_item('http://example.com/file.bin', 'test_title')
        self.assertIsNotNone(item_id)
        
        # Get next item
        next_item = queue.get_next_item()
        self.assertIsNotNone(next_item)
        self.assertEqual(next_item['url'], 'http://example.com/file.bin')
    
    def test_priority_ordering(self):
        """Test priority-based ordering"""
        queue = self.DownloadQueue(queue_file=self.queue_path)
        
        # Add low priority item
        id1 = queue.add_item('http://example.com/file1.bin', 'low_priority', priority=0)
        
        # Add high priority item
        id2 = queue.add_item('http://example.com/file2.bin', 'high_priority', priority=2)
        
        # High priority should be retrieved first
        next_item = queue.get_next_item()
        self.assertEqual(next_item['title'], 'high_priority')
    
    def test_queue_persistence(self):
        """Test queue persists across instances"""
        # Add item to queue
        queue1 = self.DownloadQueue(queue_file=self.queue_path)
        queue1.add_item('http://example.com/file.bin', 'test_item')
        
        # Create new queue instance from same file
        queue2 = self.DownloadQueue(queue_file=self.queue_path)
        
        # Item should still be there
        next_item = queue2.get_next_item()
        self.assertIsNotNone(next_item)
        self.assertEqual(next_item['title'], 'test_item')
    
    def test_status_transitions(self):
        """Test item status transitions"""
        queue = self.DownloadQueue(queue_file=self.queue_path)
        
        # Add item
        item_id = queue.add_item('http://example.com/file.bin', 'test')
        
        # Mark as downloading
        queue.mark_downloading(item_id)
        stats = queue.get_queue_stats()
        self.assertEqual(stats['downloading'], 1)
        
        # Mark as completed
        queue.mark_completed(item_id)
        stats = queue.get_queue_stats()
        self.assertEqual(stats['completed'], 1)
    
    def test_retry_failed_items(self):
        """Test retrying failed items"""
        queue = self.DownloadQueue(queue_file=self.queue_path)
        
        # Add and fail an item
        item_id = queue.add_item('http://example.com/file.bin', 'test')
        queue.mark_failed(item_id, 'Download error')
        
        # Retry should reset status
        queue.retry_failed(max_retries=3)
        stats = queue.get_queue_stats()
        self.assertGreater(stats['queued'], 0)
    
    def test_queue_statistics(self):
        """Test queue statistics"""
        queue = self.DownloadQueue(queue_file=self.queue_path)
        
        # Add multiple items
        for i in range(5):
            queue.add_item(f'http://example.com/file{i}.bin', f'item_{i}')
        
        # Get stats
        stats = queue.get_queue_stats()
        self.assertEqual(stats['total'], 5)
        self.assertEqual(stats['queued'], 5)


class TestSpeedMonitoring(unittest.TestCase):
    """Test download speed monitoring"""
    
    def setUp(self):
        from resume import DownloadProgress
        self.DownloadProgress = DownloadProgress
    
    def test_progress_initialization(self):
        """Test progress tracker initialization"""
        progress = self.DownloadProgress(1000, Path('test.bin'))
        self.assertIsNotNone(progress)
        self.assertEqual(progress.total_size, 1000)
    
    def test_progress_tracking(self):
        """Test progress update tracking"""
        progress = self.DownloadProgress(1000, Path('test.bin'))
        
        # Simulate chunk downloads
        for _ in range(10):
            progress.update(100)
        
        self.assertEqual(progress.downloaded, 1000)
        self.assertEqual(progress.percentage, 100.0)
    
    def test_speed_calculation(self):
        """Test speed calculation"""
        import time
        progress = self.DownloadProgress(1000, Path('test.bin'))
        
        # Simulate download
        progress.update(100)
        time.sleep(0.01)  # Small delay
        progress.update(100)
        
        speed = progress.speed_mbps
        self.assertGreaterEqual(speed, 0)
    
    def test_statistics_tracking(self):
        """Test speed statistics tracking"""
        progress = self.DownloadProgress(1000, Path('test.bin'))
        
        # Simulate chunks
        for _ in range(5):
            progress.update(200)
        
        stats = progress.get_stats()
        self.assertIn('current_speed', stats)
        self.assertIn('peak_speed', stats)
        self.assertIn('average_speed', stats)
        self.assertIn('percentage', stats)
    
    def test_eta_calculation(self):
        """Test ETA calculation"""
        import time
        progress = self.DownloadProgress(1000, Path('test.bin'))
        
        progress.update(500)
        time.sleep(0.01)
        progress.update(500)
        
        eta = progress.eta_seconds
        self.assertIsNotNone(eta)
        self.assertGreaterEqual(eta, 0)


class TestDatabaseIntegrity(unittest.TestCase):
    """Test database integrity checking"""
    
    def setUp(self):
        from database import DatabaseManager
        self.DatabaseManager = DatabaseManager
        
        # Create temp database
        self.temp_db = tempfile.NamedTemporaryFile(delete=False, suffix='.db')
        self.temp_db.close()
        self.db_path = self.temp_db.name
    
    def tearDown(self):
        # Cleanup
        if Path(self.db_path).exists():
            Path(self.db_path).unlink()
    
    def test_database_initialization(self):
        """Test database initialization"""
        db = self.DatabaseManager(self.db_path)
        self.assertIsNotNone(db)
        self.assertTrue(Path(self.db_path).exists())
    
    def test_add_titleid(self):
        """Test adding titleid"""
        db = self.DatabaseManager(self.db_path)
        result = db.add_titleid('TESTID00', 'Test Game', 'Test Publisher')
        self.assertTrue(result)
    
    def test_add_and_verify_cover(self):
        """Test adding and verifying cover"""
        db = self.DatabaseManager(self.db_path)
        db.add_titleid('TESTID00')
        
        result = db.add_cover(
            'TESTID00',
            cover_url='http://example.com/cover.jpg',
            file_path='/tmp/cover.jpg',
            status='downloaded'
        )
        self.assertTrue(result)
    
    def test_add_and_verify_update(self):
        """Test adding and verifying update"""
        db = self.DatabaseManager(self.db_path)
        db.add_titleid('TESTID00')
        
        result = db.add_title_update(
            'TESTID00',
            media_id='12345678',
            version='3',
            download_url='http://example.com/update.bin',
            status='downloaded'
        )
        self.assertTrue(result)
    
    def test_verify_file_integrity(self):
        """Test file integrity verification"""
        db = self.DatabaseManager(self.db_path)
        
        # Create test file
        test_file = Path(tempfile.gettempdir()) / 'test_file.bin'
        test_file.write_bytes(b'test content')
        
        try:
            db.add_titleid('TESTID00')
            db.add_cover(
                'TESTID00',
                cover_url='http://example.com/cover.jpg',
                file_path=str(test_file),
                status='downloaded'
            )
            
            # Verify integrity
            results = db.verify_file_integrity()
            self.assertIsNotNone(results)
            self.assertIn('verified', results)
            self.assertIn('corrupted', results)
            self.assertIn('missing', results)
        
        finally:
            if test_file.exists():
                test_file.unlink()
    
    def test_checksum_calculation(self):
        """Test file checksum calculation"""
        db = self.DatabaseManager(self.db_path)
        
        # Create test file
        test_file = Path(tempfile.gettempdir()) / 'test_checksum.bin'
        test_file.write_bytes(b'test content for checksum')
        
        try:
            checksum = db._calculate_file_checksum(test_file)
            self.assertIsNotNone(checksum)
            self.assertEqual(len(checksum), 64)  # SHA256 is 64 hex chars
            
            # Same content should produce same checksum
            checksum2 = db._calculate_file_checksum(test_file)
            self.assertEqual(checksum, checksum2)
        
        finally:
            if test_file.exists():
                test_file.unlink()


class TestAPIIntegration(unittest.TestCase):
    """Test REST API functionality"""
    
    def setUp(self):
        try:
            from api import UnityScraperAPI
            self.UnityScraperAPI = UnityScraperAPI
            self.api_available = True
        except ImportError:
            self.api_available = False
    
    def test_api_initialization(self):
        """Test API initialization"""
        if not self.api_available:
            self.skipTest("Flask not installed")
        
        api = self.UnityScraperAPI(scraper=None, port=8001)
        self.assertIsNotNone(api)
        self.assertIsNotNone(api.app)
    
    def test_api_routes_registered(self):
        """Test all API routes are registered"""
        if not self.api_available:
            self.skipTest("Flask not installed")
        
        api = self.UnityScraperAPI(scraper=None, port=8001)
        
        # Check key routes exist
        routes = [rule.rule for rule in api.app.url_map.iter_rules()]
        self.assertIn('/api/health', routes)
        self.assertIn('/api/statistics', routes)
        self.assertIn('/api/config', routes)


class TestFeatureIntegration(unittest.TestCase):
    """Test integration of all features together"""
    
    def test_i18n_with_gui_strings(self):
        """Test i18n provides all GUI strings"""
        from i18n import Translator
        translator = Translator()
        
        # Check critical UI strings exist in all languages
        critical_keys = [
            'button_start', 'button_stop', 'button_test',
            'title_main', 'label_titleids', 'label_output'
        ]
        
        for lang in ['en', 'es', 'fr', 'de', 'ja']:
            for key in critical_keys:
                self.assertIn(key, translator.translations[lang],
                            f"Missing key '{key}' in language '{lang}'")
    
    def test_queue_with_speed_monitoring(self):
        """Test queue items work with speed monitoring"""
        from queue_manager import DownloadQueue
        from resume import DownloadProgress
        
        queue = DownloadQueue()
        
        # Add item to queue
        item_id = queue.add_item('http://example.com/file.bin', 'test', priority=1)
        self.assertIsNotNone(item_id)
        
        # Create progress tracker (would be used during download)
        progress = DownloadProgress(1000, Path('file.bin'))
        progress.update(500)
        
        # Both should work independently
        self.assertIsNotNone(queue.get_next_item())
        self.assertGreater(progress.percentage, 0)
    
    def test_integrity_checker_with_database(self):
        """Test integrity checker works with database"""
        from database import DatabaseManager
        
        # Create temp database
        temp_db = tempfile.NamedTemporaryFile(delete=False, suffix='.db')
        temp_db.close()
        
        try:
            db = DatabaseManager(temp_db.name)
            db.add_titleid('TESTID00')
            
            # Run integrity check
            results = db.verify_file_integrity('TESTID00')
            self.assertIsNotNone(results)
            self.assertIn('total', results)
        
        finally:
            Path(temp_db.name).unlink()


def run_integration_tests():
    """Run all integration tests"""
    # Create test suite
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    # Add test classes
    suite.addTests(loader.loadTestsFromTestCase(TestI18nModule))
    suite.addTests(loader.loadTestsFromTestCase(TestUpdaterModule))
    suite.addTests(loader.loadTestsFromTestCase(TestQueueManager))
    suite.addTests(loader.loadTestsFromTestCase(TestSpeedMonitoring))
    suite.addTests(loader.loadTestsFromTestCase(TestDatabaseIntegrity))
    suite.addTests(loader.loadTestsFromTestCase(TestAPIIntegration))
    suite.addTests(loader.loadTestsFromTestCase(TestFeatureIntegration))
    
    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    return result.wasSuccessful()


if __name__ == '__main__':
    success = run_integration_tests()
    sys.exit(0 if success else 1)
