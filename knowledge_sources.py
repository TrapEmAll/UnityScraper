"""Source adapter framework for Xbox 360 knowledge imports."""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Protocol
from urllib.parse import quote

import requests

from app_paths import DATA_DIR, ensure_app_dirs
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
        ensure_app_dirs()
        self.cache_dir = Path(cache_dir) if cache_dir else DATA_DIR / "source_cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.rate_limit_seconds = rate_limit_seconds
        self.timeout = timeout
        self.session = session or requests.Session()
        self.session.headers.setdefault(
            "User-Agent",
            (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "UnityScraperKnowledge/1.0 Safari/537.36"
            ),
        )
        self.session.headers.setdefault("Accept", "text/html,application/xhtml+xml")
        self._last_request = 0.0

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
        last_error: requests.RequestException | None = None

        for fetch_url in urls:
            self._wait()
            try:
                response = self.session.get(fetch_url, timeout=self.timeout)
                response.raise_for_status()
                text = response.text
                cache_path.write_text(text, encoding="utf-8")
                fetched_at = utc_now()
                return SourceDocument(
                    url=url,
                    title=title,
                    document_type=document_type,
                    text=text,
                    fetched_at=fetched_at,
                    content_sha256=self._sha256_text(text),
                    cache_path=cache_path,
                    http_status=response.status_code,
                )
            except requests.RequestException as exc:
                last_error = exc

        if cache_path.exists():
            logger.warning("Using cached source document for %s", url)
            text = cache_path.read_text(encoding="utf-8")
            return SourceDocument(
                url=url,
                title=title,
                document_type=document_type,
                text=text,
                fetched_at=utc_now(),
                content_sha256=self._sha256_text(text),
                cache_path=cache_path,
                http_status=0,
            )

        if last_error:
            raise last_error
        raise requests.RequestException(f"No fetch URLs available for {url}")

    def _wait(self) -> None:
        elapsed = time.time() - self._last_request
        if elapsed < self.rate_limit_seconds:
            time.sleep(self.rate_limit_seconds - elapsed)
        self._last_request = time.time()

    def _cache_path(self, url: str) -> Path:
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
        return self.cache_dir / f"{digest}.html"

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
        errors: list[str] = []

        try:
            for document in adapter.fetch_documents():
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
        except Exception as exc:
            errors.append(str(exc))
            self.repository.finish_import_run(
                run_id,
                "failed",
                records_seen,
                records_imported,
                errors,
            )
            raise

        self.repository.finish_import_run(
            run_id,
            "success",
            records_seen,
            records_imported,
            errors,
        )
        return {
            "source": source.slug,
            "adapter": adapter.adapter_name,
            "records_seen": records_seen,
            "records_imported": records_imported,
        }
