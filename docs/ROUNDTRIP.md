# Round-trip preservation

## DOCX source embedded in Typst

For semantic DOCX to Typst conversion, `typx` writes a leading block comment containing:

- format version;
- source format;
- SHA-256 of the generated Typst body;
- SHA-256 of the original DOCX bytes;
- gzip plus base64 encoded DOCX bytes;
- non-executable metadata.

The Typst file remains valid because the payload is inside a comment. On conversion back, the payload is restored only when the body hash still matches.

## Typst source embedded in DOCX

For semantic Typst to DOCX conversion, `typx` writes `customXml/typx-source.xml` containing:

- the original source compressed with gzip and encoded as base64;
- source SHA-256;
- a semantic digest of the generated DOCX package;
- optional source path and converter metadata.

The relationship uses a converter-specific URI. The semantic digest excludes volatile properties and the converter's own source part and relationship.

## Raw nodes

Unsupported OOXML nodes are compressed and encoded into `RawBlock` or `RawInline` nodes. The generated Typst uses converter wrappers whose visible result is a fallback body. On reverse conversion, structurally compatible raw OOXML can be reinserted.

## Editing policy

`auto` is the recommended default:

- untouched counterpart: exact recovery;
- edited counterpart: semantic conversion;
- unsupported subtrees: raw preservation where safe;
- no silent claim of perfect reversibility.
