#!/usr/bin/env python3
"""Compare Android .ko modversion CRCs with pinned GKI exports and peer modules."""

from __future__ import annotations

import argparse
import os
import re
import struct
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path


MODULE_VERSION_NAME_LEN = 56
MODULE_VERSION_RECORD_SIZE = 64
ELF64_SECTION_HEADER_SIZE = 64
ELF64_SYMBOL_SIZE = 24
ELF_MACHINE_AARCH64 = 183
MAX_MODULE_FILE_SIZE = 256 * 1024 * 1024


class KmiCheckError(ValueError):
    """Input files are malformed or incomplete for a fail-closed KMI check."""


@dataclass(frozen=True)
class ModuleSymbols:
    path: Path
    imports: dict[str, int]
    exports: dict[str, int]


@dataclass
class KmiReport:
    consumers: int = 0
    providers: int = 0
    import_references: int = 0
    gki_matches: int = 0
    module_matches: int = 0
    unresolved: list[tuple[str, str]] = field(default_factory=list)
    crc_mismatches: list[tuple[str, str, int, tuple[int, ...]]] = field(default_factory=list)
    provider_conflicts: list[tuple[str, tuple[int, ...]]] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not (self.unresolved or self.crc_mismatches or self.provider_conflicts)


def _section_blob(data: bytes, section: tuple[int, ...], label: str) -> bytes:
    offset, size = section[4], section[5]
    if offset < 0 or size < 0 or offset + size > len(data):
        raise KmiCheckError(f"ELF section {label} extends beyond the file")
    return data[offset : offset + size]


def _cstring(data: bytes, offset: int, label: str) -> str:
    if offset < 0 or offset >= len(data):
        raise KmiCheckError(f"invalid {label} string offset {offset}")
    end = data.find(b"\0", offset)
    if end < 0:
        raise KmiCheckError(f"unterminated {label} string")
    try:
        return data[offset:end].decode("ascii")
    except UnicodeDecodeError as exc:
        raise KmiCheckError(f"non-ASCII {label} string") from exc


