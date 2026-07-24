"""
Unit Tests for UnityScraper
Comprehensive test suite for all modules
"""

import unittest
import tempfile
import shutil
import json
import hashlib
import os
import sys
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
from external_tools import (
    ExternalToolError,
    ExternalToolRunner,
    format_command,
    split_arguments,
)
from external_tools_gui import bundled_xextool_path
from knowledge_service import KnowledgeService
from knowledge_sources import KnowledgeImportService, SourceInfo
from library_service import LibraryService
from modern_gui import XEXTOOL_CREATOR, navigation_shortcut
from title_catalog import XboxUnityTitleCatalog
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
from api import UnityScraperAPI
from app_version import DISPLAY_VERSION
from app_paths import resolve_storage_paths
from platform_support import desktop_font_family, path_opener_command


class TestPlatformSupport(unittest.TestCase):
    """Test cross-platform storage and desktop integration."""

    def test_linux_uses_xdg_directories(self):
        home = Path("/home/tester")
        paths = resolve_storage_paths(
            os_name="posix",
            platform_name="linux",
            environ={
                "XDG_DATA_HOME": "/xdg/data",
                "XDG_CONFIG_HOME": "/xdg/config",
                "XDG_CACHE_HOME": "/xdg/cache",
                "XDG_STATE_HOME": "/xdg/state",
            },
            home=home,
        )

        self.assertEqual(paths.base, Path("/xdg/data/unityscraper"))
        self.assertEqual(paths.config, Path("/xdg/config/unityscraper"))
        self.assertEqual(paths.cache, Path("/xdg/cache/unityscraper"))
        self.assertEqual(paths.logs, Path("/xdg/state/unityscraper/logs"))

    def test_linux_xdg_defaults_follow_home(self):
        home = Path("/home/tester")
        paths = resolve_storage_paths(
            os_name="posix",
            platform_name="linux",
            environ={},
            home=home,
        )

        self.assertEqual(paths.base, home / ".local/share/unityscraper")
        self.assertEqual(paths.config, home / ".config/unityscraper")
        self.assertEqual(paths.cache, home / ".cache/unityscraper")
        self.assertEqual(paths.logs, home / ".local/state/unityscraper/logs")

    def test_linux_ignores_relative_xdg_values(self):
        home = Path("/home/tester")
        paths = resolve_storage_paths(
            os_name="posix",
            platform_name="linux",
            environ={"XDG_CONFIG_HOME": "relative/config"},
            home=home,
        )

        self.assertEqual(paths.config, home / ".config/unityscraper")

    def test_portable_mode_keeps_everything_together(self):
        paths = resolve_storage_paths(portable_root=Path("/opt/unityscraper"))

        self.assertEqual(paths.base, Path("/opt/unityscraper/UnityScraperData"))
        self.assertEqual(paths.config, paths.base / "config")
        self.assertEqual(paths.cache, paths.base / "cache")

    def test_platform_openers(self):
        self.assertIsNone(path_opener_command(os_name="nt", platform_name="win32"))
        self.assertEqual(
            path_opener_command(os_name="posix", platform_name="darwin"),
            ["open"],
        )
        with patch("platform_support.shutil.which") as which:
            which.side_effect = lambda command: "/usr/bin/gio" if command == "gio" else None
            self.assertEqual(
                path_opener_command(os_name="posix", platform_name="linux"),
                ["gio", "open"],
            )

    def test_desktop_font_is_defined(self):
        self.assertTrue(desktop_font_family())

    def test_linux_desktop_metadata_is_complete(self):
        desktop = Path("packaging/linux/io.github.trapemall.UnityScraper.desktop")
        metadata = Path("packaging/linux/io.github.trapemall.UnityScraper.metainfo.xml")
        self.assertIn("Type=Application", desktop.read_text(encoding="utf-8"))
        self.assertIn("@EXEC@", desktop.read_text(encoding="utf-8"))

        import xml.etree.ElementTree as element_tree

        root = element_tree.parse(metadata).getroot()
        self.assertEqual(root.attrib["type"], "desktop-application")
        self.assertEqual(
            root.findtext("id"),
            "io.github.trapemall.UnityScraper",
        )


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

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.database = DatabaseManager(Path(self.temp_dir) / "scraper.db")

    def tearDown(self):
        shutil.rmtree(self.temp_dir)
    
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
        scraper = UnityScraper(config, database=self.database)
        
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
            scraper = UnityScraper(config, database=self.database)
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
            scraper = UnityScraper(config, database=self.database)
            
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


