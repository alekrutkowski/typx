from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Literal

from .model import (
    Block,
    Bookmark,
    Border,
    Break,
    BreakBlock,
    Change,
    Citation,
    CodeBlock,
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
    MathBlock,
    MathInline,
    NoteRef,
    Paragraph,
    ParagraphStyle,
    Quote,
    Reference,
    RawBlock,
    RawInline,
    Resource,
    SectionProperties,
    Table,
    TableCell,
    TableRow,
    Text,
    TextStyle,
)
from .roundtrip import decode_raw_fragment, extract_docx_from_typst
from .util import (
    coalesce_text,
    dimensions_points,
    escape_typst_text,
    find_balanced,
    guess_media_type,
    normalize_hex_color,
    parse_float,
    parse_int,
    parse_typst_length,
    quote_typst_string,
    sanitize_filename,
    sha256_bytes,
    split_top_level,
    strip_outer,
    unescape_typst_string,
)


@dataclass(slots=True)
class TypstReadOptions:
    root: Path | None = None
    resolve_includes: bool = True
    load_assets: bool = True
    unknown: Literal["preserve", "drop"] = "preserve"
    max_include_depth: int = 16
    max_asset_size: int = 512 * 1024 * 1024


@dataclass(slots=True)
class TypstExpression:
    raw: str
    start: int
    end: int
    name: str | None = None
    positional: list[str] = field(default_factory=list)
    named: dict[str, str] = field(default_factory=dict)
    body: str | None = None
    command: str | None = None
    tail: str = ""


@dataclass(slots=True)
class _ParseContext:
    text_style: TextStyle = field(default_factory=TextStyle)
    paragraph_style: ParagraphStyle = field(default_factory=ParagraphStyle)
    variables: dict[str, Any] = field(default_factory=dict)
    heading_numbering: str | None = None
    heading_supplement: str | None = None
    figure_numbering: str | None = "1"
    figure_supplement: str | None = None
    equation_numbering: str | None = None
    equation_supplement: str | None = None
    list_marker: str | None = None
    enum_numbering: str | None = None

    def copy(self) -> "_ParseContext":
        return _ParseContext(
            text_style=self.text_style.copy(),
            paragraph_style=self.paragraph_style.copy(),
            variables=dict(self.variables),
            heading_numbering=self.heading_numbering,
            heading_supplement=self.heading_supplement,
            figure_numbering=self.figure_numbering,
            figure_supplement=self.figure_supplement,
            equation_numbering=self.equation_numbering,
            equation_supplement=self.equation_supplement,
            list_marker=self.list_marker,
            enum_numbering=self.enum_numbering,
        )


_IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_-]*(?:\.[A-Za-z_][A-Za-z0-9_-]*)*")


def _skip_space_comments(source: str, index: int) -> int:
    while index < len(source):
        if source[index].isspace():
            index += 1
        elif source.startswith("//", index):
            end = source.find("\n", index + 2)
            index = len(source) if end < 0 else end + 1
        elif source.startswith("/*", index):
            depth = 1
            cursor = index + 2
            while cursor < len(source) and depth:
                if source.startswith("/*", cursor):
                    depth += 1; cursor += 2
                elif source.startswith("*/", cursor):
                    depth -= 1; cursor += 2
                else:
                    cursor += 1
            index = cursor
        else:
            break
    return index


def _scan_string(source: str, index: int) -> int:
    quote = source[index]
    cursor = index + 1
    escaped = False
    while cursor < len(source):
        ch = source[cursor]
        if escaped:
            escaped = False
        elif ch == "\\":
            escaped = True
        elif ch == quote:
            return cursor + 1
        cursor += 1
    return len(source)


def _scan_balanced_with_comments(source: str, index: int, open_char: str, close_char: str) -> int:
    if index >= len(source) or source[index] != open_char:
        return index
    depth = 1
    cursor = index + 1
    while cursor < len(source):
        if source[cursor] == '"':
            cursor = _scan_string(source, cursor)
            continue
        if source.startswith("//", cursor):
            end = source.find("\n", cursor + 2)
            cursor = len(source) if end < 0 else end + 1
            continue
        if source.startswith("/*", cursor):
            nested = 1
            cursor += 2
            while cursor < len(source) and nested:
                if source.startswith("/*", cursor):
                    nested += 1; cursor += 2
                elif source.startswith("*/", cursor):
                    nested -= 1; cursor += 2
                else:
                    cursor += 1
            continue
        ch = source[cursor]
        if ch == open_char:
            depth += 1
        elif ch == close_char:
            depth -= 1
            if depth == 0:
                return cursor + 1
        cursor += 1
    return len(source)



def _scan_statement_end(source: str, index: int) -> int:
    """Scan one top-level Typst code statement, respecting nested delimiters."""
    stack: list[str] = []
    pairs = {"(": ")", "[": "]", "{": "}"}
    cursor = index
    while cursor < len(source):
        if source[cursor] == '"':
            cursor = _scan_string(source, cursor)
            continue
        if source.startswith("//", cursor):
            end = source.find("\n", cursor + 2)
            return len(source) if end < 0 else end
        if source.startswith("/*", cursor):
            depth = 1; cursor += 2
            while cursor < len(source) and depth:
                if source.startswith("/*", cursor): depth += 1; cursor += 2
                elif source.startswith("*/", cursor): depth -= 1; cursor += 2
                else: cursor += 1
            continue
        ch = source[cursor]
        if ch in pairs:
            stack.append(pairs[ch])
        elif stack and ch == stack[-1]:
            stack.pop()
        elif not stack and ch in "\r\n;":
            return cursor
        cursor += 1
    return cursor

def _parse_call_arguments(raw: str) -> tuple[list[str], dict[str, str]]:
    positional: list[str] = []
    named: dict[str, str] = {}
    for part in split_top_level(raw):
        if not part:
            continue
        match = re.match(r"^([A-Za-z_][A-Za-z0-9_-]*)\s*:\s*(.*)$", part, re.DOTALL)
        if match:
            named[match.group(1)] = match.group(2).strip()
        else:
            positional.append(part)
    return positional, named


def parse_hash_expression(source: str, index: int) -> TypstExpression | None:
    if index >= len(source) or source[index] != "#":
        return None
    start = index
    index += 1
    if index >= len(source):
        return TypstExpression("#", start, index)
    # Embedded parenthesized/code/content expressions.
    if source[index] in "([{":
        pairs = {"(": ")", "[": "]", "{": "}"}
        end = _scan_balanced_with_comments(source, index, source[index], pairs[source[index]])
        return TypstExpression(source[start:end], start, end, name=None, body=source[index + 1:end - 1])
    command_match = re.match(r"(set|show|let|import|include)\b", source[index:])
    command = None
    if command_match:
        command = command_match.group(1)
        index += command_match.end()
        index = _skip_space_comments(source, index)
    ident_match = _IDENTIFIER_RE.match(source, index)
    if not ident_match:
        # Include/import commonly take a quoted path directly. Show/let can
        # also begin with patterns that are not identifiers. Preserve the
        # complete top-level statement in those cases.
        if command in {"let", "show", "import", "include"}:
            end = _scan_statement_end(source, index)
            return TypstExpression(source[start:end], start, end, command=command)
        # Literal code expression, consume to a safe inline boundary.
        end = index
        while end < len(source) and source[end] not in " \t\r\n,;[]{}()":
            end += 1
        return TypstExpression(source[start:end], start, end, command=command)
    name = ident_match.group(0)
    index = ident_match.end()
    positional: list[str] = []
    named: dict[str, str] = {}
    body = None
    # Function calls and method chains. Preserve the complete chain in tail.
    if index < len(source) and source[index] == "(":
        end = _scan_balanced_with_comments(source, index, "(", ")")
        positional, named = _parse_call_arguments(source[index + 1:end - 1])
        index = end
    # A content block may follow a function call, with optional whitespace.
    after = index
    while after < len(source) and source[after] in " \t":
        after += 1
    if after < len(source) and source[after] == "[":
        end = _scan_balanced_with_comments(source, after, "[", "]")
        body = source[after + 1:end - 1]
        index = end
    # Consume method/property chains such as #counter(page).display().
    chain_start = index
    while index < len(source) and source[index] == ".":
        dot = index
        index += 1
        method = _IDENTIFIER_RE.match(source, index)
        if not method:
            index = dot
            break
        index = method.end()
        if index < len(source) and source[index] == "(":
            index = _scan_balanced_with_comments(source, index, "(", ")")
    tail = source[chain_start:index]
    if command in {"let", "show", "import", "include"}:
        index = _scan_statement_end(source, index)
    # Labels can follow referenceable function calls. Keep them in raw so the
    # semantic handler can reconstruct bookmarks and cross-references.
    after = index
    while after < len(source) and source[after] in " \t":
        after += 1
    label_match = re.match(r"<[A-Za-z0-9_.:-]+>", source[after:])
    if label_match:
        index = after + label_match.end()
    return TypstExpression(source[start:index], start, index, name, positional, named, body, command, tail)


