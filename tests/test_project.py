from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[1]
MERGER_PATH = ROOT / "scripts/merge_kconfig.py"
MODULE_ZIP = ROOT / "modules/OP13-DualBoot-Manager-v2.1.0-preview.zip"

spec = importlib.util.spec_from_file_location("merge_kconfig", MERGER_PATH)
assert spec is not None and spec.loader is not None
merge_kconfig = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = merge_kconfig
spec.loader.exec_module(merge_kconfig)


class KconfigMergeTests(unittest.TestCase):
    def test_merge_is_idempotent(self) -> None:
        base = "CONFIG_BASE=y\n"
        fragment = "# sample\nCONFIG_BASE=y\nCONFIG_NEW=y\n"
        once = merge_kconfig.merge_config(base, fragment)
        twice = merge_kconfig.merge_config(once, fragment)
        self.assertEqual(once, twice)
        self.assertEqual(once.count("CONFIG_NEW=y"), 1)

    def test_conflicting_base_value_is_rejected_by_default(self) -> None:
        with self.assertRaises(merge_kconfig.KconfigError):
            merge_kconfig.merge_config("# CONFIG_FEATURE is not set\n", "CONFIG_FEATURE=y\n")

    def test_override_must_be_explicit(self) -> None:
        merged = merge_kconfig.merge_config(
            "CONFIG_FEATURE=n\n", "CONFIG_FEATURE=y\n", allow_overrides=True
        )
        self.assertIn("CONFIG_FEATURE=n", merged)
        self.assertIn("CONFIG_FEATURE=y", merged)

    def test_conflicting_duplicate_fragment_is_rejected(self) -> None:
        with self.assertRaises(merge_kconfig.KconfigError):
            merge_kconfig.merge_config("", "CONFIG_FEATURE=y\n# CONFIG_FEATURE is not set\n")

    def test_file_merge_preserves_mode_and_does_not_partially_write_on_conflict(self) -> None:
        with tempfile.TemporaryDirectory(prefix="op13-kconfig-test-") as temp:
            base_path = Path(temp) / "gki_defconfig"
            fragment_path = Path(temp) / "fragment.config"
            base_path.write_text("CONFIG_EXISTING=y\n", encoding="utf-8")
            base_path.chmod(0o644)
            fragment_path.write_text("CONFIG_NEW=y\n", encoding="utf-8")
            merge_kconfig.merge_file(base_path, fragment_path, allow_overrides=False)
            self.assertEqual(base_path.stat().st_mode & 0o777, 0o644)
            self.assertIn("CONFIG_NEW=y", base_path.read_text(encoding="utf-8"))

            before = base_path.read_bytes()
            fragment_path.write_text("CONFIG_EXISTING=n\n", encoding="utf-8")
            with self.assertRaises(merge_kconfig.KconfigError):
                merge_kconfig.merge_file(base_path, fragment_path, allow_overrides=False)
            self.assertEqual(base_path.read_bytes(), before)


