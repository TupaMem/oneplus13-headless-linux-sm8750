from __future__ import annotations

import os
import re
import subprocess
import tempfile
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
        workflow = (ROOT / ".github/workflows/kernel-build.yml").read_text(encoding="utf-8")
        userns_patch = (CI / "patches/0008-op13-gki-userns-config.patch").read_text(
            encoding="utf-8"
        )
        userns_fragment = (CI / "patches/op13-userns.fragment").read_text(encoding="utf-8")
        self.assertIn("--jobs=1", script)
        self.assertIn("KLEAF_MAKE_JOBS=1", script)
        self.assertIn('--repo-rev="$REPO_TOOL_COMMIT"', script)
        self.assertIn("//common:kernel_aarch64", script)
        self.assertIn(
            'run "${BAZEL_COMMAND_OPTS[@]}" //common:kernel_aarch64_abi_diff', script
        )
        self.assertLess(
            script.index("//common:kernel_aarch64_abi_diff\n"),
            script.index("build \"${BAZEL_COMMAND_OPTS[@]}\" //common:kernel_aarch64\n"),
        )
        self.assertIn('git -C "$WORKSPACE/common" apply --check "$USERNS_PATCH"', script)
        self.assertIn('git -C "$WORKSPACE/common" apply "$USERNS_PATCH"', script)
        self.assertNotIn("//msm-kernel:sun_perf", script)
        self.assertNotIn("modules_install", script)
        expected_image = 'IMAGE="$WORKSPACE/bazel-bin/common/kernel_aarch64/Image"'
        self.assertIn(expected_image, script)
        self.assertIn(expected_image, collect)
        self.assertNotIn("prepare_oplus_workspace.sh", script)
        self.assertNotIn("sun-perf-headless.config", script)
        self.assertNotIn("0007-kleaf-sun-perf-image-only.patch", script)
        self.assertIn("build_target=//common:kernel_aarch64", collect)
        self.assertIn("image_lineage=common GKI with project CONFIG_USER_NS=y overlay", collect)
        self.assertIn("build_make_goals=Image,Image.lz4,Image.gz,modules", collect)
        self.assertIn("common_gki_modules_goal_included=yes", collect)
        self.assertIn("sun_perf_vendor_modules_built=no", collect)
        self.assertIn("modules_install_built=no", collect)
        self.assertIn("oneplus_modules_commit_pinned_not_built=", collect)
        self.assertIn("image_source_commit=${KERNEL_COMMON_COMMIT}", collect)
        self.assertIn("abi_gate_target=//common:kernel_aarch64_abi_diff", collect)
        self.assertIn("common_gki_abi_validated=${COMMON_GKI_ABI_VALIDATED}", collect)
        self.assertIn("oneplus_vendor_module_kmi_validated=no", collect)
        self.assertIn("user_ns_overlay_applied=${USERNS_OVERLAY_APPLIED}", collect)
        self.assertIn("user_ns_config_verified=${USERNS_CONFIG_VERIFIED}", collect)
        self.assertIn("IMAGE_COLLECTED=no", collect)
        self.assertIn("common/build.config.gki.aarch64", collect)
        self.assertIn("flashable=no", collect)
        self.assertIn("boot_image_generated=no", collect)
        self.assertIn("abl_included=no", collect)
        self.assertIn("common GKI base Image", collect)
        self.assertIn('"defconfig_fragments": ["arch/arm64/configs/op13_userns.fragment"]', userns_patch)
        self.assertEqual(userns_fragment, "CONFIG_USER_NS=y\n")
        self.assertIn("op13-gki-base-image-${{ github.run_number }}", workflow)
        self.assertIn("op13-gki-base-image-artifacts/", workflow)
        self.assertEqual(workflow.count("ABI_GATE_STATUS: ${{ runner.temp }}/op13-gki-abi-gate-passed"), 2)
        self.assertEqual(workflow.count("USERNS_OVERLAY_STATUS: ${{ runner.temp }}/op13-gki-userns-overlay-applied"), 2)
        self.assertIn("flashable", (ROOT / "docs/KLEAF_ACTIONS_BUILD.md").read_text())

    def test_collector_packages_only_raw_common_image_with_provenance(self):
        with tempfile.TemporaryDirectory(prefix="op13-gki-artifact-test-") as temp:
            temp_root = Path(temp)
            workspace = temp_root / "workspace"
            runner_temp = temp_root / "runner-temp"
            artifact_dir = temp_root / "artifact"
            image = workspace / "bazel-bin/common/kernel_aarch64/Image"
            image.parent.mkdir(parents=True)
            image.write_bytes(b"synthetic raw GKI Image\x00")
            for relative in (
                "common/BUILD.bazel",
                "common/build.config.gki.aarch64",
                "common/arch/arm64/configs/gki_defconfig",
            ):
                source = workspace / relative
                source.parent.mkdir(parents=True, exist_ok=True)
                source.write_text("pinned test fixture\n", encoding="utf-8")
            runner_temp.mkdir()
            build_log = runner_temp / "build.log"
            build_log.write_text("synthetic build log\n", encoding="utf-8")

            env = os.environ.copy()
            env.update(
                {
                    "KERNEL_WORKSPACE": str(workspace),
                    "RUNNER_TEMP": str(runner_temp),
                    "BUILD_LOG": str(build_log),
                    "ARTIFACT_DIR": str(artifact_dir),
                    "ABI_GATE_STATUS": str(runner_temp / "abi-gate-passed"),
                    "IMAGE_BUILD_STATUS": str(runner_temp / "image-build-passed"),
                    "USERNS_OVERLAY_STATUS": str(runner_temp / "userns-overlay-applied"),
                    "GITHUB_OUTPUT": str(runner_temp / "github-output.txt"),
                }
            )
            Path(env["ABI_GATE_STATUS"]).touch()
            Path(env["IMAGE_BUILD_STATUS"]).touch()
            Path(env["USERNS_OVERLAY_STATUS"]).touch()
            subprocess.run(["bash", str(CI / "collect_artifacts.sh")], env=env, check=True)

            self.assertEqual((artifact_dir / "Image").read_bytes(), image.read_bytes())
            info = (artifact_dir / "BUILD_INFO.txt").read_text(encoding="utf-8")
            self.assertIn("build_target=//common:kernel_aarch64", info)
            self.assertIn("image_lineage=common GKI with project CONFIG_USER_NS=y overlay", info)
            self.assertIn("abi_gate_status=pass", info)
            self.assertIn("common_gki_abi_validated=yes", info)
            self.assertIn("oneplus_vendor_module_kmi_validated=no", info)
            self.assertIn("user_ns_overlay_applied=yes", info)
            self.assertIn("user_ns_config_verified=yes", info)
            self.assertIn("image_collected=yes", info)
            self.assertIn("sun_perf_vendor_modules_built=no", info)
            self.assertTrue((artifact_dir / "source-inputs/common/build.config.gki.aarch64").is_file())
            self.assertTrue((artifact_dir / "source-inputs/op13-userns.fragment").is_file())
            self.assertTrue(
                (artifact_dir / "source-inputs/0008-op13-gki-userns-config.patch").is_file()
            )
            subprocess.run(
                ["sha256sum", "--check", "SHA256SUMS"],
                cwd=artifact_dir,
                check=True,
                capture_output=True,
                text=True,
            )

    def test_collector_never_packages_image_without_abi_gate(self):
        with tempfile.TemporaryDirectory(prefix="op13-gki-fail-closed-test-") as temp:
            temp_root = Path(temp)
            workspace = temp_root / "workspace"
            runner_temp = temp_root / "runner-temp"
            artifact_dir = temp_root / "artifact"
            image = workspace / "bazel-bin/common/kernel_aarch64/Image"
            image.parent.mkdir(parents=True)
            image.write_bytes(b"must not package without ABI pass")
            artifact_dir.mkdir()
            (artifact_dir / "Image").write_bytes(b"stale image from a prior invocation")
            runner_temp.mkdir()
            build_log = runner_temp / "build.log"
            build_log.write_text("ABI gate failed\n", encoding="utf-8")
            image_build_status = runner_temp / "image-build-passed"
            image_build_status.touch()
            userns_overlay_status = runner_temp / "userns-overlay-applied"
            userns_overlay_status.touch()

            env = os.environ.copy()
            env.update(
                {
                    "KERNEL_WORKSPACE": str(workspace),
                    "RUNNER_TEMP": str(runner_temp),
                    "BUILD_LOG": str(build_log),
                    "ARTIFACT_DIR": str(artifact_dir),
                    "ABI_GATE_STATUS": str(runner_temp / "abi-gate-passed"),
                    "IMAGE_BUILD_STATUS": str(image_build_status),
                    "USERNS_OVERLAY_STATUS": str(userns_overlay_status),
                    "GITHUB_OUTPUT": str(runner_temp / "github-output.txt"),
                }
            )
            subprocess.run(["bash", str(CI / "collect_artifacts.sh")], env=env, check=True)

            info = (artifact_dir / "BUILD_INFO.txt").read_text(encoding="utf-8")
            self.assertFalse((artifact_dir / "Image").exists())
            self.assertIn("abi_gate_status=no", info)
            self.assertIn("common_gki_abi_validated=no", info)
            self.assertIn("user_ns_overlay_applied=yes", info)
            self.assertIn("user_ns_config_verified=no", info)
            self.assertIn("image_build_succeeded=yes", info)
            self.assertIn("image_collected=no", info)

    def test_ci_shell_scripts_parse_without_running_the_build(self):
        for script in sorted(CI.glob("*.sh")):
            with self.subTest(script=script.name):
                subprocess.run(["bash", "-n", str(script)], check=True)


if __name__ == "__main__":
    unittest.main()
