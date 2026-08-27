from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from pathlib import Path
from typing import Any, Iterable, Literal


@dataclass(slots=True)
class TextStyle:
    bold: bool | None = None
    italic: bool | None = None
    underline: str | None = None
    strike: bool | None = None
    double_strike: bool | None = None
    small_caps: bool | None = None
    all_caps: bool | None = None
    hidden: bool | None = None
    superscript: bool | None = None
    subscript: bool | None = None
    font: str | None = None
    font_east_asia: str | None = None
    font_complex: str | None = None
    size_pt: float | None = None
    color: str | None = None
    highlight: str | None = None
    language: str | None = None
    language_east_asia: str | None = None
    language_complex: str | None = None
    letter_spacing_pt: float | None = None
    scale_percent: int | None = None
    baseline_pt: float | None = None
    rtl: bool | None = None
    no_proof: bool | None = None
    emboss: bool | None = None
    imprint: bool | None = None
    outline: bool | None = None
    shadow: bool | None = None
    text_effects: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)

    def merged(self, other: "TextStyle | None") -> "TextStyle":
        if other is None:
            return self.copy()
        values: dict[str, Any] = {}
        for name in self.__dataclass_fields__:
            left = getattr(self, name)
            right = getattr(other, name)
            if isinstance(left, dict):
                values[name] = {**left, **(right or {})}
            else:
                values[name] = right if right is not None else left
        return TextStyle(**values)

    def copy(self) -> "TextStyle":
        return TextStyle(**{name: (dict(value) if isinstance(value, dict) else value)
                            for name, value in ((n, getattr(self, n)) for n in self.__dataclass_fields__)})

    def is_empty(self) -> bool:
        return all((not value if isinstance(value, dict) else value is None)
                   for value in (getattr(self, n) for n in self.__dataclass_fields__))


@dataclass(slots=True)
class Border:
    style: str = "single"
    width_pt: float = 0.5
    color: str = "000000"
    space_pt: float = 0.0
    shadow: bool = False


@dataclass(slots=True)
class TabStop:
    position_pt: float
    alignment: str = "left"
    leader: str = "none"


@dataclass(slots=True)
class ParagraphStyle:
    style_id: str | None = None
    align: str | None = None
    left_indent_pt: float | None = None
    right_indent_pt: float | None = None
    first_line_indent_pt: float | None = None
    hanging_indent_pt: float | None = None
    space_before_pt: float | None = None
    space_after_pt: float | None = None
    line_spacing: float | None = None
    line_spacing_rule: str | None = None
    keep_next: bool | None = None
    keep_lines: bool | None = None
    page_break_before: bool | None = None
    widow_control: bool | None = None
    contextual_spacing: bool | None = None
    mirror_indents: bool | None = None
    suppress_line_numbers: bool | None = None
    bidi: bool | None = None
    text_direction: str | None = None
    shading: str | None = None
    borders: dict[str, Border] = field(default_factory=dict)
    tabs: list[TabStop] = field(default_factory=list)
    default_text_style: TextStyle = field(default_factory=TextStyle)
    outline_level: int | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    def merged(self, other: "ParagraphStyle | None") -> "ParagraphStyle":
        if other is None:
            return self.copy()
        values: dict[str, Any] = {}
        for name in self.__dataclass_fields__:
            left = getattr(self, name)
            right = getattr(other, name)
            if name == "default_text_style":
                values[name] = left.merged(right)
            elif isinstance(left, dict):
                values[name] = {**left, **(right or {})}
            elif isinstance(left, list):
                values[name] = list(right) if right else list(left)
            else:
                values[name] = right if right is not None else left
        return ParagraphStyle(**values)

    def copy(self) -> "ParagraphStyle":
        return ParagraphStyle(
            **{
                name: (
                    value.copy() if isinstance(value, TextStyle)
                    else dict(value) if isinstance(value, dict)
                    else list(value) if isinstance(value, list)
                    else value
                )
                for name, value in ((n, getattr(self, n)) for n in self.__dataclass_fields__)
            }
        )


@dataclass(slots=True)
class ListProperties:
    ordered: bool = False
    level: int = 0
    start: int = 1
    number_format: str = "decimal"
    pattern: str | None = None
    marker: str | None = None
    num_id: int | None = None
    restart: bool = False
    checked: bool | None = None