def parse_call_value(value: str) -> TypstExpression | None:
    stripped = value.strip()
    match = _IDENTIFIER_RE.match(stripped)
    if not match:
        return None
    name = match.group(0)
    index = match.end()
    positional: list[str] = []
    named: dict[str, str] = {}
    body = None
    if index < len(stripped) and stripped[index] == "(":
        end = _scan_balanced_with_comments(stripped, index, "(", ")")
        if end <= index or end > len(stripped):
            return None
        positional, named = _parse_call_arguments(stripped[index + 1:end - 1])
        index = end
    while index < len(stripped) and stripped[index].isspace():
        index += 1
    if index < len(stripped) and stripped[index] == "[":
        end = _scan_balanced_with_comments(stripped, index, "[", "]")
        body = stripped[index + 1:end - 1]
        index = end
    if stripped[index:].strip():
        return None
    return TypstExpression(stripped, 0, len(stripped), name, positional, named, body)


class TypstReader:
    def __init__(self, source: str, source_path: Path | None = None,
                 options: TypstReadOptions | None = None, include_depth: int = 0):
        self.original_source = source
        self.source_path = source_path
        self.options = options or TypstReadOptions()
        if self.options.root is None and source_path is not None:
            self.options.root = source_path.parent
        self.include_depth = include_depth
        self.doc = Document(source_format="typst", source_path=str(source_path) if source_path else None,
                            source_text=source)
        self.context = _ParseContext()
        self._resource_by_path: dict[str, str] = {}
        self._label_counter = 0
        payload = extract_docx_from_typst(source)
        if payload:
            self.doc.roundtrip["embedded_docx"] = payload
            source = payload.body
        self.source = source.lstrip("\ufeff")

    @classmethod
    def read(cls, source: str | Path, options: TypstReadOptions | None = None) -> Document:
        if isinstance(source, Path) or (isinstance(source, str) and "\n" not in source and Path(source).exists()):
            path = Path(source)
            text = path.read_text(encoding="utf-8")
            return cls(text, path, options).parse()
        return cls(str(source), None, options).parse()

    def parse(self) -> Document:
        self.doc.blocks = self._parse_blocks(self.source, self.context)
        if not self.doc.sections:
            self.doc.sections = [SectionProperties()]
        self._resolve_numbering_and_references()
        return self.doc

    # ---------- block parser ----------

    def _parse_blocks(self, source: str, context: _ParseContext) -> list[Block]:
        lines = source.splitlines(keepends=True)
        offsets: list[int] = []
        offset = 0
        for line in lines:
            offsets.append(offset)
            offset += len(line)
        blocks: list[Block] = []
        paragraph_lines: list[str] = []

        def flush_paragraph() -> None:
            if not paragraph_lines:
                return
            raw = "".join(paragraph_lines)
            paragraph_lines.clear()
            # Single markup newlines are spaces; escaped newlines remain explicit.
            raw = re.sub(r"(?<!\\)\n", " ", raw).strip()
            if raw:
                blocks.append(Paragraph(self._parse_inlines(raw, context.text_style), context.paragraph_style.copy()))

        i = 0
        while i < len(lines):
            line = lines[i]
            stripped = line.strip()
            left = line.lstrip(" \t")
            indent = len(line) - len(left)
            if not stripped:
                flush_paragraph(); i += 1; continue
            if left.startswith("//"):
                i += 1; continue
            if left.startswith("/*"):
                # Consume a possibly nested block comment.
                joined = "".join(lines[i:])
                depth = 0; cursor = 0
                while cursor < len(joined):
                    if joined.startswith("/*", cursor): depth += 1; cursor += 2
                    elif joined.startswith("*/", cursor):
                        depth -= 1; cursor += 2
                        if depth == 0: break
                    else: cursor += 1
                consumed = joined[:cursor].count("\n")
                i += max(1, consumed); continue
            # Raw fenced block.
            fence_match = re.match(r"^(`{3,})([^\n`]*)\n?$", left)
            if fence_match:
                flush_paragraph()
                fence = fence_match.group(1)
                language = fence_match.group(2).strip() or None
                content: list[str] = []
                i += 1
                while i < len(lines) and not lines[i].lstrip().startswith(fence):
                    content.append(lines[i]); i += 1
                if i < len(lines): i += 1
                raw_style = context.text_style.copy()
                raw_style.font = "DejaVu Sans Mono"
                raw_style.size_pt = 0.8 * (context.text_style.size_pt or 11.0)
                blocks.append(CodeBlock("".join(content).rstrip("\n"), language, style=raw_style))
                continue
            # Markup heading.
            heading_match = re.match(r"^(=+)\s+(.*?)(?:\n)?$", left, re.DOTALL)
            if heading_match:
                flush_paragraph()
                level = min(6, len(heading_match.group(1)))
                body_text, label = self._extract_trailing_label(heading_match.group(2))
                heading_style = context.text_style.copy()
                if heading_style.size_pt is not None:
                    heading_style.size_pt *= 1.4 if level == 1 else 1.2 if level == 2 else 1.0
                blocks.append(Heading(level, self._parse_inlines(body_text, heading_style),
                                      numbering=context.heading_numbering, label=label,
                                      supplement=context.heading_supplement))
                i += 1; continue
            # Markup lists and term lists.
            if re.match(r"^[-+]\s+", left) or re.match(r"^/\s+", left):
                flush_paragraph()
                list_block, i = self._parse_markup_list(lines, i, context)
                blocks.append(list_block)
                continue
            # Display equation delimited on its own line.
            if stripped.startswith("$"):
                math_text, consumed, is_display = self._consume_math_block(lines, i)
                if is_display:
                    flush_paragraph()
                    body, label = self._extract_trailing_label(math_text)
                    blocks.append(MathBlock(body.strip("$\n "), label=label,
                                            numbering=context.equation_numbering,
                                            supplement=context.equation_supplement))
                    i += consumed; continue
            # Top-level code expression.
            if left.startswith("#"):
                absolute = offsets[i] + indent
                expression = parse_hash_expression(source, absolute)
                if expression:
                    end_line = source.count("\n", 0, expression.end)
                    line_end_abs = source.find("\n", expression.end)
                    if line_end_abs < 0: line_end_abs = len(source)
                    only_expression = not source[expression.end:line_end_abs].strip()
                    if only_expression:
                        flush_paragraph()
                        handled = self._handle_top_expression(expression, context)
                        if handled is not None:
                            blocks.extend(handled)
                        i = max(i + 1, end_line + 1)
                        continue
            paragraph_lines.append(line)
            i += 1
        flush_paragraph()
        return blocks

    def _consume_math_block(self, lines: list[str], index: int) -> tuple[str, int, bool]:
        first = lines[index].strip()
        single_line = re.match(r"^\$\s+(.*?)\s+\$\s*(<([A-Za-z0-9_.:-]+)>)?\s*$", first, re.DOTALL)
        if single_line:
            label = single_line.group(2) or ""
            return single_line.group(1) + ((" " + label) if label else ""), 1, True
        if first.count("$") >= 2 and not (first.startswith("$ ") or first.endswith(" $")):
            return first, 1, False
        # A line consisting of '$', or opening '$ ' convention, is treated as display.
        if first == "$":
            content = []
            cursor = index + 1
            while cursor < len(lines) and lines[cursor].strip() != "$":
                content.append(lines[cursor]); cursor += 1
            if cursor < len(lines):
                return "".join(content), cursor - index + 1, True
        if first.startswith("$") and not first.endswith("$"):
            content = [lines[index][lines[index].find("$") + 1:]]
            cursor = index + 1
            while cursor < len(lines):
                pos = lines[cursor].rfind("$")
                if pos >= 0:
                    content.append(lines[cursor][:pos])
                    return "".join(content), cursor - index + 1, True
                content.append(lines[cursor]); cursor += 1
        if first.startswith("$ ") and first.endswith(" $"):
            return first[1:-1], 1, True
        return first, 1, False

    def _parse_markup_list(self, lines: list[str], start: int,
                           context: _ParseContext) -> tuple[ListBlock, int]:
        base_indent = len(lines[start]) - len(lines[start].lstrip(" \t"))
        root: ListBlock | None = None
        stack: list[tuple[int, ListBlock, ListItem | None]] = []
        i = start
        while i < len(lines):
            line = lines[i].rstrip("\r\n")
            left = line.lstrip(" \t")
            indent = len(line) - len(left)
            marker_match = re.match(r"^([-+])\s+(.*)$", left, re.DOTALL)
            term_match = re.match(r"^/\s+(.+?):\s*(.*)$", left, re.DOTALL)
            if not marker_match and not term_match:
                if stack and indent > stack[-1][0] and left.strip():
                    item = stack[-1][2]
                    if item:
                        continuation = self._parse_blocks(left, context.copy())
                        if continuation and isinstance(item.blocks[0], Paragraph) and isinstance(continuation[0], Paragraph):
                            item.blocks[0].inlines.append(Text(" "))
                            item.blocks[0].inlines.extend(continuation[0].inlines)
                            item.blocks.extend(continuation[1:])
                        else:
                            item.blocks.extend(continuation)
                    i += 1; continue
                break
            if indent < base_indent:
                break
            if term_match:
                ordered = False
                content = term_match.group(2)
                term = self._parse_inlines(term_match.group(1), context.text_style)
                is_terms = True
            else:
                ordered = marker_match.group(1) == "+"
                content = marker_match.group(2)
                term = None
                is_terms = False
            while stack and stack[-1][0] > indent:
                stack.pop()
            if stack and stack[-1][0] == indent and stack[-1][1].ordered == ordered and bool(stack[-1][1].marker == "terms") == is_terms:
                target = stack[-1][1]
            else:
                target = ListBlock(
                    ordered=ordered,
                    marker="terms" if is_terms else context.list_marker,
                    number_format=self._number_format_from_pattern(context.enum_numbering) if ordered else "decimal",
                )
                if not stack:
                    root = target
                else:
                    parent_item = stack[-1][2]
                    if parent_item is not None:
                        parent_item.blocks.append(target)
                stack.append((indent, target, None))
            # Typst has no special Markdown-style task-list syntax.  A literal
            # ``[x]`` or ``[ ]`` after a list marker is ordinary content and must
            # remain ordinary text rather than being rewritten to checkbox glyphs.
            item = ListItem(
                [Paragraph(self._parse_inlines(content, context.text_style), context.paragraph_style.copy())],
                None,
                term,
            )
            target.items.append(item)
            stack[-1] = (indent, target, item)
            i += 1
        return root or ListBlock(False), i

    # ---------- top-level expression handlers ----------

    def _handle_top_expression(self, expr: TypstExpression,
                               context: _ParseContext) -> list[Block] | None:
        if expr.command == "set":
            self._apply_set(expr, context)
            return []
        if expr.command == "let":
            self._apply_let(expr, context)
            return []
        if expr.command == "include":
            return self._handle_include(expr, context)
        if expr.command in {"import", "show"}:
            return [self._raw_typst_block(expr.raw, [], f"Typst {expr.command} rule")]
        name = expr.name or ""
        if name in {"pagebreak", "colbreak"}:
            return [BreakBlock("page" if name == "pagebreak" else "column")]
        if name == "divider":
            stroke = expr.named.get("stroke", "0.75pt")
            thickness = parse_typst_length(stroke.split("+")[0].strip()) or 0.75
            color_match = re.search(r"#([0-9A-Fa-f]{6})", stroke)
            return [Divider(thickness, color_match.group(1).upper() if color_match else "808080")]
        if name in {"heading", "title"}:
            body = expr.body or (expr.positional[-1] if expr.positional else "")
            level = 0 if name == "title" else parse_int(self._literal(expr.named.get("level", "1"), context), 1) or 1
            label = self._label_from_expr(expr)
            heading_style = context.text_style.copy()
            if heading_style.size_pt is not None:
                heading_style.size_pt *= 1.7 if level == 0 else 1.4 if level == 1 else 1.2 if level == 2 else 1.0
            return [Heading(level, self._parse_inlines(self._content_text(body), heading_style),
                            numbering=(self._string_value(expr.named.get("numbering"), context)
                                       if "numbering" in expr.named else context.heading_numbering),
                            label=label,
                            supplement=(self._string_value(expr.named.get("supplement"), context)
                                        if "supplement" in expr.named else context.heading_supplement),
                            outlined=self._bool_value(expr.named.get("outlined"), True, context),
                            bookmarked=self._bool_value(expr.named.get("bookmarked"), True, context))]
        if name in {"table", "grid"}:
            return [self._parse_table_expression(expr, context)]
        if name == "figure":
            return [self._parse_figure_expression(expr, context)]
        if name == "quote":
            body = expr.body or expr.named.get("body") or (expr.positional[0] if expr.positional else "")
            attribution = expr.named.get("attribution")
            return [Quote(self._parse_content_blocks(body, context),
                          self._parse_inlines(self._content_text(attribution or ""), context.text_style),
                          self._bool_value(expr.named.get("block"), True, context))]
        if name in {"raw"}:
            text = self._string_value(expr.positional[0] if expr.positional else expr.body, context) or ""
            language = self._string_value(expr.named.get("lang"), context)
            block = self._bool_value(expr.named.get("block"), True, context)
            raw_style = context.text_style.copy()
            raw_style.font = "DejaVu Sans Mono"
            raw_style.size_pt = 0.8 * (context.text_style.size_pt or 11.0)
            return [CodeBlock(text, language, block, style=raw_style)]
        if name in {"equation", "math.equation"}:
            body = expr.body or (expr.positional[0] if expr.positional else "")
            return [MathBlock(
                self._content_text(body),
                numbering=(self._string_value(expr.named.get("numbering"), context)
                           if "numbering" in expr.named else context.equation_numbering),
                label=self._label_from_expr(expr),
                supplement=(self._string_value(expr.named.get("supplement"), context)
                            if "supplement" in expr.named else context.equation_supplement),
            )]
        if name in {"list", "enum", "terms"}:
            return [self._parse_list_expression(expr, context)]
        if name in {"par", "align", "block", "box", "pad", "columns", "place", "rotate", "scale", "skew", "move"}:
            return self._parse_layout_wrapper(expr, context)
        if name in {"image"}:
            inline = self._parse_image_expression(expr, context)
            return [Paragraph([inline], context.paragraph_style.copy())]
        if name in {"rect", "square", "circle", "ellipse", "line", "polygon", "curve"}:
            inline = self._shape_to_image(expr, context)
            return [Paragraph([inline], context.paragraph_style.copy())]
        if name == "outline":
            return [Paragraph([Field("TOC", [Text("Table of contents")])])]
        if name == "bibliography":
            path = self._string_value(expr.positional[0] if expr.positional else None, context)
            return [self._raw_typst_block(expr.raw, [Paragraph([Text(f"Bibliography{': ' + path if path else ''}")])], "Typst bibliography")]
        if name == "typx_raw":
            return self._parse_ty_px_raw_block(expr, context)
        if name == "typx_sdt":
            body = expr.named.get("body") or expr.body or ""
            return [ContentControl(
                self._parse_content_blocks(body, context),
                tag=self._string_value(expr.named.get("tag"), context),
                alias=self._string_value(expr.named.get("alias"), context),
                control_id=self._string_value(expr.named.get("id"), context),
                control_type=self._string_value(expr.named.get("kind"), context),
                lock=self._string_value(expr.named.get("lock"), context),
            )]
        # A generic block expression may still produce inline content.
        inline = self._handle_inline_expression(expr, context.text_style, context)
        if inline is not None:
            return [Paragraph(inline if isinstance(inline, list) else [inline], context.paragraph_style.copy())]
        return [self._raw_typst_block(expr.raw, [], f"Unsupported Typst expression #{name}")]

    def _apply_set(self, expr: TypstExpression, context: _ParseContext) -> None:
        name = expr.name or ""
        if name == "document":
            for key in ("title", "author", "description", "keywords", "date"):
                value = expr.named.get(key)
                if value is not None:
                    self.doc.metadata[key] = self._literal(value, context)
        elif name == "page":
            section = self.doc.sections[-1] if self.doc.sections else SectionProperties()
            for key, attr_name in (("width", "page_width_pt"), ("height", "page_height_pt")):
                if key in expr.named:
                    value = parse_typst_length(expr.named[key])
                    if value is not None: setattr(section, attr_name, value)
            margin = expr.named.get("margin")
            if margin:
                parsed = self._literal(margin, context)
                if isinstance(parsed, (int, float, str)):
                    points = parse_typst_length(str(parsed))
                    if points is not None:
                        section.margin_top_pt = section.margin_right_pt = section.margin_bottom_pt = section.margin_left_pt = points
                elif isinstance(parsed, dict):
                    # Typst's x/y margin shorthands address both opposing sides;
                    # explicit side values take precedence over the shorthand.
                    if "x" in parsed:
                        points = parse_typst_length(str(parsed["x"]))
                        if points is not None:
                            section.margin_left_pt = section.margin_right_pt = points
                    if "y" in parsed:
                        points = parse_typst_length(str(parsed["y"]))
                        if points is not None:
                            section.margin_top_pt = section.margin_bottom_pt = points
                    for key, attr_name in (("top", "margin_top_pt"), ("right", "margin_right_pt"),
                                           ("bottom", "margin_bottom_pt"), ("left", "margin_left_pt")):
                        if key in parsed:
                            points = parse_typst_length(str(parsed[key]))
                            if points is not None:
                                setattr(section, attr_name, points)
            columns = parse_int(self._literal(expr.named.get("columns", "1"), context), 1) or 1
            section.columns = columns
            if "numbering" in expr.named:
                section.page_numbering = self._string_value(expr.named.get("numbering"), context)
                section.page_number_format = self._page_number_format(section.page_numbering)
            if "number-align" in expr.named:
                section.page_number_align = self._string_value(expr.named.get("number-align"), context)
            for key, attr_name in (("header", "header_default"), ("footer", "footer_default")):
                if key in expr.named:
                    setattr(section, attr_name, self._parse_content_blocks(expr.named[key], context))
            if self.doc.sections:
                self.doc.sections[-1] = section
            else:
                self.doc.sections.append(section)
        elif name == "columns":
            section = self.doc.sections[-1] if self.doc.sections else SectionProperties()
            gutter = parse_typst_length(expr.named.get("gutter"))
            if gutter is not None:
                section.column_spacing_pt = gutter
                section.raw["typst_column_gutter_explicit"] = True
            if self.doc.sections:
                self.doc.sections[-1] = section
            else:
                self.doc.sections.append(section)
        elif name == "text":
            context.text_style = context.text_style.merged(self._style_from_text_args(expr.named, context))
        elif name == "par":
            context.paragraph_style = context.paragraph_style.merged(self._style_from_par_args(expr.named, context))
        elif name == "heading":
            if "numbering" in expr.named:
                context.heading_numbering = self._string_value(expr.named.get("numbering"), context)
            if "supplement" in expr.named:
                context.heading_supplement = self._string_value(expr.named.get("supplement"), context)
        elif name == "figure":
            if "numbering" in expr.named:
                context.figure_numbering = self._string_value(expr.named.get("numbering"), context)
            if "supplement" in expr.named:
                context.figure_supplement = self._string_value(expr.named.get("supplement"), context)
        elif name in {"equation", "math.equation"}:
            if "numbering" in expr.named:
                context.equation_numbering = self._string_value(expr.named.get("numbering"), context)
            if "supplement" in expr.named:
                context.equation_supplement = self._string_value(expr.named.get("supplement"), context)
        elif name == "list":
            context.list_marker = self._string_value(expr.named.get("marker"), context)
        elif name == "enum":
            context.enum_numbering = self._string_value(expr.named.get("numbering"), context)
        else:
            self.doc.warnings.append(f"preserved but did not evaluate set rule for {name}")

    def _apply_let(self, expr: TypstExpression, context: _ParseContext) -> None:
        # parse_hash_expression models the first identifier as expr.name. The remaining assignment is in source.
        raw = expr.raw
        match = re.match(r"#let\s+([A-Za-z_][A-Za-z0-9_-]*)\s*(?:\([^)]*\))?\s*=\s*(.*)$", raw, re.DOTALL)
        if not match:
            return
        name, value = match.group(1), match.group(2).strip()
        if "(" in raw[raw.find(name) + len(name):raw.find("=") if "=" in raw else len(raw)]:
            context.variables[name] = {"function": raw}
        else:
            context.variables[name] = self._literal(value, context)

    def _handle_include(self, expr: TypstExpression, context: _ParseContext) -> list[Block]:
        raw = expr.raw
        match = re.search(r"#include\s+(.+)$", raw, re.DOTALL)
        value = match.group(1).strip() if match else (expr.positional[0] if expr.positional else "")
        path_value = self._string_value(value, context)
        if not path_value or not self.options.resolve_includes or self.include_depth >= self.options.max_include_depth:
            return [self._raw_typst_block(raw, [], "Typst include")]
        path = self._resolve_path(path_value)
        if not path or not path.exists():
            self.doc.warnings.append(f"included file not found: {path_value}")
            return [self._raw_typst_block(raw, [], "Missing Typst include")]
        nested_options = TypstReadOptions(
            root=self.options.root,
            resolve_includes=self.options.resolve_includes,
            load_assets=self.options.load_assets,
            unknown=self.options.unknown,
            max_include_depth=self.options.max_include_depth,
            max_asset_size=self.options.max_asset_size,
        )
        nested = TypstReader(path.read_text(encoding="utf-8"), path, nested_options, self.include_depth + 1).parse()
        self.doc.resources.update(nested.resources)
        self.doc.warnings.extend(nested.warnings)
        return nested.blocks

    # ---------- inline parser ----------

    def _parse_inlines(self, source: str, base_style: TextStyle | None = None,
                       context: _ParseContext | None = None) -> list[Inline]:
        context = context or self.context
        base_style = base_style or context.text_style
        result: list[Inline] = []
        buffer: list[str] = []

        def flush() -> None:
            if buffer:
                result.append(Text("".join(buffer), base_style.copy()))
                buffer.clear()

        i = 0
        while i < len(source):
            if source.startswith("//", i):
                end = source.find("\n", i + 2)
                i = len(source) if end < 0 else end + 1
                if result and not isinstance(result[-1], Break): buffer.append(" ")
                continue
            if source.startswith("/*", i):
                depth = 1; cursor = i + 2
                while cursor < len(source) and depth:
                    if source.startswith("/*", cursor): depth += 1; cursor += 2
                    elif source.startswith("*/", cursor): depth -= 1; cursor += 2
                    else: cursor += 1
                i = cursor; continue
            ch = source[i]
            if ch == "\\":
                if i + 1 < len(source) and source[i + 1] == "\n":
                    flush(); result.append(Break("line")); i += 2; continue
                if i + 1 < len(source):
                    buffer.append(source[i + 1]); i += 2; continue
                flush(); result.append(Break("line")); i += 1; continue
            if ch in "*_":
                end = self._find_markup_delimiter(source, i + 1, ch)
                if end >= 0:
                    flush()
                    style = base_style.copy()
                    if ch == "*": style.bold = True
                    else: style.italic = True
                    result.extend(self._parse_inlines(source[i + 1:end], style, context))
                    i = end + 1; continue
            if ch == "`":
                fence_len = len(source[i:]) - len(source[i:].lstrip("`"))
                fence = "`" * fence_len
                end = source.find(fence, i + fence_len)
                if end >= 0:
                    flush()
                    raw = source[i + fence_len:end]
                    style = base_style.copy()
                    style.font = "DejaVu Sans Mono"
                    style.size_pt = 0.8 * (base_style.size_pt or 11.0)
                    result.append(RawInline("typst-raw", raw, [Text(raw, style)], "Typst raw text"))
                    i = end + fence_len; continue
            if ch == "$":
                end = self._find_unescaped(source, "$", i + 1)
                if end >= 0:
                    flush(); result.append(MathInline(source[i + 1:end].strip())); i = end + 1; continue
            if ch == "#":
                expr = parse_hash_expression(source, i)
                if expr and expr.end > i + 1:
                    flush()
                    handled = self._handle_inline_expression(expr, base_style, context)
                    if handled is None:
                        if self.options.unknown == "preserve":
                            result.append(RawInline("typst", expr.raw, [], f"Unsupported Typst inline #{expr.name or ''}"))
                    elif isinstance(handled, list):
                        result.extend(handled)
                    else:
                        result.append(handled)
                    i = expr.end; continue
            if ch == "@":
                match = re.match(r"@([A-Za-z0-9_.:-]+)", source[i:])
                if match:
                    flush(); label = match.group(1)
                    # Full stops, commas, and sentence punctuation are not part of a
                    # reference merely because labels may contain dots internally.
                    trimmed = label.rstrip(".,;!?")
                    if trimmed:
                        label = trimmed
                    end = i + 1 + len(label)
                    supplement = None
                    if end < len(source) and source[end] == "[":
                        close = _scan_balanced_with_comments(source, end, "[", "]")
                        supplement = source[end + 1:close - 1]; end = close
                    children = self._parse_inlines(supplement, base_style, context) if supplement is not None else []
                    result.append(Reference(label, children, self._content_text(supplement) if supplement is not None else None)); i = end; continue
            if ch == "<":
                match = re.match(r"<([A-Za-z0-9_.:-]+)>", source[i:])
                if match:
                    flush(); result.append(Bookmark(match.group(1))); i += match.end(); continue
            url = re.match(r"https?://[^\s<>\[\]]+", source[i:])
            if url:
                flush(); target = url.group(0).rstrip(".,;:!?)")
                result.append(Link(target, [Text(target, base_style.copy())])); i += len(target); continue
            if ch == "\n":
                buffer.append(" ")
            else:
                buffer.append(ch)
            i += 1
        flush()
        return coalesce_text(result)

    def _handle_inline_expression(self, expr: TypstExpression, base_style: TextStyle,
                                  context: _ParseContext) -> Inline | list[Inline] | None:
        name = expr.name or ""
        body_raw = expr.body or expr.named.get("body")
        body = self._parse_inlines(self._content_text(body_raw or ""), base_style, context) if body_raw is not None else []
        if name in context.variables:
            value = context.variables[name]
            if isinstance(value, str): return self._parse_inlines(value, base_style, context)
            if isinstance(value, (int, float, bool)): return Text(str(value).lower() if isinstance(value, bool) else str(value), base_style.copy())
        if name in {"strong", "emph", "underline", "strike", "smallcaps", "upper", "lower", "super", "sub", "highlight", "text"}:
            style = base_style.copy()
            if name == "strong": style.bold = True
            elif name == "emph": style.italic = True
            elif name == "underline": style.underline = "single"
            elif name == "strike": style.strike = True
            elif name == "smallcaps": style.small_caps = True
            elif name == "upper": style.all_caps = True
            elif name == "super": style.superscript = True
            elif name == "sub": style.subscript = True
            elif name == "highlight": style.highlight = self._color_value(expr.named.get("fill") or (expr.positional[0] if expr.positional else None), context)
            elif name == "text": style = style.merged(self._style_from_text_args(expr.named, context))
            source_body = self._content_text(body_raw or (expr.positional[-1] if expr.positional else ""))
            return self._parse_inlines(source_body, style, context)
        if name == "link":
            target_raw = expr.positional[0] if expr.positional else expr.named.get("dest", "")
            target = self._string_value(target_raw, context) or target_raw.strip("<>")
            return Link(target, body or [Text(target, base_style.copy())], anchor=target_raw.strip().startswith("<"))
        if name == "image":
            return self._parse_image_expression(expr, context)
        if name in {"linebreak"}:
            return Break("line")
        if name in {"pagebreak", "colbreak"}:
            return Break("page" if name == "pagebreak" else "column")
        if name == "footnote":
            note_body = self._parse_content_blocks(body_raw or (expr.positional[0] if expr.positional else ""), context)
            note_id = str(len(self.doc.footnotes) + 1)
            self.doc.footnotes[note_id] = note_body
            return NoteRef("footnote", note_id, note_body)
        if name in {"ref"}:
            target = self._string_value(expr.positional[0] if expr.positional else None, context) or ""
            supplement_raw = expr.named.get("supplement")
            supplement = self._content_text(supplement_raw) if supplement_raw is not None else None
            form = self._string_value(expr.named.get("form"), context) or "normal"
            if form not in {"normal", "page"}: form = "normal"
            return Reference(target.strip("<>"), body, supplement, form)
        if name == "cite":
            keys = [self._string_value(value, context) or value.strip("<>") for value in expr.positional]
            return Citation([key for key in keys if key], self._content_text(expr.named.get("supplement", "")) or None)
        if name == "raw":
            text = self._string_value(expr.positional[0] if expr.positional else body_raw, context) or ""
            style = base_style.copy()
            style.font = "DejaVu Sans Mono"
            style.size_pt = 0.8 * (base_style.size_pt or 11.0)
            return RawInline("typst-raw", text, [Text(text, style)], "Typst raw text")
        if name in {"box", "block", "align", "pad", "move", "place", "rotate", "scale", "skew", "hide"}:
            return body
        if name in {"h", "v"}:
            return Text(" ", base_style.copy())
        if name == "typx_raw":
            fallback = body
            fmt = self._string_value(expr.named.get("format"), context) or "unknown"
            data = self._string_value(expr.named.get("data"), context) or ""
            return RawInline(fmt, data, fallback, self._string_value(expr.named.get("description"), context))
        if name == "typx_field":
            code = self._string_value(expr.named.get("code"), context) or ""
            return Field(code, body, self._bool_value(expr.named.get("locked"), False, context),
                         self._bool_value(expr.named.get("dirty"), False, context))
        if name == "typx_change":
            kind = self._string_value(expr.named.get("kind"), context) or "insert"
            if kind not in {"insert", "delete", "move_from", "move_to"}: kind = "insert"
            return Change(kind, body, self._string_value(expr.named.get("author"), context),
                          self._string_value(expr.named.get("date"), context), self._string_value(expr.named.get("id"), context))
        if name == "typx_comment_ref":
            comment_id = self._string_value(expr.positional[0] if expr.positional else None, context) or ""
            from .model import CommentAnchor
            return CommentAnchor(comment_id, "reference")
        if name == "counter" and "display" in expr.tail:
            target = self._string_value(expr.positional[0] if expr.positional else None, context) or ""
            if target == "page": return Field("PAGE", [])
        if name == "datetime":
            return Field("DATE", body)
        if name in {"rect", "square", "circle", "ellipse", "line", "polygon", "curve"}:
            return self._shape_to_image(expr, context)
        if name == "metadata":
            return []
        return None

    # ---------- expression-specific conversions ----------

    def _parse_table_expression(self, expr: TypstExpression, context: _ParseContext) -> Table:
        columns_value = expr.named.get("columns")
        column_widths: list[float | None] = []
        columns_count = 1
        if columns_value:
            literal = self._literal(columns_value, context)
            if isinstance(literal, int):
                columns_count = max(1, literal)
            elif isinstance(literal, (list, tuple)):
                columns_count = max(1, len(literal))
                for value in literal:
                    column_widths.append(parse_typst_length(str(value)))
            else:
                columns_count = parse_int(literal, 1) or 1
        items: list[tuple[TableCell, bool]] = []
        for value in expr.positional:
            call = parse_call_value(value)
            if call and call.name in {"table.header", "table.footer"}:
                nested_values = call.positional
                if call.body is not None: nested_values = ["[" + call.body + "]"]
                for nested in nested_values:
                    items.append((self._table_cell_from_value(nested, context, header=call.name == "table.header"), call.name == "table.header"))
                continue
            if call and call.name == "table.cell":
                items.append((self._table_cell_from_expr(call, context), False)); continue
            if call and call.name in {"table.hline", "table.vline"}:
                continue
            items.append((self._table_cell_from_value(value, context), False))
        # Build logical rows while reserving columns occupied by row-spanning
        # cells from earlier rows.  Counting only the current row's colspans
        # places following cells one column too far to the right whenever a
        # previous row contains ``rowspan`` (for example API/Worker groups in
        # the complex-table regression fixture).
        rows: list[TableRow] = []
        row = TableRow()
        row_index = 0
        cursor = 0
        blocked_until = [0] * columns_count

        def find_slot(start_col: int, span: int) -> int | None:
            col = max(0, start_col)
            while col + span <= columns_count:
                if all(blocked_until[index] <= row_index for index in range(col, col + span)):
                    return col
                col += 1
            return None

        def advance_row() -> None:
            nonlocal row, row_index, cursor
            if row.cells:
                rows.append(row)
            row = TableRow()
            row_index += 1
            cursor = 0

        for cell, header in items:
            span = max(1, min(columns_count, cell.colspan))
            slot = find_slot(cursor, span)
            while slot is None:
                advance_row()
                slot = find_slot(0, span)
            cell.header = cell.header or header
            row.header = row.header or header
            row.cells.append(cell)
            for col in range(slot, slot + span):
                blocked_until[col] = max(blocked_until[col], row_index + max(1, cell.rowspan))
            cursor = slot + span
        if row.cells:
            rows.append(row)
        return Table(
            rows,
            column_widths,
            align=self._string_value(expr.named.get("align"), context),
            layout="fixed" if column_widths else "autofit",
            raw={"typst_kind": expr.name},
        )

    def _table_cell_from_value(self, value: str, context: _ParseContext,
                               header: bool = False) -> TableCell:
        call = parse_call_value(value)
        if call and call.name == "table.cell":
            cell = self._table_cell_from_expr(call, context); cell.header = header; return cell
        content = self._content_text(value)
        return TableCell(self._parse_content_blocks(content, context), header=header)

    def _table_cell_from_expr(self, expr: TypstExpression, context: _ParseContext) -> TableCell:
        body = expr.body or expr.named.get("body") or (expr.positional[-1] if expr.positional else "")
        return TableCell(
            blocks=self._parse_content_blocks(body, context),
            colspan=parse_int(self._literal(expr.named.get("colspan", "1"), context), 1) or 1,
            rowspan=parse_int(self._literal(expr.named.get("rowspan", "1"), context), 1) or 1,
            align=self._string_value(expr.named.get("align"), context),
            shading=self._color_value(expr.named.get("fill"), context),
            header=self._bool_value(expr.named.get("header"), False, context),
        )

    def _parse_figure_expression(self, expr: TypstExpression, context: _ParseContext) -> Figure:
        body_raw = expr.named.get("body") or expr.body or (expr.positional[0] if expr.positional else "")
        body_expr = parse_call_value(self._content_text(body_raw))
        if body_expr and body_expr.name in {"image", "rect", "square", "circle", "ellipse", "line", "polygon", "curve"}:
            inline = self._parse_image_expression(body_expr, context) if body_expr.name == "image" else self._shape_to_image(body_expr, context)
            body = [Paragraph([inline])]
        elif body_expr and body_expr.name in {"table", "grid"}:
            body = [self._parse_table_expression(body_expr, context)]
        else:
            body = self._parse_content_blocks(body_raw, context)
        caption_raw = expr.named.get("caption", "")
        return Figure(
            body=body,
            caption=self._parse_inlines(self._content_text(caption_raw), context.text_style),
            kind_name=self._string_value(expr.named.get("kind"), context) or "figure",
            label=self._label_from_expr(expr),
            numbering=(self._string_value(expr.named.get("numbering"), context)
                       if "numbering" in expr.named else context.figure_numbering),
            placement=self._string_value(expr.named.get("placement"), context),
            align=self._string_value(expr.named.get("align"), context),
            supplement=(self._string_value(expr.named.get("supplement"), context)
                        if "supplement" in expr.named else context.figure_supplement),
        )

    def _parse_list_expression(self, expr: TypstExpression, context: _ParseContext) -> ListBlock:
        ordered = expr.name == "enum"
        items: list[ListItem] = []
        for value in expr.positional:
            call = parse_call_value(value)
            if call and call.name in {"list.item", "enum.item", "terms.item"}:
                body = call.body or (call.positional[-1] if call.positional else "")
                term = self._parse_inlines(self._content_text(call.positional[0]), context.text_style) if call.name == "terms.item" and call.positional else None
                items.append(ListItem(self._parse_content_blocks(body, context), term=term))
            else:
                items.append(ListItem(self._parse_content_blocks(value, context)))
        numbering = (self._string_value(expr.named.get("numbering"), context)
                     if "numbering" in expr.named else context.enum_numbering)
        return ListBlock(
            ordered,
            items,
            start=parse_int(self._literal(expr.named.get("start", "1"), context), 1) or 1,
            number_format=self._number_format_from_pattern(numbering) if ordered else "decimal",
            marker=self._string_value(expr.named.get("marker"), context),
        )

    def _parse_layout_wrapper(self, expr: TypstExpression, context: _ParseContext) -> list[Block]:
        body_raw = expr.body or expr.named.get("body") or (expr.positional[-1] if expr.positional else "")
        nested_context = context.copy()
        if expr.name == "par": nested_context.paragraph_style = nested_context.paragraph_style.merged(self._style_from_par_args(expr.named, context))
        if expr.name == "align":
            align_raw = expr.positional[0] if expr.positional else expr.named.get("alignment")
            nested_context.paragraph_style.align = self._string_value(align_raw, context) or (align_raw or "").strip()
        if expr.name == "pad":
            for key, attr_name in (("left", "left_indent_pt"), ("right", "right_indent_pt")):
                if key in expr.named:
                    setattr(nested_context.paragraph_style, attr_name, parse_typst_length(expr.named[key]))
        if expr.name == "block":
            nested_context.paragraph_style.shading = self._color_value(expr.named.get("fill"), context)
        blocks = self._parse_content_blocks(body_raw, nested_context)
        if expr.name == "columns":
            count = parse_int(self._literal(expr.positional[0] if expr.positional else expr.named.get("count", "2"), context), 2) or 2
            section = self.doc.sections[-1] if self.doc.sections else SectionProperties()
            before = SectionProperties(**{name: getattr(section, name) for name in section.__dataclass_fields__})
            columns_section = SectionProperties(**{name: getattr(section, name) for name in section.__dataclass_fields__})
            before.section_type = "continuous"
            columns_section.section_type = "continuous"
            columns_section.columns = count
            gutter = parse_typst_length(expr.named.get("gutter"))
            if gutter is not None:
                columns_section.column_spacing_pt = gutter
                columns_section.raw["typst_column_gutter_explicit"] = True
            # A paragraph-level w:sectPr describes the section that ends at that
            # paragraph.  End the preceding one-column section first, then end the
            # temporary multi-column section after its content.
            return [BreakBlock("section", before), *blocks, BreakBlock("section", columns_section)]
        if expr.name in {"place", "rotate", "scale", "skew", "move"} and self.options.unknown == "preserve":
            return [self._raw_typst_block(expr.raw, blocks, f"Typst layout transform {expr.name}")]
        return blocks

    def _parse_image_expression(self, expr: TypstExpression, context: _ParseContext) -> ImageInline | RawInline:
        source_raw = expr.positional[0] if expr.positional else expr.named.get("source", "")
        path_value = self._string_value(source_raw, context)
        width = parse_typst_length(expr.named.get("width"))
        height = parse_typst_length(expr.named.get("height"))
        alt = self._string_value(expr.named.get("alt"), context)
        if not path_value:
            return RawInline("typst", expr.raw, [Text("[dynamic image]")], "Dynamic Typst image")
        path = self._resolve_path(path_value)
        data = None
        if self.options.load_assets and path and path.exists() and path.is_file():
            if path.stat().st_size <= self.options.max_asset_size:
                data = path.read_bytes()
            else:
                self.doc.warnings.append(f"image exceeds size limit: {path}")
        if data is None:
            resource_id = "img-path-" + hashlib.sha256(path_value.encode()).hexdigest()[:16]
            media_type = guess_media_type(path_value)
            self.doc.add_resource(Resource(resource_id, sanitize_filename(Path(path_value).name, "image"), media_type,
                                           source_path=str(path) if path else path_value, width_pt=width, height_pt=height, alt_text=alt))
            return ImageInline(resource_id, width, height, alt)
        checksum = sha256_bytes(data)
        resource_id = "img-" + checksum[:16]
        media_type = guess_media_type(path_value, data)
        natural_w, natural_h = dimensions_points(data, media_type)
        if width is not None and height is None and natural_w and natural_h:
            height = width * natural_h / natural_w
        elif height is not None and width is None and natural_w and natural_h:
            width = height * natural_w / natural_h
        resource = Resource(resource_id, sanitize_filename(Path(path_value).name, "image"), media_type, data=data,
                            source_path=str(path), width_pt=width or natural_w, height_pt=height or natural_h,
                            alt_text=alt, checksum=checksum)
        self.doc.add_resource(resource)
        return ImageInline(resource_id, width or natural_w, height or natural_h, alt)

    def _shape_to_image(self, expr: TypstExpression, context: _ParseContext) -> ImageInline:
        name = expr.name or "rect"
        width = parse_typst_length(expr.named.get("width")) or (parse_typst_length(expr.named.get("radius")) or 36) * (2 if name == "circle" else 1)
        height = parse_typst_length(expr.named.get("height")) or width
        if name == "line": height = max(1.0, parse_typst_length(expr.named.get("stroke", "1pt")) or 1.0)
        fill = self._color_value(expr.named.get("fill"), context) or "FFFFFF"
        stroke_value = expr.named.get("stroke")
        stroke = self._color_value(stroke_value, context) or "000000"
        stroke_width = parse_typst_length((stroke_value or "1pt").split("+")[0].strip()) or 1.0
        px_w = max(1, int(round(width * 96 / 72)))
        px_h = max(1, int(round(height * 96 / 72)))
        body_text = re.sub(r"\s+", " ", self._content_text(expr.body or "")).strip()
        if name in {"circle", "ellipse"}:
            shape = f'<ellipse cx="{px_w/2:g}" cy="{px_h/2:g}" rx="{max(0, px_w/2-stroke_width):g}" ry="{max(0, px_h/2-stroke_width):g}" fill="#{fill}" stroke="#{stroke}" stroke-width="{stroke_width:g}"/>'
        elif name == "line":
            shape = f'<line x1="0" y1="{px_h/2:g}" x2="{px_w}" y2="{px_h/2:g}" stroke="#{stroke}" stroke-width="{stroke_width:g}"/>'
        elif name == "polygon":
            points = f"0,{px_h} {px_w/2},0 {px_w},{px_h}"
            shape = f'<polygon points="{points}" fill="#{fill}" stroke="#{stroke}" stroke-width="{stroke_width:g}"/>'
        else:
            radius = parse_typst_length(expr.named.get("radius")) or 0
            shape = f'<rect x="{stroke_width/2:g}" y="{stroke_width/2:g}" width="{max(0, px_w-stroke_width):g}" height="{max(0, px_h-stroke_width):g}" rx="{radius:g}" fill="#{fill}" stroke="#{stroke}" stroke-width="{stroke_width:g}"/>'
        text_svg = ""
        if body_text:
            escaped = body_text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            text_svg = f'<text x="50%" y="50%" dominant-baseline="middle" text-anchor="middle" font-size="14">{escaped}</text>'
        svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="{px_w}" height="{px_h}" viewBox="0 0 {px_w} {px_h}">{shape}{text_svg}</svg>'.encode()
        checksum = sha256_bytes(svg); resource_id = "shape-" + checksum[:16]
        self.doc.add_resource(Resource(resource_id, resource_id + ".svg", "image/svg+xml", data=svg,
                                       width_pt=width, height_pt=height, checksum=checksum,
                                       raw={"typst_shape": expr.raw}))
        return ImageInline(resource_id, width, height, alt_text=f"Typst {name} shape")

    def _parse_ty_px_raw_block(self, expr: TypstExpression, context: _ParseContext) -> list[Block]:
        fmt = self._string_value(expr.named.get("format"), context) or "unknown"
        data = self._string_value(expr.named.get("data"), context) or ""
        body = self._parse_content_blocks(expr.named.get("body") or expr.body or "", context)
        return [RawBlock(fmt, data, body, self._string_value(expr.named.get("description"), context))]

    # ---------- counters and references ----------

    def _resolve_numbering_and_references(self) -> None:
        """Resolve the static counters that Typst would expose through references.

        typx is deliberately a static transpiler rather than a Typst evaluator.  Still,
        headings, figures, and equations use deterministic document-order counters in the
        supported subset, so resolving their visible reference text here is both safer and
        closer to Typst than copying ``@label`` literally into Word.
        """
        labels: dict[str, tuple[str, str | None, str | None]] = {}
        heading_counts = [0] * 9
        figure_counts: dict[str, int] = {}
        equation_count = 0

        for block in self.doc.walk_blocks():
            if isinstance(block, Heading):
                if block.numbering:
                    level = max(1, min(len(heading_counts), block.level or 1))
                    heading_counts[level - 1] += 1
                    for index in range(level, len(heading_counts)):
                        heading_counts[index] = 0
                    active = heading_counts[:level]
                    block.number_text = self._format_numbering_pattern(block.numbering, active)
                if block.label:
                    labels[block.label] = (
                        block.supplement if block.supplement is not None else "Section",
                        block.number_text,
                        "heading",
                    )
            elif isinstance(block, Figure):
                if block.numbering:
                    key = block.kind_name or "figure"
                    figure_counts[key] = figure_counts.get(key, 0) + 1
                    block.number_text = self._format_numbering_pattern(block.numbering, [figure_counts[key]])
                if block.label:
                    default_supplement = "Table" if block.kind_name == "table" else "Figure"
                    labels[block.label] = (
                        block.supplement if block.supplement is not None else default_supplement,
                        block.number_text,
                        "figure",
                    )
            elif isinstance(block, MathBlock):
                if block.numbering:
                    equation_count += 1
                    block.number_text = self._format_numbering_pattern(block.numbering, [equation_count])
                if block.label:
                    labels[block.label] = (
                        block.supplement if block.supplement is not None else "Equation",
                        block.number_text,
                        "equation",
                    )

        def resolve_inlines(inlines: list[Inline]) -> None:
            for inline in inlines:
                if isinstance(inline, Reference):
                    info = labels.get(inline.target)
                    if inline.form == "page":
                        # Word's PAGEREF field supplies the dynamic page number.  Keep a
                        # deterministic cached value for renderers that do not update fields.
                        if not inline.children:
                            inline.children = [Text("1")]
                        continue
                    if not info:
                        if not inline.children:
                            inline.children = [Text("@" + inline.target)]
                        self.doc.warnings.append(f"unresolved reference: <{inline.target}>")
                        continue
                    auto_supplement, number_text, kind = info
                    if not number_text:
                        if not inline.children:
                            inline.children = [Text("@" + inline.target)]
                        self.doc.warnings.append(f"reference target is not numbered: <{inline.target}>")
                        continue
                    supplement = inline.supplement if inline.supplement is not None else auto_supplement
                    # Typst's normal heading references omit the punctuation suffix from
                    # a heading numbering pattern.  For example, headings displayed as
                    # ``1.`` under ``numbering: "1."`` are referenced as ``Section 1``.
                    # Keep paired equation punctuation such as ``(1)`` intact.
                    reference_number = re.sub(r"[.,:;]+$", "", number_text) if kind == "heading" else number_text
                    label = f"{supplement} {reference_number}".strip() if supplement else reference_number
                    inline.children = [Text(label)]
                elif isinstance(inline, Link):
                    resolve_inlines(inline.children)
                elif isinstance(inline, Field):
                    resolve_inlines(inline.children)
                elif isinstance(inline, Citation):
                    resolve_inlines(inline.fallback)
                elif isinstance(inline, Change):
                    resolve_inlines(inline.children)
                elif isinstance(inline, RawInline):
                    resolve_inlines(inline.fallback)

        for block in self.doc.walk_blocks():
            if isinstance(block, (Paragraph, Heading)):
                resolve_inlines(block.inlines)
            elif isinstance(block, Figure):
                resolve_inlines(block.caption)
            elif isinstance(block, Quote):
                resolve_inlines(block.attribution)

    @classmethod
    def _format_numbering_pattern(cls, pattern: str, numbers: list[int]) -> str:
        if not numbers:
            return ""
        symbols = list(re.finditer(r"[1aAiI]", pattern))
        if not symbols:
            return str(numbers[-1])
        if len(symbols) == 1:
            match = symbols[0]
            prefix, suffix = pattern[:match.start()], pattern[match.end():]
            token = match.group(0)
            if len(numbers) == 1:
                return prefix + cls._format_counter(numbers[0], token) + suffix
            separator = suffix or "."
            core = separator.join(cls._format_counter(value, token) for value in numbers)
            return prefix + core + suffix
        rendered = pattern
        offset = 0
        for index, match in enumerate(symbols[:len(numbers)]):
            start, end = match.start() + offset, match.end() + offset
            replacement = cls._format_counter(numbers[index], match.group(0))
            rendered = rendered[:start] + replacement + rendered[end:]
            offset += len(replacement) - (match.end() - match.start())
        return rendered

    @staticmethod
    def _format_counter(value: int, token: str) -> str:
        if token == "1":
            return str(value)
        if token in {"a", "A"}:
            n = max(1, value)
            letters = ""
            while n:
                n, remainder = divmod(n - 1, 26)
                letters = chr(ord("a") + remainder) + letters
            return letters.upper() if token == "A" else letters
        if token in {"i", "I"}:
            n = max(1, value)
            pieces: list[str] = []
            for number, roman in ((1000, "M"), (900, "CM"), (500, "D"), (400, "CD"),
                                  (100, "C"), (90, "XC"), (50, "L"), (40, "XL"),
                                  (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")):
                while n >= number:
                    pieces.append(roman); n -= number
            result = "".join(pieces)
            return result if token == "I" else result.lower()
        return str(value)

    @staticmethod
    def _page_number_format(pattern: str | None) -> str | None:
        if not pattern:
            return None
        for token, fmt in (("I", "upperRoman"), ("i", "lowerRoman"),
                           ("A", "upperLetter"), ("a", "lowerLetter"), ("1", "decimal")):
            if token in pattern:
                return fmt
        return None

    @staticmethod
    def _number_format_from_pattern(pattern: str | None) -> str:
        if not pattern:
            return "decimal"
        match = re.search(r"[1aAiI]", pattern)
        token = match.group(0) if match else "1"
        return {"1": "decimal", "a": "lowerLetter", "A": "upperLetter",
                "i": "lowerRoman", "I": "upperRoman"}.get(token, "decimal")

    # ---------- literal/style helpers ----------

    def _literal(self, raw: str | None, context: _ParseContext) -> Any:
        if raw is None: return None
        text = raw.strip()
        if not text: return ""
        if text.startswith('"') and text.endswith('"'):
            try: return json.loads(text)
            except json.JSONDecodeError: return unescape_typst_string(text[1:-1])
        if text in {"true", "false"}: return text == "true"
        if text == "none": return None
        if text == "auto": return "auto"
        if re.fullmatch(r"[+-]?\d+", text): return int(text)
        if re.fullmatch(r"[+-]?(?:\d+\.\d*|\.\d+)(?:[eE][+-]?\d+)?", text): return float(text)
        if text.startswith("[") and _scan_balanced_with_comments(text, 0, "[", "]") == len(text): return text[1:-1]
        if text.startswith("(") and _scan_balanced_with_comments(text, 0, "(", ")") == len(text):
            parts = split_top_level(text[1:-1])
            dictionary = {}
            is_dict = False
            values = []
            for part in parts:
                match = re.match(r"^([A-Za-z_][A-Za-z0-9_-]*)\s*:\s*(.*)$", part, re.DOTALL)
                if match:
                    is_dict = True; dictionary[match.group(1)] = self._literal(match.group(2), context)
                elif part:
                    values.append(self._literal(part, context))
            return dictionary if is_dict else values
        if text in context.variables:
            return context.variables[text]
        return text

    def _string_value(self, raw: str | None, context: _ParseContext) -> str | None:
        value = self._literal(raw, context)
        if value is None: return None
        if isinstance(value, str):
            if value.startswith("[") and value.endswith("]"): return value[1:-1]
            return value
        return str(value)

    def _bool_value(self, raw: str | None, default: bool, context: _ParseContext) -> bool:
        value = self._literal(raw, context)
        return value if isinstance(value, bool) else default

    def _color_value(self, raw: str | None, context: _ParseContext) -> str | None:
        if not raw: return None
        text = str(self._literal(raw, context)).strip()
        match = re.search(r"#([0-9A-Fa-f]{3,8})", text)
        if match: return normalize_hex_color(match.group(1))
        match = re.match(r"rgb\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)", text)
        if match: return "".join(f"{min(255,int(x)):02X}" for x in match.groups())
        return normalize_hex_color(text)

    def _style_from_text_args(self, named: dict[str, str], context: _ParseContext) -> TextStyle:
        style = TextStyle()
        style.font = self._string_value(named.get("font"), context)
        style.size_pt = parse_typst_length(named.get("size"))
        style.color = self._color_value(named.get("fill"), context)
        style.highlight = self._color_value(named.get("highlight"), context)
        style.language = self._string_value(named.get("lang"), context)
        region = self._string_value(named.get("region"), context)
        if style.language and region: style.language += "-" + region
        style.letter_spacing_pt = parse_typst_length(named.get("tracking"))
        style.baseline_pt = parse_typst_length(named.get("baseline"))
        weight = self._string_value(named.get("weight"), context)
        if weight and (weight.lower() in {"bold", "semibold", "black"} or (parse_int(weight, 0) or 0) >= 600): style.bold = True
        font_style = self._string_value(named.get("style"), context)
        if font_style in {"italic", "oblique"}: style.italic = True
        direction = self._string_value(named.get("dir"), context)
        if direction in {"rtl", "right-to-left"}: style.rtl = True
        return style

    def _style_from_par_args(self, named: dict[str, str], context: _ParseContext) -> ParagraphStyle:
        style = ParagraphStyle()
        style.first_line_indent_pt = parse_typst_length(named.get("first-line-indent"))
        style.hanging_indent_pt = parse_typst_length(named.get("hanging-indent"))
        leading = parse_typst_length(named.get("leading"))
        if leading is not None:
            # Typst's leading is the extra distance between lines. Word stores
            # automatic line spacing as a multiplier of 240, so approximate it
            # relative to the active font size instead of treating it as an
            # impossibly small exact line height.
            font_size = context.text_style.size_pt or 11.0
            style.line_spacing = 1.0 + max(0.0, leading) / max(1.0, font_size)
            style.line_spacing_rule = "auto"
        if self._bool_value(named.get("justify"), False, context): style.align = "both"
        return style

    def _parse_content_blocks(self, raw: str, context: _ParseContext) -> list[Block]:
        return self._parse_blocks(self._content_text(raw), context.copy())

    @staticmethod
    def _content_text(raw: str) -> str:
        text = raw.strip()
        inner = strip_outer(text, "[", "]")
        return inner if inner is not None else text

    def _resolve_path(self, value: str) -> Path | None:
        value = value.replace("\\", "/")
        path = Path(value)
        if path.is_absolute(): return path
        base = self.source_path.parent if self.source_path else self.options.root
        return (base / path).resolve() if base else path

    def _raw_typst_block(self, raw: str, fallback: list[Block], description: str) -> RawBlock:
        return RawBlock("typst", raw, fallback, description) if self.options.unknown == "preserve" else RawBlock("typst", "", fallback, description)

    def _label_from_expr(self, expr: TypstExpression) -> str | None:
        raw = expr.raw
        match = re.search(r"<([A-Za-z0-9_.:-]+)>\s*$", raw)
        return match.group(1) if match else None

    @staticmethod
    def _extract_trailing_label(text: str) -> tuple[str, str | None]:
        match = re.search(r"\s*<([A-Za-z0-9_.:-]+)>\s*$", text)
        return (text[:match.start()].rstrip(), match.group(1)) if match else (text.strip(), None)

    @staticmethod
    def _find_markup_delimiter(source: str, start: int, delimiter: str) -> int:
        cursor = start
        while cursor < len(source):
            if source[cursor] == "\\": cursor += 2; continue
            if source[cursor] == delimiter: return cursor
            cursor += 1
        return -1

    @staticmethod
    def _find_unescaped(source: str, char: str, start: int) -> int:
        cursor = start
        while cursor < len(source):
            if source[cursor] == "\\": cursor += 2; continue
            if source[cursor] == char: return cursor
            cursor += 1
        return -1
