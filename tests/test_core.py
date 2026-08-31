from __future__ import annotations

import hashlib
import io
import zipfile
import xml.etree.ElementTree as ET
import struct
import tempfile
import unittest
from unittest.mock import patch
import zlib
from pathlib import Path

from typx.cli import main
from typx.docx_package import DocxPackage
from typx.docx_reader import DocxReadOptions, DocxReader
from typx.docx_writer import DocxWriteOptions, DocxWriter
from typx.mapping import MAPPING, as_csv, as_json, as_markdown
from typx.omml import omml_to_typst, typst_math_to_omml
from typx.model import (
    Border,
    Bookmark,
    Break,
    BreakBlock,
    Change,
    Citation,
    CodeBlock,
    Comment,
    CommentAnchor,
    ContentControl,
    Divider,
    Document,
    Field,
    Figure,
    Heading,
    ImageInline,
    Link,
    ListBlock,
    ListItem,
    MathBlock,
    MathInline,
    NoteRef,
    Paragraph,
    ParagraphStyle,
    Quote,
    RawInline,
    Reference,
    Resource,
    SectionProperties,
    StyleDefinition,
    Table,
    TableCell,
    TableRow,
    Text,
    TextStyle,
)
from typx.roundtrip import (
    embed_docx_in_typst,
    extract_docx_from_typst,
    extract_typst_from_docx,
)
from typx.typst_reader import TypstReadOptions, TypstReader
from typx.typst_writer import TypstWriteOptions, TypstWriter


def png_bytes(width: int = 4, height: int = 3) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    raw = b"".join(b"\x00" + bytes([40, 110, 190]) * width for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )



def fake_font_bytes(family: str = "Synthetic Font") -> bytes:
    encoded = family.encode("utf-16-be")
    # Minimal sfnt containing only a name table. It is sufficient for typx's
    # font-family resolver tests; it is not intended to be rendered.
    name_table = (
        struct.pack(">HHH", 0, 1, 18)
        + struct.pack(">HHHHHH", 3, 1, 0x0409, 1, len(encoded), 0)
        + encoded
    )
    table_offset = 12 + 16
    return (
        b"\x00\x01\x00\x00"
        + struct.pack(">HHHH", 1, 0, 0, 0)
        + b"name" + struct.pack(">III", 0, table_offset, len(name_table))
        + name_table
    )


def add_word_bibliography(docx: bytes) -> bytes:
    bibliography = b"""<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<b:Sources xmlns:b="http://schemas.openxmlformats.org/officeDocument/2006/bibliography" SelectedStyle="\\APA.XSL" StyleName="APA">
  <b:Source>
    <b:Tag>Smith2024</b:Tag><b:SourceType>JournalArticle</b:SourceType>
    <b:Author><b:Author><b:NameList><b:Person><b:Last>Smith</b:Last><b:First>Alex</b:First></b:Person></b:NameList></b:Author></b:Author>
    <b:Title>Reliable conversion systems</b:Title><b:JournalName>Interop Quarterly</b:JournalName>
    <b:Year>2024</b:Year><b:Volume>8</b:Volume><b:Issue>2</b:Issue><b:Pages>14-29</b:Pages>
  </b:Source>
  <b:Source>
    <b:Tag>Jones2025</b:Tag><b:SourceType>Book</b:SourceType>
    <b:Author><b:Author><b:NameList><b:Person><b:Last>Jones</b:Last><b:First>Riley</b:First></b:Person></b:NameList></b:Author></b:Author>
    <b:Title>Document Interchange</b:Title><b:Publisher>Example Press</b:Publisher><b:Year>2025</b:Year>
  </b:Source>
</b:Sources>"""
    source = io.BytesIO(docx)
    output = io.BytesIO()
    with zipfile.ZipFile(source, "r") as archive, zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as target:
        for info in archive.infolist():
            target.writestr(info, archive.read(info.filename))
        target.writestr("customXml/itemBibliography.xml", bibliography)
    return output.getvalue()


def strictify_docx(data: bytes) -> bytes:
    replacements = {
        b"http://schemas.openxmlformats.org/wordprocessingml/2006/main": b"http://purl.oclc.org/ooxml/wordprocessingml/main",
        b"http://schemas.openxmlformats.org/officeDocument/2006/relationships": b"http://purl.oclc.org/ooxml/officeDocument/relationships",
        b"http://schemas.openxmlformats.org/package/2006/relationships": b"http://purl.oclc.org/ooxml/package/relationships",
        b"http://schemas.openxmlformats.org/package/2006/content-types": b"http://purl.oclc.org/ooxml/package/content-types",
        b"http://schemas.openxmlformats.org/drawingml/2006/main": b"http://purl.oclc.org/ooxml/drawingml/main",
        b"http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing": b"http://purl.oclc.org/ooxml/drawingml/wordprocessingDrawing",
        b"http://schemas.openxmlformats.org/drawingml/2006/picture": b"http://purl.oclc.org/ooxml/drawingml/picture",
        b"http://schemas.openxmlformats.org/officeDocument/2006/math": b"http://purl.oclc.org/ooxml/officeDocument/math",
        b"http://schemas.openxmlformats.org/package/2006/metadata/core-properties": b"http://purl.oclc.org/ooxml/package/metadata/core-properties",
        b"http://schemas.openxmlformats.org/officeDocument/2006/extended-properties": b"http://purl.oclc.org/ooxml/officeDocument/extended-properties",
        b"http://schemas.openxmlformats.org/officeDocument/2006/custom-properties": b"http://purl.oclc.org/ooxml/officeDocument/custom-properties",
        b"http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes": b"http://purl.oclc.org/ooxml/officeDocument/docPropsVTypes",
    }
    source = io.BytesIO(data)
    output = io.BytesIO()
    with zipfile.ZipFile(source, "r") as archive, zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as target:
        for info in archive.infolist():
            payload = archive.read(info.filename)
            if info.filename.endswith((".xml", ".rels")) or info.filename == "[Content_Types].xml":
                for old, new in replacements.items():
                    payload = payload.replace(old, new)
            target.writestr(info.filename, payload)
    return output.getvalue()

