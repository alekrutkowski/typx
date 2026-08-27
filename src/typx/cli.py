from __future__ import annotations

import argparse
import json
import os
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import asdict, fields
from pathlib import Path
from typing import Any, Iterable, Sequence

from .constants import APP_NAME, OOXML_BASELINE, TYPST_BASELINE, VERSION
from .docx_package import DocxPackage
from .docx_reader import DocxReadOptions, DocxReader
from .docx_writer import DocxWriteOptions, DocxWriter
from .mapping import MAPPING, SOURCES, as_csv, as_json, as_markdown
from .model import (
    Change,
    CommentAnchor,
    ContentControl,
    Document,
    Field,
    Figure,
    Heading,
    Inline,
    Link,
    ListBlock,
    MathInline,
    NoteRef,
    Paragraph,
    RawBlock,
    RawInline,
    Table,
    as_serializable,
)
from .roundtrip import extract_docx_from_typst, extract_typst_from_docx
from .typst_reader import TypstReadOptions, TypstReader
from .typst_writer import TypstWriteOptions, TypstWriter


class TypxError(RuntimeError):
    """A user-facing conversion or validation error."""


def _json_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _eprint(*values: object) -> None:
    print(*values, file=sys.stderr)


def _infer_format(path: Path, explicit: str | None = None) -> str:
    if explicit:
        return explicit
    suffix = path.suffix.lower()
    if suffix == ".typ":
        return "typst"
    if suffix == ".docx":
        return "docx"
    raise TypxError(
        f"cannot infer the format of {path}; use --from or --to with typst or docx"
    )


def _default_output(input_path: Path, target_format: str) -> Path:
    return input_path.with_suffix(".typ" if target_format == "typst" else ".docx")


def _ensure_output(path: Path, force: bool) -> None:
    if path.exists() and not force:
        raise TypxError(f"output already exists: {path} (use --force to replace it)")
    path.parent.mkdir(parents=True, exist_ok=True)


def _write_text(path: Path, text: str, force: bool) -> None:
    _ensure_output(path, force)
    path.write_text(text, encoding="utf-8", newline="\n")


def _write_bytes(path: Path, data: bytes, force: bool) -> None:
    _ensure_output(path, force)
    path.write_bytes(data)


def _convert_docx_to_typst(args: argparse.Namespace, source: Path, output: Path) -> dict[str, Any]:
    docx_bytes = source.read_bytes()
    package = DocxPackage.open(docx_bytes)
    embedded = extract_typst_from_docx(package)

    if args.roundtrip in {"auto", "exact"} and embedded is not None:
        unchanged = embedded.package_unchanged(package)
        if unchanged:
            _write_text(output, embedded.source, args.force)
            return {
                "input": str(source),
                "output": str(output),
                "from": "docx",
                "to": "typst",
                "mode": "exact",
                "bytes": len(embedded.source.encode("utf-8")),
                "warnings": [],
            }
        if args.roundtrip == "exact":
            raise TypxError(
                "the embedded Typst source exists, but the DOCX semantic digest changed; "
                "exact recovery is unsafe"
            )
    elif args.roundtrip == "exact":
        raise TypxError("the DOCX contains no typx exact-roundtrip Typst source")

    comments = "drop" if args.no_comments else "preserve"
    assets_dir = Path(args.assets_dir).resolve() if args.assets_dir else None
    read_options = DocxReadOptions(
        revisions=args.revisions,
        comments=comments,
        unknown=args.unknown,
        extract_assets=not args.no_assets,
        assets_dir=assets_dir,
        preserve_package_parts=False,
    )
    document = DocxReader(package, read_options).parse()
    write_options = TypstWriteOptions(
        output_path=output,
        assets_dir=assets_dir,
        preserve_raw=args.unknown == "preserve",
        preserve_comments=not args.no_comments,
        materialize_assets=not args.no_assets,
    )
    body = TypstWriter(document, write_options).write()

    embed = args.roundtrip != "off" and not args.no_embed
    if embed:
        from .roundtrip import embed_docx_in_typst

        body = embed_docx_in_typst(
            body,
            docx_bytes,
            {
                "source-name": source.name,
                "typst-baseline": TYPST_BASELINE,
                "ooxml-baseline": OOXML_BASELINE,
            },
        )
    _write_text(output, body, args.force)
    return {
        "input": str(source),
        "output": str(output),
        "from": "docx",
        "to": "typst",
        "mode": "semantic+payload" if embed else "semantic",
        "bytes": len(body.encode("utf-8")),
        "resources": len(document.resources),
        "warnings": document.warnings,
    }


