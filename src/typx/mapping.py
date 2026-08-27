from __future__ import annotations

import csv
import io
import json
from dataclasses import asdict, dataclass
from typing import Iterable

from .constants import OOXML_BASELINE, TYPST_BASELINE


@dataclass(frozen=True, slots=True)
class MappingEntry:
    id: str
    category: str
    typst: str
    typst_kind: str
    docx: str
    docx_part: str
    typst_to_docx: str
    docx_to_typst: str
    implementation_t2d: str
    implementation_d2t: str
    notes: str


SOURCES = [
    {
        "title": "Typst reference",
        "url": "https://typst.app/docs/reference/",
        "scope": "Language syntax, standard library, export and introspection reference",
    },
    {
        "title": "Typst 0.15.1 release",
        "url": "https://github.com/typst/typst/releases/tag/v0.15.1",
        "scope": "Pinned Typst baseline and 0.15 series changes",
    },
    {
        "title": "ECMA-376 Office Open XML",
        "url": "https://ecma-international.org/publications-and-standards/standards/ecma-376/",
        "scope": "OOXML parts 1 through 4 and OPC packaging baseline",
    },
    {
        "title": "Microsoft Word extensions to OOXML",
        "url": "https://learn.microsoft.com/en-us/openspecs/office_standards/ms-docx/b839fe1f-e1ca-4fa6-8c26-5954d0abbccd",
        "scope": "MS-DOCX protocol revision 23.0 extensions",
    },
    {
        "title": "WordprocessingML document structure",
        "url": "https://learn.microsoft.com/en-us/office/open-xml/word/structure-of-a-wordprocessingml-document",
        "scope": "WordprocessingML package and body hierarchy",
    },
]


_entries: list[MappingEntry] = []
_counter = 0


def _add(category: str, typst: str, typst_kind: str, docx: str, part: str,
         t2d: str, d2t: str, it2d: str, id2t: str, notes: str) -> None:
    global _counter
    _counter += 1
    _entries.append(MappingEntry(
        f"M{_counter:04d}", category, typst, typst_kind, docx, part,
        t2d, d2t, it2d, id2t, notes,
    ))


def _many(category: str, items: Iterable[str], typst_kind: str, docx: str, part: str,
          t2d: str, d2t: str, it2d: str, id2t: str, notes: str) -> None:
    for item in items:
        _add(category, item, typst_kind, docx, part, t2d, d2t, it2d, id2t, notes)


# Fidelity vocabulary used below:
# exact       – direct structural/semantic counterpart
# high        – generally equivalent with bounded property loss
# approximate – visible/semantic approximation
# preserve    – retained as raw counterpart data, not natively transformed
# evaluate    – requires executing Typst code or Word field/layout engines
# none        – no counterpart in the other format
#
# Implementation vocabulary:
# full, partial, preserve, none.

# Language and markup syntax.
_add("Language / markup", "plain markup text", "syntax", "w:p / w:r / w:t", "word/document.xml", "high", "high", "full", "full", "Unicode text and paragraph boundaries map directly; line wrapping is renderer-dependent.")
_add("Language / markup", "paragraph break (blank line)", "syntax", "w:p boundary", "word/document.xml", "exact", "exact", "full", "full", "A blank markup line becomes a new Word paragraph.")
_add("Language / markup", "escaped line break \\", "syntax", "w:br", "word/document.xml", "high", "high", "full", "full", "Typst linebreak and Word text-wrapping break are equivalent for ordinary text.")
_add("Language / markup", "non-breaking space / weak spacing", "syntax", "Unicode NBSP or w:noBreakHyphen / spacing", "word/document.xml", "approximate", "approximate", "partial", "partial", "Word has several special spacing characters; Typst has richer layout spacing semantics.")
_add("Language / markup", "*strong*", "syntax", "w:rPr/w:b", "word/document.xml", "exact", "exact", "full", "full", "Bold intent maps directly.")
_add("Language / markup", "_emphasis_", "syntax", "w:rPr/w:i", "word/document.xml", "exact", "exact", "full", "full", "Italic intent maps directly.")
_add("Language / markup", "`raw text` and fenced raw blocks", "syntax", "Code character/paragraph style and w:t", "word/document.xml + styles.xml", "high", "high", "full", "full", "Language tags are retained as metadata/style hints; Word does not natively syntax-highlight code.")
_add("Language / markup", "$inline math$", "syntax", "m:oMath", "word/document.xml", "high", "high", "full", "full", "Converted through OMML; unsupported math nodes retain raw OMML.")
_add("Language / markup", "$ display math $", "syntax", "m:oMathPara", "word/document.xml", "high", "high", "full", "full", "Display placement maps to an equation paragraph.")
_add("Language / markup", "= heading / #heading", "syntax + element", "Heading paragraph style + w:outlineLvl", "word/document.xml + styles.xml", "high", "high", "full", "full", "Levels, labels, and outline participation are retained; custom show rules are not evaluated.")
_add("Language / markup", "- bullet list", "syntax", "w:numPr + numbering.xml bullet level", "word/document.xml + numbering.xml", "high", "high", "full", "full", "Nested levels and custom bullet glyphs are supported.")
_add("Language / markup", "+ numbered list", "syntax", "w:numPr + numbering.xml numeric level", "word/document.xml + numbering.xml", "high", "high", "full", "full", "Starts and common decimal/letter/Roman formats map directly.")
_add("Language / markup", "/ term: description", "syntax", "definition-style paragraph sequence or table", "word/document.xml", "approximate", "approximate", "full", "partial", "WordprocessingML has no native definition-list element.")
_add("Language / markup", "[content block]", "syntax", "sequence of Word blocks/inlines", "word/document.xml", "high", "high", "full", "partial", "Content values are flattened to their materialized document tree.")
_add("Language / markup", "<label>", "syntax", "w:bookmarkStart / w:bookmarkEnd", "word/document.xml", "high", "high", "full", "full", "Word bookmark names are sanitized to Word's identifier constraints.")
_add("Language / markup", "@reference", "syntax", "REF/PAGEREF field or internal hyperlink", "word/document.xml", "high", "high", "full", "full", "Reference supplements and automatic localization may need Word field updates.")
_add("Language / markup", "URL / #link", "syntax + element", "w:hyperlink relationship or anchor", "document relationships", "exact", "exact", "full", "full", "External hyperlinks and internal targets are supported.")
_add("Language / markup", "// line comment", "syntax", "no visible Word node", "none", "none", "none", "none", "none", "Typst source comments are preserved only by embedded exact-roundtrip source.")
_add("Language / markup", "/* nested block comment */", "syntax", "no visible Word node", "none", "none", "none", "none", "none", "Comments are source-level, not document-level Word comments.")
_add("Language / markup", "# expression escape", "syntax", "materialized result or preservation payload", "customXml/typx-source.xml", "evaluate", "none", "partial", "none", "Literal/simple expressions are parsed; arbitrary computation is preserved rather than executed.")

