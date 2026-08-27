## Summary

Describe the change and the conversion or packaging problem it addresses.

## Affected constructs

List the relevant Typst syntax, OOXML elements, or CLI behavior.

## Verification

- [ ] `python -m compileall -q src tests scripts`
- [ ] `PYTHONPATH=src python -m unittest discover -s tests -v`
- [ ] `python scripts/build_release.py`
- [ ] `python scripts/verify_release.py`
- [ ] User-facing documentation updated where needed
- [ ] Mapping entries updated where needed
