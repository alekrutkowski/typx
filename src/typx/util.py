from __future__ import annotations

import base64
import binascii
import gzip
import hashlib
import html
import io
import json
import math
import mimetypes
import os
import posixpath
import re
import struct
import xml.etree.ElementTree as ET
from copy import deepcopy
from pathlib import Path
from typing import Any, Iterable, Iterator

from .constants import (
    EMU_PER_INCH, EXT_BY_MIME, MIME_BY_EXT, NS, POINTS_PER_INCH,
    STRICT_TO_TRANSITIONAL_NS, TWIPS_PER_INCH,
)
from .model import Break, Field, Inline, Link, MathInline, RawInline, Text


def qn(prefix: str, local: str) -> str:
    return f"{{{NS[prefix]}}}{local}"


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag.split(":")[-1]


def namespace_uri(tag: str) -> str | None:
    return tag[1:].split("}", 1)[0] if tag.startswith("{") else None


def attr(element: ET.Element | None, name: str, default: Any = None,
         prefix: str = "w") -> Any:
    if element is None:
        return default
    return element.get(qn(prefix, name), element.get(name, default))


def bool_attr(element: ET.Element | None, name: str = "val", default: bool | None = None,
              prefix: str = "w") -> bool | None:
    if element is None:
        return default
    value = attr(element, name, None, prefix)
    if value is None:
        return True
    return str(value).strip().lower() not in {"0", "false", "off", "no", "none"}


def child(element: ET.Element | None, tag: str, prefix: str = "w") -> ET.Element | None:
    return None if element is None else element.find(qn(prefix, tag))


def children(element: ET.Element | None, tag: str, prefix: str = "w") -> list[ET.Element]:
    return [] if element is None else list(element.findall(qn(prefix, tag)))


def parse_xml(data: bytes | str) -> ET.Element:
    if isinstance(data, str):
        data = data.encode("utf-8")
    if b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
        raise ValueError("DTD/entity declarations are not accepted in OOXML parts")
    root = ET.fromstring(data)
    _normalize_strict_ooxml_namespaces(root)
    return root


def _normalize_strict_ooxml_namespaces(root: ET.Element) -> None:
    """Normalize ISO/IEC 29500 Strict names to the equivalent reader vocabulary."""
    for element in root.iter():
        if element.tag.startswith("{"):
            uri, local = element.tag[1:].split("}", 1)
            mapped = STRICT_TO_TRANSITIONAL_NS.get(uri)
            if mapped:
                element.tag = f"{{{mapped}}}{local}"
        if element.attrib:
            normalized: dict[str, str] = {}
            changed = False
            for key, value in element.attrib.items():
                new_key = key
                if key.startswith("{"):
                    uri, local = key[1:].split("}", 1)
                    mapped = STRICT_TO_TRANSITIONAL_NS.get(uri)
                    if mapped:
                        new_key = f"{{{mapped}}}{local}"
                        changed = True
                normalized[new_key] = value
            if changed:
                element.attrib.clear()
                element.attrib.update(normalized)


def clone_element(element: ET.Element) -> ET.Element:
    return deepcopy(element)


def xml_bytes(element: ET.Element, declaration: bool = True) -> bytes:
    return ET.tostring(element, encoding="utf-8", xml_declaration=declaration,
                       short_empty_elements=True)


def canonical_xml_bytes(element: ET.Element) -> bytes:
    try:
        text = ET.canonicalize(ET.tostring(element, encoding="unicode"), strip_text=False)
        return text.encode("utf-8")
    except (AttributeError, TypeError):
        return ET.tostring(element, encoding="utf-8")


def sanitize_filename(name: str, fallback: str = "asset") -> str:
    name = name.replace("\\", "/").rsplit("/", 1)[-1]
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip(".-")
    if not name:
        name = fallback
    stem, suffix = os.path.splitext(name)
    stem = stem[:80] or fallback
    suffix = suffix[:16]
    return stem + suffix


