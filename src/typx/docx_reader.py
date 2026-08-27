from __future__ import annotations

import hashlib
import posixpath
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Literal

from .constants import NS, REL_TYPES
from .docx_package import DocxPackage, Relationship
from .model import (
    Block,
    Bookmark,
    Border,
    Break,
    BreakBlock,
    Change,
    Citation,
    CodeBlock,
    Comment,
    CommentAnchor,
    ContentControl,
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
    TabStop,
    Table,
    TableCell,
    TableRow,
    Text,
    TextStyle,
)
from .omml import omml_to_typst
from .roundtrip import encode_raw_fragment
from .util import (
    attr,
    bool_attr,
    child,
    children,
    coalesce_text,
    emu_to_points,
    extension_for_media_type,
    guess_media_type,
    half_points_to_points,
    image_dimensions,
    local_name,
    normalize_hex_color,
    ooxml_highlight_to_hex,
    parse_float,
    parse_int,
    qn,
    resolve_part_target,
    sanitize_filename,
    text_from_inlines,
    twips_to_points,
    xml_bytes,
)


@dataclass(slots=True)
class DocxReadOptions:
    revisions: Literal["accept", "reject", "annotate", "preserve"] = "annotate"
    comments: Literal["preserve", "drop"] = "preserve"
    unknown: Literal["preserve", "drop"] = "preserve"
    extract_assets: bool = True
    assets_dir: Path | None = None
    preserve_package_parts: bool = False
    max_unknown_fragment_bytes: int = 16 * 1024 * 1024


@dataclass(slots=True)
class NumberingLevel:
    level: int
    start: int = 1
    num_format: str = "decimal"
    text: str = "%1."
    suffix: str = "tab"
    paragraph: ParagraphStyle = field(default_factory=ParagraphStyle)
    text_style: TextStyle = field(default_factory=TextStyle)
    restart_after_level: int | None = None
    legal: bool = False
    picture_bullet_id: str | None = None


@dataclass(slots=True)
class NumberingInstance:
    num_id: int
    abstract_id: int
    overrides: dict[int, NumberingLevel] = field(default_factory=dict)
    start_overrides: dict[int, int] = field(default_factory=dict)


@dataclass(slots=True)
class _FieldState:
    code: list[str] = field(default_factory=list)
    result: list[Inline] = field(default_factory=list)
    separated: bool = False
    locked: bool = False
    dirty: bool = False


