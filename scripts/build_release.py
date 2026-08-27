from __future__ import annotations

import hashlib
import re
import shutil
import zipfile
from pathlib import Path

from build_zipapp import main as build_zipapp


ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
FIXED_TIME = (2000, 1, 1, 0, 0, 0)
TOP_LEVEL_FILES = {
    ".gitignore",
    "ACKNOWLEDGMENTS.md",
    "CHANGELOG.md",
    "LICENSE",
    "README.md",
    "THIRD_PARTY_NOTICES.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "SUPPORT.md",
    ".editorconfig",
    ".gitattributes",
    "pyproject.toml",
}
SOURCE_DIRS = {".github", "docs", "examples", "mapping", "scripts", "src", "tests"}


def _version() -> str:
    text = (ROOT / "src" / "typx" / "constants.py").read_text(encoding="utf-8")
    match = re.search(r'^VERSION\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if not match:
        raise RuntimeError("VERSION not found in src/typx/constants.py")
    return match.group(1)


def _source_files() -> list[Path]:
    files: list[Path] = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(ROOT)
        if relative.name in {".DS_Store"} or relative.suffix in {".pyc", ".pyo"}:
            continue
        if (
            "__pycache__" in relative.parts
            or ".qa" in relative.parts
            or "dist" in relative.parts
            or "build" in relative.parts
            or any(part.endswith(".egg-info") for part in relative.parts)
        ):
            continue
        if len(relative.parts) == 1:
            if relative.as_posix() in TOP_LEVEL_FILES:
                files.append(path)
        elif relative.parts[0] in SOURCE_DIRS:
            files.append(path)
    return sorted(files, key=lambda item: item.relative_to(ROOT).as_posix())


def _info(name: str, mode: int = 0o644) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, FIXED_TIME)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = (mode & 0xFFFF) << 16
    return info


def _mode(relative: Path) -> int:
    if relative.as_posix() == "scripts/typx" or relative.suffix == ".py":
        return 0o755 if relative.parts and relative.parts[0] == "scripts" else 0o644
    return 0o644


def _write_source_zip(path: Path, prefix: str, files: list[Path], extras: dict[str, bytes] | None = None) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for source in files:
            relative = source.relative_to(ROOT)
            archive.writestr(_info(f"{prefix}/{relative.as_posix()}", _mode(relative)), source.read_bytes())
        for relative, data in sorted((extras or {}).items()):
            archive.writestr(_info(f"{prefix}/{relative}", 0o755 if relative.endswith(".pyz") else 0o644), data)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    version = _version()
    prefix = f"typx-{version}"
    DIST.mkdir(parents=True, exist_ok=True)
    build_zipapp()

    generic_pyz = DIST / "typx.pyz"
    versioned_pyz = DIST / f"{prefix}.pyz"
    shutil.copyfile(generic_pyz, versioned_pyz)
    try:
        versioned_pyz.chmod(0o755)
    except OSError:
        pass

    files = _source_files()
    source_zip = DIST / f"{prefix}-source.zip"
    _write_source_zip(source_zip, prefix, files)

    preliminary = {
        versioned_pyz.name: _sha256(versioned_pyz),
        source_zip.name: _sha256(source_zip),
    }
    embedded_checksums = "".join(f"{digest}  {name}\n" for name, digest in sorted(preliminary.items())).encode("utf-8")
    bundle_zip = DIST / f"{prefix}-bundle.zip"
    _write_source_zip(
        bundle_zip,
        prefix,
        files,
        {
            f"dist/{versioned_pyz.name}": versioned_pyz.read_bytes(),
            "dist/SHA256SUMS.txt": embedded_checksums,
        },
    )

    checksums = {
        versioned_pyz.name: _sha256(versioned_pyz),
        source_zip.name: _sha256(source_zip),
        bundle_zip.name: _sha256(bundle_zip),
    }
    (DIST / "SHA256SUMS.txt").write_text(
        "".join(f"{digest}  {name}\n" for name, digest in sorted(checksums.items())),
        encoding="utf-8",
        newline="\n",
    )
    print(versioned_pyz)
    print(source_zip)
    print(bundle_zip)
    print(DIST / "SHA256SUMS.txt")


if __name__ == "__main__":
    main()