@dataclass(slots=True)
class SectionProperties:
    page_width_pt: float = 595.276
    page_height_pt: float = 841.89
    margin_top_pt: float = 72.0
    margin_bottom_pt: float = 72.0
    margin_left_pt: float = 72.0
    margin_right_pt: float = 72.0
    gutter_pt: float = 0.0
    header_distance_pt: float = 36.0
    footer_distance_pt: float = 36.0
    orientation: str = "portrait"
    columns: int = 1
    column_spacing_pt: float = 36.0
    equal_column_width: bool = True
    column_widths_pt: list[float] = field(default_factory=list)
    page_number_start: int | None = None
    page_number_format: str | None = None
    title_page: bool = False
    different_odd_even: bool = False
    vertical_align: str | None = None
    line_numbering: dict[str, Any] = field(default_factory=dict)
    header_default: list["Block"] = field(default_factory=list)
    header_first: list["Block"] = field(default_factory=list)
    header_even: list["Block"] = field(default_factory=list)
    footer_default: list["Block"] = field(default_factory=list)
    footer_first: list["Block"] = field(default_factory=list)
    footer_even: list["Block"] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Resource:
    id: str
    filename: str
    media_type: str
    data: bytes | None = None
    source_path: str | None = None
    width_pt: float | None = None
    height_pt: float | None = None
    alt_text: str | None = None
    title: str | None = None
    checksum: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Inline:
    kind: str


@dataclass(slots=True)
class Text(Inline):
    text: str
    style: TextStyle = field(default_factory=TextStyle)

    def __init__(self, text: str, style: TextStyle | None = None):
        self.kind = "text"
        self.text = text
        self.style = style or TextStyle()


@dataclass(slots=True)
class Break(Inline):
    break_type: Literal["line", "page", "column", "soft", "tab"] = "line"

    def __init__(self, break_type: Literal["line", "page", "column", "soft", "tab"] = "line"):
        self.kind = "break"
        self.break_type = break_type


@dataclass(slots=True)
class Link(Inline):
    target: str
    children: list[Inline] = field(default_factory=list)
    tooltip: str | None = None
    anchor: bool = False

    def __init__(self, target: str, children: list[Inline] | None = None,
                 tooltip: str | None = None, anchor: bool = False):
        self.kind = "link"
        self.target = target
        self.children = children or []
        self.tooltip = tooltip
        self.anchor = anchor


@dataclass(slots=True)
class Bookmark(Inline):
    name: str
    bookmark_id: str | None = None
    end: bool = False

    def __init__(self, name: str, bookmark_id: str | None = None, end: bool = False):
        self.kind = "bookmark"
        self.name = name
        self.bookmark_id = bookmark_id
        self.end = end


@dataclass(slots=True)
class ImageInline(Inline):
    resource_id: str
    width_pt: float | None = None
    height_pt: float | None = None
    alt_text: str | None = None
    title: str | None = None
    floating: bool = False
    wrap: str | None = None
    crop: dict[str, float] = field(default_factory=dict)

    def __init__(self, resource_id: str, width_pt: float | None = None,
                 height_pt: float | None = None, alt_text: str | None = None,
                 title: str | None = None, floating: bool = False,
                 wrap: str | None = None, crop: dict[str, float] | None = None):
        self.kind = "image"
        self.resource_id = resource_id
        self.width_pt = width_pt
        self.height_pt = height_pt
        self.alt_text = alt_text
        self.title = title
        self.floating = floating
        self.wrap = wrap
        self.crop = crop or {}


@dataclass(slots=True)
class MathInline(Inline):
    typst: str
    display: bool = False
    omml: str | None = None
    fallback_text: str | None = None

    def __init__(self, typst: str, display: bool = False,
                 omml: str | None = None, fallback_text: str | None = None):
        self.kind = "math"
        self.typst = typst
        self.display = display
        self.omml = omml
        self.fallback_text = fallback_text


@dataclass(slots=True)
class NoteRef(Inline):
    note_type: Literal["footnote", "endnote"]
    note_id: str
    body: list["Block"] = field(default_factory=list)

    def __init__(self, note_type: Literal["footnote", "endnote"], note_id: str,
                 body: list["Block"] | None = None):
        self.kind = "note"
        self.note_type = note_type
        self.note_id = note_id
        self.body = body or []


