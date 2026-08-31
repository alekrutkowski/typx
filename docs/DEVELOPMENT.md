# Development guide

## Design goal

`typx` tries to make loss visible. A converter bug should not silently turn an unsupported construct into something that merely looks plausible. When a faithful native conversion is not available, the implementation should preserve the original material or emit a documented fallback.

## Core pipeline

Both readers produce `typx.model.Document`. Writers consume that same model.

```text
TypstReader ─┐
             ├─> Document model ─> TypstWriter
DocxReader  ─┘                  └─> DocxWriter
```

Important modules:

| Module | Responsibility |
|---|---|
| `typst_reader.py` | Static parsing of Typst source and recoverable code constructs |
| `docx_package.py` | OPC ZIP package, relationships, content types, safety checks |
| `docx_reader.py` | WordprocessingML → shared model |
| `model.py` | Shared document, block, inline, style, resource, note, and preservation types |
| `omml.py` | Typst math ↔ Office Math conversion helpers |
| `typst_writer.py` | Shared model → Typst source |
| `docx_writer.py` | Shared model → deterministic DOCX package |
| `roundtrip.py` | Exact counterpart embedding and integrity checks |
| `mapping.py` | Typst ↔ DOCX coverage matrix and exports |
| `cli.py` | Command-line interface |

## Run tests

From the repository root:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

The suite uses only the Python standard library.

## Compile-check Python sources

```bash
python3 -m compileall -q src tests scripts
```

## Build locally

```bash
python3 scripts/build_release.py
```

The builder first creates `dist/typx.pyz`, then copies it to a versioned name and creates deterministic source and bundle ZIP files.

Verify the output:

```bash
python3 scripts/verify_release.py
```

## Version consistency

The version currently lives in both `pyproject.toml` and `src/typx/constants.py`. CI checks that these values match:

```bash
python3 scripts/check_version.py
```

Release publication does not depend on a version tag. Every successful push to `main` updates the rolling GitHub Release.

## Reproducibility

Release archives use:

- sorted file order;
- a fixed ZIP timestamp;
- fixed file modes;
- deterministic compression settings.

CI runs the release builder twice and compares `SHA256SUMS.txt`. A change in hashes from an unchanged checkout is treated as a build failure.

## DOCX development notes

DOCX is an OPC package. A change that adds a new XML part usually requires attention to all of the following:

1. the part payload;
2. `[Content_Types].xml`;
3. the appropriate `.rels` relationship part;
4. relationship target normalization;
5. preservation behavior when the part is read but not semantically modeled.

Prefer namespace-aware XML construction and parsing. Never use string concatenation for user-provided XML text.

## Typst development notes

The Typst reader is intentionally static. If a construct requires general language evaluation, mark the boundary rather than implementing an unsafe or misleading pseudo-evaluator.

When a test claims a `.typ` file is valid Typst, validate it with the official Typst compiler. A successful `typx validate` only establishes that the converter's static parser accepts the file.