def broad_document() -> Document:
    image = png_bytes()
    resource = Resource(
        id="image-1",
        filename="sample.png",
        media_type="image/png",
        data=image,
        width_pt=96,
        height_pt=72,
        alt_text="A tiny generated test image",
        title="Generated image",
        checksum=hashlib.sha256(image).hexdigest(),
    )
    section = SectionProperties(
        page_width_pt=595.276,
        page_height_pt=841.89,
        margin_top_pt=54,
        margin_bottom_pt=54,
        margin_left_pt=63,
        margin_right_pt=63,
        columns=1,
        page_number_start=3,
        page_number_format="decimal",
        title_page=True,
        different_odd_even=True,
        line_numbering={"count_by": 5, "start": 1, "restart": "newPage"},
        header_default=[Paragraph([Text("Default header")])],
        header_first=[Paragraph([Text("First-page header")])],
        header_even=[Paragraph([Text("Even-page header")])],
        footer_default=[Paragraph([Field("PAGE", [Text("3")])])],
        footer_first=[Paragraph([Text("First-page footer")])],
        footer_even=[Paragraph([Text("Even-page footer")])],
    )
    paragraph_style = ParagraphStyle(
        align="justify",
        left_indent_pt=12,
        right_indent_pt=8,
        first_line_indent_pt=18,
        space_before_pt=6,
        space_after_pt=8,
        line_spacing=1.2,
        line_spacing_rule="auto",
        keep_next=True,
        keep_lines=True,
        widow_control=True,
        shading="FFF7CC",
        borders={"bottom": Border(style="single", width_pt=1, color="4472C4")},
    )
    styled = [
        Bookmark("intro"),
        Text("Bold", TextStyle(bold=True, font="Aptos", size_pt=12, color="C00000")),
        Text(" and "),
        Text("italic", TextStyle(italic=True)),
        Text(", "),
        Text("underlined", TextStyle(underline="single")),
        Text(", "),
        Text("highlighted", TextStyle(highlight="FFF200")),
        Text(", "),
        Text("struck", TextStyle(strike=True)),
        Text(", "),
        Text("small caps", TextStyle(small_caps=True)),
        Text(", H"),
        Text("2", TextStyle(subscript=True)),
        Text("O and x"),
        Text("2", TextStyle(superscript=True)),
        Text(". "),
        Link("https://typst.app", [Text("External link")], tooltip="Typst"),
        Text("; "),
        Link("intro", [Text("internal link")], anchor=True),
        Text("; "),
        MathInline("frac(1, 2) + sqrt(x)"),
        Text("; "),
        NoteRef("footnote", "fn1", [Paragraph([Text("Footnote body with "), Text("style", TextStyle(italic=True))])]),
        Text("; "),
        NoteRef("endnote", "en1", [Paragraph([Text("Endnote body")])]),
        Text("; field "),
        Field("DATE \\@ \"yyyy-MM-dd\"", [Text("2026-08-26")], dirty=True),
        Text("; citation "),
        Citation(["knuth1984"], supplement="p. 10", fallback=[Text("[Knuth 1984]")]),
        Text("; "),
        CommentAnchor("c1", "start"),
        Text("commented text"),
        CommentAnchor("c1", "end"),
        CommentAnchor("c1", "reference"),
        Text("; "),
        Change("insert", [Text("inserted")], author="Reviewer", date="2026-08-26T12:00:00Z", change_id="7"),
        Text(" / "),
        Change("delete", [Text("deleted")], author="Reviewer", date="2026-08-26T12:01:00Z", change_id="8"),
        Break("line"),
        Text("After a line break."),
    ]
    nested = ListBlock(
        False,
        [
            ListItem([Paragraph([Text("Nested bullet")])]),
            ListItem([Paragraph([Text("Checked item")])], checked=True),
        ],
        level=1,
        marker="–",
    )
    ordered = ListBlock(
        True,
        [
            ListItem([Paragraph([Text("First numbered item")]), nested]),
            ListItem([Paragraph([Text("Second numbered item")])]),
        ],
        start=4,
        number_format="upperRoman",
    )
    table = Table(
        rows=[
            TableRow(
                [
                    TableCell([Paragraph([Text("Merged header")])], colspan=2, header=True, shading="D9EAF7"),
                    TableCell([Paragraph([Text("Header C")])], header=True, shading="D9EAF7"),
                ],
                header=True,
                cant_split=True,
            ),
            TableRow([
                TableCell([Paragraph([Text("Row-spanning cell")])], rowspan=2, vertical_align="center"),
                TableCell([Paragraph([Text("B2")])]),
                TableCell([Paragraph([Text("C2")])]),
            ]),
            TableRow([
                TableCell([Paragraph([Text("B3")])]),
                TableCell([Paragraph([Text("C3")])]),
            ]),
        ],
        column_widths_pt=[120, 120, 120],
        align="center",
        width_pt=360,
        layout="fixed",
        caption="Coverage table",
        description="Merged cells and formatting",
        borders={name: Border(width_pt=0.75, color="808080") for name in ("top", "bottom", "left", "right", "insideH", "insideV")},
    )
    figure = Figure(
        body=[Paragraph([ImageInline("image-1", width_pt=144, height_pt=108, alt_text=resource.alt_text)])],
        caption=[Text("Generated image caption")],
        kind_name="figure",
        label="fig-sample",
        numbering="1",
        placement="top",
        align="center",
    )
    doc = Document(
        metadata={
            "title": "typx broad coverage fixture",
            "subject": "Bidirectional conversion test",
            "author": "Alek Rutkowski",
            "keywords": "Typst, DOCX, OOXML",
            "description": "A generated test document",
            "category": "Testing",
            "language": "en-US",
        },
        custom_properties={"Build": 1, "Passed": True, "Ratio": 1.25},
        sections=[section],
        resources={resource.id: resource},
        comments={
            "c1": Comment(
                "c1",
                author="Reviewer",
                initials="RV",
                date="2026-08-26T12:02:00Z",
                blocks=[Paragraph([Text("A Word comment")])],
                done=False,
            )
        },
        blocks=[
            Heading(1, [Text("Broad coverage")], numbering="1.", label="intro"),
            Paragraph(styled, paragraph_style),
            ordered,
            table,
            figure,
            Quote([Paragraph([Text("A block quotation")])], [Text("Attribution")]),
            CodeBlock("x = 1\nprint(x)\n", language="python"),
            MathBlock("sum_(i=1)^n i = frac(n(n+1), 2)", numbering="(1)", label="eq-sum"),
            Divider(1.25, "4472C4"),
            ContentControl(
                [Paragraph([Text("Content control body")])],
                tag="test-tag",
                alias="Test control",
                control_id="42",
                control_type="richText",
                lock="sdtContentLocked",
            ),
            BreakBlock("page"),
            Heading(2, [Text("Second page")], label="second"),
            Paragraph([Text("Final paragraph")]),
        ],
        source_format="typst",
        source_path="fixture.typ",
        source_text="= Broad coverage\n\nFixture source.\n",
    )
    return doc


class MappingTests(unittest.TestCase):
    def test_mapping_exports(self) -> None:
        self.assertGreaterEqual(len(MAPPING), 440)
        self.assertEqual(len({entry.id for entry in MAPPING}), len(MAPPING))
        self.assertIn('"entry_count":', as_json())
        self.assertTrue(as_csv().startswith("id,category,"))
        self.assertIn("## Matrix", as_markdown())


