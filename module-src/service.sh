#!/system/bin/sh
# ==============================================================================
# service.sh — Local read-only preview page
# ==============================================================================
MODDIR=${0%/*}

# Wait until Android boot completes
WAITED=0
while [ "$(getprop sys.boot_completed 2>/dev/null)" != "1" ] && [ "$WAITED" -lt 60 ]; do
    sleep 2
    WAITED=$((WAITED + 1))
done
if [ "$(getprop sys.boot_completed 2>/dev/null)" != "1" ]; then
    exit 0
fi

# Do not run a slot guardian or mutate boot partitions at startup.
# Serve only the static preview page on loopback when BusyBox is available.
for bb in /data/adb/ksu/bin/busybox /data/adb/ap/bin/busybox /data/adb/magisk/busybox /system/bin/busybox; do
    if [ -x "$bb" ]; then
        "$bb" httpd -p 127.0.0.1:8750 -h "${MODDIR}/webroot" 2>/dev/null || true
        break
    fi
done
