"""
Unit Tests for UnityScraper
Comprehensive test suite for all modules
"""

import unittest
import tempfile
import shutil
import json
import time
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
import requests

# Import modules to test
from main import Config, RateLimiter, UnityScraper
from database import DatabaseManager
from resume import ResumableDownloader, DownloadProgress, BatchDownloadManager


class TestConfig(unittest.TestCase):
    """Test configuration management"""
    
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.config_file = Path(self.temp_dir) / "test_config.json"
    
    def tearDown(self):
        shutil.rmtree(self.temp_dir)
    
    def test_default_config(self):
        """Test default configuration values"""
        config = Config()
        self.assertEqual(config.workers, 4)
        self.assertEqual(config.rate_limit, 0.35)
        self.assertEqual(config.timeout, 30)
        self.assertTrue(config.use_https)
    
    def test_save_and_load_config(self):
        """Test saving and loading configuration"""
        config = Config()
        config.workers = 8
        config.rate_limit = 0.5
        config.save_to_file(str(self.config_file))
        
        # Load and verify
        loaded_config = Config(str(self.config_file))
        self.assertEqual(loaded_config.workers, 8)
        self.assertEqual(loaded_config.rate_limit, 0.5)
    
    def test_invalid_config_file(self):
        """Test handling of invalid config file"""
        invalid_file = Path(self.temp_dir) / "invalid.json"
        with open(invalid_file, 'w') as f:
            f.write("not valid json{")
        
        # Should use defaults without crashing
        config = Config(str(invalid_file))
        self.assertEqual(config.workers, 4)


class TestRateLimiter(unittest.TestCase):
    """Test rate limiting functionality"""
    
    def test_rate_limiting(self):
        """Test that rate limiter enforces minimum interval"""
        limiter = RateLimiter(0.1)
        
        start = time.time()
        limiter.wait()
        limiter.wait()
        elapsed = time.time() - start
        
        # Should take at least 0.1 seconds for second call
        self.assertGreaterEqual(elapsed, 0.1)
    
    def test_concurrent_rate_limiting(self):
        """Test rate limiter is thread-safe"""
        import threading
        
        limiter = RateLimiter(0.05)
        results = []
        
        def test_thread():
            start = time.time()
            limiter.wait()
            results.append(time.time() - start)
        
        threads = [threading.Thread(target=test_thread) for _ in range(5)]
        start = time.time()
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        total_time = time.time() - start
        # 5 calls with 0.05s interval should take at least 0.2s
        self.assertGreaterEqual(total_time, 0.2)


class TestUnityScraper(unittest.TestCase):
    """Test main scraper functionality"""
    
    def test_validate_titleid(self):
        """Test TitleID validation"""
        # Valid TitleIDs
        self.assertEqual(UnityScraper.validate_titleid('TESTID00'), 'TESTID00')
        self.assertEqual(UnityScraper.validate_titleid('testid00'), 'TESTID00')
        self.assertEqual(UnityScraper.validate_titleid('00000155'), '00000155')
        
        # Invalid TitleIDs
        self.assertIsNone(UnityScraper.validate_titleid('12345'))  # Too short
        self.assertIsNone(UnityScraper.validate_titleid('123456789'))  # Too long
        self.assertIsNone(UnityScraper.validate_titleid('GGGG8888'))  # Invalid hex
        self.assertIsNone(UnityScraper.validate_titleid(''))  # Empty
    
    @patch('main.UnityScraper._test_connection')
    def test_scraper_initialization(self, mock_test):
        """Test scraper initialization"""
        mock_test.return_value = None
        config = Config()
        scraper = UnityScraper(config)
        
        self.assertIsNotNone(scraper.session)
        self.assertIsNotNone(scraper.rate_limiter)
        mock_test.assert_called_once()
    
    @patch('requests.Session.get')
    def test_make_request_success(self, mock_get):
        """Test successful HTTP request"""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'test': 'data'}
        mock_get.return_value = mock_response
        
        config = Config()
        with patch.object(UnityScraper, '_test_connection'):
            scraper = UnityScraper(config)
            response = scraper._make_request('http://test.com')
        
        self.assertIsNotNone(response)
        self.assertEqual(response.status_code, 200)
    
    @patch('requests.Session.get')
    def test_make_request_rate_limit(self, mock_get):
        """Test handling of 429 rate limit"""
        mock_response = Mock()
        mock_response.status_code = 429
        mock_get.return_value = mock_response
        
        config = Config()
        config.max_retries = 1
        
        with patch.object(UnityScraper, '_test_connection'):
            scraper = UnityScraper(config)
            
            start = time.time()
            response = scraper._make_request('http://test.com')
            elapsed = time.time() - start
            
            # Should have waited before retry
            self.assertGreater(elapsed, 1.0)


