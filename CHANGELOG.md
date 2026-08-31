# Changelog

## 0.3.2 – 2026-08-28

- Fix DOCX-to-Typst PAGE/NUMPAGES field output by wrapping contextual page-counter reads in `#context`.
- Convert multi-letter Word OMML identifiers such as `MTBF` and `MTTR` to quoted Typst math text while retaining mathematical function names such as `sin`.
- Recalibrate Word automatic line spacing to Typst leading, mapping Word's common 1.15-line setting to Typst's 0.65 em default instead of an undersized absolute point gap.
- Extract fonts actually used by DOCX content into the generated Typst asset tree. Embedded Word font parts are preferred and deobfuscated; missing variants fall back to matching fonts installed in the local Windows/Linux font folders. Theme-font references and Word alternate font names are resolved.
- Emit Typst font-family fallback lists when a copied font's internal family name differs from the Word family name, and document `--font-path` usage for local Typst compilation. Font binaries are copied only at conversion time and are not bundled with typx releases.
- Add Microsoft Word bibliography conversion: current-document bibliography sources from `customXml` become a local BibLaTeX asset, single-source `CITATION` fields become native Typst citations, page switches become citation supplements, common Word styles map to Typst bibliography styles, and `BIBLIOGRAPHY` becomes a Typst bibliography element. Grouped Word citations retain their cached display while registering each source invisibly.
- Add regression coverage for contextual page fields, OMML text identifiers, Word-to-Typst leading, embedded/system font extraction, font deobfuscation, and Word bibliography conversion; the core suite now contains 30 tests.

## 0.3.1 – 2026-08-28

- Replace exact Word line spacing with expandable automatic leading and reduce default paragraph-after spacing, fixing excessive vertical rhythm and preventing inline SVG/shape clipping.
- Add Word font-table fallbacks from Libertinus Serif to Palatino Linotype and from DejaVu Sans Mono to Consolas so code remains monospace and body text remains serif when Typst's bundled fonts are unavailable.
- Define superscript `FootnoteReference` and `EndnoteReference` character styles and apply them to body and note markers.
- Fix Typst table row construction and Word table placement for cells following earlier row spans; compact final cell-paragraph spacing for Typst tables and grids.
- Preserve Typst list text beginning with `[x]` or `[ ]` literally instead of converting it to checkbox glyphs.
- Harden independent Word list definitions with unique deterministic numbering template identities and explicit suffix metadata to prevent desktop Word from merging unrelated bullet/enum formats.
- Correct the advanced cross-reference fixture so `MTBF`/`MTTR` are math text and the labelled equation is valid Typst.
- Add regressions for literal bracket-list text, row-span placement, superscript note references, Word font fallbacks, and independent numbering templates; the core suite now contains 24 tests.

## 0.3.0 – 2026-08-28

- Align default Typst-to-DOCX typography with Typst 0.15.1: Libertinus Serif 11 pt body text, black compact title/heading scales, plain links, and DejaVu Sans Mono raw/code text at 0.8 em.
- Align default page geometry with Typst A4: 2.5 cm margins, Typst-like header/footer placement, and a 4% default column gutter derived from the active content width.
- Make paragraph leading/spacing, block quotes, figures/captions, list placement, and figure centering substantially closer to Typst's default visual rhythm.
- Match Typst's distinct `table` and `grid` defaults: tables use 1 pt black rules with 5 pt cell inset, while grids remain borderless with zero inset unless explicitly styled.
- Preserve explicit Typst text size/font and page-margin overrides over the visual profile, including proportional default heading scaling and raw/code sizing relative to the active text size.
- Correct Typst `(x: ..., y: ...)` page-margin shorthand so each shorthand applies to both opposing sides.
- Add explicit `columns(gutter: ...)` handling while retaining Typst's 4% automatic gutter when no gutter is specified.
- Add visual-profile regression coverage; the core suite now contains 20 tests.

## 0.2.0 – 2026-08-28

- Resolve static Typst `@label` and `#ref(...)` cross-references to numbered headings, figures/tables, and equations; emit internal Word hyperlinks and dynamic `PAGEREF` fields for page-form references.
- Implement static document-order numbering for referenceable headings, figures, and equations, including visible numbered headings and equation numbers in generated DOCX.
- Add automatic Typst `page(numbering: ...)` conversion to Word PAGE/NUMPAGES fields, with left/center/right placement and semantic DOCX-to-Typst recovery for simple automatic page-number headers/footers.
- Fix ordered/unordered list type leakage and numbering continuation by giving each ordered-list instance an explicit start override.
- Match Typst's zero top-level list-marker indent by default while retaining hanging indentation for list bodies and nested levels.
- Preserve SVG intrinsic aspect ratio when only width or only height is specified.
- Support temporary `columns(...)` regions with continuous Word section breaks so column settings do not leak into later content or force unnecessary pages.
- Improve figure-wrapped tables, custom figure supplements, enum numbering-format mapping, page/section parsing, and reverse conversion of Word bookmarks, REF/PAGEREF fields, inline content controls, and multi-section documents.
- Add regression coverage for list type/restarts/indentation, width-only SVG sizing, cross-references, page numbering, and advanced section behavior; the core suite now contains 17 tests.
- Expand the realistic Typst interoperability corpus to 18 documents, including page references, nested mixed lists, spanned tables, grids, shapes, static variables/includes, temporary columns, and figure-wrapped tables.

## 0.1.1 – 2026-08-27

- Fix schema-invalid WordprocessingML child ordering in paragraph, run, style, section, and bullet-numbering properties that caused Microsoft Word to report unreadable content and repair generated DOCX files.
- Emit a complete three-entry DrawingML theme style matrix instead of empty style lists for better desktop Word interoperability.
- Render bullet markers as Unicode in the document font instead of forcing them through the legacy Symbol font, preventing missing-glyph rectangles in Word.
- Emit explicit numbering tabs for more stable list indentation across Word and LibreOffice.
- Stop forcing field recalculation on document open by default; add `--update-fields` for documents that explicitly need it.
- Add DOCX interoperability regression tests for numbering structure, bullet glyphs, and field-update settings.

## 0.1.0 – 2026-08-26

- Initial bidirectional Typst and DOCX converter.
- Shared document model with native mappings and raw preservation nodes.
- Deterministic Transitional WordprocessingML writer.
- Transitional and namespace-normalized Strict WordprocessingML reader.
- OMML and Typst math conversion.
- Exact source-counterpart embedding in both directions.
- 442-row mapping exported as Markdown, JSON, and CSV.
- Validation, inspection, and intermediate-model CLI commands.
