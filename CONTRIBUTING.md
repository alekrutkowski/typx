# Contributing to typx

Thanks for considering a contribution. `typx` sits between two large document models, so small changes can have surprisingly wide effects. The most useful contributions are narrow, reproducible, and accompanied by a regression test.

## Development setup

Python 3.11 or newer is required. The runtime has no third-party dependencies.

```bash
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -e .
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

On Windows PowerShell:

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
py -m pip install -e .
$env:PYTHONPATH = "src"
py -m unittest discover -s tests -v
```

## Before submitting a pull request

Run the same core checks used by CI:

```bash
python3 -m compileall -q src tests scripts
PYTHONPATH=src python3 -m unittest discover -s tests -v
python3 scripts/build_release.py
python3 scripts/verify_release.py
```

Then run the release builder a second time and confirm that the hashes in `dist/SHA256SUMS.txt` do not change.

## Adding or changing a mapping

A mapping change should usually answer four questions:

1. What is the source construct?
2. What is the closest target construct?
3. What information is lost or approximated in each direction?
4. Is the construct implemented natively, partially, preserved, or unsupported?

The machine-readable mapping is generated from `src/typx/mapping.py`. Keep the Markdown, JSON, and CSV exports synchronized by using the CLI or the existing generation code rather than editing only one export by hand.

## Tests

Prefer small unit tests that isolate a specific document feature. For DOCX tests, construct minimal OOXML or use the internal model and writer when possible. For Typst tests, distinguish between:

- syntax accepted by `typx`'s static parser;
- syntax confirmed by the official Typst compiler.

Do not describe the former as compiler validation.

## Compatibility

Changes should preserve Python 3.11 support unless a version-policy change is discussed first. Avoid adding runtime dependencies unless the benefit is substantial and the licensing, security, and packaging consequences are documented.

## Style

Keep the code direct and explicit. The project intentionally avoids a large framework stack. Public behavior should be documented in the README or the appropriate file under `docs/`.

## Commit and pull-request scope

A focused pull request is easier to review than a large refactor mixed with feature work. Include:

- the motivation;
- the affected Typst and/or OOXML constructs;
- tests;
- documentation changes where user-visible behavior changes.

By contributing, you agree that your contribution is licensed under the repository's MIT License.
