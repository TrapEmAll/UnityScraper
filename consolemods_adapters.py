"""ConsoleMods source adapters for Xbox 360 game metadata."""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from typing import Iterable

from knowledge_base import EntityRecord, Fact, Identifier, normalize_titleid
from knowledge_sources import (
    CachedHttpClient,
    ParsedDocument,
    SourceDocument,
    SourceInfo,
    mediawiki_raw_url,
)

CONSOLEMODS_SOURCE = SourceInfo(
    slug="consolemods",
    name="ConsoleMods Wiki",
    homepage_url="https://consolemods.org/wiki/Main_Page",
    license_name="Creative Commons Attribution unless otherwise noted",
    license_url="https://consolemods.org/wiki/ConsoleMods:Copyrights",
    notes=(
        "Imported records preserve source URLs and should be treated as "
        "community-maintained reference data, not authoritative platform data."
    ),
)

TITLE_ID_URL = "https://consolemods.org/wiki/Xbox_360:List_of_Every_Xbox_360_Title_ID"
MULTI_ID_URL = "https://consolemods.org/wiki/Xbox_360:List_of_Multi-ID_Games"

_TAG_RE = re.compile(r"<[^>]+>")
_SPACE_RE = re.compile(r"\s+")
_TITLE_ID_RE = re.compile(r"\b[0-9A-Fa-f]{8}\b")
_PUBLISHER_HEADING_RE = re.compile(
    r"^(?:#+\s*)?(?:=+\s*)?(?P<code>[A-Za-z0-9]{2})\s*"
    r"\((?P<prefix>[0-9A-Fa-f]{4})\)\s*(?:-->|→)\s*(?P<publisher>.+)$"
)
_TITLE_HEADING_RE = re.compile(
    r"^(?:#+\s*)?(?:=+\s*)?(?P<short_code>[A-Za-z0-9]{2}-\d{4})\s*"
    r"\((?P<titleid>[0-9A-Fa-f]{8})\)"
)
_MULTI_HEADING_RE = re.compile(r"^(?:#+\s*)?(?:=+\s*)?(?P<title>[^#=].+?)(?:\s*=+)?$")
_MULTI_ROW_RE = re.compile(
    r"^(?P<short_code>[A-Za-z0-9]{2}-\d{4})\s*(?:-->|→)\s*(?P<title>.+)$"
)
_REGION_RE = re.compile(r"(?:\((?P<paren>[^()]*)\)|\[(?P<bracket>[^\[\]]*)\])\s*$")


@dataclass(frozen=True)
class ParsedTitle:
    """Internal representation extracted from ConsoleMods lists."""

    titleid: str
    short_code: str
    title: str
    publisher: str = ""
    publisher_prefix: str = ""
    aliases: tuple[str, ...] = ()
    region: str = ""
    notes: str = ""


class ConsoleModsTitleIdAdapter:
    """Import the ConsoleMods list of every physical Xbox 360 TitleID."""

    source = CONSOLEMODS_SOURCE
    adapter_name = "consolemods_title_ids"

    def __init__(self, client: CachedHttpClient | None = None) -> None:
        self.client = client or CachedHttpClient()

    def fetch_documents(self) -> Iterable[SourceDocument]:
        yield self.client.get_text(
            TITLE_ID_URL,
            "Xbox 360:List of Every Xbox 360 Title ID",
            "consolemods_title_id_list",
            fallback_urls=(
                mediawiki_raw_url("Xbox_360:List_of_Every_Xbox_360_Title_ID"),
            ),
        )

    def parse_document(self, document: SourceDocument) -> ParsedDocument:
        records = tuple(
            _record_from_title(parsed, document.url, document.title, confidence=0.95)
            for parsed in parse_title_id_document(document.text)
        )
        return ParsedDocument(document, records)


