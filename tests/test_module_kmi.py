from __future__ import annotations

import importlib.util
import struct
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "check_module_kmi", ROOT / "scripts/check_module_kmi.py"
)
assert SPEC is not None and SPEC.loader is not None
KMI = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = KMI
SPEC.loader.exec_module(KMI)


def make_arm64_module(imports: dict[str, int], exports: dict[str, int]) -> bytes:
    """Build a minimal ELF64 fixture containing kernel __versions/__kcrctab data."""
    section_names = ["", ".shstrtab", ".strtab", ".symtab", "__kcrctab", "__versions", "__ksymtab"]
    shstrtab = b"\0"
    section_name_offsets = {}
    for name in section_names[1:]:
        section_name_offsets[name] = len(shstrtab)
        shstrtab += name.encode("ascii") + b"\0"

    symbol_names = [f"__ksymtab_{name}" for name in exports]
    symbol_names += [f"__crc_{name}" for name in exports]
    strtab = b"\0"
    symbol_name_offsets = {}
    for name in symbol_names:
        symbol_name_offsets[name] = len(strtab)
        strtab += name.encode("ascii") + b"\0"

    symtab = bytearray(24)  # STN_UNDEF
    for name in exports:
        symtab.extend(struct.pack("<IBBHQQ", symbol_name_offsets[f"__ksymtab_{name}"], 0, 0, 6, 0, 0))
    for index, name in enumerate(exports):
        symtab.extend(
            struct.pack("<IBBHQQ", symbol_name_offsets[f"__crc_{name}"], 0, 0, 4, index * 4, 0)
        )

    kcrctab = b"".join(struct.pack("<I", crc) for crc in exports.values())
    versions = bytearray()
    for name, crc in imports.items():
        encoded = name.encode("ascii")
        if len(encoded) >= 56:
            raise ValueError("test symbol exceeds MODULE_NAME_LEN")
        versions.extend(struct.pack("<Q56s", crc, encoded))
    ksymtab = b"\0" * (12 * len(exports))
    contents = [b"", shstrtab, strtab, bytes(symtab), kcrctab, bytes(versions), ksymtab]
    alignments = [1, 1, 1, 8, 4, 8, 4]
    section_types = [0, 3, 3, 2, 1, 1, 1]
    section_flags = [0, 0, 0, 0, 2, 2, 2]
    section_links = [0, 0, 0, 2, 0, 0, 0]
    section_entry_sizes = [0, 0, 0, 24, 4, 0, 12]

    image = bytearray(64)
    section_offsets = [0]
    for index in range(1, len(contents)):
        alignment = alignments[index]
        while len(image) % alignment:
            image.append(0)
        section_offsets.append(len(image))
        image.extend(contents[index])
    while len(image) % 8:
        image.append(0)
    section_table_offset = len(image)
    image.extend(bytes(64 * len(contents)))

    for index in range(len(contents)):
        header = struct.pack(
            "<IIQQQQIIQQ",
            section_name_offsets.get(section_names[index], 0),
            section_types[index],
            section_flags[index],
            0,
            section_offsets[index],
            len(contents[index]),
            section_links[index],
            1 if index == 3 else 0,
            alignments[index],
            section_entry_sizes[index],
        )
        start = section_table_offset + index * 64
        image[start : start + 64] = header

    ident = b"\x7fELF" + bytes((2, 1, 1, 0, 0)) + bytes(7)
    elf_header = struct.pack(
        "<16sHHIQQQIHHHHHH",
        ident,
        1,  # ET_REL
        183,  # EM_AARCH64
        1,
        0,
        0,
        section_table_offset,
        0,
        64,
        0,
        0,
        64,
        len(contents),
        1,
    )
    image[:64] = elf_header
    return bytes(image)


class ModuleKmiTests(unittest.TestCase):
    def test_parse_module_imports_and_exported_crcs(self):
        with tempfile.TemporaryDirectory(prefix="op13-kmi-elf-") as temp:
            module = Path(temp) / "fixture.ko"
            module.write_bytes(
                make_arm64_module(
                    {"kernel_symbol": 0x12345678},
                    {"peer_symbol": 0xAABBCCDD},
                )
            )
            parsed = KMI.parse_module(module)
        self.assertEqual(parsed.imports, {"kernel_symbol": 0x12345678})
        self.assertEqual(parsed.exports, {"peer_symbol": 0xAABBCCDD})

    def test_parse_symvers_merges_identical_exports(self):
        with tempfile.TemporaryDirectory(prefix="op13-kmi-symvers-") as temp:
            first = Path(temp) / "vmlinux.symvers"
            second = Path(temp) / "modules.symvers"
            first.write_text("0x12345678\tkernel_symbol\tvmlinux\tEXPORT_SYMBOL\n", encoding="utf-8")
            second.write_text("0x12345678\tkernel_symbol\tfoo.ko\tEXPORT_SYMBOL_GPL\n", encoding="utf-8")
            self.assertEqual(KMI.parse_symvers([first, second]), {"kernel_symbol": 0x12345678})

    def test_parse_symvers_rejects_conflicting_crc(self):
        with tempfile.TemporaryDirectory(prefix="op13-kmi-symvers-") as temp:
            first = Path(temp) / "first.symvers"
            second = Path(temp) / "second.symvers"
            first.write_text("0x12345678\tkernel_symbol\tvmlinux\tEXPORT_SYMBOL\n", encoding="utf-8")
            second.write_text("0x87654321\tkernel_symbol\tfoo.ko\tEXPORT_SYMBOL\n", encoding="utf-8")
            with self.assertRaises(KMI.KmiCheckError):
                KMI.parse_symvers([first, second])

    def test_compare_checks_gki_and_peer_module_crc(self):
        with tempfile.TemporaryDirectory(prefix="op13-kmi-compare-") as temp:
            consumer_path = Path(temp) / "consumer.ko"
            provider_path = Path(temp) / "provider.ko"
            consumer_path.write_bytes(
                make_arm64_module(
                    {"kernel_symbol": 0x12345678, "peer_symbol": 0xAABBCCDD}, {}
                )
            )
            provider_path.write_bytes(make_arm64_module({}, {"peer_symbol": 0xAABBCCDD}))
            consumer = KMI.parse_module(consumer_path)
            provider = KMI.parse_module(provider_path)
            report = KMI.compare_kmi(
                {"kernel_symbol": 0x12345678}, [consumer], [consumer, provider]
            )
        self.assertTrue(report.passed)
        self.assertEqual(report.gki_matches, 1)
        self.assertEqual(report.module_matches, 1)

    def test_compare_rejects_crc_mismatch_and_unresolved_import(self):
        with tempfile.TemporaryDirectory(prefix="op13-kmi-failure-") as temp:
            consumer_path = Path(temp) / "consumer.ko"
            consumer_path.write_bytes(
                make_arm64_module(
                    {"kernel_symbol": 0x11111111, "missing_symbol": 0x22222222}, {}
                )
            )
            consumer = KMI.parse_module(consumer_path)
            report = KMI.compare_kmi(
                {"kernel_symbol": 0x12345678}, [consumer], [consumer]
            )
        self.assertFalse(report.passed)
        self.assertEqual(len(report.crc_mismatches), 1)
        self.assertEqual(len(report.unresolved), 1)


if __name__ == "__main__":
    unittest.main()
