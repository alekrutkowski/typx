from __future__ import annotations

import os
import re
import struct
from functools import lru_cache
from pathlib import Path
from typing import Iterable


def _u16(data: bytes, offset: int) -> int:
    return struct.unpack_from(">H", data, offset)[0]


def _u32(data: bytes, offset: int) -> int:
    return struct.unpack_from(">I", data, offset)[0]


def _font_offsets(data: bytes) -> list[int]:
    if data[:4] == b"ttcf" and len(data) >= 12:
        count = _u32(data, 8)
        if count > 256 or len(data) < 12 + 4 * count:
            return []
        return [_u32(data, 12 + 4 * index) for index in range(count)]
    if data[:4] in {b"\x00\x01\x00\x00", b"OTTO", b"true", b"typ1"}:
        return [0]
    return []


def _name_records(data: bytes, font_offset: int) -> Iterable[tuple[int, int, int, int, bytes]]:
    if font_offset < 0 or font_offset + 12 > len(data):
        return
    try:
        table_count = _u16(data, font_offset + 4)
    except struct.error:
        return
    records_end = font_offset + 12 + table_count * 16
    if table_count > 4096 or records_end > len(data):
        return
    name_offset = None
    name_length = None
    for index in range(table_count):
        base = font_offset + 12 + index * 16
        if data[base:base + 4] != b"name":
            continue
        try:
            name_offset = _u32(data, base + 8)
            name_length = _u32(data, base + 12)
        except struct.error:
            return
        break
    if name_offset is None or name_length is None:
        return
    table = font_offset + name_offset
    if table + 6 > len(data) or table + name_length > len(data):
        return
    try:
        count = _u16(data, table + 2)
        string_offset = _u16(data, table + 4)
    except struct.error:
        return
    record_base = table + 6
    strings = table + string_offset
    if count > 8192 or record_base + count * 12 > len(data):
        return
    for index in range(count):
        base = record_base + index * 12
        try:
            platform_id = _u16(data, base)
            encoding_id = _u16(data, base + 2)
            language_id = _u16(data, base + 4)
            name_id = _u16(data, base + 6)
            length = _u16(data, base + 8)
            offset = _u16(data, base + 10)
        except struct.error:
            continue
        start = strings + offset
        end = start + length
        if start < strings or end > len(data):
            continue
        yield platform_id, encoding_id, language_id, name_id, data[start:end]


def _decode_name(platform_id: int, encoding_id: int, payload: bytes) -> str | None:
    try:
        if platform_id in {0, 3}:
            return payload.decode("utf-16-be").strip("\x00 ")
        if platform_id == 1:
            return payload.decode("mac_roman").strip("\x00 ")
        return payload.decode("utf-8").strip("\x00 ")
    except (UnicodeDecodeError, LookupError):
        return None


def font_family_names(data: bytes) -> set[str]:
    """Return family/typographic-family names advertised by an sfnt font."""
    names: set[str] = set()
    for offset in _font_offsets(data):
        for platform_id, encoding_id, _language_id, name_id, payload in _name_records(data, offset):
            if name_id not in {1, 16, 21}:
                continue
            value = _decode_name(platform_id, encoding_id, payload)
            if value:
                names.add(value)
    return names


def font_style_names(data: bytes) -> set[str]:
    names: set[str] = set()
    for offset in _font_offsets(data):
        for platform_id, encoding_id, _language_id, name_id, payload in _name_records(data, offset):
            if name_id not in {2, 17, 22}:
                continue
            value = _decode_name(platform_id, encoding_id, payload)
            if value:
                names.add(value)
    return names


def font_extension(data: bytes) -> str:
    if data[:4] == b"OTTO":
        return ".otf"
    if data[:4] == b"ttcf":
        return ".ttc"
    return ".ttf"


def deobfuscate_ooxml_font(data: bytes, font_key: str | None) -> bytes:
    """De-obfuscate a Word embedded font part (ODTTF) using w:fontKey."""
    if not font_key:
        return data
    hex_key = re.sub(r"[^0-9A-Fa-f]", "", font_key)
    if len(hex_key) != 32:
        return data
    try:
        key = bytes.fromhex(hex_key)[::-1]
    except ValueError:
        return data
    result = bytearray(data)
    for index in range(min(32, len(result))):
        result[index] ^= key[index % 16]
    return bytes(result)


def normalized_family(name: str) -> str:
    return re.sub(r"[\s_\-]+", "", name).casefold()


def system_font_dirs() -> list[Path]:
    candidates: list[Path] = []
    if os.name == "nt":
        windir = Path(os.environ.get("WINDIR", r"C:\Windows"))
        candidates.append(windir / "Fonts")
        local = os.environ.get("LOCALAPPDATA")
        if local:
            candidates.append(Path(local) / "Microsoft" / "Windows" / "Fonts")
    else:
        candidates.extend([
            Path("/usr/share/fonts"),
            Path("/usr/local/share/fonts"),
            Path.home() / ".local" / "share" / "fonts",
            Path.home() / ".fonts",
        ])
    seen: set[str] = set()
    result: list[Path] = []
    for path in candidates:
        key = os.path.normcase(str(path.expanduser()))
        if key not in seen and path.is_dir():
            seen.add(key)
            result.append(path.expanduser())
    return result


@lru_cache(maxsize=4)
def _font_index_for_dirs(directory_key: tuple[str, ...]) -> dict[str, tuple[str, ...]]:
    index: dict[str, list[str]] = {}
    for directory_text in directory_key:
        directory = Path(directory_text)
        try:
            files = directory.rglob("*")
            for path in files:
                if not path.is_file() or path.suffix.lower() not in {".ttf", ".otf", ".ttc"}:
                    continue
                try:
                    data = path.read_bytes()
                    families = font_family_names(data)
                except (OSError, ValueError, struct.error):
                    continue
                for family in families:
                    index.setdefault(normalized_family(family), []).append(str(path))
        except OSError:
            continue
    return {key: tuple(dict.fromkeys(paths)) for key, paths in index.items()}


def find_system_fonts(family: str, *, aliases: Iterable[str] = (),
                      directories: Iterable[Path] | None = None) -> list[Path]:
    dirs = tuple(str(path) for path in (list(directories) if directories is not None else system_font_dirs()))
    index = _font_index_for_dirs(dirs)
    for candidate in (family, *aliases):
        paths = index.get(normalized_family(candidate), ())
        if paths:
            return [Path(path) for path in paths]
    return []
