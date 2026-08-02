"""Source adapter framework for Xbox 360 knowledge imports."""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Protocol
from urllib.parse import quote, urlparse

import requests

from app_paths import CACHE_DIR, ensure_app_dirs
from knowledge_base import EntityRecord, KnowledgeRepository, utc_now

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SourceInfo:
    """Metadata about an external knowledge source."""

    slug: str
    name: str
    homepage_url: str
    license_name: str = ""
    license_url: str = ""
    notes: str = ""


@dataclass(frozen=True)
class SourceDocument:
    """A fetched source document and its cache/provenance details."""

    url: str
    title: str
    document_type: str
    text: str
    fetched_at: str
    content_sha256: str
    cache_path: Path
    http_status: int = 200
    from_cache: bool = False
    fetch_error: str = ""
    final_url: str = ""


class SourceAccessBlockedError(requests.RequestException):
    """Raised when a site requires interactive browser verification."""

    def __init__(self, url: str, status_code: int = 403) -> None:
        self.url = url
        self.status_code = status_code
        super().__init__(
            f"{url} denied automated access (HTTP {status_code}). "
            "The site appears to require browser verification. Existing offline "
            "content remains available; open the page in a browser and use "
            "Import Saved Wiki Pages to add or refresh it."
        )


@dataclass(frozen=True)
class ParsedDocument:
    """Adapter output for one source document."""

    document: SourceDocument
    records: tuple[EntityRecord, ...]


class SourceAdapter(Protocol):
    """Adapter interface implemented by each external source."""

    source: SourceInfo
    adapter_name: str

    def fetch_documents(self) -> Iterable[SourceDocument]:
        """Fetch or load every document needed by this adapter."""

    def parse_document(self, document: SourceDocument) -> ParsedDocument:
        """Extract normalized entity records from a fetched document."""