def _convert_typst_to_docx(args: argparse.Namespace, source: Path, output: Path) -> dict[str, Any]:
    source_text = source.read_text(encoding="utf-8")
    payload = extract_docx_from_typst(source_text)
    if args.roundtrip in {"auto", "exact"} and payload is not None:
        if payload.unchanged:
            _write_bytes(output, payload.payload, args.force)
            return {
                "input": str(source),
                "output": str(output),
                "from": "typst",
                "to": "docx",
                "mode": "exact",
                "bytes": len(payload.payload),
                "warnings": [],
            }
        if args.roundtrip == "exact":
            raise TypxError(
                "the Typst round-trip payload exists, but the generated Typst body changed; "
                "exact DOCX recovery is unsafe"
            )
    elif args.roundtrip == "exact":
        raise TypxError("the Typst file contains no typx exact-roundtrip DOCX payload")

    read_options = TypstReadOptions(
        root=source.parent,
        resolve_includes=not args.no_includes,
        load_assets=not args.no_assets,
        unknown=args.unknown,
    )
    document = TypstReader(source_text, source, read_options).parse()
    document.source_format = "typst"
    document.source_text = source_text
    document.source_path = str(source)
    writer_options = DocxWriteOptions(
        output_path=output,
        preserve_raw=args.unknown == "preserve",
        preserve_comments=not args.no_comments,
        preserve_revisions=args.revisions == "preserve",
        embed_typst_source=args.roundtrip != "off" and not args.no_embed,
        missing_assets="error" if args.missing_assets == "error" else "placeholder",
    )
    data = DocxWriter(document, writer_options).build()
    _write_bytes(output, data, args.force)
    return {
        "input": str(source),
        "output": str(output),
        "from": "typst",
        "to": "docx",
        "mode": "semantic+payload" if writer_options.embed_typst_source else "semantic",
        "bytes": len(data),
        "resources": len(document.resources),
        "warnings": document.warnings,
    }


def command_convert(args: argparse.Namespace) -> int:
    source = Path(args.input).expanduser().resolve()
    if not source.is_file():
        raise TypxError(f"input file does not exist: {source}")
    source_format = _infer_format(source, args.source_format)
    target_format = args.target_format or ("docx" if source_format == "typst" else "typst")
    if source_format == target_format:
        raise TypxError("source and target formats must differ")
    output = (
        Path(args.output).expanduser().resolve()
        if args.output
        else _default_output(source, target_format)
    )
    if output == source:
        raise TypxError("input and output paths must differ")

    if source_format == "docx" and target_format == "typst":
        result = _convert_docx_to_typst(args, source, output)
    elif source_format == "typst" and target_format == "docx":
        result = _convert_typst_to_docx(args, source, output)
    else:
        raise TypxError(f"unsupported conversion: {source_format} to {target_format}")

    if args.json:
        sys.stdout.write(_json_dump(result))
    elif not args.quiet:
        warning_suffix = f"; {len(result['warnings'])} warning(s)" if result.get("warnings") else ""
        _eprint(
            f"{APP_NAME}: {result['mode']} conversion wrote {result['output']} "
            f"({result['bytes']} bytes{warning_suffix})"
        )
        for warning in result.get("warnings", []):
            _eprint(f"{APP_NAME}: warning: {warning}")
    return 0


def _walk_inlines(items: Iterable[Inline]) -> Iterable[Inline]:
    for item in items:
        yield item
        if isinstance(item, (Link, Field, Change)):
            yield from _walk_inlines(item.children)
        elif isinstance(item, RawInline):
            yield from _walk_inlines(item.fallback)


