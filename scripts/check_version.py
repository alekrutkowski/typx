from __future__ import annotations

import argparse
import re
import sys
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONSTANTS = ROOT / "src" / "typx" / "constants.py"
PYPROJECT = ROOT / "pyproject.toml"


def source_version() -> str:
    text = CONSTANTS.read_text(encoding="utf-8")
    match = re.search(r'^VERSION\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if not match:
        raise RuntimeError(f"VERSION not found in {CONSTANTS}")
    return match.group(1)


def project_version() -> str:
    with PYPROJECT.open("rb") as handle:
        data = tomllib.load(handle)
    return str(data["project"]["version"])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check typx version metadata and optional Git tag.")
    parser.add_argument("--tag", help="Require this tag to equal v<project-version>.")
    parser.add_argument("--print-version", action="store_true", help="Print only the validated version.")
    args = parser.parse_args(argv)

    source = source_version()
    project = project_version()
    if source != project:
        print(
            f"Version mismatch: src/typx/constants.py has {source!r}, "
            f"pyproject.toml has {project!r}.",
            file=sys.stderr,
        )
        return 1

    if args.tag is not None:
        expected = f"v{project}"
        if args.tag != expected:
            print(f"Tag mismatch: expected {expected!r}, got {args.tag!r}.", file=sys.stderr)
            return 1

    if args.print_version:
        print(project)
    else:
        suffix = f"; tag {args.tag} matches" if args.tag is not None else ""
        print(f"Version metadata is consistent: {project}{suffix}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