class TestDatabaseManager(unittest.TestCase):
    """Test database functionality"""
    
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test.db"
        self.db = DatabaseManager(str(self.db_path))
    
    def tearDown(self):
        shutil.rmtree(self.temp_dir)
    
    def test_database_initialization(self):
        """Test database creation"""
        self.assertTrue(self.db_path.exists())
    
    def test_add_titleid(self):
        """Test adding TitleID"""
        success = self.db.add_titleid(
            'TESTID00',
            name='Test Game',
            publisher='Test Publisher'
        )
        self.assertTrue(success)
        
        # Verify it was added
        info = self.db.get_titleid_info('TESTID00')
        self.assertIsNotNone(info)
        self.assertEqual(info['name'], 'Test Game')
    
    def test_add_duplicate_titleid(self):
        """Test updating existing TitleID"""
        self.db.add_titleid('TESTID00', name='Game 1')
        self.db.add_titleid('TESTID00', name='Game 2')
        
        info = self.db.get_titleid_info('TESTID00')
        self.assertEqual(info['name'], 'Game 2')
    
    def test_add_title_update(self):
        """Test adding title update"""
        self.db.add_titleid('TESTID00')
        success = self.db.add_title_update(
            'TESTID00',
            media_id='12345678',
            version='3',
            download_url='http://test.com/update.bin'
        )
        self.assertTrue(success)
        
        info = self.db.get_titleid_info('TESTID00')
        self.assertEqual(len(info['updates']), 1)
        self.assertEqual(info['updates'][0]['version'], '3')
    
    def test_add_cover(self):
        """Test adding cover"""
        self.db.add_titleid('TESTID00')
        success = self.db.add_cover(
            'TESTID00',
            cover_url='http://test.com/cover.jpg',
            cover_type='front'
        )
        self.assertTrue(success)
        
        info = self.db.get_titleid_info('TESTID00')
        self.assertEqual(len(info['covers']), 1)
        self.assertEqual(info['covers'][0]['cover_type'], 'front')
    
    def test_search_titleids(self):
        """Test searching TitleIDs"""
        self.db.add_titleid('TESTID00', name='Test Game')
        self.db.add_titleid('TESTID01', name='Call of Duty')
        
        results = self.db.search_titleids('test')
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['titleid'], 'TESTID00')
    
    def test_statistics(self):
        """Test statistics generation"""
        self.db.add_titleid('TESTID00', name='Game 1')
        self.db.add_titleid('TESTID01', name='Game 2')
        self.db.add_title_update('TESTID00', 'media1', 'v1', 'http://test.com')
        
        stats = self.db.get_statistics()
        self.assertEqual(stats['total_titleids'], 2)
        self.assertEqual(stats['total_updates'], 1)
    
    def test_export_to_json(self):
        """Test JSON export"""
        self.db.add_titleid('TESTID00', name='Test Game')
        
        export_file = Path(self.temp_dir) / "export.json"
        success = self.db.export_to_json(str(export_file))
        
        self.assertTrue(success)
        self.assertTrue(export_file.exists())
        
        with open(export_file) as f:
            data = json.load(f)
            self.assertIn('titleids', data)
            self.assertIn('statistics', data)


class TestDownloadProgress(unittest.TestCase):
    """Test download progress tracking"""
    
    def test_progress_calculation(self):
        """Test progress percentage calculation"""
        progress = DownloadProgress(1000, Path('test.bin'))
        progress.update(500)
        
        self.assertEqual(progress.percentage, 50.0)
        self.assertEqual(progress.downloaded, 500)
    
    def test_speed_calculation(self):
        """Test download speed calculation"""
        progress = DownloadProgress(10000, Path('test.bin'))
        time.sleep(0.1)
        progress.update(5000)
        
        # Speed should be positive
        self.assertGreater(progress.speed_mbps, 0)
    
    def test_eta_calculation(self):
        """Test ETA calculation"""
        progress = DownloadProgress(10000, Path('test.bin'))
        time.sleep(0.1)
        progress.update(5000)
        
        eta = progress.eta_seconds
        self.assertIsNotNone(eta)
        self.assertGreater(eta, 0)


