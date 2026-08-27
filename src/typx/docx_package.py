from __future__ import annotations

import hashlib
import io
import posixpath
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable
import xml.etree.ElementTree as ET

from .constants import (CONTENT_TYPES, NS, REL_TYPES, STRICT_RELATIONSHIP_PREFIXES,
                        TYPX_RELATIONSHIP_PREFIXES)
from .util import (
    canonical_xml_bytes,
    local_name,
    parse_xml,
    qn,
    rels_part_for,
    resolve_part_target,
    safe_zip_name,
    sha256_bytes,
    xml_bytes,
)


@dataclass(slots=True)
class Relationship:
    id: str
    type: str
    target: str
    target_mode: str | None = None
    source_part: str = ""

    @property
    def external(self) -> bool:
        return (self.target_mode or "").lower() == "external"

    @property
    def resolved_target(self) -> str:
        return self.target if self.external else resolve_part_target(self.source_part, self.target)


@dataclass(slots=True)
class ContentTypeTable:
    defaults: dict[str, str] = field(default_factory=dict)
    overrides: dict[str, str] = field(default_factory=dict)

    @classmethod
    def parse(cls, data: bytes) -> "ContentTypeTable":
        root = parse_xml(data)
        defaults: dict[str, str] = {}
        overrides: dict[str, str] = {}
        for item in root:
            tag = local_name(item.tag)
            if tag == "Default":
                defaults[(item.get("Extension") or "").lower()] = item.get("ContentType", "")
            elif tag == "Override":
                overrides[(item.get("PartName") or "").lstrip("/")] = item.get("ContentType", "")
        return cls(defaults, overrides)

    def for_part(self, name: str) -> str | None:
        name = name.lstrip("/")
        if name in self.overrides:
            return self.overrides[name]
        suffix = posixpath.splitext(name)[1].lstrip(".").lower()
        return self.defaults.get(suffix)


class DocxPackage:
    def __init__(self, parts: dict[str, bytes], content_types: ContentTypeTable | None = None):
        self.parts = {safe_zip_name(name): data for name, data in parts.items()}
        self.content_types = content_types or (
            ContentTypeTable.parse(self.parts["[Content_Types].xml"])
            if "[Content_Types].xml" in self.parts else ContentTypeTable()
        )
        self._rels_cache: dict[str, dict[str, Relationship]] = {}

    @classmethod
    def open(cls, source: str | Path | bytes,
             *, max_parts: int = 20000,
             max_part_size: int = 512 * 1024 * 1024,
             max_total_size: int = 2 * 1024 * 1024 * 1024) -> "DocxPackage":
        if isinstance(source, (str, Path)):
            stream: str | Path | io.BytesIO = source
        else:
            stream = io.BytesIO(source)
        parts: dict[str, bytes] = {}
        total = 0
        with zipfile.ZipFile(stream, "r") as archive:
            infos = archive.infolist()
            if len(infos) > max_parts:
                raise ValueError(f"DOCX has {len(infos)} parts, above safety limit {max_parts}")
            for info in infos:
                if info.is_dir():
                    continue
                name = safe_zip_name(info.filename)
                if info.file_size > max_part_size:
                    raise ValueError(f"part {name!r} exceeds safety limit")
                total += info.file_size
                if total > max_total_size:
                    raise ValueError("DOCX uncompressed size exceeds safety limit")
                parts[name] = archive.read(info)
        if "[Content_Types].xml" not in parts:
            raise ValueError("not a valid OPC package: [Content_Types].xml is missing")
        return cls(parts)

    def get(self, name: str, default: bytes | None = None) -> bytes | None:
        return self.parts.get(safe_zip_name(name), default)

    def require(self, name: str) -> bytes:
        normalized = safe_zip_name(name)
        try:
            return self.parts[normalized]
        except KeyError as exc:
            raise ValueError(f"required DOCX part is missing: /{normalized}") from exc

    def xml(self, name: str) -> ET.Element:
        return parse_xml(self.require(name))

    def relationships(self, source_part: str = "") -> dict[str, Relationship]:
        source_part = safe_zip_name(source_part) if source_part else ""
        if source_part in self._rels_cache:
            return self._rels_cache[source_part]
        rels_name = "_rels/.rels" if not source_part else rels_part_for(source_part)
        data = self.parts.get(rels_name)
        result: dict[str, Relationship] = {}
        if data:
            root = parse_xml(data)
            for element in root:
                if local_name(element.tag) != "Relationship":
                    continue
                rel_type = element.get("Type", "")
                for strict_prefix, transitional_prefix in STRICT_RELATIONSHIP_PREFIXES.items():
                    if rel_type.startswith(strict_prefix):
                        rel_type = transitional_prefix + rel_type[len(strict_prefix):]
                        break
                rel = Relationship(
                    id=element.get("Id", ""),
                    type=rel_type,
                    target=element.get("Target", ""),
                    target_mode=element.get("TargetMode"),
                    source_part=source_part,
                )
                result[rel.id] = rel
        self._rels_cache[source_part] = result
        return result

    def relationship_by_type(self, source_part: str, rel_type: str) -> Relationship | None:
        for rel in self.relationships(source_part).values():
            if rel.type == rel_type:
                return rel
        return None

    def office_document_part(self) -> str:
        rel = self.relationship_by_type("", REL_TYPES["office_document"])
        if rel and not rel.external:
            return rel.resolved_target
        if "word/document.xml" in self.parts:
            return "word/document.xml"
        raise ValueError("package has no officeDocument relationship")

    def list_parts(self, prefix: str = "") -> list[str]:
        prefix = prefix.lstrip("/")
        return sorted(name for name in self.parts if name.startswith(prefix))

    def semantic_digest(self, *, exclude_typx: bool = True) -> str:
        """Digest meaningful package content while ignoring ZIP metadata and volatile properties."""
        digest = hashlib.sha256()
        ignored = {
            "docProps/core.xml",
            "docProps/app.xml",
            "word/settings.xml",  # settings contains volatile compatibility/session values
        }
        for name in sorted(self.parts):
            if name in ignored:
                continue
            if exclude_typx and (name.startswith("customXml/typx-") or name == "customXml/itemTyPx.xml"):
                continue
            if exclude_typx and name.endswith(".rels") and any(prefix.encode("utf-8") in self.parts[name] for prefix in TYPX_RELATIONSHIP_PREFIXES):
                # Keep non-typx relationships by filtering below.
                try:
                    root = parse_xml(self.parts[name])
                    kept = [child for child in list(root)
                            if not any(prefix in child.get("Type", "") for prefix in TYPX_RELATIONSHIP_PREFIXES)]
                    root[:] = kept
                    data = canonical_xml_bytes(root)
                except ET.ParseError:
                    data = self.parts[name]
            elif name.lower().endswith(".xml") or name.lower().endswith(".rels"):
                try:
                    root = parse_xml(self.parts[name])
                    if name == "docProps/core.xml":
                        for child in list(root):
                            if local_name(child.tag) in {"modified", "lastModifiedBy", "revision"}:
                                root.remove(child)
                    if exclude_typx and name == "[Content_Types].xml":
                        root[:] = [
                            item for item in list(root)
                            if not (local_name(item.tag) == "Override" and
                                    (item.get("PartName") or "").lstrip("/").startswith("customXml/typx-"))
                        ]
                    data = canonical_xml_bytes(root)
                except ET.ParseError:
                    data = self.parts[name]
            else:
                data = self.parts[name]
            digest.update(name.encode("utf-8"))
            digest.update(b"\0")
            digest.update(hashlib.sha256(data).digest())
        return digest.hexdigest()