_many("Language / code", [
    "#let binding", "function definition", "anonymous function", "function call", "named arguments",
    "positional arguments", "argument spreading", "destructuring binding", "if / else", "for loop",
    "while loop", "break", "continue", "return", "context expression", "set rule", "show rule",
    "show-set rule", "import", "include", "module member access", "method call", "array indexing",
    "dictionary access", "assignment", "compound assignment", "comparison operators", "boolean operators",
    "arithmetic operators", "range construction", "field access", "closure capture",
], "code construct", "No native OOXML language construct; materialized document result plus embedded Typst source", "customXml/typx-source.xml", "evaluate", "none", "partial", "none", "The converter is a structural parser, not the Typst engine. Literal bindings and static includes are handled; dynamic behavior is preserved in source/raw wrappers.")

# Foundation/value types.
_many("Foundations / values", [
    "none", "auto", "bool", "int", "float", "decimal", "fraction", "ratio", "angle", "length",
    "relative", "color", "gradient", "tiling/pattern", "stroke", "alignment", "direction", "array",
    "dictionary", "string", "bytes", "regex", "datetime", "duration", "version", "label", "content",
    "selector", "location", "counter", "state", "function", "type", "module", "plugin",
], "value/type", "Literal property, text, custom property, field, or embedded source depending on use", "multiple parts", "evaluate", "none", "partial", "none", "Values have no standalone DOCX equivalent. They map only when consumed by a document element; source-level identity is retained by the embedded Typst payload.")

# Document model.
_add("Document model", "document", "element", "core/app/custom document properties", "docProps/*.xml", "high", "high", "full", "full", "Title, author, subject, keywords, language, dates, description, category, and custom values are mapped.")
_add("Document model", "metadata", "element", "w:docVars, custom properties, semantic metadata", "settings.xml / docProps/custom.xml", "approximate", "approximate", "partial", "partial", "Metadata with no standard core property is stored as a custom property or raw payload.")
_add("Document model", "heading", "element", "w:p with heading style and outline level", "word/document.xml", "high", "high", "full", "full", "Numbering can be represented through numbering styles or SEQ/REF fields; complex show rules are preserved.")
_add("Document model", "outline", "element", "TOC field", "word/document.xml", "high", "high", "full", "full", "Word must update the TOC field to materialize current entries.")
_add("Document model", "figure", "element", "drawing/table/equation plus Caption paragraph and SEQ field", "word/document.xml", "high", "approximate", "full", "partial", "Word has captions but no general figure wrapper. Body and caption association is heuristic in DOCX to Typst.")
_add("Document model", "figure.caption", "element", "Caption style paragraph + SEQ field", "word/document.xml", "high", "high", "full", "partial", "Labels become bookmarks.")
_add("Document model", "quote", "element", "Quote-style paragraph(s)", "word/document.xml + styles.xml", "high", "high", "full", "full", "Attribution becomes a right-aligned quote paragraph.")
_add("Document model", "footnote", "element", "w:footnoteReference and footnotes part", "word/footnotes.xml", "exact", "exact", "full", "full", "Standard footnotes and their block content are supported.")
_add("Document model", "endnote", "conceptual extension", "w:endnoteReference and endnotes part", "word/endnotes.xml", "high", "exact", "full", "full", "Typst has native footnotes but no distinct endnote primitive; endnotes use preservation wrappers on the Typst side.")
_add("Document model", "ref", "element", "REF, PAGEREF, NOTEREF field", "word/document.xml", "high", "high", "full", "full", "Reference form selects field code or hyperlink.")
_add("Document model", "link", "element", "w:hyperlink", "word/document.xml + relationships", "exact", "exact", "full", "full", "Tooltip and internal/external targets are retained.")
_add("Document model", "bibliography", "element", "bibliography sources, CITATION/BIBLIOGRAPHY fields, or static paragraphs", "word/bibliography.xml / document.xml", "approximate", "approximate", "partial", "partial", "CSL processing and Word bibliography engines differ. Citation keys and visible fallback are retained.")
_add("Document model", "cite", "element", "CITATION field", "word/document.xml", "high", "high", "full", "partial", "Multiple keys and supplements are mapped to field switches where possible.")
_add("Document model", "numbering", "function", "w:numFmt / w:lvlText / field switches", "numbering.xml / document.xml", "high", "high", "partial", "partial", "Common Arabic, alphabetic, Roman, ordinal, and custom patterns are supported.")
_add("Document model", "list", "element", "numbering definition with bullet format", "numbering.xml", "high", "high", "full", "full", "Marker alignment/layout properties are approximated by indents and tabs.")
_add("Document model", "enum", "element", "numbering definition with numeric format", "numbering.xml", "high", "high", "full", "full", "Nested numbering and starts are supported.")
_add("Document model", "terms", "element", "definition-style paragraphs", "word/document.xml", "approximate", "approximate", "full", "partial", "No semantic WordprocessingML counterpart.")
_add("Document model", "table", "element", "w:tbl", "word/document.xml", "high", "high", "full", "full", "Rows, cells, widths, alignment, borders, shading, layout, caption, and description are covered.")
_add("Document model", "table.cell", "element", "w:tc / w:tcPr", "word/document.xml", "high", "high", "full", "full", "Column spans, row spans, cell margins, vertical alignment, direction, shading, and borders are supported.")
_add("Document model", "table.header", "configuration", "w:tblHeader row property", "word/document.xml", "high", "high", "full", "full", "Repeating header rows map directly.")
_add("Document model", "divider", "element", "paragraph bottom border", "word/document.xml", "high", "approximate", "full", "partial", "Word has no thematic-break element; a bordered empty paragraph is used.")
_add("Document model", "paragraph", "element", "w:p", "word/document.xml", "exact", "exact", "full", "full", "Paragraph style and direct formatting are merged into the intermediate model.")
_add("Document model", "linebreak", "element", "w:br", "word/document.xml", "exact", "exact", "full", "full", "Page and column break variants are also covered.")
_add("Document model", "smartquote", "element", "literal typographic quotation marks", "word/document.xml", "high", "approximate", "partial", "partial", "Word smart-quote behavior is an application option, not a persistent semantic node.")

