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
import sqlite3
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
from tool_catalog import ToolCatalog, ToolDefinition, operation_for
from knowledge_service import KnowledgeService
from knowledge_sources import (
    CachedHttpClient,
    KnowledgeImportService,
    SourceAccessBlockedError,
    SourceInfo,
)
from offline_knowledge import OfflineKnowledgeArchive
from library_service import GameSummary, LibraryService
from modern_gui import LE_FLUFFIE_CREATOR, XEXTOOL_CREATOR, navigation_shortcut
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
    extract_stfs_files,
    inspect_stfs,
    inspect_xbe,
    list_stfs_entries,
    package_destination,
    scan_local_target,
)
from backup_service import BackupRepository, BackupService
from api import UnityScraperAPI
from app_version import DISPLAY_VERSION
from app_paths import resolve_storage_paths
from platform_support import desktop_font_family, path_opener_command
from profile_manager import ProfileSaveManager, find_content_root, mask_identifier
from unityscraper.app.api.entrypoint import create_api
from unityscraper.app.cli import CliCommand, CliCommandRegistry, build_cli_registry
from unityscraper.app.cli.legacy import run_legacy_cli
from unityscraper.app.desktop.entrypoint import main as package_desktop_main
from unityscraper.core import APP_METADATA
from unityscraper.core.db import MigrationRegistry
from unityscraper.core.jobs import CancellationToken, JobProgress, JobResult, JobRunner
from unityscraper.core.paths import app_root as package_app_root
from unityscraper.core.paths import resource_path as package_resource_path
from unityscraper.core.version import DISPLAY_VERSION as PACKAGE_DISPLAY_VERSION
from unityscraper.domains.backups.service import BackupService as ModularBackupService
from unityscraper.domains.backups.migrations import ensure_backup_schema as DomainBackupSchema
from unityscraper.domains.knowledge.models import EntityRecord as ModularEntityRecord
from unityscraper.domains.library.models import GameSummary as ModularGameSummary
from unityscraper.domains.library.service import LibraryService as ModularLibraryService
from unityscraper.domains.packages.commands import InspectStfsPackage, InventoryStfsFileTable
from unityscraper.domains.tools.catalog import ToolCatalog as ModularToolCatalog
from unityscraper.domains.tools.models import ToolDefinition as ModularToolDefinition
from unityscraper.domains.tools.runner import ExternalToolRunner as ModularToolRunner


class TestPlatformSupport(unittest.TestCase):
    """Test cross-platform storage and desktop integration."""

    def test_legacy_translations_are_repaired_at_load_time(self):
        from i18n import TRANSLATIONS

        self.assertEqual(TRANSLATIONS["es"]["settings"], "Configuraci\u00f3n")
        self.assertEqual(TRANSLATIONS["ja"]["browse"], "\u53c2\u7167")

    def test_bounded_language_pack_extends_navigation_with_english_fallback(self):
        from i18n import init_translator

        root = Path(tempfile.mkdtemp())
        try:
            (root / "nl.json").write_text(json.dumps({
                "language": "nl", "strings": {"nav_library": "BIBLIOTHEEK"}
            }), encoding="utf-8")
            translator = init_translator("nl", root)
            self.assertEqual(translator.get("nav_library"), "BIBLIOTHEEK")
            self.assertEqual(translator.get("nav_settings"), "SETTINGS")
        finally:
            shutil.rmtree(root)

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

    def test_macos_uses_native_user_directories(self):
        home = Path("/Users/tester")
        paths = resolve_storage_paths(
            os_name="posix", platform_name="darwin", environ={}, home=home
        )
        self.assertEqual(
            paths.base, home / "Library" / "Application Support" / "UnityScraper"
        )
        self.assertEqual(paths.cache, home / "Library" / "Caches" / "UnityScraper")
        self.assertEqual(paths.logs, home / "Library" / "Logs" / "UnityScraper")

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

    def test_pyinstaller_collects_package_modules(self):
        spec = Path("UnityScraper.spec").read_text(encoding="utf-8")

        self.assertIn("collect_submodules('unityscraper')", spec)


