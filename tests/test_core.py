from __future__ import annotations

import hashlib
import io
import zipfile
import struct
import tempfile
import unittest
import zlib
from pathlib import Path

from typx.cli import main
from typx.docx_package import DocxPackage
from typx.docx_reader import DocxReadOptions, DocxReader
from typx.docx_writer import DocxWriteOptions, DocxWriter
from typx.mapping import MAPPING, as_csv, as_json, as_markdown
from typx.omml import typst_math_to_omml
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
    Resource,
    SectionProperties,
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
