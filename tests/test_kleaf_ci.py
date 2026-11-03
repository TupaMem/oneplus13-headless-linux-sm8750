from __future__ import annotations

import posixpath
import re
import subprocess
import unittest
from pathlib import Path
from xml.etree import ElementTree


ROOT = Path(__file__).resolve().parents[1]
CI = ROOT / "ci/kleaf"


def read_pins() -> dict[str, str]:
    return {
        key: value
        for line in (CI / "pins.env").read_text(encoding="utf-8").splitlines()
        if line and not line.lstrip().startswith("#")
        for key, value in [line.split("=", 1)]
    }


class KleafActionsTests(unittest.TestCase):
    def test_manifest_is_fully_sha_pinned_and_matches_device_revisions(self):
        pins = read_pins()
        root = ElementTree.parse(CI / "manifest.xml").getroot()
        projects = root.findall("project")
        self.assertEqual(len(projects), 37)
        by_name = {project.attrib["name"]: project for project in projects}
        for project in projects:
            revision = project.attrib.get("revision", "")
            with self.subTest(project=project.attrib["name"]):
                self.assertRegex(revision, r"^[0-9a-f]{40}$")

        expected = {
            "android_kernel_oneplus_sm8750": "KERNEL_COMMIT",
            "android_kernel_oneplus_sm8750-modules": "KERNEL_MODULES_COMMIT",
            "android_kernel_oneplus_sm8750-devicetrees": "DEVICE_TREE_COMMIT",
            "kernel/common": "KERNEL_COMMON_COMMIT",
            "kernel/build": "KERNEL_BUILD_COMMIT",
        }
        for name, pin_name in expected.items():
            with self.subTest(project=name):
                self.assertEqual(by_name[name].attrib["revision"], pins[pin_name])

    def test_actions_workflow_is_manual_and_actions_are_pinned(self):
        workflow = (ROOT / ".github/workflows/kernel-build.yml").read_text(encoding="utf-8")
        self.assertRegex(workflow, r"(?m)^on:\s*$")
        self.assertIn("  workflow_dispatch:", workflow)
        self.assertNotRegex(workflow, r"(?m)^  (push|pull_request):")
        self.assertIn("contents: read", workflow)
        self.assertIn("timeout-minutes: 360", workflow)
        for action_ref in re.findall(r"(?m)^\s+uses: ([^\s]+)$", workflow):
            with self.subTest(action=action_ref):
                self.assertRegex(action_ref, r"@[0-9a-f]{40}$")

    def test_build_is_single_job_and_artifact_is_not_flashable(self):
        script = (CI / "run_build.sh").read_text(encoding="utf-8")
        collect = (CI / "collect_artifacts.sh").read_text(encoding="utf-8")
        config = (CI / "patches/sun-perf-headless.config").read_text(encoding="utf-8")
        self.assertIn("--jobs=1", script)
        self.assertIn("KLEAF_MAKE_JOBS=1", script)
        self.assertIn("apply --unidiff-zero --check", script)
        self.assertIn('--repo-rev="$REPO_TOOL_COMMIT"', script)
        self.assertIn("//msm-kernel:sun_perf", script)
        self.assertIn("//msm-kernel:sun_perf_modules_install", script)
        self.assertIn('DEVICETREE_VENDOR="$WORKSPACE/vendor/qcom/kernel/arch/arm64/boot/dts/vendor"', script)
        self.assertIn('link_exact "$DEVICETREE_VENDOR" "$WORKSPACE/kernel/oneplus/sm8750-devicetrees"', script)
        self.assertIn('"$DEVICETREE_VENDOR/BUILD.bazel"', script)
        self.assertIn('"$DEVICETREE_VENDOR/qcom/platform_map.bzl"', script)
        self.assertIn('MODULES_PATCH="$PROJECT_ROOT/ci/kleaf/patches/0005-oplus-ufs-sandbox-includes.patch"', script)
        self.assertIn('git -C "$MODULES_TREE" apply --check "$MODULES_PATCH"', script)
        ufs_patch = (CI / "patches/0005-oplus-ufs-sandbox-includes.patch").read_text(encoding="utf-8")
        host_header = "../../../../../../../../../msm-kernel/drivers/ufs/host/ufs-qcom.h"
        core_header = "../../../../../../../../../msm-kernel/drivers/ufs/core/ufshcd-priv.h"
        module_source_dir = (
            "kernel/oneplus/sm8750-modules/oplus/kernel/storage/"
            "storage_feature_in_module/common/ufs_oplus_dbg"
        )
        self.assertIn(f'"{host_header}"', ufs_patch)
        self.assertIn(f'"{core_header}"', ufs_patch)
        self.assertEqual(
            posixpath.normpath(posixpath.join(module_source_dir, host_header)),
            "msm-kernel/drivers/ufs/host/ufs-qcom.h",
        )
        self.assertEqual(
            posixpath.normpath(posixpath.join(module_source_dir, core_header)),
            "msm-kernel/drivers/ufs/core/ufshcd-priv.h",
        )
        self.assertIn(
            '"$PROJECT_ROOT/ci/kleaf/patches/0005-oplus-ufs-sandbox-includes.patch" '
            '"$ARTIFACT_DIR/source-inputs/"',
            collect,
        )
        self.assertIn("CONFIG_OPLUS_QCOM_UFS_DRIVER=y", config)
        self.assertIn("CONFIG_OPLUS_UFS_DRIVER=m", config)
        self.assertIn("--//msm-kernel:skip_abl=true", script)
        self.assertIn("--//msm-kernel:skip_abi=true", script)
        self.assertNotIn("//msm-kernel:sun_perf_abi", script)
        self.assertIn("flashable=no", collect)
        self.assertIn("boot_image_generated=no", collect)
        self.assertIn("abl_included=no", collect)
        self.assertIn("flashable", (ROOT / "docs/KLEAF_ACTIONS_BUILD.md").read_text())

    def test_ci_shell_scripts_parse_without_running_the_build(self):
        for script in sorted(CI.glob("*.sh")):
            with self.subTest(script=script.name):
                subprocess.run(["bash", "-n", str(script)], check=True)


if __name__ == "__main__":
    unittest.main()
