# Arch Linux ARM userspace and end-user roadmap

**Status: direction selected; implementation has not started.** The planned
userspace base is Arch Linux for AArch64. This is a device-port and image-build
project, not a plan to create a new Linux distribution from scratch. There is
no Linux rootfs, bootable image, installer, or supported OnePlus 13 port in this
repository today.

## Recorded direction

- **Userspace:** Arch-family AArch64/glibc userspace. Arch Linux ARM is the
  initial implementation candidate; it is a separate project/package source
  from upstream Arch Linux. Its current AArch64 repositories, maintenance,
  bootstrap method, signatures, and support terms must be reviewed and pinned
  before use. Choosing Arch does not imply OnePlus 13 device support.
- **Kernel:** use the pinned common GKI base `Image` as the kernel artifact,
  paired with compatible OnePlus `sun/perf` vendor components when those are
  built and validated. The GKI image is the common base, not an Image with the
  vendor profile compiled into it. The user selected this artifact direction;
  CI has not yet been changed to collect it.
- **Bring-up target:** start with a minimal, headless AArch64 rootfs. A desktop
  is a later milestone, gated on display, GPU, input, and power support.
- **Distribution work:** keep the base package manager and repositories from
  Arch Linux ARM; maintain only the device-specific kernel/module integration,
  rootfs recipe, configuration, and boot integration needed by this project.

## Safety and scope constraints

- Android remains the intended environment in A; Linux is intended for B. These
  labels are provisional: the target's actual slot and partition layout has not
  been confirmed, and a slot must not be assumed to be a dedicated Linux rootfs.
- Preserve Android FBE. Do not store, request, log, or copy a PIN or key. Do not
  format, repurpose, or mount Android `/data` from Linux unless a later design
  proves the exact Android/KeyMint flow and receives explicit approval.
- The Linux rootfs location and encryption model are **not decided**. Keep it
  separate from Android user data in the design until device facts say what is
  possible.
- No OTA may run while B is assigned to Linux. OTA suppression, slot switching,
  install, rollback, and recovery are not implemented.
- No phone writes or boot tests without a separate exact plan and confirmation.
  No ABL/bootloader changes, flashable package, or device operation is part of
  this documentation task.
- Android vendor libraries cannot be assumed to work in glibc userspace;
  proprietary firmware, interfaces, and redistribution rights need separate
  review.

## Roadmap and gates

### 0. Establish facts — read-only

Confirm the exact OnePlus 13 SKU/region, ROM revision, bootloader and AVB state,
slot semantics, physical/logical partition map, filesystems, and Android FBE /
KeyMint properties using the existing read-only preflight. Do not infer these
from the product name or a different OnePlus 13 variant. This gate does not
authorize writes.

### 1. Produce and identify the kernel component

Fix the Actions workflow to collect the pinned `//common:kernel_aarch64` raw
`Image`, then verify its SHA-256 and provenance. The current workflow instead
asks the mixed-tree `//msm-kernel:sun_perf` target for `Image`; run `41781537334`
fails because that target has no `vmlinux` rule in mixed-tree mode. The selected
GKI Image path is not implemented yet. Separately determine the exact vendor
modules, DTB/DTBO, firmware, and version/KMI matching needed for a usable device
port. A raw Image alone is not a bootable Linux system.

### 2. Build a reproducible Arch rootfs — host/CI only

Choose and pin the Arch Linux ARM bootstrap source and package repositories;
verify signatures and record package versions. Create a minimal AArch64 rootfs
recipe with only required base packages and services. Keep credentials and
device data out of the build. Validate package installation, init, filesystem
layout, and service startup in a host-side test environment; this is not proof
that the phone can boot it.

### 3. Device integration research

Map the kernel/module interfaces, storage, USB, networking, firmware, power,
and input/display requirements. Start headless. Treat graphics, audio, camera,
modem, suspend, and thermal behavior as separate hardware gates. Do not copy
Android Bionic-only vendor libraries into Arch and call that compatibility.

### 4. Resolve boot, FBE, and handoff design

The existing Android-unlock-then-Linux-handoff flow is a hypothesis, not a
validated implementation. Establish whether Android credential UI, `vold`,
KeyMint/TEE, and required vendor services can safely unlock Android data before
Linux userspace takes over. Never capture the credential. Also determine how
the rootfs is mounted and how Android can still boot and recover.

### 5. Define install, update, and recovery

Only after the previous gates pass, design a reversible installer, explicit
Android-A maintenance path, OTA blocking while B is Linux, and tested fallback
to Android. Each write must have an exact partition target, backup/recovery
procedure, and separate user approval. Do not treat a read-only block flag as
durable OTA protection.

### 6. End-user quality gate

Do not call this ready until the rootfs build is reproducible; boot and fallback
are tested on the exact supported SKU; required hardware works to a declared
scope; Android FBE remains intact; OTA/update behavior is controlled; recovery
is tested; and the user-facing package has checksums, provenance, update
instructions, and limitations. A desktop is not a release requirement unless
graphics support is independently proven.

## Current blockers

- No exact device SKU, partition map, boot-chain facts, or target-device test.
- No successful Kleaf Image artifact; the current mixed-tree Image target fails.
- No validated matching `sun/perf` modules or OnePlus 13 Linux hardware port.
- No Arch rootfs recipe, package pin set, boot integration, installer, OTA guard,
  or recovery procedure.
- The A/B and Android credential handoff concepts remain unproven. This plan
  does not authorize flashing or any other device write.
