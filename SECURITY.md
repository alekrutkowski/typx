# Security policy

## Supported versions

During the alpha phase, security fixes are applied to the current development branch and the most recent tagged release when practical.

## Reporting a vulnerability

Please do not open a public issue for a vulnerability that could expose users to malicious DOCX packages, unsafe path handling, external-resource execution, or similar security problems.

Report security issues privately to:

**Alek Rutkowski**  
**alek.rutkowski@gmail.com**

Include a minimal reproducer if it is safe to share, the affected version, and the expected impact.

## Security-sensitive areas

Particular care is required around:

- ZIP path traversal and decompression limits;
- XML entity and DTD handling;
- relationship target resolution;
- local Typst include and asset paths;
- preservation of opaque OOXML;
- external relationships and embedded executable content.

`typx` is designed not to execute macros, OLE objects, ActiveX, arbitrary Typst code, or external DOCX relationships.
