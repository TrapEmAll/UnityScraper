"""Optional REST API for local UnityScraper automation."""

from __future__ import annotations

import logging
import json
import os
import secrets
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Optional

from flask import Flask, jsonify, request
from flask_cors import CORS

from app_paths import DATABASE_PATH, EXPORTS_DIR, PLUGINS_DIR
from app_version import DISPLAY_VERSION

if TYPE_CHECKING:
    from main import UnityScraper

logger = logging.getLogger(__name__)

LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
DEFAULT_CORS_ORIGINS = (
    "http://127.0.0.1:*",
    "http://localhost:*",
)


class UnityScraperAPI:
    """REST wrapper with local defaults and opt-in remote authentication."""

    CONFIG_RULES: dict[str, tuple[type, float | None, float | None]] = {
        "workers": (int, 1, 32),
        "rate_limit": (float, 0.05, 60),
        "timeout": (int, 1, 600),
        "max_retries": (int, 0, 20),
        "retry_backoff": (float, 0, 120),
        "bandwidth_limit": (int, 0, None),
        "verify_checksums": (bool, None, None),
        "dry_run": (bool, None, None),
        "refresh_interval_days": (int, 0, 3650),
    }

    def __init__(
        self,
        scraper: Optional["UnityScraper"] = None,
        port: int = 8000,
        host: str = "127.0.0.1",
        token: Optional[str] = None,
        token_scopes: Optional[dict[str, list[str]]] = None,
        cors_origins: Optional[list[str]] = None,
        requests_per_minute: int = 120,
    ):
        self.scraper = scraper
        self.port = port
        self.host = host
        self.token = token or os.environ.get("UNITYSCRAPER_API_TOKEN", "").strip()
        self.tokens: dict[str, frozenset[str]] = {
            key: frozenset(values) for key, values in (token_scopes or {}).items() if key
        }
        if self.token:
            self.tokens[self.token] = frozenset({"*"})
        raw_tokens = os.environ.get("UNITYSCRAPER_API_TOKENS", "").strip()
        if raw_tokens:
            try:
                configured = json.loads(raw_tokens)
                if isinstance(configured, dict):
                    for key, values in configured.items():
                        if isinstance(key, str) and key and isinstance(values, list):
                            self.tokens[key] = frozenset(str(value) for value in values)
            except json.JSONDecodeError:
                logger.warning("UNITYSCRAPER_API_TOKENS is not valid JSON")
        if host not in LOOPBACK_HOSTS and not self.tokens:
            raise ValueError(
                "A token is required when the API is bound beyond localhost"
            )
        self.requests_per_minute = max(10, min(int(requests_per_minute), 10_000))
        self._request_windows: dict[str, deque[float]] = defaultdict(deque)
        self._security_lock = threading.Lock()

        self.app = Flask(__name__)
        self.app.config["MAX_CONTENT_LENGTH"] = 64 * 1024
        CORS(
            self.app,
            resources={
                r"/api/*": {
                    "origins": cors_origins or list(DEFAULT_CORS_ORIGINS)
                }
            },
        )
        self.running = False
        self._register_security()
        self._register_routes()

    def _register_security(self) -> None:
        @self.app.before_request
        def require_token():
            client = request.remote_addr or "unknown"
            now = time.monotonic()
            with self._security_lock:
                window = self._request_windows[client]
                while window and now - window[0] >= 60:
                    window.popleft()
                if len(window) >= self.requests_per_minute:
                    return jsonify({"error": "Request limit exceeded"}), 429
                window.append(now)
            if not self.tokens or request.path == "/api/health":
                return None
            supplied = request.headers.get("X-API-Key", "")
            authorization = request.headers.get("Authorization", "")
            if authorization.startswith("Bearer "):
                supplied = authorization[7:]
            matched_scopes: frozenset[str] | None = None
            for configured_token, scopes in self.tokens.items():
                if secrets.compare_digest(supplied, configured_token):
                    matched_scopes = scopes
                    break
            if matched_scopes is None:
                return jsonify({"error": "Authentication required"}), 401
            required = self._required_scope(request.method, request.path)
            if "*" not in matched_scopes and required not in matched_scopes:
                return jsonify({"error": f"Token lacks the {required} scope"}), 403
            return None

        @self.app.after_request
        def security_headers(response):
            response.headers["Cache-Control"] = "no-store"
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["X-Frame-Options"] = "DENY"
            return response

    def _register_routes(self) -> None:
        @self.app.get("/api/health")
        def health():
            return jsonify(
                {
                    "status": "healthy",
                    "version": DISPLAY_VERSION,
                    "scraper_loaded": self.scraper is not None,
                    "authentication_required": bool(self.tokens),
                    "rate_limit_per_minute": self.requests_per_minute,
                }
            )

        @self.app.get("/api/titleids")
        def get_titleids():
            return self._execute(
                lambda: {"titleids": self._require_scraper().db.search_titleids("")}
            )

        @self.app.get("/api/titleid/<titleid>")
        def get_titleid_info(titleid: str):
            normalized = self._titleid_or_error(titleid)
            if not isinstance(normalized, str):
                return normalized
            try:
                info = self._require_scraper().db.get_titleid_info(normalized)
                if info is None:
                    return jsonify({"error": "TitleID not found"}), 404
                return jsonify(info)
            except Exception as exc:
                return self._server_error(exc)

        @self.app.get("/api/search")
        def search():
            query = request.args.get("q", "")[:200]
            return self._execute(
                lambda: self._search_response(
                    self._require_scraper().db.search_titleids(query)
                )
            )

        @self.app.get("/api/community/search")
        def community_search():
            from unified_search import UnifiedSearchService

            query = request.args.get("q", "")[:200]
            categories = tuple(
                value.strip() for value in request.args.getlist("category") if value.strip()
            )
            limit = request.args.get("limit", default=100, type=int)
            if len(query.strip()) < 2:
                return jsonify({"error": "q must contain at least two characters"}), 400
            if limit is None or limit < 1 or limit > 500:
                return jsonify({"error": "limit must be between 1 and 500"}), 400
            return self._execute(lambda: self._search_response(
                UnifiedSearchService(self._database_path()).search(
                    query, categories=categories, limit=limit
                )
            ))

        @self.app.get("/api/preservation/dedup/actions")
        def dedup_actions():
            from community_services import PreservationPlanningService

            plan_id = request.args.get("plan_id", type=int)
            return self._execute(lambda: {
                "actions": PreservationPlanningService(self._database_path()).list_dedup_actions(
                    plan_id
                )
            })

        @self.app.post("/api/preservation/dedup/preview")
        def dedup_preview():
            from community_services import PreservationPlanningService

            payload = request.get_json(silent=True)
            if not isinstance(payload, dict) or not isinstance(payload.get("root"), str):
                return jsonify({"error": "A root directory is required"}), 400
            return self._execute(
                lambda: PreservationPlanningService(self._database_path()).create_dedup_plan(
                    payload["root"]
                )
            )

        @self.app.post("/api/preservation/dedup/<int:action_id>/apply")
        def dedup_apply(action_id: int):
            from community_services import PreservationPlanningService

            payload = request.get_json(silent=True) or {}
            mode = payload.get("mode", "quarantine") if isinstance(payload, dict) else ""
            if mode not in {"quarantine", "hardlink"}:
                return jsonify({"error": "mode must be quarantine or hardlink"}), 400
            return self._execute(
                lambda: PreservationPlanningService(self._database_path()).apply_dedup_action(
                    action_id, mode
                )
            )

        @self.app.post("/api/preservation/dedup/<int:action_id>/restore")
        def dedup_restore(action_id: int):
            from community_services import PreservationPlanningService

            return self._execute(
                lambda: PreservationPlanningService(self._database_path()).restore_dedup_action(
                    action_id
                )
            )

        @self.app.get("/api/plugins")
        def plugins():
            from community_services import PluginControlService

            return self._execute(lambda: {
                "plugins": PluginControlService(self._database_path()).discover(PLUGINS_DIR)
            })

        @self.app.get("/api/library/audit")
        def library_audit():
            from roadmap_services import LibraryIntelligenceService

            return self._execute(
                lambda: LibraryIntelligenceService(self._database_path()).audit()
            )

        @self.app.post("/api/metadata-snapshots/export")
        def metadata_snapshot_export():
            from roadmap_services import MetadataSnapshotService

            payload = request.get_json(silent=True)
            if not isinstance(payload, dict) or not isinstance(payload.get("destination"), str):
                return jsonify({"error": "A destination path is required"}), 400
            return self._execute(
                lambda: MetadataSnapshotService(self._database_path()).export(
                    payload["destination"]
                )
            )

        @self.app.post("/api/metadata-snapshots/import")
        def metadata_snapshot_import():
            from roadmap_services import MetadataSnapshotService

            payload = request.get_json(silent=True)
            if not isinstance(payload, dict) or not isinstance(payload.get("source"), str):
                return jsonify({"error": "A source path is required"}), 400
            return self._execute(
                lambda: MetadataSnapshotService(self._database_path()).import_snapshot(
                    payload["source"]
                )
            )

        @self.app.post("/api/packages/extract")
        def package_extract():
            from community_services import PackageWorkspaceService

            payload = request.get_json(silent=True)
            if not isinstance(payload, dict):
                return jsonify({"error": "A JSON object is required"}), 400
            source = payload.get("source")
            destination = payload.get("destination")
            selected = payload.get("selected_paths")
            if not isinstance(source, str) or not isinstance(destination, str):
                return jsonify({"error": "source and destination paths are required"}), 400
            if selected is not None and (
                not isinstance(selected, list) or not all(isinstance(item, str) for item in selected)
            ):
                return jsonify({"error": "selected_paths must be a string array"}), 400
            return self._execute(
                lambda: PackageWorkspaceService(self._database_path()).extract_read_only(
                    source, destination, selected
                )
            )

        @self.app.post("/api/reports/preservation")
        def preservation_report():
            from roadmap_services import PreservationReportService

            payload = request.get_json(silent=True)
            if not isinstance(payload, dict) or not isinstance(payload.get("destination"), str):
                return jsonify({"error": "A destination path is required"}), 400
            return self._execute(
                lambda: PreservationReportService(self._database_path()).export_html(
                    payload["destination"]
                )
            )

        @self.app.get("/api/hardware")
        def hardware_list():
            from roadmap_services import HardwareInventoryService

            return self._execute(
                lambda: {"records": HardwareInventoryService(self._database_path()).list()}
            )

        @self.app.post("/api/hardware")
        def hardware_save():
            from roadmap_services import HardwareInventoryService

            payload = request.get_json(silent=True)
            if not isinstance(payload, dict) or not isinstance(payload.get("label"), str):
                return jsonify({"error": "A record label is required"}), 400
            values = {key: value for key, value in payload.items() if key != "label"}
            if not all(isinstance(value, str) for value in values.values()):
                return jsonify({"error": "Hardware fields must be strings"}), 400
            return self._execute(
                lambda: HardwareInventoryService(self._database_path()).save(
                    payload["label"], **values
                )
            )

        @self.app.post("/api/metadata/<titleid>")
        def collect_metadata(titleid: str):
            normalized = self._titleid_or_error(titleid)
            if not isinstance(normalized, str):
                return normalized
            return self._execute(
                lambda: self._operation_response(
                    self._require_scraper().collect_metadata(normalized),
                    normalized,
                    "Metadata collected",
                    "Metadata collection failed",
                )
            )

        @self.app.post("/api/download/<titleid>")
        def download_titleid(titleid: str):
            normalized = self._titleid_or_error(titleid)
            if not isinstance(normalized, str):
                return normalized
            return self._execute(
                lambda: self._operation_response(
                    self._require_scraper().process_titleid(normalized),
                    normalized,
                    "Download completed",
                    "Download failed",
                )
            )

        @self.app.get("/api/statistics")
        def statistics():
            return self._execute(
                lambda: self._require_scraper().db.get_statistics()
            )

        @self.app.get("/api/failed-items")
        def failed_items():
            titleid = request.args.get("titleid")
            if titleid:
                normalized = self._titleid_or_error(titleid)
                if not isinstance(normalized, str):
                    return normalized
                titleid = normalized
            return self._execute(
                lambda: self._failed_response(
                    self._require_scraper().db.get_failed_items(titleid)
                )
            )

        @self.app.post("/api/retry-failed")
        def retry_failed():
            titleid = request.args.get("titleid")
            if titleid:
                normalized = self._titleid_or_error(titleid)
                if not isinstance(normalized, str):
                    return normalized
                titleid = normalized

            def retry() -> dict:
                self._require_scraper().retry_failed_downloads(titleid)
                return {"success": True, "message": "Retry process completed"}

            return self._execute(retry)

        @self.app.get("/api/verify-integrity")
        def verify_integrity():
            titleid = request.args.get("titleid")
            if titleid:
                normalized = self._titleid_or_error(titleid)
                if not isinstance(normalized, str):
                    return normalized
                titleid = normalized
            return self._execute(
                lambda: self._require_scraper().db.verify_file_integrity(titleid)
            )

        @self.app.get("/api/export")
        def export():
            export_format = request.args.get("format", "json").lower()
            if export_format not in {"json", "csv"}:
                return jsonify({"error": "format must be json or csv"}), 400
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            output = EXPORTS_DIR / f"unityscraper-{timestamp}.{export_format}"

            def perform_export() -> dict:
                self._require_scraper().export_database(
                    export_format, str(output)
                )
                return {
                    "success": True,
                    "filename": output.name,
                    "path": str(output),
                }

            return self._execute(perform_export)

        @self.app.get("/api/config")
        def get_config():
            def configuration() -> dict:
                config = self._require_scraper().config
                return {
                    key: getattr(config, key)
                    for key in self.CONFIG_RULES
                } | {
                    "base_url": "http://xboxunity.net",
                    "use_https": False,
                }

            return self._execute(configuration)

        @self.app.post("/api/config")
        def update_config():
            payload = request.get_json(silent=True)
            if not isinstance(payload, dict):
                return jsonify({"error": "A JSON object is required"}), 400
            unknown = sorted(set(payload) - set(self.CONFIG_RULES))
            if unknown:
                return jsonify(
                    {"error": f"Unsupported configuration keys: {', '.join(unknown)}"}
                ), 400
            try:
                values = {
                    key: self._validate_config_value(key, value)
                    for key, value in payload.items()
                }
            except (TypeError, ValueError) as exc:
                return jsonify({"error": str(exc)}), 400

            def apply_configuration() -> dict:
                config = self._require_scraper().config
                for key, value in values.items():
                    setattr(config, key, value)
                config.base_url = "http://xboxunity.net"
                config.http_fallback_url = config.base_url
                config.use_https = False
                return {"success": True, "updated": sorted(values)}

            return self._execute(apply_configuration)

    def _require_scraper(self) -> "UnityScraper":
        if self.scraper is None:
            raise RuntimeError("Scraper not initialized")
        return self.scraper

    @staticmethod
    def _required_scope(method: str, path: str) -> str:
        if method in {"GET", "HEAD", "OPTIONS"}:
            return "read"
        if path.startswith("/api/download") or path.startswith("/api/retry-failed"):
            return "transfer"
        return "write"

    def _database_path(self) -> Path:
        if self.scraper is None:
            return DATABASE_PATH
        return Path(getattr(self.scraper.db, "db_path", DATABASE_PATH))

    def _titleid_or_error(self, titleid: str):
        if self.scraper is None:
            return jsonify({"error": "Scraper not initialized"}), 400
        normalized = self.scraper.validate_titleid(titleid)
        if normalized is None:
            return jsonify({"error": "TitleID must be 8 hexadecimal characters"}), 400
        return normalized

    def _execute(self, operation: Callable[[], Any]):
        try:
            return jsonify(operation())
        except RuntimeError as exc:
            return jsonify({"error": str(exc)}), 400
        except Exception as exc:
            return self._server_error(exc)

    @staticmethod
    def _search_response(results: list) -> dict:
        return {"results": results, "count": len(results)}

    @staticmethod
    def _failed_response(items: list) -> dict:
        return {"failed_items": items, "count": len(items)}

    @staticmethod
    def _operation_response(
        success: bool,
        titleid: str,
        success_message: str,
        failure_message: str,
    ) -> dict:
        return {
            "success": bool(success),
            "titleid": titleid,
            "message": success_message if success else failure_message,
        }

    @classmethod
    def _validate_config_value(cls, key: str, value: Any) -> Any:
        expected, minimum, maximum = cls.CONFIG_RULES[key]
        if expected is bool:
            if not isinstance(value, bool):
                raise TypeError(f"{key} must be true or false")
            return value
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError(f"{key} must be numeric")
        converted = expected(value)
        if minimum is not None and converted < minimum:
            raise ValueError(f"{key} must be at least {minimum}")
        if maximum is not None and converted > maximum:
            raise ValueError(f"{key} must be no greater than {maximum}")
        return converted

    @staticmethod
    def _server_error(error: Exception):
        logger.exception("API request failed")
        return jsonify({"error": "The request could not be completed"}), 500

    def run(self, debug: bool = False) -> None:
        self.running = True
        logger.info("Starting API server on %s:%s", self.host, self.port)
        self.app.run(
            host=self.host,
            port=self.port,
            debug=debug,
            use_reloader=False,
        )

    def run_in_thread(self, debug: bool = False) -> threading.Thread:
        thread = threading.Thread(target=self.run, args=(debug,), daemon=True)
        thread.start()
        return thread