class TestResumableDownloader(unittest.TestCase):
    """Test resumable download functionality"""
    
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.session = requests.Session()
        self.downloader = ResumableDownloader(self.session)
    
    def tearDown(self):
        shutil.rmtree(self.temp_dir)
    
    def test_checksum_calculation(self):
        """Test checksum calculation"""
        test_file = Path(self.temp_dir) / "test.txt"
        test_file.write_text("Hello, World!")
        
        checksum = self.downloader.calculate_checksum(test_file)
        self.assertIsInstance(checksum, str)
        self.assertEqual(len(checksum), 64)  # SHA256 length
    
    def test_checksum_verification(self):
        """Test checksum verification"""
        test_file = Path(self.temp_dir) / "test.txt"
        test_file.write_text("Hello, World!")
        
        correct_checksum = self.downloader.calculate_checksum(test_file)
        wrong_checksum = "0" * 64
        
        self.assertTrue(self.downloader.verify_checksum(test_file, correct_checksum))
        self.assertFalse(self.downloader.verify_checksum(test_file, wrong_checksum))
    
    def test_temp_filepath(self):
        """Test temporary file path generation"""
        dest = Path(self.temp_dir) / "file.bin"
        temp = self.downloader.get_temp_filepath(dest)
        
        self.assertEqual(temp.name, "file.bin.partial")
        self.assertEqual(temp.parent, dest.parent)
    
    def test_metadata_save_load(self):
        """Test metadata save and load"""
        dest = Path(self.temp_dir) / "file.bin"
        
        self.downloader.save_metadata(dest, "http://test.com", 1000, "abc123")
        metadata = self.downloader.load_metadata(dest)
        
        self.assertIsNotNone(metadata)
        self.assertEqual(metadata['url'], "http://test.com")
        self.assertEqual(metadata['total_size'], 1000)
        self.assertEqual(metadata['checksum'], "abc123")


class TestBatchDownloadManager(unittest.TestCase):
    """Test batch download management"""
    
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        session = requests.Session()
        downloader = ResumableDownloader(session)
        self.manager = BatchDownloadManager(downloader)
    
    def tearDown(self):
        shutil.rmtree(self.temp_dir)
    
    def test_add_download(self):
        """Test adding downloads to queue"""
        download_id = self.manager.add_download(
            'http://test.com/file.bin',
            Path(self.temp_dir) / 'file.bin'
        )
        
        self.assertIsNotNone(download_id)
        self.assertEqual(len(self.manager.active_downloads), 1)
    
    def test_get_status(self):
        """Test status reporting"""
        self.manager.add_download('http://test.com/1.bin', Path(self.temp_dir) / '1.bin')
        self.manager.add_download('http://test.com/2.bin', Path(self.temp_dir) / '2.bin')
        
        status = self.manager.get_status()
        self.assertEqual(status['total'], 2)
        self.assertEqual(status['completed'], 0)


class TestIntegration(unittest.TestCase):
    """Integration tests for complete workflows"""
    
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test.db"
    
    def tearDown(self):
        shutil.rmtree(self.temp_dir)
    
    def test_complete_workflow(self):
        """Test complete download and database workflow"""
        # Initialize database
        db = DatabaseManager(str(self.db_path))
        
        # Add TitleID
        db.add_titleid('TESTID00', name='Test Game')
        
        # Simulate adding updates and covers
        db.add_title_update(
            'TESTID00',
            media_id='12345678',
            version='3',
            download_url='http://test.com/update.bin',
            file_path=str(Path(self.temp_dir) / 'update.bin')
        )
        
        db.add_cover(
            'TESTID00',
            cover_url='http://test.com/cover.jpg',
            file_path=str(Path(self.temp_dir) / 'cover.jpg')
        )
        
        # Verify everything was stored
        info = db.get_titleid_info('TESTID00')
        self.assertIsNotNone(info)
        self.assertEqual(len(info['updates']), 1)
        self.assertEqual(len(info['covers']), 1)
        
        # Test export
        export_file = Path(self.temp_dir) / "export.json"
        db.export_to_json(str(export_file))
        self.assertTrue(export_file.exists())


def run_tests():
    """Run all tests"""
    # Create test suite
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    # Add all test classes
    suite.addTests(loader.loadTestsFromTestCase(TestConfig))
    suite.addTests(loader.loadTestsFromTestCase(TestRateLimiter))
    suite.addTests(loader.loadTestsFromTestCase(TestUnityScraper))
    suite.addTests(loader.loadTestsFromTestCase(TestDatabaseManager))
    suite.addTests(loader.loadTestsFromTestCase(TestDownloadProgress))
    suite.addTests(loader.loadTestsFromTestCase(TestResumableDownloader))
    suite.addTests(loader.loadTestsFromTestCase(TestBatchDownloadManager))
    suite.addTests(loader.loadTestsFromTestCase(TestIntegration))
    
    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    # Print summary
    print("\n" + "="*70)
    print("TEST SUMMARY")
    print("="*70)
    print(f"Tests run: {result.testsRun}")
    print(f"Successes: {result.testsRun - len(result.failures) - len(result.errors)}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")
    print("="*70)
    
    return result.wasSuccessful()


if __name__ == '__main__':
    success = run_tests()
    exit(0 if success else 1)