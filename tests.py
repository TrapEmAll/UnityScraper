"""
Unit Tests for UnityScraper
Comprehensive test suite for all modules
"""

import unittest
import tempfile
import shutil
import json
import time
import zipfile
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
import requests

# Import modules to test
from main import Config, RateLimiter, UnityScraper
from database import DatabaseManager
from resume import ResumableDownloader, DownloadProgress, BatchDownloadManager
from consolemods_adapters import (
    parse_multi_id_document,
    parse_title_id_document,
    short_code_to_titleid,
)
from knowledge_base import EntityRecord, Fact, Identifier, KnowledgeRepository
from dat_adapters import parse_dat
from knowledge_service import KnowledgeService
from knowledge_sources import KnowledgeImportService, SourceInfo
from wiki_adapters import extract_article_text, parse_sitemap
from backup_manager import (
    BackupItem,
    FtpBackupClient,
    FtpTarget,
    InvalidPackageError,
    UnsafeArchiveError,
    atomic_copy,
    import_stfs_zip,
    inspect_stfs,
    inspect_xbe,
    package_destination,
    scan_local_target,
)
from backup_service import BackupRepository


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
        self.assertFalse(config.use_https)
        self.assertEqual(config.base_url, "http://xboxunity.net")
    
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

    def test_knowledge_schema_initialization(self):
        """Test normalized knowledge tables are created."""
        with self.db.get_connection() as conn:
            row = conn.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table' AND name = 'knowledge_facts'
                """
            ).fetchone()
        self.assertIsNotNone(row)

    def test_backup_schema_initialization(self):
        """Test additive backup inventory and operation tables are created."""
        expected = {
            "backup_targets",
            "backup_scans",
            "backup_inventory",
            "backup_operations",
        }
        with self.db.get_connection() as conn:
            rows = conn.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table' AND name LIKE 'backup_%'
                """
            ).fetchall()
        self.assertTrue(expected.issubset({row["name"] for row in rows}))
    
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

    def test_enrich_unknown_metadata_from_knowledge(self):
        """Test imported knowledge fills only unknown library fields."""
        with self.db.get_connection() as conn:
            repo = KnowledgeRepository(conn)
            source_id = repo.upsert_source("test", "Test Source")
            repo.upsert_entity_record(
                EntityRecord(
                    "game",
                    "South Park: The Stick of Truth",
                    identifiers=(Identifier("titleid", "555308C5"),),
                    facts=(
                        Fact("title", "South Park: The Stick of Truth"),
                        Fact("publisher", "Ubisoft"),
                    ),
                ),
                source_id,
            )

        self.db.add_titleid("555308C5", name="Unknown", publisher="Unknown Publisher")
        info = self.db.get_titleid_info("555308C5")
        self.assertEqual(info["name"], "South Park: The Stick of Truth")
        self.assertEqual(info["publisher"], "Ubisoft")

        self.db.add_titleid("555308C5", name="User Name", publisher="User Publisher")
        info = self.db.get_titleid_info("555308C5")
        self.assertEqual(info["name"], "User Name")
        self.assertEqual(info["publisher"], "User Publisher")