# Text and paragraph formatting.
_text_map = [
    ("text.font", "w:rFonts", "high", "high"), ("text.size", "w:sz / w:szCs", "exact", "exact"),
    ("text.weight", "w:b / font weight", "high", "high"), ("text.style", "w:i", "high", "high"),
    ("text.fill", "w:color", "high", "high"), ("text.stroke", "w:outline or text effects", "approximate", "approximate"),
    ("text.tracking", "w:spacing", "high", "high"), ("text.stretch", "w:w", "high", "high"),
    ("text.baseline", "w:position", "high", "high"), ("text.lang", "w:lang/@w:val", "exact", "exact"),
    ("text.region", "BCP 47 region in w:lang", "high", "high"), ("text.script", "w:rFonts eastAsia/cs + w:lang", "approximate", "approximate"),
    ("text.dir", "w:rtl / paragraph bidi", "high", "high"), ("text.hyphenate", "w:suppressAutoHyphens/document settings", "approximate", "approximate"),
    ("text.costs", "no direct counterpart", "none", "none"), ("text.top-edge", "font metrics only", "none", "none"),
    ("text.bottom-edge", "font metrics only", "none", "none"), ("text.discretionary-ligatures", "OpenType feature settings", "approximate", "approximate"),
    ("text.historical-ligatures", "OpenType feature settings", "approximate", "approximate"), ("text.number-type", "OpenType feature settings", "approximate", "approximate"),
    ("text.number-width", "OpenType feature settings", "approximate", "approximate"), ("text.slashed-zero", "OpenType feature settings", "approximate", "approximate"),
    ("text.fractions", "OpenType feature settings", "approximate", "approximate"), ("text.stylistic-set", "OpenType feature settings", "approximate", "approximate"),
]
for typst, docx, t2d, d2t in _text_map:
    _add("Text formatting", typst, "property", docx, "word/document.xml + styles.xml", t2d, d2t,
         "full" if t2d in {"exact", "high"} else "partial" if t2d == "approximate" else "none",
         "full" if d2t in {"exact", "high"} else "partial" if d2t == "approximate" else "none",
         "Variable-font axes and arbitrary OpenType features may be retained only as raw formatting.")

_inline_styles = [
    ("strong", "w:b"), ("emph", "w:i"), ("underline", "w:u"), ("overline", "w:bar/text effect"),
    ("strike", "w:strike"), ("highlight", "w:highlight or w:shd"), ("smallcaps", "w:smallCaps"),
    ("upper", "w:caps or transformed text"), ("lower", "transformed text"), ("super", "w:vertAlign=superscript"),
    ("sub", "w:vertAlign=subscript"), ("hide", "w:vanish or omitted content"),
]
for typst, docx in _inline_styles:
    _add("Text formatting", typst, "element", docx, "word/document.xml", "high", "high", "full", "full", "Case transformation can be semantic in Typst but is often materialized as text in Word.")

_par_map = [
    ("par.leading", "w:spacing/@w:line", "approximate"), ("par.spacing", "w:spacing before/after", "high"),
    ("par.justify", "w:jc=both", "high"), ("par.linebreaks", "line-breaking application behavior", "approximate"),
    ("par.first-line-indent", "w:ind/@w:firstLine", "exact"), ("par.hanging-indent", "w:ind/@w:hanging", "exact"),
    ("par.indent", "w:ind left/right", "high"), ("par.orphan", "w:widowControl", "approximate"),
    ("par.widow", "w:widowControl", "approximate"), ("par.keep", "w:keepLines", "high"),
    ("par.keep-with-next", "w:keepNext", "high"), ("par.tabs", "w:tabs", "high"),
    ("par.align", "w:jc", "high"), ("par.direction", "w:bidi / w:textDirection", "high"),
]
for typst, docx, fidelity in _par_map:
    _add("Paragraph formatting", typst, "property", docx, "word/document.xml + styles.xml", fidelity, fidelity,
         "full" if fidelity in {"exact", "high"} else "partial", "full" if fidelity in {"exact", "high"} else "partial",
         "Typst and Word use different line-layout algorithms, so pagination can differ even when properties map.")

# Page and layout.
_layout_rows = [
    ("page.width / page.height / paper", "w:pgSz", "high", "high", "full", "full"),
    ("page.margin", "w:pgMar", "exact", "exact", "full", "full"),
    ("page.flipped / landscape", "w:pgSz/@w:orient", "high", "high", "full", "full"),
    ("page.columns", "w:cols", "high", "high", "full", "full"),
    ("page.header", "header part + w:headerReference", "high", "high", "full", "full"),
    ("page.footer", "footer part + w:footerReference", "high", "high", "full", "full"),
    ("page.numbering", "w:pgNumType + PAGE field", "high", "high", "full", "full"),
    ("page.background / fill", "VML/DrawingML background or page color", "approximate", "approximate", "partial", "preserve"),
    ("page.foreground", "header-layer drawing", "approximate", "none", "partial", "none"),
    ("page.binding / gutter", "w:pgMar/@w:gutter", "high", "high", "full", "full"),
    ("pagebreak", "w:br type=page or pageBreakBefore", "exact", "exact", "full", "full"),
    ("colbreak", "w:br type=column", "exact", "exact", "full", "full"),
    ("columns", "section columns", "high", "high", "full", "full"),
    ("align", "paragraph/table alignment", "high", "high", "full", "full"),
    ("block", "paragraph/table container properties", "approximate", "approximate", "partial", "partial"),
    ("box", "inline run/drawing/text box", "approximate", "approximate", "partial", "partial"),
    ("pad", "indents/cell margins/drawing offsets", "approximate", "approximate", "partial", "partial"),
    ("stack", "ordered paragraphs or positioned drawings", "approximate", "none", "partial", "none"),
    ("grid", "w:tbl", "high", "high", "full", "full"),
    ("place", "wp:anchor positioning", "approximate", "approximate", "partial", "partial"),
    ("move", "drawing offset", "approximate", "approximate", "partial", "partial"),
    ("rotate", "DrawingML transform", "high", "high", "partial", "preserve"),
    ("scale", "DrawingML extent/transform", "high", "high", "partial", "preserve"),
    ("skew", "DrawingML transform", "approximate", "preserve", "partial", "preserve"),
    ("repeat", "materialized repeated content", "evaluate", "none", "partial", "none"),
    ("measure", "no stored Word counterpart", "evaluate", "none", "none", "none"),
    ("layout", "materialized layout result", "evaluate", "none", "preserve", "none"),
]
for typst, docx, t2d, d2t, it2d, id2t in _layout_rows:
    _add("Page and layout", typst, "element/property", docx, "word/document.xml + section/header/footer parts", t2d, d2t, it2d, id2t,
         "Word is flow-layout oriented; arbitrary Typst layout closures and exact coordinates cannot always be reconstructed.")

