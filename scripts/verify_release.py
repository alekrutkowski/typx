from __future__ import annotations

import hashlib
import subprocess
import sys
import zipfile
from pathlib import Path

from check_version import project_version, source_version


ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def checksum_manifest(path: Path) -> dict[str, str]:
    entries: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        digest, name = line.split(None, 1)
        entries[name.strip()] = digest
    return entries


def require_zip_members(path: Path, required: set[str]) -> None:
    with zipfile.ZipFile(path, "r") as archive:
        bad = archive.testzip()
        if bad is not None:
            raise RuntimeError(f"Corrupt ZIP member {bad!r} in {path}")
        names = set(archive.namelist())
    missing = sorted(required - names)
    if missing:
        raise RuntimeError(f"{path.name} is missing required members: {missing}")


def main() -> int:
    version = project_version()
    if version != source_version():
        raise RuntimeError("Version metadata does not match")

    prefix = f"typx-{version}"
    pyz = DIST / f"{prefix}.pyz"
    source_zip = DIST / f"{prefix}-source.zip"
    bundle_zip = DIST / f"{prefix}-bundle.zip"
    manifest = DIST / "SHA256SUMS.txt"

    expected = [pyz, source_zip, bundle_zip, manifest]
    missing = [str(path) for path in expected if not path.is_file()]
    if missing:
        raise RuntimeError(f"Missing release artifacts: {missing}")

    recorded = checksum_manifest(manifest)
    for path in (pyz, source_zip, bundle_zip):
        actual = sha256(path)
        wanted = recorded.get(path.name)
        if wanted != actual:
            raise RuntimeError(
                f"SHA-256 mismatch for {path.name}: manifest={wanted!r}, actual={actual!r}"
            )

    result = subprocess.run(
        [sys.executable, str(pyz), "--version"],
        check=True,
        capture_output=True,
        text=True,
    )
    if version not in result.stdout:
        raise RuntimeError(f"Zip application version output does not contain {version!r}: {result.stdout!r}")

    source_root = f"{prefix}/"
    require_zip_members(
        source_zip,
        {
            source_root + "README.md",
            source_root + "LICENSE",
            source_root + "pyproject.toml",
            source_root + "src/typx/cli.py",
            source_root + "tests/test_core.py",
            source_root + ".github/workflows/ci.yml",
            source_root + ".github/workflows/release.yml",
            source_root + "scripts/build_release.py",
            source_root + "scripts/verify_release.py",
        },
    )

    require_zip_members(
        bundle_zip,
        {
            source_root + "README.md",
            source_root + f"dist/{prefix}.pyz",
            source_root + "dist/SHA256SUMS.txt",
        },
    )

    with zipfile.ZipFile(source_zip, "r") as archive:
        if any(name.startswith(source_root + "dist/") for name in archive.namelist()):
            raise RuntimeError("Source ZIP unexpectedly contains dist/ artifacts")

    print(f"Verified typx {version} release artifacts")
    for path in (pyz, source_zip, bundle_zip):
        print(f"{sha256(path)}  {path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
