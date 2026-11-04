#!/usr/bin/env bash
# Reproducible, single-job host build. ABI-gates and packages the common GKI base Image.
set -Eeuo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$PROJECT_ROOT/ci/kleaf/pins.env"
WORKSPACE="${KERNEL_WORKSPACE:?Set KERNEL_WORKSPACE to a fresh workspace path}"
RUNNER_TEMP="${RUNNER_TEMP:?RUNNER_TEMP must be set by the CI runner}"
BUILD_LOG="${BUILD_LOG:-$RUNNER_TEMP/op13-gki-base-image-build.log}"
ARTIFACT_DIR="${ARTIFACT_DIR:-$RUNNER_TEMP/op13-gki-base-image-artifacts}"
ABI_GATE_STATUS="${ABI_GATE_STATUS:-$RUNNER_TEMP/op13-gki-abi-gate-passed}"
IMAGE_BUILD_STATUS="${IMAGE_BUILD_STATUS:-$RUNNER_TEMP/op13-gki-image-build-passed}"
USERNS_OVERLAY_STATUS="${USERNS_OVERLAY_STATUS:-$RUNNER_TEMP/op13-gki-userns-overlay-applied}"
REPO_TOOL_DIR="$RUNNER_TEMP/git-repo-$REPO_TOOL_COMMIT"
MANIFEST_REPO="$RUNNER_TEMP/op13-kernel-manifest"
MANIFEST_URL="https://gerrit.googlesource.com/git-repo"

rm -f -- "$ABI_GATE_STATUS" "$IMAGE_BUILD_STATUS" "$USERNS_OVERLAY_STATUS"

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

echo "[*] Building the pinned common GKI base Image for the OnePlus 13 project."
echo "[*] This is not a sun/perf-configured Image; no vendor module target is requested."
echo "[*] CONFIG_USER_NS=y is applied via a pinned project fragment and ABI-gated against the pinned GKI baseline."
echo "[*] GKI target make goals also build common GKI modules; they are not packaged."
echo "[*] No boot image, ABL, device access, or flash step."
echo "[*] Common kernel revision: $KERNEL_COMMON_COMMIT"
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

USERNS_PATCH="$PROJECT_ROOT/ci/kleaf/patches/0008-op13-gki-userns-config.patch"
USERNS_FRAGMENT="$PROJECT_ROOT/ci/kleaf/patches/op13-userns.fragment"
if [ ! -s "$USERNS_FRAGMENT" ]; then
    echo "[!] CONFIG_USER_NS fragment is missing or empty." >&2
    exit 1
fi
git -C "$WORKSPACE/common" apply --check "$USERNS_PATCH"
cp -- "$USERNS_FRAGMENT" "$WORKSPACE/common/arch/arm64/configs/op13_userns.fragment"
git -C "$WORKSPACE/common" apply "$USERNS_PATCH"
git -C "$WORKSPACE/common" diff --check
if ! grep -Fq '"defconfig_fragments": ["arch/arm64/configs/op13_userns.fragment"]' "$WORKSPACE/common/BUILD.bazel"; then
    echo "[!] The pinned common BUILD target does not reference the USER_NS fragment." >&2
    exit 1
fi
: > "$USERNS_OVERLAY_STATUS"

free_kb="$(df -Pk "$WORKSPACE" | awk 'END {print $4}')"
if [ "$free_kb" -lt $((20 * 1024 * 1024)) ]; then
    echo "[!] Less than 20 GiB remains after source sync; refusing to start Kleaf." >&2
    df -h "$WORKSPACE" >&2
    exit 1
fi
df -h "$WORKSPACE"

export JAVA_HOME="$WORKSPACE/prebuilts/jdk/jdk11/linux-x86"
export PATH="$JAVA_HOME/bin:$PATH"
export KLEAF_MAKE_JOBS=1
cd "$WORKSPACE"

BAZEL="$WORKSPACE/tools/bazel"
BAZEL_STARTUP_OPTS=(
    --output_user_root="$RUNNER_TEMP/bazel-cache"
)
BAZEL_COMMAND_OPTS=(
    --jobs=1
    --color=no
    --curses=no
    --ignore_missing_projects
    --incompatible_sandbox_hermetic_tmp=false
    --nozstd_dwarf_compression
)

echo "[*] Enforcing the pinned common GKI ABI baseline before Image build."
"$BAZEL" "${BAZEL_STARTUP_OPTS[@]}" run "${BAZEL_COMMAND_OPTS[@]}" //common:kernel_aarch64_abi_diff
: > "$ABI_GATE_STATUS"
echo "[+] Pinned common GKI ABI diff passed with CONFIG_USER_NS=y."

"$BAZEL" "${BAZEL_STARTUP_OPTS[@]}" build "${BAZEL_COMMAND_OPTS[@]}" //common:kernel_aarch64

IMAGE="$WORKSPACE/bazel-bin/common/kernel_aarch64/Image"
if [ ! -s "$IMAGE" ]; then
    echo "[!] Bazel succeeded but the expected common GKI Image is missing: $IMAGE" >&2
    exit 1
fi
: > "$IMAGE_BUILD_STATUS"
echo "[+] Raw common GKI Image built: $(sha256sum "$IMAGE")"
