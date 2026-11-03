#!/usr/bin/env bash
# Reproducible, single-job host build. Produces only a raw kernel Image.
set -Eeuo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$PROJECT_ROOT/ci/kleaf/pins.env"
WORKSPACE="${KERNEL_WORKSPACE:?Set KERNEL_WORKSPACE to a fresh workspace path}"
RUNNER_TEMP="${RUNNER_TEMP:?RUNNER_TEMP must be set by the CI runner}"
BUILD_LOG="${BUILD_LOG:-$RUNNER_TEMP/op13-sun-perf-build.log}"
ARTIFACT_DIR="${ARTIFACT_DIR:-$RUNNER_TEMP/op13-sun-perf-artifacts}"
REPO_TOOL_DIR="$RUNNER_TEMP/git-repo-$REPO_TOOL_COMMIT"
MANIFEST_REPO="$RUNNER_TEMP/op13-kernel-manifest"
MANIFEST_URL="https://gerrit.googlesource.com/git-repo"

case "$WORKSPACE" in
    "$PROJECT_ROOT"|"$PROJECT_ROOT"/*)
        echo "[!] KERNEL_WORKSPACE must be outside the checked-out project." >&2
        exit 2
        ;;
esac
if [ -d "$WORKSPACE" ] && [ -n "$(find "$WORKSPACE" -mindepth 1 -maxdepth 1 -print -quit)" ]; then
    echo "[!] Refusing to use a non-empty workspace: $WORKSPACE" >&2
    exit 2
fi
if [ -e "$REPO_TOOL_DIR" ] || [ -e "$MANIFEST_REPO" ]; then
    echo "[!] Refusing to overwrite existing temporary repo inputs." >&2
    exit 2
fi
mkdir -p "$WORKSPACE" "$(dirname "$BUILD_LOG")" "$ARTIFACT_DIR"
exec > >(tee -a "$BUILD_LOG") 2>&1

echo "[*] Building pinned OnePlus 13 sun/perf kernel on the Actions runner."
echo "[*] No boot image, ABL, DTC, ABI target, device access, or flash step."
echo "[*] Kernel revision: $KERNEL_COMMIT"
echo "[*] Single-job build; KLEAF_MAKE_JOBS=1."

# Use a pinned repo client. The manifest itself is a committed local lockfile,
# not the mutable branch head of the Android kernel manifest repository.
git init -q "$REPO_TOOL_DIR"
git -C "$REPO_TOOL_DIR" remote add origin "$MANIFEST_URL"
git -C "$REPO_TOOL_DIR" fetch --depth=1 origin "$REPO_TOOL_COMMIT"
git -C "$REPO_TOOL_DIR" checkout --quiet --detach FETCH_HEAD
if [ "$(git -C "$REPO_TOOL_DIR" rev-parse HEAD)" != "$REPO_TOOL_COMMIT" ]; then
    echo "[!] repo tool revision mismatch." >&2
    exit 1
fi
printf '%s  %s\n' "$REPO_LAUNCHER_SHA256" "$REPO_TOOL_DIR/repo" | sha256sum --check
python3 "$REPO_TOOL_DIR/repo" --version

# repo expects its manifest to be served by a Git repository. Create a fresh,
# local, immutable input repository from the tracked lockfile.
mkdir -p "$MANIFEST_REPO"
git -C "$MANIFEST_REPO" init -q -b locked
cp "$PROJECT_ROOT/ci/kleaf/manifest.xml" "$MANIFEST_REPO/default.xml"
git -C "$MANIFEST_REPO" add default.xml
git -C "$MANIFEST_REPO" -c user.name='OP13 CI' -c user.email='ci@localhost' commit -q -m 'Pinned kernel build manifest'

cd "$WORKSPACE"
python3 "$REPO_TOOL_DIR/repo" init \
    --manifest-url="file://$MANIFEST_REPO" \
    --manifest-branch=locked \
    --repo-url="$MANIFEST_URL" \
    --repo-rev="$REPO_TOOL_COMMIT"
python3 "$REPO_TOOL_DIR/repo" sync --jobs=4 --no-clone-bundle

assert_revision() {
    local directory="$1" expected="$2" actual
    actual="$(git -C "$directory" rev-parse HEAD)"
    if [ "$actual" != "$expected" ]; then
        echo "[!] Revision mismatch in $directory: expected $expected, got $actual" >&2
        exit 1
    fi
}
assert_revision "$WORKSPACE/msm-kernel" "$KERNEL_COMMIT"
assert_revision "$WORKSPACE/kernel/oneplus/sm8750-modules" "$KERNEL_MODULES_COMMIT"
assert_revision "$WORKSPACE/kernel/oneplus/sm8750-devicetrees" "$DEVICE_TREE_COMMIT"
assert_revision "$WORKSPACE/common" "$KERNEL_COMMON_COMMIT"
assert_revision "$WORKSPACE/build/kernel" "$KERNEL_BUILD_COMMIT"

free_kb="$(df -Pk "$WORKSPACE" | awk 'END {print $4}')"
if [ "$free_kb" -lt $((20 * 1024 * 1024)) ]; then
    echo "[!] Less than 20 GiB remains after source sync; refusing to start Kleaf." >&2
    df -h "$WORKSPACE" >&2
    exit 1
fi
df -h "$WORKSPACE"

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

link_exact "$WORKSPACE/sm8750" "$WORKSPACE/msm-kernel"
link_exact "$WORKSPACE/sm8750-modules" "$WORKSPACE/kernel/oneplus/sm8750-modules"
link_exact "$WORKSPACE/sm8750-devicetrees" "$WORKSPACE/kernel/oneplus/sm8750-devicetrees"
DEVICETREE_VENDOR="$WORKSPACE/vendor/qcom/kernel/arch/arm64/boot/dts/vendor"
mkdir -p "$(dirname "$DEVICETREE_VENDOR")"
link_exact "$DEVICETREE_VENDOR" "$WORKSPACE/kernel/oneplus/sm8750-devicetrees"
if [ ! -f "$DEVICETREE_VENDOR/BUILD.bazel" ] || [ ! -f "$DEVICETREE_VENDOR/qcom/platform_map.bzl" ]; then
    echo "[!] Pinned device-tree package is missing its Kleaf BUILD or qcom platform map." >&2
    exit 1
fi
link_exact "$WORKSPACE/build/msm_kernel_extensions.bzl" "$WORKSPACE/msm-kernel/msm_kernel_extensions.bzl"
KERNEL_WORKSPACE="$WORKSPACE" bash "$PROJECT_ROOT/ci/kleaf/prepare_oplus_workspace.sh"

for patch in \
    "$PROJECT_ROOT/ci/kleaf/patches/0003-kleaf-deduplicate-module-outs.patch" \
    "$PROJECT_ROOT/ci/kleaf/patches/0004-kleaf-use-kernel-package-root.patch"; do
    git -C "$WORKSPACE/msm-kernel" apply --unidiff-zero --check "$patch"
    git -C "$WORKSPACE/msm-kernel" apply --unidiff-zero "$patch"
done
python3 "$PROJECT_ROOT/scripts/merge_kconfig.py" \
    "$WORKSPACE/msm-kernel/arch/arm64/configs/gki_defconfig" \
    "$PROJECT_ROOT/ci/kleaf/patches/sun-perf-headless.config"
git -C "$WORKSPACE/msm-kernel" diff --check

export JAVA_HOME="$WORKSPACE/prebuilts/jdk/jdk11/linux-x86"
export PATH="$JAVA_HOME/bin:$PATH"
export KLEAF_MAKE_JOBS=1
cd "$WORKSPACE"

"$WORKSPACE/tools/bazel" \
    --output_user_root="$RUNNER_TEMP/bazel-cache" \
    build \
    --jobs=1 \
    --color=no \
    --curses=no \
    --//msm-kernel:skip_abl=true \
    --//msm-kernel:skip_dtc=true \
    --//msm-kernel:skip_abi=true \
    --user_kmi_symbol_lists=//msm-kernel:android/abi_gki_aarch64_qcom \
    --ignore_missing_projects \
    --incompatible_sandbox_hermetic_tmp=false \
    --nozstd_dwarf_compression \
    //msm-kernel:sun_perf \
    //msm-kernel:sun_perf_modules_install

IMAGE="$WORKSPACE/bazel-bin/msm-kernel/sun_perf/arch/arm64/boot/Image"
if [ ! -s "$IMAGE" ]; then
    echo "[!] Bazel succeeded but the expected raw kernel Image is missing: $IMAGE" >&2
    exit 1
fi
cp -- "$IMAGE" "$ARTIFACT_DIR/Image"
echo "[+] Raw Image built: $(sha256sum "$ARTIFACT_DIR/Image")"
