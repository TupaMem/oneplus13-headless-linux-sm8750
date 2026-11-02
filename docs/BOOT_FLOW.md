# Proposed boot flow: Android in A, glibc Linux in B

**Status: design recorded; hardware implementation not started.** No key material,
partition table, boot image, or system image is modified by this design document
or the preflight script.

## Accepted target

- Slot A remains the normal Android ROM.
- Slot B boots a LineageOS-derived kernel and eventually a glibc Linux rootfs.
- Android `/data` encryption remains enabled. No raw key or PIN is stored in the
  module, boot image, logs, or command line.
- Android automatic OTA is blocked while B is Linux. Any Android maintenance is
  a separate, manually reviewed procedure that must preserve B.
- The Android lock screen is the intended credential UI. SDDM starts only after
  Android has unlocked `/data` and Linux has mounted its rootfs.

## Proposed sequence

```text
Boot ROM / ABL selects B
  → B boot image: LineageOS kernel + experimental initramfs
  → matching Android early-boot components initialize storage and KeyMint
  → Android lock screen requests the user's credential locally
  → Android's vold / credential / KeyMint flow unlocks the required /data keys
  → a privileged, audited handoff mounts the Linux rootfs and starts glibc
  → Linux graphical session (Wayland); optionally SDDM for Linux login
```

The kernel does not decrypt Android user data by itself. The credential must go
through the Android userspace and hardware-backed KeyMint/TEE flow. Existing
wrapped key blobs stay in Android-managed storage; copying them to the module
does not make them independently usable. `vold` has no standalone lock-screen
UI, so the handoff must reuse sufficient Android credential UI/services or
implement a device-specific client. It must not capture the PIN into a file,
property, log, environment variable, or command-line argument.

If the Linux rootfs is stored inside Android `/data`, it cannot be mounted until
the required Android data-encryption layers have been unlocked. This is the
reason Android authentication precedes SDDM. A rootfs on another device or
partition changes the storage design but does not remove the need to assess its
encryption and boot-time availability.

## OTA policy and slot ownership

Android A/B OTA normally writes the inactive slot. When Android A is active,
that is commonly B, so a standard OTA conflicts with the Linux installation.
The Android updater and `update_engine` must not perform unattended updates.
This policy cannot prevent writes made through recovery, fastboot, a manually
flashed package, or vendor service tools. `blockdev --setro` is not a durable
security boundary and must not be treated as a backup or safety guarantee.

Before any Android update workflow is designed, it must identify the exact
images and dynamic-partition metadata written by the target ROM, prove that the
workflow writes only the intended Android slot, and verify a recovery path. No
OTA, slot switch, or partition-writing command is implemented in the preview
module.

## Wayland is a separate gate

Reaching glibc does not establish graphics support. Before promising a desktop,
verify the actual kernel exposes a usable display connector and DRM/KMS device,
input/touch devices, and a compatible Mesa/GBM path for the GPU. A KGSL node or
vendor OpenCL/Vulkan library alone does not prove a Wayland compositor can
drive the phone display. Android vendor libraries may depend on Bionic and
cannot be assumed to load into glibc.

## Implementation gates

1. **Read-only device inventory** — run `scripts/android_preflight.sh` on the
   exact ROM/device; review slot, crypto properties, `/data` mount, partition
   nodes/sizes, and available filesystems. It does not collect PINs, keys,
   serial numbers, or raw partition contents.
2. **Unlock feasibility** — obtain the matching LineageOS init/fstab, `vold`,
   KeyMint/credential components and vendor HAL dependencies. Establish the
   correct Android lock-screen flow while booting B. No guessed shell command
   is an acceptable substitute.
3. **Handoff prototype** — on a recoverable test device, unlock `/data`, mount a
   harmless test image, then perform and test the userspace handoff. Do not
   flash a Linux boot image yet.
4. **Boot and failure recovery** — test failed PIN, corrupt/missing rootfs,
   reboot loops, fallback to A, and recovery using the device's actual
   bootloader/service procedure.
5. **Graphics** — validate DRM/KMS, touch and Wayland independently.
6. **OTA maintenance** — implement and test an explicit Android-A update path
   only after the previous stages pass. Automatic OTA remains off.

Until these gates pass, the correct behavior is fail-closed: no credential
capture, no partition writes, no slot switching, and no claim of hard-brick
protection.