def _document_stats(document: Document) -> dict[str, Any]:
    block_counts: Counter[str] = Counter()
    inline_counts: Counter[str] = Counter()
    for block in document.walk_blocks():
        block_counts[type(block).__name__] += 1
        inline_items: list[Inline] = []
        if isinstance(block, (Paragraph, Heading)):
            inline_items = block.inlines
        elif isinstance(block, Figure):
            inline_items = block.caption
        for inline in _walk_inlines(inline_items):
            inline_counts[type(inline).__name__] += 1
    return {
        "source_format": document.source_format,
        "metadata": as_serializable(document.metadata),
        "blocks": dict(sorted(block_counts.items())),
        "inlines": dict(sorted(inline_counts.items())),
        "sections": len(document.sections),
        "styles": len(document.styles),
        "resources": len(document.resources),
        "resource_bytes": sum(len(resource.data or b"") for resource in document.resources.values()),
        "comments": len(document.comments),
        "footnotes": len(document.footnotes),
        "endnotes": len(document.endnotes),
        "warnings": document.warnings,
    }


def _inspect_typst(path: Path, deep: bool) -> dict[str, Any]:
    source = path.read_text(encoding="utf-8")
    payload = extract_docx_from_typst(source)
    result: dict[str, Any] = {
        "path": str(path),
        "format": "typst",
        "size": path.stat().st_size,
        "line_count": source.count("\n") + (0 if source.endswith("\n") else 1),
        "roundtrip": {
            "embedded_docx": payload is not None,
            "counterpart_unchanged": payload.unchanged if payload else None,
            "embedded_bytes": len(payload.payload) if payload else 0,
        },
    }
    if deep:
        document = TypstReader(
            source,
            path,
            TypstReadOptions(root=path.parent, resolve_includes=True, load_assets=False),
        ).parse()
        result["document"] = _document_stats(document)
    return result


def _inspect_docx(path: Path, deep: bool) -> dict[str, Any]:
    package = DocxPackage.open(path)
    embedded = extract_typst_from_docx(package)
    result: dict[str, Any] = {
        "path": str(path),
        "format": "docx",
        "size": path.stat().st_size,
        "parts": len(package.parts),
        "main_part": package.office_document_part(),
        "content_types": len(package.content_types.defaults) + len(package.content_types.overrides),
        "roundtrip": {
            "embedded_typst": embedded is not None,
            "counterpart_unchanged": embedded.package_unchanged(package) if embedded else None,
            "source_bytes": len(embedded.source.encode("utf-8")) if embedded else 0,
        },
    }
    if deep:
        document = DocxReader(
            package,
            DocxReadOptions(extract_assets=False, preserve_package_parts=False),
        ).parse()
        result["document"] = _document_stats(document)
    return result


def _human_inspect(result: dict[str, Any]) -> str:
    lines = [
        f"Path: {result['path']}",
        f"Format: {result['format']}",
        f"Size: {result['size']} bytes",
    ]
    if result["format"] == "docx":
        lines.extend([
            f"Parts: {result['parts']}",
            f"Main part: {result['main_part']}",
        ])
    else:
        lines.append(f"Lines: {result['line_count']}")
    roundtrip = result["roundtrip"]
    if result["format"] == "docx":
        lines.append(f"Embedded Typst source: {'yes' if roundtrip['embedded_typst'] else 'no'}")
    else:
        lines.append(f"Embedded DOCX payload: {'yes' if roundtrip['embedded_docx'] else 'no'}")
    if roundtrip["counterpart_unchanged"] is not None:
        lines.append(f"Exact counterpart eligible: {'yes' if roundtrip['counterpart_unchanged'] else 'no'}")
    document = result.get("document")
    if document:
        lines.extend([
            f"Sections: {document['sections']}",
            f"Styles: {document['styles']}",
            f"Resources: {document['resources']} ({document['resource_bytes']} bytes)",
            f"Comments / footnotes / endnotes: {document['comments']} / {document['footnotes']} / {document['endnotes']}",
            "Blocks: " + ", ".join(f"{key}={value}" for key, value in document["blocks"].items()),
            "Inlines: " + ", ".join(f"{key}={value}" for key, value in document["inlines"].items()),
        ])
        for warning in document.get("warnings", []):
            lines.append(f"Warning: {warning}")
    return "\n".join(lines) + "\n"


