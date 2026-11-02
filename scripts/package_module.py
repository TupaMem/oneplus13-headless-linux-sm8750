#!/usr/bin/env python3
"""Build the preview module ZIP reproducibly from module-src/."""

from __future__ import annotations

import argparse
import os
import tempfile
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "module-src"
DEFAULT_OUTPUT = ROOT / "modules/OP13-DualBoot-Manager-v2.1.0-preview.zip"


def build_archive(output: Path) -> None:
    if not SOURCE.is_dir():
        raise FileNotFoundError(f"module source directory not found: {SOURCE}")
    source_root = SOURCE.resolve()
    output = output.resolve()
    try:
        output.relative_to(source_root)
    except ValueError:
        pass
    else:
        raise ValueError("output archive must not be placed inside module-src/")
    files = sorted(path for path in SOURCE.rglob("*") if path.is_file())
    if not files:
        raise ValueError(f"no module files found under {SOURCE}")
    symlinks = [path for path in files if path.is_symlink()]
    if symlinks:
        raise ValueError("module source must not contain symlinks: " + ", ".join(map(str, symlinks)))
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{output.name}.", dir=output.parent)
    os.close(fd)
    try:
        with zipfile.ZipFile(temp_name, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for path in files:
                relative = path.relative_to(SOURCE).as_posix()
                info = zipfile.ZipInfo(relative, date_time=(2020, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                executable = (
                    path.name.endswith(".sh")
                    or relative.startswith("system/bin/")
                    or relative.endswith("/update-binary")
                )
                mode = 0o755 if executable else 0o644
                info.external_attr = (0o100000 | mode) << 16
                archive.writestr(info, path.read_bytes())
        with zipfile.ZipFile(temp_name) as archive:
            bad_entry = archive.testzip()
            if bad_entry is not None:
                raise zipfile.BadZipFile(f"CRC check failed for {bad_entry}")
        os.replace(temp_name, output)
    except BaseException:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    build_archive(args.output)
    print(f"Built {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
