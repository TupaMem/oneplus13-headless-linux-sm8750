# Pinned Kleaf build on GitHub Actions

The workflow `.github/workflows/kernel-build.yml` is a manual, host-only build
of the pinned common GKI base Image intended for the OnePlus 13 `sun/perf` port.
Start it from **GitHub → Actions → OnePlus 13 GKI base Image build → Run
workflow**. It is intentionally not triggered by pushes or pull requests: a
full Kleaf compile consumes hours and substantial runner disk space.

## What it does

1. Frees unused preinstalled SDK/tooling space on an ephemeral
   `ubuntu-24.04` GitHub-hosted runner, then checks that at least 30 GiB is
   available.
2. Initializes `repo` from the committed `ci/kleaf/manifest.xml` lockfile. The
   manifest pins all 37 source repositories to exact Git revisions; tool and
   OPlus helper revisions are recorded in `ci/kleaf/pins.env`.
3. Verifies the pinned source revisions, then applies the reviewed project
   overlay `0008-op13-gki-userns-config.patch` and
   `op13-userns.fragment`. The fragment sets `CONFIG_USER_NS=y` only for the
   ARM64 common GKI target; it does not alter KMI symbol lists or exports.
4. Runs `//common:kernel_aarch64_abi_diff` against the pinned common GKI STG
   baseline. The pinned Kleaf target enforces the diff exit code; any ABI/KMI
   difference stops the workflow before the Image build/package step.
5. Builds `//common:kernel_aarch64`. This is the Android common GKI base, not a
   `sun/perf`-configured Image. Its pinned make-goal list also requests
   `Image.lz4`, `Image.gz`, and common GKI `modules`; only the raw `Image` is
   packaged. No OnePlus vendor-module or modules-install target is requested.
   The vendor modules are still required for a complete device port and have
   not been built/validated by this workflow.
6. Uploads a 14-day Actions artifact containing the raw common GKI `Image`
   only if the ABI gate and Image build pass, plus build log, checksums, source
   lockfile, overlay patch/fragment, relevant common build inputs, and
   provenance. This is not a GitHub Release.

The artifact is a **raw ARM64 common GKI base Image with a project
`CONFIG_USER_NS=y` overlay**, not a OnePlus `sun/perf`-configured Image,
`boot.img`, `vendor_boot.img`, or `init_boot.img`. It is marked `flashable=no`
and has not been boot-tested. Do not flash it directly. The workflow never
connects to a phone, reads device secrets, or performs device operations. The
ABI gate checks the modified common GKI against its pinned baseline; this does
not establish matching OnePlus vendor-module KMI, FBE/KeyMint compatibility,
recovery safety, graphics support, or OTA behavior.

## Pins and changes

- `manifest.xml` locks the common kernel, Kleaf/build dependencies, and the
  pinned OnePlus kernel/modules/device-tree source revisions used by the wider
  project. Only the common GKI target is built by this workflow.
- `pins.env` records the pinned repo client, upstream manifest provenance and
  OnePlus helper revision. The exact project overlay patch and USER_NS fragment
  are included in the artifact.
- The repo client launcher checksum and source commit are verified before
  initialization; `repo init` fetches that exact commit from the official
  Gerrit remote.
- Kleaf compatibility patches for a future vendor-module build remain under
  `ci/kleaf/patches/`; this GKI Image workflow applies only the USER_NS overlay.
  Changes to any pin or build patch require review and a fresh successful
  Actions build. The first run starts with an empty Bazel cache and may take
  several hours. GitHub-hosted runner limits or source-host throttling can stop
  it; in that case the artifact/log records the failure, and no local fallback
  build should be started automatically.

## Current status

Actions run `41669250057` reached vendor-module `modpost` but failed with
unresolved symbols: the pinned GKI KMI does not export
`make_kuid`/`from_kuid_munged` while this profile enables `USER_NS`. Follow-up
run `41781537334` confirmed that `make_goals=["Image"]` cannot be used on the
mixed-tree `//msm-kernel:sun_perf` target: Kbuild reports `No rule to make
target 'vmlinux', needed by 'Image'`. Its common dependency completed, but its
GKI Image was not collected. The updated workflow now applies `CONFIG_USER_NS=y`,
enforces the pinned common ABI diff, then builds and collects the raw Image.
This path has not yet passed an Actions run. It does not build or validate the
Arch Linux ARM rootfs, matching OnePlus vendor modules, bootability, or device
behavior.

## Local validation without compiling the kernel

```sh
bash -n ci/kleaf/*.sh
python3 -m unittest discover -s tests -v
```

These checks parse scripts and validate metadata only. Running
`ci/kleaf/run_build.sh` performs the actual large build and is intended for the
Actions runner.