def command_inspect(args: argparse.Namespace) -> int:
    path = Path(args.input).expanduser().resolve()
    if not path.is_file():
        raise TypxError(f"input file does not exist: {path}")
    file_format = _infer_format(path, args.source_format)
    result = _inspect_docx(path, args.deep) if file_format == "docx" else _inspect_typst(path, args.deep)
    sys.stdout.write(_json_dump(result) if args.json else _human_inspect(result))
    return 0


def _validate_docx(path: Path, deep: bool) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    package: DocxPackage | None = None
    try:
        package = DocxPackage.open(path)
    except Exception as exc:  # noqa: BLE001 - converted to a validation diagnostic
        errors.append(str(exc))
    if package is None:
        return {"path": str(path), "format": "docx", "valid": False, "errors": errors, "warnings": warnings}

    for name, data in package.parts.items():
        if name.lower().endswith((".xml", ".rels")) or name == "[Content_Types].xml":
            try:
                ET.fromstring(data)
            except ET.ParseError as exc:
                errors.append(f"malformed XML in /{name}: {exc}")

    try:
        main_part = package.office_document_part()
        if main_part not in package.parts:
            errors.append(f"officeDocument target is missing: /{main_part}")
    except Exception as exc:  # noqa: BLE001
        errors.append(str(exc))
        main_part = None

    sources = [""] + [
        name for name in package.parts
        if not name.endswith(".rels") and name != "[Content_Types].xml"
    ]
    relationship_count = 0
    for source in sources:
        try:
            relationships = package.relationships(source)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"cannot parse relationships for /{source}: {exc}")
            continue
        relationship_count += len(relationships)
        seen_ids: set[str] = set()
        for rel in relationships.values():
            if not rel.id:
                errors.append(f"relationship without Id in /{source or '_rels/.rels'}")
            elif rel.id in seen_ids:
                errors.append(f"duplicate relationship Id {rel.id!r} in /{source or '_rels/.rels'}")
            seen_ids.add(rel.id)
            if not rel.external and rel.resolved_target not in package.parts:
                errors.append(
                    f"missing relationship target /{rel.resolved_target} "
                    f"from /{source or '_rels/.rels'} ({rel.id})"
                )

    for name in package.parts:
        if name == "[Content_Types].xml" or name.endswith(".rels"):
            continue
        if package.content_types.for_part(name) is None:
            warnings.append(f"no content type declared for /{name}")

    document_stats: dict[str, Any] | None = None
    if deep and not errors:
        try:
            document = DocxReader(
                package,
                DocxReadOptions(extract_assets=False, preserve_package_parts=False),
            ).parse()
            document_stats = _document_stats(document)
            warnings.extend(document.warnings)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"semantic parse failed: {exc}")

    return {
        "path": str(path),
        "format": "docx",
        "valid": not errors,
        "parts": len(package.parts),
        "relationships": relationship_count,
        "main_part": main_part,
        "errors": errors,
        "warnings": warnings,
        "document": document_stats,
    }


def _validate_typst(path: Path, deep: bool) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    document_stats: dict[str, Any] | None = None
    source = ""
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        errors.append(str(exc))
    if not errors:
        try:
            document = TypstReader(
                source,
                path,
                TypstReadOptions(
                    root=path.parent,
                    resolve_includes=deep,
                    load_assets=deep,
                    unknown="preserve",
                ),
            ).parse()
            document_stats = _document_stats(document)
            warnings.extend(document.warnings)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"static Typst parse failed: {exc}")
    return {
        "path": str(path),
        "format": "typst",
        "valid": not errors,
        "scope": "typx static-language validation, not full Typst compiler validation",
        "errors": errors,
        "warnings": warnings,
        "document": document_stats,
    }


def command_validate(args: argparse.Namespace) -> int:
    path = Path(args.input).expanduser().resolve()
    if not path.is_file():
        raise TypxError(f"input file does not exist: {path}")
    file_format = _infer_format(path, args.source_format)
    result = _validate_docx(path, args.deep) if file_format == "docx" else _validate_typst(path, args.deep)
    if args.json:
        sys.stdout.write(_json_dump(result))
    else:
        status = "valid" if result["valid"] else "invalid"
        print(f"{path}: {status} {file_format}")
        for warning in result.get("warnings", []):
            print(f"warning: {warning}")
        for error in result.get("errors", []):
            print(f"error: {error}")
    return 0 if result["valid"] else 1