class TestXboxUnityTitleCatalog(unittest.TestCase):
    """Test persistent, HTTP-only XboxUnity title autocomplete data."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "catalog.db"
        self.database = DatabaseManager(self.db_path)

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    @staticmethod
    def _response(items, *, pages=1, page=0):
        response = Mock()
        response.url = (
            "http://xboxunity.net/Resources/Lib/TitleList.php"
            f"?category=0&count=100&page={page}"
        )
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "Items": items,
            "Count": len(items),
            "Pages": pages,
            "Page": page,
        }
        return response

    def test_sync_caches_every_page_and_searches_name_or_titleid(self):
        session = Mock()
        session.get.side_effect = [
            self._response(
                [
                    {
                        "TitleID": "4D5307E6",
                        "Name": "Halo 3",
                        "TitleType": "360",
                        "Covers": "40",
                        "Updates": "12",
                    }
                ],
                pages=2,
                page=0,
            ),
            self._response(
                [
                    {
                        "TitleID": "4D53085B",
                        "Name": "Halo: Reach",
                        "TitleType": "360",
                        "Covers": "28",
                        "Updates": "11",
                    }
                ],
                pages=2,
                page=1,
            ),
        ]
        catalog = XboxUnityTitleCatalog(
            self.db_path,
            session=session,
            request_interval=0,
        )

        result = catalog.sync()

        self.assertEqual(result.pages_fetched, 2)
        self.assertEqual(catalog.count(), 2)
        self.assertEqual(catalog.search("reach")[0].titleid, "4D53085B")
        self.assertEqual(catalog.search("4D5307")[0].name, "Halo 3")
        self.assertTrue(session.get.call_args_list[0].args[0].startswith("http://"))

    def test_catalog_enrichment_never_replaces_a_known_name(self):
        catalog = XboxUnityTitleCatalog(self.db_path)
        catalog._store_page(
            [
                {"TitleID": "4D5307E6", "Name": "Halo 3", "TitleType": "360"},
                {"TitleID": "4D53085B", "Name": "Halo: Reach", "TitleType": "360"},
            ],
            "http://xboxunity.net/Resources/Lib/TitleList.php?page=0",
        )
        self.database.add_titleid("4D5307E6", name="4D5307E6")
        self.database.add_titleid("4D53085B", name="My Preferred Reach Name")

        self.assertEqual(self.database.get_titleid_info("4D5307E6")["name"], "Halo 3")
        self.assertEqual(
            self.database.get_titleid_info("4D53085B")["name"],
            "My Preferred Reach Name",
        )

    def test_library_does_not_display_titleid_as_the_game_name(self):
        self.database.add_titleid("555308C5")

        games = LibraryService(self.db_path).list_games()

        self.assertEqual(games[0].name, "Unknown game")

    def test_library_uses_cached_catalog_name_before_sync_finishes(self):
        self.database.add_titleid("53510804")
        catalog = XboxUnityTitleCatalog(self.db_path)
        catalog._store_page(
            [{"TitleID": "53510804", "Name": "Hitman: Absolution", "TitleType": "360"}],
            "http://xboxunity.net/Resources/Lib/TitleList.php?page=47",
        )

        library = LibraryService(self.db_path)
        games = library.list_games("Hitman")
        details = library.get_game_details("53510804")

        self.assertEqual(games[0].name, "Hitman: Absolution")
        self.assertEqual(details["title"]["name"], "Hitman: Absolution")

    def test_failed_sync_keeps_page_progress_and_enriches_downloaded_names(self):
        self.database.add_titleid("53510804")
        session = Mock()
        session.get.side_effect = [
            self._response(
                [{"TitleID": "53510804", "Name": "Hitman: Absolution"}],
                pages=2,
                page=0,
            ),
            requests.ConnectionError("connection lost"),
        ]
        catalog = XboxUnityTitleCatalog(
            self.db_path,
            session=session,
            request_interval=0,
        )

        with self.assertRaises(requests.ConnectionError):
            catalog.sync()

        self.assertEqual(
            self.database.get_titleid_info("53510804")["name"],
            "Hitman: Absolution",
        )
        with self.database.get_connection() as connection:
            run = connection.execute(
                """
                SELECT status, pages_expected, pages_fetched, items_upserted
                FROM xboxunity_catalog_sync_runs
                ORDER BY id DESC
                LIMIT 1
                """
            ).fetchone()
        self.assertEqual(dict(run), {
            "status": "failed",
            "pages_expected": 2,
            "pages_fetched": 1,
            "items_upserted": 1,
        })

    def test_database_startup_repairs_names_from_an_interrupted_cache(self):
        self.database.add_titleid("53510804")
        catalog = XboxUnityTitleCatalog(self.db_path)
        catalog._store_page(
            [{"TitleID": "53510804", "Name": "Hitman: Absolution"}],
            "http://xboxunity.net/Resources/Lib/TitleList.php?page=47",
        )

        reopened = DatabaseManager(self.db_path)

        self.assertEqual(
            reopened.get_titleid_info("53510804")["name"],
            "Hitman: Absolution",
        )

    def test_non_http_xboxunity_base_url_is_rejected(self):
        with self.assertRaises(ValueError):
            XboxUnityTitleCatalog(self.db_path, base_url="https://xboxunity.net")


class TestExternalTools(unittest.TestCase):
    """Test shell-free execution for user-supplied command-line tools."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.input_path = Path(self.temp_dir) / "default.xex"
        self.input_path.write_bytes(b"XEX2")

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def test_xextool_template_splits_into_an_argument_vector(self):
        self.assertEqual(
            split_arguments('-l "{input}"', windows=True),
            ["-l", "{input}"],
        )

    def test_runner_substitutes_input_without_shell_interpretation(self):
        runner = ExternalToolRunner()
        marker = "value; echo this-is-data"

        result = runner.run(
            sys.executable,
            [
                "-c",
                "import sys; print(sys.argv[1]); print(sys.argv[2])",
                marker,
                "{input}",
            ],
            input_path=self.input_path,
        )

        self.assertEqual(result.returncode, 0)
        self.assertIn(marker, result.stdout)
        self.assertIn(str(self.input_path.resolve()), result.stdout)
        self.assertFalse(result.cancelled)

    def test_runner_rejects_missing_executable_and_input(self):
        runner = ExternalToolRunner()
        with self.assertRaises(ExternalToolError):
            runner.build_command(
                Path(self.temp_dir) / "missing.exe",
                ["{input}"],
                input_path=self.input_path,
            )
        with self.assertRaises(ExternalToolError):
            runner.build_command(
                sys.executable,
                ["{input}"],
                input_path=Path(self.temp_dir) / "missing.xex",
            )

    def test_command_preview_quotes_paths(self):
        preview = format_command(
            ("tool.exe", "folder with spaces/default.xex"),
            windows=True,
        )
        self.assertEqual(preview, 'tool.exe "folder with spaces/default.xex"')

    def test_tenth_navigation_page_uses_alt_zero(self):
        self.assertEqual(navigation_shortcut(1), "1")
        self.assertEqual(navigation_shortcut(9), "9")
        self.assertEqual(navigation_shortcut(10), "0")
        self.assertIsNone(navigation_shortcut(11))

    def test_bundled_xextool_has_documented_binary(self):
        binary = (
            Path(__file__).resolve().parent
            / "assets"
            / "tools"
            / "xextool"
            / "xextool.exe"
        )
        digest = hashlib.sha256(binary.read_bytes()).hexdigest().upper()
        self.assertEqual(
            digest,
            "D93C1B814AD6FF124834F4235BF8AAC9F09DBA8D69C335EBECC8D6EFE8D5A062",
        )
        self.assertEqual(bundled_xextool_path(), binary if os.name == "nt" else None)

    def test_about_credits_xextool_creator(self):
        self.assertEqual(XEXTOOL_CREATOR, "xorloser")


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
        facts = {(item.property, item.value) for item in records[0].facts}
        self.assertIn(("release_group", "Example Game"), facts)

    def test_dat_name_tags_add_release_relationship_facts(self):
        sample = """
        <datafile><game name="Example Game (Europe) (En,Fr) (Rev 2) (Disc 1 of 2)">
          <rom name="example.iso" size="1" crc="00000000"/>
        </game></datafile>
        """
        record = parse_dat(sample, "disc_release")[0]
        facts = {(item.property, item.value) for item in record.facts}
        self.assertIn(("region", "Europe"), facts)
        self.assertIn(("languages", "En, Fr"), facts)
        self.assertIn(("revision", "Rev 2"), facts)
        self.assertIn(("disc_count", "2"), facts)

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

    def test_atomic_copy_reports_mismatched_existing_file_as_conflict(self):
        source = self.temp_dir / "source.bin"
        destination = self.temp_dir / "destination.bin"
        source.write_bytes(b"new")
        destination.write_bytes(b"existing")
        result = atomic_copy(source, destination)
        self.assertEqual(result.status, "conflict")
        self.assertEqual(destination.read_bytes(), b"existing")

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


