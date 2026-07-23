"""Local Redump and No-Intro XML DAT adapters."""

from __future__ import annotations

import hashlib
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Iterable

from knowledge_base import EntityRecord, Fact, Identifier, utc_now
from knowledge_sources import ParsedDocument, SourceDocument, SourceInfo


REDUMP_SOURCE = SourceInfo(
    slug="redump",
    name="Redump",
    homepage_url="http://redump.org/",
    license_name="Metadata terms set by Redump",
    license_url="http://redump.org/",
    notes="Physical-disc identity and verification metadata. No disc images are imported.",
)

NOINTRO_SOURCE = SourceInfo(
    slug="no-intro",
    name="No-Intro DAT-o-MATIC",
    homepage_url="https://datomatic.no-intro.org/",
    license_name="Metadata terms set by No-Intro",
    license_url="https://datomatic.no-intro.org/",
    notes="Digital/package identity and verification metadata. No content files are imported.",
)


class LocalDatAdapter:
    """Parse a user-supplied Logiqx-style XML DAT file."""

    def __init__(self, path: Path | str, source_kind: str) -> None:
        self.path = Path(path)
        source_key = source_kind.strip().casefold()
        if source_key == "redump":
            self.source = REDUMP_SOURCE
            self.entity_type = "disc_release"
        elif source_key in {"no-intro", "nointro"}:
            self.source = NOINTRO_SOURCE
            self.entity_type = "digital_release"
        else:
            raise ValueError("DAT source must be 'redump' or 'no-intro'")
        self.adapter_name = f"{self.source.slug}_local_dat"

    def fetch_documents(self) -> Iterable[SourceDocument]:
        if not self.path.is_file():
            raise FileNotFoundError(self.path)
        raw = self.path.read_bytes()
        text = raw.decode("utf-8-sig", errors="replace")
        yield SourceDocument(
            url=self.path.resolve().as_uri(),
            title=self.path.name,
            document_type="logiqx_dat",
            text=text,
            fetched_at=utc_now(),
            content_sha256=hashlib.sha256(raw).hexdigest(),
            cache_path=self.path.resolve(),
            http_status=0,
        )

    def parse_document(self, document: SourceDocument) -> ParsedDocument:
        return ParsedDocument(document, tuple(parse_dat(document.text, self.entity_type)))


def parse_dat(text: str, entity_type: str) -> list[EntityRecord]:
    """Parse common Redump/No-Intro XML DAT variants into release entities."""
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise ValueError(f"Invalid XML DAT: {exc}") from exc

    header = root.find("header")
    set_name = _child_text(header, "name") or _child_text(header, "description")
    records: list[EntityRecord] = []

    for game in (*root.findall("game"), *root.findall("machine")):
        game_name = (game.get("name") or _child_text(game, "description")).strip()
        if not game_name:
            continue
        identifiers: list[Identifier] = []
        facts: list[Fact] = []

        for property_name, xml_name in (
            ("description", "description"),
            ("category", "category"),
            ("region", "region"),
            ("languages", "languages"),
            ("version", "version"),
            ("serial", "serial"),
        ):
            value = _child_text(game, xml_name)
            if value:
                facts.append(Fact(property_name, value))
                if property_name == "serial":
                    identifiers.append(Identifier("serial", value))

        if set_name:
            facts.append(Fact("dat_set", set_name))

        file_nodes = [*game.findall("rom"), *game.findall("disk")]
        for file_node in file_nodes:
            file_name = (file_node.get("name") or "").strip()
            if file_name:
                facts.append(Fact("file_name", file_name))
            for attribute, identifier_type in (
                ("crc", "crc32"),
                ("md5", "md5"),
                ("sha1", "sha1"),
                ("sha256", "sha256"),
                ("serial", "serial"),
            ):
                value = (file_node.get(attribute) or "").strip()
                if value:
                    identifiers.append(Identifier(identifier_type, value))
            for attribute in ("size", "status"):
                value = (file_node.get(attribute) or "").strip()
                if value:
                    facts.append(Fact(f"file_{attribute}", value))

        identifiers = list(dict.fromkeys(identifiers))
        unique_facts: list[Fact] = []
        seen_facts: set[tuple[str, str]] = set()
        for fact in facts:
            key = (fact.property, fact.value)
            if key not in seen_facts:
                seen_facts.add(key)
                unique_facts.append(fact)
        records.append(
            EntityRecord(
                entity_type=entity_type,
                canonical_name=game_name,
                identifiers=tuple(identifiers),
                facts=tuple(unique_facts),
            )
        )
    return records


def _child_text(node: ET.Element | None, name: str) -> str:
    if node is None:
        return ""
    child = node.find(name)
    return (child.text or "").strip() if child is not None else ""