class TestModularFoundation(unittest.TestCase):
    """Test package ownership and legacy compatibility boundaries."""

    def test_domain_service_exports_preserve_existing_implementations(self):
        self.assertIs(ModularBackupService, BackupService)
        self.assertIs(ModularLibraryService, LibraryService)
        self.assertIs(ModularGameSummary, GameSummary)
        self.assertIs(ModularEntityRecord, EntityRecord)
        self.assertIs(ModularToolDefinition, ToolDefinition)
        self.assertIs(ModularToolCatalog, ToolCatalog)
        self.assertIs(ModularToolRunner, ExternalToolRunner)

    def test_migrated_implementations_are_domain_owned(self):
        self.assertEqual(
            ModularLibraryService.__module__,
            "unityscraper.domains.library.service",
        )
        self.assertEqual(
            ModularGameSummary.__module__,
            "unityscraper.domains.library.models",
        )
        self.assertEqual(
            ModularToolCatalog.__module__,
            "unityscraper.domains.tools.catalog",
        )
        self.assertEqual(
            ModularToolRunner.__module__,
            "unityscraper.domains.tools.runner",
        )

    def test_backup_schema_is_domain_owned_with_legacy_compatibility(self):
        from backup_service import ensure_backup_schema as LegacyBackupSchema

        self.assertIs(LegacyBackupSchema, DomainBackupSchema)

    def test_package_inspection_command_returns_job_result(self):
        root = Path(tempfile.mkdtemp())
        try:
            package = root / "save.bin"
            header = bytearray(0x1791)
            header[:4] = b"CON "
            header[0x344:0x348] = (1).to_bytes(4, "big")
            header[0x354:0x358] = bytes.fromhex("12345678")
            header[0x360:0x364] = bytes.fromhex("53510804")
            title = "Hitman: Absolution".encode("utf-16-be")
            header[0x411:0x411 + len(title)] = title
            package.write_bytes(header)

            result = InspectStfsPackage().run(package)

            self.assertEqual(result.status, "completed")
            self.assertEqual(result.payload["package"]["title_id"], "53510804")
            self.assertEqual(result.payload["package"]["display_name"], "Hitman: Absolution")
        finally:
            shutil.rmtree(root)

    def test_package_inventory_command_returns_failed_job_result(self):
        root = Path(tempfile.mkdtemp())
        try:
            package = root / "invalid.bin"
            package.write_bytes(b"not a package")

            result = InventoryStfsFileTable().run(package)

            self.assertEqual(result.status, "failed")
            self.assertEqual(result.payload["source"], str(package))
        finally:
            shutil.rmtree(root)

    def test_core_paths_match_legacy_asset_resolution(self):
        self.assertEqual(package_app_root(), Path.cwd())
        self.assertTrue(package_resource_path("JSON.txt").is_file())

    def test_core_metadata_matches_legacy_version(self):
        self.assertEqual(PACKAGE_DISPLAY_VERSION, DISPLAY_VERSION)
        self.assertEqual(APP_METADATA.name, "UnityScraper")
        self.assertEqual(APP_METADATA.display_version, DISPLAY_VERSION)

    def test_cli_registry_exposes_legacy_adapter(self):
        registry = build_cli_registry()
        command = registry.get("legacy")

        self.assertIn("legacy", registry.as_dict())
        self.assertEqual(command.description, "Run the existing full UnityScraper CLI surface.")

    def test_cli_registry_rejects_duplicate_command_names(self):
        registry = CliCommandRegistry()
        command = CliCommand(name="example", description="Example", handler=lambda argv: 0)
        registry.register(command)

        with self.assertRaises(ValueError):
            registry.register(command)

    def test_legacy_cli_adapter_restores_sys_argv(self):
        original = sys.argv[:]
        with patch("main.main", return_value=None) as legacy:
            result = run_legacy_cli(["--help"])

        self.assertEqual(result, 0)
        self.assertEqual(sys.argv, original)
        self.assertEqual(legacy.call_count, 1)

    def test_app_surface_entrypoints_delegate_lazily(self):
        with patch("desktop_app.main", return_value=0) as desktop:
            self.assertEqual(package_desktop_main(), 0)
        with patch("api.UnityScraperAPI", return_value="api") as api_class:
            self.assertEqual(create_api(), "api")

        self.assertEqual(desktop.call_count, 1)
        self.assertEqual(api_class.call_count, 1)

    def test_job_progress_percent_is_bounded(self):
        self.assertEqual(
            JobProgress(status="running", message="working", current=5, total=10).percent,
            50.0,
        )
        self.assertEqual(
            JobProgress(status="running", message="over", current=15, total=10).percent,
            100.0,
        )
        self.assertIsNone(JobProgress(status="running", message="unknown").percent)

    def test_job_result_factories_set_terminal_state(self):
        completed = JobResult.completed("done", count=2)
        failed = JobResult.failed("failed", reason="example")
        cancelled = JobResult.cancelled()

        self.assertEqual(completed.status, "completed")
        self.assertEqual(completed.payload["count"], 2)
        self.assertIsNotNone(completed.finished_at)
        self.assertEqual(failed.status, "failed")
        self.assertEqual(failed.payload["reason"], "example")
        self.assertIsNotNone(failed.finished_at)
        self.assertEqual(cancelled.status, "cancelled")
        self.assertIsNotNone(cancelled.finished_at)

    def test_job_runner_normalizes_success_failure_and_progress(self):
        progress = []
        runner = JobRunner(progress_callback=progress.append)

        success = runner.run(
            "example",
            lambda context: JobResult.completed("done", name=context.name),
        )

        failure = runner.run(
            "failing",
            lambda context: (_ for _ in ()).throw(RuntimeError("boom")),
        )

        self.assertEqual(success.status, "completed")
        self.assertEqual(success.payload["name"], "example")
        self.assertEqual(failure.status, "failed")
        self.assertEqual(failure.payload["job"], "failing")
        self.assertGreaterEqual(len(progress), 4)
        self.assertEqual(progress[0].message, "example started")

    def test_job_runner_honors_pre_cancelled_token(self):
        token = CancellationToken()
        token.cancel()

        result = JobRunner().run(
            "cancelled",
            lambda context: JobResult.completed("should not run"),
            token=token,
        )

        self.assertEqual(result.status, "cancelled")
        self.assertEqual(result.payload["job"], "cancelled")

    def test_domain_migration_registry_applies_once(self):
        calls = []

        def migration(connection):
            calls.append("applied")
            connection.execute("CREATE TABLE example_domain_table (id INTEGER PRIMARY KEY)")

        registry = MigrationRegistry()
        registry.register(domain="example", version=1, name="example schema", apply=migration)

        with sqlite3.connect(":memory:") as connection:
            first = registry.apply(connection)
            second = registry.apply(connection)
            table = connection.execute(
                """
                SELECT name FROM sqlite_master
                WHERE type = 'table' AND name = 'example_domain_table'
                """
            ).fetchone()

        self.assertEqual([item.key for item in first], ["example:1"])
        self.assertEqual(second, [])
        self.assertEqual(calls, ["applied"])
        self.assertIsNotNone(table)


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

    def test_runner_supports_directory_input_and_output(self):
        runner = ExternalToolRunner()
        source = Path(self.temp_dir) / "source"
        output = Path(self.temp_dir) / "output"
        source.mkdir()
        output.mkdir()

        command = runner.build_command(
            sys.executable,
            ["{input}", "{output}"],
            input_path=source,
            output_path=output,
            input_kind="directory",
            output_kind="directory",
        )

        self.assertEqual(command[1:], (str(source.resolve()), str(output.resolve())))

    def test_unused_paths_are_ignored_for_launch_only_operations(self):
        runner = ExternalToolRunner()

        command = runner.build_command(
            sys.executable,
            (),
            input_path=Path(self.temp_dir) / "stale-missing-input",
            output_path=Path(self.temp_dir) / "stale-missing-output",
            input_kind="none",
            output_kind="none",
        )

        self.assertEqual(command, (str(Path(sys.executable).resolve()),))

    def test_catalog_contains_requested_tools_and_excludes_omissions(self):
        catalog = ToolCatalog(Path(self.temp_dir) / "config.json")
        tool_ids = {tool.id for tool in catalog.definitions()}

        self.assertTrue(
            {
                "xextool",
                "extract-xiso",
                "xenia",
                "xenia-canary",
                "velocity",
                "iso2god",
                "god2iso",
                "xbox-image-browser",
                "le-fluffie",
                "custom",
            }.issubset(tool_ids)
        )
        self.assertNotIn("fatxplorer", tool_ids)
        self.assertNotIn("j-runner", tool_ids)

    def test_extract_xiso_operations_are_explicit_and_guarded(self):
        tool = ToolCatalog(Path(self.temp_dir) / "config.json").get("extract-xiso")
        extract = operation_for(tool, "extract")
        rewrite = operation_for(tool, "rewrite")
        xextool = ToolCatalog(Path(self.temp_dir) / "config.json").get("xextool")
        custom = operation_for(xextool, "custom")

        self.assertEqual(extract.arguments, ("-x", "{input}", "-d", "{output}"))
        self.assertEqual((extract.input_kind, extract.output_kind), ("file", "directory"))
        self.assertTrue(rewrite.destructive)
        self.assertTrue(custom.destructive)

    def test_catalog_persists_and_hashes_user_selected_executable(self):
        config_path = Path(self.temp_dir) / "config.json"
        executable = Path(self.temp_dir) / "extract-xiso.exe"
        executable.write_bytes(b"test executable")
        catalog = ToolCatalog(config_path)

        saved = catalog.save_path("extract-xiso", executable)

        self.assertEqual(saved, executable.resolve())
        self.assertEqual(catalog.configured_path("extract-xiso"), executable.resolve())
        self.assertEqual(
            catalog.checksum(executable),
            hashlib.sha256(b"test executable").hexdigest().upper(),
        )

    @patch("unityscraper.domains.tools.runner.subprocess.Popen")
    def test_detached_launch_uses_argument_vector(self, popen):
        popen.return_value.pid = 360
        runner = ExternalToolRunner()

        launched = runner.launch_detached(
            sys.executable,
            ("{input}",),
            input_path=self.input_path,
            input_kind="file",
        )

        self.assertEqual(launched.pid, 360)
        self.assertEqual(launched.command[1], str(self.input_path.resolve()))
        self.assertFalse(popen.call_args.kwargs["shell"])

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

    def test_about_credits_le_fluffie_creator(self):
        self.assertEqual(LE_FLUFFIE_CREATOR, "Dalavin (DJ SkunkieButt)")


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