def safe_zip_name(name: str) -> str:
    normalized = posixpath.normpath(name.replace("\\", "/")).lstrip("/")
    if normalized.startswith("../") or normalized == "..":
        raise ValueError(f"unsafe package path: {name}")
    return normalized


def resolve_part_target(source_part: str, target: str) -> str:
    target = target.replace("\\", "/")
    if target.startswith("/"):
        return safe_zip_name(target)
    return safe_zip_name(posixpath.join(posixpath.dirname(source_part), target))


def rels_part_for(source_part: str) -> str:
    directory, filename = posixpath.split(source_part)
    return posixpath.join(directory, "_rels", filename + ".rels") if directory else f"_rels/{filename}.rels"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def gzip_b64(data: bytes) -> str:
    return base64.b64encode(gzip.compress(data, compresslevel=9, mtime=0)).decode("ascii")


def ungzip_b64(text: str, max_output: int = 512 * 1024 * 1024) -> bytes:
    raw = base64.b64decode(re.sub(r"\s+", "", text), validate=True)
    with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:
        out = stream.read(max_output + 1)
    if len(out) > max_output:
        raise ValueError("embedded payload exceeds configured safety limit")
    return out


def json_b64(value: Any) -> str:
    return gzip_b64(json.dumps(value, ensure_ascii=False, sort_keys=True,
                               separators=(",", ":")).encode("utf-8"))


def unjson_b64(text: str) -> Any:
    return json.loads(ungzip_b64(text).decode("utf-8"))


def points_to_twips(points: float | int | None) -> int | None:
    return None if points is None else int(round(float(points) * 20.0))


def twips_to_points(twips: str | int | float | None) -> float | None:
    try:
        return float(twips) / 20.0 if twips is not None else None
    except (TypeError, ValueError):
        return None


def half_points_to_points(value: str | int | float | None) -> float | None:
    try:
        return float(value) / 2.0 if value is not None else None
    except (TypeError, ValueError):
        return None


def points_to_half_points(value: float | None) -> int | None:
    return None if value is None else int(round(value * 2.0))


def emu_to_points(value: str | int | float | None) -> float | None:
    try:
        return float(value) * POINTS_PER_INCH / EMU_PER_INCH if value is not None else None
    except (TypeError, ValueError):
        return None


def points_to_emu(value: float | None) -> int | None:
    return None if value is None else int(round(value * EMU_PER_INCH / POINTS_PER_INCH))


_LENGTH_RE = re.compile(
    r"^\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)\s*"
    r"(pt|mm|cm|in|em|fr|%|deg|rad)?\s*$"
)


def parse_typst_length(value: str | int | float | None,
                       em_size_pt: float = 11.0,
                       percent_base_pt: float | None = None) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = _LENGTH_RE.match(str(value))
    if not match:
        return None
    number = float(match.group(1))
    unit = match.group(2) or "pt"
    if unit == "pt":
        return number
    if unit == "in":
        return number * 72.0
    if unit == "cm":
        return number * 72.0 / 2.54
    if unit == "mm":
        return number * 72.0 / 25.4
    if unit == "em":
        return number * em_size_pt
    if unit == "%" and percent_base_pt is not None:
        return number * percent_base_pt / 100.0
    return None


def format_typst_length(points: float | None, digits: int = 3) -> str:
    if points is None:
        return "auto"
    rounded = round(points, digits)
    if float(rounded).is_integer():
        return f"{int(rounded)}pt"
    return f"{rounded:g}pt"


