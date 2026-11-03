#!/usr/bin/env bash
# Fetch the pinned, sparse OnePlus Kleaf rule package into an existing workspace.
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
WORKDIR="${KERNEL_WORKSPACE:?Set KERNEL_WORKSPACE to the repo workspace root}"
source "$PROJECT_ROOT/ci/kleaf/pins.env"

REPO_URL="https://github.com/OnePlusOSS/android_kernel_modules_and_devicetree_oneplus_sm8750.git"
SRC="$WORKDIR/op13-oplus-kleaf-rules"
KPLAT="$SRC/kernel_platform"
PACKAGE="$KPLAT/oplus/bazel"
COMMON_LINK="$KPLAT/common"
COMMON="$WORKDIR/common"
DEST="$WORKDIR/build/kernel/oplus"

for required in "$WORKDIR/build/kernel/kleaf/kernel.bzl" "$COMMON/Makefile" "$WORKDIR/tools/bazel"; do
    if [ ! -e "$required" ]; then
        echo "[!] Missing expected kernel workspace path: $required" >&2
        exit 1
    fi
done

if [ ! -e "$SRC" ]; then
    git clone --depth=1 --filter=blob:none --no-checkout "$REPO_URL" "$SRC"
    git -C "$SRC" sparse-checkout init --cone
    git -C "$SRC" sparse-checkout set kernel_platform/oplus/bazel
    git -C "$SRC" fetch --depth=1 origin "$OPLUS_KLEAF_COMMIT"
    git -C "$SRC" checkout --detach FETCH_HEAD
fi

if ! git -C "$SRC" rev-parse --git-dir >/dev/null 2>&1; then
    echo "[!] OPlus helper source exists but is not a Git checkout: $SRC" >&2
    exit 1
fi
if [ "$(git -C "$SRC" remote get-url origin)" != "$REPO_URL" ]; then
    echo "[!] OPlus helper checkout has an unexpected origin." >&2
    exit 1
fi
if [ "$(git -C "$SRC" rev-parse HEAD)" != "$OPLUS_KLEAF_COMMIT" ]; then
    echo "[!] OPlus helper checkout is not pinned at $OPLUS_KLEAF_COMMIT." >&2
    exit 1
fi

for file in BUILD.bazel oplus_modules_define.bzl oplus_modules_dist.bzl oplus_modules_variant.bzl oplus_modules_variant.sh; do
    if [ ! -f "$PACKAGE/$file" ]; then
        echo "[!] Pinned OPlus package is missing $file" >&2
        exit 1
    fi
done

link_exact() {
    local link="$1" target="$2"
    if [ -L "$link" ]; then
        if [ "$(readlink -f "$link")" != "$(readlink -f "$target")" ]; then
            echo "[!] Existing symlink points elsewhere: $link" >&2
            exit 1
        fi
    elif [ -e "$link" ]; then
        echo "[!] Refusing to replace existing path: $link" >&2
        exit 1
    else
        ln -s "$target" "$link"
    fi
}

link_exact "$COMMON_LINK" "$COMMON"
link_exact "$DEST" "$PACKAGE"

EXPECTED_VARIANT=$(cat <<'EOF'
bazel_support_target = ["sun"]
bazel_support_variant = ["perf"]
OPLUS_FEATURES = ""
LINUX_KERNEL_VERSION = "6.6"
EOF
)
VARIANT_FILE="$PACKAGE/oplus_modules_variant.bzl"
PINNED_VARIANT="$(git -C "$SRC" show "$OPLUS_KLEAF_COMMIT:kernel_platform/oplus/bazel/oplus_modules_variant.bzl")"
CURRENT_VARIANT="$(cat "$VARIANT_FILE")"
if [ "$CURRENT_VARIANT" != "$EXPECTED_VARIANT" ]; then
    if [ "$CURRENT_VARIANT" != "$PINNED_VARIANT" ]; then
        echo "[!] OPlus variant file has unexpected edits; refusing to overwrite." >&2
        exit 1
    fi
    "$PACKAGE/oplus_modules_variant.sh" sun perf ""
fi

if [ "$(cat "$VARIANT_FILE")" != "$EXPECTED_VARIANT" ]; then
    echo "[!] Generated OPlus target settings differ from sun/perf expectations." >&2
    exit 1
fi

printf '[+] Pinned OPlus Kleaf rules prepared for sun/perf (%s).\n' "$OPLUS_KLEAF_COMMIT"