# Visual elements and media.
_visual_rows = [
    ("image", "w:drawing + a:blip/pic:pic", "high", "high", "full", "full"),
    ("image.width / height", "wp:extent / a:xfrm", "exact", "exact", "full", "full"),
    ("image.alt", "wp:docPr/@descr", "high", "high", "full", "full"),
    ("image.fit / crop", "a:srcRect + extent", "high", "high", "full", "full"),
    ("image.format PNG/JPEG/GIF/BMP/TIFF/SVG/EMF/WMF/WebP", "media part + image relationship", "high", "high", "full", "full"),
    ("rect / square", "DrawingML shape or generated SVG", "high", "approximate", "partial", "preserve"),
    ("circle / ellipse", "DrawingML shape or generated SVG", "high", "approximate", "partial", "preserve"),
    ("line", "DrawingML line or generated SVG", "high", "approximate", "partial", "preserve"),
    ("polygon", "freeform geometry or generated SVG", "high", "approximate", "partial", "preserve"),
    ("curve / path", "DrawingML custom geometry or SVG", "approximate", "preserve", "partial", "preserve"),
    ("stroke", "a:ln / Word borders", "high", "high", "partial", "partial"),
    ("fill color", "a:solidFill / w:shd", "high", "high", "full", "full"),
    ("gradient", "a:gradFill", "high", "high", "partial", "preserve"),
    ("pattern / tiling", "a:pattFill / image fill", "approximate", "approximate", "partial", "preserve"),
    ("clip", "a:srcRect/custom geometry", "approximate", "preserve", "partial", "preserve"),
    ("opacity", "a:alpha", "high", "high", "partial", "preserve"),
]
for row in _visual_rows:
    _add("Visualize", row[0], "element/property", row[1], "word/document.xml + word/media/*", *row[2:], "The implementation favors portable images/SVG for Typst primitives; original OOXML drawings are retained as raw fragments on reverse conversion.")

# Mathematics.
_math_rows = [
    ("equation", "m:oMath / m:oMathPara"), ("frac", "m:f"), ("binom", "m:f with noBar"),
    ("sqrt / root", "m:rad"), ("super / sub / attach", "m:sSup / m:sSub / m:sSubSup / m:sPre"),
    ("limits", "m:limLow / m:limUpp / m:nary limits"), ("sum / product / integral / big operators", "m:nary"),
    ("lr delimiters", "m:d"), ("matrix / vector", "m:m"), ("cases / equation array", "m:eqArr or matrix"),
    ("accent", "m:acc"), ("overline / underline", "m:bar"), ("overbrace / underbrace", "m:groupChr"),
    ("operator/function", "m:func"), ("phantom/hide", "m:phant"), ("math text", "m:r / m:t"),
    ("math alignment points", "m:eqArr alignment / run layout", "approximate"),
    ("math font variants", "m:sty / m:scr / m:nor", "approximate"),
    ("math spacing", "m:ctrlPr and run spacing", "approximate"),
    ("math numbering/label", "SEQ field/bookmark beside equation", "high"),
]
for row in _math_rows:
    typst, docx = row[0], row[1]
    fidelity = row[2] if len(row) > 2 else "high"
    _add("Mathematics", typst, "math syntax/function", docx, "word/document.xml (OMML)", fidelity, fidelity,
         "full" if fidelity == "high" else "partial", "full" if fidelity == "high" else "partial",
         "The converter includes an OMML parser/emitter and preserves unrecognized OMML as compressed raw XML.")

# Introspection and state.
_many("Introspection", ["counter", "counter.get", "counter.at", "counter.display", "counter.final", "counter.update"],
      "contextual function", "PAGE/NUMPAGES/SEQ fields or numbering state", "word/document.xml", "evaluate", "approximate", "partial", "partial", "Built-in page and sequence counters map to fields; arbitrary custom counters require Typst execution.")
_many("Introspection", ["state", "state.get", "state.at", "state.final", "state.update"],
      "contextual function", "no native Word state machine", "customXml/typx-source.xml", "evaluate", "none", "preserve", "none", "State is source computation and is retained in the embedded source.")
_many("Introspection", ["query", "selector", "within", "here", "locate", "location", "context"],
      "contextual function/type", "materialized result; bookmarks/fields for selected cases", "document.xml + customXml", "evaluate", "none", "preserve", "none", "Word stores the result, not a general query over semantic Typst elements.")

# Data loading and export-specific constructs.
_data_rows = [
    ("read", "external file result", "evaluate"), ("csv", "table/text generated from CSV", "evaluate"),
    ("json", "materialized result or custom XML", "evaluate"), ("yaml", "materialized result", "evaluate"),
    ("toml", "materialized result", "evaluate"), ("xml", "customXml or materialized result", "evaluate"),
    ("cbor", "materialized result", "evaluate"), ("bibliography file", "bibliography sources/fields", "approximate"),
]
for typst, docx, fidelity in _data_rows:
    _add("Data loading", typst, "function", docx, "customXml/* / word/document.xml", fidelity, "none", "partial" if fidelity != "none" else "none", "none", "Static local includes/assets are read; arbitrary data transformations require the Typst engine.")

