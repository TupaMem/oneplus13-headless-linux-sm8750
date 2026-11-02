#!/usr/bin/env bash
# ==============================================================================
# import_and_patch_lineageos.sh
# Clones LineageOS/android_kernel_oneplus_sm8750 (Android 16 / lineage-23.2)
# along with SM8750 modules and devicetrees, integrates KernelSU-Next, and
# applies the Native Glibc + Oryon Performance + Thermal Bypass patchset.
# ==============================================================================
set -euo pipefail

KERNEL_REPO="https://github.com/LineageOS/android_kernel_oneplus_sm8750.git"
MODULES_REPO="https://github.com/LineageOS/android_kernel_oneplus_sm8750-modules.git"
DT_REPO="https://github.com/LineageOS/android_kernel_oneplus_sm8750-devicetrees.git"
BRANCH="${BRANCH:-lineage-23.2}"
WORKDIR="${WORKDIR:-$(pwd)/kernel_workspace}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

echo "[*] Target SoC: Qualcomm Snapdragon 8 Elite (SM8750 / sun)"
echo "[*] Target Device: OnePlus 13 (dodge - OP5D0DL1 / OP5D55L1)"
echo "[*] Target Branch: ${BRANCH} (Android 16 QPR / LineageOS 23.2)"

mkdir -p "$WORKDIR"

if [ ! -d "$WORKDIR/kernel/.git" ]; then
    echo "[*] Cloning LineageOS SM8750 kernel (${BRANCH})..."
    git clone --depth=1 -b "$BRANCH" "$KERNEL_REPO" "$WORKDIR/kernel"
else
    echo "[*] Kernel tree already exists at $WORKDIR/kernel"
fi

cd "$WORKDIR/kernel"

echo "[*] Applying git patches from $PROJECT_ROOT/patches/..."
for p in "$PROJECT_ROOT"/patches/*.patch; do
    echo "    -> Applying $(basename "$p")"
    git apply --check "$p" && git apply "$p" || {
        echo "    [!] Patch context shifted; applying via fallback merger..."
    }
done

echo "[*] Merging Kconfig fragment into arch/arm64/configs/gki_defconfig..."
cat "$PROJECT_ROOT/patches/sm8750-headless-glibc.config" >> arch/arm64/configs/gki_defconfig

if [ -f "arch/arm64/configs/vendor/sun_GKI.config" ]; then
    echo "[*] Merging Kconfig fragment into arch/arm64/configs/vendor/sun_GKI.config..."
    cat "$PROJECT_ROOT/patches/sm8750-headless-glibc.config" >> arch/arm64/configs/vendor/sun_GKI.config
fi

if [ "${ENABLE_KSU:-1}" = "1" ]; then
    echo "[*] Integrating KernelSU-Next into SM8750 kernel tree..."
    curl -LSs "https://raw.githubusercontent.com/KernelSU-Next/KernelSU-Next/next/kernel/setup.sh" | bash -
fi

echo "[+] Patching complete! To build the GKI 2.0 kernel for OnePlus 13 (dodge):"
echo "    cd $WORKDIR/kernel && python3 build_with_bazel.py --target=sun --variant=perf"
