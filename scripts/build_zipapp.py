from __future__ import annotations

import io
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src"
OUTPUT = ROOT / "dist" / "typx.pyz"
FIXED_TIME = (2000, 1, 1, 0, 0, 0)
SHEBANG = b"#!/usr/bin/env python3\n"
MAIN = b"from typx.cli import main\nraise SystemExit(main())\n"


def _zip_info(name: str, mode: int = 0o644) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, FIXED_TIME)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = (mode & 0xFFFF) << 16
    return info


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        archive.writestr(_zip_info("__main__.py"), MAIN)
        for path in sorted((SOURCE / "typx").rglob("*.py")):
            relative = path.relative_to(SOURCE).as_posix()
            archive.writestr(_zip_info(relative), path.read_bytes())
    OUTPUT.write_bytes(SHEBANG + buffer.getvalue())
    try:
        OUTPUT.chmod(0o755)
    except OSError:
        pass
    print(OUTPUT)


if __name__ == "__main__":
    main()