_export_rows = [
    ("pdf.artifact", "decorative/accessibility flag", "approximate"),
    ("pdf.attach", "OPC embedded package or OLE attachment", "approximate"),
    ("pdf.embed", "embedded file/object", "approximate"),
    ("PDF standards configuration", "no DOCX counterpart", "none"),
    ("HTML element", "Word content or altChunk HTML", "approximate"),
    ("html.frame", "SVG/image fallback", "approximate"),
    ("bundle", "multiple OPC parts/resources but not multi-output semantics", "none"),
]
for typst, docx, fidelity in _export_rows:
    _add("Export-specific", typst, "element/configuration", docx, "package-specific", fidelity, "none", "partial" if fidelity == "approximate" else "none", "none", "Export-target controls do not generally have a WordprocessingML semantic equivalent and are preserved in source.")


# Entries that complete the top-level Typst 0.15.1 reference inventory.
_foundation_function_rows = [
    ("arguments", "function argument bundle", "evaluate"),
    ("assert / assert.eq / assert.ne", "no document node; conversion-time diagnostic", "none"),
    ("calc and numeric calculation functions", "materialized numeric property or text", "evaluate"),
    ("eval", "materialized result plus embedded source", "evaluate"),
    ("panic", "no document node; evaluation failure", "none"),
    ("path", "OPC part URI, relationship target, or source asset path", "approximate"),
    ("repr", "materialized diagnostic text", "evaluate"),
    ("standard library namespace", "no document node", "none"),
    ("symbol", "Unicode scalar, symbol-font run, or drawing", "high"),
    ("sys", "core/app properties for selected values; otherwise no counterpart", "evaluate"),
    ("target", "DOCX export target metadata only", "approximate"),
    ("plugin invocation", "materialized result plus embedded source", "evaluate"),
]
for typst, docx, fidelity in _foundation_function_rows:
    _add(
        "Foundations / functions",
        typst,
        "function/type family",
        docx,
        "multiple parts or no persistent part",
        fidelity,
        "none",
        "partial" if fidelity in {"high", "approximate", "evaluate"} else "none",
        "none",
        "Computational definitions do not survive as executable programs in DOCX. Static results are converted and the original source is available through exact-roundtrip embedding.",
    )

_model_inventory_rows = [
    ("asset", "OPC part plus relationship and content type", "high", "high", "full", "full"),
    ("title", "core title property and Title paragraph style", "high", "high", "full", "full"),
    ("bullet-list", "w:numPr bullet numbering", "high", "high", "full", "full"),
    ("numbered-list", "w:numPr numeric numbering", "high", "high", "full", "full"),
    ("paragraph-break", "w:p boundary", "exact", "exact", "full", "full"),
    ("reference", "REF/PAGEREF/NOTEREF field or hyperlink", "high", "high", "full", "full"),
    ("strong-emphasis", "w:b", "exact", "exact", "full", "full"),
    ("emphasis", "w:i", "exact", "exact", "full", "full"),
    ("term-list", "definition-style paragraphs or two-column table", "approximate", "approximate", "full", "partial"),
]
for typst, docx, t2d, d2t, it2d, id2t in _model_inventory_rows:
    _add(
        "Document model / reference inventory",
        typst,
        "element",
        docx,
        "word/document.xml and related parts",
        t2d,
        d2t,
        it2d,
        id2t,
        "This row uses the canonical name shown in the Typst 0.15.1 reference; related syntax and detailed properties are mapped elsewhere in the matrix.",
    )

_text_function_rows = [
    ("lorem", "materialized generated text", "evaluate", "none", "partial", "none"),
    ("lower", "materialized lowercase text", "high", "approximate", "full", "partial"),
    ("upper", "materialized uppercase text or w:caps", "high", "approximate", "full", "partial"),
    ("raw", "Code style run/paragraph with literal text", "high", "high", "full", "full"),
    ("smartquote", "literal typographic quote characters", "high", "approximate", "partial", "partial"),
]
for typst, docx, t2d, d2t, it2d, id2t in _text_function_rows:
    _add("Text / reference inventory", typst, "element/function", docx, "word/document.xml", t2d, d2t, it2d, id2t,
         "Word stores characters and run properties, not Typst's text-producing function call.")

_math_inventory_rows = [
    ("cancel", "m:borderBox strikeH/strikeTLBR/strikeBLTR", "high", "high", "partial", "partial"),
    ("math.class", "OMML spacing class inferred from operator/run context", "approximate", "none", "partial", "none"),
    ("primes", "m:sSup or literal prime run", "high", "high", "full", "full"),
    ("math.size", "m:argSz and run size", "approximate", "approximate", "partial", "partial"),
    ("math.stretch", "m:d/m:nary growth and DrawingML sizing", "approximate", "approximate", "partial", "partial"),
    ("math.style", "m:sty, m:scr, m:nor, and run properties", "high", "high", "partial", "partial"),
    ("math.variant", "m:sty/m:scr and Unicode mathematical alphabets", "approximate", "approximate", "partial", "partial"),
]
for typst, docx, t2d, d2t, it2d, id2t in _math_inventory_rows:
    _add("Mathematics / reference inventory", typst, "math function", docx, "word/document.xml (OMML)", t2d, d2t, it2d, id2t,
         "OMML and Typst math have different spacing and font-class models; unknown nodes are retained as raw OMML.")

_symbol_rows = [
    ("sym general symbols", "Unicode text, symbol-font run, or DrawingML fallback", "high", "high", "full", "full"),
    ("emoji", "Unicode emoji run, color-font glyph, or image fallback", "high", "high", "full", "full"),
]
for typst, docx, t2d, d2t, it2d, id2t in _symbol_rows:
    _add("Symbols", typst, "module/value", docx, "word/document.xml + fonts/media", t2d, d2t, it2d, id2t,
         "Actual appearance depends on installed fonts and the Word/Typst shaping engines.")