@dataclass(slots=True)
class Field(Inline):
    code: str
    children: list[Inline] = field(default_factory=list)
    locked: bool = False
    dirty: bool = False

    def __init__(self, code: str, children: list[Inline] | None = None,
                 locked: bool = False, dirty: bool = False):
        self.kind = "field"
        self.code = code
        self.children = children or []
        self.locked = locked
        self.dirty = dirty


@dataclass(slots=True)
class Citation(Inline):
    keys: list[str]
    supplement: str | None = None
    style: str | None = None
    fallback: list[Inline] = field(default_factory=list)

    def __init__(self, keys: list[str], supplement: str | None = None,
                 style: str | None = None, fallback: list[Inline] | None = None):
        self.kind = "citation"
        self.keys = keys
        self.supplement = supplement
        self.style = style
        self.fallback = fallback or []


@dataclass(slots=True)
class CommentAnchor(Inline):
    comment_id: str
    event: Literal["start", "end", "reference"]

    def __init__(self, comment_id: str, event: Literal["start", "end", "reference"]):
        self.kind = "comment_anchor"
        self.comment_id = comment_id
        self.event = event


@dataclass(slots=True)
class Change(Inline):
    change_type: Literal["insert", "delete", "move_from", "move_to"]
    children: list[Inline]
    author: str | None = None
    date: str | None = None
    change_id: str | None = None

    def __init__(self, change_type: Literal["insert", "delete", "move_from", "move_to"],
                 children: list[Inline], author: str | None = None,
                 date: str | None = None, change_id: str | None = None):
        self.kind = "change"
        self.change_type = change_type
        self.children = children
        self.author = author
        self.date = date
        self.change_id = change_id


@dataclass(slots=True)
class RawInline(Inline):
    format: str
    data: str
    fallback: list[Inline] = field(default_factory=list)
    description: str | None = None

    def __init__(self, format: str, data: str, fallback: list[Inline] | None = None,
                 description: str | None = None):
        self.kind = "raw"
        self.format = format
        self.data = data
        self.fallback = fallback or []
        self.description = description


@dataclass(slots=True)
class Block:
    kind: str


@dataclass(slots=True)
class Paragraph(Block):
    inlines: list[Inline] = field(default_factory=list)
    style: ParagraphStyle = field(default_factory=ParagraphStyle)
    list_props: ListProperties | None = None
    source_span: tuple[int, int] | None = None

    def __init__(self, inlines: list[Inline] | None = None,
                 style: ParagraphStyle | None = None,
                 list_props: ListProperties | None = None,
                 source_span: tuple[int, int] | None = None):
        self.kind = "paragraph"
        self.inlines = inlines or []
        self.style = style or ParagraphStyle()
        self.list_props = list_props
        self.source_span = source_span


@dataclass(slots=True)
class Heading(Block):
    level: int
    inlines: list[Inline] = field(default_factory=list)
    numbering: str | None = None
    label: str | None = None
    outlined: bool = True
    bookmarked: bool = True
    style: ParagraphStyle = field(default_factory=ParagraphStyle)

    def __init__(self, level: int, inlines: list[Inline] | None = None,
                 numbering: str | None = None, label: str | None = None,
                 outlined: bool = True, bookmarked: bool = True,
                 style: ParagraphStyle | None = None):
        self.kind = "heading"
        self.level = level
        self.inlines = inlines or []
        self.numbering = numbering
        self.label = label
        self.outlined = outlined
        self.bookmarked = bookmarked
        self.style = style or ParagraphStyle()


@dataclass(slots=True)
class ListItem:
    blocks: list[Block] = field(default_factory=list)
    checked: bool | None = None
    term: list[Inline] | None = None


@dataclass(slots=True)
class ListBlock(Block):
    ordered: bool
    items: list[ListItem] = field(default_factory=list)
    start: int = 1
    level: int = 0
    number_format: str = "decimal"
    marker: str | None = None
    tight: bool = False

    def __init__(self, ordered: bool, items: list[ListItem] | None = None,
                 start: int = 1, level: int = 0, number_format: str = "decimal",
                 marker: str | None = None, tight: bool = False):
        self.kind = "list"
        self.ordered = ordered
        self.items = items or []
        self.start = start
        self.level = level
        self.number_format = number_format
        self.marker = marker
        self.tight = tight


