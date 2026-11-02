# OnePlus 13 / SM8750 headless Linux experiments

> **Experimental source, not a working dual-boot release.** Nothing here has been validated on a OnePlus 13. Do not flash images or rely on the project to protect partitions or OTA updates. Read [`PROJECT_STATUS.md`](PROJECT_STATUS.md) before using any device-facing script.

The repository contains kernel patches, Kconfig settings, host/device scripts, a C smoke-test/benchmark program, and source for a preview-only KernelSU/Magisk module. It does **not** contain a kernel, glibc build, boot images, or a Linux root filesystem.

## Current safety limits

- The module ZIP is a **read-only preview**. Its backend reports limited status; install, restore, reboot, and slot-switch operations are disabled. The web page is static and does not run shell commands. **It does not block Android's existing OTA updater.**
- `post-fs-data.sh` no longer changes block-device flags; the service does not auto-run the slot guardian.
- KernelSU setup and the thermal-bypass patch are opt-in. The importer fails on patch conflicts instead of printing a false success. Kconfig changes are idempotent and conflicting values require explicit review.
- `enter_headless.sh` stops only selected Android services that were running and records them for a best-effort restore. It does not modify CPU/GPU clocks, thermal policy, swap, or sysctls. It can still stop the local Android UI; maintain ADB access and inspect the script first.
- The proposed A=Android / B=Linux boot flow is recorded in [`docs/BOOT_FLOW.md`](docs/BOOT_FLOW.md). Android encryption unlock, lock-screen handoff, Linux pivot, and OTA blocking are **not implemented**.
- The thermal bypass patch remains in the repository for review but is **not recommended** and is not applied by default.

These safeguards do not make the project device-ready. In particular, patch applicability is not kernel compilation, and a successful host test says nothing about the boot chain, OTA, GPU/NPU, or recovery.

## Tests

Run the local test suite on Linux with Python 3, GCC, and Bash:

```bash
bash tests/run_tests.sh
```

It runs Python unit tests for Kconfig merging, applies patches to **synthetic fixtures only**, checks shell syntax and the module ZIP, rebuilds the ZIP from source, then compiles and runs the C tests with AddressSanitizer and UndefinedBehaviorSanitizer. The C measurements are host-specific. They must not be presented as OnePlus 13 results.

To check textual patch applicability against a separately obtained kernel checkout:

```bash
python3 tests/verify_kernel_patches.py --kernel-tree /path/to/android_kernel_oneplus_sm8750
```

This is still not a build or a KMI/runtime validation.

## Source layout

- `patches/` — Kconfig fragment and two kernel patches; the thermal bypass is opt-in and unsafe to assume correct.
- `scripts/import_and_patch_lineageos.sh` — clones the selected LineageOS kernel branch and applies the default patch/config set.
- `scripts/merge_kconfig.py` — idempotent Kconfig merge with explicit conflict handling.
- `scripts/enter_headless.sh` — limited Android service stop/restore helper.
- `scripts/android_preflight.sh` — read-only inventory of selected Android properties, `/data` mount/capacity and fstab flags, filesystem availability, and visible physical/logical partition nodes. It does not read key blobs or modify the device.
- `docs/BOOT_FLOW.md` — accepted architecture and implementation gates.
- `runtime/setup_micro_glibc.sh` — stages an **already-built** AArch64 glibc directory. It does not build or download glibc, and refuses to overwrite a non-empty destination unless `OVERWRITE=1` is explicitly set.
- `tests/advanced_suite.c` — IPC lifecycle, timing, CPU affinity/atomic-count, and GEMM correctness smoke tests plus non-portable benchmarks.
- `module-src/` — editable, fail-closed preview module sources.
- `modules/OP13-DualBoot-Manager-v2.1.0-preview.zip` — generated preview package; not a usable Linux installer.

Rebuild the module ZIP after editing `module-src/`:

```bash
python3 scripts/package_module.py
```

## Kernel import (review before running)

The script fetches a mutable upstream branch and modifies `kernel_workspace/kernel`; it does not validate the resulting device build. Review the upstream revision and local changes before proceeding.

```bash
BRANCH=lineage-23.2 ./scripts/import_and_patch_lineageos.sh
```

The default leaves KernelSU and thermal bypass disabled. To opt into KernelSU, inspect an immutable setup script first and provide its URL plus SHA-256:

```bash
ENABLE_KSU=1 \
KSU_SETUP_URL='https://example.invalid/reviewed-immutable-setup.sh' \
KSU_SETUP_SHA256='<64-hex-digest>' \
./scripts/import_and_patch_lineageos.sh
```

Do not enable `ENABLE_THERMAL_BYPASS=1` on a device. No flashing instructions are provided because no boot image or recovery procedure has been validated.

## First device-side step: read-only inventory

After reviewing the script, copy it to a temporary path and run it on the target ROM:

```bash
adb push scripts/android_preflight.sh /data/local/tmp/
adb shell su -c 'sh /data/local/tmp/android_preflight.sh'
```

The script itself only reads. `adb push` places the script in `/data/local/tmp`; the report intentionally omits serial numbers, credentials, and encryption keys. Review the output before sharing it.

## License

No license is currently specified. Public visibility does not grant reuse rights; obtain the rights holder’s decision before redistribution or reuse.