_layout_inventory_rows = [
    ("alignment", "w:jc, table alignment, anchor alignment", "high", "high"),
    ("angle", "DrawingML rotation in 1/60000 degree units", "high", "high"),
    ("direction", "w:bidi, w:rtl, w:textDirection", "high", "high"),
    ("fraction (layout)", "table/grid width fractions after resolution", "evaluate", "none"),
    ("length", "twips, EMUs, half-points, percentages", "high", "high"),
    ("ratio", "percentage or resolved dimension", "high", "approximate"),
    ("relative length", "resolved length or percentage", "approximate", "approximate"),
    ("h spacing", "tabs, run spacing, indents, or literal spacing", "approximate", "approximate"),
    ("v spacing", "paragraph before/after spacing or empty paragraph", "approximate", "approximate"),
    ("padding", "cell margins, paragraph indents, or text-box margins", "approximate", "approximate"),
]
for typst, docx, t2d, d2t in _layout_inventory_rows:
    _add("Layout / reference inventory", typst, "value/element", docx, "word/document.xml", t2d, d2t,
         "partial" if t2d in {"approximate", "evaluate"} else "full",
         "partial" if d2t == "approximate" else "none" if d2t == "none" else "full",
         "Dimensions can be stored in multiple OOXML unit systems; relative layout may require resolving against a page, column, cell, or drawing frame.")

_export_inventory_rows = [
    ("pdf.data-cell", "table-cell semantics and accessibility metadata", "approximate"),
    ("pdf.header-cell", "w:tblHeader plus cell semantics", "high"),
    ("pdf.table-summary", "w:tblDescription / accessibility metadata", "high"),
    ("html.elem", "native Word content or altChunk HTML", "approximate"),
    ("html.typed", "native Word content or custom XML/altChunk", "approximate"),
    ("png export", "no source-level DOCX control; raster image when embedded", "none"),
    ("svg export", "no source-level DOCX control; SVG image when embedded", "none"),
]
for typst, docx, fidelity in _export_inventory_rows:
    _add("Export / reference inventory", typst, "export element/configuration", docx, "package-specific", fidelity, "none",
         "partial" if fidelity in {"high", "approximate"} else "none", "none",
         "Export-only behavior is not part of WordprocessingML's document semantics and is retained in the original Typst source.")