@dataclass(slots=True)
class TableCell:
    blocks: list[Block] = field(default_factory=list)
    colspan: int = 1
    rowspan: int = 1
    width_pt: float | None = None
    vertical_align: str | None = None
    align: str | None = None
    shading: str | None = None
    borders: dict[str, Border] = field(default_factory=dict)
    margins_pt: dict[str, float] = field(default_factory=dict)
    header: bool = False
    text_direction: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class TableRow:
    cells: list[TableCell] = field(default_factory=list)
    header: bool = False
    cant_split: bool = False
    height_pt: float | None = None
    height_rule: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Table(Block):
    rows: list[TableRow] = field(default_factory=list)
    column_widths_pt: list[float | None] = field(default_factory=list)
    align: str | None = None
    width_pt: float | None = None
    layout: str = "autofit"
    style_id: str | None = None
    caption: str | None = None
    description: str | None = None
    borders: dict[str, Border] = field(default_factory=dict)
    shading: str | None = None
    cell_spacing_pt: float | None = None
    bidi: bool = False
    raw: dict[str, Any] = field(default_factory=dict)

    def __init__(self, rows: list[TableRow] | None = None,
                 column_widths_pt: list[float | None] | None = None,
                 align: str | None = None, width_pt: float | None = None,
                 layout: str = "autofit", style_id: str | None = None,
                 caption: str | None = None, description: str | None = None,
                 borders: dict[str, Border] | None = None,
                 shading: str | None = None, cell_spacing_pt: float | None = None,
                 bidi: bool = False, raw: dict[str, Any] | None = None):
        self.kind = "table"
        self.rows = rows or []
        self.column_widths_pt = column_widths_pt or []
        self.align = align
        self.width_pt = width_pt
        self.layout = layout
        self.style_id = style_id
        self.caption = caption
        self.description = description
        self.borders = borders or {}
        self.shading = shading
        self.cell_spacing_pt = cell_spacing_pt
        self.bidi = bidi
        self.raw = raw or {}


@dataclass(slots=True)
class Figure(Block):
    body: list[Block] = field(default_factory=list)
    caption: list[Inline] = field(default_factory=list)
    kind_name: str = "figure"
    label: str | None = None
    numbering: str | None = None
    placement: str | None = None
    align: str | None = None
    supplement: str | None = None

    def __init__(self, body: list[Block] | None = None, caption: list[Inline] | None = None,
                 kind_name: str = "figure", label: str | None = None,
                 numbering: str | None = None, placement: str | None = None,
                 align: str | None = None, supplement: str | None = None):
        self.kind = "figure"
        self.body = body or []
        self.caption = caption or []
        self.kind_name = kind_name
        self.label = label
        self.numbering = numbering
        self.placement = placement
        self.align = align
        self.supplement = supplement


@dataclass(slots=True)
class Quote(Block):
    blocks: list[Block] = field(default_factory=list)
    attribution: list[Inline] = field(default_factory=list)
    block_quote: bool = True

    def __init__(self, blocks: list[Block] | None = None,
                 attribution: list[Inline] | None = None, block_quote: bool = True):
        self.kind = "quote"
        self.blocks = blocks or []
        self.attribution = attribution or []
        self.block_quote = block_quote


@dataclass(slots=True)
class CodeBlock(Block):
    text: str
    language: str | None = None
    block: bool = True
    syntaxes: list[str] = field(default_factory=list)

    def __init__(self, text: str, language: str | None = None, block: bool = True,
                 syntaxes: list[str] | None = None):
        self.kind = "code"
        self.text = text
        self.language = language
        self.block = block
        self.syntaxes = syntaxes or []


@dataclass(slots=True)
class MathBlock(Block):
    typst: str
    omml: str | None = None
    numbering: str | None = None
    label: str | None = None

    def __init__(self, typst: str, omml: str | None = None,
                 numbering: str | None = None, label: str | None = None):
        self.kind = "math"
        self.typst = typst
        self.omml = omml
        self.numbering = numbering
        self.label = label


@dataclass(slots=True)
class Divider(Block):
    thickness_pt: float = 0.75
    color: str = "808080"

    def __init__(self, thickness_pt: float = 0.75, color: str = "808080"):
        self.kind = "divider"
        self.thickness_pt = thickness_pt
        self.color = color