class TestOfflineKnowledgeArchive(unittest.TestCase):
    """Test blocked-source fallback, saved-page import, and local rendering."""

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.db_path = self.temp_dir / "knowledge.db"
        self.cache_dir = self.temp_dir / "cache"
        self.output_dir = self.temp_dir / "offline"

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    @staticmethod
    def _response(status: int, text: str, url: str):
        response = Mock()
        response.status_code = status
        response.text = text
        response.url = url
        response.headers = {"Server": "cloudflare"} if status != 200 else {}
        if status == 200:
            response.raise_for_status.return_value = None
        return response

    def test_browser_challenge_uses_cache_and_preserves_fetch_time(self):
        url = "https://xenonlibrary.com/wiki/Motherboard"
        session = Mock()
        session.get.side_effect = (
            self._response(200, "<html><h1>Motherboard</h1><p>Known data.</p></html>", url),
            self._response(403, "<html><title>Just a moment</title></html>", url),
        )
        client = CachedHttpClient(
            cache_dir=self.cache_dir,
            rate_limit_seconds=0,
            session=session,
        )
        fresh = client.get_text(url, "Motherboard", "wiki_article")
        cached = client.get_text(url, "Motherboard", "wiki_article")
        cached_again = client.get_text(url, "Motherboard", "wiki_article")
        self.assertTrue(cached.from_cache)
        self.assertTrue(cached_again.from_cache)
        self.assertEqual(cached.fetched_at, fresh.fetched_at)
        self.assertIn("browser verification", cached.fetch_error)
        self.assertEqual(session.get.call_count, 2)
        self.assertEqual(client.cached_urls(("xenonlibrary.com",)), [url])

    def test_browser_challenge_without_cache_has_actionable_error(self):
        url = "https://consolemods.org/wiki/Xbox_360:Main_Page"
        session = Mock()
        session.get.return_value = self._response(
            403, "<html><title>Just a moment</title></html>", url
        )
        client = CachedHttpClient(
            cache_dir=self.cache_dir,
            rate_limit_seconds=0,
            session=session,
        )
        with self.assertRaisesRegex(SourceAccessBlockedError, "Import Saved Wiki Pages"):
            client.get_text(url, "Xbox 360", "wiki_article")

    def test_saved_page_import_builds_script_free_offline_article(self):
        saved = self.temp_dir / "motherboard.html"
        saved.write_text(
            """<html><head><title>Motherboard - XenonLibrary</title>
            <link rel="canonical" href="https://xenonlibrary.com/wiki/Motherboard">
            <script src="https://tracker.invalid/a.js"></script></head>
            <body><h1>Motherboard</h1><p>Board revision reference.</p></body></html>""",
            encoding="utf-8",
        )
        archive = OfflineKnowledgeArchive(
            database_path=self.db_path,
            output_dir=self.output_dir,
            cache_dir=self.cache_dir,
        )
        summary = archive.import_saved_pages(saved, "xenonlibrary")
        self.assertEqual(summary["records_imported"], 1)
        self.assertTrue(archive.index_path.exists())
        index = archive.index_path.read_text(encoding="utf-8")
        self.assertIn("Motherboard", index)
        article_path = next((self.output_dir / "pages" / "xenonlibrary").glob("*.html"))
        article = article_path.read_text(encoding="utf-8")
        self.assertIn("Board revision reference.", article)
        self.assertNotIn("tracker.invalid", article)
        self.assertIn("https://xenonlibrary.com/wiki/Motherboard", article)

    def test_saved_consolemods_title_list_enriches_unknown_game(self):
        saved = self.temp_dir / "titleids.html"
        saved.write_text(
            """<html><head><title>List of Every Xbox 360 Title ID</title>
            <link rel="canonical" href="https://consolemods.org/wiki/Xbox_360:List_of_Every_Xbox_360_Title_ID">
            </head><body><h2>SQ (5351) --&gt; Square Enix</h2>
            <h3>SQ-2052 (53510804)</h3><p>Hitman: Absolution</p></body></html>""",
            encoding="utf-8",
        )
        database = DatabaseManager(str(self.db_path))
        database.add_titleid("53510804", "Unknown game", "Unknown Publisher")
        archive = OfflineKnowledgeArchive(
            database_path=self.db_path,
            output_dir=self.output_dir,
            cache_dir=self.cache_dir,
        )
        summary = archive.import_saved_pages(saved, "consolemods-wiki")
        self.assertEqual(summary["titleids_enriched"], 1)
        row = database.get_titleid_info("53510804")
        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(row["name"], "Hitman: Absolution")
        self.assertEqual(row["publisher"], "Square Enix")


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
        profile_id="0000000000000000",
        console_id="0000000000",
        device_id="0000000000000000000000000000000000000000",
        save_game_id="00000000",
    ):
        path = self.temp_dir / name
        header = bytearray(0x1791)
        header[:4] = b"LIVE"
        header[0x344:0x348] = content_type.to_bytes(4, "big")
        header[0x354:0x358] = bytes.fromhex(mediaid)
        header[0x360:0x364] = bytes.fromhex(titleid)
        header[0x366] = 1
        header[0x367] = 1
        header[0x368:0x36C] = bytes.fromhex(save_game_id)
        header[0x36C:0x371] = bytes.fromhex(console_id)
        header[0x371:0x379] = bytes.fromhex(profile_id)
        header[0x3FD:0x411] = bytes.fromhex(device_id)
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

    def test_inspect_stfs_reads_profile_ownership_fields(self):
        package = inspect_stfs(
            self._stfs(
                content_type=0x00000001,
                profile_id="E00015BF00008BD2",
                console_id="0102030405",
                device_id="11" * 20,
                save_game_id="12345678",
            )
        )
        self.assertEqual(package.content_label, "Saved Game")
        self.assertEqual(package.profile_id, "E00015BF00008BD2")
        self.assertEqual(package.console_id, "0102030405")
        self.assertEqual(package.device_id, "11" * 20)
        self.assertEqual(package.save_game_id, "12345678")

    def test_stfs_file_table_is_inventoried_read_only(self):
        payload = bytearray(0xD000)
        payload[:4] = b"LIVE"
        payload[0x340:0x344] = (0xA000).to_bytes(4, "big")
        payload[0x344:0x348] = (1).to_bytes(4, "big")
        payload[0x360:0x364] = bytes.fromhex("53510804")
        payload[0x379] = 0x24
        payload[0x37B] = 1
        payload[0x37C:0x37E] = (1).to_bytes(2, "big")
        name = b"savegame.dat"
        entry = 0xB000
        payload[entry:entry + len(name)] = name
        payload[entry + 0x28] = len(name) | 0x40
        payload[entry + 0x29:entry + 0x2C] = (1).to_bytes(3, "little")
        payload[entry + 0x2F:entry + 0x32] = (1).to_bytes(3, "little")
        payload[entry + 0x32:entry + 0x34] = (0xFFFF).to_bytes(2, "big")
        payload[entry + 0x34:entry + 0x38] = (123).to_bytes(4, "big")
        package_path = self.temp_dir / "listing.stfs"
        package_path.write_bytes(payload)

        entries = list_stfs_entries(package_path)
        self.assertEqual(entries[0].path, "savegame.dat")
        self.assertEqual(entries[0].size, 123)
        self.assertTrue(entries[0].consecutive)

        payload[0x379 + 0x1C:0x379 + 0x20] = (2).to_bytes(4, "big")
        payload[0xC000:0xC004] = b"data"
        package_path.write_bytes(payload)
        destination = self.temp_dir / "extracted"
        result = extract_stfs_files(package_path, destination)
        self.assertEqual((destination / "savegame.dat").read_bytes()[:4], b"data")
        self.assertEqual(result["extracted"][0]["size"], 123)
        self.assertTrue(Path(result["manifest"]).is_file())

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
        data[certificate_offset + 0x9C:certificate_offset + 0xA0] = (0x21).to_bytes(
            4, "little"
        )
        data[certificate_offset + 0xA0:certificate_offset + 0xA4] = (0x5).to_bytes(
            4, "little"
        )
        data[certificate_offset + 0xA8:certificate_offset + 0xAC] = (2).to_bytes(4, "little")
        data[certificate_offset + 0xAC:certificate_offset + 0xB0] = (7).to_bytes(4, "little")
        path.write_bytes(data)
        package = inspect_xbe(path)
        self.assertEqual(package.title_id, "4D530064")
        self.assertEqual(package.title_name, "Original Game")
        self.assertEqual(package.allowed_media, 0x21)
        self.assertEqual(package.region_flags, 0x5)
        self.assertEqual(package.disc_number, 2)
        self.assertEqual(package.version, 7)

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

    def test_scoped_tokens_and_request_limits_are_enforced(self):
        api = UnityScraperAPI(
            self.scraper,
            token_scopes={"reader": ["read"], "writer": ["read", "write"]},
            requests_per_minute=10,
        )
        client = api.app.test_client()
        self.assertEqual(client.get(
            "/api/titleids", headers={"X-API-Key": "reader"}
        ).status_code, 200)
        self.assertEqual(client.post(
            "/api/config", json={"workers": 5}, headers={"X-API-Key": "reader"}
        ).status_code, 403)
        self.assertEqual(client.post(
            "/api/config", json={"workers": 5}, headers={"X-API-Key": "writer"}
        ).status_code, 200)
        limited = UnityScraperAPI(self.scraper, requests_per_minute=10).app.test_client()
        for _ in range(10):
            self.assertEqual(limited.get("/api/health").status_code, 200)
        self.assertEqual(limited.get("/api/health").status_code, 429)

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


