#!/usr/bin/env bash
# Stage an already-built glibc runtime. This script does not build or download glibc.
set -euo pipefail

: "${GLIBC_SOURCE:?Set GLIBC_SOURCE to a directory containing lib64/ld-linux-aarch64.so.1 and libc.so.6}"
GLIBC_ROOT="${GLIBC_ROOT:-/data/glibc}"
OVERWRITE="${OVERWRITE:-0}"
while [[ "$GLIBC_ROOT" != "/" && "$GLIBC_ROOT" == */ ]]; do
    GLIBC_ROOT="${GLIBC_ROOT%/}"
done
SOURCE_LIB="${GLIBC_SOURCE%/}/lib64"
TARGET_LIB="${GLIBC_ROOT%/}/lib64"

case "$GLIBC_ROOT" in
    /|/data|/system|/vendor|/product|/apex|"")
        echo "[!] Refusing unsafe GLIBC_ROOT: $GLIBC_ROOT" >&2
        exit 2
        ;;
    /*) ;;
    *)
        echo "[!] GLIBC_ROOT must be an absolute path." >&2
        exit 2
        ;;
esac
case "$OVERWRITE" in
    0|1) ;;
    *)
        echo "[!] OVERWRITE must be 0 or 1." >&2
        exit 2
        ;;
esac
case "$GLIBC_ROOT" in
    *[!A-Za-z0-9._/-]*|*/../*|*/..|*/./*|*/.)
        echo "[!] GLIBC_ROOT contains unsupported or traversal characters." >&2
        exit 2
        ;;
esac

LOADER="$SOURCE_LIB/ld-linux-aarch64.so.1"
if [ ! -x "$LOADER" ] || [ ! -f "$SOURCE_LIB/libc.so.6" ]; then
    echo "[!] GLIBC_SOURCE is incomplete: expected executable $LOADER and libc.so.6." >&2
    exit 1
fi

if [ -e "$GLIBC_ROOT" ]; then
    if [ -L "$GLIBC_ROOT" ] || [ ! -d "$GLIBC_ROOT" ]; then
        echo "[!] GLIBC_ROOT exists but is not a regular directory: $GLIBC_ROOT" >&2
        exit 1
    fi
    if [ -n "$(find "$GLIBC_ROOT" -mindepth 1 -maxdepth 1 -print -quit)" ] && [ "$OVERWRITE" != "1" ]; then
        echo "[!] GLIBC_ROOT is not empty; set OVERWRITE=1 only after reviewing its contents." >&2
        exit 1
    fi
fi

if command -v readelf >/dev/null 2>&1; then
    MACHINE="$(readelf -h "$LOADER" | awk -F: '/Machine:/ { sub(/^[[:space:]]+/, "", $2); print $2; exit }')"
    case "$MACHINE" in
        AArch64*) ;;
        *)
            echo "[!] Expected an AArch64 glibc loader, found: ${MACHINE:-unknown}" >&2
            exit 1
            ;;
    esac
fi

echo "[*] Staging existing AArch64 glibc files in $GLIBC_ROOT (no download/build)."
mkdir -p "$TARGET_LIB" "$GLIBC_ROOT/etc" "$GLIBC_ROOT/bin" "$GLIBC_ROOT/shm"
cp -a "$SOURCE_LIB/." "$TARGET_LIB/"

cat > "$GLIBC_ROOT/etc/nsswitch.conf" <<'EOF'
hosts: files dns
networks: files
passwd: files
group: files
shadow: files
EOF

cat > "$GLIBC_ROOT/etc/passwd" <<'EOF'
root:x:0:0:root:/root:/bin/sh
EOF
cat > "$GLIBC_ROOT/etc/group" <<'EOF'
root:x:0:
EOF

cat > "$GLIBC_ROOT/bin/glibc-run" <<'EOF'
#!/system/bin/sh
GLIBC_ROOT="${GLIBC_ROOT:-/data/glibc}"
LOADER="$GLIBC_ROOT/lib64/ld-linux-aarch64.so.1"
if [ ! -x "$LOADER" ]; then
    echo "[!] AArch64 glibc loader not found: $LOADER" >&2
    exit 1
fi
exec "$LOADER" --library-path "$GLIBC_ROOT/lib64" "$@"
EOF
chmod 0755 "$GLIBC_ROOT/bin/glibc-run"

echo "[+] Runtime files staged. This does not prove ABI compatibility with Android vendor libraries."
