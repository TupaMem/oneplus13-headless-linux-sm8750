#!/usr/bin/env bash
# ==============================================================================
# import_and_patch_lineageos.sh
# Clones LineageOS/android_kernel_oneplus_sm8750 (Android 16 / lineage-23.2)
# Applies the kernel patches and Kconfig fragment. KernelSU and the thermal
# bypass are opt-in; the latter is intentionally not enabled by default.
# ==============================================================================
set -euo pipefail

KERNEL_REPO="https://github.com/LineageOS/android_kernel_oneplus_sm8750.git"
BRANCH="${BRANCH:-lineage-23.2}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
WORKDIR="${WORKDIR:-${PROJECT_ROOT}/kernel_workspace}"
ENABLE_KSU="${ENABLE_KSU:-0}"
ENABLE_THERMAL_BYPASS="${ENABLE_THERMAL_BYPASS:-0}"

case "$ENABLE_KSU" in 0|1) ;; *) echo "[!] ENABLE_KSU must be 0 or 1." >&2; exit 1 ;; esac
case "$ENABLE_THERMAL_BYPASS" in 0|1) ;; *) echo "[!] ENABLE_THERMAL_BYPASS must be 0 or 1." >&2; exit 1 ;; esac
case "${ALLOW_KCONFIG_OVERRIDES:-0}" in 0|1) ;; *) echo "[!] ALLOW_KCONFIG_OVERRIDES must be 0 or 1." >&2; exit 1 ;; esac

echo "[*] Target SoC: Qualcomm Snapdragon 8 Elite (SM8750 / sun)"
echo "[*] Target Device: OnePlus 13 (dodge - OP5D0DL1 / OP5D55L1)"
echo "[*] Target Branch: ${BRANCH} (Android 16 QPR / LineageOS 23.2)"

mkdir -p "$WORKDIR"

if [ ! -e "$WORKDIR/kernel" ]; then
    echo "[*] Cloning LineageOS SM8750 kernel (${BRANCH})..."
    git clone --depth=1 -b "$BRANCH" "$KERNEL_REPO" "$WORKDIR/kernel"
elif ! git -C "$WORKDIR/kernel" rev-parse --git-dir >/dev/null 2>&1; then
    echo "[!] $WORKDIR/kernel exists but is not a Git checkout; refusing to use it." >&2
    exit 1
else
    echo "[*] Kernel tree already exists at $WORKDIR/kernel"
fi

cd "$WORKDIR/kernel"

for required_file in arch/arm64/configs/gki_defconfig drivers/thermal/thermal_core.c; do
    if [ ! -f "$required_file" ]; then
        echo "[!] Expected kernel file not found: $required_file" >&2
        exit 1
    fi
done

echo "[*] Applying git patches from $PROJECT_ROOT/patches/..."
for p in "$PROJECT_ROOT"/patches/*.patch; do
    [ -f "$p" ] || continue
    if [[ "$(basename "$p")" == "0002-sm8750-oryon-thermal-bypass.patch" && "$ENABLE_THERMAL_BYPASS" != "1" ]]; then
        if git apply --reverse --check "$p"; then
            echo "[!] Thermal bypass is already applied in this tree, but ENABLE_THERMAL_BYPASS=0." >&2
            echo "    Inspect/revert the existing change manually; this script will not alter it." >&2
            exit 1
        fi
        echo "[i] Skipping optional thermal bypass (set ENABLE_THERMAL_BYPASS=1 to opt in)."
        continue
    fi
    echo "    -> Applying $(basename "$p")"
    if git apply --check "$p"; then
        git apply "$p"
    elif git apply --reverse --check "$p"; then
        echo "    [i] Already applied."
    else
        echo "[!] Patch does not apply cleanly (and is not already applied): $p" >&2
        exit 1
    fi
done

MERGE_ARGS=()
if [ "${ALLOW_KCONFIG_OVERRIDES:-0}" = "1" ]; then
    MERGE_ARGS+=(--allow-overrides)
fi
echo "[*] Merging Kconfig fragment into arch/arm64/configs/gki_defconfig..."
python3 "$SCRIPT_DIR/merge_kconfig.py" "${MERGE_ARGS[@]}" \
    arch/arm64/configs/gki_defconfig "$PROJECT_ROOT/patches/sm8750-headless-glibc.config"

if [ -f "arch/arm64/configs/vendor/sun_GKI.config" ]; then
    echo "[*] Merging Kconfig fragment into arch/arm64/configs/vendor/sun_GKI.config..."
    python3 "$SCRIPT_DIR/merge_kconfig.py" "${MERGE_ARGS[@]}" \
        arch/arm64/configs/vendor/sun_GKI.config "$PROJECT_ROOT/patches/sm8750-headless-glibc.config"
fi

if [ "$ENABLE_KSU" = "1" ]; then
    : "${KSU_SETUP_URL:?Set KSU_SETUP_URL to a reviewed immutable setup-script URL}"
    : "${KSU_SETUP_SHA256:?Set KSU_SETUP_SHA256 to the reviewed script SHA-256}"
    if [[ ! "$KSU_SETUP_SHA256" =~ ^[[:xdigit:]]{64}$ ]]; then
        echo "[!] KSU_SETUP_SHA256 must be a 64-character SHA-256 hex digest." >&2
        exit 1
    fi
    command -v curl >/dev/null
    command -v sha256sum >/dev/null
    KSU_SCRIPT="$(mktemp)"
    trap 'rm -f "$KSU_SCRIPT"' EXIT
    echo "[*] Downloading the explicitly pinned KernelSU setup script..."
    curl --fail --location --silent --show-error "$KSU_SETUP_URL" --output "$KSU_SCRIPT"
    ACTUAL_SHA256="$(sha256sum "$KSU_SCRIPT" | awk '{print $1}')"
    if [ "$ACTUAL_SHA256" != "${KSU_SETUP_SHA256,,}" ]; then
        echo "[!] KernelSU setup-script SHA-256 mismatch; refusing to execute it." >&2
        exit 1
    fi
    bash "$KSU_SCRIPT"
fi

echo "[+] Patch/config integration complete. This does not validate a device build."
echo "    ENABLE_KSU defaults to 0; ENABLE_THERMAL_BYPASS defaults to 0."
echo "    To build the GKI 2.0 kernel for OnePlus 13 (dodge):"
echo "    cd $WORKDIR/kernel && python3 build_with_bazel.py --target=sun --variant=perf"
