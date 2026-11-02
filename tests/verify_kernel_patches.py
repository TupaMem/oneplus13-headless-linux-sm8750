#!/usr/bin/env python3
"""Validate the Kconfig fragment and optionally check patch applicability.

The fixture mode only proves the patches match the small checked-in test
fixtures. It is not a substitute for testing against the actual LineageOS tree.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATCH_DIR = ROOT / "patches"
FRAGMENT = PATCH_DIR / "sm8750-headless-glibc.config"
PATCH_NAMES = (
    "0001-sm8750-headless-glibc-kconfig.patch",
    "0002-sm8750-oryon-thermal-bypass.patch",
)
REQUIRED_CONFIGS = {
    "CONFIG_SYSVIPC": "y",
    "CONFIG_SYSVIPC_SYSCTL": "y",
    "CONFIG_POSIX_MQUEUE": "y",
    "CONFIG_POSIX_MQUEUE_SYSCTL": "y",
    "CONFIG_NAMESPACES": "y",
    "CONFIG_UTS_NS": "y",
    "CONFIG_IPC_NS": "y",
    "CONFIG_USER_NS": "y",
    "CONFIG_PID_NS": "y",
    "CONFIG_NET_NS": "y",
    "CONFIG_DEVTMPFS": "y",
    "CONFIG_DEVTMPFS_MOUNT": "y",
    "CONFIG_BINFMT_MISC": "y",
    "CONFIG_OVERLAY_FS": "y",
    "CONFIG_TMPFS_POSIX_ACL": "y",
    "CONFIG_CPU_FREQ_DEFAULT_GOV_PERFORMANCE": "y",
    "CONFIG_CPU_FREQ_GOV_PERFORMANCE": "y",
    "CONFIG_SECURITY_SELINUX_DEVELOP": "y",
    "CONFIG_SECURITY_SELINUX_BOOTPARAM": "y",
}
ASSIGNMENT = re.compile(r"^\s*(CONFIG_[A-Z0-9_]+)=(.*)\s*$")
UNSET = re.compile(r"^\s*#\s*(CONFIG_[A-Z0-9_]+)\s+is\s+not\s+set\s*$")


class ValidationError(RuntimeError):
    pass


def parse_config(text: str, label: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for number, line in enumerate(text.splitlines(), start=1):
        match = ASSIGNMENT.match(line)
        if match:
            name, value = match.groups()
        else:
            match = UNSET.match(line)
            if not match:
                continue
            name, value = match.group(1), "n"
        if name in result and result[name] != value:
            raise ValidationError(
                f"{label}:{number}: conflicting values for {name}: "
                f"{result[name]!r} and {value!r}"
            )
        result[name] = value
    return result


def validate_fragment() -> None:
    if not FRAGMENT.is_file():
        raise ValidationError(f"Kconfig fragment missing: {FRAGMENT}")
    config = parse_config(FRAGMENT.read_text(encoding="utf-8"), str(FRAGMENT))
    missing = [name for name in REQUIRED_CONFIGS if config.get(name) != "y"]
    if missing:
        raise ValidationError("Missing or disabled required Kconfig options: " + ", ".join(missing))
    print(f"[PASS] Kconfig fragment contains {len(REQUIRED_CONFIGS)} required assignments.")


def patch_paths() -> list[Path]:
    paths = [PATCH_DIR / name for name in PATCH_NAMES]
    missing = [str(path) for path in paths if not path.is_file()]
    if missing:
        raise ValidationError("Missing patch files: " + ", ".join(missing))
    return paths


def run_git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, text=True, capture_output=True, check=False)


def make_patch_fixture(root: Path) -> None:
    gki_dir = root / "arch/arm64/configs"
    thermal_dir = root / "drivers/thermal"
    gki_dir.mkdir(parents=True)
    thermal_dir.mkdir(parents=True)
    (gki_dir / "gki_defconfig").write_text(
        "CONFIG_IKCONFIG=y\n"
        "CONFIG_IKCONFIG_PROC=y\n"
        "CONFIG_CGROUPS=y\n"
        "CONFIG_MEMCG=y\n"
        "CONFIG_BLK_CGROUP=y\n"
        "CONFIG_CGROUP_SCHED=y\n"
        "CONFIG_UCLAMP_TASK=y\n",
        encoding="utf-8",
    )
    (thermal_dir / "thermal_core.c").write_text(
        "static DEFINE_MUTEX(thermal_list_lock);\n"
        "static DEFINE_MUTEX(thermal_governor_lock);\n"
        "static atomic_t in_suspend;\n"
        "\n"
        "static void handle_thermal_trip(struct thermal_zone_device *tz,\n"
        "                                const struct thermal_trip *trip)\n"
        "{\n"
        "        if (trip->temperature == THERMAL_TEMP_INVALID)\n"
        "                return;\n"
        "\n"
        "        if (tz->last_temperature != THERMAL_TEMP_INVALID) {\n"
        "                if (tz->last_temperature < trip->temperature &&\n"
        "                    tz->temperature >= trip->temperature)\n",
        encoding="utf-8",
    )


def check_patch_fixture() -> None:
    print("[INFO] Applying patches to synthetic context fixtures (not a kernel tree).")
    with tempfile.TemporaryDirectory(prefix="sm8750-patch-fixture-") as temp:
        root = Path(temp)
        make_patch_fixture(root)
        init = run_git(["git", "init", "-q"], root)
        if init.returncode != 0:
            raise ValidationError(f"git init failed: {init.stderr.strip()}")
        for patch in patch_paths():
            check = run_git(["git", "apply", "--check", str(patch)], root)
            if check.returncode != 0:
                raise ValidationError(f"Fixture check failed for {patch.name}: {check.stderr.strip()}")
            apply = run_git(["git", "apply", str(patch)], root)
            if apply.returncode != 0:
                raise ValidationError(f"Fixture apply failed for {patch.name}: {apply.stderr.strip()}")

        patched_gki = (root / "arch/arm64/configs/gki_defconfig").read_text(encoding="utf-8")
        patched_thermal = (root / "drivers/thermal/thermal_core.c").read_text(encoding="utf-8")
        missing = [name for name, value in REQUIRED_CONFIGS.items()
                   if f"{name}={value}" not in patched_gki]
        if missing:
            raise ValidationError("Patch fixture lacks Kconfig additions: " + ", ".join(missing))
        required_thermal = (
            "sm8750_headless_thermal_bypass",
            "trip->type != THERMAL_TRIP_CRITICAL",
            "trip->type != THERMAL_TRIP_HOT",
        )
        if any(token not in patched_thermal for token in required_thermal):
            raise ValidationError("Thermal patch fixture is missing expected text")
    print("[PASS] Both patches apply to their synthetic fixtures; no kernel/KMI claim is made.")


def check_kernel_tree(kernel_tree: Path) -> None:
    kernel_tree = kernel_tree.resolve()
    if not (kernel_tree / ".git").exists():
        raise ValidationError(f"Not a Git checkout: {kernel_tree}")
    for relative in ("arch/arm64/configs/gki_defconfig", "drivers/thermal/thermal_core.c"):
        if not (kernel_tree / relative).is_file():
            raise ValidationError(f"Kernel tree is missing expected path: {relative}")

    print(f"[INFO] Checking patch applicability in real checkout: {kernel_tree}")
    for patch in patch_paths():
        forward = run_git(["git", "apply", "--check", str(patch)], kernel_tree)
        if forward.returncode == 0:
            print(f"[PASS] {patch.name}: applies cleanly")
            continue
        reverse = run_git(["git", "apply", "--reverse", "--check", str(patch)], kernel_tree)
        if reverse.returncode == 0:
            print(f"[PASS] {patch.name}: already applied")
            continue
        raise ValidationError(
            f"{patch.name} neither applies cleanly nor appears already applied. "
            f"git apply: {forward.stderr.strip()}"
        )
    print("[INFO] This checks textual applicability only, not compilation, KMI, or runtime behavior.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="apply patches to synthetic fixtures; this is not a LineageOS validation",
    )
    parser.add_argument(
        "--kernel-tree",
        type=Path,
        help="also check patch applicability against an existing kernel Git checkout",
    )
    args = parser.parse_args()
    try:
        validate_fragment()
        patch_paths()
        if args.self_test:
            check_patch_fixture()
        if args.kernel_tree:
            check_kernel_tree(args.kernel_tree)
    except (OSError, ValidationError) as error:
        print(f"[FAIL] {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