class TestProfileSaveManager(unittest.TestCase):
    """Test read-only profile discovery and conflict-safe snapshots."""

    PROFILE_ID = "E00015BF00008BD2"
    TITLE_ID = "53510804"

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.content = self.temp_dir / "device" / "Content"
        self.profile_root = self.content / self.PROFILE_ID
        self.profile_package = (
            self.profile_root / "FFFE07D1" / "00010000" / self.PROFILE_ID
        )
        self.save_path = (
            self.profile_root / self.TITLE_ID / "00000001" / "savegame"
        )
        self._write_stfs(
            self.profile_package,
            titleid="FFFE07D1",
            content_type=0x00010000,
            title="TestPlayer",
        )
        self._write_stfs(
            self.save_path,
            titleid=self.TITLE_ID,
            content_type=0x00000001,
            title="Hitman: Absolution Save",
        )
        self.manager = ProfileSaveManager(
            self.temp_dir / "profiles.db",
            self.temp_dir / "snapshots",
        )

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def _write_stfs(self, path, *, titleid, content_type, title):
        path.parent.mkdir(parents=True, exist_ok=True)
        header = bytearray(0x1791)
        header[:4] = b"CON "
        header[0x344:0x348] = content_type.to_bytes(4, "big")
        header[0x354:0x358] = bytes.fromhex("12345678")
        header[0x360:0x364] = bytes.fromhex(titleid)
        header[0x368:0x36C] = bytes.fromhex("11223344")
        header[0x36C:0x371] = bytes.fromhex("0102030405")
        header[0x371:0x379] = bytes.fromhex(self.PROFILE_ID)
        header[0x3FD:0x411] = bytes.fromhex("22" * 20)
        encoded = title.encode("utf-16-be")
        header[0x411 : 0x411 + len(encoded)] = encoded
        header[0x1691 : 0x1691 + len(encoded)] = encoded
        path.write_bytes(header + b"profile-save-payload")

    def test_content_root_and_masking(self):
        self.assertEqual(
            find_content_root(self.temp_dir / "device"),
            self.content.resolve(),
        )
        masked = mask_identifier(self.PROFILE_ID)
        self.assertTrue(masked.endswith("8BD2"))
        self.assertNotIn(self.PROFILE_ID, masked)

    def test_scan_indexes_profile_and_save_without_modifying_source(self):
        original = self.save_path.read_bytes()
        result = self.manager.scan(self.content)
        profiles = self.manager.list_profiles()
        saves = self.manager.list_saves(self.PROFILE_ID)

        self.assertEqual((len(result.profiles), len(result.saves)), (1, 1))
        self.assertEqual(profiles[0]["gamertag"], "TestPlayer")
        self.assertEqual(profiles[0]["save_count"], 1)
        self.assertEqual(saves[0]["titleid"], self.TITLE_ID)
        self.assertEqual(saves[0]["status"], "header-valid")
        self.assertEqual(self.save_path.read_bytes(), original)

    def test_snapshot_restore_preserves_destination_conflict(self):
        self.manager.scan(self.content)
        save_id = int(self.manager.list_saves(self.PROFILE_ID)[0]["id"])
        snapshot_id = self.manager.create_snapshot(
            self.PROFILE_ID,
            save_ids=[save_id],
            label="Before transfer",
        )
        snapshot = self.manager.list_snapshots()[0]
        self.assertEqual(snapshot["status"], "complete")
        self.assertEqual(snapshot["file_count"], 1)

        destination = self.temp_dir / "restore"
        conflict = destination / self.TITLE_ID / "00000001" / "savegame"
        conflict.parent.mkdir(parents=True)
        conflict.write_bytes(b"keep this copy")

        result = self.manager.restore_snapshot(snapshot_id, destination)
        restored = conflict.with_name("savegame.restored-1")
        self.assertEqual(conflict.read_bytes(), b"keep this copy")
        self.assertEqual(restored.read_bytes(), self.save_path.read_bytes())
        self.assertEqual((result.restored, result.conflicts), (1, 1))

    def test_profile_snapshot_contains_manifest_and_every_profile_file(self):
        self.manager.scan(self.content)
        snapshot_id = self.manager.create_snapshot(self.PROFILE_ID)
        snapshot = self.manager.list_snapshots()[0]
        manifest = Path(snapshot["snapshot_path"]) / "manifest.json"
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        self.assertEqual(snapshot_id, payload["snapshot_id"])
        self.assertEqual(len(payload["files"]), 2)
        self.assertIn("DJ SkunkieButt", payload["attribution"])