def normalize_hex_color(value: str | None, default: str | None = None) -> str | None:
    if value is None:
        return default
    value = value.strip().lstrip("#")
    named = {
        "black": "000000", "white": "FFFFFF", "red": "FF0000",
        "green": "008000", "blue": "0000FF", "yellow": "FFFF00",
        "gray": "808080", "grey": "808080", "silver": "C0C0C0",
        "maroon": "800000", "purple": "800080", "fuchsia": "FF00FF",
        "lime": "00FF00", "olive": "808000", "navy": "000080",
        "teal": "008080", "aqua": "00FFFF", "orange": "FFA500",
        "transparent": "transparent", "auto": "auto",
    }
    if value.lower() in named:
        return named[value.lower()]
    if re.fullmatch(r"[0-9A-Fa-f]{3}", value):
        value = "".join(ch * 2 for ch in value)
    if re.fullmatch(r"[0-9A-Fa-f]{6}", value):
        return value.upper()
    if re.fullmatch(r"[0-9A-Fa-f]{8}", value):
        return value.upper()
    return default


def typst_color(value: str | None) -> str:
    if not value or value in {"auto", "transparent"}:
        return value or "black"
    normalized = normalize_hex_color(value, value)
    if normalized and re.fullmatch(r"[0-9A-F]{6}(?:[0-9A-F]{2})?", normalized):
        return f'rgb("#{normalized}")'
    return str(value)


def ooxml_highlight_to_hex(name: str | None) -> str | None:
    table = {
        "black": "000000", "blue": "0000FF", "cyan": "00FFFF",
        "green": "00FF00", "magenta": "FF00FF", "red": "FF0000",
        "yellow": "FFFF00", "white": "FFFFFF", "darkBlue": "000080",
        "darkCyan": "008080", "darkGreen": "008000", "darkMagenta": "800080",
        "darkRed": "800000", "darkYellow": "808000", "darkGray": "808080",
        "lightGray": "C0C0C0", "none": None,
    }
    return table.get(name or "")


def hex_to_ooxml_highlight(value: str | None) -> str | None:
    if not value:
        return None
    normalized = normalize_hex_color(value)
    reverse = {
        "000000": "black", "0000FF": "blue", "00FFFF": "cyan",
        "00FF00": "green", "FF00FF": "magenta", "FF0000": "red",
        "FFFF00": "yellow", "FFFFFF": "white", "000080": "darkBlue",
        "008080": "darkCyan", "008000": "darkGreen", "800080": "darkMagenta",
        "800000": "darkRed", "808000": "darkYellow", "808080": "darkGray",
        "C0C0C0": "lightGray",
    }
    return reverse.get(normalized or "")


def escape_typst_text(text: str) -> str:
    replacements = {
        "\\": "\\\\", "#": "\\#", "*": "\\*", "_": "\\_",
        "`": "\\`", "$": "\\$", "@": "\\@", "<": "\\<", ">": "\\>",
        "[": "\\[", "]": "\\]",
    }
    return "".join(replacements.get(ch, ch) for ch in text)


def escape_typst_string(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )


def unescape_typst_string(text: str) -> str:
    try:
        return json.loads('"' + text.replace('"', '\\"') + '"')
    except json.JSONDecodeError:
        return re.sub(r"\\(.)", r"\1", text)


def quote_typst_string(text: str) -> str:
    return f'"{escape_typst_string(text)}"'


def text_from_inlines(inlines: Iterable[Inline]) -> str:
    chunks: list[str] = []
    for inline in inlines:
        if isinstance(inline, Text):
            chunks.append(inline.text)
        elif isinstance(inline, Break):
            chunks.append("\t" if inline.break_type == "tab" else "\n")
        elif isinstance(inline, Link):
            chunks.append(text_from_inlines(inline.children))
        elif isinstance(inline, Field):
            chunks.append(text_from_inlines(inline.children))
        elif isinstance(inline, MathInline):
            chunks.append(inline.fallback_text or inline.typst)
        elif isinstance(inline, RawInline):
            chunks.append(text_from_inlines(inline.fallback))
        elif hasattr(inline, "children"):
            chunks.append(text_from_inlines(getattr(inline, "children")))
    return "".join(chunks)


def coalesce_text(inlines: Iterable[Inline]) -> list[Inline]:
    out: list[Inline] = []
    for inline in inlines:
        if isinstance(inline, Text) and inline.text:
            if out and isinstance(out[-1], Text) and out[-1].style == inline.style:
                out[-1].text += inline.text
            else:
                out.append(inline)
        else:
            out.append(inline)
    return out


