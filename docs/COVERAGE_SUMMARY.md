# Coverage summary

This summary describes the 442 rows in the full directional matrix. Counts are mapping rows, not a claim that every row has identical complexity or test depth. The authoritative row-level detail is in [`mapping/MAPPING.md`](../mapping/MAPPING.md).

## Baselines

| Side | Baseline |
|---|---|
| Typst | 0.15.1 |
| OOXML | ECMA-376 5th edition / ISO/IEC 29500 family |
| Microsoft Word extensions | MS-DOCX 23.0 |

## Implementation status by direction

| Status | Typst to DOCX | DOCX to Typst |
|---|---:|---:|
| `full` | 125 | 196 |
| `partial` | 287 | 65 |
| `preserve` | 13 | 50 |
| `none` | 17 | 131 |

## Conceptual fidelity by direction

| Fidelity | Typst to DOCX | DOCX to Typst |
|---|---:|---:|
| `exact` | 21 | 22 |
| `high` | 176 | 162 |
| `approximate` | 93 | 92 |
| `preserve` | 32 | 35 |
| `evaluate` | 104 | 0 |
| `none` | 16 | 131 |

## Rows by category

| Category | Rows |
|---|---:|
| DOCX-specific | 133 |
| Text formatting | 36 |
| Foundations / values | 35 |
| Language / code | 32 |
| Page and layout | 27 |
| Document model | 24 |
| Language / markup | 20 |
| Mathematics | 20 |
| Introspection | 18 |
| Visualize | 16 |
| Paragraph formatting | 14 |
| Foundations / functions | 12 |
| Layout / reference inventory | 10 |
| Document model / reference inventory | 9 |
| Data loading | 8 |
| Export-specific | 7 |
| Mathematics / reference inventory | 7 |
| Export / reference inventory | 7 |
| Text / reference inventory | 5 |
| Symbols | 2 |

## Reading the counts

- `full` means native parsing and emission are implemented for the row as defined.
- `partial` means a common or statically provable subset is implemented.
- `preserve` means counterpart data survives through raw fragments or exact-round-trip payloads, but is not natively transformed.
- `none` means no semantic transformation is implemented in that direction.
- `evaluate` in the fidelity columns identifies Typst code or Word behavior that requires a language, field, or layout engine.
