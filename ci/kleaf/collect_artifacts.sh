#!/usr/bin/env bash
# Collect logs and, on success, only the raw Image and build provenance.
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$PROJECT_ROOT/ci/kleaf/pins.env"
WORKSPACE="${KERNEL_WORKSPACE:?Set KERNEL_WORKSPACE}"
RUNNER_TEMP="${RUNNER_TEMP:?RUNNER_TEMP must be set}"
BUILD_LOG="${BUILD_LOG:-$RUNNER_TEMP/op13-sun-perf-build.log}"
ARTIFACT_DIR="${ARTIFACT_DIR:-$RUNNER_TEMP/op13-sun-perf-artifacts}"
IMAGE="$WORKSPACE/bazel-bin/msm-kernel/sun_perf/arch/arm64/boot/Image"

mkdir -p "$ARTIFACT_DIR/logs" "$ARTIFACT_DIR/source-inputs"
if [ -s "$BUILD_LOG" ]; then
    cp -- "$BUILD_LOG" "$ARTIFACT_DIR/logs/build.log"
else
    printf 'Build log was not created.\n' > "$ARTIFACT_DIR/logs/build.log"
fi
cp -- "$PROJECT_ROOT/ci/kleaf/manifest.xml" "$ARTIFACT_DIR/source-inputs/manifest.xml"
cp -- "$PROJECT_ROOT/ci/kleaf/pins.env" "$ARTIFACT_DIR/source-inputs/pins.env"
cp -- "$PROJECT_ROOT/ci/kleaf/patches/0003-kleaf-deduplicate-module-outs.patch" "$ARTIFACT_DIR/source-inputs/"
cp -- "$PROJECT_ROOT/ci/kleaf/patches/0004-kleaf-use-kernel-package-root.patch" "$ARTIFACT_DIR/source-inputs/"
cp -- "$PROJECT_ROOT/ci/kleaf/patches/0005-oplus-ufs-sandbox-includes.patch" "$ARTIFACT_DIR/source-inputs/"
cp -- "$PROJECT_ROOT/ci/kleaf/patches/sun-perf-headless.config" "$ARTIFACT_DIR/source-inputs/"

BUILD_RESULT="Image unavailable; inspect logs/build.log"
if [ -s "$IMAGE" ]; then
    cp -- "$IMAGE" "$ARTIFACT_DIR/Image"
    BUILD_RESULT="raw Image collected"
fi

cat > "$ARTIFACT_DIR/BUILD_INFO.txt" <<EOF
artifact_type=raw ARM64 kernel Image only
source_commit=${KERNEL_COMMIT}
modules_commit=${KERNEL_MODULES_COMMIT}
device_tree_commit=${DEVICE_TREE_COMMIT}
kernel_common_commit=${KERNEL_COMMON_COMMIT}
kernel_build_commit=${KERNEL_BUILD_COMMIT}
oplus_kleaf_commit=${OPLUS_KLEAF_COMMIT}
repo_tool_commit=${REPO_TOOL_COMMIT}
upstream_kernel_manifest_commit=${UPSTREAM_KERNEL_MANIFEST_COMMIT}
build_targets=//msm-kernel:sun_perf,//msm-kernel:sun_perf_modules_install
bazel_jobs=1
kleaf_make_jobs=1
boot_image_generated=no
abl_included=no
device_tested=no
flashable=no
result=${BUILD_RESULT}
EOF

cat > "$ARTIFACT_DIR/README.txt" <<'EOF'
GitHub Actions host-build artifact. Image, when present, is a raw ARM64 Linux
kernel Image. It is NOT boot.img, vendor_boot.img, or init_boot.img and is not
flashable as packaged. No bootloader/ABL target or target-device test was run.
Verify SHA256SUMS before using or moving any file. This does not establish
bootability, FBE/KeyMint compatibility, recovery safety, graphics support, or
OTA behavior.
EOF

(
    cd "$ARTIFACT_DIR"
    find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS
)
echo "artifact_files=true" >> "${GITHUB_OUTPUT:-/dev/null}"
printf '[+] Collected Actions artifact directory: %s\n' "$ARTIFACT_DIR"
