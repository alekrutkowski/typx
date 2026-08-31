from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .model import (
    Block,
    Bookmark,
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
    MathBlock,
    MathInline,
    NoteRef,
    Paragraph,
    ParagraphStyle,
    Quote,
    RawBlock,
    RawInline,
    Reference,
    SectionProperties,
    Table,
    TableCell,
    Text,
    TextStyle,
)
from .util import (
    escape_typst_string,
    escape_typst_text,
    format_typst_length,
    quote_typst_string,
    text_from_inlines,
    typst_color,
)


@dataclass(slots=True)
class TypstWriteOptions:
    output_path: Path | None = None
    assets_dir: Path | None = None
    emit_preamble: bool = True
    preserve_raw: bool = True
    preserve_comments: bool = True
    materialize_assets: bool = True
    line_width: int = 100


class TypstWriter:
    def __init__(self, document: Document, options: TypstWriteOptions | None = None):
        self.doc = document
        self.options = options or TypstWriteOptions()
        self._needs_raw = False
        self._needs_field = False
        self._needs_change = False
        self._needs_sdt = False
        self._needs_comment = False
        self._needs_citation = False
        self._has_bibliography_field = False
        self._asset_paths: dict[str, str] = {}

    def write(self) -> str:
        self._scan_features()
        self._materialize_assets()
        chunks: list[str] = []
        if self.options.emit_preamble:
            preamble = self._preamble()
            if preamble:
                chunks.append(preamble.rstrip())
        body = self._blocks(self.doc.blocks, indent=0).strip()
        if body:
            chunks.append(body)
        comments = self._comments_appendix()
        if comments:
            chunks.append(comments)
        return "\n\n".join(chunks).rstrip() + "\n"

    def _scan_features(self) -> None:
        def has_bibliography(items: Iterable[Inline]) -> bool:
            for item in items:
                if isinstance(item, Field) and re.match(r"^\s*BIBLIOGRAPHY(?:\s|$)", item.code, re.IGNORECASE):
                    return True
                if isinstance(item, (Link, Field, Change)) and has_bibliography(item.children):
                    return True
                if isinstance(item, RawInline) and has_bibliography(item.fallback):
                    return True
                if isinstance(item, Citation) and has_bibliography(item.fallback):
                    return True
            return False

        for block in self.doc.walk_blocks():
            items: list[Inline] = []
            if isinstance(block, (Paragraph, Heading)):
                items = block.inlines
            elif isinstance(block, Figure):
                items = block.caption
            elif isinstance(block, Quote):
                items = block.attribution
            if items and has_bibliography(items):
                self._has_bibliography_field = True
                break

        def inlines(items: Iterable[Inline]) -> None:
            for item in items:
                if isinstance(item, RawInline):
                    self._needs_raw = True
                    inlines(item.fallback)
                elif isinstance(item, Field):
                    if not self._field_has_native_mapping(item.code):
                        self._needs_field = True
                    inlines(item.children)
                elif isinstance(item, Change):
                    self._needs_change = True
                    inlines(item.children)
                elif isinstance(item, CommentAnchor):
                    self._needs_comment = True
                elif isinstance(item, Citation):
                    self._needs_citation = True
                    inlines(item.fallback)
                elif isinstance(item, Link):
                    inlines(item.children)
        for block in self.doc.walk_blocks():
            if isinstance(block, Paragraph):
                inlines(block.inlines)
            elif isinstance(block, Heading):
                inlines(block.inlines)
            elif isinstance(block, Figure):
                inlines(block.caption)
            elif isinstance(block, Quote):
                inlines(block.attribution)
            elif isinstance(block, ContentControl):
                self._needs_sdt = True
            elif isinstance(block, RawBlock):
                self._needs_raw = True
        if self.doc.comments:
            self._needs_comment = True

    def _materialize_assets(self) -> None:
        if not self.options.materialize_assets:
            return
        output_path = self.options.output_path
        assets_dir = self.options.assets_dir
        if assets_dir is None and output_path is not None:
            assets_dir = output_path.parent / f"{output_path.stem}_assets"
        for resource_id, resource in self.doc.resources.items():
            path: Path | None = None
            is_font = resource.raw.get("kind") == "font"
            if resource.source_path and Path(resource.source_path).exists() and not is_font:
                path = Path(resource.source_path)
            elif assets_dir is not None and (resource.data is not None or resource.source_path):
                path = assets_dir / resource.filename
                path.parent.mkdir(parents=True, exist_ok=True)
                if resource.data is not None:
                    if path.exists() and path.read_bytes() != resource.data:
                        path = path.with_name(f"{path.stem}-{resource.id[-8:]}{path.suffix}")
                    path.write_bytes(resource.data)
                elif resource.source_path:
                    source = Path(resource.source_path)
                    if path.exists():
                        try:
                            if source.resolve() == path.resolve():
                                pass
                            elif path.read_bytes() != source.read_bytes():
                                path = path.with_name(f"{path.stem}-{resource.id[-8:]}{path.suffix}")
                                shutil.copyfile(source, path)
                        except OSError:
                            shutil.copyfile(source, path)
                    else:
                        shutil.copyfile(source, path)
            if path:
                if output_path:
                    try:
                        rendered = os.path.relpath(path, output_path.parent).replace(os.sep, "/")
                    except ValueError:
                        rendered = str(path).replace(os.sep, "/")
                else:
                    rendered = str(path).replace(os.sep, "/")
                self._asset_paths[resource_id] = rendered

    def _preamble(self) -> str:
        lines: list[str] = [
            f"// Generated by typx from {self.doc.source_format or 'an intermediate document'}.",
            "// Unsupported constructs are retained in typx_* wrappers whose visible result is their fallback body.",
        ]
        font_paths = [self._asset_paths.get(resource_id) for resource_id in self.doc.font_resource_ids]
        font_paths = [path for path in font_paths if path]
        if font_paths:
            font_dirs = sorted(dict.fromkeys(os.path.dirname(path).replace("\\", "/") or "." for path in font_paths))
            lines.append("// Word fonts copied into this project: " + ", ".join(font_dirs) + ".")
            lines.append("// Typst.app discovers uploaded project fonts automatically.")
            for font_dir in font_dirs:
                lines.append(f"// Local CLI: typst compile --font-path {quote_typst_string(font_dir)} <file.typ>")
        metadata_args = []
        mapping = {"title": "title", "author": "author", "keywords": "keywords", "description": "description"}
        for source_key, target_key in mapping.items():
            value = self.doc.metadata.get(source_key)
            if value:
                if source_key == "keywords" and isinstance(value, str):
                    keyword_items = [part.strip() for part in re.split(r"[,;]", value) if part.strip()]
                    metadata_args.append(f"{target_key}: ({', '.join(quote_typst_string(x) for x in keyword_items)})")
                else:
                    metadata_args.append(f"{target_key}: {quote_typst_string(str(value))}")
        if metadata_args:
            lines.append("#set document(" + ", ".join(metadata_args) + ")")

        section = self.doc.sections[0] if self.doc.sections else SectionProperties()
        margin = (
            f"(top: {format_typst_length(section.margin_top_pt)}, "
            f"right: {format_typst_length(section.margin_right_pt)}, "
            f"bottom: {format_typst_length(section.margin_bottom_pt)}, "
            f"left: {format_typst_length(section.margin_left_pt)})"
        )
        page_args = [
            f"width: {format_typst_length(section.page_width_pt)}",
            f"height: {format_typst_length(section.page_height_pt)}",
            f"margin: {margin}",
        ]
        if section.columns > 1:
            page_args.append(f"columns: {section.columns}")
        if section.page_numbering:
            page_args.append(f"numbering: {quote_typst_string(section.page_numbering)}")
            if section.page_number_align:
                page_args.append(f"number-align: {section.page_number_align}")
        if section.header_default:
            page_args.append("header: [" + self._blocks(section.header_default, indent=1).strip() + "]")
        if section.footer_default:
            page_args.append("footer: [" + self._blocks(section.footer_default, indent=1).strip() + "]")
        lines.append("#set page(" + ", ".join(page_args) + ")")
        if section.page_number_start is not None:
            lines.append(f"#counter(page).update({section.page_number_start})")

        defaults = self.doc.styles.get("__docDefaults__")
        if defaults:
            text_args = self._text_style_args(defaults.text)
            if text_args:
                lines.append("#set text(" + ", ".join(text_args) + ")")
            par_args = self._par_style_args(defaults.paragraph)
            if par_args:
                lines.append("#set par(" + ", ".join(par_args) + ")")

        if self._needs_raw:
            lines.extend([
                "#let typx_raw(format: \"unknown\", data: \"\", description: none, body: []) = body",
            ])
        if self._needs_field:
            lines.append("#let typx_field(code: \"\", locked: false, dirty: false, body: []) = body")
        if self._needs_change:
            lines.append("#let typx_change(kind: \"insert\", author: none, date: none, id: none, body: []) = body")
        if self._needs_sdt:
            lines.append("#let typx_sdt(tag: none, alias: none, id: none, kind: none, lock: none, binding: none, body: []) = body")
        if self._needs_comment:
            lines.append("#let typx_comment_ref(id) = metadata((kind: \"typx-comment-ref\", id: id))")
        return "\n".join(lines)

    def _blocks(self, blocks: Iterable[Block], indent: int = 0) -> str:
        rendered: list[str] = []
        for block in blocks:
            text = self._block(block, indent)
            if text:
                rendered.append(text.rstrip())
        return "\n\n".join(rendered)

    def _block(self, block: Block, indent: int) -> str:
        prefix = "  " * indent
        if isinstance(block, Heading):
            body = self._inlines(block.inlines)
            label = f" <{self._safe_label(block.label)}>" if block.label else ""
            if block.level <= 0:
                return prefix + f"#title[{body}]{label}"
            return prefix + "=" * max(1, min(6, block.level)) + " " + body + label
        if isinstance(block, Paragraph):
            body = self._inlines(block.inlines)
            return prefix + self._wrap_paragraph(body, block.style)
        if isinstance(block, ListBlock):
            return self._list(block, indent)
        if isinstance(block, Table):
            return prefix + self._table(block, indent)
        if isinstance(block, Figure):
            body = self._blocks(block.body, indent + 1).strip()
            caption = self._inlines(block.caption)
            args = [f"body: [{body}]"]
            if caption:
                args.append(f"caption: [{caption}]")
            if block.kind_name and block.kind_name != "figure":
                args.append(f"kind: {quote_typst_string(block.kind_name)}")
            if block.numbering:
                args.append(f"numbering: {quote_typst_string(block.numbering)}")
            if block.supplement:
                args.append(f"supplement: {quote_typst_string(block.supplement)}")
            figure = "#figure(" + ", ".join(args) + ")"
            if block.label:
                figure += f" <{self._safe_label(block.label)}>"
            return prefix + figure
        if isinstance(block, Quote):
            body = self._blocks(block.blocks, indent + 1).strip()
            args = [f"block: {'true' if block.block_quote else 'false'}", f"body: [{body}]"]
            if block.attribution:
                args.append(f"attribution: [{self._inlines(block.attribution)}]")
            return prefix + "#quote(" + ", ".join(args) + ")"
        if isinstance(block, CodeBlock):
            language = block.language or ""
            fence = "```"
            while fence in block.text:
                fence += "`"
            return prefix + f"{fence}{language}\n{block.text.rstrip()}\n{fence}"
        if isinstance(block, MathBlock):
            body = block.typst.strip()
            if block.numbering:
                args = [f"numbering: {quote_typst_string(block.numbering)}"]
                if block.supplement:
                    args.append(f"supplement: {quote_typst_string(block.supplement)}")
                result = prefix + "#math.equation(" + ", ".join(args) + ")[" + body + "]"
                if block.label:
                    result += f" <{self._safe_label(block.label)}>"
                return result
            result = prefix + "$\n" + self._indent_text(body, indent + 1) + "\n" + prefix + "$"
            if block.label:
                result += f" <{self._safe_label(block.label)}>"
            return result
        if isinstance(block, Divider):
            return prefix + f"#divider(stroke: {format_typst_length(block.thickness_pt)} + {typst_color(block.color)})"
        if isinstance(block, BreakBlock):
            if block.break_type == "column":
                return prefix + "#colbreak()"
            if block.break_type == "section":
                section = block.section or SectionProperties()
                return prefix + self._section_break(section)
            return prefix + "#pagebreak()"
        if isinstance(block, ContentControl):
            self._needs_sdt = True
            body = self._blocks(block.blocks, indent + 1).strip()
            args = []
            for key, value in (("tag", block.tag), ("alias", block.alias), ("id", block.control_id),
                               ("kind", block.control_type), ("lock", block.lock)):
                if value is not None:
                    args.append(f"{key}: {quote_typst_string(str(value))}")
            if block.data_binding:
                entries = ", ".join(f"{key}: {quote_typst_string(str(value))}" for key, value in block.data_binding.items())
                args.append(f"binding: ({entries})")
            args.append(f"body: [{body}]")
            return prefix + "#typx_sdt(" + ", ".join(args) + ")"
        if isinstance(block, RawBlock):
            fallback = self._blocks(block.fallback, indent + 1).strip()
            if not self.options.preserve_raw:
                return prefix + fallback
            args = [f"format: {quote_typst_string(block.format)}", f"data: {quote_typst_string(block.data)}"]
            if block.description:
                args.append(f"description: {quote_typst_string(block.description)}")
            args.append(f"body: [{fallback}]")
            return prefix + "#typx_raw(" + ", ".join(args) + ")"
        return prefix + f"// typx: unhandled IR block {type(block).__name__}"

    def _section_break(self, section: SectionProperties) -> str:
        margin = (
            f"(top: {format_typst_length(section.margin_top_pt)}, right: {format_typst_length(section.margin_right_pt)}, "
            f"bottom: {format_typst_length(section.margin_bottom_pt)}, left: {format_typst_length(section.margin_left_pt)})"
        )
        args = [
            f"width: {format_typst_length(section.page_width_pt)}",
            f"height: {format_typst_length(section.page_height_pt)}",
            f"margin: {margin}",
        ]
        if section.columns > 1:
            args.append(f"columns: {section.columns}")
        if section.page_numbering:
            args.append(f"numbering: {quote_typst_string(section.page_numbering)}")
            if section.page_number_align:
                args.append(f"number-align: {section.page_number_align}")
        if section.header_default:
            args.append("header: [" + self._blocks(section.header_default, indent=1).strip() + "]")
        if section.footer_default:
            args.append("footer: [" + self._blocks(section.footer_default, indent=1).strip() + "]")

        # Word section boundaries can be continuous.  A continuous boundary
        # should alter page settings without forcing a new page in Typst.
        prefix = "" if (section.section_type or "").lower() == "continuous" else "#pagebreak()\n"
        result = prefix + "#set page(" + ", ".join(args) + ")"
        if section.page_number_start is not None:
            result += f"\n#counter(page).update({section.page_number_start})"
        return result

    def _wrap_paragraph(self, body: str, style: ParagraphStyle) -> str:
        result = body
        wrappers: list[tuple[str, list[str]]] = []
        if style.align and style.align not in {"left", "start"}:
            align = {"both": "left + horizon", "distribute": "left + horizon"}.get(style.align, style.align)
            wrappers.append(("align", [align]))
        padding = []
        if style.left_indent_pt:
            padding.append(f"left: {format_typst_length(style.left_indent_pt)}")
        if style.right_indent_pt:
            padding.append(f"right: {format_typst_length(style.right_indent_pt)}")
        if padding:
            wrappers.append(("pad", padding))
        par_args = self._par_style_args(style)
        if par_args:
            wrappers.append(("par", par_args))
        if style.shading or style.borders or style.keep_lines:
            block_args = []
            if style.shading:
                block_args.append(f"fill: {typst_color(style.shading)}")
            if style.borders:
                border = next(iter(style.borders.values()))
                block_args.append(f"stroke: {format_typst_length(border.width_pt)} + {typst_color(border.color)}")
            if style.keep_lines:
                block_args.append("breakable: false")
            block_args.append("inset: 2pt")
            wrappers.append(("block", block_args))
        for name, args in wrappers:
            if name == "align":
                result = f"#align({args[0]})[{result}]"
            else:
                result = f"#{name}({', '.join(args)})[{result}]"
        before = f"#v({format_typst_length(style.space_before_pt)})\n" if style.space_before_pt else ""
        after = f"\n#v({format_typst_length(style.space_after_pt)})" if style.space_after_pt else ""
        return before + result + after

    def _list(self, block: ListBlock, indent: int) -> str:
        lines: list[str] = []
        marker = "+" if block.ordered else "-"
        for index, item in enumerate(block.items):
            if not item.blocks:
                lines.append("  " * indent + marker)
                continue
            first, *rest = item.blocks
            if isinstance(first, Paragraph):
                first_text = self._inlines(first.inlines)
            else:
                first_text = self._block(first, 0).strip()
            checkbox = "[x] " if item.checked is True else "[ ] " if item.checked is False else ""
            lines.append("  " * indent + marker + " " + checkbox + first_text)
            for extra in rest:
                if isinstance(extra, ListBlock):
                    lines.append(self._list(extra, indent + 1))
                else:
                    lines.append(self._indent_text(self._block(extra, 0).strip(), indent + 1))
        if block.ordered and block.start != 1:
            body = "\n".join(lines)
            return "  " * indent + f"#enum(start: {block.start})[\n{self._indent_text(body, 1)}\n" + "  " * indent + "]"
        return "\n".join(lines)

    def _table(self, table: Table, indent: int) -> str:
        max_columns = max((sum(cell.colspan for cell in row.cells) for row in table.rows), default=1)
        if table.column_widths_pt:
            columns = []
            for width in table.column_widths_pt[:max_columns]:
                columns.append(format_typst_length(width) if width else "auto")
            columns.extend("auto" for _ in range(max_columns - len(columns)))
            columns_arg = "(" + ", ".join(columns) + ("," if len(columns) == 1 else "") + ")"
        else:
            columns_arg = str(max_columns)
        args = [f"columns: {columns_arg}"]
        if table.align:
            args.append(f"align: {table.align}")
        if table.borders:
            border = next(iter(table.borders.values()))
            args.append(f"stroke: {format_typst_length(border.width_pt)} + {typst_color(border.color)}")
        if table.shading:
            args.append(f"fill: {typst_color(table.shading)}")
        cells: list[str] = []
        for row in table.rows:
            for cell in row.cells:
                body = self._blocks(cell.blocks, indent + 2).strip()
                cell_args = []
                if cell.colspan > 1:
                    cell_args.append(f"colspan: {cell.colspan}")
                if cell.rowspan > 1:
                    cell_args.append(f"rowspan: {cell.rowspan}")
                if cell.shading:
                    cell_args.append(f"fill: {typst_color(cell.shading)}")
                if cell.align:
                    cell_args.append(f"align: {cell.align}")
                if cell.vertical_align:
                    vertical = {"center": "horizon", "bottom": "bottom", "top": "top"}.get(cell.vertical_align, cell.vertical_align)
                    cell_args.append(f"align: {vertical}")
                if cell.header or row.header:
                    constructor = "table.header" if not cell_args else "table.cell"
                else:
                    constructor = "table.cell" if cell_args else ""
                if constructor:
                    prefix = f"{constructor}({', '.join(cell_args)})" if cell_args else f"{constructor}"
                    cells.append(f"{prefix}[{body}]")
                else:
                    cells.append(f"[{body}]")
        content = ",\n".join(self._indent_text(cell, indent + 1) for cell in cells)
        if content:
            return "#table(\n" + self._indent_text(", ".join(args) + ",", indent + 1) + "\n" + content + "\n" + "  " * indent + ")"
        return "#table(" + ", ".join(args) + ")"

    def _inlines(self, inlines: Iterable[Inline]) -> str:
        return "".join(self._inline(inline) for inline in inlines)

    def _inline(self, inline: Inline) -> str:
        if isinstance(inline, Text):
            return self._styled_text(inline.text, inline.style)
        if isinstance(inline, Break):
            return {"tab": "#h(1em)", "line": " \\", "soft": "\n", "page": "#pagebreak()", "column": "#colbreak()"}.get(inline.break_type, " \\")
        if isinstance(inline, Link):
            body = self._inlines(inline.children) or escape_typst_text(inline.target)
            target = f"<{self._safe_label(inline.target)}>" if inline.anchor else quote_typst_string(inline.target)
            return f"#link({target})[{body}]"
        if isinstance(inline, Reference):
            target = f"<{self._safe_label(inline.target)}>"
            if inline.form == "page":
                args = [target, 'form: "page"']
                if inline.supplement is not None:
                    args.append(f"supplement: [{escape_typst_text(inline.supplement)}]")
                return "#ref(" + ", ".join(args) + ")"
            if inline.supplement is not None:
                return f"@{self._safe_label(inline.target)}[{escape_typst_text(inline.supplement)}]"
            return "@" + self._safe_label(inline.target)
        if isinstance(inline, Bookmark):
            # Typst labels attach to the element/content immediately before them.
            # A DOCX bookmark range therefore maps most faithfully at bookmarkEnd.
            return f" <{self._safe_label(inline.name)}>" if inline.end else ""
        if isinstance(inline, ImageInline):
            path = self._asset_paths.get(inline.resource_id)
            resource = self.doc.resources.get(inline.resource_id)
            if not path and resource:
                path = resource.source_path or resource.filename
            if not path:
                return "[missing image]"
            args = [quote_typst_string(path)]
            if inline.width_pt:
                args.append(f"width: {format_typst_length(inline.width_pt)}")
            if inline.height_pt:
                args.append(f"height: {format_typst_length(inline.height_pt)}")
            if inline.alt_text:
                args.append(f"alt: {quote_typst_string(inline.alt_text)}")
            return "#image(" + ", ".join(args) + ")"
        if isinstance(inline, MathInline):
            return "$" + inline.typst.strip() + "$"
        if isinstance(inline, NoteRef):
            body = self._blocks(inline.body, 0).strip()
            if inline.note_type == "footnote":
                return f"#footnote[{body}]"
            return f"#typx_raw(format: \"docx-endnote\", data: {quote_typst_string(inline.note_id)}, body: [#footnote[{body}]])"
        if isinstance(inline, Field):
            native = self._native_field(inline)
            if native is not None:
                return native
            fallback = self._inlines(inline.children)
            args = [f"code: {quote_typst_string(inline.code)}"]
            if inline.locked:
                args.append("locked: true")
            if inline.dirty:
                args.append("dirty: true")
            args.append(f"body: [{fallback}]")
            return "#typx_field(" + ", ".join(args) + ")"
        if isinstance(inline, Citation):
            mapped = [self.doc.bibliography_keys.get(key, key) for key in inline.keys]
            if len(mapped) == 1:
                args = [f"label({quote_typst_string(mapped[0])})"]
                if inline.supplement:
                    args.append(f"supplement: [{escape_typst_text(inline.supplement)}]")
                return "#cite(" + ", ".join(args) + ")"
            fallback = self._inlines(inline.fallback)
            hidden = "".join(f"#cite(label({quote_typst_string(key)}), form: none)" for key in mapped)
            return hidden + (fallback or "".join(f"#cite(label({quote_typst_string(key)}))" for key in mapped))
        if isinstance(inline, CommentAnchor):
            if inline.event == "reference":
                return f"#typx_comment_ref({quote_typst_string(inline.comment_id)})"
            return f"#metadata((kind: {quote_typst_string('comment-' + inline.event)}, id: {quote_typst_string(inline.comment_id)}))"
        if isinstance(inline, Change):
            body = self._inlines(inline.children)
            args = [f"kind: {quote_typst_string(inline.change_type)}"]
            for key, value in (("author", inline.author), ("date", inline.date), ("id", inline.change_id)):
                if value:
                    args.append(f"{key}: {quote_typst_string(value)}")
            args.append(f"body: [{body}]")
            return "#typx_change(" + ", ".join(args) + ")"
        if isinstance(inline, RawInline):
            fallback = self._inlines(inline.fallback)
            if not self.options.preserve_raw:
                return fallback
            args = [f"format: {quote_typst_string(inline.format)}", f"data: {quote_typst_string(inline.data)}"]
            if inline.description:
                args.append(f"description: {quote_typst_string(inline.description)}")
            args.append(f"body: [{fallback}]")
            return "#typx_raw(" + ", ".join(args) + ")"
        return ""

    def _styled_text(self, text: str, style: TextStyle) -> str:
        body = escape_typst_text(text)
        if not body:
            return ""
        if style.bold:
            body = f"*{body}*"
        if style.italic:
            body = f"_{body}_"
        if style.underline:
            body = f"#underline[{body}]"
        if style.strike or style.double_strike:
            body = f"#strike[{body}]"
        if style.small_caps:
            body = f"#smallcaps[{body}]"
        if style.all_caps:
            body = f"#upper[{body}]"
        if style.superscript:
            body = f"#super[{body}]"
        if style.subscript:
            body = f"#sub[{body}]"
        if style.highlight:
            body = f"#highlight(fill: {typst_color(style.highlight)})[{body}]"
        args = self._text_style_args(style, exclude_simple=True)
        if args:
            body = f"#text({', '.join(args)})[{body}]"
        return body

    def _text_style_args(self, style: TextStyle, exclude_simple: bool = False) -> list[str]:
        args: list[str] = []
        if style.font:
            families = self.doc.font_families.get(style.font, [style.font])
            if len(families) == 1:
                args.append(f"font: {quote_typst_string(families[0])}")
            else:
                args.append("font: (" + ", ".join(quote_typst_string(family) for family in families) + ")")
        if style.size_pt:
            args.append(f"size: {format_typst_length(style.size_pt)}")
        if style.color:
            args.append(f"fill: {typst_color(style.color)}")
        if style.language:
            lang = style.language.split("-")[0]
            args.append(f"lang: {quote_typst_string(lang)}")
            if "-" in style.language:
                args.append(f"region: {quote_typst_string(style.language.split('-', 1)[1])}")
        if style.letter_spacing_pt:
            args.append(f"tracking: {format_typst_length(style.letter_spacing_pt)}")
        if style.baseline_pt:
            args.append(f"baseline: {format_typst_length(style.baseline_pt)}")
        if style.bold and not exclude_simple:
            args.append("weight: \"bold\"")
        if style.italic and not exclude_simple:
            args.append("style: \"italic\"")
        if style.hidden:
            args.append("fill: none")
        if style.rtl:
            args.append("dir: rtl")
        return args

    def _par_style_args(self, style: ParagraphStyle) -> list[str]:
        args: list[str] = []
        if style.line_spacing:
            if style.line_spacing_rule == "auto":
                # Word stores automatic line spacing as a multiple of its nominal
                # line box. Typst's `leading` is the inter-line gap. Calibrate the
                # common Word 1.15 line setting to Typst's 0.65em default rather
                # than subtracting a guessed 11pt font size (which made DOCX ->
                # Typst text and lists much too tight).
                leading_em = max(0.0, 0.65 * float(style.line_spacing) / 1.15)
                args.append(f"leading: {leading_em:.4g}em")
            else:
                args.append(f"leading: {format_typst_length(style.line_spacing)}")
        if style.first_line_indent_pt:
            args.append(f"first-line-indent: {format_typst_length(style.first_line_indent_pt)}")
        if style.hanging_indent_pt:
            args.append(f"hanging-indent: {format_typst_length(style.hanging_indent_pt)}")
        if style.align in {"both", "distribute"}:
            args.append("justify: true")
        return args

    def _field_has_native_mapping(self, code: str) -> bool:
        return self._native_field(Field(code, [])) is not None

    def _native_field(self, field: Field) -> str | None:
        code = re.sub(r"\s+", " ", field.code.strip())
        upper = code.upper()
        fallback = self._inlines(field.children)
        if re.match(r"^PAGE(?:\s|$)", upper):
            return "#context counter(page).display()"
        if re.match(r"^(NUMPAGES|SECTIONPAGES)(?:\s|$)", upper):
            return "#context counter(page).final().first()"
        if re.match(r"^TOC(?:\s|$)", upper):
            return "#outline()"
        match = re.match(r"^(PAGEREF|REF|NOTEREF)\s+([^ \\]+)", code, re.IGNORECASE)
        if match:
            label = self._safe_label(match.group(2))
            command = match.group(1).upper()
            if command == "PAGEREF":
                return f'#ref(<{label}>, form: "page")'
            # Word REF/NOTEREF may target an arbitrary bookmark.  Typst @label
            # references are semantic and require a referenceable element, so a
            # native internal link is the safe general mapping.  Preserve Word's
            # cached field result as the visible link text.
            body = fallback or escape_typst_text(match.group(2))
            return f"#link(<{label}>)[{body}]"
        match = re.match(r"^HYPERLINK\s+(?:\\l\s+)?\"([^\"]+)\"", code, re.IGNORECASE)
        if match:
            return f"#link({quote_typst_string(match.group(1))})[{fallback or escape_typst_text(match.group(1))}]"
        if re.match(r"^BIBLIOGRAPHY(?:\s|$)", upper):
            resource_id = self.doc.bibliography_resource_id
            if not resource_id:
                return fallback or None
            resource = self.doc.resources.get(resource_id)
            path = self._asset_paths.get(resource_id)
            if not path and resource:
                path = resource.source_path or resource.filename
            if not path:
                return fallback or None
            args = [quote_typst_string(path), "title: none"]
            if self.doc.bibliography_style:
                args.append(f"style: {quote_typst_string(self.doc.bibliography_style)}")
            return "#bibliography(" + ", ".join(args) + ")"
        match = re.match(r"^CITATION\s+(\"[^\"]+\"|[^ \\]+)", code, re.IGNORECASE)
        if match:
            if not self.doc.bibliography_resource_id or not self._has_bibliography_field:
                return fallback or None
            def unquote(value: str) -> str:
                return value[1:-1] if len(value) >= 2 and value.startswith('"') and value.endswith('"') else value
            keys = [unquote(match.group(1))]
            keys.extend(unquote(item) for item in re.findall(r"\\m\s+(\"[^\"]+\"|[^ \\]+)", code, re.IGNORECASE))
            mapped = [self.doc.bibliography_keys.get(key, key) for key in keys]
            page_match = re.search(r"\\p\s+(\"[^\"]*\"|[^ \\]+)", code, re.IGNORECASE)
            supplement = unquote(page_match.group(1)) if page_match else None
            if len(mapped) == 1:
                args = [f"label({quote_typst_string(mapped[0])})"]
                if supplement:
                    display_supplement = supplement if re.match(r"(?i)^p(?:p)?\.?\s", supplement) else f"p. {supplement}"
                    args.append(f"supplement: [{escape_typst_text(display_supplement)}]")
                return "#cite(" + ", ".join(args) + ")"
            hidden = "".join(f"#cite(label({quote_typst_string(key)}), form: none)" for key in mapped)
            return hidden + (fallback or "".join(f"#cite(label({quote_typst_string(key)}))" for key in mapped))
        if re.match(r"^(DATE|TIME|CREATEDATE|SAVEDATE|PRINTDATE)(?:\s|$)", upper):
            return fallback or "#datetime.today().display()"
        if re.match(r"^QUOTE(?:\s|$)", upper):
            return fallback
        if re.match(r"^SYMBOL\s+\d+", upper):
            return fallback
        return None

    def _comments_appendix(self) -> str:
        if not self.options.preserve_comments or not self.doc.comments:
            return ""
        lines = ["// DOCX comments preserved by typx:"]
        for comment_id, comment in sorted(self.doc.comments.items(), key=lambda item: item[0]):
            body = self._blocks(comment.blocks, 0).strip().replace("\n", " ")
            meta = ", ".join(filter(None, [comment.author, comment.date]))
            lines.append(f"// [{comment_id}] {meta}: {body}")
        return "\n".join(lines)

    @staticmethod
    def _safe_label(label: str | None) -> str:
        value = re.sub(r"[^A-Za-z0-9_.:-]+", "-", label or "label").strip("-")
        return value or "label"

    @staticmethod
    def _indent_text(text: str, level: int) -> str:
        prefix = "  " * level
        return "\n".join(prefix + line if line else line for line in text.splitlines())