class TestRoadmapFeatures(unittest.TestCase):
    """Read-only GPD, Xenia, knowledge, and verification roadmap coverage."""

    PROFILE_ID = "E000012345678BD2"
    TITLE_ID = "53510804"

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.db_path = self.temp_dir / "roadmap.db"
        DatabaseManager(str(self.db_path))

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    @staticmethod
    def _gpd_bytes(unlocked=True):
        import struct

        strings = b"".join(
            value.encode("utf-16-be") + b"\0\0"
            for value in ("First Steps", "Locked text", "Unlocked text")
        )
        payload = bytearray(0x1C)
        payload[:4] = (0x1C).to_bytes(4, "big")
        payload[4:8] = (7).to_bytes(4, "big", signed=True)
        payload[8:12] = (42).to_bytes(4, "big", signed=True)
        payload[12:16] = (25).to_bytes(4, "big")
        payload[16:20] = bytes((0, 0x12 if unlocked else 0, 0, 0))
        entry_payload = bytes(payload) + strings
        header = struct.pack(">4sIIIII", b"XDBF", 1, 1, 1, 0, 0)
        entry = struct.pack(">Hqii", 1, 100, 0, len(entry_payload))
        return header + entry + entry_payload

    def test_gpd_parser_reads_achievement_without_modifying_file(self):
        from gpd_parser import parse_gpd

        path = self.temp_dir / f"{self.TITLE_ID}.gpd"
        original = self._gpd_bytes()
        path.write_bytes(original)
        report = parse_gpd(path)

        self.assertEqual(report.title_id, self.TITLE_ID)
        self.assertEqual(report.unlocked_count, 1)
        self.assertEqual(report.gamerscore_earned, 25)
        self.assertEqual(report.achievements[0].title, "First Steps")
        self.assertEqual(path.read_bytes(), original)

    def test_profile_intelligence_imports_and_compares_achievements(self):
        from profile_intelligence import ProfileIntelligenceService

        left = self.temp_dir / f"{self.TITLE_ID}.gpd"
        right = self.temp_dir / "right" / f"{self.TITLE_ID}.gpd"
        right.parent.mkdir()
        left.write_bytes(self._gpd_bytes(unlocked=True))
        right.write_bytes(self._gpd_bytes(unlocked=False))
        service = ProfileIntelligenceService(self.db_path)
        left_id = service.import_gpd(left, profile_id=self.PROFILE_ID)
        service.import_gpd(right, profile_id="E000000000000002")

        self.assertEqual(len(service.list_achievements(left_id)), 1)
        comparison = service.compare_profiles(
            self.PROFILE_ID, "E000000000000002"
        )
        self.assertEqual(len(comparison["achievements_only_left"]), 1)
        self.assertEqual(len(comparison["achievements_only_right"]), 0)

    def test_xenia_plan_copies_then_skips_identical_save(self):
        from xenia_bridge import build_migration_plan, execute_migration_plan

        source = (
            self.temp_dir
            / self.PROFILE_ID
            / self.TITLE_ID
            / "00000001"
            / "save.bin"
        )
        source.parent.mkdir(parents=True)
        source.write_bytes(b"user-owned-save")
        destination = self.temp_dir / "xenia" / "content"
        plan = build_migration_plan(
            [(source, self.TITLE_ID)],
            destination,
            source_profile_id=self.PROFILE_ID,
            target_profile_id=self.PROFILE_ID,
        )
        self.assertEqual(plan.copy_count, 1)
        self.assertEqual(execute_migration_plan(plan), (1, 0, 0))
        second = build_migration_plan(
            [(source, self.TITLE_ID)],
            destination,
            source_profile_id=self.PROFILE_ID,
            target_profile_id=self.PROFILE_ID,
        )
        self.assertEqual(second.items[0].action, "skip")

    @patch("xenia_bridge.subprocess.Popen")
    def test_xenia_installation_is_discovered_and_launched_without_a_shell(self, popen):
        from xenia_bridge import find_xenia_installation, launch_xenia

        root = self.temp_dir / "xenia"
        root.mkdir()
        executable = root / ("xenia.exe" if os.name == "nt" else "xenia")
        executable.write_bytes(b"binary")
        game = root / "game.iso"
        game.write_bytes(b"image")
        installation = find_xenia_installation(root)
        self.assertIsNotNone(installation)
        popen.return_value.pid = 42
        result = launch_xenia(installation, game, fullscreen=True)
        self.assertEqual(result["pid"], 42)
        popen.assert_called_once_with(
            [
                str(installation.executable),
                str(game.resolve()),
                "--fullscreen=true",
            ],
            cwd=installation.root,
        )

    def test_knowledge_priority_and_conflict_resolution_are_persistent(self):
        import sqlite3
        from contextlib import closing

        from knowledge_base import KnowledgeRepository

        service = KnowledgeService(self.db_path)
        sources = service.list_sources()
        source = sources[0]
        other_source = sources[1]
        service.set_source_priority(int(source["id"]), "publisher", 10)
        service.set_source_priority(int(other_source["id"]), "publisher", 20)
        priority = [
            row
            for row in service.list_priorities()
            if row.get("property") == "publisher"
        ][0]
        self.assertEqual(priority["priority"], 10)
        with closing(sqlite3.connect(self.db_path)) as connection:
            connection.row_factory = sqlite3.Row
            entity = connection.execute(
                """
                INSERT INTO knowledge_entities(
                    entity_type, canonical_name, normalized_name
                ) VALUES ('game', 'Example', 'example')
                """
            )
            entity_id = int(entity.lastrowid)
            conflict = connection.execute(
                """
                INSERT INTO knowledge_conflicts(
                    entity_id, property, existing_value, incoming_value,
                    existing_source_id, incoming_source_id, detected_at
                ) VALUES (?, 'publisher', 'A', 'B', ?, ?, 'now')
                """,
                (entity_id, source["id"], other_source["id"]),
            )
            connection.executemany(
                """
                INSERT INTO knowledge_facts(
                    entity_id, property, value, normalized_value,
                    source_id, confidence, imported_at
                ) VALUES (?, 'publisher', ?, ?, ?, ?, 'now')
                """,
                (
                    (entity_id, "A", "a", source["id"], 0.70),
                    (entity_id, "B", "b", other_source["id"], 0.99),
                ),
            )
            connection.commit()
            conflict_id = int(conflict.lastrowid)
            preferred = KnowledgeRepository(connection).get_preferred_facts(
                entity_id, ("publisher",)
            )
            self.assertEqual(preferred["publisher"]["value"], "A")
        result = service.resolve_conflict(conflict_id, "prefer_incoming")
        self.assertEqual(result["preferred_value"], "B")
        self.assertEqual(service.list_conflicts(), [])
        with closing(sqlite3.connect(self.db_path)) as connection:
            connection.row_factory = sqlite3.Row
            preferred = KnowledgeRepository(connection).get_preferred_facts(
                entity_id, ("publisher",)
            )
        self.assertEqual(preferred["publisher"]["value"], "B")

    def test_scheduler_runs_only_when_enabled_and_due(self):
        from knowledge_scheduler import KnowledgeScheduler

        scheduler = KnowledgeScheduler(self.db_path)
        self.assertIsNone(scheduler.run_if_due(lambda: "unused"))
        scheduler.configure(True, 24)
        calls = []
        result = scheduler.run_if_due(lambda: calls.append("run") or "done")
        self.assertEqual(calls, ["run"])
        self.assertEqual(result["result"], "done")
        self.assertIsNone(scheduler.run_if_due(lambda: calls.append("again")))

    def test_remote_sha256_detects_supported_read_only_command(self):
        from console_sync import _remote_sha256

        ftp = Mock()
        ftp.sendcmd.return_value = "213 " + ("AB" * 32)
        self.assertEqual(_remote_sha256(ftp, "/Hdd1/save"), ("ab" * 32))


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
        self.assertEqual(
            [row[0] for row in versions],
            [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11],
        )
        self.assertIn("collection_snapshots", tables)
        self.assertIn("preservation_matches", tables)
        self.assertIn("console_transfer_jobs", tables)
        self.assertIn("metadata_overrides", tables)
        self.assertIn("xboxunity_title_catalog", tables)
        self.assertIn("xbox_profiles", tables)
        self.assertIn("profile_saves", tables)
        self.assertIn("save_snapshots", tables)
        self.assertIn("profile_save_operations", tables)
        self.assertIn("profile_gpd_files", tables)
        self.assertIn("profile_achievements", tables)
        self.assertIn("xenia_migration_runs", tables)
        self.assertIn("knowledge_source_priorities", tables)
        self.assertIn("scheduled_sync_state", tables)
        self.assertIn("plugin_collection_runs", tables)
        self.assertIn("dedup_recovery_records", tables)
        self.assertIn("metadata_snapshot_runs", tables)
        self.assertIn("library_intelligence_runs", tables)
        self.assertIn("preservation_report_runs", tables)
        self.assertIn("hardware_inventory_records", tables)
        self.assertIn("offline_archive_runs", tables)
        self.assertIn("offline_archive_documents", tables)
        self.assertIn("offline_page_import_runs", tables)

    def test_release_readiness_toolkit_exports_portable_nonpersonal_metadata(self):
        import sqlite3
        from contextlib import closing

        from knowledge_base import EntityRecord, Fact, Identifier, KnowledgeRepository
        from roadmap_services import (
            CorrectionPackageService,
            HardwareInventoryService,
            LibraryIntelligenceService,
            MetadataSnapshotService,
            PreservationReportService,
        )

        self.database.add_titleid("53510804", "Hitman: Absolution", "Unknown")
        with closing(sqlite3.connect(self.db_path)) as connection:
            repository = KnowledgeRepository(connection)
            source_id = repository.upsert_source(
                "test-source", "Test Source", license_name="CC0"
            )
            repository.upsert_entity_record(EntityRecord(
                "game", "Hitman: Absolution",
                identifiers=(Identifier("titleid", "53510804"),),
                facts=(Fact("publisher", "Square Enix"),),
            ), source_id)
            connection.execute(
                """INSERT INTO xboxunity_title_catalog(
                       titleid,name,link_enabled,covers_count,updates_count,media_id_count,
                       user_count,source_url,raw_json,fetched_at)
                   VALUES ('53510804','Hitman: Absolution',1,2,3,1,1,
                           'http://xboxunity.net','{}','now')"""
            )
            connection.execute(
                """INSERT INTO metadata_overrides(
                       entity_type,identifier_type,identifier_value,property,value,notes,updated_at)
                   VALUES ('game','titleid','53510804','publisher','Square Enix','reviewed','now')"""
            )
            connection.commit()

        audit = LibraryIntelligenceService(self.db_path).audit()
        self.assertEqual(audit["summary"]["titles"], 1)
        self.assertTrue(any(row["kind"] == "missing-cover" for row in audit["issues"]))
        report = PreservationReportService(self.db_path).export_html(
            Path(self.temp_dir) / "report.html"
        )
        self.assertTrue(Path(report["path"]).is_file())
        corrections = CorrectionPackageService(self.db_path).export(
            Path(self.temp_dir) / "corrections.json"
        )
        self.assertEqual(corrections["corrections"], 1)
        hardware = HardwareInventoryService(self.db_path)
        hardware.save("Living room", motherboard="Trinity", dvd_drive="DG-16D4S")
        self.assertEqual(hardware.list()[0]["motherboard"], "Trinity")

        snapshot_path = Path(self.temp_dir) / "metadata.usmeta"
        exported = MetadataSnapshotService(self.db_path).export(snapshot_path)
        self.assertEqual(exported["catalog"], 1)
        imported_db = Path(self.temp_dir) / "imported.db"
        DatabaseManager(str(imported_db))
        imported = MetadataSnapshotService(imported_db).import_snapshot(snapshot_path)
        self.assertEqual(imported["catalog"], 1)
        self.assertEqual(imported["facts"], 1)

        api_scraper = Mock(db=Mock(db_path=self.db_path))
        api_client = UnityScraperAPI(api_scraper).app.test_client()
        self.assertEqual(api_client.get("/api/library/audit").status_code, 200)
        self.assertEqual(api_client.post("/api/hardware", json={
            "label": "Bench console", "motherboard": "Jasper"
        }).status_code, 200)
        api_report = Path(self.temp_dir) / "api-report.html"
        self.assertEqual(api_client.post("/api/reports/preservation", json={
            "destination": str(api_report)
        }).status_code, 200)
        self.assertTrue(api_report.is_file())

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


