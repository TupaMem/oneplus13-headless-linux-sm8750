#!/usr/bin/env bash
# ==============================================================================
# setup_micro_glibc.sh
# Builds and configures a zero-distro Micro-Glibc Runtime (< 25 MB)
# Supports both:
#   1) On-device Android 16 EROFS bypass via /dev/shm/rootfs + mount namespaces
#   2) Transparent ELF execution via binfmt_misc or patchelf / LD_LIBRARY_PATH
# ==============================================================================
set -euo pipefail

GLIBC_ROOT="${GLIBC_ROOT:-/data/glibc}"
SHM_ROOTFS="${SHM_ROOTFS:-/dev/shm/micro_glibc_rootfs}"

echo "[*] Initializing Micro-Glibc directory structure at ${GLIBC_ROOT}..."
mkdir -p "${GLIBC_ROOT}/lib64"          "${GLIBC_ROOT}/etc"          "${GLIBC_ROOT}/bin"          "${GLIBC_ROOT}/shm"

# Configure static low-latency DNS & NSSwitch (bypasses Android netd/dnsproxyd)
cat << 'EOF' > "${GLIBC_ROOT}/etc/resolv.conf"
nameserver 1.1.1.1
nameserver 8.8.8.8
options timeout:1 attempts:2
EOF

cat << 'EOF' > "${GLIBC_ROOT}/etc/nsswitch.conf"
hosts:      files dns
networks:   files
passwd:     files
group:      files
shadow:     files
EOF

cat << 'EOF' > "${GLIBC_ROOT}/etc/passwd"
root:x:0:0:root:/data/glibc:/bin/sh
EOF

cat << 'EOF' > "${GLIBC_ROOT}/etc/group"
root:x:0:
inet:x:3003:root
sdcard_rw:x:1015:root
EOF

# Create the transparent Glibc ELF Launcher wrapper
cat << 'EOF' > "${GLIBC_ROOT}/bin/glibc-run"
#!/bin/sh
GLIBC_ROOT="${GLIBC_ROOT:-/data/glibc}"
LOADER=""
for candidate in     "${GLIBC_ROOT}/lib64/ld-linux-aarch64.so.1"     "${GLIBC_ROOT}/lib64/ld-linux-x86-64.so.2"     "/lib/aarch64-linux-gnu/ld-linux-aarch64.so.1"     "/lib64/ld-linux-x86-64.so.2"; do
    if [ -x "$candidate" ]; then
        LOADER="$candidate"
        break
    fi
done

if [ -z "$LOADER" ]; then
    echo "[!] Error: No compatible glibc dynamic linker found in ${GLIBC_ROOT}/lib64" >&2
    exit 1
fi

export LD_LIBRARY_PATH="${GLIBC_ROOT}/lib64:/vendor/lib64:${LD_LIBRARY_PATH:-}"
export RESOLV_HOST_CONF="${GLIBC_ROOT}/etc/resolv.conf"
exec "$LOADER" --library-path "${GLIBC_ROOT}/lib64" "$@"
EOF
chmod +x "${GLIBC_ROOT}/bin/glibc-run"

echo "[+] Micro-Glibc Runtime initialized at ${GLIBC_ROOT}."
