import json
import logging
import os
import re
import threading
import time
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Iterable

import requests
from requests.exceptions import RequestException, Timeout

# ---------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------
# IMPORTANT: ensure handler goes to stderr
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
if not logger.handlers:
    _handler = logging.StreamHandler(sys.stderr)
    _formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    _handler.setFormatter(_formatter)
    logger.addHandler(_handler)

# Prevent duplicate logs if root logger has handlers too
logger.propagate = False

class UnityScraper:
    """
    UnityScraper:
      - Downloads cover art and Title Updates (TUs) from xboxunity.net endpoints
      - Saves raw JSON responses for archival / debugging
      - Supports parallel downloads (covers/updates) with thread-safe HTTP sessions
      - Adds rate limiting and stronger retry behavior (including 429 Retry-After)
    """

    # IMPORTANT: User requested NO HTTPS support.
    BASE_URL = "http://xboxunity.net"

    # -----------------------------------------------------------------
    # Endpoints (Lib is correct for CoverInfo; keep fallbacks for resilience)
    # -----------------------------------------------------------------
    COVERS_INFO_ENDPOINT = "/Resources/Lib/CoverInfo.php"
    COVER_IMAGE_ENDPOINT = "/Resources/Lib/Cover.php"

    UPDATES_INFO_ENDPOINT = "/Resources/Lib/TitleUpdateInfo.php"
    UPDATE_DOWNLOAD_ENDPOINT = "/Resources/Lib/TitleUpdate.php"

    # Fallback (legacy / alternative)
    _ALT_COVERS_INFO_ENDPOINT = "/Resources/Covers/CoverInfo.php"
    _ALT_COVER_IMAGE_ENDPOINT = "/Resources/Covers/Cover.php"

    _ALT_UPDATES_INFO_ENDPOINT = "/Resources/TitleUpdates/TitleUpdateInfo.php"
    _ALT_UPDATE_DOWNLOAD_ENDPOINT = "/Resources/TitleUpdates/TitleUpdate.php"

    # Retry tuning
    MAX_RETRIES = 5
    BACKOFF_FACTOR = 2.0
    MAX_BACKOFF = 45.0

    # Default threading
    DEFAULT_MAX_WORKERS = 4

    # TitleID format: 8 hex chars
    TITLEID_RE = re.compile(r"^[0-9A-F]{8}$")

    def __init__(
        self,
        base_dir: str = "unityscrape",
        max_workers: int = DEFAULT_MAX_WORKERS,
        min_request_interval: float = 0.35,
        user_agent: str = "UnityScraper/1.3 (+https://github.com/Sthornberry9/UnityScraper)",
        session: Optional[requests.Session] = None,
    ):
        self.base_dir = Path(base_dir)
        self.max_workers = max(1, int(max_workers))
        self.min_request_interval = max(0.0, float(min_request_interval))
        self.user_agent = user_agent

        # Thread-local sessions (safe for ThreadPoolExecutor)
        self._tls = threading.local()

        # Optional single session (only safe for single-thread usage)
        self._single_session = session

        # Global pacing across threads
        self._rate_lock = threading.Lock()
        self._last_request_ts = 0.0

    # -----------------------------------------------------------------
    # Session / Rate limiting helpers
    # -----------------------------------------------------------------
    def _get_session(self) -> requests.Session:
        if self.max_workers == 1 and self._single_session is not None:
            return self._single_session

        sess = getattr(self._tls, "session", None)
        if sess is None:
            sess = requests.Session()
            sess.headers.update(
                {
                    "User-Agent": self.user_agent,
                    "Accept": "*/*",
                    "Connection": "keep-alive",
                }
            )
            self._tls.session = sess
        return sess

    def _pace_requests(self) -> None:
        if self.min_request_interval <= 0:
            return
        with self._rate_lock:
            now = time.time()
            delta = now - self._last_request_ts
            if delta < self.min_request_interval:
                time.sleep(self.min_request_interval - delta)
            self._last_request_ts = time.time()

    # -----------------------------------------------------------------
    # Utility helpers
    # -----------------------------------------------------------------
    @staticmethod
    def normalize_title_id(title_id: str) -> Optional[str]:
        if not title_id:
            return None
        tid = title_id.strip().upper()
        return tid if UnityScraper.TITLEID_RE.match(tid) else None

    @staticmethod
    def _atomic_write_text(path: Path, text: str, encoding: str = "utf-8") -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(text, encoding=encoding)
        os.replace(tmp, path)

    @staticmethod
    def _safe_filename(name: str, fallback: str = "file.bin") -> str:
        if not name:
            return fallback
        name = name.replace("\\", "_").replace("/", "_")
        name = re.sub(r'[<>:"|?*\x00-\x1F]', "_", name)
        name = name.strip().rstrip(" .")
        return name or fallback

    @staticmethod
    def _extract_filename(content_disposition: Optional[str]) -> Optional[str]:
        if not content_disposition:
            return None
        m = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?', content_disposition, re.IGNORECASE)
        return m.group(1).strip() if m and m.group(1).strip() else None

    # -----------------------------------------------------------------
    # HTTP request wrapper
    # -----------------------------------------------------------------
    def _make_request(
        self,
        url: str,
        *,
        stream: bool = False,
        timeout: float = 15.0,
        allow_404: bool = False,
    ) -> Optional[requests.Response]:
        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                self._pace_requests()
                sess = self._get_session()
                resp = sess.get(url, timeout=timeout, stream=stream)

                if resp.status_code == 429:
                    retry_after = resp.headers.get("Retry-After")
                    wait_s = None
                    if retry_after:
                        try:
                            wait_s = float(retry_after)
                        except ValueError:
                            wait_s = None
                    if wait_s is None:
                        wait_s = min(self.MAX_BACKOFF, (self.BACKOFF_FACTOR ** attempt))
                    logger.warning("429 rate limited. Sleeping %.2fs then retrying (%d/%d): %s",
                                   wait_s, attempt, self.MAX_RETRIES, url)
                    time.sleep(wait_s)
                    continue

                if 500 <= resp.status_code <= 599:
                    wait_s = min(self.MAX_BACKOFF, (self.BACKOFF_FACTOR ** attempt))
                    logger.warning("Server error %s. Sleeping %.2fs then retrying (%d/%d): %s",
                                   resp.status_code, wait_s, attempt, self.MAX_RETRIES, url)
                    time.sleep(wait_s)
                    continue

                if allow_404 and resp.status_code == 404:
                    return resp

                resp.raise_for_status()
                return resp

            except (Timeout, RequestException) as exc:
                wait_s = min(self.MAX_BACKOFF, (self.BACKOFF_FACTOR ** attempt))
                logger.warning("Request failed (%d/%d). Sleeping %.2fs. %s -> %s",
                               attempt, self.MAX_RETRIES, wait_s, url, exc)
                time.sleep(wait_s)

        logger.error("All retries failed for URL: %s", url)
        return None

    def _fetch_with_fallback(self, primary_url: str, fallback_url: str, *, stream: bool) -> Optional[requests.Response]:
        resp = self._make_request(primary_url, stream=stream, allow_404=True)
        if resp is None:
            return None
        if resp.status_code != 404:
            return resp
        logger.warning("Primary endpoint 404. Falling back.\n  Primary: %s\n  Fallback: %s", primary_url, fallback_url)
        return self._make_request(fallback_url, stream=stream, allow_404=False)

    # -----------------------------------------------------------------
    # JSON storage
    # -----------------------------------------------------------------
    def _save_json(self, title_id: str, payload: Dict[str, Any], json_type: str) -> None:
        out_path = self.base_dir / title_id / f"{json_type}_data.json"
        try:
            pretty = json.dumps(payload, indent=4)
            self._atomic_write_text(out_path, pretty, encoding="utf-8")
            logger.info("Saved %s JSON for %s -> %s", json_type, title_id, out_path)
        except Exception as exc:
            logger.error("Failed to save %s JSON for %s: %s", json_type, title_id, exc)

    # -----------------------------------------------------------------
    # Covers
    # -----------------------------------------------------------------
    
        # -----------------------------------------------------------------
    # Covers: list + download single
    # -----------------------------------------------------------------
    def get_covers_info(self, title_id: str) -> Optional[Dict[str, Any]]:
        """Fetch cover info JSON for a TitleID (no downloads)."""
        tid = self.normalize_title_id(title_id)
        if not tid:
            logger.error("Invalid TitleID: %s", title_id)
            return None

        primary_info = f"{self.BASE_URL}{self.COVERS_INFO_ENDPOINT}?titleid={tid}"
        fallback_info = f"{self.BASE_URL}{self._ALT_COVERS_INFO_ENDPOINT}?titleid={tid}"

        resp = self._fetch_with_fallback(primary_info, fallback_info, stream=False)
        if not resp:
            logger.error("Cover info request failed: %s", tid)
            return None

        try:
            data = resp.json()
        except Exception as exc:
            logger.error("Failed to parse cover info JSON for %s: %s", tid, exc)
            return None

        self._save_json(tid, data, "covers")
        return data

    def download_cover_by_id(self, title_id: str, cover_id: str, out_dir: Optional[str] = None) -> Optional[str]:
        """Download a single cover image by CoverID. Returns the output filepath."""
        tid = self.normalize_title_id(title_id)
        if not tid:
            logger.error("Invalid TitleID: %s", title_id)
            return None

        cid = str(cover_id).strip()
        if not cid:
            logger.error("Invalid CoverID: %s", cover_id)
            return None

        primary_img = f"{self.BASE_URL}{self.COVER_IMAGE_ENDPOINT}?size=large&cid={cid}"
        fallback_img = f"{self.BASE_URL}{self._ALT_COVER_IMAGE_ENDPOINT}?size=large&cid={cid}"

        img_resp = self._fetch_with_fallback(primary_img, fallback_img, stream=True)
        if not img_resp:
            logger.error("Cover download failed: title=%s cover=%s", tid, cid)
            return None

        cd = img_resp.headers.get("content-disposition")
        filename = self._extract_filename(cd)
        if not filename:
            ctype = (img_resp.headers.get("Content-Type") or "").lower()
            ext = "jpg"
            if "png" in ctype:
                ext = "png"
            elif "jpeg" in ctype or "jpg" in ctype:
                ext = "jpg"
            filename = f"{cid}.{ext}"

        filename = self._safe_filename(filename, fallback=f"{cid}.jpg")

        base = Path(out_dir) if out_dir else (self.base_dir / tid / "covers")
        base.mkdir(parents=True, exist_ok=True)
        out_file = base / filename

        try:
            with out_file.open("wb") as fp:
                for chunk in img_resp.iter_content(chunk_size=1024 * 64):
                    if chunk:
                        fp.write(chunk)
            return str(out_file)
        except Exception as exc:
            logger.error("Failed writing cover %s for %s: %s", cid, tid, exc)
            return None
    
    def download_covers(self, title_id: str) -> bool:
        tid = self.normalize_title_id(title_id)
        if not tid:
            logger.error("Invalid TitleID: %s", title_id)
            return False

        primary_info = f"{self.BASE_URL}{self.COVERS_INFO_ENDPOINT}?titleid={tid}"
        fallback_info = f"{self.BASE_URL}{self._ALT_COVERS_INFO_ENDPOINT}?titleid={tid}"

        resp = self._fetch_with_fallback(primary_info, fallback_info, stream=False)
        if not resp:
            logger.error("Cover info request failed: %s", tid)
            return False

        try:
            data = resp.json()
        except Exception as exc:
            logger.error("Failed to parse cover info JSON for %s: %s", tid, exc)
            return False

        self._save_json(tid, data, "covers")

        covers_list = data.get("Covers", [])
        if not isinstance(covers_list, list) or not covers_list:
            logger.warning("No covers found for TitleID %s", tid)
            return False

        cover_dir = self.base_dir / tid / "covers"
        cover_dir.mkdir(parents=True, exist_ok=True)

        def _download_single_cover(cover: Dict[str, Any]) -> Tuple[bool, str]:
            cover_id = str(cover.get("CoverID", "")).strip()
            if not cover_id:
                return False, "UNKNOWN"

            primary_img = f"{self.BASE_URL}{self.COVER_IMAGE_ENDPOINT}?size=large&cid={cover_id}"
            fallback_img = f"{self.BASE_URL}{self._ALT_COVER_IMAGE_ENDPOINT}?size=large&cid={cover_id}"

            img_resp = self._fetch_with_fallback(primary_img, fallback_img, stream=True)
            if not img_resp:
                return False, cover_id

            cd = img_resp.headers.get("content-disposition")
            filename = self._extract_filename(cd)

            if not filename:
                ctype = (img_resp.headers.get("Content-Type") or "").lower()
                ext = "jpg"
                if "png" in ctype:
                    ext = "png"
                elif "jpeg" in ctype or "jpg" in ctype:
                    ext = "jpg"
                filename = f"{cover_id}.{ext}"

            filename = self._safe_filename(filename, fallback=f"{cover_id}.jpg")
            out_file = cover_dir / filename

            try:
                with out_file.open("wb") as fp:
                    for chunk in img_resp.iter_content(chunk_size=1024 * 64):
                        if chunk:
                            fp.write(chunk)
                return True, cover_id
            except Exception as exc:
                logger.error("Failed writing cover %s for %s: %s", cover_id, tid, exc)
                return False, cover_id

        ok_any = False
        all_ok = True

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {executor.submit(_download_single_cover, c): c for c in covers_list}
            for fut in as_completed(futures):
                success, cover_id = fut.result()
                ok_any = ok_any or success
                if not success:
                    all_ok = False
                    logger.warning("Cover download failed for TitleID %s (CoverID %s)", tid, cover_id)

        return ok_any and all_ok or ok_any

    # -----------------------------------------------------------------
    # Updates: schema-tolerant extraction
    # -----------------------------------------------------------------
    @staticmethod
    def _iter_dicts(obj: Any) -> Iterable[Dict[str, Any]]:
        """
        Walks through nested structures and yields dictionaries.
        Used to robustly find update entries even when schema differs.
        """
        if isinstance(obj, dict):
            yield obj
            for v in obj.values():
                yield from UnityScraper._iter_dicts(v)
        elif isinstance(obj, list):
            for item in obj:
                yield from UnityScraper._iter_dicts(item)

    @staticmethod
    def _extract_update_tasks(data: Dict[str, Any]) -> List[Tuple[str, Dict[str, Any]]]:
        """
        Returns list of (media_id, update_entry_dict)

        Handles multiple possible schemas, including XboxUnity's common typo/variant:
          - MediaIDS (capital S)  ✅ IMPORTANT
          - MediaIDs
          - MediaID(s) nested
          - Updates / TitleUpdates at top-level
        """
        tasks: List[Tuple[str, Dict[str, Any]]] = []

        def add_update(media_id: str, upd: Dict[str, Any]) -> None:
            mid = str(media_id).strip()
            if not mid:
                return
            if isinstance(upd, dict) and upd:
                tasks.append((mid, upd))

        # ---- NEW: accept MediaIDS as well as MediaIDs
        media = (
            data.get("MediaIDs")
            or data.get("MediaIDS")   # ✅ your JSON uses this
            or data.get("mediaids")
            or data.get("mediaIDS")
        )

        # 1) Media list
        if isinstance(media, list):
            for m in media:
                if not isinstance(m, dict):
                    continue
                mid = m.get("MediaID") or m.get("MediaId") or m.get("mediaid")
                updates = m.get("Updates") or m.get("TitleUpdates") or m.get("updates")
                if mid and isinstance(updates, list):
                    for upd in updates:
                        if isinstance(upd, dict):
                            add_update(str(mid), upd)

        # 2) Media dict (rare)
        if not tasks and isinstance(media, dict):
            mid = media.get("MediaID") or media.get("MediaId") or media.get("mediaid")
            updates = media.get("Updates") or media.get("TitleUpdates") or media.get("updates")
            if mid and isinstance(updates, list):
                for upd in updates:
                    if isinstance(upd, dict):
                        add_update(str(mid), upd)

        # 3) Top-level Updates / TitleUpdates list
        if not tasks:
            top_updates = data.get("Updates") or data.get("TitleUpdates") or data.get("updates")
            if isinstance(top_updates, list):
                for upd in top_updates:
                    if not isinstance(upd, dict):
                        continue
                    mid = upd.get("MediaID") or upd.get("MediaId") or upd.get("mediaid")
                    if mid:
                        add_update(str(mid), upd)

        # 4) Deep scan fallback
        if not tasks:
            for d in UnityScraper._iter_dicts(data):
                tuid = d.get("TitleUpdateID") or d.get("TitleUpdateId") or d.get("tuid")
                if not tuid:
                    continue
                mid = d.get("MediaID") or d.get("MediaId") or d.get("mediaid")
                if mid:
                    add_update(str(mid), d)

        # Deduplicate
        seen = set()
        deduped: List[Tuple[str, Dict[str, Any]]] = []
        for mid, upd in tasks:
            tuid = str(upd.get("TitleUpdateID") or upd.get("TitleUpdateId") or upd.get("tuid") or "").strip()
            key = (mid, tuid)
            if key in seen:
                continue
            seen.add(key)
            deduped.append((mid, upd))

        return deduped


        # -----------------------------------------------------------------
    # Updates: list + download single
    # -----------------------------------------------------------------
    def get_updates_info(self, title_id: str) -> Optional[Dict[str, Any]]:
        """Fetch title update info JSON for a TitleID (no downloads)."""
        tid = self.normalize_title_id(title_id)
        if not tid:
            logger.error("Invalid TitleID: %s", title_id)
            return None

        primary_info = f"{self.BASE_URL}{self.UPDATES_INFO_ENDPOINT}?titleid={tid}"
        fallback_info = f"{self.BASE_URL}{self._ALT_UPDATES_INFO_ENDPOINT}?titleid={tid}"

        resp = self._fetch_with_fallback(primary_info, fallback_info, stream=False)
        if not resp:
            logger.error("Update info request failed: %s", tid)
            return None

        try:
            data = resp.json()
        except Exception as exc:
            logger.error("Failed to parse update info JSON for %s: %s", tid, exc)
            return None

        self._save_json(tid, data, "updates")
        return data

    def download_update_by_id(self, title_update_id: str, out_dir: str) -> Optional[str]:
        """
        Download a single Title Update by TU ID (tuid=...).
        Returns the output filepath.
        """
        tuid = str(title_update_id).strip()
        if not tuid:
            logger.error("Invalid TitleUpdateID: %s", title_update_id)
            return None

        primary_upd = f"{self.BASE_URL}{self.UPDATE_DOWNLOAD_ENDPOINT}?tuid={tuid}"
        fallback_upd = f"{self.BASE_URL}{self._ALT_UPDATE_DOWNLOAD_ENDPOINT}?tuid={tuid}"

        upd_resp = self._fetch_with_fallback(primary_upd, fallback_upd, stream=True)
        if not upd_resp:
            logger.error("Update download failed: tuid=%s", tuid)
            return None

        cd = upd_resp.headers.get("content-disposition")
        filename = self._extract_filename(cd) or f"update_{tuid}.bin"
        filename = self._safe_filename(filename, fallback=f"update_{tuid}.bin")

        out_path = Path(out_dir)
        out_path.mkdir(parents=True, exist_ok=True)
        out_file = out_path / filename

        try:
            with out_file.open("wb") as fp:
                for chunk in upd_resp.iter_content(chunk_size=1024 * 64):
                    if chunk:
                        fp.write(chunk)
            return str(out_file)
        except Exception as exc:
            logger.error("Failed writing update %s: %s", tuid, exc)
            return None


    def download_updates(self, title_id: str) -> bool:
        tid = self.normalize_title_id(title_id)
        if not tid:
            logger.error("Invalid TitleID: %s", title_id)
            return False

        primary_info = f"{self.BASE_URL}{self.UPDATES_INFO_ENDPOINT}?titleid={tid}"
        fallback_info = f"{self.BASE_URL}{self._ALT_UPDATES_INFO_ENDPOINT}?titleid={tid}"

        resp = self._fetch_with_fallback(primary_info, fallback_info, stream=False)
        if not resp:
            logger.error("Update info request failed: %s", tid)
            return False

        try:
            data = resp.json()
        except Exception as exc:
            logger.error("Failed to parse update info JSON for %s: %s", tid, exc)
            return False

        self._save_json(tid, data, "updates")

        tasks = self._extract_update_tasks(data)
        if not tasks:
            logger.warning("No update entries found for TitleID %s (schema mismatch or truly none).", tid)
            return False

        def _download_single_update(media_id: str, update_entry: Dict[str, Any]) -> Tuple[bool, str]:
            tuid = str(update_entry.get("TitleUpdateID") or update_entry.get("TitleUpdateId") or update_entry.get("tuid") or "").strip()
            version = str(update_entry.get("Version") or update_entry.get("version") or "").strip() or "unknown"
            if not tuid:
                return False, "UNKNOWN"

            primary_upd = f"{self.BASE_URL}{self.UPDATE_DOWNLOAD_ENDPOINT}?tuid={tuid}"
            fallback_upd = f"{self.BASE_URL}{self._ALT_UPDATE_DOWNLOAD_ENDPOINT}?tuid={tuid}"

            upd_resp = self._fetch_with_fallback(primary_upd, fallback_upd, stream=True)
            if not upd_resp:
                return False, tuid

            cd = upd_resp.headers.get("content-disposition")
            filename = self._extract_filename(cd) or f"update_{tuid}.bin"
            filename = self._safe_filename(filename, fallback=f"update_{tuid}.bin")

            # Keep legacy layout for drop-in compatibility
            out_dir = self.base_dir / tid / str(media_id) / f"updateversion{version}"
            out_dir.mkdir(parents=True, exist_ok=True)
            out_file = out_dir / filename

            try:
                with out_file.open("wb") as fp:
                    for chunk in upd_resp.iter_content(chunk_size=1024 * 64):
                        if chunk:
                            fp.write(chunk)
                return True, tuid
            except Exception as exc:
                logger.error("Failed writing update %s for %s: %s", tuid, tid, exc)
                return False, tuid

        ok_any = False
        all_ok = True

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {executor.submit(_download_single_update, mid, upd): (mid, upd) for (mid, upd) in tasks}
            for fut in as_completed(futures):
                success, tuid = fut.result()
                ok_any = ok_any or success
                if not success:
                    all_ok = False
                    logger.warning("Update download failed for TitleID %s (TU %s)", tid, tuid)

        return ok_any and all_ok or ok_any

    # -----------------------------------------------------------------
    # Multi-title orchestration
    # -----------------------------------------------------------------
    def scrape_multiple(self, title_ids: List[str]) -> List[str]:
        failed: List[str] = []

        normalized: List[str] = []
        for raw in title_ids:
            tid = self.normalize_title_id(raw)
            if tid:
                normalized.append(tid)
            else:
                logger.warning("Skipping invalid TitleID: %s", raw)

        for idx, tid in enumerate(normalized, start=1):
            logger.info("=== (%d/%d) Processing TitleID %s ===", idx, len(normalized), tid)

            ok_covers = self.download_covers(tid)
            ok_updates = self.download_updates(tid)

            if not (ok_covers and ok_updates):
                failed.append(tid)

            logger.info("=== Finished %s (covers: %s, updates: %s) ===", tid, ok_covers, ok_updates)

        return failed