def _filtered_mapping(category: str | None, query: str | None) -> list[Any]:
    entries = list(MAPPING)
    if category:
        folded = category.casefold()
        entries = [entry for entry in entries if entry.category.casefold() == folded]
    if query:
        folded = query.casefold()
        entries = [
            entry for entry in entries
            if folded in " ".join(str(value) for value in asdict(entry).values()).casefold()
        ]
    return entries


def _mapping_payload(entries: list[Any], output_format: str) -> str:
    if len(entries) == len(MAPPING):
        if output_format == "json":
            return as_json()
        if output_format == "csv":
            return as_csv()
        return as_markdown()
    if output_format == "json":
        return _json_dump({
            "schema": "typx-mapping-v1",
            "typst_baseline": TYPST_BASELINE,
            "ooxml_baseline": OOXML_BASELINE,
            "entry_count": len(entries),
            "sources": SOURCES,
            "entries": [as_serializable(entry) for entry in entries],
        })
    if output_format == "csv":
        import csv
        import io
        from dataclasses import asdict

        stream = io.StringIO(newline="")
        fieldnames = list(entries[0].__dataclass_fields__) if entries else list(MAPPING[0].__dataclass_fields__)
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        for entry in entries:
            writer.writerow(asdict(entry))
        return stream.getvalue()
    lines = [
        "# Filtered Typst ↔ DOCX mapping",
        "",
        f"Rows: {len(entries)}",
        "",
        "| ID | Category | Typst construct | DOCX counterpart | T→D | D→T |",
        "|---|---|---|---|---|---|",
    ]
    for entry in entries:
        esc = lambda value: str(value).replace("|", "\\|").replace("\n", " ")
        lines.append(
            "| " + " | ".join(esc(value) for value in (
                entry.id,
                entry.category,
                entry.typst,
                entry.docx,
                entry.typst_to_docx,
                entry.docx_to_typst,
            )) + " |"
        )
    return "\n".join(lines) + "\n"


def command_mapping(args: argparse.Namespace) -> int:
    entries = _filtered_mapping(args.category, args.query)
    payload = _mapping_payload(entries, args.format)
    if args.output:
        output = Path(args.output).expanduser().resolve()
        _write_text(output, payload, args.force)
        if not args.quiet:
            _eprint(f"{APP_NAME}: wrote {len(entries)} mapping rows to {output}")
    else:
        sys.stdout.write(payload)
    return 0


def command_dump_ir(args: argparse.Namespace) -> int:
    path = Path(args.input).expanduser().resolve()
    if not path.is_file():
        raise TypxError(f"input file does not exist: {path}")
    file_format = _infer_format(path, args.source_format)
    if file_format == "docx":
        document = DocxReader.read(
            path,
            DocxReadOptions(
                revisions=args.revisions,
                comments="drop" if args.no_comments else "preserve",
                unknown=args.unknown,
                extract_assets=False,
            ),
        )
    else:
        document = TypstReader.read(
            path,
            TypstReadOptions(root=path.parent, load_assets=False, unknown=args.unknown),
        )
    payload = _json_dump(as_serializable(document))
    if args.output:
        _write_text(Path(args.output).expanduser().resolve(), payload, args.force)
    else:
        sys.stdout.write(payload)
    return 0


