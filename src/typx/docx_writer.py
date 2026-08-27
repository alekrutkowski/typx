from __future__ import annotations

import datetime as _dt
import hashlib
import io
import posixpath
import re
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Literal

from .constants import (CONTENT_TYPES, EXT_BY_MIME, NS, REL_TYPES,
                        TYPX_RELATIONSHIP_TYPE)
from .docx_package import DocxPackage, PackageBuilder
from .model import (
    Block,
    Bookmark,
    Border,
    Break,
    BreakBlock,
    Change,
    Citation,
    CodeBlock,
    CommentAnchor,
    ContentControl,
    Divider,
    Document,
    Field,
    Figure,
    Heading,
    ImageInline,
    Inline,
    Link,
    ListBlock,
    ListItem,
    ListProperties,
    MathBlock,
    MathInline,
    NoteRef,
    Paragraph,
    ParagraphStyle,
    Quote,
    RawBlock,
    RawInline,
    Resource,
    SectionProperties,
    StyleDefinition,
    Table,
    TableCell,
    TableRow,
    Text,
    TextStyle,
)
from .omml import typst_math_to_omml
from .roundtrip import decode_raw_fragment, typx_source_xml
from .util import (
    extension_for_media_type,
    hex_to_ooxml_highlight,
    normalize_hex_color,
    parse_xml,
    points_to_emu,
    points_to_half_points,
    points_to_twips,
    qn,
    sanitize_filename,
    sha256_bytes,
    text_from_inlines,
    xml_bytes,
)


@dataclass(slots=True)
class DocxWriteOptions:
    output_path: Path | None = None
    deterministic: bool = True
    preserve_raw: bool = True
    preserve_comments: bool = True
    preserve_revisions: bool = True
    embed_typst_source: bool = True
    update_fields: bool = True
    compatibility_mode: int = 15
    application_name: str = "typx"
    creator: str = ""
    missing_assets: Literal["placeholder", "error"] = "placeholder"


@dataclass(slots=True)
class _NumberingSpec:
    abstract_id: int
    num_id: int
    ordered: bool
    start: int
    number_format: str
    marker: str | None