class TestConsoleModsAdapters(unittest.TestCase):
    """Test ConsoleMods parsing helpers."""

    def test_short_code_to_titleid(self):
        self.assertEqual(short_code_to_titleid("US-2245"), "555308C5")
        self.assertEqual(short_code_to_titleid("TT-2215"), "545408A7")

    def test_parse_title_id_document(self):
        sample = """
        ## US (5553) --> Ubisoft
        ### US-2245 (555308C5)
        South Park: The Stick of Truth
        ### US-2250 (555308CA)
        Far Cry 4 [World]
        ## V3 (5633) --> GameMill entertainment
        ### V3-2001 (563307D1)
        Country Dance All Stars
        """
        parsed = parse_title_id_document(sample)
        self.assertEqual(len(parsed), 3)
        self.assertEqual(parsed[0].titleid, "555308C5")
        self.assertEqual(parsed[0].publisher, "Ubisoft")
        self.assertEqual(parsed[1].region, "World")

    def test_parse_multi_id_document(self):
        sample = """
        #### BioShock
        TT-2008 --> BioShock (World)
        TT-2062 --> BioShock (Germany)
        TT-2079 --> BioShock (Japan)
        #### Diablo III
        9O-2001 --> Diablo III (World)
        9O-2004 --> Diablo III: Reaper of Souls: Ultimate Evil Edition (World)
        """
        parsed = parse_multi_id_document(sample)
        self.assertEqual(len(parsed), 5)
        bioshock = [item for item in parsed if item.title == "BioShock"]
        self.assertEqual(bioshock[0].titleid, "545407D8")
        self.assertIn("5454080E", bioshock[0].aliases)


