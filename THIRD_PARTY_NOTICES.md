# Third-party notices

`typx` has no third-party runtime dependencies. It uses only the Python standard library.

The project refers to, but does not bundle, the following specifications and documentation:

1. Typst documentation and source repository, licensed under their respective published terms.
2. ECMA-376 / ISO/IEC 29500 Office Open XML specifications.
3. Microsoft Open Specifications documentation for Word extensions.

No font files, Microsoft Office binaries, LibreOffice binaries, Typst binaries, schemas, or third-party Python packages are redistributed in this repository.

At conversion time, the DOCX-to-Typst path can copy font programs that are embedded in the user's DOCX or installed on the user's own system into that conversion's local asset directory. Those runtime-generated copies are user-controlled outputs, are not included in typx release/test archives, and remain subject to the font copyright holder's embedding and redistribution terms.

Build and publication tooling referenced by the repository includes setuptools and official GitHub Actions. Those tools remain subject to their own licenses and are not redistributed as part of the dependency-free `typx.pyz` runtime.
