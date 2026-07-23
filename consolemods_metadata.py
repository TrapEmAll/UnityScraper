"""ConsoleMods metadata fallback for Xbox 360 TitleIDs.

The ConsoleMods Title ID pages encode the publisher in each TitleID's first
four hexadecimal digits. This module downloads both reference pages, parses
publisher prefixes and multi-ID title aliases, and uses them only when the
existing database metadata is missing or unknown.
"""

from __future__ import annotations

import html
import json
import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

from app_paths import DATA_DIR, ensure_app_dirs

logger = logging.getLogger(__name__)

EVERY_TITLE_ID_URL = (
    "https://consolemods.org/wiki/Xbox_360:List_of_Every_Xbox_360_Title_ID"
)
MULTI_ID_URL = "https://consolemods.org/wiki/Xbox_360:List_of_Multi-ID_Games"
CACHE_PATH = DATA_DIR / "consolemods_metadata.json"
CACHE_MAX_AGE_SECONDS = 30 * 24 * 60 * 60
UNKNOWN_VALUES = {"", "unknown", "unknown publisher", "n/a", "none", "null"}

_PUBLISHER_HEADING_RE = re.compile(
    r"(?:<span[^>]+class=[\"']mw-headline[\"'][^>]*>)?"
    r"(?P<code>[A-Za-z0-9]{2})\s*\((?P<prefix>[0-9A-Fa-f]{4})\)\s*"
    r"(?:--&gt;|-->|→)\s*(?P<publisher>[^<\n]+)",
    re.IGNORECASE,
)
_TITLE_ID_RE = re.compile(r"\b[0-9A-Fa-f]{8}\b")
_TAG_RE = re.compile(r"<[^>]+>")
_SPACE_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class MetadataMatch:
    """Metadata resolved for a single TitleID."""

    titleid: str
    publisher: str = ""
    title: str = ""
    related_titleids: tuple[str, ...] = ()
    source: str = "ConsoleMods"


def _clean_text(value: str) -> str:
    value = html.unescape(_TAG_RE.sub(" ", value))
    return _SPACE_RE.sub(" ", value).strip(" \t\r\n-–—:|")


def _publisher_prefix(titleid: str) -> str:
    normalized = titleid.strip().upper()
    if not _TITLE_ID_RE.fullmatch(normalized):
        return ""
    return normalized[:4]


def _is_unknown(value: str | None) -> bool:
    return not value or value.strip().casefold() in UNKNOWN_VALUES


