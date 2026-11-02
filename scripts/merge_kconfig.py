#!/usr/bin/env python3
"""Merge a Kconfig fragment without silently duplicating/conflicting symbols."""

from __future__ import annotations

import argparse
import os
import re
import stat
import sys
import tempfile
from pathlib import Path


SET_RE = re.compile(r"^\s*(CONFIG_[A-Z0-9_]+)=(.*)\s*$")
UNSET_RE = re.compile(r"^\s*#\s*(CONFIG_[A-Z0-9_]+)\s+is\s+not\s+set\s*$")


class KconfigError(ValueError):
    """Raised for ambiguous or conflicting Kconfig assignments."""


def parse_assignments(text: str, source: str) -> dict[str, str]:
    assignments: dict[str, str] = {}
    for line_number, line in enumerate(text.splitlines(), start=1):
        match = SET_RE.match(line)
        if match:
            name, value = match.groups()
        else:
            match = UNSET_RE.match(line)
            if not match:
                continue
            name, value = match.group(1), "n"

        previous = assignments.get(name)
        if previous is not None and previous != value:
            raise KconfigError(
                f"{source}:{line_number}: conflicting assignments for {name}: "
                f"{previous!r} and {value!r}"
            )
        assignments[name] = value
    return assignments


def merge_config(base: str, fragment: str, *, allow_overrides: bool = False) -> str:
    """Return an idempotent merge; reject conflicts unless explicitly allowed."""
    base_values = parse_assignments(base, "base")
    fragment_values = parse_assignments(fragment, "fragment")
    lines_to_add: list[str] = []

    for name, desired in fragment_values.items():
        current = base_values.get(name)
        if current is None:
            lines_to_add.append(f"{name}={desired}")
        elif current != desired:
            if not allow_overrides:
                raise KconfigError(
                    f"conflicting value for {name}: base has {current!r}, "
                    f"fragment requests {desired!r}; review and pass --allow-overrides"
                )
            lines_to_add.append(f"{name}={desired}")

    if not lines_to_add:
        return base if base.endswith("\n") or not base else base + "\n"

    prefix = base
    if prefix and not prefix.endswith("\n"):
        prefix += "\n"
    if prefix and not prefix.endswith("\n\n"):
        prefix += "\n"
    return prefix + "# Added by merge_kconfig.py\n" + "\n".join(lines_to_add) + "\n"


def merge_file(base_path: Path, fragment_path: Path, *, allow_overrides: bool) -> None:
    base = base_path.read_text(encoding="utf-8")
    fragment = fragment_path.read_text(encoding="utf-8")
    merged = merge_config(base, fragment, allow_overrides=allow_overrides)
    original_mode = stat.S_IMODE(base_path.stat().st_mode)

    base_path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{base_path.name}.", dir=base_path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            os.fchmod(output.fileno(), original_mode)
            output.write(merged)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temp_name, base_path)
    except BaseException:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base", type=Path, help="Kconfig file to update in place")
    parser.add_argument("fragment", type=Path, help="Kconfig fragment to merge")
    parser.add_argument(
        "--allow-overrides",
        action="store_true",
        help="append explicit values even when the base assigns a conflicting value",
    )
    args = parser.parse_args()
    try:
        merge_file(args.base, args.fragment, allow_overrides=args.allow_overrides)
    except (OSError, KconfigError) as error:
        print(f"merge_kconfig.py: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