class DocxReader:
    def __init__(self, package: DocxPackage, options: DocxReadOptions | None = None):
        self.package = package
        self.options = options or DocxReadOptions()
        self.document_part = package.office_document_part()
        self.document_rels = package.relationships(self.document_part)
        self.doc = Document(source_format="docx")
        self.styles: dict[str, StyleDefinition] = {}
        self.style_names: dict[str, str] = {}
        self.numbering_levels: dict[int, dict[int, NumberingLevel]] = {}
        self.numbering_instances: dict[int, NumberingInstance] = {}
        self.notes: dict[str, dict[str, list[Block]]] = {"footnote": {}, "endnote": {}}
        self.comment_ranges: dict[str, Comment] = {}
        self._resource_by_part: dict[str, str] = {}
        self._bookmark_names: dict[str, str] = {}
        self._section_index = 0

    @classmethod
    def read(cls, source: str | Path | bytes,
             options: DocxReadOptions | None = None) -> Document:
        package = DocxPackage.open(source)
        return cls(package, options).parse()

    def parse(self) -> Document:
        self._parse_metadata()
        self._parse_styles()
        self._parse_numbering()
        self._parse_comments()
        self._parse_notes("footnote")
        self._parse_notes("endnote")
        root = self.package.xml(self.document_part)
        body = root.find(qn("w", "body"))
        if body is None:
            raise ValueError("word/document.xml has no w:body")
        raw_blocks = self._parse_block_children(body, self.document_part)
        self.doc.blocks = self._group_lists(raw_blocks)
        if not self.doc.sections:
            self.doc.sections = [SectionProperties()]
        self.doc.styles = self.styles
        self.doc.footnotes = self.notes["footnote"]
        self.doc.endnotes = self.notes["endnote"]
        self.doc.comments = self.comment_ranges
        self.doc.source_path = None
        if self.options.preserve_package_parts:
            self.doc.raw_package_parts = dict(self.package.parts)
        return self.doc

    # ---------- package-level parts ----------

    def _parse_metadata(self) -> None:
        root_rels = self.package.relationships("")
        core_part = None
        app_part = None
        custom_part = None
        for rel in root_rels.values():
            if rel.external:
                continue
            if rel.type == REL_TYPES["core_properties"]:
                core_part = rel.resolved_target
            elif rel.type == REL_TYPES["extended_properties"]:
                app_part = rel.resolved_target
            elif rel.type == REL_TYPES["custom_properties"]:
                custom_part = rel.resolved_target
        if core_part and self.package.get(core_part):
            root = self.package.xml(core_part)
            mapping = {
                (NS["dc"], "title"): "title",
                (NS["dc"], "subject"): "subject",
                (NS["dc"], "creator"): "author",
                (NS["cp"], "keywords"): "keywords",
                (NS["dc"], "description"): "description",
                (NS["cp"], "lastModifiedBy"): "last_modified_by",
                (NS["cp"], "revision"): "revision",
                (NS["dcterms"], "created"): "created",
                (NS["dcterms"], "modified"): "modified",
                (NS["cp"], "category"): "category",
                (NS["cp"], "contentStatus"): "content_status",
                (NS["dc"], "language"): "language",
                (NS["cp"], "version"): "version",
            }
            for item in root:
                key = mapping.get((item.tag[1:].split("}", 1)[0], local_name(item.tag))) if item.tag.startswith("{") else None
                if key and item.text:
                    self.doc.metadata[key] = item.text
        if app_part and self.package.get(app_part):
            root = self.package.xml(app_part)
            for item in root:
                key = local_name(item.tag)
                if item.text and key in {"Application", "AppVersion", "Company", "Manager", "Template",
                                         "Pages", "Words", "Characters", "Lines", "Paragraphs"}:
                    self.doc.metadata[f"app_{key.lower()}"] = item.text
        if custom_part and self.package.get(custom_part):
            root = self.package.xml(custom_part)
            for prop in root:
                name = prop.get("name") or attr(prop, "name", "", "cust")
                value = None
                if len(prop):
                    value_element = prop[0]
                    kind = local_name(value_element.tag)
                    text = value_element.text or ""
                    if kind in {"i1", "i2", "i4", "i8", "int", "uint"}:
                        value = parse_int(text, 0)
                    elif kind in {"r4", "r8", "decimal"}:
                        value = parse_float(text, 0.0)
                    elif kind == "bool":
                        value = text.lower() in {"true", "1"}
                    else:
                        value = text
                if name:
                    self.doc.custom_properties[name] = value

    def _part_for_rel_type(self, rel_type: str) -> str | None:
        for rel in self.document_rels.values():
            if rel.type == rel_type and not rel.external:
                return rel.resolved_target
        return None

    def _parse_styles(self) -> None:
        styles_part = self._part_for_rel_type(REL_TYPES["styles"])
        if not styles_part or not self.package.get(styles_part):
            return
        root = self.package.xml(styles_part)
        doc_defaults = root.find(qn("w", "docDefaults"))
        default_rpr = child(child(doc_defaults, "rPrDefault"), "rPr")
        default_ppr = child(child(doc_defaults, "pPrDefault"), "pPr")
        default_style = StyleDefinition(
            style_id="__docDefaults__",
            name="Document Defaults",
            paragraph=self._parse_ppr(default_ppr),
            text=self._parse_rpr(default_rpr),
        )
        default_style.paragraph.default_text_style = default_style.text.copy()
        self.styles[default_style.style_id] = default_style

        for style in root.findall(qn("w", "style")):
            style_id = attr(style, "styleId", "")
            if not style_id:
                continue
            name = attr(child(style, "name"), "val")
            definition = StyleDefinition(
                style_id=style_id,
                name=name,
                style_type=attr(style, "type", "paragraph"),
                based_on=attr(child(style, "basedOn"), "val"),
                next_style=attr(child(style, "next"), "val"),
                linked_style=attr(child(style, "link"), "val"),
                ui_priority=parse_int(attr(child(style, "uiPriority"), "val")),
                qformat=child(style, "qFormat") is not None,
                hidden=child(style, "hidden") is not None,
                semi_hidden=child(style, "semiHidden") is not None,
                unhide_when_used=child(style, "unhideWhenUsed") is not None,
                paragraph=self._parse_ppr(child(style, "pPr")),
                text=self._parse_rpr(child(style, "rPr")),
                raw={"custom": bool_attr(style, "customStyle", False)},
            )
            definition.paragraph.default_text_style = definition.text.copy()
            self.styles[style_id] = definition
            if name:
                self.style_names[style_id] = name

        # Resolve style inheritance and document defaults.
        resolving: set[str] = set()
        resolved: dict[str, StyleDefinition] = {}

        def resolve(style_id: str) -> StyleDefinition:
            if style_id in resolved:
                return resolved[style_id]
            style = self.styles[style_id]
            if style_id in resolving:
                self.doc.warnings.append(f"cyclic style inheritance at {style_id}")
                return style
            resolving.add(style_id)
            base = self.styles.get(style.based_on or "")
            if base is not None and base.style_id != style_id:
                base = resolve(base.style_id)
            elif style.style_id != "__docDefaults__":
                base = self.styles.get("__docDefaults__")
            if base:
                style.paragraph = base.paragraph.merged(style.paragraph)
                style.text = base.text.merged(style.text)
                style.paragraph.default_text_style = style.text.copy()
            resolving.remove(style_id)
            resolved[style_id] = style
            return style

        for style_id in list(self.styles):
            resolve(style_id)

    def _parse_numbering(self) -> None:
        numbering_part = self._part_for_rel_type(REL_TYPES["numbering"])
        if not numbering_part or not self.package.get(numbering_part):
            return
        root = self.package.xml(numbering_part)
        for abstract in root.findall(qn("w", "abstractNum")):
            abstract_id = parse_int(attr(abstract, "abstractNumId"), 0) or 0
            levels: dict[int, NumberingLevel] = {}
            for lvl in abstract.findall(qn("w", "lvl")):
                level = parse_int(attr(lvl, "ilvl"), 0) or 0
                levels[level] = self._parse_numbering_level(lvl, level)
            self.numbering_levels[abstract_id] = levels
        for num in root.findall(qn("w", "num")):
            num_id = parse_int(attr(num, "numId"), 0) or 0
            abstract_id = parse_int(attr(child(num, "abstractNumId"), "val"), 0) or 0
            instance = NumberingInstance(num_id, abstract_id)
            for override in num.findall(qn("w", "lvlOverride")):
                level = parse_int(attr(override, "ilvl"), 0) or 0
                start_override = parse_int(attr(child(override, "startOverride"), "val"))
                if start_override is not None:
                    instance.start_overrides[level] = start_override
                lvl = child(override, "lvl")
                if lvl is not None:
                    instance.overrides[level] = self._parse_numbering_level(lvl, level)
            self.numbering_instances[num_id] = instance

    def _parse_numbering_level(self, lvl: ET.Element, level: int) -> NumberingLevel:
        return NumberingLevel(
            level=level,
            start=parse_int(attr(child(lvl, "start"), "val"), 1) or 1,
            num_format=attr(child(lvl, "numFmt"), "val", "decimal"),
            text=attr(child(lvl, "lvlText"), "val", f"%{level + 1}."),
            suffix=attr(child(lvl, "suff"), "val", "tab"),
            paragraph=self._parse_ppr(child(lvl, "pPr")),
            text_style=self._parse_rpr(child(lvl, "rPr")),
            restart_after_level=parse_int(attr(child(lvl, "lvlRestart"), "val")),
            legal=child(lvl, "isLgl") is not None,
            picture_bullet_id=attr(child(lvl, "lvlPicBulletId"), "val"),
        )

    def _parse_comments(self) -> None:
        if self.options.comments == "drop":
            return
        comments_part = self._part_for_rel_type(REL_TYPES["comments"])
        if not comments_part or not self.package.get(comments_part):
            return
        root = self.package.xml(comments_part)
        for comment in root.findall(qn("w", "comment")):
            comment_id = attr(comment, "id", "")
            if not comment_id:
                continue
            blocks = self._group_lists(self._parse_block_children(comment, comments_part))
            self.comment_ranges[comment_id] = Comment(
                comment_id=comment_id,
                author=attr(comment, "author"),
                initials=attr(comment, "initials"),
                date=attr(comment, "date"),
                blocks=blocks,
            )

    def _parse_notes(self, note_type: Literal["footnote", "endnote"]) -> None:
        rel_type = REL_TYPES["footnotes" if note_type == "footnote" else "endnotes"]
        part = self._part_for_rel_type(rel_type)
        if not part or not self.package.get(part):
            return
        root = self.package.xml(part)
        item_tag = "footnote" if note_type == "footnote" else "endnote"
        for note in root.findall(qn("w", item_tag)):
            note_id = attr(note, "id", "")
            if not note_id or note_id.startswith("-"):
                continue
            self.notes[note_type][note_id] = self._group_lists(self._parse_block_children(note, part))

    # ---------- property parsing ----------

    def _parse_rpr(self, rpr: ET.Element | None) -> TextStyle:
        if rpr is None:
            return TextStyle()
        fonts = child(rpr, "rFonts")
        color = child(rpr, "color")
        underline = child(rpr, "u")
        highlight = child(rpr, "highlight")
        shading = child(rpr, "shd")
        lang = child(rpr, "lang")
        style = TextStyle(
            bold=bool_attr(child(rpr, "b")) if child(rpr, "b") is not None else None,
            italic=bool_attr(child(rpr, "i")) if child(rpr, "i") is not None else None,
            underline=(attr(underline, "val", "single") if underline is not None and attr(underline, "val", "single") not in {"none", "0"} else None),
            strike=bool_attr(child(rpr, "strike")) if child(rpr, "strike") is not None else None,
            double_strike=bool_attr(child(rpr, "dstrike")) if child(rpr, "dstrike") is not None else None,
            small_caps=bool_attr(child(rpr, "smallCaps")) if child(rpr, "smallCaps") is not None else None,
            all_caps=bool_attr(child(rpr, "caps")) if child(rpr, "caps") is not None else None,
            hidden=bool_attr(child(rpr, "vanish")) if child(rpr, "vanish") is not None else None,
            font=attr(fonts, "ascii") or attr(fonts, "hAnsi") or attr(fonts, "cs"),
            font_east_asia=attr(fonts, "eastAsia"),
            font_complex=attr(fonts, "cs"),
            size_pt=half_points_to_points(attr(child(rpr, "sz"), "val")),
            color=normalize_hex_color(attr(color, "val")) if color is not None and attr(color, "val") != "auto" else None,
            highlight=ooxml_highlight_to_hex(attr(highlight, "val")) if highlight is not None else normalize_hex_color(attr(shading, "fill")) if shading is not None else None,
            language=attr(lang, "val"),
            language_east_asia=attr(lang, "eastAsia"),
            language_complex=attr(lang, "bidi"),
            letter_spacing_pt=twips_to_points(attr(child(rpr, "spacing"), "val")),
            scale_percent=parse_int(attr(child(rpr, "w"), "val")),
            baseline_pt=half_points_to_points(attr(child(rpr, "position"), "val")),
            rtl=bool_attr(child(rpr, "rtl")) if child(rpr, "rtl") is not None else None,
            no_proof=bool_attr(child(rpr, "noProof")) if child(rpr, "noProof") is not None else None,
            emboss=bool_attr(child(rpr, "emboss")) if child(rpr, "emboss") is not None else None,
            imprint=bool_attr(child(rpr, "imprint")) if child(rpr, "imprint") is not None else None,
            outline=bool_attr(child(rpr, "outline")) if child(rpr, "outline") is not None else None,
            shadow=bool_attr(child(rpr, "shadow")) if child(rpr, "shadow") is not None else None,
        )
        vert_align = attr(child(rpr, "vertAlign"), "val")
        if vert_align == "superscript":
            style.superscript = True
        elif vert_align == "subscript":
            style.subscript = True
        if underline is not None:
            underline_color = normalize_hex_color(attr(underline, "color"))
            if underline_color:
                style.raw["underline_color"] = underline_color
        rstyle = attr(child(rpr, "rStyle"), "val")
        if rstyle:
            style.raw["style_id"] = rstyle
            definition = self.styles.get(rstyle)
            if definition:
                style = definition.text.merged(style)
        # Preserve unsupported text effects from Office extensions.
        known = {
            "rStyle", "rFonts", "b", "bCs", "i", "iCs", "caps", "smallCaps", "strike",
            "dstrike", "outline", "shadow", "emboss", "imprint", "noProof", "snapToGrid",
            "vanish", "webHidden", "color", "spacing", "w", "kern", "position", "sz", "szCs",
            "highlight", "u", "effect", "bdr", "shd", "fitText", "vertAlign", "rtl", "cs", "em",
            "lang", "eastAsianLayout", "specVanish", "oMath",
        }
        for item in rpr:
            if local_name(item.tag) not in known:
                style.text_effects[local_name(item.tag)] = encode_raw_fragment(xml_bytes(item))
        return style

    def _parse_ppr(self, ppr: ET.Element | None) -> ParagraphStyle:
        if ppr is None:
            return ParagraphStyle()
        spacing = child(ppr, "spacing")
        ind = child(ppr, "ind")
        shading = child(ppr, "shd")
        style = ParagraphStyle(
            style_id=attr(child(ppr, "pStyle"), "val"),
            align=attr(child(ppr, "jc"), "val"),
            left_indent_pt=twips_to_points(attr(ind, "left") or attr(ind, "start")),
            right_indent_pt=twips_to_points(attr(ind, "right") or attr(ind, "end")),
            first_line_indent_pt=twips_to_points(attr(ind, "firstLine")),
            hanging_indent_pt=twips_to_points(attr(ind, "hanging")),
            space_before_pt=twips_to_points(attr(spacing, "before")),
            space_after_pt=twips_to_points(attr(spacing, "after")),
            keep_next=bool_attr(child(ppr, "keepNext")) if child(ppr, "keepNext") is not None else None,
            keep_lines=bool_attr(child(ppr, "keepLines")) if child(ppr, "keepLines") is not None else None,
            page_break_before=bool_attr(child(ppr, "pageBreakBefore")) if child(ppr, "pageBreakBefore") is not None else None,
            widow_control=bool_attr(child(ppr, "widowControl")) if child(ppr, "widowControl") is not None else None,
            contextual_spacing=bool_attr(child(ppr, "contextualSpacing")) if child(ppr, "contextualSpacing") is not None else None,
            mirror_indents=bool_attr(child(ppr, "mirrorIndents")) if child(ppr, "mirrorIndents") is not None else None,
            suppress_line_numbers=bool_attr(child(ppr, "suppressLineNumbers")) if child(ppr, "suppressLineNumbers") is not None else None,
            bidi=bool_attr(child(ppr, "bidi")) if child(ppr, "bidi") is not None else None,
            text_direction=attr(child(ppr, "textDirection"), "val"),
            shading=normalize_hex_color(attr(shading, "fill")) if shading is not None else None,
            outline_level=parse_int(attr(child(ppr, "outlineLvl"), "val")),
        )
        line_value = parse_float(attr(spacing, "line"))
        line_rule = attr(spacing, "lineRule")
        if line_value is not None:
            if line_rule in {None, "auto"}:
                style.line_spacing = line_value / 240.0
                style.line_spacing_rule = "auto"
            else:
                style.line_spacing = line_value / 20.0
                style.line_spacing_rule = line_rule
        pbdr = child(ppr, "pBdr")
        if pbdr is not None:
            for side in pbdr:
                style.borders[local_name(side.tag)] = self._parse_border(side)
        tabs = child(ppr, "tabs")
        if tabs is not None:
            for tab in tabs.findall(qn("w", "tab")):
                pos = twips_to_points(attr(tab, "pos"))
                if pos is not None:
                    style.tabs.append(TabStop(pos, attr(tab, "val", "left"), attr(tab, "leader", "none")))
        rpr = child(ppr, "rPr")
        if rpr is not None:
            style.default_text_style = self._parse_rpr(rpr)
        num_pr = child(ppr, "numPr")
        if num_pr is not None:
            num_id = parse_int(attr(child(num_pr, "numId"), "val"))
            num_level = parse_int(attr(child(num_pr, "ilvl"), "val"), 0)
            if num_id is not None:
                style.raw["num_id"] = num_id
                style.raw["num_level"] = num_level or 0
        if style.style_id:
            definition = self.styles.get(style.style_id)
            if definition:
                style = definition.paragraph.merged(style)
        return style

    def _parse_border(self, element: ET.Element) -> Border:
        width_eighth_pt = parse_float(attr(element, "sz"), 4.0) or 4.0
        return Border(
            style=attr(element, "val", "single"),
            width_pt=width_eighth_pt / 8.0,
            color=normalize_hex_color(attr(element, "color"), "000000") or "000000",
            space_pt=parse_float(attr(element, "space"), 0.0) or 0.0,
            shadow=bool_attr(element, "shadow", False) or False,
        )

    # ---------- body parsing ----------

    def _parse_block_children(self, parent: ET.Element, part_name: str) -> list[Block]:
        blocks: list[Block] = []
        for element in parent:
            tag = local_name(element.tag)
            if tag in {"tblPr", "tblGrid", "trPr", "tcPr", "sdtPr", "sdtEndPr"}:
                continue
            if tag == "p":
                paragraph_or_heading = self._parse_paragraph(element, part_name)
                if paragraph_or_heading is not None:
                    blocks.append(paragraph_or_heading)
                sect_pr = child(child(element, "pPr"), "sectPr")
                if sect_pr is not None:
                    section = self._parse_section(sect_pr, part_name)
                    blocks.append(BreakBlock("section", section))
            elif tag == "tbl":
                blocks.append(self._parse_table(element, part_name))
            elif tag == "sdt":
                blocks.append(self._parse_content_control(element, part_name))
            elif tag in {"customXml", "smartTag"}:
                blocks.extend(self._parse_block_children(element, part_name))
            elif tag in {"ins", "del", "moveFrom", "moveTo"}:
                accepted = self._revision_block_content(element, part_name, tag)
                blocks.extend(accepted)
            elif tag == "altChunk":
                blocks.append(self._parse_alt_chunk(element, part_name))
            elif tag == "sectPr":
                section = self._parse_section(element, part_name)
                if not self.doc.sections:
                    self.doc.sections.append(section)
                else:
                    self.doc.sections[-1] = section
            elif tag in {"proofErr", "permStart", "permEnd", "bookmarkStart", "bookmarkEnd"}:
                continue
            elif tag in {"oMathPara", "oMath"} and element.tag.startswith("{" + NS["m"]):
                blocks.append(MathBlock(omml_to_typst(element), omml=encode_raw_fragment(xml_bytes(element))))
            elif self.options.unknown == "preserve":
                blocks.append(self._raw_block(element, description=f"Unsupported DOCX block w:{tag}"))
        return blocks

    def _parse_paragraph(self, paragraph: ET.Element, part_name: str) -> Block | None:
        ppr = child(paragraph, "pPr")
        style = self._parse_ppr(ppr)
        list_props = self._parse_list_properties(ppr, style)
        inlines = self._parse_inline_children(paragraph, part_name, style.default_text_style)
        inlines = coalesce_text(inlines)
        # Empty structural paragraphs still matter for spacing or breaks.
        if not inlines and ppr is None:
            return Paragraph([])
        style_id = style.style_id or ""
        style_name = self.style_names.get(style_id, style_id)
        normalized_name = re.sub(r"[^a-z0-9]+", "", style_name.lower())
        level = style.outline_level
        if level is None:
            heading_match = re.match(r"heading(\d+)$", normalized_name)
            if heading_match:
                level = max(0, int(heading_match.group(1)) - 1)
            elif normalized_name in {"title", "documenttitle"}:
                level = -1
        label = None
        for inline in inlines:
            if isinstance(inline, Bookmark) and not inline.end:
                label = inline.name
                break
        semantic_inlines = [inline for inline in inlines if not isinstance(inline, Bookmark)]
        if (list_props is None and len(semantic_inlines) == 1
                and isinstance(semantic_inlines[0], MathInline)
                and semantic_inlines[0].display):
            math = semantic_inlines[0]
            return MathBlock(math.typst, omml=math.omml, label=label)
        if level is not None and level <= 8:
            return Heading(
                level=0 if level < 0 else level + 1,
                inlines=inlines,
                label=label,
                style=style,
            )
        return Paragraph(inlines, style=style, list_props=list_props)

    def _parse_list_properties(self, ppr: ET.Element | None, style: ParagraphStyle | None = None) -> ListProperties | None:
        num_pr = child(ppr, "numPr")
        num_id = parse_int(attr(child(num_pr, "numId"), "val")) if num_pr is not None else None
        level = parse_int(attr(child(num_pr, "ilvl"), "val"), None) if num_pr is not None else None
        if num_id is None and style is not None:
            num_id = parse_int(style.raw.get("num_id"))
            level = parse_int(style.raw.get("num_level"), 0) if level is None else level
        if num_id is None:
            return None
        level = level or 0
        if num_id is None or num_id == 0:
            return None
        instance = self.numbering_instances.get(num_id)
        numbering_level = None
        if instance:
            numbering_level = instance.overrides.get(level)
            if numbering_level is None:
                numbering_level = self.numbering_levels.get(instance.abstract_id, {}).get(level)
        num_format = numbering_level.num_format if numbering_level else "decimal"
        pattern = numbering_level.text if numbering_level else f"%{level + 1}."
        start = instance.start_overrides.get(level, numbering_level.start if numbering_level else 1) if instance else 1
        ordered = num_format not in {"bullet", "none"}
        marker = None
        if not ordered:
            marker = re.sub(r"%\d+", "", pattern).strip() or "•"
        return ListProperties(
            ordered=ordered,
            level=level,
            start=start,
            number_format=num_format,
            pattern=pattern,
            marker=marker,
            num_id=num_id,
        )

    def _parse_inline_children(self, parent: ET.Element, part_name: str,
                               inherited_style: TextStyle | None = None) -> list[Inline]:
        result: list[Inline] = []
        fields: list[_FieldState] = []

        def append(inline: Inline) -> None:
            if fields:
                if fields[-1].separated:
                    fields[-1].result.append(inline)
                elif isinstance(inline, Text):
                    fields[-1].code.append(inline.text)
            else:
                result.append(inline)

        for element in parent:
            tag = local_name(element.tag)
            if tag == "pPr" or tag in {"proofErr", "permStart", "permEnd"}:
                continue
            if tag == "r":
                events = self._parse_run_events(element, part_name, inherited_style)
                for event, payload in events:
                    if event == "field_begin":
                        fields.append(_FieldState(locked=payload.get("locked", False), dirty=payload.get("dirty", False)))
                    elif event == "field_separate":
                        if fields:
                            fields[-1].separated = True
                    elif event == "field_end":
                        if fields:
                            state = fields.pop()
                            field_inline = Field("".join(state.code).strip(), state.result, state.locked, state.dirty)
                            append(field_inline)
                    elif event == "instruction":
                        if fields:
                            fields[-1].code.append(str(payload))
                        else:
                            append(Text(str(payload), inherited_style))
                    elif event == "inline":
                        append(payload)
            elif tag == "hyperlink":
                target = attr(element, "anchor")
                anchor = bool(target)
                rel_id = attr(element, "id", None, "r")
                tooltip = attr(element, "tooltip")
                if rel_id and rel_id in self.package.relationships(part_name):
                    rel = self.package.relationships(part_name)[rel_id]
                    target = rel.target if rel.external else rel.resolved_target
                link_children = self._parse_inline_children(element, part_name, inherited_style)
                append(Link(target or "", link_children, tooltip, anchor=anchor))
            elif tag == "fldSimple":
                code = attr(element, "instr", "")
                children_inline = self._parse_inline_children(element, part_name, inherited_style)
                append(Field(code, children_inline, bool_attr(element, "fldLock", False) or False,
                             bool_attr(element, "dirty", False) or False))
            elif tag == "bookmarkStart":
                name = attr(element, "name", "")
                bookmark_id = attr(element, "id")
                if name and not name.startswith("_"):
                    self._bookmark_names[bookmark_id or name] = name
                    append(Bookmark(name, bookmark_id, False))
            elif tag == "bookmarkEnd":
                bookmark_id = attr(element, "id")
                name = self._bookmark_names.get(bookmark_id or "", bookmark_id or "")
                if name:
                    append(Bookmark(name, bookmark_id, True))
            elif tag == "commentRangeStart" and self.options.comments != "drop":
                append(CommentAnchor(attr(element, "id", ""), "start"))
            elif tag == "commentRangeEnd" and self.options.comments != "drop":
                append(CommentAnchor(attr(element, "id", ""), "end"))
            elif tag in {"ins", "del", "moveFrom", "moveTo"}:
                change_type = {"ins": "insert", "del": "delete", "moveFrom": "move_from", "moveTo": "move_to"}[tag]
                children_inline = self._parse_inline_children(element, part_name, inherited_style)
                action = self.options.revisions
                include = (change_type in {"insert", "move_to"} and action in {"accept", "annotate", "preserve"}) or \
                          (change_type in {"delete", "move_from"} and action in {"reject", "annotate", "preserve"})
                if include:
                    if action in {"annotate", "preserve"}:
                        append(Change(change_type, children_inline, attr(element, "author"),
                                      attr(element, "date"), attr(element, "id")))
                    else:
                        for inline in children_inline:
                            append(inline)
            elif tag in {"smartTag", "customXml", "sdt"}:
                for inline in self._parse_inline_children(element, part_name, inherited_style):
                    append(inline)
            elif element.tag in {qn("m", "oMath"), qn("m", "oMathPara")}:
                append(MathInline(omml_to_typst(element), display=tag == "oMathPara",
                                       omml=encode_raw_fragment(xml_bytes(element))))
            elif tag == "subDoc" and self.options.unknown == "preserve":
                append(self._raw_inline(element, description="Embedded subdocument"))
            elif self.options.unknown == "preserve":
                append(self._raw_inline(element, description=f"Unsupported DOCX inline {tag}"))
        # Recover malformed/unclosed fields without discarding visible result.
        while fields:
            state = fields.pop()
            field = Field("".join(state.code).strip(), state.result, state.locked, state.dirty)
            if fields:
                fields[-1].result.append(field)
            else:
                result.append(field)
        return result

    def _parse_run_events(self, run: ET.Element, part_name: str,
                          inherited_style: TextStyle | None) -> list[tuple[str, Any]]:
        rpr = child(run, "rPr")
        direct_style = self._parse_rpr(rpr)
        style = (inherited_style or TextStyle()).merged(direct_style)
        events: list[tuple[str, Any]] = []
        for item in run:
            tag = local_name(item.tag)
            if tag == "rPr":
                continue
            if tag in {"t", "delText"}:
                events.append(("inline", Text(item.text or "", style.copy())))
            elif tag == "tab":
                events.append(("inline", Break("tab")))
            elif tag == "br":
                break_type = attr(item, "type", "line")
                if break_type not in {"page", "column", "line"}:
                    break_type = "line"
                events.append(("inline", Break(break_type)))
            elif tag == "cr":
                events.append(("inline", Break("line")))
            elif tag == "noBreakHyphen":
                events.append(("inline", Text("‑", style.copy())))
            elif tag == "softHyphen":
                events.append(("inline", Text("\u00ad", style.copy())))
            elif tag == "sym":
                char_hex = attr(item, "char", "")
                try:
                    character = chr(int(char_hex, 16))
                except (ValueError, TypeError):
                    character = "□"
                events.append(("inline", Text(character, style.copy())))
            elif tag in {"drawing", "pict", "object"}:
                events.extend(("inline", inline) for inline in self._parse_drawing(item, part_name))
            elif tag == "footnoteReference":
                note_id = attr(item, "id", "")
                events.append(("inline", NoteRef("footnote", note_id, self.notes["footnote"].get(note_id, []))))
            elif tag == "endnoteReference":
                note_id = attr(item, "id", "")
                events.append(("inline", NoteRef("endnote", note_id, self.notes["endnote"].get(note_id, []))))
            elif tag == "commentReference" and self.options.comments != "drop":
                events.append(("inline", CommentAnchor(attr(item, "id", ""), "reference")))
            elif tag == "fldChar":
                fld_type = attr(item, "fldCharType", "")
                if fld_type == "begin":
                    events.append(("field_begin", {
                        "locked": bool_attr(item, "fldLock", False) or False,
                        "dirty": bool_attr(item, "dirty", False) or False,
                    }))
                elif fld_type == "separate":
                    events.append(("field_separate", None))
                elif fld_type == "end":
                    events.append(("field_end", None))
            elif tag in {"instrText", "delInstrText"}:
                events.append(("instruction", item.text or ""))
            elif item.tag in {qn("m", "oMath"), qn("m", "oMathPara")}:
                events.append(("inline", MathInline(omml_to_typst(item), tag == "oMathPara",
                                                     encode_raw_fragment(xml_bytes(item)))))
            elif tag in {"lastRenderedPageBreak", "separator", "continuationSeparator",
                         "footnoteRef", "endnoteRef", "annotationRef"}:
                continue
            elif self.options.unknown == "preserve":
                events.append(("inline", self._raw_inline(item, description=f"Unsupported run child {tag}")))
        return events

    def _parse_drawing(self, drawing: ET.Element, part_name: str) -> list[Inline]:
        results: list[Inline] = []
        rels = self.package.relationships(part_name)
        # Pictures in DrawingML.
        for blip in drawing.iter(qn("a", "blip")):
            rel_id = attr(blip, "embed", None, "r") or attr(blip, "link", None, "r")
            if not rel_id or rel_id not in rels:
                continue
            rel = rels[rel_id]
            if rel.external:
                results.append(Link(rel.target, [Text("[linked image]")]))
                continue
            part = rel.resolved_target
            data = self.package.get(part)
            if data is None:
                continue
            extent = next(iter(drawing.iter(qn("wp", "extent"))), None)
            width_pt = emu_to_points(extent.get("cx")) if extent is not None else None
            height_pt = emu_to_points(extent.get("cy")) if extent is not None else None
            doc_pr = next(iter(drawing.iter(qn("wp", "docPr"))), None)
            alt_text = doc_pr.get("descr") if doc_pr is not None else None
            title = doc_pr.get("title") if doc_pr is not None else None
            floating = any(item.tag == qn("wp", "anchor") for item in drawing.iter())
            wrap = None
            for item in drawing.iter():
                local = local_name(item.tag)
                if local in {"wrapNone", "wrapSquare", "wrapTight", "wrapThrough", "wrapTopAndBottom"}:
                    wrap = local
                    break
            crop: dict[str, float] = {}
            src_rect = next(iter(drawing.iter(qn("a", "srcRect"))), None)
            if src_rect is not None:
                for side in ("l", "t", "r", "b"):
                    value = parse_int(src_rect.get(side))
                    if value is not None:
                        crop[side] = value / 100000.0
            resource_id = self._resource_from_part(part, data, width_pt, height_pt, alt_text, title)
            results.append(ImageInline(resource_id, width_pt, height_pt, alt_text, title,
                                       floating=floating, wrap=wrap, crop=crop))
        # VML images.
        for image_data in drawing.iter(qn("v", "imagedata")):
            rel_id = attr(image_data, "id", None, "r")
            if not rel_id or rel_id not in rels:
                continue
            rel = rels[rel_id]
            if rel.external:
                continue
            part = rel.resolved_target
            data = self.package.get(part)
            if data is None:
                continue
            resource_id = self._resource_from_part(part, data, None, None,
                                                   image_data.get(qn("o", "title")), None)
            results.append(ImageInline(resource_id, alt_text=image_data.get(qn("o", "title"))))
        # Charts, diagrams, OLE, canvases, and shapes are preserved as raw if no picture fallback existed.
        if not results and self.options.unknown == "preserve":
            fallback = [Text("[Unsupported Word drawing/object]")]
            results.append(self._raw_inline(drawing, fallback, "DrawingML/VML object"))
        return results

    def _resource_from_part(self, part: str, data: bytes,
                            width_pt: float | None, height_pt: float | None,
                            alt_text: str | None, title: str | None) -> str:
        if part in self._resource_by_part:
            resource_id = self._resource_by_part[part]
            resource = self.doc.resources[resource_id]
            resource.width_pt = resource.width_pt or width_pt
            resource.height_pt = resource.height_pt or height_pt
            resource.alt_text = resource.alt_text or alt_text
            resource.title = resource.title or title
            return resource_id
        checksum = hashlib.sha256(data).hexdigest()
        media_type = self.package.content_types.for_part(part) or guess_media_type(part, data)
        filename = sanitize_filename(posixpath.basename(part), "image" + extension_for_media_type(media_type))
        if width_pt is None or height_pt is None:
            pixels_w, pixels_h, dpi_x, dpi_y = image_dimensions(data, media_type)
            if pixels_w and width_pt is None:
                width_pt = pixels_w * 72.0 / (dpi_x or 96.0)
            if pixels_h and height_pt is None:
                height_pt = pixels_h * 72.0 / (dpi_y or 96.0)
        resource_id = "img-" + checksum[:16]
        source_path = None
        if self.options.extract_assets and self.options.assets_dir:
            assets_dir = Path(self.options.assets_dir)
            assets_dir.mkdir(parents=True, exist_ok=True)
            candidate = assets_dir / filename
            if candidate.exists() and candidate.read_bytes() != data:
                candidate = assets_dir / f"{candidate.stem}-{checksum[:8]}{candidate.suffix}"
            candidate.write_bytes(data)
            source_path = str(candidate)
        self.doc.add_resource(Resource(
            id=resource_id,
            filename=filename,
            media_type=media_type,
            data=data,
            source_path=source_path,
            width_pt=width_pt,
            height_pt=height_pt,
            alt_text=alt_text,
            title=title,
            checksum=checksum,
            raw={"part": part},
        ))
        self._resource_by_part[part] = resource_id
        return resource_id

    def _parse_table(self, table: ET.Element, part_name: str) -> Table:
        tbl_pr = child(table, "tblPr")
        grid = child(table, "tblGrid")
        widths = [twips_to_points(attr(col, "w")) for col in children(grid, "gridCol")]
        borders: dict[str, Border] = {}
        tbl_borders = child(tbl_pr, "tblBorders")
        if tbl_borders is not None:
            for side in tbl_borders:
                borders[local_name(side.tag)] = self._parse_border(side)
        rows: list[TableRow] = []
        # Tracks active vertical merges by logical column.
        active_merges: dict[int, TableCell] = {}
        for tr in table.findall(qn("w", "tr")):
            tr_pr = child(tr, "trPr")
            row = TableRow(
                header=bool_attr(child(tr_pr, "tblHeader"), default=False) or False,
                cant_split=bool_attr(child(tr_pr, "cantSplit"), default=False) or False,
            )
            height = child(tr_pr, "trHeight")
            if height is not None:
                row.height_pt = twips_to_points(attr(height, "val"))
                row.height_rule = attr(height, "hRule")
            logical_col = 0
            for tc in tr.findall(qn("w", "tc")):
                tc_pr = child(tc, "tcPr")
                colspan = parse_int(attr(child(tc_pr, "gridSpan"), "val"), 1) or 1
                vmerge = child(tc_pr, "vMerge")
                vmerge_val = attr(vmerge, "val", "continue") if vmerge is not None else None
                if vmerge is not None and vmerge_val != "restart" and logical_col in active_merges:
                    active_merges[logical_col].rowspan += 1
                    logical_col += colspan
                    continue
                cell_borders: dict[str, Border] = {}
                tc_borders = child(tc_pr, "tcBorders")
                if tc_borders is not None:
                    for side in tc_borders:
                        cell_borders[local_name(side.tag)] = self._parse_border(side)
                margins: dict[str, float] = {}
                tc_mar = child(tc_pr, "tcMar")
                if tc_mar is not None:
                    for side in tc_mar:
                        value = twips_to_points(attr(side, "w"))
                        if value is not None:
                            margins[local_name(side.tag)] = value
                shading = child(tc_pr, "shd")
                cell = TableCell(
                    blocks=self._group_lists(self._parse_block_children(tc, part_name)),
                    colspan=colspan,
                    rowspan=1,
                    width_pt=twips_to_points(attr(child(tc_pr, "tcW"), "w")),
                    vertical_align=attr(child(tc_pr, "vAlign"), "val"),
                    shading=normalize_hex_color(attr(shading, "fill")) if shading is not None else None,
                    borders=cell_borders,
                    margins_pt=margins,
                    header=row.header,
                    text_direction=attr(child(tc_pr, "textDirection"), "val"),
                )
                row.cells.append(cell)
                if vmerge is not None and vmerge_val == "restart":
                    for col in range(logical_col, logical_col + colspan):
                        active_merges[col] = cell
                else:
                    for col in range(logical_col, logical_col + colspan):
                        active_merges.pop(col, None)
                logical_col += colspan
            rows.append(row)
        width_element = child(tbl_pr, "tblW")
        width = twips_to_points(attr(width_element, "w")) if attr(width_element, "type") in {None, "dxa"} else None
        shading = child(tbl_pr, "shd")
        table_obj = Table(
            rows=rows,
            column_widths_pt=widths,
            align=attr(child(tbl_pr, "jc"), "val"),
            width_pt=width,
            layout=attr(child(tbl_pr, "tblLayout"), "type", "autofit"),
            style_id=attr(child(tbl_pr, "tblStyle"), "val"),
            caption=attr(child(tbl_pr, "tblCaption"), "val"),
            description=attr(child(tbl_pr, "tblDescription"), "val"),
            borders=borders,
            shading=normalize_hex_color(attr(shading, "fill")) if shading is not None else None,
            cell_spacing_pt=twips_to_points(attr(child(tbl_pr, "tblCellSpacing"), "w")),
            bidi=child(tbl_pr, "bidiVisual") is not None,
        )
        return table_obj

    def _parse_content_control(self, sdt: ET.Element, part_name: str) -> ContentControl:
        sdt_pr = child(sdt, "sdtPr")
        content = child(sdt, "sdtContent")
        control_type = None
        if sdt_pr is not None:
            for item in sdt_pr:
                local = local_name(item.tag)
                if local in {"richText", "text", "picture", "comboBox", "dropDownList", "date",
                             "checkbox", "repeatingSection", "repeatingSectionItem", "citation",
                             "bibliography", "equation", "group", "docPartObj", "docPartList"}:
                    control_type = local
                    break
        binding = child(sdt_pr, "dataBinding")
        data_binding = {}
        if binding is not None:
            for key in ("xpath", "storeItemID", "prefixMappings"):
                value = attr(binding, key)
                if value:
                    data_binding[key] = value
        return ContentControl(
            blocks=self._group_lists(self._parse_block_children(content, part_name)) if content is not None else [],
            tag=attr(child(sdt_pr, "tag"), "val"),
            alias=attr(child(sdt_pr, "alias"), "val"),
            control_id=attr(child(sdt_pr, "id"), "val"),
            control_type=control_type,
            lock=attr(child(sdt_pr, "lock"), "val"),
            data_binding=data_binding,
            raw={"xml": encode_raw_fragment(xml_bytes(sdt_pr))} if sdt_pr is not None and self.options.unknown == "preserve" else {},
        )

    def _parse_alt_chunk(self, element: ET.Element, part_name: str) -> RawBlock:
        rel_id = attr(element, "id", None, "r")
        data = b""
        description = "altChunk"
        if rel_id:
            rel = self.package.relationships(part_name).get(rel_id)
            if rel and not rel.external:
                data = self.package.get(rel.resolved_target, b"") or b""
                content_type = self.package.content_types.for_part(rel.resolved_target)
                description = f"altChunk ({content_type or 'unknown content type'})"
        return RawBlock("docx-altChunk", encode_raw_fragment(data or xml_bytes(element)),
                        [Paragraph([Text(f"[{description}]")])], description)

    def _parse_section(self, sect_pr: ET.Element, part_name: str) -> SectionProperties:
        pg_sz = child(sect_pr, "pgSz")
        pg_mar = child(sect_pr, "pgMar")
        cols = child(sect_pr, "cols")
        section = SectionProperties(
            page_width_pt=twips_to_points(attr(pg_sz, "w")) or 595.276,
            page_height_pt=twips_to_points(attr(pg_sz, "h")) or 841.89,
            margin_top_pt=twips_to_points(attr(pg_mar, "top")) or 72.0,
            margin_bottom_pt=twips_to_points(attr(pg_mar, "bottom")) or 72.0,
            margin_left_pt=twips_to_points(attr(pg_mar, "left")) or 72.0,
            margin_right_pt=twips_to_points(attr(pg_mar, "right")) or 72.0,
            gutter_pt=twips_to_points(attr(pg_mar, "gutter")) or 0.0,
            header_distance_pt=twips_to_points(attr(pg_mar, "header")) or 36.0,
            footer_distance_pt=twips_to_points(attr(pg_mar, "footer")) or 36.0,
            orientation=attr(pg_sz, "orient", "portrait"),
            columns=parse_int(attr(cols, "num"), 1) or 1,
            column_spacing_pt=twips_to_points(attr(cols, "space")) or 36.0,
            equal_column_width=bool_attr(cols, "equalWidth", True) is not False,
            title_page=child(sect_pr, "titlePg") is not None,
            vertical_align=attr(child(sect_pr, "vAlign"), "val"),
        )
        if cols is not None:
            for col in cols.findall(qn("w", "col")):
                width = twips_to_points(attr(col, "w"))
                if width is not None:
                    section.column_widths_pt.append(width)
        pg_num = child(sect_pr, "pgNumType")
        if pg_num is not None:
            section.page_number_start = parse_int(attr(pg_num, "start"))
            section.page_number_format = attr(pg_num, "fmt")
        line_number = child(sect_pr, "lnNumType")
        if line_number is not None:
            section.line_numbering = {
                "count_by": parse_int(attr(line_number, "countBy")),
                "distance_pt": twips_to_points(attr(line_number, "distance")),
                "restart": attr(line_number, "restart"),
                "start": parse_int(attr(line_number, "start")),
            }
        # Header/footer references are relationships from the main document part.
        rels = self.package.relationships(part_name)
        for ref in sect_pr:
            tag = local_name(ref.tag)
            if tag not in {"headerReference", "footerReference"}:
                continue
            rel_id = attr(ref, "id", None, "r")
            rel = rels.get(rel_id or "")
            if not rel or rel.external or not self.package.get(rel.resolved_target):
                continue
            root = self.package.xml(rel.resolved_target)
            parsed = self._group_lists(self._parse_block_children(root, rel.resolved_target))
            kind = attr(ref, "type", "default")
            setattr(section, f"{'header' if tag == 'headerReference' else 'footer'}_{kind}", parsed)
        self.doc.sections.append(section)
        return section

    def _revision_block_content(self, element: ET.Element, part_name: str, tag: str) -> list[Block]:
        change_type = {"ins": "insert", "del": "delete", "moveFrom": "move_from", "moveTo": "move_to"}[tag]
        action = self.options.revisions
        include = (change_type in {"insert", "move_to"} and action in {"accept", "annotate", "preserve"}) or \
                  (change_type in {"delete", "move_from"} and action in {"reject", "annotate", "preserve"})
        if not include:
            return []
        blocks = self._parse_block_children(element, part_name)
        if action not in {"annotate", "preserve"}:
            return blocks
        # Block-level changes are represented by a raw wrapper with visible fallback.
        raw = RawBlock(
            "docx-revision",
            encode_raw_fragment(xml_bytes(element)),
            blocks,
            f"{change_type} by {attr(element, 'author', 'unknown')}",
        )
        return [raw]

    # ---------- post-processing ----------

    def _group_lists(self, blocks: list[Block]) -> list[Block]:
        output: list[Block] = []
        stack: list[tuple[int, int | None, ListBlock]] = []

        def close_to(level: int) -> None:
            while stack and stack[-1][0] >= level:
                stack.pop()

        for block in blocks:
            if not isinstance(block, Paragraph) or block.list_props is None:
                stack.clear()
                output.append(block)
                continue
            props = block.list_props
            level = max(0, props.level)
            num_id = props.num_id
            while stack and (stack[-1][0] > level or (stack[-1][0] == level and stack[-1][1] != num_id)):
                stack.pop()
            if stack and stack[-1][0] == level and stack[-1][1] == num_id:
                target = stack[-1][2]
            else:
                target = ListBlock(
                    ordered=props.ordered,
                    start=props.start,
                    level=level,
                    number_format=props.number_format,
                    marker=props.marker,
                )
                if stack and stack[-1][0] < level and stack[-1][2].items:
                    stack[-1][2].items[-1].blocks.append(target)
                else:
                    output.append(target)
                stack.append((level, num_id, target))
            block.list_props = None
            target.items.append(ListItem([block], checked=props.checked))
        return output

    def _raw_inline(self, element: ET.Element, fallback: list[Inline] | None = None,
                    description: str | None = None) -> RawInline:
        data = xml_bytes(element)
        if len(data) > self.options.max_unknown_fragment_bytes:
            self.doc.warnings.append(f"raw inline fragment dropped because it is {len(data)} bytes")
            data = b""
        return RawInline("ooxml", encode_raw_fragment(data), fallback or [], description)

    def _raw_block(self, element: ET.Element, fallback: list[Block] | None = None,
                   description: str | None = None) -> RawBlock:
        data = xml_bytes(element)
        if len(data) > self.options.max_unknown_fragment_bytes:
            self.doc.warnings.append(f"raw block fragment dropped because it is {len(data)} bytes")
            data = b""
        if fallback is None:
            text = "".join(element.itertext()).strip()
            fallback = [Paragraph([Text(text)])] if text else []
        return RawBlock("ooxml", encode_raw_fragment(data), fallback, description)