def parse_module(path: Path) -> ModuleSymbols:
    """Read imports from __versions and export CRCs from __kcrctab in an ARM64 .ko."""
    try:
        if path.stat().st_size > MAX_MODULE_FILE_SIZE:
            raise KmiCheckError(f"{path}: module file exceeds size limit")
        data = path.read_bytes()
    except OSError as exc:
        raise KmiCheckError(f"cannot read module {path}: {exc}") from exc
    if len(data) < ELF64_SECTION_HEADER_SIZE or data[:4] != b"\x7fELF":
        raise KmiCheckError(f"{path}: not an ELF module")
    if data[4] != 2 or data[5] != 1 or data[6] != 1:
        raise KmiCheckError(f"{path}: expected ELF64 little-endian module")
    elf_type, machine = struct.unpack_from("<HH", data, 16)
    if elf_type != 1 or machine != ELF_MACHINE_AARCH64:
        raise KmiCheckError(f"{path}: expected an AArch64 relocatable ELF module")

    section_offset = struct.unpack_from("<Q", data, 40)[0]
    section_entry_size, section_count, names_index = struct.unpack_from("<HHH", data, 58)
    if (
        section_entry_size != ELF64_SECTION_HEADER_SIZE
        or section_offset < ELF64_SECTION_HEADER_SIZE
        or section_offset > len(data)
    ):
        raise KmiCheckError(f"{path}: malformed ELF section table")

    def read_section(index: int) -> tuple[int, ...]:
        start = section_offset + index * section_entry_size
        if start + ELF64_SECTION_HEADER_SIZE > len(data):
            raise KmiCheckError(f"{path}: truncated ELF section table")
        return struct.unpack_from("<IIQQQQIIQQ", data, start)

    first_section = read_section(0)
    if section_count == 0:
        section_count = first_section[5]
    if names_index == 0xFFFF:
        names_index = first_section[6]
    if section_count == 0 or section_count > 65535 or names_index >= section_count:
        raise KmiCheckError(f"{path}: invalid ELF section count or name-table index")
    if section_offset + section_count * section_entry_size > len(data):
        raise KmiCheckError(f"{path}: truncated ELF section table")

    section_headers = [read_section(index) for index in range(section_count)]
    names_blob = _section_blob(data, section_headers[names_index], "section-name table")
    sections: dict[str, tuple[int, tuple[int, ...]]] = {}
    for index, section in enumerate(section_headers):
        name = _cstring(names_blob, section[0], "section-name") if section[0] else ""
        if name:
            if name in sections:
                raise KmiCheckError(f"{path}: duplicate ELF section {name}")
            if section[1] != 8:  # SHT_NOBITS has no bytes in the file.
                _section_blob(data, section, name)
            sections[name] = (index, section)

    version_section = sections.get("__versions")
    if version_section is None:
        raise KmiCheckError(f"{path}: missing __versions; cannot verify MODVERSIONS")
    versions = _section_blob(data, version_section[1], "__versions")
    if len(versions) % MODULE_VERSION_RECORD_SIZE:
        raise KmiCheckError(f"{path}: malformed __versions record size {len(versions)}")
    imports: dict[str, int] = {}
    for offset in range(0, len(versions), MODULE_VERSION_RECORD_SIZE):
        raw_crc = struct.unpack_from("<Q", versions, offset)[0]
        name_bytes = versions[
            offset + 8 : offset + 8 + MODULE_VERSION_NAME_LEN
        ].split(b"\0", 1)[0]
        if not name_bytes:
            if raw_crc:
                raise KmiCheckError(f"{path}: CRC record without a symbol name")
            continue
        if raw_crc >> 32:
            raise KmiCheckError(f"{path}: unexpected high bits in symbol CRC")
        try:
            symbol = name_bytes.decode("ascii")
        except UnicodeDecodeError as exc:
            raise KmiCheckError(f"{path}: non-ASCII imported symbol") from exc
        crc = raw_crc & 0xFFFFFFFF
        if symbol in imports and imports[symbol] != crc:
            raise KmiCheckError(f"{path}: conflicting imported CRCs for {symbol}")
        imports[symbol] = crc

    symtabs = [section for section in section_headers if section[1] == 2]  # SHT_SYMTAB
    if len(symtabs) != 1:
        raise KmiCheckError(f"{path}: expected one ELF symbol table, found {len(symtabs)}")
    symtab = symtabs[0]
    if symtab[9] != ELF64_SYMBOL_SIZE or symtab[5] % ELF64_SYMBOL_SIZE:
        raise KmiCheckError(f"{path}: malformed ELF symbol table")
    if symtab[6] >= len(section_headers):
        raise KmiCheckError(f"{path}: invalid ELF symbol string-table index")
    strings = _section_blob(data, section_headers[symtab[6]], "symbol string table")
    kcrctab_indices = {
        index
        for index, section in enumerate(section_headers)
        if section[0] and _cstring(names_blob, section[0], "section-name").startswith("__kcrctab")
    }
    exports: set[str] = set()
    export_crcs: dict[str, int] = {}
    for offset in range(0, symtab[5], ELF64_SYMBOL_SIZE):
        name_index, info, _other, section_index, value, _size = struct.unpack_from(
            "<IBBHQQ", data, symtab[4] + offset
        )
        if not name_index:
            continue
        symbol_name = _cstring(strings, name_index, "ELF symbol")
        symbol_type = info & 0x0F
        if symbol_name.startswith("__ksymtab_") and symbol_type != 3:  # STT_SECTION
            exported = symbol_name[len("__ksymtab_") :]
            if exported and exported != "strings":
                exports.add(exported)
        if symbol_name.startswith("__crc_") and section_index in kcrctab_indices:
            exported = symbol_name[len("__crc_") :]
            crc_data = _section_blob(data, section_headers[section_index], "__kcrctab")
            if value + 4 > len(crc_data):
                raise KmiCheckError(f"{path}: CRC offset out of bounds for {exported}")
            crc = struct.unpack_from("<I", crc_data, value)[0]
            if exported in export_crcs and export_crcs[exported] != crc:
                raise KmiCheckError(f"{path}: conflicting exported CRCs for {exported}")
            export_crcs[exported] = crc

    if exports != set(export_crcs):
        missing_crcs = sorted(exports - set(export_crcs))
        missing_exports = sorted(set(export_crcs) - exports)
        raise KmiCheckError(
            f"{path}: __ksymtab/__kcrctab mismatch; "
            f"exports without CRC={missing_crcs[:8]}, CRCs without export={missing_exports[:8]}"
        )
    return ModuleSymbols(path=path, imports=imports, exports=export_crcs)


