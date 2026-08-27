from __future__ import annotations

import re
import textwrap
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any

from .constants import ROUNDTRIP_FORMAT, TYPX_RELATIONSHIP_PREFIXES
from .docx_package import DocxPackage
from .util import gzip_b64, qn, sha256_bytes, sha256_text, ungzip_b64, xml_bytes


TYPST_HEADER_RE = re.compile(
    r"\A/\*\s*typx-roundtrip\s*\n(?P<header>.*?)\n\s*\*/\s*\n?",
    re.DOTALL,
)


@dataclass(slots=True)
class TypstRoundtripPayload:
    format: int
    source_format: str
    body_sha256: str
    payload_sha256: str
    payload: bytes
    metadata: dict[str, str]
    body: str

    @property
    def unchanged(self) -> bool:
        return sha256_text(self.body) == self.body_sha256


def embed_docx_in_typst(body: str, docx_bytes: bytes,
                        metadata: dict[str, str] | None = None,
                        line_width: int = 100) -> str:
    body = body.lstrip("\ufeff")
    payload = gzip_b64(docx_bytes)
    lines = [
        "/* typx-roundtrip",
        f"format: {ROUNDTRIP_FORMAT}",
        "source-format: docx",
        f"body-sha256: {sha256_text(body)}",
        f"payload-sha256: {sha256_bytes(docx_bytes)}",
        "encoding: gzip+base64",
    ]
    for key, value in sorted((metadata or {}).items()):
        safe_key = re.sub(r"[^A-Za-z0-9_.-]+", "-", key)
        safe_value = str(value).replace("\n", " ").replace("\r", " ")
        lines.append(f"meta-{safe_key}: {safe_value}")
    lines.append("payload:")
    lines.extend(textwrap.wrap(payload, line_width))
    lines.append("*/")
    return "\n".join(lines) + "\n" + body


def extract_docx_from_typst(source: str) -> TypstRoundtripPayload | None:
    match = TYPST_HEADER_RE.match(source)
    if not match:
        return None
    header = match.group("header")
    body = source[match.end():]
    values: dict[str, str] = {}
    payload_lines: list[str] = []
    in_payload = False
    for line in header.splitlines():
        stripped = line.strip()
        if stripped == "payload:":
            in_payload = True
            continue
        if in_payload:
            if stripped:
                payload_lines.append(stripped)
            continue
        if ":" in stripped:
            key, value = stripped.split(":", 1)
            values[key.strip().lower()] = value.strip()
    if values.get("encoding") != "gzip+base64":
        return None
    try:
        payload = ungzip_b64("".join(payload_lines))
        format_version = int(values.get("format", "0"))
    except (ValueError, TypeError):
        return None
    expected = values.get("payload-sha256", "")
    if expected and sha256_bytes(payload) != expected:
        raise ValueError("embedded DOCX payload checksum mismatch")
    metadata = {
        key[5:]: value for key, value in values.items() if key.startswith("meta-")
    }
    return TypstRoundtripPayload(
        format=format_version,
        source_format=values.get("source-format", "docx"),
        body_sha256=values.get("body-sha256", ""),
        payload_sha256=expected,
        payload=payload,
        metadata=metadata,
        body=body,
    )


def typx_source_xml(source: str, semantic_docx_sha256: str,
                     source_path: str | None = None,
                     metadata: dict[str, str] | None = None) -> bytes:
    root = ET.Element(qn("typx", "roundtrip"), {
        "format": str(ROUNDTRIP_FORMAT),
        "source-format": "typst",
        "source-sha256": sha256_text(source),
        "document-semantic-sha256": semantic_docx_sha256,
        "encoding": "gzip+base64",
    })
    if source_path:
        root.set("source-path", source_path)
    source_element = ET.SubElement(root, qn("typx", "source"))
    source_element.text = gzip_b64(source.encode("utf-8"))
    if metadata:
        meta = ET.SubElement(root, qn("typx", "metadata"))
        for key, value in sorted(metadata.items()):
            item = ET.SubElement(meta, qn("typx", "item"), {"name": str(key)})
            item.text = str(value)
    return xml_bytes(root)


@dataclass(slots=True)
class EmbeddedTypstSource:
    source: str
    source_sha256: str
    document_semantic_sha256: str
    source_path: str | None
    metadata: dict[str, str]

    def package_unchanged(self, package: DocxPackage) -> bool:
        return package.semantic_digest(exclude_typx=True) == self.document_semantic_sha256


def extract_typst_from_docx(package: DocxPackage) -> EmbeddedTypstSource | None:
    candidates = [
        "customXml/typx-source.xml",
        "customXml/itemTyPx.xml",
    ]
    candidates.extend(name for name in package.parts
                      if name.startswith("customXml/") and name.lower().endswith(".xml")
                      and name not in candidates)
    for name in candidates:
        data = package.get(name)
        if not data or not any(prefix.encode("utf-8") in data for prefix in TYPX_RELATIONSHIP_PREFIXES):
            continue
        try:
            root = ET.fromstring(data)
        except ET.ParseError:
            continue
        if root.tag != qn("typx", "roundtrip"):
            continue
        source_element = root.find(qn("typx", "source"))
        if source_element is None or not source_element.text:
            continue
        try:
            source = ungzip_b64(source_element.text).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            continue
        source_sha = root.get("source-sha256", "")
        if source_sha and sha256_text(source) != source_sha:
            raise ValueError("embedded Typst source checksum mismatch")
        metadata: dict[str, str] = {}
        meta = root.find(qn("typx", "metadata"))
        if meta is not None:
            for item in meta.findall(qn("typx", "item")):
                metadata[item.get("name", "")] = item.text or ""
        return EmbeddedTypstSource(
            source=source,
            source_sha256=source_sha,
            document_semantic_sha256=root.get("document-semantic-sha256", ""),
            source_path=root.get("source-path"),
            metadata=metadata,
        )
    return None


def encode_raw_fragment(data: bytes) -> str:
    return gzip_b64(data)


def decode_raw_fragment(data: str) -> bytes:
    return ungzip_b64(data, max_output=64 * 1024 * 1024)