class ConsoleModsMultiIdAdapter:
    """Import ConsoleMods relationships for games with multiple TitleIDs."""

    source = CONSOLEMODS_SOURCE
    adapter_name = "consolemods_multi_id_games"

    def __init__(self, client: CachedHttpClient | None = None) -> None:
        self.client = client or CachedHttpClient()

    def fetch_documents(self) -> Iterable[SourceDocument]:
        yield self.client.get_text(
            MULTI_ID_URL,
            "Xbox 360:List of Multi-ID Games",
            "consolemods_multi_id_list",
            fallback_urls=(
                mediawiki_raw_url("Xbox_360:List_of_Multi-ID_Games"),
            ),
        )

    def parse_document(self, document: SourceDocument) -> ParsedDocument:
        records = tuple(
            _record_from_title(parsed, document.url, document.title, confidence=0.9)
            for parsed in parse_multi_id_document(document.text)
        )
        return ParsedDocument(document, records)


def parse_title_id_document(text: str) -> list[ParsedTitle]:
    """Parse publisher, TitleID, title, and basic region data."""
    lines = _document_lines(text)
    parsed: list[ParsedTitle] = []
    publisher = ""
    publisher_prefix = ""
    index = 0

    while index < len(lines):
        line = lines[index]
        publisher_match = _PUBLISHER_HEADING_RE.match(line)
        if publisher_match:
            publisher = _clean_text(publisher_match.group("publisher"))
            publisher_prefix = publisher_match.group("prefix").upper()
            index += 1
            continue

        title_match = _TITLE_HEADING_RE.match(line)
        if title_match:
            titleid = title_match.group("titleid").upper()
            short_code = title_match.group("short_code").upper()
            titles: list[str] = []
            index += 1
            while index < len(lines):
                next_line = lines[index]
                if _PUBLISHER_HEADING_RE.match(next_line) or _TITLE_HEADING_RE.match(next_line):
                    break
                if next_line and not next_line.lower().startswith("note"):
                    titles.append(_clean_text(next_line))
                index += 1
            canonical = titles[0] if titles else titleid
            region = _extract_region(canonical)
            parsed.append(
                ParsedTitle(
                    titleid=titleid,
                    short_code=short_code,
                    title=_strip_region(canonical),
                    publisher=publisher,
                    publisher_prefix=publisher_prefix,
                    aliases=tuple(_strip_region(item) for item in titles[1:]),
                    region=region,
                )
            )
            continue
        index += 1

    return parsed


def parse_multi_id_document(text: str) -> list[ParsedTitle]:
    """Parse multi-ID groups and variant TitleIDs from ConsoleMods."""
    lines = _document_lines(text)
    parsed: list[ParsedTitle] = []
    current_note = ""
    pending: list[ParsedTitle] = []

    def flush_group() -> None:
        if not pending:
            return
        related = tuple(item.titleid for item in pending)
        for item in pending:
            aliases = tuple(other for other in related if other != item.titleid)
            parsed.append(
                ParsedTitle(
                    titleid=item.titleid,
                    short_code=item.short_code,
                    title=item.title,
                    aliases=aliases,
                    region=item.region,
                    notes=current_note,
                )
            )

    for line in lines:
        row_match = _MULTI_ROW_RE.match(line)
        if row_match:
            short_code = row_match.group("short_code").upper()
            titleid = short_code_to_titleid(short_code)
            if not titleid:
                continue
            title_text = _clean_text(row_match.group("title"))
            pending.append(
                ParsedTitle(
                    titleid=titleid,
                    short_code=short_code,
                    title=_strip_region(title_text),
                    region=_extract_region(title_text),
                )
            )
            continue

        if line.lower().startswith("note"):
            current_note = _clean_text(line)
            continue

        if _looks_like_multi_heading(line):
            flush_group()
            current_note = ""
            pending = []
            continue

    flush_group()
    return parsed