@dataclass(slots=True)
class PackageRelationship:
    source: str
    id: str
    type: str
    target: str
    target_mode: str | None = None


class PackageBuilder:
    def __init__(self):
        self.parts: dict[str, bytes] = {}
        self.default_content_types: dict[str, str] = {
            "rels": "application/vnd.openxmlformats-package.relationships+xml",
            "xml": "application/xml",
        }
        self.override_content_types: dict[str, str] = {}
        self.relationships: dict[str, list[PackageRelationship]] = {}

    def add_part(self, name: str, data: bytes | str | ET.Element,
                 content_type: str | None = None) -> str:
        name = safe_zip_name(name)
        if isinstance(data, ET.Element):
            payload = xml_bytes(data)
        elif isinstance(data, str):
            payload = data.encode("utf-8")
        else:
            payload = data
        self.parts[name] = payload
        if content_type:
            self.override_content_types[name] = content_type
        return name

    def add_default_content_type(self, extension: str, content_type: str) -> None:
        self.default_content_types[extension.lower().lstrip(".")] = content_type

    def add_relationship(self, source: str, rel_type: str, target: str,
                         *, target_mode: str | None = None,
                         rel_id: str | None = None) -> str:
        source = safe_zip_name(source) if source else ""
        items = self.relationships.setdefault(source, [])
        if rel_id is None:
            used = {item.id for item in items}
            index = 1
            while f"rId{index}" in used:
                index += 1
            rel_id = f"rId{index}"
        items.append(PackageRelationship(source, rel_id, rel_type, target, target_mode))
        return rel_id

    def _content_types_xml(self) -> ET.Element:
        # LibreOffice rejects prefixed content-type elements even though XML
        # namespace prefixes are semantically equivalent. Emit the canonical
        # OPC spelling with a default namespace for maximum interoperability.
        root = ET.Element("Types", {"xmlns": NS["ct"]})
        for extension, content_type in sorted(self.default_content_types.items()):
            ET.SubElement(root, "Default", {
                "Extension": extension,
                "ContentType": content_type,
            })
        for name, content_type in sorted(self.override_content_types.items()):
            ET.SubElement(root, "Override", {
                "PartName": "/" + name,
                "ContentType": content_type,
            })
        return root

    def _relationships_xml(self, source: str) -> ET.Element:
        root = ET.Element(qn("rel", "Relationships"))
        for rel in self.relationships.get(source, []):
            attrs = {"Id": rel.id, "Type": rel.type, "Target": rel.target}
            if rel.target_mode:
                attrs["TargetMode"] = rel.target_mode
            ET.SubElement(root, qn("rel", "Relationship"), attrs)
        return root

    def finalize(self) -> dict[str, bytes]:
        output = dict(self.parts)
        output["[Content_Types].xml"] = xml_bytes(self._content_types_xml())
        for source in self.relationships:
            name = "_rels/.rels" if not source else rels_part_for(source)
            output[name] = xml_bytes(self._relationships_xml(source))
        return output

    def save(self, path: str | Path, *, deterministic: bool = True) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        parts = self.finalize()
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for name in sorted(parts):
                data = parts[name]
                if deterministic:
                    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                    info.compress_type = zipfile.ZIP_DEFLATED
                    info.external_attr = 0o600 << 16
                    archive.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
                else:
                    archive.writestr(name, data)