class TestKnowledgeApplication(unittest.TestCase):
    """Test DAT ingestion, wiki parsing, and knowledge browser queries."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "knowledge.db"

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def test_parse_redump_style_dat(self):
        sample = """
        <datafile>
          <header><name>Microsoft - Xbox 360</name></header>
          <game name="Example Game (USA)">
            <description>Example Game (USA)</description>
            <region>USA</region>
            <serial>AB-1234</serial>
            <rom name="example.iso" size="1024"
                 crc="1234ABCD" md5="0123456789ABCDEF0123456789ABCDEF"
                 sha1="0123456789ABCDEF0123456789ABCDEF01234567"/>
          </game>
        </datafile>
        """
        records = parse_dat(sample, "disc_release")
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].canonical_name, "Example Game (USA)")
        identifiers = {(item.kind, item.value) for item in records[0].identifiers}
        self.assertIn(("serial", "AB-1234"), identifiers)
        self.assertIn(("crc32", "1234ABCD"), identifiers)
        self.assertIn(("sha1", "0123456789ABCDEF0123456789ABCDEF01234567"), identifiers)

    def test_parse_sitemap_and_article(self):
        sitemap = """
        <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
          <url><loc>https://free60.org/Hardware/</loc></url>
          <url><loc>https://free60.org/Formats/</loc></url>
        </urlset>
        """
        pages, children = parse_sitemap(sitemap)
        self.assertEqual(len(pages), 2)
        self.assertEqual(children, [])

        title, body = extract_article_text(
            "<html><head><title>NAND - Free60 Wiki</title></head>"
            "<body><h1>NAND</h1><p>Flash storage reference.</p>"
            "<script>ignore me</script></body></html>",
            "Fallback",
        )
        self.assertEqual(title, "NAND")
        self.assertIn("Flash storage reference.", body)
        self.assertNotIn("ignore me", body)

    def test_search_and_provenance_details(self):
        db = DatabaseManager(str(self.db_path))
        with db.get_connection() as connection:
            repository = KnowledgeRepository(connection)
            source_id = repository.upsert_source(
                "test-wiki",
                "Test Wiki",
                homepage_url="https://example.test/",
                license_name="CC BY 4.0",
            )
            repository.upsert_entity_record(
                EntityRecord(
                    entity_type="hardware",
                    canonical_name="Xenon Motherboard",
                    identifiers=(Identifier("part_number", "X803600-011"),),
                    facts=(Fact("nand_size", "16 MB"),),
                ),
                source_id,
            )

        service = KnowledgeService(self.db_path)
        results = service.search("X803600")
        self.assertEqual(len(results), 1)
        details = service.entity_details(results[0]["id"])
        self.assertEqual(details["entity"]["canonical_name"], "Xenon Motherboard")
        self.assertEqual(details["facts"][0]["source_name"], "Test Wiki")
        test_source = next(
            row for row in service.list_sources() if row["slug"] == "test-wiki"
        )
        self.assertEqual(test_source["license_name"], "CC BY 4.0")

    def test_failed_import_run_is_persisted(self):
        class FailingAdapter:
            source = SourceInfo("failing", "Failing Source", "https://example.test")
            adapter_name = "failing_adapter"

            @staticmethod
            def fetch_documents():
                raise RuntimeError("source unavailable")
                yield

            @staticmethod
            def parse_document(document):
                raise AssertionError(document)

        db = DatabaseManager(str(self.db_path))
        with db.get_connection() as connection:
            repository = KnowledgeRepository(connection)
            summary = KnowledgeImportService(repository).run_adapter(FailingAdapter())
            self.assertEqual(summary["status"], "failed")

        service = KnowledgeService(self.db_path)
        run = service.list_import_runs()[0]
        self.assertEqual(run["status"], "failed")
        self.assertIn("source unavailable", run["errors"])


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


class TestBackupManager(unittest.TestCase):
    """Test local Xbox backup inspection and safe transfer behavior."""

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def _stfs(
        self,
        name="package.bin",
        titleid="4D5307E6",
        mediaid="12345678",
        content_type=0x000D0000,
        title="Test Game",
    ):
        path = self.temp_dir / name
        header = bytearray(0x1791)
        header[:4] = b"LIVE"
        header[0x344:0x348] = content_type.to_bytes(4, "big")
        header[0x354:0x358] = bytes.fromhex(mediaid)
        header[0x360:0x364] = bytes.fromhex(titleid)
        header[0x366] = 1
        header[0x367] = 1
        encoded = title.encode("utf-16-be")
        header[0x411:0x411 + len(encoded)] = encoded
        header[0x1691:0x1691 + len(encoded)] = encoded
        path.write_bytes(header + b"payload")
        return path

    def test_inspect_stfs_and_destination(self):
        package = inspect_stfs(self._stfs())
        self.assertEqual(package.title_id, "4D5307E6")
        self.assertEqual(package.media_id, "12345678")
        self.assertEqual(package.content_label, "Xbox Live Arcade")
        destination = package_destination(package, self.temp_dir / "target")
        self.assertIn("000D0000", destination.parts)
        self.assertEqual(destination.parent.parent.name, "4D5307E6")

    def test_rejects_unknown_stfs_content_type(self):
        with self.assertRaises(InvalidPackageError):
            inspect_stfs(self._stfs(content_type=0xDEADBEEF))

    def test_atomic_copy_verifies_and_publishes(self):
        source = self.temp_dir / "source.bin"
        source.write_bytes(b"xbox" * 1000)
        destination = self.temp_dir / "out" / "destination.bin"
        result = atomic_copy(source, destination)
        self.assertEqual(result.status, "completed")
        self.assertEqual(source.read_bytes(), destination.read_bytes())
        self.assertFalse(destination.with_name("destination.bin.partial").exists())

    def test_zip_import_rejects_traversal(self):
        archive = self.temp_dir / "unsafe.zip"
        with zipfile.ZipFile(archive, "w") as handle:
            handle.writestr("../escape.bin", b"unsafe")
        with self.assertRaises(UnsafeArchiveError):
            import_stfs_zip(archive, self.temp_dir / "target")

    def test_zip_import_installs_package(self):
        package = self._stfs()
        archive = self.temp_dir / "packages.zip"
        with zipfile.ZipFile(archive, "w") as handle:
            handle.write(package, "nested/game")
        results = import_stfs_zip(archive, self.temp_dir / "target")
        self.assertEqual(len(results), 1)
        self.assertTrue(Path(results[0].destination).is_file())

    def test_zip_import_preserves_validated_content_tree(self):
        archive = self.temp_dir / "god.zip"
        with zipfile.ZipFile(archive, "w") as handle:
            handle.writestr(
                "Content/0000000000000000/4D5307E6/00007000/12345678",
                b"god-header",
            )
            handle.writestr(
                "Content/0000000000000000/4D5307E6/00007000/"
                "12345678.data/Data0000",
                b"god-chunk",
            )
            handle.writestr(
                "Content/0000000000000000/4D5307E6/DEADBEEF/ignored",
                b"unknown",
            )
        target = self.temp_dir / "target"
        results = import_stfs_zip(archive, target)
        self.assertEqual(len(results), 2)
        base = target / "Content" / "0000000000000000" / "4D5307E6"
        self.assertEqual(
            (base / "00007000" / "12345678.data" / "Data0000").read_bytes(),
            b"god-chunk",
        )
        self.assertFalse((base / "DEADBEEF" / "ignored").exists())

    def test_scan_detects_base_game_and_orphan_support_content(self):
        content = self.temp_dir / "Content" / "0000000000000000"
        base = content / "4D5307E6" / "00007000"
        orphan = content / "555308C5" / "000B0000"
        base.mkdir(parents=True)
        orphan.mkdir(parents=True)
        (base / "12345678").write_bytes(b"header")
        (orphan / "update").write_bytes(b"update")
        result = scan_local_target(self.temp_dir, lambda value: f"Game {value}")
        statuses = {item.title_id: item.status for item in result.items}
        self.assertEqual(statuses["4D5307E6"], "ready")
        self.assertEqual(statuses["555308C5"], "incomplete")
        self.assertEqual(len(result.warnings), 1)

    def test_inspect_xbe_certificate(self):
        path = self.temp_dir / "default.xbe"
        data = bytearray(0x300)
        data[:4] = b"XBEH"
        base = 0x10000
        certificate_offset = 0x180
        data[0x104:0x108] = base.to_bytes(4, "little")
        data[0x118:0x11C] = (base + certificate_offset).to_bytes(4, "little")
        data[certificate_offset + 0x8:certificate_offset + 0xC] = (
            0x4D530064
        ).to_bytes(4, "little")
        title = "Original Game".encode("utf-16-le")
        start = certificate_offset + 0xC
        data[start:start + len(title)] = title
        path.write_bytes(data)
        package = inspect_xbe(path)
        self.assertEqual(package.title_id, "4D530064")
        self.assertEqual(package.title_name, "Original Game")

    def test_backup_schema_is_additive_and_omits_passwords(self):
        repository = BackupRepository(self.temp_dir / "backup.db")
        repository.save_ftp_target(
            "Console",
            FtpTarget(host="192.0.2.10", password="do-not-store"),
        )
        rows = repository.list_targets()
        self.assertEqual(len(rows), 1)
        self.assertNotIn("do-not-store", rows[0]["settings_json"])

    def test_ftp_upload_skips_existing_remote_package(self):
        package = self._stfs()

        class FakeFtp:
            stored = False

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def mkd(self, _path):
                return None

            def voidcmd(self, _command):
                return "200"

            def size(self, _path):
                return 100

            def storbinary(self, *_args, **_kwargs):
                self.stored = True

        fake = FakeFtp()
        client = FtpBackupClient(FtpTarget(host="192.0.2.10"))
        with patch.object(client, "_connect", return_value=fake):
            result = client.upload_stfs(package)
        self.assertEqual(result.status, "skipped")
        self.assertFalse(fake.stored)


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
    suite.addTests(loader.loadTestsFromTestCase(TestConsoleModsAdapters))
    suite.addTests(loader.loadTestsFromTestCase(TestKnowledgeApplication))
    suite.addTests(loader.loadTestsFromTestCase(TestDownloadProgress))
    suite.addTests(loader.loadTestsFromTestCase(TestResumableDownloader))
    suite.addTests(loader.loadTestsFromTestCase(TestBatchDownloadManager))
    suite.addTests(loader.loadTestsFromTestCase(TestIntegration))
    suite.addTests(loader.loadTestsFromTestCase(TestBackupManager))
    
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
