# Architecture

## Conversion pipeline

```text
.typ source
    │
    ▼
TypstReader ───────────────┐
                           │
                           ▼
                    shared document model
                           │
                           ▼
DOCXWriter ───────────────► .docx OPC package

.docx OPC package
    │
    ▼
DocxPackage + DocxReader ─┐
                          │
                          ▼
                   shared document model
                          │
                          ▼
TypstWriter ─────────────► .typ source + assets
```

## Shared model

`src/typx/model.py` defines a format-neutral tree:

- `Document` contains metadata, sections, resources, styles, comments, notes, blocks, warnings, and optional source payloads.
- Block nodes cover paragraphs, headings, lists, tables, figures, quotes, code, display math, dividers, breaks, content controls, and raw fragments.
- Inline nodes cover text, breaks, links, bookmarks, images, math, notes, fields, citations, comment anchors, revisions, and raw fragments.
- Styles separate paragraph and text properties and use points, percentages, normalized colors, and explicit directionality.

This model is intentionally richer than the common intersection of Typst and DOCX. Features that only one format supports can therefore survive the first parse and be approximated or preserved on output.

## DOCX package layer

`DocxPackage` is a safe OPC reader. It resolves relationships, content types, and the main document part. XML parsing normalizes ISO/IEC 29500 Strict namespaces to the internal Transitional vocabulary. The writer emits deterministic Transitional WordprocessingML because it has the broadest compatibility across Microsoft Word, LibreOffice, and other consumers.

`PackageBuilder` writes stable part order, stable relationship order, fixed ZIP timestamps, and compressed package members. The semantic digest ignores volatile document properties and the converter's own custom source relationship.

## DOCX reader

The reader resolves:

1. package and document properties;
2. style inheritance;
3. abstract and concrete numbering definitions;
4. comments and note parts;
5. document blocks and inline runs;
6. section references and header/footer parts;
7. images and other resources;
8. OMML equations;
9. preservation nodes for unsupported XML.

Tracked revisions can be accepted, rejected, annotated, or retained as revision nodes.

## Typst reader

The Typst reader is a static parser, not an evaluator. It handles three syntactic modes and recognizes common document-producing expressions. Static local includes and assets can be resolved. Literal values and simple wrappers are interpreted. Arbitrary code remains source-level data and is retained by exact-roundtrip embedding or explicit raw nodes.

## Writers

The Typst writer favors idiomatic markup for simple constructs and explicit function calls where properties are needed. It writes extracted resources beside the output file.

The DOCX writer builds all package parts directly with `xml.etree.ElementTree` and `zipfile`. It does not rely on Microsoft Office automation, LibreOffice, `python-docx`, or a native XML library.

## Preservation strategy

The converter uses three layers:

1. **Native mapping** through the shared model.
2. **Raw fragment preservation** for unsupported OOXML nodes and converter wrappers.
3. **Exact counterpart embedding** for byte-exact DOCX recovery or source-exact Typst recovery when integrity checks show that the counterpart was not edited.

The layered design makes lossy reconstruction explicit rather than silently deleting unsupported constructs.