class DocxWriter:
    """Serialize the shared document model as a Transitional WordprocessingML package.

    The writer intentionally uses only Python's standard library. OOXML constructs that
    cannot be represented by the shared model can be reinserted from RawBlock/RawInline
    fragments when preservation is enabled.
    """

    def __init__(self, document: Document, options: DocxWriteOptions | None = None):
        self.doc = document
        self.options = options or DocxWriteOptions()
        self.builder = PackageBuilder()
        self.document_part = "word/document.xml"
        self._numbering_by_object: dict[int, _NumberingSpec] = {}
        self._numberings: list[_NumberingSpec] = []
        self._next_num_id = 1
        self._next_abstract_id = 0
        self._bookmark_ids: dict[str, int] = {}
        self._next_bookmark_id = 0
        self._image_parts: dict[str, tuple[str, str]] = {}
        self._next_drawing_id = 1
        self._note_ids: dict[tuple[str, str], int] = {}
        self._note_bodies: dict[str, dict[int, list[Block]]] = {"footnote": {}, "endnote": {}}
        self._next_note_id = {"footnote": 1, "endnote": 1}
        self._comment_ids: dict[str, int] = {}
        self._next_comment_id = 0
        self._header_footer_index = {"header": 0, "footer": 0}
        self._part_rel_cache: dict[tuple[str, str, str, str | None], str] = {}
        self._warnings: list[str] = []

    @classmethod
    def write_file(cls, document: Document, path: str | Path,
                   options: DocxWriteOptions | None = None) -> Path:
        opts = options or DocxWriteOptions()
        opts.output_path = Path(path)
        writer = cls(document, opts)
        writer.save(path)
        return Path(path)

    def build(self) -> bytes:
        self._prepare()
        parts = self.builder.finalize()
        if self.options.embed_typst_source and self.doc.source_format == "typst" and self.doc.source_text:
            semantic = DocxPackage(parts).semantic_digest(exclude_typx=True)
            source_part = "customXml/typx-source.xml"
            self.builder.add_part(
                source_part,
                typx_source_xml(
                    self.doc.source_text,
                    semantic,
                    self.doc.source_path,
                    {"writer": "typx", "model": "shared-ir-v1"},
                ),
                CONTENT_TYPES["custom_xml"],
            )
            self.builder.add_relationship(
                self.document_part,
                TYPX_RELATIONSHIP_TYPE,
                "../customXml/typx-source.xml",
            )
            parts = self.builder.finalize()
        return self._zip_bytes(parts)

    def save(self, path: str | Path | None = None) -> Path:
        output = Path(path or self.options.output_path or "output.docx")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(self.build())
        return output

    @property
    def warnings(self) -> list[str]:
        return [*self.doc.warnings, *self._warnings]

    # ---------- package assembly ----------

    def _prepare(self) -> None:
        self._register_lists(self.doc.blocks)
        self._register_comments()
        self._add_root_relationships()
        self._add_properties()
        self._add_styles()
        self._add_numbering()
        self._add_settings()
        self._add_font_table()
        self._add_theme()
        document = self._document_xml()
        self.builder.add_part(self.document_part, document, CONTENT_TYPES["document"])
        self.builder.add_relationship(self.document_part, REL_TYPES["styles"], "styles.xml")
        self.builder.add_relationship(self.document_part, REL_TYPES["settings"], "settings.xml")
        self.builder.add_relationship(self.document_part, REL_TYPES["numbering"], "numbering.xml")
        self.builder.add_relationship(self.document_part, REL_TYPES["font_table"], "fontTable.xml")
        self.builder.add_relationship(self.document_part, REL_TYPES["theme"], "theme/theme1.xml")
        self._add_notes_parts()
        self._add_comments_part()

    def _zip_bytes(self, parts: dict[str, bytes]) -> bytes:
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for name in sorted(parts):
                data = parts[name]
                if self.options.deterministic:
                    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                    info.compress_type = zipfile.ZIP_DEFLATED
                    info.external_attr = 0o600 << 16
                    archive.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
                else:
                    archive.writestr(name, data)
        return stream.getvalue()

    def _add_root_relationships(self) -> None:
        self.builder.add_relationship("", REL_TYPES["office_document"], "word/document.xml", rel_id="rId1")
        self.builder.add_relationship("", REL_TYPES["core_properties"], "docProps/core.xml", rel_id="rId2")
        self.builder.add_relationship("", REL_TYPES["extended_properties"], "docProps/app.xml", rel_id="rId3")
        if self.doc.custom_properties:
            self.builder.add_relationship("", REL_TYPES["custom_properties"], "docProps/custom.xml", rel_id="rId4")

    def _add_properties(self) -> None:
        metadata = self.doc.metadata
        core = ET.Element(qn("cp", "coreProperties"))
        mapping = [
            ("title", "dc", "title"), ("subject", "dc", "subject"),
            ("author", "dc", "creator"), ("keywords", "cp", "keywords"),
            ("description", "dc", "description"), ("last_modified_by", "cp", "lastModifiedBy"),
            ("revision", "cp", "revision"), ("category", "cp", "category"),
            ("content_status", "cp", "contentStatus"), ("language", "dc", "language"),
            ("version", "cp", "version"),
        ]
        for key, prefix, tag in mapping:
            value = metadata.get(key)
            if value is None or value == "":
                continue
            if isinstance(value, (list, tuple)):
                value = "; ".join(str(item) for item in value)
            ET.SubElement(core, qn(prefix, tag)).text = str(value)
        timestamp = "2000-01-01T00:00:00Z" if self.options.deterministic else _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        for key, tag in (("created", "created"), ("modified", "modified")):
            value = str(metadata.get(key) or timestamp)
            element = ET.SubElement(core, qn("dcterms", tag), {qn("xsi", "type"): "dcterms:W3CDTF"})
            element.text = value
        self.builder.add_part("docProps/core.xml", core, CONTENT_TYPES["core"])

        app = ET.Element(qn("ep", "Properties"))
        ET.SubElement(app, qn("ep", "Application")).text = str(metadata.get("app_application") or self.options.application_name)
        ET.SubElement(app, qn("ep", "AppVersion")).text = str(metadata.get("app_appversion") or "0.1")
        ET.SubElement(app, qn("ep", "DocSecurity")).text = "0"
        ET.SubElement(app, qn("ep", "ScaleCrop")).text = "false"
        ET.SubElement(app, qn("ep", "Company")).text = str(metadata.get("app_company") or "")
        ET.SubElement(app, qn("ep", "LinksUpToDate")).text = "false"
        ET.SubElement(app, qn("ep", "SharedDoc")).text = "false"
        ET.SubElement(app, qn("ep", "HyperlinksChanged")).text = "false"
        self.builder.add_part("docProps/app.xml", app, CONTENT_TYPES["extended"])

        if self.doc.custom_properties:
            root = ET.Element(qn("cust", "Properties"))
            pid = 2
            for name, value in sorted(self.doc.custom_properties.items()):
                prop = ET.SubElement(root, qn("cust", "property"), {
                    "fmtid": "{D5CDD505-2E9C-101B-9397-08002B2CF9AE}",
                    "pid": str(pid),
                    "name": str(name),
                })
                pid += 1
                if isinstance(value, bool):
                    ET.SubElement(prop, qn("vt", "bool")).text = "true" if value else "false"
                elif isinstance(value, int):
                    ET.SubElement(prop, qn("vt", "i4")).text = str(value)
                elif isinstance(value, float):
                    ET.SubElement(prop, qn("vt", "r8")).text = repr(value)
                else:
                    ET.SubElement(prop, qn("vt", "lpwstr")).text = str(value)
            self.builder.add_part("docProps/custom.xml", root, CONTENT_TYPES["custom"])

    def _add_settings(self) -> None:
        root = ET.Element(qn("w", "settings"))
        ET.SubElement(root, qn("w", "zoom"), {qn("w", "percent"): "100"})
        ET.SubElement(root, qn("w", "defaultTabStop"), {qn("w", "val"): "720"})
        if any(section.different_odd_even for section in self.doc.sections):
            ET.SubElement(root, qn("w", "evenAndOddHeaders"))
        if self.options.update_fields:
            ET.SubElement(root, qn("w", "updateFields"), {qn("w", "val"): "true"})
        compat = ET.SubElement(root, qn("w", "compat"))
        ET.SubElement(compat, qn("w", "compatSetting"), {
            qn("w", "name"): "compatibilityMode",
            qn("w", "uri"): "http://schemas.microsoft.com/office/word",
            qn("w", "val"): str(self.options.compatibility_mode),
        })
        ET.SubElement(root, qn("w", "decimalSymbol"), {qn("w", "val"): "."})
        ET.SubElement(root, qn("w", "listSeparator"), {qn("w", "val"): ","})
        self.builder.add_part("word/settings.xml", root, CONTENT_TYPES["settings"])

    def _add_font_table(self) -> None:
        fonts: set[str] = {"Aptos", "Calibri", "Cambria", "Courier New"}
        for style in self.doc.styles.values():
            for name in (style.text.font, style.text.font_east_asia, style.text.font_complex,
                         style.paragraph.default_text_style.font):
                if name:
                    fonts.add(name)
        for block in self.doc.walk_blocks():
            for inline in self._block_inlines(block):
                if isinstance(inline, Text):
                    for name in (inline.style.font, inline.style.font_east_asia, inline.style.font_complex):
                        if name:
                            fonts.add(name)
        root = ET.Element(qn("w", "fonts"))
        for name in sorted(fonts):
            font = ET.SubElement(root, qn("w", "font"), {qn("w", "name"): name})
            ET.SubElement(font, qn("w", "charset"), {qn("w", "val"): "00"})
            ET.SubElement(font, qn("w", "family"), {qn("w", "val"): "swiss" if name != "Courier New" else "modern"})
            ET.SubElement(font, qn("w", "pitch"), {qn("w", "val"): "variable" if name != "Courier New" else "fixed"})
        self.builder.add_part("word/fontTable.xml", root, CONTENT_TYPES["font_table"])

    def _add_theme(self) -> None:
        # Compact but complete DrawingML theme. Word uses this for theme colors and fonts.
        theme = ET.Element(qn("a", "theme"), {"name": "typx"})
        elements = ET.SubElement(theme, qn("a", "themeElements"))
        scheme = ET.SubElement(elements, qn("a", "clrScheme"), {"name": "typx"})
        colors = {
            "dk1": ("sysClr", {"val": "windowText", "lastClr": "000000"}),
            "lt1": ("sysClr", {"val": "window", "lastClr": "FFFFFF"}),
            "dk2": ("srgbClr", {"val": "1F1F1F"}), "lt2": ("srgbClr", {"val": "EDEDED"}),
            "accent1": ("srgbClr", {"val": "4472C4"}), "accent2": ("srgbClr", {"val": "ED7D31"}),
            "accent3": ("srgbClr", {"val": "A5A5A5"}), "accent4": ("srgbClr", {"val": "FFC000"}),
            "accent5": ("srgbClr", {"val": "5B9BD5"}), "accent6": ("srgbClr", {"val": "70AD47"}),
            "hlink": ("srgbClr", {"val": "0563C1"}), "folHlink": ("srgbClr", {"val": "954F72"}),
        }
        for key, (tag, attrs) in colors.items():
            container = ET.SubElement(scheme, qn("a", key))
            ET.SubElement(container, qn("a", tag), attrs)
        fonts = ET.SubElement(elements, qn("a", "fontScheme"), {"name": "typx"})
        for kind, latin in (("majorFont", "Aptos Display"), ("minorFont", "Aptos")):
            item = ET.SubElement(fonts, qn("a", kind))
            ET.SubElement(item, qn("a", "latin"), {"typeface": latin})
            ET.SubElement(item, qn("a", "ea"), {"typeface": ""})
            ET.SubElement(item, qn("a", "cs"), {"typeface": ""})
        fmt = ET.SubElement(elements, qn("a", "fmtScheme"), {"name": "typx"})
        for list_name in ("fillStyleLst", "lnStyleLst", "effectStyleLst", "bgFillStyleLst"):
            ET.SubElement(fmt, qn("a", list_name))
        ET.SubElement(theme, qn("a", "objectDefaults"))
        ET.SubElement(theme, qn("a", "extraClrSchemeLst"))
        self.builder.add_part("word/theme/theme1.xml", theme, CONTENT_TYPES["theme"])

    # ---------- styles and numbering ----------

    def _add_styles(self) -> None:
        root = ET.Element(qn("w", "styles"))
        defaults = ET.SubElement(root, qn("w", "docDefaults"))
        rpr_default = ET.SubElement(ET.SubElement(defaults, qn("w", "rPrDefault")), qn("w", "rPr"))
        ET.SubElement(rpr_default, qn("w", "rFonts"), {
            qn("w", "asciiTheme"): "minorHAnsi", qn("w", "hAnsiTheme"): "minorHAnsi",
            qn("w", "eastAsiaTheme"): "minorEastAsia", qn("w", "cstheme"): "minorBidi",
        })
        ET.SubElement(rpr_default, qn("w", "sz"), {qn("w", "val"): "22"})
        ET.SubElement(rpr_default, qn("w", "szCs"), {qn("w", "val"): "22"})
        ppr_default = ET.SubElement(ET.SubElement(defaults, qn("w", "pPrDefault")), qn("w", "pPr"))
        ET.SubElement(ppr_default, qn("w", "spacing"), {qn("w", "after"): "160", qn("w", "line"): "259", qn("w", "lineRule"): "auto"})

        builtins: list[tuple[str, str, str, str | None, TextStyle, ParagraphStyle]] = [
            ("Normal", "Normal", "paragraph", None, TextStyle(size_pt=11), ParagraphStyle()),
            ("Title", "Title", "paragraph", "Normal", TextStyle(size_pt=26, bold=True, color="1F1F1F"), ParagraphStyle(space_after_pt=12, outline_level=0)),
            ("Subtitle", "Subtitle", "paragraph", "Normal", TextStyle(size_pt=15, italic=True, color="595959"), ParagraphStyle(space_after_pt=10)),
            ("Quote", "Quote", "paragraph", "Normal", TextStyle(italic=True, color="404040"), ParagraphStyle(left_indent_pt=36, right_indent_pt=36, space_before_pt=6, space_after_pt=6)),
            ("Caption", "Caption", "paragraph", "Normal", TextStyle(size_pt=9, italic=True, color="404040"), ParagraphStyle(space_before_pt=6, space_after_pt=6)),
            ("Code", "Code", "paragraph", "Normal", TextStyle(font="Courier New", size_pt=9), ParagraphStyle(left_indent_pt=18, right_indent_pt=18, shading="F2F2F2", space_before_pt=6, space_after_pt=6)),
            ("ListParagraph", "List Paragraph", "paragraph", "Normal", TextStyle(), ParagraphStyle(left_indent_pt=36)),
            ("Hyperlink", "Hyperlink", "character", None, TextStyle(color="0563C1", underline="single"), ParagraphStyle()),
        ]
        for level in range(1, 10):
            size = max(11.0, 20.0 - (level - 1) * 1.25)
            builtins.append((f"Heading{level}", f"heading {level}", "paragraph", "Normal",
                             TextStyle(size_pt=size, bold=True, color="2F5496"),
                             ParagraphStyle(space_before_pt=10 if level == 1 else 6, space_after_pt=4,
                                            keep_next=True, outline_level=level - 1)))
        emitted: set[str] = set()
        for style_id, name, kind, based, text, paragraph in builtins:
            self._append_style(root, StyleDefinition(style_id, name, kind, based_on=based,
                                                      qformat=kind == "paragraph", paragraph=paragraph, text=text), builtin=True)
            emitted.add(style_id)
        for style_id, style in sorted(self.doc.styles.items()):
            if style_id in emitted:
                continue
            self._append_style(root, style)
        self.builder.add_part("word/styles.xml", root, CONTENT_TYPES["styles"])

    def _append_style(self, root: ET.Element, style: StyleDefinition, builtin: bool = False) -> None:
        attrs = {qn("w", "type"): style.style_type, qn("w", "styleId"): self._safe_style_id(style.style_id)}
        if builtin:
            attrs[qn("w", "default")] = "1" if style.style_id == "Normal" else "0"
        element = ET.SubElement(root, qn("w", "style"), attrs)
        ET.SubElement(element, qn("w", "name"), {qn("w", "val"): style.name or style.style_id})
        if style.based_on:
            ET.SubElement(element, qn("w", "basedOn"), {qn("w", "val"): self._safe_style_id(style.based_on)})
        if style.next_style:
            ET.SubElement(element, qn("w", "next"), {qn("w", "val"): self._safe_style_id(style.next_style)})
        if style.linked_style:
            ET.SubElement(element, qn("w", "link"), {qn("w", "val"): self._safe_style_id(style.linked_style)})
        if style.ui_priority is not None:
            ET.SubElement(element, qn("w", "uiPriority"), {qn("w", "val"): str(style.ui_priority)})
        if style.qformat:
            ET.SubElement(element, qn("w", "qFormat"))
        if style.hidden:
            ET.SubElement(element, qn("w", "hidden"))
        if style.semi_hidden:
            ET.SubElement(element, qn("w", "semiHidden"))
        if style.unhide_when_used:
            ET.SubElement(element, qn("w", "unhideWhenUsed"))
        if style.style_type in {"paragraph", "table"}:
            ppr = self._paragraph_properties(style.paragraph, None, include_style=False)
            if len(ppr):
                element.append(ppr)
        if style.style_type in {"paragraph", "character"}:
            rpr = self._run_properties(style.text)
            if len(rpr):
                element.append(rpr)

    def _register_lists(self, blocks: Iterable[Block]) -> None:
        for block in blocks:
            if isinstance(block, ListBlock):
                key = id(block)
                if key not in self._numbering_by_object and block.marker != "terms":
                    spec = _NumberingSpec(self._next_abstract_id, self._next_num_id,
                                          block.ordered, block.start, block.number_format, block.marker)
                    self._next_abstract_id += 1
                    self._next_num_id += 1
                    self._numbering_by_object[key] = spec
                    self._numberings.append(spec)
                for item in block.items:
                    self._register_lists(item.blocks)
            elif isinstance(block, Table):
                for row in block.rows:
                    for cell in row.cells:
                        self._register_lists(cell.blocks)
            elif isinstance(block, Figure):
                self._register_lists(block.body)
            elif isinstance(block, Quote):
                self._register_lists(block.blocks)
            elif isinstance(block, ContentControl):
                self._register_lists(block.blocks)
            elif isinstance(block, RawBlock):
                self._register_lists(block.fallback)

    def _add_numbering(self) -> None:
        root = ET.Element(qn("w", "numbering"))
        for spec in self._numberings:
            abstract = ET.SubElement(root, qn("w", "abstractNum"), {qn("w", "abstractNumId"): str(spec.abstract_id)})
            ET.SubElement(abstract, qn("w", "multiLevelType"), {qn("w", "val"): "hybridMultilevel"})
            for level in range(9):
                lvl = ET.SubElement(abstract, qn("w", "lvl"), {qn("w", "ilvl"): str(level)})
                ET.SubElement(lvl, qn("w", "start"), {qn("w", "val"): str(spec.start if level == 0 else 1)})
                if spec.ordered:
                    fmt = self._num_format(spec.number_format, level)
                    pattern = self._number_pattern(fmt, level)
                    ET.SubElement(lvl, qn("w", "numFmt"), {qn("w", "val"): fmt})
                    ET.SubElement(lvl, qn("w", "lvlText"), {qn("w", "val"): pattern})
                else:
                    bullets = [spec.marker or "•", "◦", "▪", "•", "◦", "▪", "•", "◦", "▪"]
                    ET.SubElement(lvl, qn("w", "numFmt"), {qn("w", "val"): "bullet"})
                    ET.SubElement(lvl, qn("w", "lvlText"), {qn("w", "val"): bullets[level]})
                    rpr = ET.SubElement(lvl, qn("w", "rPr"))
                    ET.SubElement(rpr, qn("w", "rFonts"), {qn("w", "ascii"): "Symbol", qn("w", "hAnsi"): "Symbol"})
                ET.SubElement(lvl, qn("w", "lvlJc"), {qn("w", "val"): "left"})
                ppr = ET.SubElement(lvl, qn("w", "pPr"))
                ET.SubElement(ppr, qn("w", "tabs"))
                ET.SubElement(ppr, qn("w", "ind"), {
                    qn("w", "left"): str(720 + level * 360),
                    qn("w", "hanging"): "360",
                })
            num = ET.SubElement(root, qn("w", "num"), {qn("w", "numId"): str(spec.num_id)})
            ET.SubElement(num, qn("w", "abstractNumId"), {qn("w", "val"): str(spec.abstract_id)})
            if spec.start != 1:
                override = ET.SubElement(num, qn("w", "lvlOverride"), {qn("w", "ilvl"): "0"})
                ET.SubElement(override, qn("w", "startOverride"), {qn("w", "val"): str(spec.start)})
        self.builder.add_part("word/numbering.xml", root, CONTENT_TYPES["numbering"])

    # ---------- main document ----------

    def _document_xml(self) -> ET.Element:
        root = ET.Element(qn("w", "document"))
        body = ET.SubElement(root, qn("w", "body"))
        self._write_blocks(body, self.doc.blocks, self.document_part)
        final_section = self.doc.sections[-1] if self.doc.sections else SectionProperties()
        body.append(self._section_properties(final_section, self.document_part))
        return root

    def _write_blocks(self, parent: ET.Element, blocks: Iterable[Block], part_name: str,
                      list_depth: int = 0) -> None:
        for block in blocks:
            self._write_block(parent, block, part_name, list_depth)

    def _write_block(self, parent: ET.Element, block: Block, part_name: str,
                     list_depth: int = 0) -> None:
        if isinstance(block, Paragraph):
            parent.append(self._paragraph(block.inlines, block.style, block.list_props, part_name))
        elif isinstance(block, Heading):
            style = block.style.copy()
            style.style_id = "Title" if block.level <= 0 else f"Heading{min(9, max(1, block.level))}"
            p = self._paragraph(block.inlines, style, None, part_name, heading_label=block.label)
            parent.append(p)
        elif isinstance(block, ListBlock):
            self._write_list(parent, block, part_name, list_depth)
        elif isinstance(block, Table):
            parent.append(self._table(block, part_name))
        elif isinstance(block, Figure):
            self._write_blocks(parent, block.body, part_name, list_depth)
            if block.caption:
                caption = []
                supplement = block.supplement or ("Table" if block.kind_name == "table" else "Figure")
                caption.extend([Text(supplement + " "), Field(f"SEQ {supplement} \\* ARABIC", [Text("1")]), Text(": ")])
                caption.extend(block.caption)
                style = ParagraphStyle(style_id="Caption", align=block.align or "center")
                parent.append(self._paragraph(caption, style, None, part_name, heading_label=block.label))
        elif isinstance(block, Quote):
            for child_block in block.blocks:
                if isinstance(child_block, Paragraph):
                    style = child_block.style.copy(); style.style_id = "Quote"
                    parent.append(self._paragraph(child_block.inlines, style, child_block.list_props, part_name))
                else:
                    self._write_block(parent, child_block, part_name, list_depth)
            if block.attribution:
                style = ParagraphStyle(style_id="Quote", align="right")
                parent.append(self._paragraph([Text("– "), *block.attribution], style, None, part_name))
        elif isinstance(block, CodeBlock):
            style = ParagraphStyle(style_id="Code", shading="F2F2F2")
            inlines: list[Inline] = []
            lines = block.text.splitlines()
            for index, line in enumerate(lines or [""]):
                if index:
                    inlines.append(Break("line"))
                inlines.append(Text(line, TextStyle(font="Courier New", size_pt=9, no_proof=True)))
            parent.append(self._paragraph(inlines, style, None, part_name))
        elif isinstance(block, MathBlock):
            p = ET.Element(qn("w", "p"))
            ppr = ET.SubElement(p, qn("w", "pPr"))
            ET.SubElement(ppr, qn("w", "jc"), {qn("w", "val"): "center"})
            math = self._decode_omml(block.omml, display=True) or typst_math_to_omml(block.typst, display=True)
            p.append(math)
            if block.label:
                self._wrap_paragraph_bookmark(p, block.label)
            parent.append(p)
        elif isinstance(block, Divider):
            style = ParagraphStyle(borders={"bottom": Border("single", block.thickness_pt, block.color)},
                                   space_before_pt=4, space_after_pt=4)
            parent.append(self._paragraph([], style, None, part_name))
        elif isinstance(block, BreakBlock):
            if block.break_type == "section":
                p = ET.Element(qn("w", "p"))
                ppr = ET.SubElement(p, qn("w", "pPr"))
                ppr.append(self._section_properties(block.section or SectionProperties(), part_name))
                parent.append(p)
            else:
                parent.append(self._paragraph([Break(block.break_type)], ParagraphStyle(), None, part_name))
        elif isinstance(block, ContentControl):
            parent.append(self._content_control(block, part_name))
        elif isinstance(block, RawBlock):
            if self.options.preserve_raw and block.format in {"ooxml", "docx-revision"}:
                raw = self._decode_raw_element(block.data)
                if raw is not None and self._is_block_element(raw):
                    parent.append(raw)
                    return
            self._write_blocks(parent, block.fallback, part_name, list_depth)
            if not block.fallback and block.description:
                parent.append(self._paragraph([Text(f"[{block.description}]")], ParagraphStyle(), None, part_name))
        else:
            parent.append(self._paragraph([Text(f"[Unsupported block: {type(block).__name__}]")], ParagraphStyle(), None, part_name))

    def _paragraph(self, inlines: Iterable[Inline], style: ParagraphStyle,
                   list_props: ListProperties | None, part_name: str,
                   heading_label: str | None = None) -> ET.Element:
        p = ET.Element(qn("w", "p"))
        ppr = self._paragraph_properties(style, list_props)
        if len(ppr):
            p.append(ppr)
        if heading_label:
            bookmark_id = self._bookmark_id(heading_label)
            ET.SubElement(p, qn("w", "bookmarkStart"), {qn("w", "id"): str(bookmark_id), qn("w", "name"): self._safe_bookmark_name(heading_label)})
        self._write_inlines(p, inlines, part_name)
        if heading_label:
            ET.SubElement(p, qn("w", "bookmarkEnd"), {qn("w", "id"): str(self._bookmark_id(heading_label))})
        return p

    def _paragraph_properties(self, style: ParagraphStyle, list_props: ListProperties | None,
                              include_style: bool = True) -> ET.Element:
        ppr = ET.Element(qn("w", "pPr"))
        if include_style and style.style_id:
            ET.SubElement(ppr, qn("w", "pStyle"), {qn("w", "val"): self._safe_style_id(style.style_id)})
        if list_props and list_props.num_id:
            numpr = ET.SubElement(ppr, qn("w", "numPr"))
            ET.SubElement(numpr, qn("w", "ilvl"), {qn("w", "val"): str(max(0, min(8, list_props.level)))})
            ET.SubElement(numpr, qn("w", "numId"), {qn("w", "val"): str(list_props.num_id)})
        if style.align:
            align = {"start": "left", "end": "right", "justify": "both", "left": "left", "right": "right", "center": "center"}.get(style.align, style.align)
            ET.SubElement(ppr, qn("w", "jc"), {qn("w", "val"): align})
        ind_attrs: dict[str, str] = {}
        for value, key in ((style.left_indent_pt, "left"), (style.right_indent_pt, "right"),
                           (style.first_line_indent_pt, "firstLine"), (style.hanging_indent_pt, "hanging")):
            converted = points_to_twips(value)
            if converted is not None:
                ind_attrs[qn("w", key)] = str(abs(converted) if key == "hanging" else converted)
        if ind_attrs:
            ET.SubElement(ppr, qn("w", "ind"), ind_attrs)
        spacing_attrs: dict[str, str] = {}
        before = points_to_twips(style.space_before_pt); after = points_to_twips(style.space_after_pt)
        if before is not None: spacing_attrs[qn("w", "before")] = str(before)
        if after is not None: spacing_attrs[qn("w", "after")] = str(after)
        if style.line_spacing is not None:
            if style.line_spacing_rule in {"exact", "atLeast"}:
                spacing_attrs[qn("w", "line")] = str(points_to_twips(style.line_spacing) or 0)
                spacing_attrs[qn("w", "lineRule")] = style.line_spacing_rule
            else:
                value = style.line_spacing
                spacing_attrs[qn("w", "line")] = str(round(value * 240 if value < 10 else value))
                spacing_attrs[qn("w", "lineRule")] = "auto"
        if spacing_attrs:
            ET.SubElement(ppr, qn("w", "spacing"), spacing_attrs)
        for enabled, tag in ((style.keep_next, "keepNext"), (style.keep_lines, "keepLines"),
                             (style.page_break_before, "pageBreakBefore"), (style.widow_control, "widowControl"),
                             (style.contextual_spacing, "contextualSpacing"), (style.mirror_indents, "mirrorIndents"),
                             (style.suppress_line_numbers, "suppressLineNumbers"), (style.bidi, "bidi")):
            if enabled is not None:
                ET.SubElement(ppr, qn("w", tag), {qn("w", "val"): "1" if enabled else "0"})
        if style.text_direction:
            ET.SubElement(ppr, qn("w", "textDirection"), {qn("w", "val"): style.text_direction})
        if style.shading:
            ET.SubElement(ppr, qn("w", "shd"), {qn("w", "val"): "clear", qn("w", "color"): "auto", qn("w", "fill"): normalize_hex_color(style.shading, "FFFFFF") or "FFFFFF"})
        if style.borders:
            borders = ET.SubElement(ppr, qn("w", "pBdr"))
            self._append_borders(borders, style.borders)
        if style.tabs:
            tabs = ET.SubElement(ppr, qn("w", "tabs"))
            for tab in style.tabs:
                ET.SubElement(tabs, qn("w", "tab"), {
                    qn("w", "val"): tab.alignment,
                    qn("w", "leader"): tab.leader,
                    qn("w", "pos"): str(points_to_twips(tab.position_pt) or 0),
                })
        if style.outline_level is not None:
            ET.SubElement(ppr, qn("w", "outlineLvl"), {qn("w", "val"): str(max(0, min(9, style.outline_level)))})
        if not style.default_text_style.is_empty():
            ppr.append(self._run_properties(style.default_text_style))
        return ppr

    # ---------- inline content ----------

    def _write_inlines(self, parent: ET.Element, inlines: Iterable[Inline], part_name: str,
                       deleted: bool = False) -> None:
        for inline in inlines:
            if isinstance(inline, Text):
                parent.append(self._text_run(inline.text, inline.style, deleted=deleted))
            elif isinstance(inline, Break):
                run = ET.SubElement(parent, qn("w", "r"))
                if inline.break_type == "tab":
                    ET.SubElement(run, qn("w", "tab"))
                elif inline.break_type == "soft":
                    ET.SubElement(run, qn("w", "softHyphen"))
                else:
                    type_value = {"page": "page", "column": "column", "line": "textWrapping"}.get(inline.break_type, "textWrapping")
                    ET.SubElement(run, qn("w", "br"), {qn("w", "type"): type_value})
            elif isinstance(inline, Link):
                attrs: dict[str, str] = {}
                if inline.anchor or inline.target.startswith("#"):
                    attrs[qn("w", "anchor")] = self._safe_bookmark_name(inline.target.lstrip("#"))
                else:
                    rid = self._relationship(part_name, REL_TYPES["hyperlink"], inline.target, "External")
                    attrs[qn("r", "id")] = rid
                if inline.tooltip:
                    attrs[qn("w", "tooltip")] = inline.tooltip
                hyperlink = ET.SubElement(parent, qn("w", "hyperlink"), attrs)
                if inline.children:
                    self._write_inlines(hyperlink, inline.children, part_name, deleted)
                else:
                    hyperlink.append(self._text_run(inline.target, TextStyle(color="0563C1", underline="single"), deleted=deleted))
            elif isinstance(inline, Bookmark):
                bookmark_id = self._bookmark_id(inline.name, inline.bookmark_id)
                if inline.end:
                    ET.SubElement(parent, qn("w", "bookmarkEnd"), {qn("w", "id"): str(bookmark_id)})
                else:
                    ET.SubElement(parent, qn("w", "bookmarkStart"), {
                        qn("w", "id"): str(bookmark_id), qn("w", "name"): self._safe_bookmark_name(inline.name),
                    })
            elif isinstance(inline, ImageInline):
                image = self._image_run(inline, part_name)
                parent.append(image)
            elif isinstance(inline, MathInline):
                math = self._decode_omml(inline.omml, display=inline.display) or typst_math_to_omml(inline.typst, display=inline.display)
                parent.append(math)
            elif isinstance(inline, NoteRef):
                note_id = self._note_id(inline)
                run = ET.SubElement(parent, qn("w", "r"))
                rpr = ET.SubElement(run, qn("w", "rPr")); ET.SubElement(rpr, qn("w", "rStyle"), {qn("w", "val"): "FootnoteReference"})
                ET.SubElement(run, qn("w", "footnoteReference" if inline.note_type == "footnote" else "endnoteReference"), {qn("w", "id"): str(note_id)})
            elif isinstance(inline, Field):
                self._write_field(parent, inline, part_name)
            elif isinstance(inline, Citation):
                code = "CITATION " + " \\m ".join(inline.keys)
                if inline.supplement:
                    code += f' \\p "{inline.supplement.replace(chr(34), chr(39))}"'
                fallback = inline.fallback or [Text("[" + "; ".join(inline.keys) + "]")]
                self._write_field(parent, Field(code, fallback), part_name)
            elif isinstance(inline, CommentAnchor):
                comment_id = self._comment_id(inline.comment_id)
                if inline.event == "start":
                    ET.SubElement(parent, qn("w", "commentRangeStart"), {qn("w", "id"): str(comment_id)})
                elif inline.event == "end":
                    ET.SubElement(parent, qn("w", "commentRangeEnd"), {qn("w", "id"): str(comment_id)})
                else:
                    run = ET.SubElement(parent, qn("w", "r"))
                    ET.SubElement(run, qn("w", "commentReference"), {qn("w", "id"): str(comment_id)})
            elif isinstance(inline, Change):
                if not self.options.preserve_revisions:
                    if inline.change_type in {"insert", "move_to"}:
                        self._write_inlines(parent, inline.children, part_name, deleted)
                    continue
                tag = {"insert": "ins", "delete": "del", "move_from": "moveFrom", "move_to": "moveTo"}[inline.change_type]
                attrs = {qn("w", "id"): str(self._stable_numeric_id(inline.change_id or f"change-{id(inline)}")),
                         qn("w", "author"): inline.author or self.options.creator or "typx"}
                if inline.date:
                    attrs[qn("w", "date")] = inline.date
                wrapper = ET.SubElement(parent, qn("w", tag), attrs)
                self._write_inlines(wrapper, inline.children, part_name, deleted=inline.change_type in {"delete", "move_from"})
            elif isinstance(inline, RawInline):
                if self.options.preserve_raw and inline.format == "ooxml":
                    raw = self._decode_raw_element(inline.data)
                    if raw is not None and self._is_inline_element(raw):
                        parent.append(raw)
                        continue
                self._write_inlines(parent, inline.fallback, part_name, deleted)
            else:
                parent.append(self._text_run(f"[Unsupported inline: {type(inline).__name__}]", TextStyle(), deleted=deleted))

    def _text_run(self, text: str, style: TextStyle, deleted: bool = False) -> ET.Element:
        run = ET.Element(qn("w", "r"))
        rpr = self._run_properties(style)
        if len(rpr):
            run.append(rpr)
        # Keep embedded line breaks and tabs meaningful even when represented as text.
        chunks = re.split(r"(\t|\r?\n)", text)
        for chunk in chunks:
            if chunk == "\t":
                ET.SubElement(run, qn("w", "tab"))
            elif chunk in {"\n", "\r\n"}:
                ET.SubElement(run, qn("w", "br"))
            elif chunk:
                tag = "delText" if deleted else "t"
                attrs = {qn("xml", "space"): "preserve"} if chunk[:1].isspace() or chunk[-1:].isspace() else {}
                ET.SubElement(run, qn("w", tag), attrs).text = chunk
        if not chunks or text == "":
            ET.SubElement(run, qn("w", "delText" if deleted else "t"))
        return run

    def _run_properties(self, style: TextStyle) -> ET.Element:
        rpr = ET.Element(qn("w", "rPr"))
        for value, tag in ((style.bold, "b"), (style.italic, "i"), (style.strike, "strike"),
                           (style.double_strike, "dstrike"), (style.small_caps, "smallCaps"),
                           (style.all_caps, "caps"), (style.hidden, "vanish"), (style.rtl, "rtl"),
                           (style.no_proof, "noProof"), (style.emboss, "emboss"), (style.imprint, "imprint"),
                           (style.outline, "outline"), (style.shadow, "shadow")):
            if value is not None:
                ET.SubElement(rpr, qn("w", tag), {qn("w", "val"): "1" if value else "0"})
        if style.underline:
            ET.SubElement(rpr, qn("w", "u"), {qn("w", "val"): style.underline})
        if style.superscript:
            ET.SubElement(rpr, qn("w", "vertAlign"), {qn("w", "val"): "superscript"})
        elif style.subscript:
            ET.SubElement(rpr, qn("w", "vertAlign"), {qn("w", "val"): "subscript"})
        font_attrs: dict[str, str] = {}
        if style.font:
            font_attrs.update({qn("w", "ascii"): style.font, qn("w", "hAnsi"): style.font})
        if style.font_east_asia: font_attrs[qn("w", "eastAsia")] = style.font_east_asia
        if style.font_complex: font_attrs[qn("w", "cs")] = style.font_complex
        if font_attrs:
            ET.SubElement(rpr, qn("w", "rFonts"), font_attrs)
        size = points_to_half_points(style.size_pt)
        if size is not None:
            ET.SubElement(rpr, qn("w", "sz"), {qn("w", "val"): str(size)})
            ET.SubElement(rpr, qn("w", "szCs"), {qn("w", "val"): str(size)})
        if style.color:
            ET.SubElement(rpr, qn("w", "color"), {qn("w", "val"): normalize_hex_color(style.color, "000000") or "000000"})
        if style.highlight:
            highlight = hex_to_ooxml_highlight(style.highlight)
            if highlight:
                ET.SubElement(rpr, qn("w", "highlight"), {qn("w", "val"): highlight})
            else:
                ET.SubElement(rpr, qn("w", "shd"), {qn("w", "val"): "clear", qn("w", "fill"): normalize_hex_color(style.highlight, "FFFF00") or "FFFF00"})
        lang_attrs: dict[str, str] = {}
        if style.language: lang_attrs[qn("w", "val")] = style.language.replace("_", "-")
        if style.language_east_asia: lang_attrs[qn("w", "eastAsia")] = style.language_east_asia.replace("_", "-")
        if style.language_complex: lang_attrs[qn("w", "bidi")] = style.language_complex.replace("_", "-")
        if lang_attrs:
            ET.SubElement(rpr, qn("w", "lang"), lang_attrs)
        if style.letter_spacing_pt is not None:
            ET.SubElement(rpr, qn("w", "spacing"), {qn("w", "val"): str(points_to_twips(style.letter_spacing_pt) or 0)})
        if style.scale_percent is not None:
            ET.SubElement(rpr, qn("w", "w"), {qn("w", "val"): str(style.scale_percent)})
        if style.baseline_pt is not None:
            ET.SubElement(rpr, qn("w", "position"), {qn("w", "val"): str(points_to_half_points(style.baseline_pt) or 0)})
        return rpr

    def _write_field(self, parent: ET.Element, field: Field, part_name: str) -> None:
        begin = ET.SubElement(parent, qn("w", "r"))
        attrs = {qn("w", "fldCharType"): "begin"}
        if field.locked: attrs[qn("w", "fldLock")] = "1"
        if field.dirty: attrs[qn("w", "dirty")] = "1"
        ET.SubElement(begin, qn("w", "fldChar"), attrs)
        instruction = ET.SubElement(parent, qn("w", "r"))
        ET.SubElement(instruction, qn("w", "instrText"), {qn("xml", "space"): "preserve"}).text = " " + field.code.strip() + " "
        separate = ET.SubElement(parent, qn("w", "r")); ET.SubElement(separate, qn("w", "fldChar"), {qn("w", "fldCharType"): "separate"})
        self._write_inlines(parent, field.children or [Text(self._field_placeholder(field.code))], part_name)
        end = ET.SubElement(parent, qn("w", "r")); ET.SubElement(end, qn("w", "fldChar"), {qn("w", "fldCharType"): "end"})

    # ---------- images ----------

    def _image_run(self, image: ImageInline, part_name: str) -> ET.Element:
        resource = self.doc.resources.get(image.resource_id)
        if resource is None:
            return self._missing_image_run(image, f"resource {image.resource_id!r} is absent")
        data = resource.data
        if data is None and resource.source_path:
            path = Path(resource.source_path)
            if path.exists() and path.is_file():
                data = path.read_bytes()
        if data is None:
            if self.options.missing_assets == "error":
                raise FileNotFoundError(f"missing image data for {resource.filename}")
            return self._missing_image_run(image, f"missing image: {resource.filename}")
        part, rel_target = self._add_image_part(resource, data)
        rid = self._relationship(part_name, REL_TYPES["image"], rel_target)
        width = image.width_pt or resource.width_pt or 144.0
        height = image.height_pt or resource.height_pt or 108.0
        cx = points_to_emu(width) or 1828800
        cy = points_to_emu(height) or 1371600
        drawing_id = self._next_drawing_id; self._next_drawing_id += 1
        run = ET.Element(qn("w", "r"))
        drawing = ET.SubElement(run, qn("w", "drawing"))
        if image.floating:
            container = ET.SubElement(drawing, qn("wp", "anchor"), {
                "distT": "0", "distB": "0", "distL": "114300", "distR": "114300",
                "simplePos": "0", "relativeHeight": "0", "behindDoc": "0", "locked": "0",
                "layoutInCell": "1", "allowOverlap": "1",
            })
            ET.SubElement(container, qn("wp", "simplePos"), {"x": "0", "y": "0"})
            pos_h = ET.SubElement(container, qn("wp", "positionH"), {"relativeFrom": "column"})
            ET.SubElement(pos_h, qn("wp", "align")).text = "center"
            pos_v = ET.SubElement(container, qn("wp", "positionV"), {"relativeFrom": "paragraph"})
            ET.SubElement(pos_v, qn("wp", "posOffset")).text = "0"
        else:
            container = ET.SubElement(drawing, qn("wp", "inline"), {"distT": "0", "distB": "0", "distL": "0", "distR": "0"})
        ET.SubElement(container, qn("wp", "extent"), {"cx": str(cx), "cy": str(cy)})
        ET.SubElement(container, qn("wp", "effectExtent"), {"l": "0", "t": "0", "r": "0", "b": "0"})
        docpr_attrs = {"id": str(drawing_id), "name": resource.filename or f"Picture {drawing_id}"}
        description = image.alt_text or resource.alt_text
        title = image.title or resource.title
        if description: docpr_attrs["descr"] = description
        if title: docpr_attrs["title"] = title
        ET.SubElement(container, qn("wp", "docPr"), docpr_attrs)
        ET.SubElement(container, qn("wp", "cNvGraphicFramePr"))
        if image.floating:
            wrap_tag = {"square": "wrapSquare", "tight": "wrapTight", "through": "wrapThrough", "topAndBottom": "wrapTopAndBottom", "none": "wrapNone"}.get(image.wrap or "square", "wrapSquare")
            wrap = ET.SubElement(container, qn("wp", wrap_tag))
            if wrap_tag == "wrapSquare": wrap.set("wrapText", "bothSides")
        graphic = ET.SubElement(container, qn("a", "graphic"))
        graphic_data = ET.SubElement(graphic, qn("a", "graphicData"), {"uri": NS["pic"]})
        pic = ET.SubElement(graphic_data, qn("pic", "pic"))
        nv = ET.SubElement(pic, qn("pic", "nvPicPr"))
        ET.SubElement(nv, qn("pic", "cNvPr"), docpr_attrs)
        ET.SubElement(nv, qn("pic", "cNvPicPr"))
        blip_fill = ET.SubElement(pic, qn("pic", "blipFill"))
        blip = ET.SubElement(blip_fill, qn("a", "blip"), {qn("r", "embed"): rid})
        if image.crop:
            ET.SubElement(blip_fill, qn("a", "srcRect"), {
                side: str(round(max(0.0, min(1.0, image.crop.get(side, 0.0))) * 100000))
                for side in ("l", "t", "r", "b")
            })
        stretch = ET.SubElement(blip_fill, qn("a", "stretch")); ET.SubElement(stretch, qn("a", "fillRect"))
        sppr = ET.SubElement(pic, qn("pic", "spPr"))
        xfrm = ET.SubElement(sppr, qn("a", "xfrm"))
        ET.SubElement(xfrm, qn("a", "off"), {"x": "0", "y": "0"})
        ET.SubElement(xfrm, qn("a", "ext"), {"cx": str(cx), "cy": str(cy)})
        geometry = ET.SubElement(sppr, qn("a", "prstGeom"), {"prst": "rect"}); ET.SubElement(geometry, qn("a", "avLst"))
        return run

    def _add_image_part(self, resource: Resource, data: bytes) -> tuple[str, str]:
        checksum = resource.checksum or sha256_bytes(data)
        existing = self._image_parts.get(checksum)
        if existing:
            return existing
        media_type = resource.media_type or "application/octet-stream"
        extension = Path(resource.filename).suffix.lower() or extension_for_media_type(media_type, ".bin")
        if media_type == "image/jpeg": extension = ".jpg"
        filename = sanitize_filename(Path(resource.filename).stem or "image", "image") + "-" + checksum[:12] + extension
        part = f"word/media/{filename}"
        self.builder.add_part(part, data)
        self.builder.add_default_content_type(extension, media_type)
        result = (part, "media/" + filename)
        self._image_parts[checksum] = result
        return result

    def _missing_image_run(self, image: ImageInline, reason: str) -> ET.Element:
        self._warnings.append(reason)
        return self._text_run("[" + (image.alt_text or reason) + "]", TextStyle(italic=True, color="A00000"))

    # ---------- lists ----------

    def _write_list(self, parent: ET.Element, block: ListBlock, part_name: str, depth: int) -> None:
        if block.marker == "terms" or any(item.term for item in block.items):
            for item in block.items:
                inlines: list[Inline] = []
                if item.term:
                    for inline in item.term:
                        if isinstance(inline, Text):
                            inlines.append(Text(inline.text, inline.style.merged(TextStyle(bold=True))))
                        else:
                            inlines.append(inline)
                    inlines.extend([Text(": ")])
                first = item.blocks[0] if item.blocks else Paragraph([])
                if isinstance(first, Paragraph):
                    inlines.extend(first.inlines)
                    parent.append(self._paragraph(inlines, first.style, None, part_name))
                    remaining = item.blocks[1:]
                else:
                    parent.append(self._paragraph(inlines, ParagraphStyle(), None, part_name))
                    remaining = item.blocks
                self._write_blocks(parent, remaining, part_name, depth + 1)
            return
        spec = self._numbering_by_object.get(id(block))
        if spec is None:
            return
        level = max(0, min(8, depth))
        for item in block.items:
            blocks = item.blocks or [Paragraph([])]
            first_emitted = False
            if item.checked is not None:
                prefix = "☒ " if item.checked else "☐ "
            else:
                prefix = ""
            for child in blocks:
                if isinstance(child, Paragraph) and not first_emitted:
                    inlines = ([Text(prefix)] if prefix else []) + list(child.inlines)
                    props = ListProperties(block.ordered, level, block.start, block.number_format,
                                           marker=block.marker, num_id=spec.num_id, checked=item.checked)
                    style = child.style.copy()
                    if not style.style_id: style.style_id = "ListParagraph"
                    parent.append(self._paragraph(inlines, style, props, part_name))
                    first_emitted = True
                elif isinstance(child, ListBlock):
                    self._write_list(parent, child, part_name, depth + 1)
                else:
                    self._write_block(parent, child, part_name, depth + 1)
            if not first_emitted:
                props = ListProperties(block.ordered, level, block.start, block.number_format,
                                       marker=block.marker, num_id=spec.num_id, checked=item.checked)
                parent.append(self._paragraph([Text(prefix)] if prefix else [], ParagraphStyle(style_id="ListParagraph"), props, part_name))

    # ---------- tables ----------

    def _table(self, table: Table, part_name: str) -> ET.Element:
        tbl = ET.Element(qn("w", "tbl"))
        pr = ET.SubElement(tbl, qn("w", "tblPr"))
        if table.style_id:
            ET.SubElement(pr, qn("w", "tblStyle"), {qn("w", "val"): self._safe_style_id(table.style_id)})
        width = points_to_twips(table.width_pt)
        ET.SubElement(pr, qn("w", "tblW"), {qn("w", "w"): str(width or 0), qn("w", "type"): "dxa" if width else "auto"})
        if table.align:
            ET.SubElement(pr, qn("w", "jc"), {qn("w", "val"): {"start": "left", "end": "right"}.get(table.align, table.align)})
        ET.SubElement(pr, qn("w", "tblLayout"), {qn("w", "type"): "fixed" if table.layout == "fixed" else "autofit"})
        if table.caption: ET.SubElement(pr, qn("w", "tblCaption"), {qn("w", "val"): table.caption})
        if table.description: ET.SubElement(pr, qn("w", "tblDescription"), {qn("w", "val"): table.description})
        if table.shading:
            ET.SubElement(pr, qn("w", "shd"), {qn("w", "val"): "clear", qn("w", "fill"): normalize_hex_color(table.shading, "FFFFFF") or "FFFFFF"})
        if table.cell_spacing_pt is not None:
            ET.SubElement(pr, qn("w", "tblCellSpacing"), {qn("w", "w"): str(points_to_twips(table.cell_spacing_pt) or 0), qn("w", "type"): "dxa"})
        borders = table.borders or {side: Border("single", 0.5, "BFBFBF") for side in ("top", "left", "bottom", "right", "insideH", "insideV")}
        border_root = ET.SubElement(pr, qn("w", "tblBorders")); self._append_borders(border_root, borders)
        if table.bidi: ET.SubElement(pr, qn("w", "bidiVisual"))

        placements, ncols = self._table_placements(table)
        grid = ET.SubElement(tbl, qn("w", "tblGrid"))
        widths = list(table.column_widths_pt)
        while len(widths) < ncols: widths.append(None)
        default_width = (table.width_pt / ncols) if table.width_pt and ncols else 72.0
        for col in range(ncols):
            ET.SubElement(grid, qn("w", "gridCol"), {qn("w", "w"): str(points_to_twips(widths[col] or default_width) or 1440)})

        for row_index, row in enumerate(table.rows):
            tr = ET.SubElement(tbl, qn("w", "tr"))
            trpr = ET.SubElement(tr, qn("w", "trPr"))
            if row.header: ET.SubElement(trpr, qn("w", "tblHeader"))
            if row.cant_split: ET.SubElement(trpr, qn("w", "cantSplit"))
            if row.height_pt is not None:
                ET.SubElement(trpr, qn("w", "trHeight"), {qn("w", "val"): str(points_to_twips(row.height_pt) or 0), qn("w", "hRule"): row.height_rule or "atLeast"})
            if not len(trpr): tr.remove(trpr)
            col = 0
            while col < ncols:
                placement = placements.get((row_index, col))
                if placement is None:
                    col += 1
                    continue
                cell, origin_row, origin_col, is_continuation = placement
                self._append_table_cell(tr, cell, part_name, is_continuation, row.header, widths, origin_col)
                col += max(1, cell.colspan)
        return tbl

    def _table_placements(self, table: Table) -> tuple[dict[tuple[int, int], tuple[TableCell, int, int, bool]], int]:
        occupied: dict[tuple[int, int], tuple[TableCell, int, int, bool]] = {}
        max_col = 0
        for r, row in enumerate(table.rows):
            col = 0
            for cell in row.cells:
                while (r, col) in occupied:
                    col += 1
                colspan = max(1, cell.colspan); rowspan = max(1, cell.rowspan)
                occupied[(r, col)] = (cell, r, col, False)
                for rr in range(r + 1, r + rowspan):
                    occupied[(rr, col)] = (cell, r, col, True)
                # Covered columns are marked with None sentinel by omission and skipped using colspan at starts.
                for rr in range(r, r + rowspan):
                    for cc in range(col + 1, col + colspan):
                        occupied[(rr, cc)] = (cell, r, col, True) if rr > r and cc == col else occupied.get((rr, cc), None)  # type: ignore[assignment]
                col += colspan
                max_col = max(max_col, col)
        # Remove internal span sentinels. Only origin or vertical continuation starts should emit a tc.
        cleaned: dict[tuple[int, int], tuple[TableCell, int, int, bool]] = {}
        for key, value in occupied.items():
            if value is None:
                continue
            cell, origin_r, origin_c, continuation = value
            if key[1] == origin_c:
                cleaned[key] = value
        return cleaned, max_col

    def _append_table_cell(self, tr: ET.Element, cell: TableCell, part_name: str,
                           continuation: bool, row_header: bool,
                           widths: list[float | None], origin_col: int) -> None:
        tc = ET.SubElement(tr, qn("w", "tc"))
        pr = ET.SubElement(tc, qn("w", "tcPr"))
        width = cell.width_pt
        if width is None and widths:
            width = sum((widths[index] or 72.0) for index in range(origin_col, min(len(widths), origin_col + max(1, cell.colspan))))
        if width is not None:
            ET.SubElement(pr, qn("w", "tcW"), {qn("w", "w"): str(points_to_twips(width) or 0), qn("w", "type"): "dxa"})
        if cell.colspan > 1:
            ET.SubElement(pr, qn("w", "gridSpan"), {qn("w", "val"): str(cell.colspan)})
        if cell.rowspan > 1:
            ET.SubElement(pr, qn("w", "vMerge"), {qn("w", "val"): "continue" if continuation else "restart"})
        if cell.vertical_align:
            ET.SubElement(pr, qn("w", "vAlign"), {qn("w", "val"): {"middle": "center"}.get(cell.vertical_align, cell.vertical_align)})
        if cell.text_direction:
            ET.SubElement(pr, qn("w", "textDirection"), {qn("w", "val"): cell.text_direction})
        if cell.shading:
            ET.SubElement(pr, qn("w", "shd"), {qn("w", "val"): "clear", qn("w", "fill"): normalize_hex_color(cell.shading, "FFFFFF") or "FFFFFF"})
        if cell.borders:
            borders = ET.SubElement(pr, qn("w", "tcBorders")); self._append_borders(borders, cell.borders)
        if cell.margins_pt:
            margins = ET.SubElement(pr, qn("w", "tcMar"))
            for side, value in cell.margins_pt.items():
                ET.SubElement(margins, qn("w", side), {qn("w", "w"): str(points_to_twips(value) or 0), qn("w", "type"): "dxa"})
        if continuation:
            ET.SubElement(tc, qn("w", "p"))
            return
        if cell.header or row_header:
            # Header semantics are represented at row level; preserve a cell hint too.
            ET.SubElement(pr, qn("w", "tcFitText"), {qn("w", "val"): "0"})
        self._write_blocks(tc, cell.blocks, part_name)
        if not any(child.tag == qn("w", "p") for child in tc):
            ET.SubElement(tc, qn("w", "p"))

    # ---------- notes, comments, content controls ----------

    def _note_id(self, note: NoteRef) -> int:
        key = (note.note_type, note.note_id)
        if key in self._note_ids:
            return self._note_ids[key]
        candidate = int(note.note_id) if str(note.note_id).isdigit() and int(note.note_id) > 0 else self._next_note_id[note.note_type]
        used = set(self._note_bodies[note.note_type])
        while candidate in used or candidate <= 0:
            candidate += 1
        self._next_note_id[note.note_type] = candidate + 1
        self._note_ids[key] = candidate
        body = note.body or (self.doc.footnotes.get(note.note_id, []) if note.note_type == "footnote" else self.doc.endnotes.get(note.note_id, []))
        self._note_bodies[note.note_type][candidate] = body
        return candidate

    def _add_notes_parts(self) -> None:
        for note_type in ("footnote", "endnote"):
            # Add notes referenced only through Document maps as well.
            source = self.doc.footnotes if note_type == "footnote" else self.doc.endnotes
            for key, body in source.items():
                if (note_type, str(key)) not in self._note_ids:
                    self._note_id(NoteRef(note_type, str(key), body))
            if not self._note_bodies[note_type]:
                continue
            plural = "footnotes" if note_type == "footnote" else "endnotes"
            item_tag = "footnote" if note_type == "footnote" else "endnote"
            root = ET.Element(qn("w", plural))
            separator = ET.SubElement(root, qn("w", item_tag), {qn("w", "id"): "-1", qn("w", "type"): "separator"})
            p = ET.SubElement(separator, qn("w", "p")); r = ET.SubElement(p, qn("w", "r")); ET.SubElement(r, qn("w", "separator"))
            continuation = ET.SubElement(root, qn("w", item_tag), {qn("w", "id"): "0", qn("w", "type"): "continuationSeparator"})
            p = ET.SubElement(continuation, qn("w", "p")); r = ET.SubElement(p, qn("w", "r")); ET.SubElement(r, qn("w", "continuationSeparator"))
            for note_id, blocks in sorted(self._note_bodies[note_type].items()):
                item = ET.SubElement(root, qn("w", item_tag), {qn("w", "id"): str(note_id)})
                self._write_blocks(item, blocks or [Paragraph([])], f"word/{plural}.xml")
            part = f"word/{plural}.xml"
            self.builder.add_part(part, root, CONTENT_TYPES[plural])
            self.builder.add_relationship(self.document_part, REL_TYPES[plural], f"{plural}.xml")

    def _register_comments(self) -> None:
        for key in self.doc.comments:
            self._comment_id(key)
        for block in self.doc.walk_blocks():
            for inline in self._block_inlines(block):
                if isinstance(inline, CommentAnchor):
                    self._comment_id(inline.comment_id)

    def _comment_id(self, key: str) -> int:
        key = str(key)
        if key in self._comment_ids:
            return self._comment_ids[key]
        candidate = int(key) if key.isdigit() and int(key) >= 0 else self._next_comment_id
        used = set(self._comment_ids.values())
        while candidate in used:
            candidate += 1
        self._next_comment_id = candidate + 1
        self._comment_ids[key] = candidate
        return candidate

    def _add_comments_part(self) -> None:
        if not self.options.preserve_comments or not self._comment_ids:
            return
        root = ET.Element(qn("w", "comments"))
        reverse = {value: key for key, value in self._comment_ids.items()}
        for numeric in sorted(reverse):
            key = reverse[numeric]
            comment = self.doc.comments.get(key)
            attrs = {qn("w", "id"): str(numeric), qn("w", "author"): (comment.author if comment else None) or self.options.creator or "typx"}
            if comment and comment.initials: attrs[qn("w", "initials")] = comment.initials
            if comment and comment.date: attrs[qn("w", "date")] = comment.date
            element = ET.SubElement(root, qn("w", "comment"), attrs)
            self._write_blocks(element, comment.blocks if comment and comment.blocks else [Paragraph([Text("Comment")])], "word/comments.xml")
        self.builder.add_part("word/comments.xml", root, CONTENT_TYPES["comments"])
        self.builder.add_relationship(self.document_part, REL_TYPES["comments"], "comments.xml")

    def _content_control(self, control: ContentControl, part_name: str) -> ET.Element:
        sdt = ET.Element(qn("w", "sdt"))
        pr = ET.SubElement(sdt, qn("w", "sdtPr"))
        if control.alias: ET.SubElement(pr, qn("w", "alias"), {qn("w", "val"): control.alias})
        if control.tag: ET.SubElement(pr, qn("w", "tag"), {qn("w", "val"): control.tag})
        if control.control_id: ET.SubElement(pr, qn("w", "id"), {qn("w", "val"): str(self._stable_numeric_id(control.control_id))})
        if control.lock: ET.SubElement(pr, qn("w", "lock"), {qn("w", "val"): control.lock})
        if control.data_binding:
            attrs = {}
            mapping = {"prefix_mappings": "prefixMappings", "xpath": "xpath", "store_item_id": "storeItemID"}
            for key, value in control.data_binding.items():
                attrs[qn("w", mapping.get(key, key))] = value
            ET.SubElement(pr, qn("w", "dataBinding"), attrs)
        kind = control.control_type or "richText"
        kind_tag = {"checkbox": "checkBox", "date": "date", "dropdown": "dropDownList", "combo": "comboBox",
                    "picture": "picture", "group": "group", "repeatingSection": "repeatingSection",
                    "plainText": "text", "richText": "richText"}.get(kind, kind)
        ET.SubElement(pr, qn("w", kind_tag))
        content = ET.SubElement(sdt, qn("w", "sdtContent"))
        self._write_blocks(content, control.blocks or [Paragraph([])], part_name)
        return sdt

    # ---------- sections and headers ----------

    def _section_properties(self, section: SectionProperties, part_name: str) -> ET.Element:
        sect = ET.Element(qn("w", "sectPr"))
        for category in ("header", "footer"):
            for kind in ("default", "first", "even"):
                blocks = getattr(section, f"{category}_{kind}")
                if blocks:
                    target, rid = self._add_header_footer(category, blocks, part_name)
                    ET.SubElement(sect, qn("w", f"{category}Reference"), {qn("w", "type"): kind, qn("r", "id"): rid})
        ET.SubElement(sect, qn("w", "pgSz"), {
            qn("w", "w"): str(points_to_twips(section.page_width_pt) or 11906),
            qn("w", "h"): str(points_to_twips(section.page_height_pt) or 16838),
            **({qn("w", "orient"): section.orientation} if section.orientation and section.orientation != "portrait" else {}),
        })
        ET.SubElement(sect, qn("w", "pgMar"), {
            qn("w", "top"): str(points_to_twips(section.margin_top_pt) or 1440),
            qn("w", "right"): str(points_to_twips(section.margin_right_pt) or 1440),
            qn("w", "bottom"): str(points_to_twips(section.margin_bottom_pt) or 1440),
            qn("w", "left"): str(points_to_twips(section.margin_left_pt) or 1440),
            qn("w", "header"): str(points_to_twips(section.header_distance_pt) or 720),
            qn("w", "footer"): str(points_to_twips(section.footer_distance_pt) or 720),
            qn("w", "gutter"): str(points_to_twips(section.gutter_pt) or 0),
        })
        cols_attrs = {qn("w", "num"): str(max(1, section.columns)),
                      qn("w", "space"): str(points_to_twips(section.column_spacing_pt) or 720),
                      qn("w", "equalWidth"): "1" if section.equal_column_width else "0"}
        cols = ET.SubElement(sect, qn("w", "cols"), cols_attrs)
        if not section.equal_column_width and section.column_widths_pt:
            for width in section.column_widths_pt:
                ET.SubElement(cols, qn("w", "col"), {qn("w", "w"): str(points_to_twips(width) or 0)})
        if section.page_number_start is not None or section.page_number_format:
            attrs = {}
            if section.page_number_start is not None: attrs[qn("w", "start")] = str(section.page_number_start)
            if section.page_number_format: attrs[qn("w", "fmt")] = section.page_number_format
            ET.SubElement(sect, qn("w", "pgNumType"), attrs)
        if section.title_page: ET.SubElement(sect, qn("w", "titlePg"))
        if section.vertical_align: ET.SubElement(sect, qn("w", "vAlign"), {qn("w", "val"): section.vertical_align})
        if section.line_numbering:
            attrs = {}
            mapping = {"count_by": "countBy", "distance_pt": "distance", "restart": "restart", "start": "start"}
            for key, value in section.line_numbering.items():
                if value is None: continue
                attrs[qn("w", mapping.get(key, key))] = str(points_to_twips(value) if key == "distance_pt" else value)
            ET.SubElement(sect, qn("w", "lnNumType"), attrs)
        return sect

    def _add_header_footer(self, category: str, blocks: list[Block], source_part: str) -> tuple[str, str]:
        self._header_footer_index[category] += 1
        index = self._header_footer_index[category]
        part = f"word/{category}{index}.xml"
        root = ET.Element(qn("w", "hdr" if category == "header" else "ftr"))
        self._write_blocks(root, blocks, part)
        self.builder.add_part(part, root, CONTENT_TYPES[category])
        rid = self._relationship(source_part, REL_TYPES[category], f"{category}{index}.xml")
        return part, rid

    # ---------- raw and relationships ----------

    def _relationship(self, source: str, rel_type: str, target: str,
                      target_mode: str | None = None) -> str:
        key = (source, rel_type, target, target_mode)
        if key in self._part_rel_cache:
            return self._part_rel_cache[key]
        rid = self.builder.add_relationship(source, rel_type, target, target_mode=target_mode)
        self._part_rel_cache[key] = rid
        return rid

    def _decode_raw_element(self, data: str) -> ET.Element | None:
        try:
            payload = decode_raw_fragment(data)
            if not payload:
                return None
            return parse_xml(payload)
        except (ValueError, ET.ParseError):
            return None

    @staticmethod
    def _is_block_element(element: ET.Element) -> bool:
        return element.tag in {qn("w", name) for name in ("p", "tbl", "sdt", "customXml", "altChunk", "ins", "del", "moveFrom", "moveTo")}

    @staticmethod
    def _is_inline_element(element: ET.Element) -> bool:
        return element.tag in {qn("w", name) for name in ("r", "hyperlink", "sdt", "customXml", "smartTag", "fldSimple",
                                                                   "bookmarkStart", "bookmarkEnd", "commentRangeStart", "commentRangeEnd",
                                                                   "ins", "del", "moveFrom", "moveTo")} or element.tag in {qn("m", "oMath"), qn("m", "oMathPara")}

    def _decode_omml(self, encoded: str | None, display: bool) -> ET.Element | None:
        if not encoded:
            return None
        try:
            element = parse_xml(decode_raw_fragment(encoded))
        except (ValueError, ET.ParseError):
            return None
        if display and element.tag == qn("m", "oMath"):
            para = ET.Element(qn("m", "oMathPara")); para.append(element); return para
        if not display and element.tag == qn("m", "oMathPara"):
            math = element.find(qn("m", "oMath")); return math
        return element

    # ---------- small helpers ----------

    def _append_borders(self, parent: ET.Element, borders: dict[str, Border]) -> None:
        name_map = {"inside_h": "insideH", "inside_v": "insideV"}
        for side, border in borders.items():
            if not isinstance(border, Border):
                continue
            size = max(2, min(96, round(border.width_pt * 8)))
            attrs = {qn("w", "val"): border.style or "single", qn("w", "sz"): str(size),
                     qn("w", "space"): str(max(0, round(border.space_pt))),
                     qn("w", "color"): normalize_hex_color(border.color, "000000") or "000000"}
            if border.shadow: attrs[qn("w", "shadow")] = "1"
            ET.SubElement(parent, qn("w", name_map.get(side, side)), attrs)

    def _bookmark_id(self, name: str, preferred: str | None = None) -> int:
        key = self._safe_bookmark_name(name)
        if key in self._bookmark_ids:
            return self._bookmark_ids[key]
        candidate = int(preferred) if preferred and str(preferred).isdigit() else self._next_bookmark_id
        used = set(self._bookmark_ids.values())
        while candidate in used or candidate < 0:
            candidate += 1
        self._next_bookmark_id = candidate + 1
        self._bookmark_ids[key] = candidate
        return candidate

    def _wrap_paragraph_bookmark(self, paragraph: ET.Element, label: str) -> None:
        bookmark_id = self._bookmark_id(label)
        start = ET.Element(qn("w", "bookmarkStart"), {qn("w", "id"): str(bookmark_id), qn("w", "name"): self._safe_bookmark_name(label)})
        end = ET.Element(qn("w", "bookmarkEnd"), {qn("w", "id"): str(bookmark_id)})
        insert_at = 1 if len(paragraph) and paragraph[0].tag == qn("w", "pPr") else 0
        paragraph.insert(insert_at, start); paragraph.append(end)

    @staticmethod
    def _safe_bookmark_name(value: str) -> str:
        value = re.sub(r"[^A-Za-z0-9_]", "_", value.lstrip("#"))
        if not value or not value[0].isalpha(): value = "b_" + value
        return value[:40]

    @staticmethod
    def _safe_style_id(value: str) -> str:
        cleaned = re.sub(r"[^A-Za-z0-9_]", "", value.replace(" ", ""))
        return (cleaned or "Style")[:253]

    @staticmethod
    def _stable_numeric_id(value: str) -> int:
        if str(value).isdigit(): return int(value)
        return int(hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:7], 16)

    @staticmethod
    def _field_placeholder(code: str) -> str:
        command = code.strip().split(maxsplit=1)[0].upper() if code.strip() else "FIELD"
        return {"PAGE": "1", "NUMPAGES": "1", "DATE": "2000-01-01", "TIME": "00:00",
                "TOC": "Table of contents", "SEQ": "1"}.get(command, "[" + command + "]")

    @staticmethod
    def _num_format(value: str, level: int) -> str:
        mapping = {"1": "decimal", "a": "lowerLetter", "A": "upperLetter", "i": "lowerRoman", "I": "upperRoman",
                   "decimal": "decimal", "lower-alpha": "lowerLetter", "upper-alpha": "upperLetter",
                   "lower-roman": "lowerRoman", "upper-roman": "upperRoman"}
        return mapping.get(value, value if value in {"decimal", "lowerLetter", "upperLetter", "lowerRoman", "upperRoman", "ordinal", "cardinalText"} else "decimal")

    @staticmethod
    def _number_pattern(fmt: str, level: int) -> str:
        suffix = ")" if fmt in {"lowerLetter", "upperLetter"} else "."
        return f"%{level + 1}{suffix}"

    @staticmethod
    def _block_inlines(block: Block) -> Iterable[Inline]:
        if isinstance(block, (Paragraph, Heading)):
            yield from block.inlines
        elif isinstance(block, Figure):
            yield from block.caption
        elif isinstance(block, Quote):
            yield from block.attribution


__all__ = ["DocxWriteOptions", "DocxWriter"]
