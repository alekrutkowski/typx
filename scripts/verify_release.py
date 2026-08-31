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

    pyz = DIST / "typx.pyz"
    manifest = DIST / "SHA256SUMS.txt"

    expected = [pyz, manifest]
    missing = [str(path) for path in expected if not path.is_file()]
    if missing:
        raise RuntimeError(f"Missing release artifacts: {missing}")

    recorded = checksum_manifest(manifest)
    if set(recorded) != {pyz.name}:
        raise RuntimeError(
            "SHA256SUMS.txt must contain exactly one entry for typx.pyz; "
            f"found {sorted(recorded)}"
        )

    actual = sha256(pyz)
    wanted = recorded[pyz.name]
    if wanted != actual:
        raise RuntimeError(
            f"SHA-256 mismatch for {pyz.name}: manifest={wanted!r}, actual={actual!r}"
        )

    require_zip_members(
        pyz,
        {
            "__main__.py",
            "typx/cli.py",
            "typx/constants.py",
        },
    )

    result = subprocess.run(
        [sys.executable, str(pyz), "--version"],
        check=True,
        capture_output=True,
        text=True,
    )
    if version not in result.stdout:
        raise RuntimeError(
            f"Zip application version output does not contain {version!r}: {result.stdout!r}"
        )

    print(f"Verified typx {version} rolling release artifact")
    print(f"{actual}  {pyz.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
