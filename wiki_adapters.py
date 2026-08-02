"""Whole-site knowledge adapters for Xbox 360 community wikis."""

from __future__ import annotations

import hashlib
import html
import json
import re
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from typing import Iterable
from urllib.parse import quote, urlencode, urlparse

from knowledge_base import EntityRecord, Fact, Identifier
from knowledge_sources import (
    CachedHttpClient,
    ParsedDocument,
    SourceDocument,
    SourceInfo,
)


CONSOLEMODS_WIKI_SOURCE = SourceInfo(
    slug="consolemods-wiki",
    name="ConsoleMods Xbox 360 Wiki",
    homepage_url="https://consolemods.org/wiki/Xbox_360:Main_Page",
    license_name="CC BY 4.0 (unless otherwise noted)",
    license_url="https://consolemods.org/wiki/ConsoleMods:Copyrights",
    notes="Practical Xbox 360 hardware, repair, modding, and software reference.",
)

XENONLIBRARY_SOURCE = SourceInfo(
    slug="xenonlibrary",
    name="XenonLibrary",
    homepage_url="https://xenonlibrary.com/",
    license_name="CC BY-NC-SA 4.0 (unless otherwise noted)",
    license_url="https://xenonlibrary.com/wiki/XenonLibrary:Copyrights",
    notes="Xbox 360 hardware, prototypes, development systems, and part numbers.",
)

FREE60_SOURCE = SourceInfo(
    slug="free60",
    name="Free60 Wiki",
    homepage_url="https://free60.org/",
    license_name="Source-specific; preserve page attribution",
    license_url="https://free60.org/",
    notes="Historical system internals, Linux, homebrew, formats, and development.",
)


