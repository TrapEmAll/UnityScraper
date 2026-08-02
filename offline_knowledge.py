"""Safe, self-contained offline archive for cached community wiki pages."""

from __future__ import annotations

import hashlib
import html
import json
import re
import sqlite3
import zipfile
from dataclasses import dataclass
from contextlib import closing
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse

from app_paths import DATABASE_PATH, OFFLINE_KNOWLEDGE_DIR
from consolemods_adapters import (
    ConsoleModsMultiIdAdapter,
    ConsoleModsTitleIdAdapter,
)
from database import DatabaseManager
from knowledge_base import KnowledgeRepository, utc_now
from knowledge_sources import CachedHttpClient, KnowledgeImportService, SourceDocument
from wiki_adapters import (
    CONSOLEMODS_WIKI_SOURCE,
    FREE60_SOURCE,
    XENONLIBRARY_SOURCE,
    ConsoleModsWikiAdapter,
    Free60WikiAdapter,
    XenonLibraryWikiAdapter,
    extract_article_text,
)

MAX_FILES = 5000
MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_TOTAL_BYTES = 250 * 1024 * 1024

SOURCE_ADAPTERS = {
    "consolemods-wiki": ConsoleModsWikiAdapter,
    "xenonlibrary": XenonLibraryWikiAdapter,
    "free60": Free60WikiAdapter,
}
SOURCE_INFO = {
    source.slug: source
    for source in (CONSOLEMODS_WIKI_SOURCE, XENONLIBRARY_SOURCE, FREE60_SOURCE)
}
SOURCE_HOSTS = {
    "consolemods-wiki": {"consolemods.org", "www.consolemods.org"},
    "xenonlibrary": {"xenonlibrary.com", "www.xenonlibrary.com"},
    "free60": {"free60.org", "www.free60.org"},
}


class OfflineArchiveError(ValueError):
    """A saved-page import or offline archive could not be completed safely."""


class _PageMetadataParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.canonical_url = ""
        self.title = ""
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key.casefold(): value or "" for key, value in attrs}
        if tag.casefold() == "title":
            self._in_title = True
        if tag.casefold() == "link" and "canonical" in values.get("rel", "").casefold():
            self.canonical_url = values.get("href", "")
        if tag.casefold() == "meta" and values.get("property", "").casefold() == "og:url":
            self.canonical_url = self.canonical_url or values.get("content", "")

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data


@dataclass(frozen=True)
class _SavedPage:
    name: str
    text: str


class _SavedWikiAdapter:
    def __init__(
        self,
        source_slug: str,
        documents: Iterable[SourceDocument],
        client: CachedHttpClient,
    ) -> None:
        adapter_class = SOURCE_ADAPTERS[source_slug]
        self.source = SOURCE_INFO[source_slug]
        self.adapter_name = f"{source_slug}_saved_pages"
        self._parser = adapter_class(client=client, max_documents=0)
        self._documents = tuple(documents)

    def fetch_documents(self) -> Iterable[SourceDocument]:
        return iter(self._documents)

    def parse_document(self, document: SourceDocument):
        if self.source.slug == "consolemods-wiki":
            lowered_url = document.url.casefold()
            if "list_of_every_xbox_360_title_id" in lowered_url:
                return ConsoleModsTitleIdAdapter(self._parser.client).parse_document(document)
            if "list_of_multi-id_games" in lowered_url:
                return ConsoleModsMultiIdAdapter(self._parser.client).parse_document(document)
        return self._parser.parse_document(document)