def guess_media_type(filename: str, data: bytes | None = None) -> str:
    ext = Path(filename).suffix.lower()
    if ext in MIME_BY_EXT:
        return MIME_BY_EXT[ext]
    guessed = mimetypes.guess_type(filename)[0]
    if guessed:
        return guessed
    if data:
        if data.startswith(b"\x89PNG\r\n\x1a\n"):
            return "image/png"
        if data.startswith(b"\xff\xd8"):
            return "image/jpeg"
        if data.startswith((b"GIF87a", b"GIF89a")):
            return "image/gif"
        if data.startswith(b"BM"):
            return "image/bmp"
        if data[:5].lower() == b"<?xml" or b"<svg" in data[:512].lower():
            return "image/svg+xml"
    return "application/octet-stream"


def extension_for_media_type(media_type: str, fallback: str = ".bin") -> str:
    return EXT_BY_MIME.get(media_type, mimetypes.guess_extension(media_type) or fallback)


def image_dimensions(data: bytes, media_type: str | None = None) -> tuple[int | None, int | None, float | None, float | None]:
    """Return pixel width, pixel height, dpi x, dpi y using only the stdlib."""
    media_type = media_type or guess_media_type("", data)
    try:
        if media_type == "image/png" and data.startswith(b"\x89PNG"):
            width, height = struct.unpack(">II", data[16:24])
            dpi_x = dpi_y = 96.0
            offset = 8
            while offset + 12 <= len(data):
                length = struct.unpack(">I", data[offset:offset + 4])[0]
                ctype = data[offset + 4:offset + 8]
                payload = data[offset + 8:offset + 8 + length]
                if ctype == b"pHYs" and len(payload) >= 9:
                    xppm, yppm, unit = struct.unpack(">IIB", payload[:9])
                    if unit == 1:
                        dpi_x, dpi_y = xppm * 0.0254, yppm * 0.0254
                    break
                offset += 12 + length
            return width, height, dpi_x, dpi_y
        if media_type == "image/gif" and data.startswith((b"GIF87a", b"GIF89a")):
            width, height = struct.unpack("<HH", data[6:10])
            return width, height, 96.0, 96.0
        if media_type == "image/bmp" and data.startswith(b"BM"):
            width, height = struct.unpack("<ii", data[18:26])
            ppm_x, ppm_y = struct.unpack("<ii", data[38:46])
            dpi_x = ppm_x * 0.0254 if ppm_x else 96.0
            dpi_y = ppm_y * 0.0254 if ppm_y else 96.0
            return abs(width), abs(height), dpi_x, dpi_y
        if media_type == "image/jpeg" and data.startswith(b"\xff\xd8"):
            stream = io.BytesIO(data)
            stream.read(2)
            dpi_x = dpi_y = 96.0
            while True:
                marker_start = stream.read(1)
                if not marker_start:
                    break
                if marker_start != b"\xff":
                    continue
                marker = stream.read(1)
                while marker == b"\xff":
                    marker = stream.read(1)
                if marker in {b"\xd8", b"\xd9"}:
                    continue
                length_raw = stream.read(2)
                if len(length_raw) != 2:
                    break
                length = struct.unpack(">H", length_raw)[0]
                payload = stream.read(max(0, length - 2))
                if marker == b"\xe0" and payload.startswith(b"JFIF\x00") and len(payload) >= 14:
                    unit = payload[7]
                    xden, yden = struct.unpack(">HH", payload[8:12])
                    if unit == 1:
                        dpi_x, dpi_y = float(xden or 96), float(yden or 96)
                    elif unit == 2:
                        dpi_x, dpi_y = (xden or 38) * 2.54, (yden or 38) * 2.54
                if marker[0] in {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF} and len(payload) >= 5:
                    height, width = struct.unpack(">HH", payload[1:5])
                    return width, height, dpi_x, dpi_y
        if media_type == "image/svg+xml":
            text = data.decode("utf-8", "replace")
            root = parse_xml(text)
            width = parse_svg_dimension(root.get("width"))
            height = parse_svg_dimension(root.get("height"))
            if (width is None or height is None) and root.get("viewBox"):
                parts = re.split(r"[ ,]+", root.get("viewBox", "").strip())
                if len(parts) == 4:
                    width = width or float(parts[2])
                    height = height or float(parts[3])
            return int(width) if width else None, int(height) if height else None, 96.0, 96.0
    except (ValueError, struct.error, ET.ParseError, OSError):
        pass
    return None, None, None, None


