#!/usr/bin/env bash
# Collect logs and, on success, only the raw common GKI Image and provenance.
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$PROJECT_ROOT/ci/kleaf/pins.env"
WORKSPACE="${KERNEL_WORKSPACE:?Set KERNEL_WORKSPACE}"
RUNNER_TEMP="${RUNNER_TEMP:?RUNNER_TEMP must be set}"
BUILD_LOG="${BUILD_LOG:-$RUNNER_TEMP/op13-gki-base-image-build.log}"
ARTIFACT_DIR="${ARTIFACT_DIR:-$RUNNER_TEMP/op13-gki-base-image-artifacts}"
ABI_GATE_STATUS="${ABI_GATE_STATUS:-$RUNNER_TEMP/op13-gki-abi-gate-passed}"
IMAGE_BUILD_STATUS="${IMAGE_BUILD_STATUS:-$RUNNER_TEMP/op13-gki-image-build-passed}"
USERNS_OVERLAY_STATUS="${USERNS_OVERLAY_STATUS:-$RUNNER_TEMP/op13-gki-userns-overlay-applied}"
IMAGE="$WORKSPACE/bazel-bin/common/kernel_aarch64/Image"

mkdir -p "$ARTIFACT_DIR/logs" "$ARTIFACT_DIR/source-inputs"
rm -f -- "$ARTIFACT_DIR/Image" "$ARTIFACT_DIR/SHA256SUMS"
if [ -s "$BUILD_LOG" ]; then
    cp -- "$BUILD_LOG" "$ARTIFACT_DIR/logs/build.log"
else
    printf 'Build log was not created.\n' > "$ARTIFACT_DIR/logs/build.log"
fi
cp -- "$PROJECT_ROOT/ci/kleaf/manifest.xml" "$ARTIFACT_DIR/source-inputs/manifest.xml"
cp -- "$PROJECT_ROOT/ci/kleaf/pins.env" "$ARTIFACT_DIR/source-inputs/pins.env"
cp -- "$PROJECT_ROOT/ci/kleaf/patches/0008-op13-gki-userns-config.patch" "$ARTIFACT_DIR/source-inputs/"
cp -- "$PROJECT_ROOT/ci/kleaf/patches/op13-userns.fragment" "$ARTIFACT_DIR/source-inputs/"
for input in \
    common/BUILD.bazel \
    common/build.config.gki.aarch64 \
    common/arch/arm64/configs/gki_defconfig \
    common/arch/arm64/configs/op13_userns.fragment; do
    if [ -f "$WORKSPACE/$input" ]; then
        mkdir -p "$ARTIFACT_DIR/source-inputs/$(dirname "$input")"
        cp -- "$WORKSPACE/$input" "$ARTIFACT_DIR/source-inputs/$input"
    fi
done

ABI_GATE_RESULT=no
COMMON_GKI_ABI_VALIDATED=no
USERNS_OVERLAY_APPLIED=no
USERNS_CONFIG_VERIFIED=no
if [ -f "$ABI_GATE_STATUS" ]; then
    ABI_GATE_RESULT=pass
    COMMON_GKI_ABI_VALIDATED=yes
    USERNS_CONFIG_VERIFIED=yes
fi
if [ -f "$USERNS_OVERLAY_STATUS" ]; then
    USERNS_OVERLAY_APPLIED=yes
fi
IMAGE_BUILD_SUCCEEDED=no
if [ -f "$IMAGE_BUILD_STATUS" ]; then
    IMAGE_BUILD_SUCCEEDED=yes
fi

BUILD_RESULT="Image not packaged; inspect build status and logs/build.log"
IMAGE_COLLECTED=no
if [ "$ABI_GATE_RESULT" = pass ] && [ "$IMAGE_BUILD_SUCCEEDED" = yes ] && [ -s "$IMAGE" ]; then
    cp -- "$IMAGE" "$ARTIFACT_DIR/Image"
    BUILD_RESULT="raw common GKI base Image collected"
    IMAGE_COLLECTED=yes
elif [ "$ABI_GATE_RESULT" != pass ]; then
    BUILD_RESULT="Image not packaged: common GKI ABI gate did not pass"
elif [ "$IMAGE_BUILD_SUCCEEDED" != yes ]; then
    BUILD_RESULT="Image not packaged: common GKI Image build did not complete"
else
    BUILD_RESULT="Image not packaged: Image output is missing or empty"
fi

cat > "$ARTIFACT_DIR/BUILD_INFO.txt" <<EOF
artifact_type=raw ARM64 common GKI base Image only
image_lineage=common GKI with project CONFIG_USER_NS=y overlay; not built with the OnePlus sun/perf profile
image_source_repository=kernel/common
image_source_commit=${KERNEL_COMMON_COMMIT}
build_target=//common:kernel_aarch64
build_config=common/build.config.gki.aarch64
build_overlay_patch=0008-op13-gki-userns-config.patch
build_defconfig_fragment=op13-userns.fragment
user_ns_requested=yes
user_ns_overlay_applied=${USERNS_OVERLAY_APPLIED}
user_ns_config_verified=${USERNS_CONFIG_VERIFIED}
build_make_goals=Image,Image.lz4,Image.gz,modules
common_gki_modules_goal_included=yes
abi_gate_target=//common:kernel_aarch64_abi_diff
abi_gate_status=${ABI_GATE_RESULT}
common_gki_abi_validated=${COMMON_GKI_ABI_VALIDATED}
oneplus_vendor_module_kmi_validated=no
image_build_succeeded=${IMAGE_BUILD_SUCCEEDED}
image_collected=${IMAGE_COLLECTED}
oneplus_kernel_commit_pinned_not_used_as_image_source=${KERNEL_COMMIT}
oneplus_modules_commit_pinned_not_built=${KERNEL_MODULES_COMMIT}
device_tree_commit_pinned_not_built=${DEVICE_TREE_COMMIT}
kernel_build_commit=${KERNEL_BUILD_COMMIT}
oplus_kleaf_commit_not_used=${OPLUS_KLEAF_COMMIT}
repo_tool_commit=${REPO_TOOL_COMMIT}
upstream_kernel_manifest_commit=${UPSTREAM_KERNEL_MANIFEST_COMMIT}
bazel_jobs=1
kleaf_make_jobs=1
sun_perf_vendor_modules_built=no
modules_install_built=no
boot_image_generated=no
abl_included=no
device_tested=no
flashable=no
result=${BUILD_RESULT}
EOF

cat > "$ARTIFACT_DIR/README.txt" <<'EOF'
GitHub Actions host-build artifact. Image, when present, is the raw ARM64
common GKI base Image with a project CONFIG_USER_NS=y fragment, compared
against the pinned common GKI ABI baseline. It is NOT a OnePlus sun/perf-configured
Image, and it is NOT boot.img, vendor_boot.img, or init_boot.img. The pinned
common target also requests common GKI modules, but packages only Image;
OnePlus sun/perf vendor modules and modules_install were not built. This file
is not flashable as packaged. No bootloader/ABL target or target-device test was run.
Verify SHA256SUMS before using or moving any file. This does not establish
OnePlus compatibility, bootability, matching vendor-module KMI, FBE/KeyMint
compatibility, recovery safety, graphics support, or OTA behavior.
EOF

(
    cd "$ARTIFACT_DIR"
    find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS
)
echo "artifact_files=true" >> "${GITHUB_OUTPUT:-/dev/null}"
printf '[+] Collected Actions artifact directory: %s\n' "$ARTIFACT_DIR"