class TestCommunityRoadmap(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.db_path = self.temp_dir / "community.db"
        self.database = DatabaseManager(str(self.db_path))

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def test_unified_search_spans_games_profiles_and_achievements(self):
        import sqlite3
        from contextlib import closing
        from unified_search import UnifiedSearchService

        self.database.add_titleid("53510804", "Hitman: Absolution", "Square Enix")
        with closing(sqlite3.connect(self.db_path)) as connection:
            connection.execute(
                """INSERT INTO xbox_profiles(profile_id, gamertag, source_path,
                   profile_kind, package_status, first_seen_at, last_seen_at)
                   VALUES ('E000000000000001', 'Agent47', 'profile', 'retail',
                   'header-valid', 'now', 'now')"""
            )
            connection.commit()
        service = UnifiedSearchService(self.db_path)
        self.assertEqual(service.search("Hitman")[0]["identifier"], "53510804")
        self.assertEqual(service.search("Agent47")[0]["category"], "profile")

        api_scraper = Mock(db=self.database)
        response = UnityScraperAPI(api_scraper).app.test_client().get(
            "/api/community/search?q=Hitman"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["results"][0]["identifier"], "53510804")

    def test_structured_knowledge_extracts_cached_hardware_article(self):
        import sqlite3
        from contextlib import closing
        from structured_knowledge import StructuredKnowledgeService

        cache = self.temp_dir / "jasper.html"
        cache.write_text(
            "<html><h1>Jasper Motherboard</h1><table>"
            "<tr><th>CPU</th><td>65 nm</td></tr>"
            "<tr><th>NAND</th><td>16 MB</td></tr></table></html>",
            encoding="utf-8",
        )
        with closing(sqlite3.connect(self.db_path)) as connection:
            source = connection.execute(
                """INSERT INTO knowledge_sources(slug, name)
                   VALUES ('test-source', 'Test Source')"""
            )
            source_id = source.lastrowid
            connection.execute(
                """INSERT INTO source_documents(source_id, url, title, cache_path)
                   VALUES (?, 'https://example.test/jasper', 'Jasper Motherboard', ?)""",
                (source_id, str(cache)),
            )
            connection.commit()
        service = StructuredKnowledgeService(self.db_path)
        self.assertEqual(service.extract_cached_documents()["extracted"], 1)
        record = service.list_records()[0]
        self.assertEqual(record["record_type"], "motherboard")
        self.assertEqual(record["properties"]["cpu"], "65 nm")

    def test_gpd_title_history_and_safe_image_metadata(self):
        import struct
        from gpd_parser import parse_gpd_bytes

        title = bytearray(0x28)
        struct.pack_into(">IIIII", title, 0, 0x53510804, 50, 25, 1000, 500)
        title.extend("Hitman: Absolution".encode("utf-16-be") + b"\0\0")
        image = b"\x89PNG\r\n\x1a\n" + b"image payload"
        header = struct.pack(">4sIIIII", b"XDBF", 1, 2, 2, 0, 0)
        entries = (
            struct.pack(">Hqii", 4, 0x53510804, 0, len(title))
            + struct.pack(">Hqii", 2, 42, len(title), len(image))
        )
        report = parse_gpd_bytes(header + entries + title + image)
        self.assertEqual(report.titles[0].title_id, "53510804")
        self.assertEqual(report.titles[0].gamerscore_earned, 500)
        self.assertEqual(report.images[0].image_format, "png")

    def test_console_sync_plan_can_queue_revalidated_uploads(self):
        import sqlite3
        from contextlib import closing
        from community_services import ConsolePlanService

        local = self.temp_dir / "content"
        game = local / "53510804" / "00000001" / "save.bin"
        game.parent.mkdir(parents=True)
        game.write_bytes(b"new save")
        with closing(sqlite3.connect(self.db_path)) as connection:
            snapshot = connection.execute(
                """INSERT INTO console_inventory_snapshots(root, captured_at, status)
                   VALUES ('/Hdd1/Content/0000000000000000', 'now', 'completed')"""
            )
            connection.execute(
                """INSERT INTO console_inventory_items(snapshot_id, remote_path, size)
                   VALUES (?, '/Hdd1/Content/0000000000000000/old.bin', 3)""",
                (snapshot.lastrowid,),
            )
            connection.commit()
            snapshot_id = snapshot.lastrowid
        service = ConsolePlanService(self.db_path)
        self.assertEqual(service.list_snapshots()[0]["id"], snapshot_id)
        plan = service.create_plan(local, snapshot_id)
        self.assertEqual(plan["summary"]["uploads"], 1)
        self.assertTrue(any(item["action"] == "review_remote" for item in plan["actions"]))
        queued = service.queue_uploads(plan["plan_id"])
        self.assertEqual(len(queued["queued_job_ids"]), 1)
        with closing(sqlite3.connect(self.db_path)) as connection:
            status = connection.execute(
                "SELECT status FROM console_transfer_jobs WHERE id=?",
                (queued["queued_job_ids"][0],),
            ).fetchone()[0]
        self.assertEqual(status, "queued")

    def test_artwork_disc_dedup_and_storage_plans(self):
        import sqlite3
        from PIL import Image
        from community_services import ArtworkService, PreservationPlanningService, StorageAndXboxService

        artwork = self.temp_dir / "cover.png"
        Image.new("RGB", (64, 96), "green").save(artwork)
        art = ArtworkService(self.db_path)
        art.set_preference("53510804", artwork)
        exported = art.export(self.temp_dir / "art-export")
        self.assertEqual(exported["exported"], 1)

        duplicates = self.temp_dir / "duplicates"
        duplicates.mkdir()
        (duplicates / "a.bin").write_bytes(b"same")
        (duplicates / "b.bin").write_bytes(b"same")
        plan = PreservationPlanningService(self.db_path).create_dedup_plan(duplicates)
        self.assertEqual(plan["groups"], 1)
        self.assertEqual((duplicates / "a.bin").read_bytes(), b"same")
        from contextlib import closing
        with closing(sqlite3.connect(self.db_path)) as connection:
            action_id = connection.execute(
                "SELECT id FROM dedup_actions WHERE plan_id=?", (plan["plan_id"],)
            ).fetchone()[0]
        applied = PreservationPlanningService(self.db_path).apply_dedup_action(action_id)
        self.assertTrue(Path(applied["quarantine"]).is_file())
        self.assertFalse(Path(applied["duplicate"]).exists())
        restored = PreservationPlanningService(self.db_path).restore_dedup_action(action_id)
        self.assertEqual(Path(restored["restored"]).read_bytes(), b"same")
        self.assertFalse(Path(applied["quarantine"]).exists())

        fatx = self.temp_dir / "drive.img"
        fatx.write_bytes(
            b"XTAF" + bytes.fromhex("12345678")
            + (8).to_bytes(4, "big") + (1).to_bytes(4, "big") + bytes(52)
        )
        audit = StorageAndXboxService(self.db_path).audit_storage(fatx)
        self.assertEqual(audit["filesystem"], "FATX")
        self.assertEqual(audit["access_mode"], "read-only")
        self.assertEqual(audit["details"]["partitions"][0]["cluster_size"], 4096)
        self.assertTrue(audit["details"]["partitions"][0]["header_valid"])

    def test_plugin_recovery_and_accessibility_controls(self):
        from community_services import AccessibilityService, PluginControlService, RecoveryService

        plugin = self.temp_dir / "plugins" / "sample"
        plugin.mkdir(parents=True)
        (plugin / "plugin.py").write_text("value = 1\n", encoding="utf-8")
        (plugin / "plugin.json").write_text(json.dumps({
            "id": "sample", "name": "Sample", "version": "1.0",
            "api_version": 1, "entrypoint": "plugin.py", "permissions": ["metadata"],
        }), encoding="utf-8")
        control = PluginControlService(self.db_path)
        discovered = control.discover(plugin.parent)
        self.assertEqual(discovered[0]["id"], "sample")
        control.set_state("sample", True, plugin / "plugin.py", ["metadata"])
        self.assertTrue(control.discover(plugin.parent)[0]["trusted"])

        partial = self.temp_dir / "download.partial"
        partial.write_bytes(b"partial")
        events = RecoveryService(self.db_path).scan([self.temp_dir])
        partial_event = next(item for item in events if item["event_type"] == "partial_file")
        recovered = RecoveryService(self.db_path).recover(partial_event["id"])
        self.assertIn("quarantined", recovered["action"])
        self.assertFalse(partial.exists())

        access = AccessibilityService(self.db_path)
        access.set("large_text", True)
        access.set("high_contrast", True)
        access.set("reduced_motion", True)
        self.assertTrue(access.get()["large_text"])
        self.assertTrue(access.get()["high_contrast"])
        self.assertTrue(access.get()["reduced_motion"])

    def test_enabled_plugin_requires_approved_checksum_and_enriches_unknowns(self):
        from community_services import PluginControlService
        from plugins import PluginManager, load_enabled_plugin_configuration

        plugin = self.temp_dir / "plugins" / "catalog"
        plugin.mkdir(parents=True)
        entry = plugin / "collector.py"
        entry.write_text(
            "from plugins import MetadataCollectorPlugin\n"
            "class Catalog(MetadataCollectorPlugin):\n"
            "    def validate_titleid(self, titleid): return True\n"
            "    def collect(self, titleid):\n"
            "        return {'title': 'Fallback Name', 'publisher': 'Fallback Publisher'}\n",
            encoding="utf-8",
        )
        (plugin / "plugin.json").write_text(json.dumps({
            "id": "catalog", "name": "Catalog", "version": "1.0",
            "api_version": 1, "entrypoint": "collector.py", "permissions": ["metadata"],
        }), encoding="utf-8")
        PluginControlService(self.db_path).set_state("catalog", True, entry, ["metadata"])
        enabled, trusted = load_enabled_plugin_configuration(self.db_path, plugin.parent)
        manager = PluginManager(str(plugin.parent), enabled_plugins=enabled,
                                trusted_hashes=trusted)
        self.assertEqual(manager.collect_enabled("53510804")[0]["status"], "completed")

        self.database.add_titleid("53510804", "Hitman: Absolution", "Unknown")
        scraper = UnityScraper.__new__(UnityScraper)
        scraper.db = self.database
        scraper.plugin_manager = manager
        scraper._collect_plugin_metadata("53510804")
        title = self.database.get_titleid_info("53510804")
        self.assertEqual(title["name"], "Hitman: Absolution")
        self.assertEqual(title["publisher"], "Fallback Publisher")

        entry.write_text(entry.read_text(encoding="utf-8") + "# changed\n", encoding="utf-8")
        enabled, trusted = load_enabled_plugin_configuration(self.db_path, plugin.parent)
        self.assertEqual((enabled, trusted), ([], {}))

    def test_package_workspace_is_read_only_and_profile_tools_are_audited(self):
        from community_services import PackageWorkspaceService
        from profile_intelligence import ProfileIntelligenceService

        package = self.temp_dir / "save.bin"
        header = bytearray(0x1791)
        header[:4] = b"CON "
        header[0x344:0x348] = (1).to_bytes(4, "big")
        header[0x354:0x358] = bytes.fromhex("12345678")
        header[0x360:0x364] = bytes.fromhex("53510804")
        header[0x371:0x379] = bytes.fromhex("E000000000000001")
        header[0x3FD:0x411] = bytes.fromhex("11" * 20)
        title = "Hitman: Absolution".encode("utf-16-be")
        header[0x411:0x411 + len(title)] = title
        header[0x1691:0x1691 + len(title)] = title
        package.write_bytes(header + b"payload")

        service = PackageWorkspaceService(self.db_path)
        details = service.inspect(package)
        self.assertFalse(details["mutation_ready"])
        manifest = service.create_workspace(package, self.temp_dir / "workspace")
        self.assertTrue(manifest.is_file())
        self.assertTrue(json.loads(manifest.read_text(encoding="utf-8"))["read_only"])

        intelligence = ProfileIntelligenceService(self.db_path)
        preview = intelligence.preview_ownership_migration(
            "E000000000000001", package, target_profile_id="E000000000000002"
        )
        self.assertGreater(preview["preview_id"], 0)
        self.assertIn("Preview only", preview["warnings"][0])
        other = self.temp_dir / "other.bin"
        other.write_bytes(package.read_bytes()[:-1] + b"x")
        comparison = intelligence.compare_save_files(package, other)
        self.assertFalse(comparison["identical"])


def run_tests():
    """Run all tests"""
    # Create test suite
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # Add all test classes
    suite.addTests(loader.loadTestsFromTestCase(TestPlatformSupport))
    suite.addTests(loader.loadTestsFromTestCase(TestModularFoundation))
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
    suite.addTests(loader.loadTestsFromTestCase(TestProfileSaveManager))
    suite.addTests(loader.loadTestsFromTestCase(TestRoadmapFeatures))
    suite.addTests(loader.loadTestsFromTestCase(TestUnifiedV1Foundation))
    suite.addTests(loader.loadTestsFromTestCase(TestCommunityRoadmap))
    
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