class _VisibleTextParser(HTMLParser):
    """Extract readable text while ignoring page chrome scripts and styles."""

    ignored = {"script", "style", "noscript", "svg"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._ignored_depth = 0
        self._title_depth = 0
        self.title = ""
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag in self.ignored:
            self._ignored_depth += 1
        if tag in {"h1", "title"}:
            self._title_depth += 1
        if tag in {"p", "li", "tr", "h1", "h2", "h3", "h4", "br"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.ignored and self._ignored_depth:
            self._ignored_depth -= 1
        if tag in {"h1", "title"} and self._title_depth:
            self._title_depth -= 1
        if tag in {"p", "li", "tr", "h1", "h2", "h3", "h4"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._ignored_depth:
            return
        value = " ".join(data.split())
        if not value:
            return
        if self._title_depth and not self.title:
            self.title = value
        self.parts.append(value)


class SitemapWikiAdapter:
    """Discover wiki pages from XML sitemaps and import searchable article text."""

    source: SourceInfo
    adapter_name: str
    sitemap_urls: tuple[str, ...]
    seed_urls: tuple[str, ...]
    allowed_hosts: tuple[str, ...]
    required_path_fragments: tuple[str, ...] = ()
    api_endpoint = ""
    api_title_prefix = ""
    wiki_base_url = ""

    def __init__(
        self,
        client: CachedHttpClient | None = None,
        max_documents: int | None = None,
        known_urls: Iterable[str] = (),
    ) -> None:
        self.client = client or CachedHttpClient(rate_limit_seconds=1.0)
        self.max_documents = max_documents
        self.known_urls = tuple(known_urls)
        self.errors: list[str] = []

    def fetch_documents(self) -> Iterable[SourceDocument]:
        urls = self._discover_urls()
        if self.max_documents is not None:
            urls = urls[: max(self.max_documents, 0)]
        errors: list[str] = []
        self.errors = errors
        yielded = 0
        for url in urls:
            try:
                document = self.client.get_text(
                    url,
                    title=_title_from_url(url),
                    document_type="wiki_article",
                )
                yielded += 1
                yield document
            except Exception as exc:
                errors.append(f"{url}: {exc}")
                continue
        if errors and not yielded:
            preview = "; ".join(errors[:5])
            if len(errors) > 5:
                preview += f"; and {len(errors) - 5} more"
            raise RuntimeError(preview)

    def parse_document(self, document: SourceDocument) -> ParsedDocument:
        title, body = extract_article_text(document.text, document.title)
        summary = body[:500].rsplit(" ", 1)[0] if len(body) > 500 else body
        warning = ""
        lowered = body.casefold()
        if any(marker in lowered for marker in ("outdated", "historical", "obsolete")):
            warning = "This source page may contain historical or outdated information."

        facts = [
            Fact(
                "article_text",
                body,
                normalized_value=f"sha256:{hashlib.sha256(body.encode('utf-8')).hexdigest()}",
                confidence=0.8,
                source_url=document.url,
                source_title=title,
            ),
            Fact(
                "summary",
                summary,
                confidence=0.8,
                source_url=document.url,
                source_title=title,
            ),
            Fact("source_url", document.url, normalized_value=document.url),
        ]
        if warning:
            facts.append(Fact("freshness_warning", warning, confidence=1.0))

        record = EntityRecord(
            entity_type="knowledge_article",
            canonical_name=title,
            identifiers=(Identifier("url", document.url),),
            facts=tuple(facts),
        )
        return ParsedDocument(document, (record,))

    def _discover_urls(self) -> list[str]:
        discovered: set[str] = {
            url for url in self.seed_urls if self._allowed(url)
        }
        discovered.update(url for url in self.known_urls if self._allowed(url))
        discovered.update(
            url
            for url in self.client.cached_urls(self.allowed_hosts)
            if self._allowed(url)
        )
        discovered.update(self._discover_mediawiki_urls())
        pending = list(self.sitemap_urls)
        visited: set[str] = set()

        while pending:
            sitemap_url = pending.pop(0)
            if sitemap_url in visited:
                continue
            visited.add(sitemap_url)
            try:
                document = self.client.get_text(
                    sitemap_url,
                    title="Sitemap",
                    document_type="sitemap",
                )
            except Exception:
                continue
            page_urls, child_sitemaps = parse_sitemap(document.text)
            pending.extend(url for url in child_sitemaps if url not in visited)
            discovered.update(url for url in page_urls if self._allowed(url))

        return sorted(discovered)

    def _discover_mediawiki_urls(self) -> list[str]:
        if not self.api_endpoint or not self.wiki_base_url:
            return []
        discovered: list[str] = []
        continuation = ""
        while True:
            parameters = {
                "action": "query",
                "list": "allpages",
                "aplimit": "max",
                "apprefix": self.api_title_prefix,
                "format": "json",
                "formatversion": "2",
            }
            if continuation:
                parameters["apcontinue"] = continuation
            url = f"{self.api_endpoint}?{urlencode(parameters)}"
            try:
                document = self.client.get_text(
                    url,
                    title="All pages",
                    document_type="mediawiki_api",
                )
                payload = json.loads(document.text)
            except Exception:
                break
            for page in payload.get("query", {}).get("allpages", ()):
                title = str(page.get("title") or "").strip()
                if not title:
                    continue
                page_url = self.wiki_base_url + quote(
                    title.replace(" ", "_"),
                    safe=":_()-",
                )
                if self._allowed(page_url):
                    discovered.append(page_url)
            continuation = str(
                payload.get("continue", {}).get("apcontinue") or ""
            )
            if not continuation:
                break
        return discovered

    def _allowed(self, url: str) -> bool:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or parsed.netloc not in self.allowed_hosts:
            return False
        if self.required_path_fragments and not any(
            fragment in parsed.path for fragment in self.required_path_fragments
        ):
            return False
        lowered = parsed.path.casefold()
        excluded = (
            "/special:",
            "/file:",
            "/category:",
            "/images/",
            "/assets/",
            "/index.php",
        )
        return not any(value in lowered for value in excluded)


class ConsoleModsWikiAdapter(SitemapWikiAdapter):
    source = CONSOLEMODS_WIKI_SOURCE
    adapter_name = "consolemods_xbox360_wiki"
    sitemap_urls = (
        "https://consolemods.org/sitemap.xml",
        "https://consolemods.org/wiki/sitemap.xml",
    )
    seed_urls = (
        "https://consolemods.org/wiki/Xbox_360:Main_Page",
        "https://consolemods.org/wiki/Xbox_360:Motherboard_Information",
        "https://consolemods.org/wiki/Xbox_360:Buying_Guide",
    )
    allowed_hosts = ("consolemods.org", "www.consolemods.org")
    required_path_fragments = ("/wiki/Xbox_360", "/wiki/Xbox_360%3A")
    api_endpoint = "https://consolemods.org/w/api.php"
    api_title_prefix = "Xbox 360:"
    wiki_base_url = "https://consolemods.org/wiki/"


class XenonLibraryWikiAdapter(SitemapWikiAdapter):
    source = XENONLIBRARY_SOURCE
    adapter_name = "xenonlibrary_wiki"
    sitemap_urls = (
        "https://xenonlibrary.com/sitemap.xml",
        "https://xenonlibrary.com/wiki/sitemap.xml",
    )
    seed_urls = (
        "https://xenonlibrary.com/wiki/Motherboard",
        "https://xenonlibrary.com/wiki/Part_Number_Matrix",
        "https://xenonlibrary.com/wiki/Xenon_(Motherboard)",
        "https://xenonlibrary.com/wiki/Errors",
    )
    allowed_hosts = ("xenonlibrary.com", "www.xenonlibrary.com")
    required_path_fragments = ("/wiki/",)
    api_endpoint = "https://xenonlibrary.com/api.php"
    wiki_base_url = "https://xenonlibrary.com/wiki/"


class Free60WikiAdapter(SitemapWikiAdapter):
    source = FREE60_SOURCE
    adapter_name = "free60_wiki"
    sitemap_urls = ("https://free60.org/sitemap.xml",)
    seed_urls = (
        "https://free60.org/",
        "https://free60.org/Hardware/",
        "https://free60.org/System_Software/",
        "https://free60.org/Formats/",
        "https://free60.org/Homebrew/",
    )
    allowed_hosts = ("free60.org", "www.free60.org")


def parse_sitemap(text: str) -> tuple[list[str], list[str]]:
    """Return page URLs and nested sitemap URLs from a sitemap document."""
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return [], []
    local_name = root.tag.rsplit("}", 1)[-1]
    locations = [
        (node.text or "").strip()
        for node in root.iter()
        if node.tag.rsplit("}", 1)[-1] == "loc" and (node.text or "").strip()
    ]
    if local_name == "sitemapindex":
        return [], locations
    return locations, []


def extract_article_text(raw_html: str, fallback_title: str) -> tuple[str, str]:
    """Extract a stable title and normalized visible body from an HTML page."""
    parser = _VisibleTextParser()
    parser.feed(raw_html)
    parser.close()
    title = html.unescape(parser.title or fallback_title).strip()
    title = re.sub(r"\s+[-|]\s+(XenonLibrary|Free60 Wiki|ConsoleMods Wiki)$", "", title)
    body = "\n".join(
        line.strip()
        for line in re.sub(r"[ \t]+", " ", "".join(parser.parts)).splitlines()
        if line.strip()
    )
    return title or fallback_title, body


def _title_from_url(url: str) -> str:
    path = urlparse(url).path.rstrip("/")
    value = path.rsplit("/", 1)[-1] or urlparse(url).netloc
    return html.unescape(value.replace("_", " ").replace("%3A", ":"))