class ConsoleModsMetadata:
    """Load, cache, and query ConsoleMods publisher/title metadata."""

    def __init__(
        self,
        cache_path: Path | str = CACHE_PATH,
        timeout: int = 30,
        session: requests.Session | None = None,
    ) -> None:
        ensure_app_dirs()
        self.cache_path = Path(cache_path)
        self.timeout = timeout
        self.session = session or requests.Session()
        self.session.headers.setdefault(
            "User-Agent",
            "UnityScraper/0.8 (+https://github.com/TrapEmAll/UnityScraper)",
        )
        self._data: dict[str, Any] | None = None

    def lookup(self, titleid: str, refresh: bool = False) -> MetadataMatch | None:
        """Return publisher/title metadata for an eight-digit hexadecimal TitleID."""
        normalized = titleid.strip().upper()
        if not _TITLE_ID_RE.fullmatch(normalized):
            return None

        data = self.load(refresh=refresh)
        prefix = _publisher_prefix(normalized)
        publisher = str(data.get("publishers", {}).get(prefix, "")).strip()
        multi = data.get("multi_id", {}).get(normalized, {})
        title = str(multi.get("title", "")).strip()
        related = tuple(
            item
            for item in multi.get("titleids", [])
            if isinstance(item, str) and item != normalized
        )

        if not publisher and not title and not related:
            return None
        return MetadataMatch(normalized, publisher, title, related)

    def load(self, refresh: bool = False) -> dict[str, Any]:
        if self._data is not None and not refresh:
            return self._data

        cached = self._read_cache()
        if cached and not refresh and not self._cache_is_stale(cached):
            self._data = cached
            return cached

        try:
            fresh = self.refresh()
        except (requests.RequestException, OSError, ValueError) as exc:
            logger.warning("ConsoleMods metadata refresh failed: %s", exc)
            if cached:
                self._data = cached
                return cached
            self._data = self._empty_data()
            return self._data

        self._data = fresh
        return fresh

    def refresh(self) -> dict[str, Any]:
        """Download and parse both ConsoleMods reference pages."""
        every_html = self._download(EVERY_TITLE_ID_URL)
        multi_html = self._download(MULTI_ID_URL)
        data = {
            "version": 1,
            "updated_at": int(time.time()),
            "sources": [EVERY_TITLE_ID_URL, MULTI_ID_URL],
            "publishers": self.parse_publishers(every_html),
            "multi_id": self.parse_multi_id_games(multi_html),
        }
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
        logger.info(
            "Cached ConsoleMods metadata: %s publishers, %s multi-ID entries",
            len(data["publishers"]),
            len(data["multi_id"]),
        )
        return data

    def _download(self, url: str) -> str:
        response = self.session.get(url, timeout=self.timeout)
        response.raise_for_status()
        return response.text

    @staticmethod
    def parse_publishers(page_html: str) -> dict[str, str]:
        publishers: dict[str, str] = {}
        for match in _PUBLISHER_HEADING_RE.finditer(page_html):
            prefix = match.group("prefix").upper()
            publisher = _clean_text(match.group("publisher"))
            if publisher:
                publishers.setdefault(prefix, publisher)
        return publishers

    @staticmethod
    def parse_multi_id_games(page_html: str) -> dict[str, dict[str, Any]]:
        """Parse rows/sections containing one title name and two or more TitleIDs."""
        groups: dict[str, dict[str, Any]] = {}
        candidates = re.findall(
            r"<(?:tr|li|p|h[2-5])\b[^>]*>(.*?)</(?:tr|li|p|h[2-5])>",
            page_html,
            flags=re.IGNORECASE | re.DOTALL,
        )

        for candidate in candidates:
            titleids = list(dict.fromkeys(item.upper() for item in _TITLE_ID_RE.findall(candidate)))
            if len(titleids) < 2:
                continue
            text = _clean_text(_TITLE_ID_RE.sub(" ", candidate))
            text = re.sub(r"\b(?:PAL|NTSC|JAP|JPN|USA|EUR|EU|JP|NA)\b", " ", text, flags=re.I)
            title = _SPACE_RE.sub(" ", text).strip(" -–—:|,")
            if not title or len(title) > 180:
                continue
            record = {"title": title, "titleids": titleids}
            for titleid in titleids:
                groups[titleid] = record
        return groups

    def _read_cache(self) -> dict[str, Any] | None:
        if not self.cache_path.exists():
            return None
        try:
            value = json.loads(self.cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return value if isinstance(value, dict) else None

    @staticmethod
    def _cache_is_stale(data: dict[str, Any]) -> bool:
        try:
            updated_at = int(data.get("updated_at", 0))
        except (TypeError, ValueError):
            return True
        return time.time() - updated_at > CACHE_MAX_AGE_SECONDS

    @staticmethod
    def _empty_data() -> dict[str, Any]:
        return {
            "version": 1,
            "updated_at": 0,
            "sources": [EVERY_TITLE_ID_URL, MULTI_ID_URL],
            "publishers": {},
            "multi_id": {},
        }


def resolve_unknown_metadata(
    titleid: str,
    name: str | None = None,
    publisher: str | None = None,
    provider: ConsoleModsMetadata | None = None,
) -> tuple[str | None, str | None, dict[str, Any]]:
    """Fill only unknown name/publisher fields and return source metadata."""
    provider = provider or ConsoleModsMetadata()
    match = provider.lookup(titleid)
    if match is None:
        return name, publisher, {}

    resolved_name = match.title if _is_unknown(name) and match.title else name
    resolved_publisher = (
        match.publisher if _is_unknown(publisher) and match.publisher else publisher
    )
    metadata: dict[str, Any] = {
        "metadata_source": match.source,
        "publisher_prefix": _publisher_prefix(match.titleid),
    }
    if match.related_titleids:
        metadata["related_titleids"] = list(match.related_titleids)
    return resolved_name, resolved_publisher, metadata
