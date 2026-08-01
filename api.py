"""Optional REST API for local UnityScraper automation."""

from __future__ import annotations

import logging
import os
import secrets
import threading
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
        cors_origins: Optional[list[str]] = None,
    ):
        self.scraper = scraper
        self.port = port
        self.host = host
        self.token = token or os.environ.get("UNITYSCRAPER_API_TOKEN", "").strip()
        if host not in LOOPBACK_HOSTS and not self.token:
            raise ValueError(
                "A token is required when the API is bound beyond localhost"
            )

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
            if not self.token or request.path == "/api/health":
                return None
            supplied = request.headers.get("X-API-Key", "")
            authorization = request.headers.get("Authorization", "")
            if authorization.startswith("Bearer "):
                supplied = authorization[7:]
            if not secrets.compare_digest(supplied, self.token):
                return jsonify({"error": "Authentication required"}), 401
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
                    "authentication_required": bool(self.token),
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
