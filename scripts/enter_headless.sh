#!/system/bin/sh
# ==============================================================================
# enter_headless.sh
# Runtime Android 16 (LineageOS 23.2) Headless Mode
# Target: OnePlus 13 (dodge / Snapdragon 8 Elite SM8750)
# Stops only selected Android UI/background services that were running before
# entry. It does not change thermal policy, clocks, GPU, swap, or sysctls.
# ==============================================================================
set -eu

MODE="${1:-start}"
STATE_DIR="/data/adb/op13-headless"
STATE_FILE="${STATE_DIR}/services"
SERVICES="zygote zygote_secondary surfaceflinger lmkd"

if [ "$(id -u)" != "0" ]; then
    echo "[!] Run this script as root." >&2
    exit 1
fi

if [ ! -x /system/bin/setprop ] || ! command -v getprop >/dev/null 2>&1; then
    echo "[!] Android init tools were not found; this script requires Android userspace." >&2
    exit 1
fi

if [ "$MODE" = "restore" ]; then
    if [ ! -f "$STATE_FILE" ]; then
        echo "[i] No saved headless service state; nothing to restore."
        exit 0
    fi
    echo "[*] Restarting only services that were running before headless mode..."
    while IFS= read -r service; do
        case "$service" in
            zygote|zygote_secondary|surfaceflinger|lmkd)
                /system/bin/setprop "ctl.start" "$service"
                ;;
            *)
                echo "[!] Ignoring unexpected service name in state file: $service" >&2
                ;;
        esac
    done < "$STATE_FILE"
    rm -f "$STATE_FILE"
    echo "[+] Previously running Android services were requested to start."
    exit 0
fi

if [ "$MODE" != "start" ]; then
    echo "Usage: $0 [start|restore]" >&2
    exit 2
fi

if [ -e "$STATE_FILE" ]; then
    echo "[i] Headless mode already has a saved service state; use '$0 restore' first."
    exit 0
fi

echo "[*] Ensuring Dropbear SSH / ADB TCP persistence before stopping UI services..."
if [ -x /data/glibc/bin/dropbear ]; then
    /data/glibc/bin/dropbear -R -p 2222
fi

mkdir -p "$STATE_DIR"
chmod 0700 "$STATE_DIR"
STATE_TMP="${STATE_FILE}.tmp.$$"
umask 077
if ! (set -C; : > "$STATE_TMP") 2>/dev/null; then
    echo "[!] Could not safely create state file $STATE_TMP" >&2
    exit 1
fi
for service in $SERVICES; do
    if [ "$(getprop "init.svc.$service" 2>/dev/null || true)" = "running" ]; then
        printf '%s\n' "$service" >> "$STATE_TMP"
    fi
done
mv "$STATE_TMP" "$STATE_FILE"

echo "[*] Stopping Android UI/background services recorded in $STATE_FILE..."
while IFS= read -r service; do
    /system/bin/setprop "ctl.stop" "$service"
done < "$STATE_FILE"

echo "[+] Selected services stopped. Thermal controls, clocks, GPU and swap were left unchanged."