def parse_svg_dimension(value: str | None) -> float | None:
    if not value:
        return None
    match = re.match(r"\s*([0-9.]+)\s*(px|pt|cm|mm|in)?", value)
    if not match:
        return None
    number = float(match.group(1))
    unit = match.group(2) or "px"
    return {
        "px": number,
        "pt": number * 96.0 / 72.0,
        "in": number * 96.0,
        "cm": number * 96.0 / 2.54,
        "mm": number * 96.0 / 25.4,
    }[unit]


def dimensions_points(data: bytes, media_type: str | None = None) -> tuple[float | None, float | None]:
    width, height, dpi_x, dpi_y = image_dimensions(data, media_type)
    if width is None or height is None:
        return None, None
    return width * 72.0 / (dpi_x or 96.0), height * 72.0 / (dpi_y or 96.0)


def iter_element_text(element: ET.Element) -> Iterator[str]:
    if element.text:
        yield element.text
    for item in element:
        yield from iter_element_text(item)
        if item.tail:
            yield item.tail


def xml_escape(text: str) -> str:
    return html.escape(text, quote=True)


def clamp(value: float, low: float, high: float) -> float:
    return min(high, max(low, value))


def parse_int(value: Any, default: int | None = None) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def parse_float(value: Any, default: float | None = None) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def split_top_level(text: str, delimiter: str = ",") -> list[str]:
    parts: list[str] = []
    start = 0
    stack: list[str] = []
    quote: str | None = None
    escaped = False
    i = 0
    pairs = {")": "(", "]": "[", "}": "{"}
    while i < len(text):
        ch = text[i]
        if quote:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == quote:
                quote = None
        else:
            if ch == '"':
                quote = ch
            elif text.startswith("//", i):
                end = text.find("\n", i + 2)
                i = len(text) if end < 0 else end
                continue
            elif text.startswith("/*", i):
                end = text.find("*/", i + 2)
                i = len(text) if end < 0 else end + 1
            elif ch in "([{":
                stack.append(ch)
            elif ch in ")]}" and stack and stack[-1] == pairs[ch]:
                stack.pop()
            elif not stack and text.startswith(delimiter, i):
                parts.append(text[start:i].strip())
                start = i + len(delimiter)
                i += len(delimiter) - 1
        i += 1
    parts.append(text[start:].strip())
    return parts


def find_balanced(text: str, start: int, open_char: str, close_char: str) -> int:
    if start >= len(text) or text[start] != open_char:
        return -1
    depth = 0
    quote: str | None = None
    escaped = False
    i = start
    while i < len(text):
        ch = text[i]
        if quote:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == quote:
                quote = None
        else:
            if ch == '"':
                quote = ch
            elif text.startswith("//", i):
                end = text.find("\n", i + 2)
                if end < 0:
                    return -1
                i = end
            elif text.startswith("/*", i):
                end = text.find("*/", i + 2)
                if end < 0:
                    return -1
                i = end + 1
            elif ch == open_char:
                depth += 1
            elif ch == close_char:
                depth -= 1
                if depth == 0:
                    return i
        i += 1
    return -1


def strip_outer(text: str, open_char: str, close_char: str) -> str | None:
    stripped = text.strip()
    if stripped.startswith(open_char) and find_balanced(stripped, 0, open_char, close_char) == len(stripped) - 1:
        return stripped[1:-1]
    return None


def stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