class CachedHttpClient:
    """Small HTTP client with local raw-document cache and request pacing."""

    def __init__(
        self,
        cache_dir: Path | str | None = None,
        rate_limit_seconds: float = 1.0,
        timeout: int = 30,
        session: requests.Session | None = None,
    ) -> None:
        if cache_dir is None:
            ensure_app_dirs()
            self.cache_dir = CACHE_DIR / "source_documents"
        else:
            self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.rate_limit_seconds = rate_limit_seconds
        self.timeout = timeout
        self.session = session or requests.Session()
        self.session.headers.setdefault(
            "User-Agent",
            "UnityScraper/1.2 (+https://github.com/TrapEmAll/UnityScraper)",
        )
        self.session.headers.setdefault(
            "Accept", "text/html,application/xhtml+xml,application/json"
        )
        self._last_request = 0.0
        self._blocked_hosts: dict[str, SourceAccessBlockedError] = {}

    def get_text(
        self,
        url: str,
        title: str,
        document_type: str,
        fallback_urls: Iterable[str] = (),
    ) -> SourceDocument:
        """Fetch a URL, falling back to a cached copy if the network fails."""
        cache_path = self._cache_path(url)
        urls = (url, *tuple(fallback_urls))
        metadata_path = self._metadata_path(url)
        last_error: requests.RequestException | None = None

        for fetch_url in urls:
            host = urlparse(fetch_url).netloc.casefold()
            if host in self._blocked_hosts:
                last_error = self._blocked_hosts[host]
                continue
            self._wait()
            try:
                response = self.session.get(fetch_url, timeout=self.timeout)
                if self._is_browser_challenge(response):
                    raise SourceAccessBlockedError(fetch_url, response.status_code)
                response.raise_for_status()
                text = response.text
                self._validate_content(text, document_type, fetch_url)
                cache_path.write_text(text, encoding="utf-8")
                fetched_at = utc_now()
                metadata = {
                    "url": url,
                    "fetch_url": fetch_url,
                    "final_url": str(getattr(response, "url", fetch_url)),
                    "title": title,
                    "document_type": document_type,
                    "fetched_at": fetched_at,
                    "http_status": response.status_code,
                    "content_sha256": self._sha256_text(text),
                    "content_type": response.headers.get("Content-Type", ""),
                    "etag": response.headers.get("ETag", ""),
                    "last_modified": response.headers.get("Last-Modified", ""),
                }
                metadata_path.write_text(
                    json.dumps(metadata, indent=2, sort_keys=True), encoding="utf-8"
                )
                return SourceDocument(
                    url=url,
                    title=title,
                    document_type=document_type,
                    text=text,
                    fetched_at=fetched_at,
                    content_sha256=self._sha256_text(text),
                    cache_path=cache_path,
                    http_status=response.status_code,
                    final_url=str(metadata["final_url"]),
                )
            except requests.RequestException as exc:
                last_error = exc
                if isinstance(exc, SourceAccessBlockedError):
                    self._blocked_hosts[host] = exc

        if cache_path.exists():
            logger.warning("Using cached source document for %s", url)
            text = cache_path.read_text(encoding="utf-8")
            metadata = self._read_metadata(metadata_path)
            return SourceDocument(
                url=url,
                title=title,
                document_type=document_type,
                text=text,
                fetched_at=str(metadata.get("fetched_at") or utc_now()),
                content_sha256=self._sha256_text(text),
                cache_path=cache_path,
                http_status=0,
                from_cache=True,
                fetch_error=str(last_error or "Network unavailable"),
                final_url=str(metadata.get("final_url") or url),
            )

        if last_error:
            raise last_error
        raise requests.RequestException(f"No fetch URLs available for {url}")

    def store_text(
        self,
        url: str,
        title: str,
        document_type: str,
        text: str,
        *,
        fetched_at: str | None = None,
        imported_from: str = "",
    ) -> SourceDocument:
        """Store a user-provided page in the standard cache with provenance."""
        if not text.strip():
            raise ValueError("The saved page is empty")
        self._validate_content(text, document_type, url)
        cache_path = self._cache_path(url)
        metadata_path = self._metadata_path(url)
        timestamp = fetched_at or utc_now()
        digest = self._sha256_text(text)
        cache_path.write_text(text, encoding="utf-8")
        metadata_path.write_text(
            json.dumps(
                {
                    "url": url,
                    "fetch_url": url,
                    "final_url": url,
                    "title": title,
                    "document_type": document_type,
                    "fetched_at": timestamp,
                    "http_status": 0,
                    "content_sha256": digest,
                    "imported_from": imported_from,
                },
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        return SourceDocument(
            url=url,
            title=title,
            document_type=document_type,
            text=text,
            fetched_at=timestamp,
            content_sha256=digest,
            cache_path=cache_path,
            http_status=0,
            from_cache=True,
            final_url=url,
        )

    def cached_urls(self, hosts: Iterable[str] = ()) -> list[str]:
        """Return canonical URLs recorded by cache metadata sidecars."""
        allowed = {host.casefold() for host in hosts}
        urls: set[str] = set()
        for path in self.cache_dir.glob("*.json"):
            metadata = self._read_metadata(path)
            url = str(metadata.get("url") or "")
            if not url:
                continue
            if allowed and urlparse(url).netloc.casefold() not in allowed:
                continue
            if self._cache_path(url).exists():
                urls.add(url)
        return sorted(urls)

    def _wait(self) -> None:
        elapsed = time.time() - self._last_request
        if elapsed < self.rate_limit_seconds:
            time.sleep(self.rate_limit_seconds - elapsed)
        self._last_request = time.time()

    def _cache_path(self, url: str) -> Path:
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
        return self.cache_dir / f"{digest}.html"

    def _metadata_path(self, url: str) -> Path:
        return self._cache_path(url).with_suffix(".json")

    @staticmethod
    def _read_metadata(path: Path) -> dict[str, object]:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (OSError, ValueError):
            return {}

    @staticmethod
    def _is_browser_challenge(response: requests.Response) -> bool:
        markers = " ".join(
            (
                response.headers.get("Server", ""),
                response.headers.get("cf-ray", ""),
                response.text[:4096],
            )
        ).casefold()
        strong_challenge = any(
            marker in markers
            for marker in ("just a moment", "challenge-platform", "browser verification")
        )
        if response.status_code == 200:
            return strong_challenge and "cloudflare" in markers
        if response.status_code not in {403, 429, 503}:
            return False
        return any(
            marker in markers
            for marker in (
                "cloudflare",
                "cf-ray",
                "just a moment",
                "challenge-platform",
                "browser verification",
            )
        )

    @staticmethod
    def _validate_content(text: str, document_type: str, url: str) -> None:
        stripped = text.lstrip()
        if not stripped:
            raise requests.RequestException(f"Empty response from {url}")
        if document_type == "mediawiki_api" and not stripped.startswith(("{", "[")):
            raise requests.RequestException(
                f"Expected MediaWiki JSON but received a web page from {url}"
            )

    @staticmethod
    def _sha256_text(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()


def mediawiki_raw_url(page_title: str) -> str:
    """Return a MediaWiki raw-wikitext URL for a page title."""
    return (
        "https://consolemods.org/w/index.php?title="
        f"{quote(page_title, safe=':_')}&action=raw"
    )


class KnowledgeImportService:
    """Run adapters and persist their records with source provenance."""

    def __init__(self, repository: KnowledgeRepository) -> None:
        self.repository = repository

    def run_adapter(self, adapter: SourceAdapter) -> dict[str, int | str]:
        """Run one adapter and return a compact import summary."""
        source = adapter.source
        source_id = self.repository.upsert_source(
            source.slug,
            source.name,
            homepage_url=source.homepage_url,
            license_name=source.license_name,
            license_url=source.license_url,
            notes=source.notes,
        )
        run_id = self.repository.begin_import_run(source.slug, adapter.adapter_name)
        records_seen = 0
        records_imported = 0
        cached_documents = 0
        errors: list[str] = []

        status = "success"
        try:
            for document in adapter.fetch_documents():
                if document.fetch_error:
                    cached_documents += 1
                    if document.fetch_error not in errors:
                        errors.append(document.fetch_error)
                document_id, revision_id = self.repository.upsert_document(
                    source_id,
                    document.url,
                    document.title,
                    document.document_type,
                    document.fetched_at,
                    document.content_sha256,
                    str(document.cache_path),
                    http_status=document.http_status,
                    license_name=source.license_name,
                    metadata={
                        "from_cache": document.from_cache,
                        "fetch_error": document.fetch_error,
                        "final_url": document.final_url,
                    },
                )
                parsed = adapter.parse_document(document)
                records_seen += len(parsed.records)
                for record in parsed.records:
                    self.repository.upsert_entity_record(
                        record,
                        source_id,
                        document_id=document_id,
                        revision_id=revision_id,
                    )
                    records_imported += 1
            for warning in getattr(adapter, "errors", ()):
                if warning not in errors:
                    errors.append(warning)
        except Exception as exc:
            errors.append(str(exc))
            status = "partial" if records_imported else "failed"
        if status == "success" and records_seen == 0:
            status = "empty"
        elif status == "success" and errors:
            status = "partial"

        self.repository.finish_import_run(
            run_id,
            status,
            records_seen,
            records_imported,
            errors,
        )
        return {
            "source": source.slug,
            "adapter": adapter.adapter_name,
            "status": status,
            "records_seen": records_seen,
            "records_imported": records_imported,
            "cached_documents": cached_documents,
            "error": "; ".join(errors),
        }
