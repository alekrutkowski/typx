from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Iterable

from .constants import NS
from .util import local_name


@dataclass(slots=True)
class WordBibliographyEntry:
    tag: str
    entry_type: str
    fields: dict[str, str] = field(default_factory=dict)


_SOURCE_TYPE_MAP = {
    "Book": "book",
    "BookSection": "incollection",
    "JournalArticle": "article",
    "ArticleInAPeriodical": "article",
    "ConferenceProceedings": "inproceedings",
    "Report": "report",
    "InternetSite": "online",
    "DocumentFromInternetSite": "online",
    "ElectronicSource": "online",
    "Patent": "patent",
    "Case": "jurisdiction",
    "Film": "video",
    "Interview": "misc",
    "Misc": "misc",
    "SoundRecording": "audio",
    "Performance": "performance",
    "Art": "artwork",
}


def _text(element: ET.Element | None) -> str:
    if element is None:
        return ""
    return "".join(element.itertext()).strip()


def _child_text(source: ET.Element, name: str) -> str:
    for child in source:
        if local_name(child.tag) == name:
            return _text(child)
    return ""


def _people(source: ET.Element, role: str) -> list[str]:
    names: list[str] = []
    for element in source.iter():
        if local_name(element.tag) != role:
            continue
        corporate = next((item for item in element.iter() if local_name(item.tag) == "Corporate"), None)
        if corporate is not None and _text(corporate):
            names.append(_text(corporate))
        for person in (item for item in element.iter() if local_name(item.tag) == "Person"):
            first = _child_text(person, "First")
            middle = _child_text(person, "Middle")
            last = _child_text(person, "Last")
            suffix = _child_text(person, "Suffix")
            given = " ".join(part for part in (first, middle) if part)
            if last and given:
                value = f"{last}, {given}"
            else:
                value = last or given
            if suffix:
                value = f"{value}, {suffix}" if value else suffix
            if value:
                names.append(value)
    # The Word schema nests an Author role inside an outer Author container, so
    # de-duplicate while retaining the source order.
    return list(dict.fromkeys(names))


def _safe_key(tag: str, used: set[str]) -> str:
    base = re.sub(r"[^A-Za-z0-9_.:+-]+", "-", tag).strip("-.") or "word-source"
    key = base
    suffix = 2
    while key in used:
        key = f"{base}-{suffix}"
        suffix += 1
    used.add(key)
    return key


def parse_word_bibliography_roots(roots: Iterable[ET.Element]) -> tuple[list[WordBibliographyEntry], dict[str, str]]:
    entries: list[WordBibliographyEntry] = []
    key_map: dict[str, str] = {}
    used: set[str] = set()
    for root in roots:
        if local_name(root.tag) != "Sources" or not root.tag.startswith("{" + NS["b"] + "}"):
            continue
        for source in root:
            if local_name(source.tag) != "Source":
                continue
            tag = _child_text(source, "Tag")
            if not tag:
                continue
            key = _safe_key(tag, used)
            key_map[tag] = key
            source_type = _child_text(source, "SourceType") or "Misc"
            entry_type = _SOURCE_TYPE_MAP.get(source_type, "misc")
            fields: dict[str, str] = {}
            direct_map = {
                "Title": "title",
                "Year": "year",
                "Month": "month",
                "Day": "day",
                "JournalName": "journaltitle",
                "PeriodicalTitle": "journaltitle",
                "BookTitle": "booktitle",
                "ConferenceName": "eventtitle",
                "Publisher": "publisher",
                "Institution": "institution",
                "City": "location",
                "StateProvince": "location",
                "CountryRegion": "location",
                "Volume": "volume",
                "Issue": "number",
                "Pages": "pages",
                "Edition": "edition",
                "URL": "url",
                "Comments": "note",
                "ShortTitle": "shorttitle",
                "Medium": "howpublished",
                "ProductionCompany": "organization",
                "Theater": "venue",
                "PatentNumber": "number",
                "Court": "institution",
                "Reporter": "journaltitle",
                "CaseNumber": "number",
                "Station": "organization",
                "Distributor": "publisher",
                "Type": "type",
            }
            locations: list[str] = []
            for word_name, bib_name in direct_map.items():
                value = _child_text(source, word_name)
                if not value:
                    continue
                if bib_name == "location":
                    locations.append(value)
                elif bib_name not in fields:
                    fields[bib_name] = value
            if locations:
                fields["location"] = ", ".join(dict.fromkeys(locations))
            standard_number = _child_text(source, "StandardNumber")
            if standard_number:
                fields["isbn" if entry_type in {"book", "incollection"} else "issn"] = standard_number
            accessed = "-".join(filter(None, (
                _child_text(source, "YearAccessed"),
                (_child_text(source, "MonthAccessed") or "").zfill(2) if _child_text(source, "MonthAccessed") else "",
                (_child_text(source, "DayAccessed") or "").zfill(2) if _child_text(source, "DayAccessed") else "",
            )))
            if accessed:
                fields["urldate"] = accessed
            authors = _people(source, "Author")
            editors = _people(source, "Editor")
            translators = _people(source, "Translator")
            if authors:
                fields["author"] = " and ".join(authors)
            if editors:
                fields["editor"] = " and ".join(editors)
            if translators:
                fields["translator"] = " and ".join(translators)
            entries.append(WordBibliographyEntry(key, entry_type, fields))
    return entries, key_map


def _bib_value(value: str) -> str:
    # BibLaTeX is UTF-8 capable. Keep Unicode intact and escape only structural
    # characters that would otherwise terminate a braced field.
    return value.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")


def entries_to_biblatex(entries: Iterable[WordBibliographyEntry]) -> str:
    chunks: list[str] = []
    preferred_order = [
        "author", "editor", "translator", "title", "shorttitle", "booktitle",
        "journaltitle", "eventtitle", "year", "month", "day", "volume", "number",
        "pages", "edition", "publisher", "institution", "organization", "location",
        "isbn", "issn", "url", "urldate", "type", "howpublished", "venue", "note",
    ]
    for entry in entries:
        lines = [f"@{entry.entry_type}{{{entry.tag},"]
        seen: set[str] = set()
        for name in preferred_order:
            value = entry.fields.get(name)
            if value:
                lines.append(f"  {name} = {{{_bib_value(value)}}},")
                seen.add(name)
        for name in sorted(set(entry.fields) - seen):
            value = entry.fields[name]
            if value:
                lines.append(f"  {name} = {{{_bib_value(value)}}},")
        lines.append("}")
        chunks.append("\n".join(lines))
    return "\n\n".join(chunks).rstrip() + ("\n" if chunks else "")