class TestRestAPI(unittest.TestCase):
    """Test API authentication and configuration safety boundaries."""

    def setUp(self):
        class FakeConfig:
            workers = 4
            rate_limit = 0.35
            timeout = 30
            max_retries = 3
            retry_backoff = 2.0
            bandwidth_limit = 0
            verify_checksums = False
            dry_run = False
            refresh_interval_days = 0
            base_url = "http://xboxunity.net"
            http_fallback_url = base_url
            use_https = False

        class FakeDatabase:
            @staticmethod
            def search_titleids(_query):
                return []

        class FakeScraper:
            config = FakeConfig()
            db = FakeDatabase()

            @staticmethod
            def validate_titleid(value):
                value = value.upper()
                if len(value) == 8 and all(
                    character in "0123456789ABCDEF" for character in value
                ):
                    return value
                return None

        self.scraper = FakeScraper()

    def test_remote_bind_requires_token(self):
        with self.assertRaises(ValueError):
            UnityScraperAPI(self.scraper, host="0.0.0.0")

    def test_health_reports_current_version_without_token(self):
        client = UnityScraperAPI(self.scraper, token="secret").app.test_client()
        response = client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["version"], DISPLAY_VERSION)

    def test_token_protects_non_health_routes(self):
        client = UnityScraperAPI(self.scraper, token="secret").app.test_client()
        self.assertEqual(client.get("/api/titleids").status_code, 401)
        response = client.get(
            "/api/titleids",
            headers={"Authorization": "Bearer secret"},
        )
        self.assertEqual(response.status_code, 200)

    def test_config_rejects_unknown_and_https_keys(self):
        client = UnityScraperAPI(self.scraper).app.test_client()
        response = client.post("/api/config", json={"use_https": True})
        self.assertEqual(response.status_code, 400)
        self.assertIn("Unsupported", response.get_json()["error"])

    def test_config_validates_and_applies_allowlisted_values(self):
        client = UnityScraperAPI(self.scraper).app.test_client()
        response = client.post(
            "/api/config",
            json={"workers": 8, "rate_limit": 0.5},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.scraper.config.workers, 8)
        self.assertEqual(self.scraper.config.rate_limit, 0.5)
        self.assertFalse(self.scraper.config.use_https)