# DOCX constructs with no clean Typst counterpart.
_docx_only = [
    ("OPC package parts and relationships", "project files/assets and exact payload", "preserve", "full"),
    ("[Content_Types].xml", "asset MIME/type knowledge", "preserve", "full"),
    ("core properties", "document metadata", "high", "full"),
    ("extended properties", "document/app metadata", "approximate", "full"),
    ("custom properties", "metadata dictionary", "high", "full"),
    ("styles.xml paragraph styles", "set/show rules or direct properties", "high", "full"),
    ("styles.xml character styles", "text wrappers", "high", "full"),
    ("table styles", "table styling/show rules", "approximate", "partial"),
    ("latent styles and style gallery metadata", "no visible counterpart", "preserve", "preserve"),
    ("theme colors and fonts", "explicit colors/fonts", "approximate", "partial"),
    ("font table", "font names", "high", "full"),
    ("numbering abstractNum/num/lvl", "list/enum", "high", "full"),
    ("picture bullets", "image marker", "approximate", "partial"),
    ("section break types continuous/next/even/odd", "page/column/section wrapper", "approximate", "partial"),
    ("different first/odd/even headers and footers", "conditional page header/footer", "high", "full"),
    ("page borders", "page background/foreground drawing", "approximate", "preserve"),
    ("line numbering", "no native general counterpart", "approximate", "full"),
    ("document grid / East Asian layout grid", "layout settings", "approximate", "preserve"),
    ("paragraph borders and shading", "block fill/stroke", "high", "full"),
    ("paragraph tabs", "par tabs", "high", "full"),
    ("drop caps / framePr", "placed large initial", "approximate", "preserve"),
    ("run emboss/imprint/outline/shadow", "text effects", "approximate", "full"),
    ("WordArt / text effects", "vector text/image", "approximate", "preserve"),
    ("proofing language/noProof", "text language / raw metadata", "high", "full"),
    ("soft hyphen/no-break hyphen", "Unicode/special spacing", "high", "full"),
    ("simple fields w:fldSimple", "Typst counter/ref/date/link or typx_field", "high", "full"),
    ("complex fields fldChar/instrText", "Typst counter/ref/date/link or typx_field", "high", "full"),
    ("form fields", "content control/raw wrapper", "approximate", "partial"),
    ("bookmarks", "labels", "high", "full"),
    ("permissions ranges", "no direct counterpart", "preserve", "preserve"),
    ("document protection", "no direct counterpart", "preserve", "preserve"),
    ("tracked insertions/deletions", "typx_change visible wrapper", "high", "full"),
    ("tracked moves", "typx_change/raw revision", "approximate", "full"),
    ("property-change revisions", "raw OOXML", "preserve", "preserve"),
    ("comments", "typx comment anchors and appendix", "high", "full"),
    ("threaded comments / replies / resolved state", "comment metadata/raw", "approximate", "partial"),
    ("footnotes", "footnote", "exact", "full"),
    ("endnotes", "raw/typx wrapper", "approximate", "full"),
    ("content controls rich/plain text", "typx_sdt wrapper", "high", "full"),
    ("checkbox/date/dropdown/combo/picture content controls", "typx_sdt wrapper", "approximate", "full"),
    ("repeating-section content controls", "typx_sdt/raw", "preserve", "full"),
    ("data-bound content controls", "typx_sdt data binding metadata", "preserve", "full"),
    ("custom XML parts", "raw payload or source asset", "preserve", "preserve"),
    ("smart tags", "raw inline wrapper", "preserve", "preserve"),
    ("altChunk HTML/RTF/MHTML", "raw block with fallback", "preserve", "full"),
    ("DrawingML inline pictures", "image", "high", "full"),
    ("floating drawings and text wrapping", "place/image", "approximate", "full"),
    ("VML legacy drawings", "image/raw OOXML", "preserve", "full"),
    ("shapes and text boxes", "shape/image/block", "approximate", "partial"),
    ("grouped drawings", "image/raw", "preserve", "preserve"),
    ("charts", "rendered image plus raw chart parts", "preserve", "preserve"),
    ("SmartArt diagrams", "rendered image plus raw diagram parts", "preserve", "preserve"),
    ("embedded OLE objects", "attachment/link/raw", "preserve", "preserve"),
    ("embedded packages", "asset/raw", "preserve", "preserve"),
    ("macros in DOCM", "no `.docx` counterpart", "none", "none"),
    ("OMML equations", "Typst math", "high", "full"),
    ("mail merge settings/data source", "no direct counterpart", "preserve", "preserve"),
    ("bibliography sources", "bibliography/cite", "approximate", "partial"),
    ("glossary document/building blocks", "include/template source", "preserve", "preserve"),
    ("document variables", "metadata/state", "approximate", "partial"),
    ("web settings", "no direct counterpart", "preserve", "preserve"),
    ("printer settings", "no direct counterpart", "preserve", "preserve"),
    ("embedded fonts/font obfuscation", "font reference only", "preserve", "preserve"),
    ("digital signatures", "no semantic counterpart", "none", "none"),
    ("IRM/encryption", "outside unencrypted DOCX model", "none", "none"),
    ("MCE AlternateContent", "selected fallback plus raw OOXML", "preserve", "full"),
    ("Word 2010–2026 w14/w15/w16 extensions", "native approximation plus raw OOXML", "preserve", "full"),
    ("accessibility image descriptions", "image alt text", "high", "full"),
    ("table captions/descriptions", "figure/table caption metadata", "high", "full"),
    ("w:pPr/w:spacing before/after/line/lineRule", "par spacing/leading", "high", "full"),
    ("w:pPr/w:ind left/right/firstLine/hanging/start/end", "par indents", "high", "full"),
    ("w:pPr/w:jc and w:jc/@w:val variants", "par alignment", "high", "full"),
    ("w:pPr/w:keepNext, w:keepLines, w:pageBreakBefore", "par keep/pagebreak behavior", "high", "full"),
    ("w:pPr/w:widowControl and contextualSpacing", "par widow/orphan and spacing behavior", "approximate", "full"),
    ("w:pPr/w:outlineLvl", "heading outline level", "high", "full"),
    ("w:pPr/w:bidi and w:textDirection", "text/par direction", "high", "full"),
    ("w:pPr mirrorIndents/suppressLineNumbers", "par mirror/line-number settings", "high", "full"),
    ("w:pPr kinsoku/wordWrap/overflowPunct", "East Asian line-breaking settings", "approximate", "preserve"),
    ("w:pPr autoSpaceDE/autoSpaceDN/adjustRightInd", "script-aware spacing settings", "approximate", "preserve"),
    ("w:pPr snapToGrid/textAlignment/textboxTightWrap", "layout hints", "approximate", "preserve"),
    ("w:rPr/w:rFonts ascii/hAnsi/eastAsia/cs/theme", "text font selection", "high", "full"),
    ("w:rPr bold/italic/underline/strike/dstrike", "strong/emph/underline/strike", "exact", "full"),
    ("w:rPr caps/smallCaps/vanish", "uppercase/smallcaps/hide", "high", "full"),
    ("w:rPr vertAlign/position", "super/sub/baseline", "high", "full"),
    ("w:rPr color/highlight/shading", "text fill/highlight", "high", "full"),
    ("w:rPr sz/szCs/spacing/w", "text size/tracking/stretch", "high", "full"),
    ("w:rPr lang/rtl/cs/noProof", "language/direction/proofing", "high", "full"),
    ("w:rPr emboss/imprint/outline/shadow", "text effects", "approximate", "full"),
    ("w:rPr kern/fitText/snapToGrid", "kerning/fitted run/layout hint", "approximate", "preserve"),
    ("w:rPr eastAsianLayout/specVanish/webHidden", "script/layout/visibility metadata", "preserve", "preserve"),
    ("w:tblPr/w:tblW, w:jc, w:tblLayout", "table width/alignment/layout", "high", "full"),
    ("w:tblBorders and w:tcBorders", "table/cell strokes", "high", "full"),
    ("w:tblCellMar and w:tcMar", "table/cell padding", "high", "full"),
    ("w:tblStyle and w:tblLook", "table show-rule/style metadata", "approximate", "partial"),
    ("w:bidiVisual", "right-to-left table order", "high", "full"),
    ("w:tblCaption and w:tblDescription", "table caption/description", "high", "full"),
    ("w:trPr/w:tblHeader, cantSplit, trHeight", "header row/splitting/height", "high", "full"),
    ("w:tcPr/w:gridSpan and w:vMerge", "table cell colspan/rowspan", "high", "full"),
    ("w:tcPr/w:tcW, shd, vAlign, textDirection", "cell width/fill/alignment/direction", "high", "full"),
    ("w:tblPrEx and conditional table formatting", "resolved table styling", "approximate", "preserve"),
    ("table row/cell insertion/deletion revisions", "typx_change/raw table revision", "preserve", "preserve"),
    ("w:sectPr/w:pgSz and w:pgMar", "page size/orientation/margins/gutter", "high", "full"),
    ("w:sectPr/w:cols including unequal columns", "page columns", "high", "full"),
    ("w:sectPr/w:pgNumType", "page-number start/format", "high", "full"),
    ("w:sectPr headerReference/footerReference", "page headers/footers", "high", "full"),
    ("w:sectPr titlePg/evenAndOddHeaders", "first/even/odd page variants", "high", "full"),
    ("w:sectPr/w:lnNumType", "line numbering", "approximate", "full"),
    ("w:sectPr/w:vAlign", "vertical page alignment", "approximate", "full"),
    ("w:sectPr/w:footnotePr and w:endnotePr", "note placement/numbering metadata", "approximate", "preserve"),
    ("w:sectPr/w:paperSrc", "printer paper source", "preserve", "preserve"),
    ("w:settings/w:updateFields", "field update hint", "high", "full"),
    ("w:settings/w:defaultTabStop", "default tab width", "high", "full"),
    ("w:settings/w:trackRevisions and revision view", "revision-preservation policy", "high", "full"),
    ("w:settings compatibility settings", "converter compatibility metadata", "preserve", "preserve"),
    ("w:settings autoHyphenation/consecutiveHyphenLimit", "hyphenation policy", "approximate", "preserve"),
    ("w:settings zoom/view/displayBackgroundShape", "application view settings", "preserve", "preserve"),
    ("w:settings themeFontLang/decimalSymbol/listSeparator", "locale and theme metadata", "approximate", "preserve"),
    ("w:settings rsids and session identifiers", "no semantic counterpart", "preserve", "preserve"),
    ("wp:inline and wp:anchor", "inline/floating image or placed content", "high", "full"),
    ("wp:extent/effectExtent/docPr", "image extent/effects/alt text/title", "high", "full"),
    ("wp:wrapNone/wrapSquare/wrapTight/wrapThrough/wrapTopAndBottom", "image wrapping", "approximate", "full"),
    ("wp:positionH/positionV/simplePos", "place alignment and offsets", "approximate", "full"),
    ("wp:anchor relativeHeight/behindDoc/layoutInCell/locked/allowOverlap", "floating placement metadata", "approximate", "full"),
    ("a:blip/a:srcRect/a:xfrm/a:ext", "image source/crop/transform/extent", "high", "full"),
    ("a:prstGeom/a:custGeom/a:ln/fill", "Typst shape geometry/stroke/fill", "approximate", "preserve"),
    ("commentsExtended.xml/commentsExtensible.xml/commentsIds.xml", "comment threading/resolution metadata", "approximate", "partial"),
    ("people.xml author identities", "comment/revision author metadata", "approximate", "partial"),
    ("stylesWithEffects.xml", "text/paragraph style effects", "preserve", "preserve"),
    ("bibliography.xml source records", "bibliography/citation keys and metadata", "approximate", "partial"),
    ("ink/inkML parts", "image or raw drawing payload", "preserve", "preserve"),
    ("ActiveX controls and control properties", "raw embedded object/content-control fallback", "preserve", "preserve"),
    ("customUI/ribbon parts", "no document-semantic counterpart", "none", "none"),
    ("document conformance strict/transitional", "converter mode/package metadata", "approximate", "partial"),
]
for docx, typst, fidelity, impl in _docx_only:
    _add("DOCX-specific", typst, "closest Typst representation", docx, "multiple OOXML parts", "none" if fidelity == "none" else fidelity,
         fidelity, "none" if fidelity == "none" else "partial", impl,
         "Unsupported Word extensions are retained as compressed raw OOXML when possible; exact package recovery is available for untouched generated counterparts.")