class MathTests(unittest.TestCase):
    def test_radical_and_nary_have_complete_omml_slots(self) -> None:
        radical = typst_math_to_omml("sqrt(x)")
        self.assertEqual(len(radical.findall(".//{http://schemas.openxmlformats.org/officeDocument/2006/math}deg")), 1)
        nary = typst_math_to_omml("sum_(i=1)^n i", display=True)
        ns = "{http://schemas.openxmlformats.org/officeDocument/2006/math}"
        nodes = nary.findall(f".//{ns}nary")
        self.assertEqual(len(nodes), 1)
        self.assertEqual("".join(nodes[0].find(f"{ns}sub").itertext()), "i=1")
        self.assertEqual("".join(nodes[0].find(f"{ns}sup").itertext()), "n")
        self.assertEqual("".join(nodes[0].find(f"{ns}e").itertext()), "i")


class DocxInteroperabilityTests(unittest.TestCase):
    def _bullet_document(self) -> Document:
        return Document(
            blocks=[
                ListBlock(
                    False,
                    [
                        ListItem([Paragraph([Text("First item")])]),
                        ListItem([Paragraph([Text("Second item")])]),
                    ],
                )
            ],
            source_format="typst",
            source_text="- First item\n- Second item\n",
        )

    def test_bullet_numbering_uses_schema_order_and_unicode_font(self) -> None:
        package = DocxPackage.open(
            DocxWriter(self._bullet_document(), DocxWriteOptions(embed_typst_source=False)).build()
        )
        root = ET.fromstring(package.parts["word/numbering.xml"])
        ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
        levels = root.findall(f".//{ns}lvl")
        self.assertEqual(len(levels), 9)
        for level in levels:
            names = [child.tag.removeprefix(ns) for child in level]
            self.assertEqual(names, ["start", "numFmt", "suff", "lvlText", "lvlJc", "pPr"])
            self.assertIsNone(level.find(f"{ns}rPr"))
            tabs = level.find(f"{ns}pPr/{ns}tabs/{ns}tab")
            self.assertIsNotNone(tabs)
            assert tabs is not None
            self.assertEqual(tabs.get(f"{ns}val"), "num")
        self.assertEqual(levels[0].find(f"{ns}lvlText").get(f"{ns}val"), "•")
        self.assertNotIn(b"Symbol", package.parts["word/numbering.xml"])

    def test_mixed_lists_keep_type_restart_and_typst_marker_alignment(self) -> None:
        source = """- Bullet one
- Bullet two

+ Number one
+ Number two

- Bullet three

+ Restart one
+ Restart two
"""
        document = TypstReader(source).parse()
        package = DocxPackage.open(DocxWriter(document, DocxWriteOptions(embed_typst_source=False)).build())
        ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
        numbering = ET.fromstring(package.parts["word/numbering.xml"])
        abstracts = numbering.findall(f"{ns}abstractNum")
        self.assertEqual([a.find(f"{ns}lvl/{ns}numFmt").get(f"{ns}val") for a in abstracts],
                         ["bullet", "decimal", "bullet", "decimal"])
        for abstract in abstracts:
            ind = abstract.find(f"{ns}lvl/{ns}pPr/{ns}ind")
            assert ind is not None
            self.assertEqual(ind.get(f"{ns}left"), "280")
            self.assertEqual(ind.get(f"{ns}hanging"), "280")
        nums = numbering.findall(f"{ns}num")
        ordered_overrides = [num.find(f"{ns}lvlOverride/{ns}startOverride") for num in nums]
        self.assertIsNone(ordered_overrides[0])
        self.assertEqual(ordered_overrides[1].get(f"{ns}val"), "1")
        self.assertIsNone(ordered_overrides[2])
        self.assertEqual(ordered_overrides[3].get(f"{ns}val"), "1")
        styles = ET.fromstring(package.parts["word/styles.xml"])
        list_style = next(s for s in styles.findall(f"{ns}style") if s.get(f"{ns}styleId") == "ListParagraph")
        self.assertIsNone(list_style.find(f"{ns}pPr/{ns}ind"))

    def test_typst_checkbox_like_list_text_stays_literal(self) -> None:
        source = """- [x] Completed text
- [ ] Pending text
"""
        document = TypstReader(source).parse()
        block = next(block for block in document.blocks if isinstance(block, ListBlock))
        self.assertEqual([item.checked for item in block.items], [None, None])
        visible = []
        for item in block.items:
            paragraph = item.blocks[0]
            self.assertIsInstance(paragraph, Paragraph)
            visible.append("".join(inline.text for inline in paragraph.inlines if isinstance(inline, Text)))
        self.assertEqual(visible, ["[x] Completed text", "[ ] Pending text"])

    def test_typst_table_rowspan_reserves_prior_columns(self) -> None:
        source = r'''#table(
  columns: 5,
  [Service], [P50], [P95], [P99], [SLO],
  table.cell(rowspan: 2, fill: rgb("#FADBD8"))[API], [620], [910], [1250], [99.9%],
  [640], [940], [1310], [99.9%],
  table.cell(rowspan: 2, fill: rgb("#FADBD8"))[Worker], [42], [65], [88], [99.5%],
  [44], [68], [91], [99.5%],
)
'''
        document = TypstReader(source).parse()
        table = next(block for block in document.blocks if isinstance(block, Table))
        def cell_text(cell: TableCell) -> str:
            return "".join(
                inline.text
                for block in cell.blocks if isinstance(block, Paragraph)
                for inline in block.inlines if isinstance(inline, Text)
            )
        rows = [[cell_text(cell) for cell in row.cells] for row in table.rows]
        self.assertEqual(rows[1][0], "API")
        self.assertEqual(rows[2], ["640", "940", "1310", "99.9%"])
        self.assertEqual(rows[3][0], "Worker")
        self.assertEqual(rows[4], ["44", "68", "91", "99.5%"])

        package = DocxPackage.open(DocxWriter(document, DocxWriteOptions(embed_typst_source=False)).build())
        w = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
        root = ET.fromstring(package.parts["word/document.xml"])
        word_rows = root.findall(f".//{w}tbl/{w}tr")
        self.assertEqual(word_rows[2][0].find(f"{w}tcPr/{w}vMerge").get(f"{w}val"), "continue")
        worker_text = "".join(word_rows[3][0].itertext())
        self.assertIn("Worker", worker_text)

    def test_note_reference_styles_are_superscript(self) -> None:
        document = Document(
            blocks=[Paragraph([Text("Body"), NoteRef("footnote", "1", [Paragraph([Text("Note")])])])],
            source_format="typst",
        )
        package = DocxPackage.open(DocxWriter(document, DocxWriteOptions(embed_typst_source=False)).build())
        w = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
        styles = ET.fromstring(package.parts["word/styles.xml"])
        style = next(item for item in styles.findall(f"{w}style") if item.get(f"{w}styleId") == "FootnoteReference")
        self.assertEqual(style.find(f"{w}rPr/{w}vertAlign").get(f"{w}val"), "superscript")
        doc = ET.fromstring(package.parts["word/document.xml"])
        ref_run = next(run for run in doc.findall(f".//{w}r") if run.find(f"{w}footnoteReference") is not None)
        self.assertEqual(ref_run.find(f"{w}rPr/{w}rStyle").get(f"{w}val"), "FootnoteReference")
        notes = ET.fromstring(package.parts["word/footnotes.xml"])
        note_marker = next(run for run in notes.findall(f".//{w}r") if run.find(f"{w}footnoteRef") is not None)
        self.assertEqual(note_marker.find(f"{w}rPr/{w}rStyle").get(f"{w}val"), "FootnoteReference")

    def test_independent_list_definitions_have_unique_word_template_ids(self) -> None:
        document = TypstReader("- Bullet\n\n+ One\n\n#enum(numbering: \"I.\", [Roman])\n").parse()
        package = DocxPackage.open(DocxWriter(document, DocxWriteOptions(embed_typst_source=False)).build())
        w = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
        numbering = ET.fromstring(package.parts["word/numbering.xml"])
        abstracts = numbering.findall(f"{w}abstractNum")
        nsids = [item.find(f"{w}nsid").get(f"{w}val") for item in abstracts]
        templates = [item.find(f"{w}tmpl").get(f"{w}val") for item in abstracts]
        self.assertEqual(len(nsids), len(set(nsids)))
        self.assertEqual(nsids, templates)
        self.assertEqual([item.find(f"{w}lvl/{w}numFmt").get(f"{w}val") for item in abstracts],
                         ["bullet", "decimal", "upperRoman"])

    def test_width_only_svg_preserves_intrinsic_aspect_ratio(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "wide.svg").write_text(
                '<svg xmlns="http://www.w3.org/2000/svg" width="200" height="100" viewBox="0 0 200 100">'
                '<rect width="200" height="100" fill="#4472c4"/></svg>', encoding="utf-8")
            source_path = root / "fixture.typ"
            source_path.write_text('#image("wide.svg", width: 120pt)\n', encoding="utf-8")
            document = TypstReader.read(source_path)
            paragraph = next(block for block in document.blocks if isinstance(block, Paragraph))
            image = next(inline for inline in paragraph.inlines if isinstance(inline, ImageInline))
            self.assertAlmostEqual(image.width_pt or 0, 120.0, places=4)
            self.assertAlmostEqual(image.height_pt or 0, 60.0, places=4)

    def test_typst_cross_references_resolve_to_numbered_targets(self) -> None:
        source = r'''#set heading(numbering: "1.")
#set math.equation(numbering: "(1)")
= Reliability model <reliability>

#figure(rect(width: 20pt, height: 10pt), caption: [Flow]) <flow>

$ x = 1 $ <equation>

See @reliability, @flow, and @equation.
'''
        document = TypstReader(source).parse()
        refs = [inline for block in document.walk_blocks() if isinstance(block, Paragraph)
                for inline in block.inlines if isinstance(inline, Reference)]
        self.assertEqual([[child.text for child in ref.children if isinstance(child, Text)] for ref in refs],
                         [["Section 1"], ["Figure 1"], ["Equation (1)"]])
        package = DocxPackage.open(DocxWriter(document, DocxWriteOptions(embed_typst_source=False)).build())
        xml = package.parts["word/document.xml"].decode("utf-8")
        self.assertNotIn("@reliability", xml)
        self.assertIn("Section 1", xml)
        self.assertIn("Figure 1", xml)
        self.assertIn("Equation (1)", xml)
        self.assertIn('w:anchor="reliability"', xml)
        self.assertIn('w:anchor="flow"', xml)
        self.assertIn('w:anchor="equation"', xml)

    def test_page_numbering_emits_fields_and_roundtrips_semantically(self) -> None:
        source = '#set page(numbering: "1 of 1", number-align: bottom + right)\n\n= Report\n\n#pagebreak()\nSecond page.\n'
        document = TypstReader(source).parse()
        data = DocxWriter(document, DocxWriteOptions(embed_typst_source=False)).build()
        package = DocxPackage.open(data)
        footer_name = next(name for name in package.parts if name.startswith("word/footer") and name.endswith(".xml"))
        footer = package.parts[footer_name].decode("utf-8")
        self.assertIn(" PAGE ", footer)
        self.assertIn(" NUMPAGES ", footer)
        self.assertIn('w:val="right"', footer)
        read_back = DocxReader.read(data, DocxReadOptions())
        self.assertEqual(read_back.section.page_numbering, "1 of 1")
        self.assertEqual(read_back.section.page_number_align, "bottom + right")
        typst = TypstWriter(read_back, TypstWriteOptions(materialize_assets=False)).write()
        self.assertIn('numbering: "1 of 1"', typst)
        self.assertIn('number-align: bottom + right', typst)

    def test_docx_multisection_breaks_apply_following_section_properties(self) -> None:
        portrait = SectionProperties(
            page_width_pt=595.276, page_height_pt=841.89,
            margin_top_pt=51, margin_bottom_pt=51, margin_left_pt=51, margin_right_pt=51,
        )
        landscape = SectionProperties(
            page_width_pt=841.89, page_height_pt=595.276, orientation="landscape",
            margin_top_pt=42.5, margin_bottom_pt=42.5, margin_left_pt=42.5, margin_right_pt=42.5,
            page_numbering="1 of 1", page_number_align="bottom + right",
            header_default=[Paragraph([Text("Landscape appendix")])],
        )
        final_portrait = SectionProperties(
            page_width_pt=595.276, page_height_pt=841.89,
            margin_top_pt=54, margin_bottom_pt=54, margin_left_pt=54, margin_right_pt=54,
            header_default=[Paragraph([Text("Actions")])],
        )
        # BreakBlock.section is the sectPr serialized at the end of the preceding
        # Word section; the body-level sectPr supplies the final section.
        document = Document(
            blocks=[
                Paragraph([Text("Portrait")]),
                BreakBlock("section", portrait),
                Paragraph([Text("Landscape")]),
                BreakBlock("section", landscape),
                Paragraph([Text("Portrait again")]),
            ],
            sections=[portrait, landscape, final_portrait],
            source_format="docx",
        )
        data = DocxWriter(document, DocxWriteOptions(embed_typst_source=False)).build()
        read_back = DocxReader.read(data, DocxReadOptions())
        breaks = [block for block in read_back.blocks
                  if isinstance(block, BreakBlock) and block.break_type == "section"]
        self.assertEqual(len(breaks), 2)
        self.assertGreater((breaks[0].section or SectionProperties()).page_width_pt,
                           (breaks[0].section or SectionProperties()).page_height_pt)
        self.assertLess((breaks[1].section or SectionProperties()).page_width_pt,
                        (breaks[1].section or SectionProperties()).page_height_pt)
        typst = TypstWriter(read_back, TypstWriteOptions(materialize_assets=False)).write()
        landscape_pos = typst.find("width: 841.9pt")
        final_portrait_pos = typst.rfind("width: 595.3pt")
        self.assertGreater(landscape_pos, 0)
        self.assertGreater(final_portrait_pos, landscape_pos)
        self.assertIn('numbering: "1 of 1"', typst[landscape_pos:final_portrait_pos])
        self.assertIn("Landscape appendix", typst[landscape_pos:final_portrait_pos])
        self.assertIn("Actions", typst[final_portrait_pos:])

    def test_inline_content_control_preserves_visible_text(self) -> None:
        document = Document(blocks=[Paragraph([Text("SUPPLIER_VALUE")])], source_format="docx")
        data = DocxWriter(document, DocxWriteOptions(embed_typst_source=False)).build()
        source = io.BytesIO(data)
        output = io.BytesIO()
        w = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
        with zipfile.ZipFile(source, "r") as archive, zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as target:
            for info in archive.infolist():
                payload = archive.read(info.filename)
                if info.filename == "word/document.xml":
                    root = ET.fromstring(payload)
                    paragraph = root.find(f".//{w}body/{w}p")
                    self.assertIsNotNone(paragraph)
                    assert paragraph is not None
                    run = paragraph.find(f"{w}r")
                    self.assertIsNotNone(run)
                    assert run is not None
                    index = list(paragraph).index(run)
                    paragraph.remove(run)
                    sdt = ET.Element(f"{w}sdt")
                    sdt_pr = ET.SubElement(sdt, f"{w}sdtPr")
                    ET.SubElement(sdt_pr, f"{w}alias", {f"{w}val": "Supplier"})
                    ET.SubElement(sdt_pr, f"{w}tag", {f"{w}val": "supplier"})
                    ET.SubElement(sdt_pr, f"{w}text")
                    content = ET.SubElement(sdt, f"{w}sdtContent")
                    content.append(run)
                    paragraph.insert(index, sdt)
                    payload = ET.tostring(root, encoding="utf-8", xml_declaration=True)
                target.writestr(info, payload)
        read_back = DocxReader.read(output.getvalue(), DocxReadOptions(unknown="preserve"))
        typst = TypstWriter(read_back, TypstWriteOptions(materialize_assets=False)).write()
        self.assertIn("SUPPLIER\\_VALUE", typst)
        self.assertIn("Word inline content control", typst)
        self.assertIn("#typx_raw", typst)

    def test_word_bookmark_ref_maps_to_link_without_duplicate_heading_label(self) -> None:
        document = Document(
            blocks=[
                Heading(1, [Text("Purpose and scope")], label="purpose_scope"),
                Paragraph([
                    Text("Return to "),
                    Field("REF purpose_scope \\h", [Text("Purpose and scope")]),
                    Text(" on page "),
                    Field("PAGEREF purpose_scope \\h", [Text("2")]),
                    Text("."),
                ]),
            ],
            source_format="docx",
        )
        data = DocxWriter(document, DocxWriteOptions(embed_typst_source=False)).build()
        read_back = DocxReader.read(data, DocxReadOptions())
        typst = TypstWriter(read_back, TypstWriteOptions(materialize_assets=False)).write()
        heading_line = next(line for line in typst.splitlines() if line.startswith("= "))
        self.assertEqual(heading_line.count("<purpose_scope>"), 1)
        self.assertIn("#link(<purpose_scope>)[Purpose and scope]", typst)
        self.assertIn('#ref(<purpose_scope>, form: "page")', typst)
        self.assertNotIn("@purpose_scope", typst)

    def test_builtin_style_property_order_and_theme_matrix_are_word_compatible(self) -> None:
        package = DocxPackage.open(
            DocxWriter(self._bullet_document(), DocxWriteOptions(embed_typst_source=False)).build()
        )
        w = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
        styles = ET.fromstring(package.parts["word/styles.xml"])
        by_id = {style.get(f"{w}styleId"): style for style in styles.findall(f"{w}style")}

        heading = by_id["Heading1"]
        self.assertEqual(
            [child.tag.removeprefix(w) for child in heading.find(f"{w}pPr")],
            ["keepNext", "spacing", "outlineLvl"],
        )
        self.assertEqual(
            [child.tag.removeprefix(w) for child in heading.find(f"{w}rPr")],
            ["rFonts", "b", "color", "sz", "szCs"],
        )
        hyperlink = by_id["Hyperlink"]
        self.assertIsNone(hyperlink.find(f"{w}rPr"))
        quote = by_id["Quote"]
        self.assertEqual(
            [child.tag.removeprefix(w) for child in quote.find(f"{w}pPr")],
            ["ind"],
        )
        code = by_id["Code"]
        self.assertEqual(
            [child.tag.removeprefix(w) for child in code.find(f"{w}pPr")],
            ["spacing"],
        )

        a = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
        theme = ET.fromstring(package.parts["word/theme/theme1.xml"])
        for list_name in ("fillStyleLst", "lnStyleLst", "effectStyleLst", "bgFillStyleLst"):
            matrix = theme.find(f".//{a}{list_name}")
            self.assertIsNotNone(matrix)
            assert matrix is not None
            self.assertEqual(len(matrix), 3)

    def test_typst_default_visual_profile_matches_typst_0151(self) -> None:
        source = """#title[Document title]
= Heading one
== Heading two
=== Heading three

Normal paragraph with #link("https://example.com")[a link] and `raw`.

#quote(block: true)[Quoted paragraph.]

#table(columns: 2, [A], [B], [C], [D])

#grid(columns: 2, [X], [Y])
"""
        document = TypstReader.read(source)
        package = DocxPackage.open(
            DocxWriter(document, DocxWriteOptions(embed_typst_source=False)).build()
        )
        w = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
        styles = ET.fromstring(package.parts["word/styles.xml"])
        by_id = {style.get(f"{w}styleId"): style for style in styles.findall(f"{w}style")}

        normal = by_id["Normal"]
        normal_fonts = normal.find(f"{w}rPr/{w}rFonts")
        self.assertEqual(normal_fonts.get(f"{w}ascii"), "Libertinus Serif")
        self.assertEqual(normal.find(f"{w}rPr/{w}sz").get(f"{w}val"), "22")
        self.assertEqual(normal.find(f"{w}rPr/{w}color").get(f"{w}val"), "000000")
        normal_spacing = normal.find(f"{w}pPr/{w}spacing")
        self.assertEqual(normal_spacing.get(f"{w}after"), "60")
        self.assertEqual(normal_spacing.get(f"{w}line"), "240")
        self.assertEqual(normal_spacing.get(f"{w}lineRule"), "auto")

        self.assertEqual(by_id["Title"].find(f"{w}rPr/{w}sz").get(f"{w}val"), "37")
        self.assertEqual(by_id["Heading1"].find(f"{w}rPr/{w}sz").get(f"{w}val"), "31")
        self.assertEqual(by_id["Heading2"].find(f"{w}rPr/{w}sz").get(f"{w}val"), "26")
        self.assertEqual(by_id["Heading3"].find(f"{w}rPr/{w}sz").get(f"{w}val"), "22")
        self.assertIsNone(by_id["Hyperlink"].find(f"{w}rPr"))
        self.assertEqual(by_id["Code"].find(f"{w}rPr/{w}rFonts").get(f"{w}ascii"), "DejaVu Sans Mono")
        self.assertEqual(by_id["Code"].find(f"{w}rPr/{w}sz").get(f"{w}val"), "18")

        font_table = ET.fromstring(package.parts["word/fontTable.xml"])
        fonts = {font.get(f"{w}name"): font for font in font_table.findall(f"{w}font")}
        self.assertEqual(fonts["Libertinus Serif"].find(f"{w}altName").get(f"{w}val"), "Palatino Linotype")
        self.assertEqual(fonts["DejaVu Sans Mono"].find(f"{w}altName").get(f"{w}val"), "Consolas")

        doc_root = ET.fromstring(package.parts["word/document.xml"])
        sect = doc_root.find(f".//{w}sectPr")
        margins = sect.find(f"{w}pgMar")
        self.assertEqual(margins.get(f"{w}top"), "1417")
        self.assertEqual(margins.get(f"{w}right"), "1417")
        self.assertEqual(margins.get(f"{w}bottom"), "1417")
        self.assertEqual(margins.get(f"{w}left"), "1417")
        self.assertEqual(margins.get(f"{w}header"), "992")
        self.assertEqual(margins.get(f"{w}footer"), "992")
        self.assertEqual(sect.find(f"{w}cols").get(f"{w}space"), "363")

        tables = doc_root.findall(f".//{w}tbl")
        self.assertEqual(len(tables), 2)
        table_borders = tables[0].find(f"{w}tblPr/{w}tblBorders")
        self.assertIsNotNone(table_borders)
        for border in list(table_borders):
            self.assertEqual(border.get(f"{w}val"), "single")
            self.assertEqual(border.get(f"{w}sz"), "8")
            self.assertEqual(border.get(f"{w}color"), "000000")
        table_margin = tables[0].find(f".//{w}tcPr/{w}tcMar/{w}left")
        grid_margin = tables[1].find(f".//{w}tcPr/{w}tcMar/{w}left")
        self.assertEqual(table_margin.get(f"{w}w"), "100")
        grid_borders = tables[1].find(f"{w}tblPr/{w}tblBorders")
        self.assertIsNotNone(grid_borders)
        self.assertTrue(all(border.get(f"{w}val") == "nil" for border in list(grid_borders)))
        self.assertEqual(grid_margin.get(f"{w}w"), "0")

    def test_explicit_typst_style_and_layout_overrides_win_over_profile(self) -> None:
        source = """#set text(font: "Arial", size: 14pt)
#set page(margin: (x: 1cm, y: 2cm))
= Heading
Body with `code`.
```py
print(1)
```
"""
        document = TypstReader.read(source)
        self.assertAlmostEqual(document.section.margin_left_pt, 28.3464567, places=5)
        self.assertAlmostEqual(document.section.margin_right_pt, 28.3464567, places=5)
        self.assertAlmostEqual(document.section.margin_top_pt, 56.6929134, places=5)
        self.assertAlmostEqual(document.section.margin_bottom_pt, 56.6929134, places=5)

        heading = document.blocks[0]
        self.assertIsInstance(heading, Heading)
        heading_text = heading.inlines[0]
        self.assertIsInstance(heading_text, Text)
        self.assertEqual(heading_text.style.font, "Arial")
        self.assertAlmostEqual(heading_text.style.size_pt or 0, 19.6)

        paragraph = document.blocks[1]
        self.assertIsInstance(paragraph, Paragraph)
        plain_text = paragraph.inlines[0]
        self.assertEqual(plain_text.style.font, "Arial")
        self.assertAlmostEqual(plain_text.style.size_pt or 0, 14.0)
        raw = paragraph.inlines[1]
        self.assertIsInstance(raw, RawInline)
        raw_text = raw.fallback[0]
        self.assertEqual(raw_text.style.font, "DejaVu Sans Mono")
        self.assertAlmostEqual(raw_text.style.size_pt or 0, 11.2)

        code = document.blocks[2]
        self.assertIsInstance(code, CodeBlock)
        self.assertEqual(code.style.font, "DejaVu Sans Mono")
        self.assertAlmostEqual(code.style.size_pt or 0, 11.2)

    def test_note_body_emits_reference_marker_with_spacing(self) -> None:
        document = Document(
            blocks=[Paragraph([Text("Body"), NoteRef("footnote", "1", [Paragraph([Text("Note text")])])])],
            source_format="typst",
        )
        package = DocxPackage.open(
            DocxWriter(document, DocxWriteOptions(embed_typst_source=False)).build()
        )
        w = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
        footnotes = ET.fromstring(package.parts["word/footnotes.xml"])
        note = footnotes.find(f"{w}footnote[@{w}id='1']")
        self.assertIsNotNone(note)
        first_p = note.find(f"{w}p")
        self.assertIsNotNone(first_p.find(f"{w}r/{w}footnoteRef"))
        text_nodes = first_p.findall(f"{w}r/{w}t")
        self.assertGreaterEqual(len(text_nodes), 2)
        self.assertEqual(text_nodes[0].text, " ")
        self.assertEqual(text_nodes[1].text, "Note text")

    def test_docx_page_field_uses_typst_context(self) -> None:
        section = SectionProperties(footer_default=[Paragraph([Text("Page "), Field("PAGE", [Text("1")])])])
        document = Document(blocks=[Paragraph([Text("Body")])], sections=[section], source_format="docx")
        typst = TypstWriter(document, TypstWriteOptions(materialize_assets=False)).write()
        self.assertIn("#context counter(page).display()", typst)
        self.assertNotIn("#counter(page).display()", typst)

    def test_omml_multi_letter_identifier_becomes_literal_math_text(self) -> None:
        root = ET.fromstring(
            '<m:oMath xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math">'
            '<m:r><m:t>A = </m:t></m:r><m:f><m:num><m:r><m:t>MTBF</m:t></m:r></m:num>'
            '<m:den><m:r><m:t>MTBF + MTTR</m:t></m:r></m:den></m:f></m:oMath>'
        )
        self.assertEqual(omml_to_typst(root), 'A = frac("MTBF", "MTBF" + "MTTR")')
        func = ET.fromstring(
            '<m:func xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math">'
            '<m:fName><m:r><m:t>sin</m:t></m:r></m:fName><m:e><m:r><m:t>x</m:t></m:r></m:e></m:func>'
        )
        self.assertEqual(omml_to_typst(func), "sin(x)")

    def test_word_auto_line_spacing_maps_to_readable_typst_leading(self) -> None:
        default_style = StyleDefinition(
            style_id="__docDefaults__",
            paragraph=ParagraphStyle(line_spacing=1.15, line_spacing_rule="auto"),
        )
        document = Document(
            blocks=[Paragraph([Text("Line one")]), ListBlock(False, [ListItem([Paragraph([Text("Item")])])])],
            styles={"__docDefaults__": default_style}, source_format="docx",
        )
        typst = TypstWriter(document, TypstWriteOptions(materialize_assets=False)).write()
        self.assertIn("#set par(leading: 0.65em)", typst)

    def test_docx_system_font_is_copied_into_typst_assets(self) -> None:
        document = Document(
            blocks=[Paragraph([Text("Hello", TextStyle(font="Synthetic Font"))])], source_format="docx"
        )
        docx = DocxWriter(document, DocxWriteOptions(embed_typst_source=False)).build()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            font_path = root / "Synthetic-Regular.ttf"
            font_path.write_bytes(fake_font_bytes())
            with patch("typx.docx_reader.find_system_fonts", return_value=[font_path]):
                parsed = DocxReader.read(docx, DocxReadOptions(extract_assets=True))
            output = root / "result.typ"
            typst = TypstWriter(parsed, TypstWriteOptions(output_path=output, materialize_assets=True)).write()
            copied = list((root / "result_assets" / "fonts").glob("*.ttf"))
            self.assertEqual(len(copied), 1)
            self.assertEqual(copied[0].read_bytes(), font_path.read_bytes())
            self.assertIn("--font-path", typst)
            self.assertIn('font: "Synthetic Font"', typst)

    def test_docx_embedded_font_has_priority_and_is_deobfuscated(self) -> None:
        document = Document(
            blocks=[Paragraph([Text("Hello", TextStyle(font="Synthetic Font"))])], source_format="docx"
        )
        original = DocxWriter(document, DocxWriteOptions(embed_typst_source=False)).build()
        font_data = fake_font_bytes()
        font_key = "{00112233-4455-6677-8899-AABBCCDDEEFF}"
        from typx.fonts import deobfuscate_ooxml_font
        obfuscated = deobfuscate_ooxml_font(font_data, font_key)
        source = io.BytesIO(original)
        output = io.BytesIO()
        w = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
        r = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
        relns = "{http://schemas.openxmlformats.org/package/2006/relationships}"
        with zipfile.ZipFile(source, "r") as archive, zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as target:
            for info in archive.infolist():
                payload = archive.read(info.filename)
                if info.filename == "word/fontTable.xml":
                    root = ET.fromstring(payload)
                    font = next(item for item in root.findall(f"{w}font") if item.get(f"{w}name") == "Synthetic Font")
                    ET.SubElement(font, f"{w}embedRegular", {f"{r}id": "rIdFont1", f"{w}fontKey": font_key})
                    payload = ET.tostring(root, encoding="utf-8", xml_declaration=True)
                target.writestr(info, payload)
            rel_root = ET.Element(f"{relns}Relationships")
            ET.SubElement(rel_root, f"{relns}Relationship", {
                "Id": "rIdFont1",
                "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/font",
                "Target": "fonts/font1.odttf",
            })
            target.writestr("word/_rels/fontTable.xml.rels", ET.tostring(rel_root, encoding="utf-8", xml_declaration=True))
            target.writestr("word/fonts/font1.odttf", obfuscated)
        with patch("typx.docx_reader.find_system_fonts") as system_lookup:
            parsed = DocxReader.read(output.getvalue(), DocxReadOptions(extract_assets=True))
        self.assertFalse(any(call.args and call.args[0] == "Synthetic Font" for call in system_lookup.call_args_list))
        fonts = [resource for resource in parsed.resources.values() if resource.raw.get("kind") == "font" and resource.raw.get("family") == "Synthetic Font"]
        self.assertEqual(len(fonts), 1)
        self.assertEqual(fonts[0].data, font_data)
        self.assertEqual(fonts[0].raw.get("source"), "embedded")

    def test_word_bibliography_sources_and_fields_map_to_typst(self) -> None:
        document = Document(
            blocks=[
                Paragraph([Text("Evidence "), Field("CITATION Smith2024 \\l 1033 \\p 17", [Text("(Smith, 2024, p. 17)")]), Text(".")]),
                Paragraph([Field("CITATION Smith2024 \\l 1033 \\m Jones2025", [Text("(Jones, 2025; Smith, 2024)")])]),
                Paragraph([Field("BIBLIOGRAPHY", [Text("cached bibliography")])]),
            ],
            source_format="docx",
        )
        data = add_word_bibliography(DocxWriter(document, DocxWriteOptions(embed_typst_source=False)).build())
        parsed = DocxReader.read(data, DocxReadOptions(extract_assets=True))
        self.assertIsNotNone(parsed.bibliography_resource_id)
        self.assertEqual(parsed.bibliography_keys["Smith2024"], "Smith2024")
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "bibliography.typ"
            typst = TypstWriter(parsed, TypstWriteOptions(output_path=output, materialize_assets=True)).write()
            bib = Path(directory) / "bibliography_assets" / "bibliography" / "references.bib"
            self.assertTrue(bib.is_file())
            bib_text = bib.read_text(encoding="utf-8")
            self.assertIn("@article{Smith2024", bib_text)
            self.assertIn("author = {Smith, Alex}", bib_text)
            self.assertIn("@book{Jones2025", bib_text)
            self.assertIn('#cite(label("Smith2024"), supplement: [p. 17])', typst)
            self.assertIn('#cite(label("Smith2024"), form: none)', typst)
            self.assertIn('#cite(label("Jones2025"), form: none)', typst)
            self.assertIn("(Jones, 2025; Smith, 2024)", typst)
            self.assertIn('#bibliography("bibliography_assets/bibliography/references.bib", title: none, style: "apa")', typst)

    def test_fields_are_not_forced_to_update_on_open_by_default(self) -> None:
        package = DocxPackage.open(
            DocxWriter(self._bullet_document(), DocxWriteOptions(embed_typst_source=False)).build()
        )
        root = ET.fromstring(package.parts["word/settings.xml"])
        ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
        self.assertIsNone(root.find(f"{ns}updateFields"))

        package = DocxPackage.open(
            DocxWriter(
                self._bullet_document(),
                DocxWriteOptions(embed_typst_source=False, update_fields=True),
            ).build()
        )
        root = ET.fromstring(package.parts["word/settings.xml"])
        update = root.find(f"{ns}updateFields")
        self.assertIsNotNone(update)
        assert update is not None
        self.assertEqual(update.get(f"{ns}val"), "true")


