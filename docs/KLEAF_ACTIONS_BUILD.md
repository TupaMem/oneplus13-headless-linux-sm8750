# Pinned Kleaf build on GitHub Actions

The workflow `.github/workflows/kernel-build.yml` is a manual, host-only build
for the LineageOS OnePlus 13 `sun/perf` kernel. Start it from **GitHub → Actions
→ OnePlus 13 sun/perf kernel build → Run workflow**. It is intentionally not
triggered by pushes or pull requests: a full Kleaf compile consumes hours and
substantial runner disk space.

## What it does

1. Frees unused preinstalled SDK/tooling space on an ephemeral
   `ubuntu-24.04` GitHub-hosted runner, then checks that at least 30 GiB is
   available.
2. Initializes `repo` from the committed `ci/kleaf/manifest.xml` lockfile. The
   manifest pins all 37 source repositories to exact Git revisions; tool and
   OPlus helper revisions are recorded in `ci/kleaf/pins.env`.
3. Links the pinned device-tree checkout into Kleaf's expected
   `vendor/qcom/kernel/arch/arm64/boot/dts/vendor` workspace path and verifies
   its `BUILD.bazel` and Qualcomm platform map before Bazel starts.
4. Applies the Kleaf compatibility patches and the small headless Kconfig
   fragment in `ci/kleaf/patches/`. KernelSU and the optional thermal bypass are
   not enabled.
5. The current candidate asks `//msm-kernel:sun_perf` for `Image` and omits its
   vendor module outputs. This is not a working path: `sun_perf` uses Kleaf's
   mixed-tree mode with `//common:kernel_aarch64` as `base_kernel`; Kbuild
   intentionally omits the `vmlinux` target in mixed-tree mode, so `Image`
   fails. No successful Image-only workflow target is selected yet.
6. Uploads a 14-day Actions artifact containing the raw `Image` (if built),
   build log, checksums, source lockfile and build metadata. This is not a
   GitHub Release.

The artifact is a **raw ARM64 kernel Image**, not `boot.img`, `vendor_boot.img`
or `init_boot.img`. It is marked `flashable=no` and has not been boot-tested.
Do not flash it directly. The workflow never connects to a phone, reads device
secrets, or performs device operations. It does not claim KMI/ABI validation,
FBE/KeyMint compatibility, recovery safety, graphics support, or OTA behavior.

## Pins and changes

- `manifest.xml` locks AOSP Kleaf/build dependencies and the LineageOS kernel,
  modules and device trees.
- `pins.env` records the pinned repo client, upstream manifest provenance and
  OnePlus helper revision.
- The repo client launcher checksum and source commit are verified before
  initialization; `repo init` fetches that exact commit from the official
  Gerrit remote.
- The compatibility patches are kept separate from the upstream kernel tree;
  the workflow checks they apply cleanly before using them. The module-list
  insertion uses a zero-context hunk, so the exact pinned kernel SHA is checked
  before applying it; changing that pin requires regenerating/reviewing the hunk.
- Changes to any pin or patch require review and a fresh successful Actions
  build. The first run starts with an empty Bazel cache and may take several
  hours. GitHub-hosted runner limits or source-host throttling can stop it; in
  that case the artifact/log records the failure, and no local fallback build
  should be started automatically.

## Current status

Actions run `41669250057` reached vendor-module `modpost` but failed with
unresolved symbols: the pinned GKI KMI does not export
`make_kuid`/`from_kuid_munged` while this profile enables `USER_NS`. Follow-up
run `41781537334` confirmed that `make_goals=["Image"]` cannot be used on the
mixed-tree `//msm-kernel:sun_perf` target: Kbuild reports `No rule to make
target 'vmlinux', needed by 'Image'`. Its `//common:kernel_aarch64` dependency
build completed, but its GKI Image was not collected. Before another expensive
run, choose whether to package that common GKI Image (the base image paired with
vendor modules) or design a separate non-mixed `sun_perf` image build. Neither
path would validate bootability or device-side behavior.

## Local validation without compiling the kernel

```sh
bash -n ci/kleaf/*.sh
python3 -m unittest discover -s tests -v
```

These checks parse scripts and validate metadata only. Running
`ci/kleaf/run_build.sh` performs the actual large build and is intended for the
Actions runner.
