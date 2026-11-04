# Project status and validation limits

## Current state

This is an experimental source repository, not a validated OnePlus 13 dual-boot solution. The original uploaded archive contained a corrupted `.git` directory, which was not imported. The repository has a fresh Git history.

The module has been reworked into a **read-only preview** and rebuilt from `module-src/`:

- updater commands that would write partitions, change slots, reboot, install Linux, restore images, or flash OTA now fail closed;
- the slot guardian is a status/disabled-operation stub;
- the early boot hook does not set block devices read-only;
- boot service does not run an automatic guardian;
- the web page is static, has no root bridge or remote JavaScript, and reports no simulated success;
- the package install script identifies itself as preview-only.
- it does **not** disable the Android OTA updater; OTA blocking is only part of the proposed design.

The preview module is not an installer and must not be used as a device protection mechanism. Re-enabling device operations requires device-specific implementation, recovery procedures, and hardware testing.

The intended boot design is documented in [`docs/BOOT_FLOW.md`](docs/BOOT_FLOW.md): A remains Android, B will eventually boot a LineageOS-derived kernel, Android performs its normal credential unlock, then glibc Linux takes over. This is a proposed flow only. Android unlock integration, lock-screen UI, Linux handoff, Wayland, and OTA suppression are not implemented.

## Changes in the hardening pass

- Added `scripts/merge_kconfig.py`: idempotent Kconfig merge, conflicting assignments rejected by default, explicit override flag, atomic file replacement.
- Hardened `scripts/import_and_patch_lineageos.sh`: KernelSU and thermal bypass disabled by default, patches apply-or-fail instead of silently continuing, already-applied patches handled idempotently, Kconfig conflicts surfaced, KernelSU setup script requires an explicit URL and SHA-256.
- Reduced `scripts/enter_headless.sh` to stopping selected Android services and saving which were running. CPU/GPU/thermal/swap/sysctl changes and broad process kills were removed. Restore is best-effort and only starts saved services.
- Reframed `runtime/setup_micro_glibc.sh` as a staging helper for an existing AArch64 glibc tree; it fails when the loader or libc is missing and refuses to overwrite a populated destination by default.
- Added maintainable module sources and deterministic ZIP packaging via `scripts/package_module.py`.
- Added `docs/BOOT_FLOW.md` and `scripts/android_preflight.sh` as the first implementation phase: capture non-secret device facts before designing the Android unlock/handoff. The preflight has no partition-write or key-reading path.
- Replaced the original workflow (which cloned kernel code and ran a remote installer) with offline host checks. Added a separate manual-only, SHA-pinned Kleaf workflow at `.github/workflows/kernel-build.yml`; it builds only the raw `sun/perf` kernel and modules-install targets on a GitHub-hosted runner. It does not create boot images, include ABL, run ABI validation, publish a Release, or access a device. See [`docs/KLEAF_ACTIONS_BUILD.md`](docs/KLEAF_ACTIONS_BUILD.md).

## Tests

Run:

```bash
bash tests/run_tests.sh
```

This includes:

- unit tests for Kconfig conflicts, override behavior, and merge idempotence;
- patch application against synthetic fixtures only;
- source-to-ZIP consistency, ZIP CRC/path checks, and shell syntax checks for packaged scripts;
- static checks that the preview module has no partition-write operations or simulated WebUI controls;
- C build with `-Wall -Wextra -Werror`, AddressSanitizer and UndefinedBehaviorSanitizer, followed by runtime checks for System V IPC cleanup, clock/syscall calls, actual allowed CPU affinity and exact atomic count, and full GEMM result correctness.

Last host-suite run passed: **20 Python tests**, synthetic patch fixtures, module ZIP rebuild/validation, shell syntax checks, and the sanitized C test binary. Environment: Linux x86_64, GCC 16.2, glibc 2.44, 4 allowed CPUs. The Actions workflow and lockfile also pass `actionlint`, shell syntax, manifest pin checks, and patch applicability checks. These validate host-side behavior only. No successful Kleaf Actions build or target-device preflight has completed. No unlock, handoff, OTA blocking, or partition modification is implemented.

`python3 tests/verify_kernel_patches.py --kernel-tree PATH` checks textual patch applicability against a real checkout without calling that a successful build. Its default synthetic fixture is deliberately not described as a LineageOS tree.

## Remaining known limitations

1. No OnePlus 13 device, boot image, recovery image, or rootfs has been tested or included.
2. The kernel patch still changes thermal trip handling. It is skipped by default, has no safety proof, and should not be enabled for device use.
3. The kernel importer still fetches a mutable LineageOS branch and does not build the kernel. Review/pin the exact upstream commit yourself.
4. Optional KernelSU setup runs a downloaded script after a user-supplied digest check. That digest only helps if the URL and expected digest were independently reviewed.
5. The glibc script stages files only; it does not build glibc, validate all ABI dependencies, or make Android vendor/Bionic libraries glibc-compatible.
6. The C tests run using the host's glibc and kernel. Timing values are not portable and are not device performance claims.
7. `enter_headless.sh` can stop Android UI services. ADB persistence, service names, and recovery from an interrupted script have not been tested on the target ROM.
8. No license is specified. Public visibility does not grant reuse rights.
9. Actions run `41604285375` exposed a missing device-tree workspace link;
   commit `ced1409` fixed it. Run `41609054119` found duplicate UFS query
   structs; `eca0dd4` enabled the pinned OnePlus UFS settings. Run
   `41619891068` then found sandbox-escaping UFS includes; commit `6f01414`
   corrected them. Run `41669250057` passed source sync and compilation but
   failed at modpost, so no `Image` was produced. Its log reported missing
   OPlus device-info/bootmode and QTI charger symbols, plus `make_kuid` and
   `from_kuid_munged` absent from the pinned KMI with `CONFIG_USER_NS=y`.
   The approved direction is Image-only Kleaf, preserving KMI and `USER_NS`.
   Commit `25c551f` requests only `Image` and omits the sun/perf module outputs;
   it still needs a real pinned build. The `.113` attempt ended before source
   sync completed. None of these host builds validates bootability or
   device-side features.