def short_code_to_titleid(short_code: str) -> str:
    """Convert a human-readable TitleID code like ``US-2245`` to hex."""
    match = re.fullmatch(r"([A-Za-z0-9]{2})-(\d{4})", short_code.strip())
    if not match:
        return ""
    prefix, number = match.groups()
    try:
        publisher_hex = "".join(f"{ord(char):02X}" for char in prefix.upper())
        number_hex = f"{int(number):04X}"
    except ValueError:
        return ""
    return normalize_titleid(publisher_hex + number_hex)


def _record_from_title(
    parsed: ParsedTitle,
    source_url: str,
    source_title: str,
    confidence: float,
) -> EntityRecord:
    facts = [
        Fact(
            "title",
            parsed.title,
            confidence=confidence,
            source_url=source_url,
            source_title=source_title,
            context={"short_code": parsed.short_code},
        )
    ]
    if parsed.publisher:
        facts.append(
            Fact(
                "publisher",
                parsed.publisher,
                confidence=confidence,
                source_url=source_url,
                source_title=source_title,
                context={"publisher_prefix": parsed.publisher_prefix},
            )
        )
    if parsed.publisher_prefix:
        facts.append(
            Fact(
                "publisher_prefix",
                parsed.publisher_prefix,
                normalized_value=parsed.publisher_prefix,
                confidence=confidence,
                source_url=source_url,
                source_title=source_title,
            )
        )
    if parsed.region:
        facts.append(
            Fact(
                "region",
                parsed.region,
                confidence=confidence,
                source_url=source_url,
                source_title=source_title,
            )
        )
    if parsed.notes:
        facts.append(
            Fact(
                "source_note",
                parsed.notes,
                confidence=confidence,
                source_url=source_url,
                source_title=source_title,
            )
        )
    for related in parsed.aliases:
        property_name = "related_titleid" if normalize_titleid(related) else "alternate_title"
        facts.append(
            Fact(
                property_name,
                related,
                normalized_value=normalize_titleid(related) or "",
                confidence=confidence,
                source_url=source_url,
                source_title=source_title,
            )
        )

    return EntityRecord(
        entity_type="game",
        canonical_name=parsed.title or parsed.titleid,
        identifiers=(
            Identifier("titleid", parsed.titleid, confidence=confidence),
            Identifier("title_code", parsed.short_code, confidence=confidence),
        ),
        names=(parsed.title, *tuple(item for item in parsed.aliases if not normalize_titleid(item))),
        facts=tuple(facts),
    )


def _document_lines(text: str) -> list[str]:
    if "<" in text and ">" in text:
        text = re.sub(r"</h([1-6])>", "\n", text, flags=re.I)
        text = re.sub(r"<h([1-6])[^>]*>", lambda match: "\n" + "#" * int(match.group(1)) + " ", text, flags=re.I)
        text = re.sub(r"</(?:p|li|tr|td|div)>", "\n", text, flags=re.I)
        text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
        text = _TAG_RE.sub(" ", text)
    text = html.unescape(text)
    return [
        _clean_text(_strip_wiki_heading(line))
        for line in text.splitlines()
        if _clean_text(_strip_wiki_heading(line))
    ]


def _clean_text(value: str) -> str:
    value = html.unescape(value or "")
    return _SPACE_RE.sub(" ", value).strip(" \t\r\n-–—:|")


def _extract_region(value: str) -> str:
    match = _REGION_RE.search(value or "")
    if not match:
        return ""
    return _clean_text(match.group("paren") or match.group("bracket") or "")


def _strip_region(value: str) -> str:
    return _clean_text(_REGION_RE.sub("", value or ""))


def _looks_like_multi_heading(line: str) -> bool:
    if not line or _MULTI_ROW_RE.match(line):
        return False
    if line.lower().startswith(("note", "list of", "contents", "from consolemods")):
        return False
    if _TITLE_ID_RE.search(line):
        return False
    return line.startswith("#") or line.startswith("=") or len(line) < 120


def _strip_wiki_heading(value: str) -> str:
    return re.sub(r"^\s*=+\s*(.*?)\s*=+\s*$", r"\1", value or "")
