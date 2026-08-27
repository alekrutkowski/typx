# Limitations and semantic boundary

## Typst execution

`typx` does not execute the full Typst language. The following generally require the official Typst engine and are preserved rather than evaluated:

- arbitrary functions, recursion, loops, and dynamic imports;
- plugins and WebAssembly execution;
- contextual `query`, `locate`, `here`, `counter`, and `state` behavior beyond selected built-in field mappings;
- custom show rules and layout closures;
- data transformations over CSV, JSON, YAML, TOML, XML, CBOR, or arbitrary files;
- package code whose visual result depends on execution;
- exact line breaking, shaping, pagination, and measurement.

Literal bindings, common set rules, common element calls, static local includes, and static assets are parsed.

## Layout equivalence

Typst and Word use different layout engines. Even when semantic properties map, pagination can vary due to:

- font availability and font fallback;
- shaping, kerning, hyphenation, and line-breaking algorithms;
- widow/orphan and keep behavior;
- table auto-fit and merged-cell calculations;
- floating drawings and text wrapping;
- footnote placement;
- field results and application field-update settings;
- application compatibility mode and printer metrics.

The converter targets semantic and visual similarity, not identical coordinates.

## Word fields

DOCX stores fields such as TOC, REF, PAGEREF, PAGE, NUMPAGES, SEQ, DATE, CITATION, and BIBLIOGRAPHY as instructions plus cached results. `typx` maps known fields to native Typst constructs where practical. Other fields use a `typx_field` wrapper. Word-compatible applications may need to update fields after opening the generated DOCX.

## Word application extensions

Charts, SmartArt, OLE, ActiveX, ink, embedded packages, custom user interfaces, printer settings, signatures, document protection, and many Microsoft extension namespaces have no native Typst counterpart. They are handled as follows:

- native fallback images or visible text are used when available;
- raw XML and referenced parts are preserved where structurally safe;
- exact round-trip embedding retains an untouched source package;
- macros are not executed or emitted into `.docx`.

Encrypted or rights-managed packages cannot be parsed as ordinary DOCX ZIP packages.

## Strict and Transitional OOXML

The reader normalizes the principal ISO/IEC 29500 Strict namespaces and relationship types to its internal vocabulary. The writer emits Transitional WordprocessingML. Unknown Strict-only or extension constructs are preserved as raw data when possible.

## Revisions and comments

Tracked insertions, deletions, moves, authors, dates, and comment anchors are modeled. Property-change revisions, complex table revisions, threaded-comment extensions, and application-specific reply metadata may be preserved rather than transformed semantically.

## Bibliographies

Typst CSL processing and Word's bibliography/citation field model are not equivalent. Keys, supplements, visible fallback text, and selected metadata can be carried over, but style-specific output can differ.

## Exact round-trip eligibility

Exact recovery is intentionally conservative:

- a Typst file can restore an embedded DOCX only when the generated body hash is unchanged;
- a DOCX can restore embedded Typst only when its semantic package digest is unchanged;
- editing and resaving in Word or LibreOffice commonly changes package semantics or normalization, so semantic conversion may be selected even when the document looks unchanged;
- `--roundtrip exact` fails instead of guessing.

## Validation scope

DOCX validation checks package structure and the converter's semantic parser. It is not formal schema validation against every ECMA-376 XSD and Microsoft extension schema.

Typst validation checks the static grammar understood by `typx`. It is not equivalent to `typst compile` or `typst eval`.
