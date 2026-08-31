from __future__ import annotations

import hashlib
from pathlib import Path

from build_zipapp import main as build_zipapp


ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _remove_old_release_artifacts() -> None:
    """Remove outputs produced by current and older typx release builders."""
    DIST.mkdir(parents=True, exist_ok=True)
    patterns = (
        "typx.pyz",
        "typx-*.pyz",
        "typx-*-source.zip",
        "typx-*-bundle.zip",
        "SHA256SUMS.txt",
    )
    for pattern in patterns:
        for path in DIST.glob(pattern):
            if path.is_file():
                path.unlink()


def main() -> None:
    _remove_old_release_artifacts()
    build_zipapp()

    pyz = DIST / "typx.pyz"
    digest = _sha256(pyz)
    manifest = DIST / "SHA256SUMS.txt"
    manifest.write_text(f"{digest}  {pyz.name}\n", encoding="utf-8")

    print(f"Built rolling release artifact: {pyz}")
    print(f"{digest}  {pyz.name}")
    print(manifest)


if __name__ == "__main__":
    main()