@dataclass(slots=True)
class BreakBlock(Block):
    break_type: Literal["page", "column", "section"] = "page"
    section: SectionProperties | None = None

    def __init__(self, break_type: Literal["page", "column", "section"] = "page",
                 section: SectionProperties | None = None):
        self.kind = "break"
        self.break_type = break_type
        self.section = section


@dataclass(slots=True)
class ContentControl(Block):
    blocks: list[Block] = field(default_factory=list)
    tag: str | None = None
    alias: str | None = None
    control_id: str | None = None
    control_type: str | None = None
    lock: str | None = None
    data_binding: dict[str, str] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)

    def __init__(self, blocks: list[Block] | None = None, tag: str | None = None,
                 alias: str | None = None, control_id: str | None = None,
                 control_type: str | None = None, lock: str | None = None,
                 data_binding: dict[str, str] | None = None,
                 raw: dict[str, Any] | None = None):
        self.kind = "content_control"
        self.blocks = blocks or []
        self.tag = tag
        self.alias = alias
        self.control_id = control_id
        self.control_type = control_type
        self.lock = lock
        self.data_binding = data_binding or {}
        self.raw = raw or {}


@dataclass(slots=True)
class RawBlock(Block):
    format: str
    data: str
    fallback: list[Block] = field(default_factory=list)
    description: str | None = None

    def __init__(self, format: str, data: str, fallback: list[Block] | None = None,
                 description: str | None = None):
        self.kind = "raw"
        self.format = format
        self.data = data
        self.fallback = fallback or []
        self.description = description


@dataclass(slots=True)
class Comment:
    comment_id: str
    author: str | None = None
    initials: str | None = None
    date: str | None = None
    blocks: list[Block] = field(default_factory=list)
    parent_id: str | None = None
    done: bool | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class StyleDefinition:
    style_id: str
    name: str | None = None
    style_type: str = "paragraph"
    based_on: str | None = None
    next_style: str | None = None
    linked_style: str | None = None
    ui_priority: int | None = None
    qformat: bool = False
    hidden: bool = False
    semi_hidden: bool = False
    unhide_when_used: bool = False
    paragraph: ParagraphStyle = field(default_factory=ParagraphStyle)
    text: TextStyle = field(default_factory=TextStyle)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Document:
    blocks: list[Block] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    sections: list[SectionProperties] = field(default_factory=lambda: [SectionProperties()])
    resources: dict[str, Resource] = field(default_factory=dict)
    styles: dict[str, StyleDefinition] = field(default_factory=dict)
    comments: dict[str, Comment] = field(default_factory=dict)
    footnotes: dict[str, list[Block]] = field(default_factory=dict)
    endnotes: dict[str, list[Block]] = field(default_factory=dict)
    custom_properties: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    source_format: str | None = None
    source_path: str | None = None
    source_text: str | None = None
    raw_package_parts: dict[str, bytes] = field(default_factory=dict)
    roundtrip: dict[str, Any] = field(default_factory=dict)

    def add_resource(self, resource: Resource) -> str:
        self.resources[resource.id] = resource
        return resource.id

    @property
    def section(self) -> SectionProperties:
        if not self.sections:
            self.sections.append(SectionProperties())
        return self.sections[-1]

    def walk_blocks(self, blocks: Iterable[Block] | None = None) -> Iterable[Block]:
        for block in blocks if blocks is not None else self.blocks:
            yield block
            if isinstance(block, ListBlock):
                for item in block.items:
                    yield from self.walk_blocks(item.blocks)
            elif isinstance(block, Table):
                for row in block.rows:
                    for cell in row.cells:
                        yield from self.walk_blocks(cell.blocks)
            elif isinstance(block, Figure):
                yield from self.walk_blocks(block.body)
            elif isinstance(block, Quote):
                yield from self.walk_blocks(block.blocks)
            elif isinstance(block, ContentControl):
                yield from self.walk_blocks(block.blocks)
            elif isinstance(block, RawBlock):
                yield from self.walk_blocks(block.fallback)


def as_serializable(value: Any) -> Any:
    if isinstance(value, bytes):
        return {"$bytes": len(value)}
    if isinstance(value, Path):
        return str(value)
    if is_dataclass(value):
        return {key: as_serializable(val) for key, val in asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): as_serializable(val) for key, val in value.items()}
    if isinstance(value, (list, tuple)):
        return [as_serializable(item) for item in value]
    return value
