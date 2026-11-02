#!/system/bin/sh
# Read-only Android/OnePlus inventory for the proposed A=Android, B=Linux design.
# It deliberately does not read key blobs or device identifiers, and never
# changes partition flags, mounts, slots, files, or boot state.
set -u

PARTITION_DIR="${PARTITION_DIR:-/dev/block/by-name}"

if ! command -v getprop >/dev/null 2>&1; then
    echo "[!] Android getprop is unavailable; run this on the target Android system." >&2
    exit 2
fi

printf 'report=op13-android-preflight-v1\n'
printf 'mode=read-only\n'
printf 'secrets_collected=false\n'

print_property() {
    name="$1"
    value="$(getprop "$name" 2>/dev/null || true)"
    [ -n "$value" ] || value="unknown"
    printf 'property.%s=%s\n' "$name" "$value"
}

for name in \
    ro.product.device \
    ro.board.platform \
    ro.build.version.release \
    ro.build.version.sdk \
    ro.boot.slot_suffix \
    ro.boot.verifiedbootstate \
    ro.boot.vbmeta.device_state \
    ro.boot.flash.locked \
    ro.crypto.state \
    ro.crypto.type \
    ro.crypto.metadata.enabled \
    ro.crypto.volume.options; do
    print_property "$name"
done

if [ -r /proc/mounts ]; then
    awk '$2 == "/data" { print "data.filesystem=" $3; print "data.mount_options=" $4; found=1 }
         END { if (!found) print "data.mount=unknown" }' /proc/mounts
else
    printf 'data.mount=unknown\n'
fi

if command -v df >/dev/null 2>&1; then
    df -Pk /data 2>/dev/null | awk 'NR == 2 {
        print "data.total_kb=" $2;
        print "data.available_kb=" $4;
        found=1
    } END { if (!found) print "data.capacity=unknown" }'
else
    printf 'data.capacity=unknown\n'
fi

for filesystem in ext4 f2fs; do
    if [ -r /proc/filesystems ] && grep -Eq "[[:space:]]${filesystem}$" /proc/filesystems; then
        printf 'filesystem.%s=available\n' "$filesystem"
    else
        printf 'filesystem.%s=unknown-or-unavailable\n' "$filesystem"
    fi
done

if [ -e /dev/block/loop-control ] || [ -e /dev/loop-control ]; then
    printf 'loop_device=present\n'
else
    printf 'loop_device=unknown-or-absent\n'
fi

FSTAB_FOUND=0
for fstab in /vendor/etc/fstab* /odm/etc/fstab* /system/etc/fstab* \
    /first_stage_ramdisk/fstab* /fstab*; do
    [ -f "$fstab" ] || continue
    awk -v path="$fstab" '
        $2 == "/data" {
            print "fstab.data.file=" path;
            print "fstab.data.filesystem=" $3;
            print "fstab.data.mount_flags=" $4;
            print "fstab.data.fs_mgr_flags=" $5;
            found=1
        }
        END { if (found) exit 0; exit 1 }
    ' "$fstab" && FSTAB_FOUND=1
done
if [ "$FSTAB_FOUND" -eq 0 ]; then
    printf 'fstab.data=not-found-in-standard-paths\n'
fi

if command -v lpdump >/dev/null 2>&1; then
    printf 'tool.lpdump=present (not executed)\n'
else
    printf 'tool.lpdump=absent\n'
fi

printf 'partition_dir=%s\n' "$PARTITION_DIR"
for partition in \
    boot_a boot_b init_boot_a init_boot_b vendor_boot_a vendor_boot_b \
    dtbo_a dtbo_b vbmeta_a vbmeta_b super userdata metadata misc \
    system_a system_b vendor_a vendor_b system_dlkm_a system_dlkm_b \
    vendor_dlkm_a vendor_dlkm_b; do
    node="${PARTITION_DIR}/${partition}"
    if [ ! -e "$node" ]; then
        printf 'partition.%s=not-visible\n' "$partition"
        continue
    fi

    path="$(readlink -f "$node" 2>/dev/null || printf '%s' "$node")"
    size="unknown"
    read_only="unknown"
    if command -v blockdev >/dev/null 2>&1; then
        size="$(blockdev --getsize64 "$node" 2>/dev/null || printf 'unknown')"
        read_only="$(blockdev --getro "$node" 2>/dev/null || printf 'unknown')"
    fi
    printf 'partition.%s.path=%s\n' "$partition" "$path"
    printf 'partition.%s.size_bytes=%s\n' "$partition" "$size"
    printf 'partition.%s.read_only=%s\n' "$partition" "$read_only"
done

MAPPER_DIR="${MAPPER_DIR:-/dev/block/mapper}"
MAPPER_FOUND=0
for node in "$MAPPER_DIR"/*; do
    [ -e "$node" ] || continue
    MAPPER_FOUND=1
    name="${node##*/}"
    path="$(readlink -f "$node" 2>/dev/null || printf '%s' "$node")"
    size="unknown"
    read_only="unknown"
    if command -v blockdev >/dev/null 2>&1; then
        size="$(blockdev --getsize64 "$node" 2>/dev/null || printf 'unknown')"
        read_only="$(blockdev --getro "$node" 2>/dev/null || printf 'unknown')"
    fi
    printf 'mapper.%s.path=%s\n' "$name" "$path"
    printf 'mapper.%s.size_bytes=%s\n' "$name" "$size"
    printf 'mapper.%s.read_only=%s\n' "$name" "$read_only"
done
if [ "$MAPPER_FOUND" -eq 0 ]; then
    printf 'mapper=not-visible\n'
fi

printf 'warning=inventory-only; no layout, encryption, OTA, or recovery assumptions are validated\n'
exit 0