def _add_common_input_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--from", dest="source_format", choices=("typst", "docx"), help="override input format detection")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=APP_NAME,
        description=(
            "Bidirectional static converter between Typst source and DOCX, with raw-fragment "
            "preservation and exact counterpart recovery."
        ),
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    subparsers = parser.add_subparsers(dest="command")

    convert = subparsers.add_parser("convert", help="convert .typ to .docx or .docx to .typ")
    convert.add_argument("input", help="input .typ or .docx file")
    convert.add_argument("output", nargs="?", help="output path; defaults to the opposite extension")
    _add_common_input_options(convert)
    convert.add_argument("--to", dest="target_format", choices=("typst", "docx"), help="override output format detection")
    convert.add_argument(
        "--roundtrip",
        choices=("auto", "exact", "semantic", "off"),
        default="auto",
        help=(
            "auto restores an eligible exact counterpart, exact requires one, semantic always "
            "transpiles, and off also disables counterpart embedding"
        ),
    )
    convert.add_argument("--revisions", choices=("accept", "reject", "annotate", "preserve"), default="annotate")
    convert.add_argument("--unknown", choices=("preserve", "drop"), default="preserve")
    convert.add_argument("--assets-dir", help="directory for assets extracted beside Typst output")
    convert.add_argument("--no-assets", action="store_true", help="do not load or materialize external assets")
    convert.add_argument("--no-includes", action="store_true", help="do not resolve static Typst include statements")
    convert.add_argument("--no-comments", action="store_true", help="drop Word comments and converter comment metadata")
    convert.add_argument("--no-embed", action="store_true", help="do not embed the source counterpart for later exact recovery")
    convert.add_argument("--missing-assets", choices=("placeholder", "error"), default="placeholder")
    convert.add_argument("--force", action="store_true", help="replace an existing output file")
    convert.add_argument("--json", action="store_true", help="emit a machine-readable result")
    convert.add_argument("--quiet", action="store_true", help="suppress normal status output")
    convert.set_defaults(func=command_convert)

    inspect_parser = subparsers.add_parser("inspect", help="report package, document, and round-trip information")
    inspect_parser.add_argument("input")
    _add_common_input_options(inspect_parser)
    inspect_parser.add_argument("--deep", action="store_true", help="parse the document into the shared model")
    inspect_parser.add_argument("--json", action="store_true")
    inspect_parser.set_defaults(func=command_inspect)

    validate = subparsers.add_parser("validate", help="validate OPC/XML structure and the converter's static parse")
    validate.add_argument("input")
    _add_common_input_options(validate)
    validate.add_argument("--deep", action="store_true", help="also run semantic parsing and asset/include checks")
    validate.add_argument("--json", action="store_true")
    validate.set_defaults(func=command_validate)

    mapping = subparsers.add_parser("mapping", help="print or export the Typst ↔ DOCX coverage matrix")
    mapping.add_argument("--format", choices=("markdown", "json", "csv"), default="markdown")
    mapping.add_argument("--category", help="retain one exact category name")
    mapping.add_argument("--query", help="case-insensitive search across mapping fields")
    mapping.add_argument("--output", help="write to a file instead of standard output")
    mapping.add_argument("--force", action="store_true")
    mapping.add_argument("--quiet", action="store_true")
    mapping.set_defaults(func=command_mapping)

    dump_ir = subparsers.add_parser("dump-ir", help="serialize the shared document model as JSON")
    dump_ir.add_argument("input")
    _add_common_input_options(dump_ir)
    dump_ir.add_argument("--output")
    dump_ir.add_argument("--revisions", choices=("accept", "reject", "annotate", "preserve"), default="annotate")
    dump_ir.add_argument("--unknown", choices=("preserve", "drop"), default="preserve")
    dump_ir.add_argument("--no-comments", action="store_true")
    dump_ir.add_argument("--force", action="store_true")
    dump_ir.set_defaults(func=command_dump_ir)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    commands = {"convert", "inspect", "validate", "mapping", "dump-ir"}
    if arguments and arguments[0] not in commands and not arguments[0].startswith("-"):
        arguments.insert(0, "convert")
    parser = build_parser()
    if not arguments:
        parser.print_help(sys.stderr)
        return 2
    args = parser.parse_args(arguments)
    if not hasattr(args, "func"):
        parser.print_help(sys.stderr)
        return 2
    try:
        return int(args.func(args))
    except TypxError as exc:
        _eprint(f"{APP_NAME}: error: {exc}")
        return 1
    except KeyboardInterrupt:
        _eprint(f"{APP_NAME}: interrupted")
        return 130
    except BrokenPipeError:
        try:
            sys.stdout.close()
        except OSError:
            pass
        return 0
    except Exception as exc:  # noqa: BLE001 - CLI boundary
        if os.environ.get("TYPX_DEBUG"):
            raise
        _eprint(f"{APP_NAME}: error: {exc}")
        return 1


__all__ = ["build_parser", "main"]