MAPPING: tuple[MappingEntry, ...] = tuple(_entries)


def as_json(indent: int = 2) -> str:
    payload = {
        "schema": "typx-mapping-v1",
        "typst_baseline": TYPST_BASELINE,
        "ooxml_baseline": OOXML_BASELINE,
        "entry_count": len(MAPPING),
        "fidelity_legend": {
            "exact": "Direct structural or semantic counterpart",
            "high": "Generally equivalent with bounded property loss",
            "approximate": "Visible or semantic approximation",
            "preserve": "Retained as raw counterpart data, not natively transformed",
            "evaluate": "Requires a Typst or Word evaluation/layout engine",
            "none": "No counterpart",
        },
        "implementation_legend": {
            "full": "Implemented natively in this release",
            "partial": "Implemented for the common/static subset",
            "preserve": "Retained through raw or exact-roundtrip payloads",
            "none": "Not transformed",
        },
        "sources": SOURCES,
        "entries": [asdict(entry) for entry in MAPPING],
    }
    return json.dumps(payload, ensure_ascii=False, indent=indent) + "\n"


def as_csv() -> str:
    stream = io.StringIO(newline="")
    fieldnames = list(MappingEntry.__dataclass_fields__)
    writer = csv.DictWriter(stream, fieldnames=fieldnames)
    writer.writeheader()
    for entry in MAPPING:
        writer.writerow(asdict(entry))
    return stream.getvalue()


def as_markdown() -> str:
    lines = [
        "# Typst ↔ DOCX mapping",
        "",
        f"**Typst baseline:** {TYPST_BASELINE}  ",
        f"**DOCX/OOXML baseline:** {OOXML_BASELINE}  ",
        f"**Rows:** {len(MAPPING)}",
        "",
        "This is a semantic and implementation mapping, not a claim that the two formats have identical layout engines. Typst is a programmable typesetting language; DOCX is an OPC package whose main document is a declarative WordprocessingML tree. Arbitrary Typst code therefore needs evaluation, while many application-specific Word extensions need preservation rather than translation.",
        "",
        "## Fidelity legend",
        "",
        "| Value | Meaning |",
        "|---|---|",
        "| exact | Direct structural or semantic counterpart |",
        "| high | Generally equivalent with bounded property loss |",
        "| approximate | Visible or semantic approximation |",
        "| preserve | Raw counterpart data is retained, but not natively transformed |",
        "| evaluate | Requires the Typst or Word evaluation/layout engine |",
        "| none | No counterpart |",
        "",
        "## Implementation legend",
        "",
        "| Value | Meaning |",
        "|---|---|",
        "| full | Natively implemented in this release |",
        "| partial | Implemented for a common/static subset |",
        "| preserve | Retained through raw or exact-roundtrip payloads |",
        "| none | Not transformed |",
        "",
        "## Matrix",
        "",
        "| ID | Category | Typst construct | DOCX counterpart | Typst→DOCX | DOCX→Typst | Impl T→D | Impl D→T | Notes |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for entry in MAPPING:
        def esc(value: str) -> str:
            return value.replace("|", "\\|").replace("\n", " ")
        lines.append("| " + " | ".join(map(esc, [
            entry.id, entry.category, f"`{entry.typst}` ({entry.typst_kind})",
            f"`{entry.docx}` in `{entry.docx_part}`", entry.typst_to_docx,
            entry.docx_to_typst, entry.implementation_t2d, entry.implementation_d2t,
            entry.notes,
        ])) + " |")
    lines.extend(["", "## Primary references", ""])
    for source in SOURCES:
        lines.append(f"- [{source['title']}]({source['url']}) – {source['scope']}")
    lines.extend([
        "",
        "## Round-trip policy",
        "",
        "1. Native counterparts are converted through the shared document model.",
        "2. Unsupported OOXML nodes are stored as compressed raw XML wrappers with a visible fallback.",
        "3. DOCX→Typst can embed the original DOCX in a leading comment. If the generated Typst body is unchanged, Typst→DOCX restores the exact original bytes.",
        "4. Typst→DOCX embeds the original Typst source in a custom XML part with a semantic package digest. If the generated DOCX remains semantically unchanged, DOCX→Typst restores the exact source.",
        "5. When either counterpart was edited, conversion falls back to semantic reconstruction while retaining raw fragments whenever structurally safe.",
        "",
    ])
    return "\n".join(lines)


__all__ = ["MappingEntry", "MAPPING", "SOURCES", "as_json", "as_csv", "as_markdown"]