class OfflineKnowledgeArchive:
    """Render cached source documents into a private, script-free local library."""

    def __init__(
        self,
        database_path: Path | str = DATABASE_PATH,
        output_dir: Path | str = OFFLINE_KNOWLEDGE_DIR,
        cache_dir: Path | str | None = None,
    ) -> None:
        self.database_path = Path(database_path)
        self.output_dir = Path(output_dir)
        self.client = CachedHttpClient(cache_dir=cache_dir, rate_limit_seconds=0)
        DatabaseManager(str(self.database_path))

    @property
    def index_path(self) -> Path:
        return self.output_dir / "index.html"

    def rebuild(self) -> dict[str, object]:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        started_at = utc_now()
        errors: list[str] = []
        written: list[dict[str, object]] = []
        with closing(sqlite3.connect(self.database_path)) as connection:
            connection.row_factory = sqlite3.Row
            cursor = connection.execute(
                "INSERT INTO offline_archive_runs(started_at, status) VALUES (?, 'running')",
                (started_at,),
            )
            if cursor.lastrowid is None:
                raise RuntimeError("Offline archive run was created without an identifier")
            run_id = int(cursor.lastrowid)
            rows = connection.execute(
                """
                SELECT d.id, d.url, d.title, d.fetched_at, d.content_sha256,
                       d.cache_path, d.metadata, s.slug source_slug, s.name source_name,
                       s.homepage_url, s.license_name, s.license_url
                FROM source_documents d
                JOIN knowledge_sources s ON s.id=d.source_id
                WHERE d.document_type='wiki_article'
                ORDER BY s.name, d.title COLLATE NOCASE
                """
            ).fetchall()
            for row in rows:
                try:
                    cache_path = Path(row["cache_path"] or "")
                    raw = cache_path.read_text(encoding="utf-8")
                    title, body = extract_article_text(raw, row["title"] or row["url"])
                    if not body.strip():
                        raise OfflineArchiveError("cached page contains no readable text")
                    slug = _slug(title)
                    relative = Path("pages") / str(row["source_slug"]) / f"{row['id']}-{slug}.html"
                    destination = self.output_dir / relative
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    metadata = _json_object(row["metadata"])
                    stale = bool(metadata.get("from_cache"))
                    page = self._article_html(dict(row), title, body, stale)
                    _atomic_write(destination, page)
                    connection.execute(
                        """
                        INSERT INTO offline_archive_documents(
                            document_id, archive_path, rendered_at, content_sha256, stale
                        ) VALUES (?, ?, ?, ?, ?)
                        ON CONFLICT(document_id) DO UPDATE SET
                            archive_path=excluded.archive_path,
                            rendered_at=excluded.rendered_at,
                            content_sha256=excluded.content_sha256,
                            stale=excluded.stale
                        """,
                        (row["id"], str(destination), utc_now(), row["content_sha256"], int(stale)),
                    )
                    written.append(
                        {
                            "title": title,
                            "source": row["source_name"],
                            "source_slug": row["source_slug"],
                            "path": relative.as_posix(),
                            "stale": stale,
                            "fetched_at": row["fetched_at"] or "Unknown",
                        }
                    )
                except (OSError, ValueError) as exc:
                    errors.append(f"{row['url']}: {exc}")

            _atomic_write(self.index_path, self._index_html(written))
            manifest = {
                "format": "UnityScraper Offline Knowledge Archive",
                "generated_at": utc_now(),
                "documents": written,
                "errors": errors,
            }
            _atomic_write(
                self.output_dir / "manifest.json",
                json.dumps(manifest, indent=2, sort_keys=True),
            )
            status = "success" if not errors else ("partial" if written else "failed")
            connection.execute(
                """
                UPDATE offline_archive_runs SET finished_at=?, status=?,
                    documents_written=?, index_path=?, errors=? WHERE id=?
                """,
                (utc_now(), status, len(written), str(self.index_path), json.dumps(errors), run_id),
            )
            connection.commit()
        return {
            "status": status,
            "documents_written": len(written),
            "errors": len(errors),
            "index_path": str(self.index_path),
        }

    def import_saved_pages(
        self,
        paths: Path | str | Iterable[Path | str],
        source_slug: str,
    ) -> dict[str, object]:
        if source_slug not in SOURCE_ADAPTERS:
            raise OfflineArchiveError(f"Unsupported wiki source: {source_slug}")
        inputs = [paths] if isinstance(paths, (str, Path)) else list(paths)
        pages = list(_read_saved_pages(Path(item) for item in inputs))
        documents: list[SourceDocument] = []
        for page in pages:
            metadata = _PageMetadataParser()
            metadata.feed(page.text)
            canonical = metadata.canonical_url.strip()
            if canonical and not _allowed_source_url(canonical, source_slug):
                canonical = ""
            if not canonical:
                digest = hashlib.sha256(page.text.encode("utf-8")).hexdigest()
                canonical = f"offline-import://{source_slug}/{digest}"
            title, _body = extract_article_text(page.text, metadata.title.strip() or page.name)
            documents.append(
                self.client.store_text(
                    canonical,
                    title,
                    "wiki_article",
                    page.text,
                    imported_from=page.name,
                )
            )

        db = DatabaseManager(str(self.database_path))
        with db.get_connection() as connection:
            repository = KnowledgeRepository(connection)
            summary = KnowledgeImportService(repository).run_adapter(
                _SavedWikiAdapter(source_slug, documents, self.client)
            )
            connection.execute(
                """
                INSERT INTO offline_page_import_runs(
                    source_slug, source_path, started_at, finished_at, status,
                    files_seen, files_imported, errors
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source_slug,
                    "; ".join(str(Path(item)) for item in inputs),
                    utc_now(),
                    utc_now(),
                    summary["status"],
                    len(pages),
                    summary["records_imported"],
                    json.dumps([summary.get("error", "")] if summary.get("error") else []),
                ),
            )
        enriched = db.enrich_existing_titleids_from_knowledge()
        archive = self.rebuild()
        return {
            **summary,
            "files_seen": len(pages),
            "titleids_enriched": enriched,
            "archive": archive,
        }

    @staticmethod
    def _article_html(row: dict[str, object], title: str, body: str, stale: bool) -> str:
        status = "Offline copy used after a refresh failure" if stale else "Cached copy"
        source_link = _safe_web_url(str(row["url"])) or _safe_web_url(
            str(row["homepage_url"] or "")
        )
        source_footer = (
            f'<p><a href="{html.escape(source_link, quote=True)}">Open original source</a></p>'
            if source_link
            else ""
        )
        paragraphs = "\n".join(
            f"<p>{html.escape(line)}</p>" for line in body.splitlines() if line.strip()
        )
        return _shell(
            title,
            f"""
<nav><a href="../../index.html">Back to library</a></nav>
<main><p class="eyebrow">{html.escape(str(row['source_name']))}</p>
<h1>{html.escape(title)}</h1>
<div class="meta"><span>{html.escape(status)}</span><span>Saved {html.escape(str(row['fetched_at'] or 'Unknown'))}</span></div>
<article>{paragraphs}</article>
<footer><p>License: {html.escape(str(row['license_name'] or 'See source'))}</p>
{source_footer}</footer></main>
""",
        )

    @staticmethod
    def _index_html(documents: list[dict[str, object]]) -> str:
        items = "\n".join(
            f"""<li data-search="{html.escape((str(item['title']) + ' ' + str(item['source'])).casefold(), quote=True)}">
<a href="{html.escape(str(item['path']), quote=True)}">{html.escape(str(item['title']))}</a>
<span>{html.escape(str(item['source']))}{' | offline fallback' if item['stale'] else ''}</span></li>"""
            for item in documents
        ) or "<li>No cached wiki articles are available yet.</li>"
        return _shell(
            "Offline Knowledge Library",
            f"""
<main><p class="eyebrow">UnityScraper</p><h1>Offline Knowledge Library</h1>
<p class="lede">A private, readable archive built from pages you synchronized or imported.</p>
<input id="search" type="search" placeholder="Search {len(documents)} saved pages" aria-label="Search saved pages">
<ul id="articles">{items}</ul></main>
<script>const q=document.getElementById('search');q.addEventListener('input',()=>{{const v=q.value.toLowerCase();document.querySelectorAll('#articles li').forEach(i=>i.hidden=!i.dataset.search?.includes(v));}});</script>
""",
        )


def _read_saved_pages(paths: Iterable[Path]) -> Iterable[_SavedPage]:
    count = 0
    total = 0
    for path in paths:
        candidates = sorted(path.rglob("*")) if path.is_dir() else [path]
        for candidate in candidates:
            if candidate.is_symlink():
                continue
            if candidate.suffix.casefold() == ".zip":
                with zipfile.ZipFile(candidate) as archive:
                    for info in archive.infolist():
                        if info.is_dir() or Path(info.filename).suffix.casefold() not in {".html", ".htm"}:
                            continue
                        _validate_size(info.file_size, total, count)
                        data = archive.read(info)
                        count += 1
                        total += len(data)
                        yield _SavedPage(f"{candidate}!{info.filename}", _decode_html(data))
                continue
            if candidate.suffix.casefold() not in {".html", ".htm"}:
                continue
            size = candidate.stat().st_size
            _validate_size(size, total, count)
            data = candidate.read_bytes()
            count += 1
            total += len(data)
            yield _SavedPage(str(candidate), _decode_html(data))
    if count == 0:
        raise OfflineArchiveError("No HTML pages were found in the selected files")


def _validate_size(size: int, total: int, count: int) -> None:
    if count >= MAX_FILES:
        raise OfflineArchiveError(f"Saved-page import is limited to {MAX_FILES} files")
    if size > MAX_FILE_BYTES:
        raise OfflineArchiveError("A saved page exceeds the 10 MB safety limit")
    if total + size > MAX_TOTAL_BYTES:
        raise OfflineArchiveError("Saved-page import exceeds the 250 MB safety limit")


def _decode_html(data: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "windows-1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _allowed_source_url(url: str, source_slug: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and parsed.netloc.casefold() in SOURCE_HOSTS[source_slug]


def _safe_web_url(url: str) -> str:
    parsed = urlparse(url)
    return url if parsed.scheme in {"http", "https"} and parsed.netloc else ""


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")[:80] or "article"


def _json_object(value: object) -> dict[str, object]:
    try:
        parsed = json.loads(str(value or "{}"))
        return parsed if isinstance(parsed, dict) else {}
    except ValueError:
        return {}


def _atomic_write(path: Path, text: str) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def _shell(title: str, content: str) -> str:
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(title)}</title>
<style>:root{{color-scheme:dark;--bg:#111;--panel:#1b1b1b;--text:#eee;--muted:#aaa;--accent:#6cc24a;--border:#3d3d3d}}*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--text);font:16px/1.55 Segoe UI,Arial,sans-serif}}main,nav{{max-width:1050px;margin:auto;padding:24px}}h1{{font-size:2rem;letter-spacing:0}}a{{color:#8dde69}}.eyebrow{{color:var(--accent);font-weight:700;text-transform:uppercase}}.lede,.meta,footer,li span{{color:var(--muted)}}.meta{{display:flex;gap:20px;flex-wrap:wrap;border-block:1px solid var(--border);padding:10px 0}}article{{margin-top:24px}}article p{{white-space:pre-wrap}}input{{width:100%;padding:12px;background:#202020;border:1px solid var(--border);color:var(--text);font:inherit}}ul{{list-style:none;padding:0}}li{{display:grid;gap:2px;padding:12px 0;border-bottom:1px solid var(--border)}}footer{{margin-top:32px;border-top:1px solid var(--border);padding-top:16px}}</style></head><body>{content}</body></html>"""