def parse_symvers(paths: list[Path]) -> dict[str, int]:
    """Merge one or more Module.symvers files, rejecting ambiguous export CRCs."""
    exports: dict[str, int] = {}
    for path in paths:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            raise KmiCheckError(f"cannot read symvers {path}: {exc}") from exc
        if not lines:
            raise KmiCheckError(f"symvers file is empty: {path}")
        for line_number, line in enumerate(lines, 1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            fields = stripped.split()
            if len(fields) < 4 or not re.fullmatch(r"0x[0-9a-fA-F]{1,16}", fields[0]):
                raise KmiCheckError(f"{path}:{line_number}: malformed Module.symvers row")
            crc = int(fields[0], 16)
            if crc > 0xFFFFFFFF:
                raise KmiCheckError(f"{path}:{line_number}: CRC exceeds 32 bits")
            symbol = fields[1]
            previous = exports.get(symbol)
            if previous is not None and previous != crc:
                raise KmiCheckError(
                    f"conflicting Module.symvers CRCs for {symbol}: "
                    f"0x{previous:08x} vs 0x{crc:08x}"
                )
            exports[symbol] = crc
    if not exports:
        raise KmiCheckError("Module.symvers inputs contain no exported symbols")
    return exports


def module_paths(roots: list[Path]) -> list[Path]:
    """Find regular .ko files without following symlinked directories or files."""
    found: set[Path] = set()
    for root in roots:
        if root.is_symlink() or not root.is_dir():
            raise KmiCheckError(f"module root is not a real directory: {root}")
        root = root.resolve(strict=True)
        for current, directories, files in os.walk(root, followlinks=False):
            current_path = Path(current)
            for directory in directories:
                if (current_path / directory).is_symlink():
                    raise KmiCheckError(f"symlinked directory in module tree: {current_path / directory}")
            for filename in files:
                if not filename.endswith(".ko"):
                    continue
                path = current_path / filename
                if path.is_symlink() or not path.is_file():
                    raise KmiCheckError(f"module is not a regular file: {path}")
                found.add(path.resolve(strict=True))
    if not found:
        raise KmiCheckError("no .ko files found in the supplied module directories")
    return sorted(found)


def compare_kmi(
    symvers: dict[str, int],
    consumers: list[ModuleSymbols],
    providers: list[ModuleSymbols],
) -> KmiReport:
    """Compare every consumer import CRC with GKI symvers or a supplied module export."""
    report = KmiReport(consumers=len(consumers), providers=len(providers))
    provider_crcs: dict[str, set[int]] = defaultdict(set)
    gki_symbols = set(symvers)
    for symbol, crc in symvers.items():
        provider_crcs[symbol].add(crc)
    for module in providers:
        for symbol, crc in module.exports.items():
            provider_crcs[symbol].add(crc)

    for symbol, crcs in sorted(provider_crcs.items()):
        if len(crcs) > 1:
            report.provider_conflicts.append((symbol, tuple(sorted(crcs))))

    for module in consumers:
        for symbol, crc in module.imports.items():
            report.import_references += 1
            available = provider_crcs.get(symbol, set())
            if not available:
                report.unresolved.append((str(module.path), symbol))
                continue
            if len(available) != 1 or crc not in available:
                report.crc_mismatches.append(
                    (str(module.path), symbol, crc, tuple(sorted(available)))
                )
                continue
            if symbol in gki_symbols:
                report.gki_matches += 1
            else:
                report.module_matches += 1
    return report


def _load_modules(paths: list[Path], cache: dict[Path, ModuleSymbols]) -> list[ModuleSymbols]:
    result = []
    for path in paths:
        resolved = path.resolve(strict=True)
        if resolved not in cache:
            cache[resolved] = parse_module(resolved)
        result.append(cache[resolved])
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symvers", action="append", type=Path, required=True)
    parser.add_argument("--consumer-dir", action="append", type=Path, required=True)
    parser.add_argument("--provider-dir", action="append", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        symvers = parse_symvers(args.symvers)
        cache: dict[Path, ModuleSymbols] = {}
        consumers = _load_modules(module_paths(args.consumer_dir), cache)
        providers = _load_modules(module_paths(args.provider_dir), cache)
        report = compare_kmi(symvers, consumers, providers)
    except (KmiCheckError, OSError, struct.error) as exc:
        print(f"KMI check failed closed: {exc}", file=sys.stderr)
        return 2

    print(f"GKI symvers exports: {len(symvers)}")
    print(f"Provider modules: {report.providers}; consumer modules: {report.consumers}")
    print(f"Import CRC references: {report.import_references}")
    print(f"Matched GKI exports: {report.gki_matches}; matched peer-module exports: {report.module_matches}")
    print(
        f"CRC mismatches: {len(report.crc_mismatches)}; "
        f"unresolved imports: {len(report.unresolved)}; "
        f"provider conflicts: {len(report.provider_conflicts)}"
    )
    if not report.passed:
        for path, symbol, actual, expected in report.crc_mismatches[:40]:
            candidates = ",".join(f"0x{crc:08x}" for crc in expected)
            print(f"CRC mismatch: {path}: {symbol}: module=0x{actual:08x}, providers={candidates}")
        for path, symbol in report.unresolved[:40]:
            print(f"Unresolved import: {path}: {symbol}")
        for symbol, crcs in report.provider_conflicts[:40]:
            candidates = ",".join(f"0x{crc:08x}" for crc in crcs)
            print(f"Conflicting provider CRCs: {symbol}: {candidates}")
        return 1
    print("KMI CRC comparison: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
