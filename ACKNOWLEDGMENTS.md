# Acknowledgments

This project was designed from the public Typst reference, ECMA-376 / ISO/IEC 29500, and Microsoft Open Specifications documentation.

- Typst language and documentation: https://typst.app/docs/reference/
- Typst source and release history: https://github.com/typst/typst
- ECMA-376 Office Open XML: https://ecma-international.org/publications-and-standards/standards/ecma-376/
- Microsoft Word extensions to OOXML: https://learn.microsoft.com/en-us/openspecs/office_standards/ms-docx/b839fe1f-e1ca-4fa6-8c26-5954d0abbccd

Typst is a trademark of its respective owners. Microsoft Word is a trademark of Microsoft Corporation. This independent converter is not affiliated with or endorsed by Typst GmbH, Ecma International, ISO, IEC, or Microsoft.

## Build and automation tooling

The source distribution declares setuptools as its Python build backend. GitHub-hosted automation uses the official `actions/checkout`, `actions/setup-python`, and `actions/upload-artifact` actions plus the GitHub CLI available on GitHub-hosted runners. These tools are build or automation dependencies only and are not bundled into the `typx` runtime.