class PackageTests(unittest.TestCase):
    def test_broad_document_and_determinism(self) -> None:
        doc = broad_document()
        options = DocxWriteOptions(embed_typst_source=True, preserve_revisions=True)
        first = DocxWriter(doc, options).build()
        second = DocxWriter(doc, options).build()
        self.assertEqual(first, second)

        package = DocxPackage.open(first)
        self.assertIn("word/document.xml", package.parts)
        self.assertIn("word/styles.xml", package.parts)
        self.assertIn("word/numbering.xml", package.parts)
        self.assertIn("word/comments.xml", package.parts)
        self.assertIn("word/footnotes.xml", package.parts)
        self.assertIn("word/endnotes.xml", package.parts)
        self.assertTrue(any(name.startswith("word/media/") for name in package.parts))

        for source in [""] + [name for name in package.parts if not name.endswith(".rels")]:
            for rel in package.relationships(source).values():
                if not rel.external:
                    self.assertIn(rel.resolved_target, package.parts, (source, rel.id, rel.resolved_target))

        embedded = extract_typst_from_docx(package)
        self.assertIsNotNone(embedded)
        assert embedded is not None
        self.assertEqual(embedded.source, doc.source_text)
        self.assertTrue(embedded.package_unchanged(package))

        parsed = DocxReader(package, DocxReadOptions(revisions="preserve", extract_assets=True)).parse()
        block_names = {type(block).__name__ for block in parsed.walk_blocks()}
        for name in {"Heading", "Paragraph", "ListBlock", "Table", "MathBlock", "ContentControl"}:
            self.assertIn(name, block_names)
        self.assertGreaterEqual(len(parsed.resources), 1)
        self.assertGreaterEqual(len(parsed.comments), 1)
        self.assertGreaterEqual(len(parsed.footnotes), 1)
        self.assertGreaterEqual(len(parsed.endnotes), 1)

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "broad.typ"
            typst = TypstWriter(
                parsed,
                TypstWriteOptions(output_path=output, materialize_assets=True),
            ).write()
            self.assertIn("#set page", typst)
            self.assertIn("#table", typst)
            reparsed = TypstReader(
                typst,
                output,
                TypstReadOptions(root=output.parent, load_assets=True),
            ).parse()
            self.assertGreater(len(reparsed.blocks), 5)


    def test_strict_namespace_input(self) -> None:
        source = DocxWriter(broad_document(), DocxWriteOptions(embed_typst_source=False)).build()
        strict = strictify_docx(source)
        package = DocxPackage.open(strict)
        self.assertEqual(package.office_document_part(), "word/document.xml")
        parsed = DocxReader(package, DocxReadOptions(extract_assets=True)).parse()
        self.assertTrue(any(isinstance(block, Heading) for block in parsed.blocks))
        self.assertTrue(any(isinstance(block, Table) for block in parsed.walk_blocks()))
        self.assertGreaterEqual(len(parsed.resources), 1)

    def test_apostrophe_does_not_break_content_scanning(self) -> None:
        source = "#quote(block: true)[Word's quoted text.]\n\n= After\n\nStill outside.\n"
        parsed = TypstReader(source).parse()
        self.assertEqual([type(block).__name__ for block in parsed.blocks], ["Quote", "Heading", "Paragraph"])
        quote = parsed.blocks[0]
        self.assertIsInstance(quote, Quote)
        assert isinstance(quote, Quote)
        self.assertEqual(len(quote.blocks), 1)

    def test_exact_payloads(self) -> None:
        source = "= Exact source\n\nHello.\n"
        document = TypstReader(source).parse()
        document.source_format = "typst"
        document.source_text = source
        docx = DocxWriter(document, DocxWriteOptions(embed_typst_source=True)).build()
        embedded = extract_typst_from_docx(DocxPackage.open(docx))
        self.assertIsNotNone(embedded)
        assert embedded is not None
        self.assertEqual(embedded.source, source)
        self.assertTrue(embedded.package_unchanged(DocxPackage.open(docx)))

        generated = "= Semantic body\n\nHello.\n"
        typst = embed_docx_in_typst(generated, docx, {"test": "yes"})
        payload = extract_docx_from_typst(typst)
        self.assertIsNotNone(payload)
        assert payload is not None
        self.assertTrue(payload.unchanged)
        self.assertEqual(payload.payload, docx)
        changed = typst.replace("Hello.", "Edited.")
        changed_payload = extract_docx_from_typst(changed)
        self.assertIsNotNone(changed_payload)
        assert changed_payload is not None
        self.assertFalse(changed_payload.unchanged)


