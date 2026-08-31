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

DOCX stores fields such as TOC, REF, PAGEREF, PAGE, NUMPAGES, SEQ, DATE, CITATION, and BIBLIOGRAPHY as instructions plus cached results. `typx` maps known fields to native Typst constructs where practical. Static Typst references to numbered headings, figures, and equations become internal Word hyperlinks; page-form references become `PAGEREF`; and simple automatic page numbering becomes PAGE/NUMPAGES fields. In the reverse direction, `PAGEREF` maps to Typst's page-reference form, while general Word `REF`/`NOTEREF` fields map to internal `#link` calls because a Word bookmark may target arbitrary content that is not a Typst referenceable element. Other fields use a `typx_field` wrapper. Applications may need to update layout-dependent field results after edits.

## Content controls

Block and inline Word structured-document tags (content controls) preserve their visible content. `typx` retains control metadata in semantic or raw-preservation wrappers where practical. Application-specific validation, bindings to custom XML data stores, and interactive form behavior are not executed by Typst.

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

DOCX-to-Typst conversion reads Word's current-document bibliography source records from the package's `customXml` data store and writes them as a BibLaTeX asset. Common `CITATION` and `BIBLIOGRAPHY` fields become Typst `cite`/`bibliography` elements. Common Word style selections are mapped to Typst built-in CSL styles where there is a clear counterpart.

Typst CSL processing and Word's bibliography engine are still not identical. Word can group sources, use application-specific field switches, or cache a display that cannot be reconstructed exactly from Typst's citation model. In those cases, `typx` preserves the cached Word display and registers the source keys invisibly so bibliography membership is not lost. Unsupported Word source types/fields are retained as far as BibLaTeX permits, but style-specific punctuation and ordering may differ.

## Font assets in DOCX-to-Typst conversion

When assets are enabled, the reverse converter collects font families actually used by document content. Embedded Word font parts are preferred; if a required face is not embedded, `typx` searches the local system font directories and Word font-table alternate names. Matching font files are copied into the generated Typst asset tree. The generated Typst refers to their family names because Typst selects fonts by family rather than by file path.

The set of system fonts is machine-dependent. A conversion performed on Windows with Microsoft Office installed can therefore resolve fonts that are unavailable on a Linux host, and vice versa. If a font is neither embedded nor installed, `typx` emits a warning and leaves the requested family name in the Typst output. Local Typst compilation must make extracted font directories discoverable with `--font-path` (or an equivalent environment setting). Font licensing remains the user's responsibility; typx release archives do not redistribute fonts.

## Exact round-trip eligibility

Exact recovery is intentionally conservative:

- a Typst file can restore an embedded DOCX only when the generated body hash is unchanged;
- a DOCX can restore embedded Typst only when its semantic package digest is unchanged;
- editing and resaving in Word or LibreOffice commonly changes package semantics or normalization, so semantic conversion may be selected even when the document looks unchanged;
- `--roundtrip exact` fails instead of guessing.

## Validation scope

DOCX validation checks package structure and the converter's semantic parser. It is not formal schema validation against every ECMA-376 XSD and Microsoft extension schema.

Typst validation checks the static grammar understood by `typx`. It is not equivalent to `typst compile` or `typst eval`.