class ProjectArtifactTests(unittest.TestCase):
    def test_kernel_fragment_and_patch_fixtures(self) -> None:
        result = subprocess.run(
            [sys.executable, str(ROOT / "tests/verify_kernel_patches.py"), "--self-test"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("synthetic fixtures", result.stdout)
        self.assertNotIn("KMI preservation", result.stdout)

    def test_module_archive_integrity_paths_and_shell_syntax(self) -> None:
        self.assertTrue(MODULE_ZIP.is_file())
        with zipfile.ZipFile(MODULE_ZIP) as archive:
            self.assertIsNone(archive.testzip())
            shell_count = 0
            for info in archive.infolist():
                if info.is_dir():
                    continue
                path = PurePosixPath(info.filename)
                self.assertFalse(path.is_absolute(), info.filename)
                self.assertNotIn("..", path.parts, info.filename)
                self.assertNotIn("\\", info.filename)
                data = archive.read(info.filename)
                if data.startswith(b"#!"):
                    shell_count += 1
                    mode = (info.external_attr >> 16) & 0o777
                    self.assertTrue(mode & 0o111, f"script is not executable: {info.filename}")
                    check = subprocess.run(
                        ["sh", "-n"], input=data, capture_output=True, check=False
                    )
                    self.assertEqual(
                        check.returncode,
                        0,
                        f"shell syntax error in {info.filename}: {check.stderr.decode(errors='replace')}",
                    )
            self.assertGreaterEqual(shell_count, 8)

    def test_module_package_matches_source_reproducibly(self) -> None:
        with tempfile.TemporaryDirectory(prefix="op13-module-test-") as temp:
            generated = Path(temp) / "module.zip"
            result = subprocess.run(
                [sys.executable, str(ROOT / "scripts/package_module.py"), "--output", str(generated)],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            second = Path(temp) / "module-second.zip"
            second_result = subprocess.run(
                [sys.executable, str(ROOT / "scripts/package_module.py"), "--output", str(second)],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(second_result.returncode, 0, second_result.stdout + second_result.stderr)
            self.assertEqual(generated.read_bytes(), second.read_bytes())
            with zipfile.ZipFile(generated) as archive:
                packaged = {name: archive.read(name) for name in archive.namelist()}
            source = {
                path.relative_to(ROOT / "module-src").as_posix(): path.read_bytes()
                for path in (ROOT / "module-src").rglob("*")
                if path.is_file()
            }
            self.assertEqual(packaged, source)

    def test_module_is_fail_closed_and_webui_is_static(self) -> None:
        module = ROOT / "module-src"
        engine = (module / "system/bin/op13-updater-engine").read_text(encoding="utf-8")
        guardian = (module / "system/bin/op13-slot-guardian").read_text(encoding="utf-8")
        post_fs = (module / "post-fs-data.sh").read_text(encoding="utf-8")
        service = (module / "service.sh").read_text(encoding="utf-8")
        action = (module / "action.sh").read_text(encoding="utf-8")
        page = (module / "webroot/index.html").read_text(encoding="utf-8").lower()

        for unsafe_token in ("dd if=", "blockdev --setrw", "blockdev --setro", "reboot"):
            self.assertNotIn(unsafe_token, engine.lower())
        self.assertIn("device_writes_enabled\": false", engine)
        self.assertIn("disabled in this preview build", engine)
        self.assertIn("disabled in this preview build", guardian)
        self.assertNotIn("blockdev", post_fs)
        self.assertNotIn("op13-slot-guardian\" auto", service)
        self.assertIn('"$ENGINE" status', action)
        self.assertNotIn("getevent", action)
        self.assertNotIn("flash-ota-safe", action)
        self.assertNotIn("<script", page)
        self.assertNotIn("https://", page)

    def test_module_uses_no_unverified_web_bridge(self) -> None:
        page = (ROOT / "module-src/webroot/index.html").read_text(encoding="utf-8").lower()
        self.assertNotIn("window.ksu", page)
        self.assertNotIn("setinterval", page)
        self.assertNotIn("root: granted", page)

    def test_glibc_stager_requires_complete_runtime_and_safe_target(self) -> None:
        with tempfile.TemporaryDirectory(prefix="op13-glibc-stage-") as temp:
            root = Path(temp)
            source = root / "source"
            lib64 = source / "lib64"
            lib64.mkdir(parents=True)
            loader = lib64 / "ld-linux-aarch64.so.1"
            loader.write_text("test loader placeholder\n", encoding="utf-8")
            loader.chmod(0o755)
            (lib64 / "libc.so.6").write_text("test libc placeholder\n", encoding="utf-8")

            fake_bin = root / "bin"
            fake_bin.mkdir()
            readelf = fake_bin / "readelf"
            readelf.write_text("#!/bin/sh\nprintf '  Machine: AArch64\\n'\n", encoding="utf-8")
            readelf.chmod(0o755)

            output = root / "out"
            env = {
                **os.environ,
                "GLIBC_SOURCE": str(source),
                "GLIBC_ROOT": str(output),
                "PATH": f"{fake_bin}:{os.environ['PATH']}",
            }
            result = subprocess.run(
                ["bash", str(ROOT / "runtime/setup_micro_glibc.sh")],
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(
                (output / "lib64/ld-linux-aarch64.so.1").read_text(encoding="utf-8"),
                "test loader placeholder\n",
            )
            self.assertTrue((output / "bin/glibc-run").stat().st_mode & 0o111)

            unsafe = subprocess.run(
                ["bash", str(ROOT / "runtime/setup_micro_glibc.sh")],
                env={**env, "GLIBC_ROOT": "/system/"},
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(unsafe.returncode, 0)
            self.assertIn("Refusing unsafe GLIBC_ROOT", unsafe.stderr)

            occupied = subprocess.run(
                ["bash", str(ROOT / "runtime/setup_micro_glibc.sh")],
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(occupied.returncode, 0)
            self.assertIn("GLIBC_ROOT is not empty", occupied.stderr)

            overwrite = subprocess.run(
                ["bash", str(ROOT / "runtime/setup_micro_glibc.sh")],
                env={**env, "OVERWRITE": "1"},
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(overwrite.returncode, 0, overwrite.stdout + overwrite.stderr)

    def test_repository_shell_syntax(self) -> None:
        scripts = (
            ROOT / "runtime/setup_micro_glibc.sh",
            ROOT / "scripts/enter_headless.sh",
            ROOT / "scripts/import_and_patch_lineageos.sh",
        )
        for script in scripts:
            interpreter = "bash" if "bash" in script.read_text(encoding="utf-8").splitlines()[0] else "sh"
            result = subprocess.run(
                [interpreter, "-n", str(script)], capture_output=True, text=True, check=False
            )
            self.assertEqual(result.returncode, 0, f"{script}: {result.stderr}")

    def test_import_defaults_are_non_destructive(self) -> None:
        script = (ROOT / "scripts/import_and_patch_lineageos.sh").read_text(encoding="utf-8")
        self.assertIn('ENABLE_KSU="${ENABLE_KSU:-0}"', script)
        self.assertIn('ENABLE_THERMAL_BYPASS="${ENABLE_THERMAL_BYPASS:-0}"', script)
        self.assertIn("sha256sum", script)
        self.assertNotIn("curl -LSs", script)
        self.assertNotIn("curl | bash", script)

    def test_kernel_importer_is_idempotent_and_skips_thermal_patch_by_default(self) -> None:
        with tempfile.TemporaryDirectory(prefix="op13-import-test-") as temp:
            workdir = Path(temp)
            kernel = workdir / "kernel"
            (kernel / "arch/arm64/configs/vendor").mkdir(parents=True)
            (kernel / "drivers/thermal").mkdir(parents=True)
            (kernel / "arch/arm64/configs/gki_defconfig").write_text(
                "CONFIG_IKCONFIG=y\n"
                "CONFIG_IKCONFIG_PROC=y\n"
                "CONFIG_CGROUPS=y\n"
                "CONFIG_MEMCG=y\n"
                "CONFIG_BLK_CGROUP=y\n"
                "CONFIG_CGROUP_SCHED=y\n"
                "CONFIG_UCLAMP_TASK=y\n",
                encoding="utf-8",
            )
            (kernel / "arch/arm64/configs/vendor/sun_GKI.config").write_text(
                "CONFIG_VENDOR_TEST=y\n", encoding="utf-8"
            )
            (kernel / "drivers/thermal/thermal_core.c").write_text(
                "static DEFINE_MUTEX(thermal_list_lock);\n"
                "static DEFINE_MUTEX(thermal_governor_lock);\n"
                "static atomic_t in_suspend;\n\n"
                "static void handle_thermal_trip(struct thermal_zone_device *tz,\n"
                "                                const struct thermal_trip *trip)\n"
                "{\n"
                "        if (trip->temperature == THERMAL_TEMP_INVALID)\n"
                "                return;\n\n"
                "        if (tz->last_temperature != THERMAL_TEMP_INVALID) {\n"
                "                if (tz->last_temperature < trip->temperature &&\n"
                "                    tz->temperature >= trip->temperature)\n",
                encoding="utf-8",
            )
            subprocess.run(["git", "init", "-q"], cwd=kernel, check=True)
            env = {**os.environ, "WORKDIR": str(workdir), "ENABLE_KSU": "0"}
            script = ROOT / "scripts/import_and_patch_lineageos.sh"

            for _ in range(2):
                result = subprocess.run(
                    ["bash", str(script)],
                    env=env,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("Skipping optional thermal bypass", result.stdout)

            gki = (kernel / "arch/arm64/configs/gki_defconfig").read_text(encoding="utf-8")
            vendor = (kernel / "arch/arm64/configs/vendor/sun_GKI.config").read_text(encoding="utf-8")
            thermal = (kernel / "drivers/thermal/thermal_core.c").read_text(encoding="utf-8")
            self.assertEqual(gki.count("CONFIG_SYSVIPC=y"), 1)
            self.assertEqual(vendor.count("CONFIG_SYSVIPC=y"), 1)
            self.assertNotIn("sm8750_headless_thermal_bypass", thermal)

            source_script = workdir / "ksu-setup.sh"
            marker = workdir / "ksu-executed"
            source_script.write_text(
                "#!/usr/bin/env bash\nprintf 'executed\\n' > \"$KSU_MARKER\"\n",
                encoding="utf-8",
            )
            digest = subprocess.run(
                ["sha256sum", str(source_script)], text=True, capture_output=True, check=True
            ).stdout.split()[0]
            fake_bin = workdir / "fake-bin"
            fake_bin.mkdir()
            fake_curl = fake_bin / "curl"
            fake_curl.write_text(
                "#!/bin/sh\n"
                "out=\n"
                "while [ $# -gt 0 ]; do\n"
                "  if [ \"$1\" = --output ]; then out=$2; shift 2; else shift; fi\n"
                "done\n"
                "cp \"$KSU_SOURCE\" \"$out\"\n",
                encoding="utf-8",
            )
            fake_curl.chmod(0o755)
            ksu_env = {
                **env,
                "PATH": f"{fake_bin}:{os.environ['PATH']}",
                "ENABLE_KSU": "1",
                "KSU_SETUP_URL": "fixture://reviewed-script",
                "KSU_SETUP_SHA256": digest,
                "KSU_SOURCE": str(source_script),
                "KSU_MARKER": str(marker),
            }
            verified = subprocess.run(
                ["bash", str(script)], env=ksu_env, text=True, capture_output=True, check=False
            )
            self.assertEqual(verified.returncode, 0, verified.stdout + verified.stderr)
            self.assertTrue(marker.is_file(), "verified setup script was not executed")

            marker.unlink()
            rejected = subprocess.run(
                ["bash", str(script)],
                env={**ksu_env, "KSU_SETUP_SHA256": "0" * 64},
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("SHA-256 mismatch", rejected.stderr)
            self.assertFalse(marker.exists(), "digest mismatch must prevent script execution")

            bad_workdir = workdir / "not-a-checkout"
            (bad_workdir / "kernel").mkdir(parents=True)
            bad_tree = subprocess.run(
                ["bash", str(script)],
                env={**env, "WORKDIR": str(bad_workdir)},
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(bad_tree.returncode, 0)
            self.assertIn("not a Git checkout", bad_tree.stderr)

    def test_headless_script_leaves_device_tuning_untouched(self) -> None:
        script = (ROOT / "scripts/enter_headless.sh").read_text(encoding="utf-8")
        self.assertNotIn("scaling_min_freq", script)
        self.assertNotIn("force_clk_on", script)
        self.assertNotIn("swapoff", script)
        self.assertNotIn("thermal-engine", script)
        self.assertIn("$0 restore", script)


if __name__ == "__main__":
    unittest.main()