class CliTests(unittest.TestCase):
    def test_cli_both_exact_directions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            typ = root / "input.typ"
            docx = root / "output.docx"
            recovered_typ = root / "recovered.typ"
            typ.write_text("= CLI\n\n*Bold* and $ frac(1, 2) $.\n", encoding="utf-8")
            self.assertEqual(main(["convert", str(typ), str(docx), "--roundtrip", "semantic", "--quiet"]), 0)
            self.assertEqual(main(["convert", str(docx), str(recovered_typ), "--roundtrip", "auto", "--quiet"]), 0)
            self.assertEqual(typ.read_bytes(), recovered_typ.read_bytes())
            self.assertEqual(main(["validate", str(docx), "--deep"]), 0)

            original_docx = root / "original.docx"
            semantic_typ = root / "semantic.typ"
            recovered_docx = root / "recovered.docx"
            original_docx.write_bytes(DocxWriter(broad_document(), DocxWriteOptions(embed_typst_source=False)).build())
            self.assertEqual(main(["convert", str(original_docx), str(semantic_typ), "--roundtrip", "semantic", "--quiet"]), 0)
            self.assertEqual(main(["convert", str(semantic_typ), str(recovered_docx), "--roundtrip", "auto", "--quiet"]), 0)
            self.assertEqual(original_docx.read_bytes(), recovered_docx.read_bytes())


if __name__ == "__main__":
    unittest.main()