class TestUnifiedV1Foundation(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "library.db"
        self.database = DatabaseManager(str(self.db_path))

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def test_versioned_migrations_create_all_foundation_tables(self):
        import sqlite3
        from contextlib import closing

        with closing(sqlite3.connect(self.db_path)) as connection:
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            versions = connection.execute(
                "SELECT version FROM app_schema_migrations ORDER BY version"
            ).fetchall()
        self.assertEqual([row[0] for row in versions], [1, 2, 3, 4, 5])
        self.assertIn("collection_snapshots", tables)
        self.assertIn("preservation_matches", tables)
        self.assertIn("console_transfer_jobs", tables)
        self.assertIn("metadata_overrides", tables)
        self.assertIn("xboxunity_title_catalog", tables)

    def test_xex_execution_info_is_parsed(self):
        from backup_manager import inspect_xex

        payload = bytearray(0x200)
        payload[:4] = b"XEX2"
        payload[4:8] = (8).to_bytes(4, "big")
        payload[0x14:0x18] = (1).to_bytes(4, "big")
        payload[0x18:0x1C] = (0x00040006).to_bytes(4, "big")
        payload[0x1C:0x20] = (0x80).to_bytes(4, "big")
        payload[0x80:0x84] = bytes.fromhex("11223344")
        payload[0x84:0x88] = (0x12345678).to_bytes(4, "big")
        payload[0x88:0x8C] = (0x10000001).to_bytes(4, "big")
        payload[0x8C:0x90] = bytes.fromhex("4D5307E6")
        payload[0x92] = 1
        payload[0x93] = 2
        xex = Path(self.temp_dir) / "default.xex"
        xex.write_bytes(payload)
        result = inspect_xex(xex)
        self.assertEqual(result.title_id, "4D5307E6")
        self.assertEqual(result.media_id, "11223344")
        self.assertEqual((result.disc_number, result.disc_count), (1, 2))

    def test_aurora_database_is_imported_read_only(self):
        import sqlite3
        from contextlib import closing
        from collection_intelligence import import_aurora_database

        aurora = Path(self.temp_dir) / "content.db"
        with closing(sqlite3.connect(aurora)) as connection:
            connection.execute(
                "CREATE TABLE ContentItems(TitleId TEXT, Name TEXT, MediaId TEXT, Path TEXT)"
            )
            connection.execute(
                "INSERT INTO ContentItems VALUES(?, ?, ?, ?)",
                ("4D5307E6", "Halo 3", "11223344", "/Hdd1/Games/Halo 3"),
            )
            connection.commit()
        result = import_aurora_database(aurora)
        self.assertEqual(len(result.items), 1)
        self.assertEqual(result.items[0].title_id, "4D5307E6")
        self.assertEqual(result.items[0].media_id, "11223344")

    def test_collection_analysis_uses_exact_media_id(self):
        from backup_manager import BackupItem, ScanResult
        from collection_intelligence import CollectionIntelligenceService

        self.database.add_titleid("4D5307E6", "Halo 3")
        self.database.add_title_update(
            "4D5307E6", "11223344", "6.0.1", "http://xboxunity.net/example"
        )
        item = BackupItem(
            Path(self.temp_dir) / "Halo 3",
            "4D5307E6",
            "Halo 3",
            "Extracted Xbox 360",
            100,
            media_id="11223344",
        )
        result = ScanResult(Path(self.temp_dir), [item], [], "2026-07-23T00:00:00Z")
        analysis = CollectionIntelligenceService(self.db_path).analyze_result(result, "test")
        self.assertEqual(analysis.compatibility[str(item.path)].status, "compatible")
        self.assertEqual(analysis.health_score, 100)

    def test_console_queue_recovers_interrupted_job(self):
        import sqlite3
        from contextlib import closing
        from console_sync import ConsoleSyncService

        service = ConsoleSyncService(self.db_path)
        job_id = service.enqueue("download", Path(self.temp_dir) / "file.bin", "/Hdd1/file.bin")
        with closing(sqlite3.connect(self.db_path)) as connection:
            connection.execute(
                "UPDATE console_transfer_jobs SET status='transferring' WHERE id=?", (job_id,)
            )
            connection.commit()
        recovered = ConsoleSyncService(self.db_path).list_jobs()[0]
        self.assertEqual(recovered["status"], "paused")

    def test_updater_selects_platform_asset_and_ignores_checksum(self):
        from updater import VersionChecker

        assets = [
            {"name": "UnityScraper-Windows-x64.zip.sha256"},
            {"name": "UnityScraper-Windows-x64.zip"},
            {"name": "UnityScraper-Linux-x86_64.tar.gz"},
        ]
        selected = VersionChecker.select_asset(assets, "Windows")
        self.assertEqual(selected["name"], "UnityScraper-Windows-x64.zip")


def run_tests():
    """Run all tests"""
    # Create test suite
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # Add all test classes
    suite.addTests(loader.loadTestsFromTestCase(TestPlatformSupport))
    suite.addTests(loader.loadTestsFromTestCase(TestConfig))
    suite.addTests(loader.loadTestsFromTestCase(TestRateLimiter))
    suite.addTests(loader.loadTestsFromTestCase(TestUnityScraper))
    suite.addTests(loader.loadTestsFromTestCase(TestDatabaseManager))
    suite.addTests(loader.loadTestsFromTestCase(TestXboxUnityTitleCatalog))
    suite.addTests(loader.loadTestsFromTestCase(TestExternalTools))
    suite.addTests(loader.loadTestsFromTestCase(TestConsoleModsAdapters))
    suite.addTests(loader.loadTestsFromTestCase(TestKnowledgeApplication))
    suite.addTests(loader.loadTestsFromTestCase(TestDownloadProgress))
    suite.addTests(loader.loadTestsFromTestCase(TestResumableDownloader))
    suite.addTests(loader.loadTestsFromTestCase(TestBatchDownloadManager))
    suite.addTests(loader.loadTestsFromTestCase(TestIntegration))
    suite.addTests(loader.loadTestsFromTestCase(TestBackupManager))
    suite.addTests(loader.loadTestsFromTestCase(TestRestAPI))
    suite.addTests(loader.loadTestsFromTestCase(TestUnifiedV1Foundation))
    
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
