"""Verify double-click installer launcher metadata, auto-stop, auto-restart, and ASCII/CRLF safety."""
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

import launcher

HERE = Path(__file__).resolve().parent


class LauncherTests(unittest.TestCase):
    def test_cmd_is_pure_ascii(self):
        raw = (HERE / "launcher.cmd").read_bytes()
        raw.decode("ascii")
        self.assertIn(b"launcher.py", raw)
        self.assertIn(b"chcp 65001", raw)
        self.assertIn(b"--status", raw)
        self.assertIn(b"timeout /t 5", raw)

    def test_status_and_result_formatting(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            pkg = root / "pkg"
            store = root / "store"
            app = root / "app"
            pkg.mkdir()
            (pkg / "release.json").write_text(
                json.dumps({"version": "0.4.4", "flavor": "subscription", "host": "2.35.1", "build": "aaaabbbbccccddddeeee"}),
                encoding="utf-8",
            )
            st = launcher.current_status(pkg_dir=pkg, store=store, app=app)
            self.assertEqual(st["package_version"], "0.4.4")
            self.assertFalse(st["installed"])
            self.assertFalse(st["same_build"])
            store.mkdir()
            (store / "owned.json").write_text(
                json.dumps({"build": "aaaabbbbccccddddeeee", "release": {"version": "0.4.4", "host": "2.35.1"}, "predecessor": "prev"}),
                encoding="utf-8",
            )
            st2 = launcher.current_status(pkg_dir=pkg, store=store, app=app)
            self.assertTrue(st2["installed"])
            self.assertTrue(st2["same_build"])
            self.assertTrue(st2["has_predecessor"])
            self.assertFalse(st2["host_changed"])
            (pkg / "release.json").write_text(
                json.dumps({"version": "0.5.1", "flavor": "subscription", "host": "2.35.2", "build": "bbbbccccddddeeeeffff"}),
                encoding="utf-8",
            )
            st3 = launcher.current_status(pkg_dir=pkg, store=store, app=app)
            self.assertTrue(st3["host_changed"])
            self.assertFalse(st3["has_predecessor"])
        self.assertIn("升级完成", launcher.format_result("upgrade", {"state": "upgraded", "from": "old", "build": "new"}))
        self.assertIn("已适配新版 Antigravity", launcher.format_result("upgrade", {"state": "migrated_host", "previous_host": "2.35.1", "host": "2.35.2", "build": "new"}))
        self.assertIn("安装完成", launcher.format_result("install", {"state": "installed", "build": "new"}))
        self.assertIn("卸载完成", launcher.format_result("uninstall", {"state": "uninstalled"}))
        self.assertIn("预览校验通过", launcher.format_result("preview", {"build": "b1", "candidate": "sha"}))

    def test_app_dir_resolves_registered_custom_install_and_version_match(self):
        with tempfile.TemporaryDirectory() as td:
            local = Path(td)
            default = local / "Programs/antigravity"
            (default / "resources/bin").mkdir(parents=True)
            (default / "Antigravity.exe").write_bytes(b"MZ")
            (default / "resources/bin/language_server.exe").write_bytes(b"MZ")
            custom = local / "Programs/CustomAntigravity"
            (custom / "resources/bin").mkdir(parents=True)
            (custom / "Antigravity.exe").write_bytes(b"MZ")
            (custom / "resources/bin/language_server.exe").write_bytes(b"MZ")
            (custom / "resources/app.asar").write_bytes(b"ASAR")
            self.assertEqual(launcher.app_dir(local_app_data=local, registered=[custom]), custom)
            # When both are complete, version match wins.
            (default / "resources/app.asar").write_bytes(b"ASAR")
            with mock.patch.object(launcher, "_exe_version", side_effect=lambda p: "2.35.2" if "CustomAntigravity" in str(p) else "2.36.0"):
                self.assertEqual(launcher.app_dir(expected_host="2.36.0", local_app_data=local, registered=[custom]), default)
            # Without custom registration, default path is returned.
            self.assertEqual(launcher.app_dir(local_app_data=local), default)

    def test_list_target_processes_handles_single_dict_and_list(self):
        app = Path(r"C:\Users\demo\AppData\Local\Programs\antigravity")
        single = {
            "pid": 100,
            "ppid": 1,
            "name": "Antigravity.exe",
            "exe": str(app / "Antigravity.exe"),
            "cmd": '"Antigravity.exe"',
        }
        multi = [
            single,
            {
                "pid": 101,
                "ppid": 100,
                "name": "Antigravity.exe",
                "exe": str(app / "Antigravity.exe"),
                "cmd": '"Antigravity.exe" --type=renderer',
            },
            {
                "pid": 102,
                "ppid": 100,
                "name": "language_server.exe",
                "exe": str(app / "resources/bin/language_server.exe"),
                "cmd": '"language_server.exe" --standalone',
            },
        ]
        with mock.patch.object(launcher.os, "name", "nt"), mock.patch.object(launcher.subprocess, "run") as run_mock:
            run_mock.return_value = subprocess.CompletedProcess([], 0, stdout=json.dumps(single), stderr="")
            res1 = launcher.list_target_processes(app)
            self.assertEqual(len(res1), 1)
            self.assertEqual(res1[0]["kind"], "root")

            run_mock.return_value = subprocess.CompletedProcess([], 0, stdout=json.dumps(multi), stderr="")
            res2 = launcher.list_target_processes(app)
            self.assertEqual([p["kind"] for p in res2], ["root", "helper", "ls"])

    def test_stop_antigravity_graceful_success(self):
        root_proc = [{"pid": 200, "ppid": 1, "name": "Antigravity.exe", "exe": "x", "cmd": "x", "kind": "root"}]
        with mock.patch.object(launcher, "list_target_processes", side_effect=[root_proc, []]), \
             mock.patch.object(launcher, "request_graceful_close", return_value=True) as grace, \
             mock.patch.object(launcher, "force_kill_processes") as kill:
            ok, msg = launcher.stop_antigravity(Path("C:/app"), timeout=2.0, graceful_wait=1.0, poll_interval=0.01, settle=0.0, log=lambda *_: None)
            self.assertTrue(ok)
            self.assertIn("正常退出", msg)
            grace.assert_called_once_with([200])
            kill.assert_not_called()

    def test_stop_antigravity_fallback_to_scoped_force_kill(self):
        root_proc = [{"pid": 300, "ppid": 1, "name": "Antigravity.exe", "exe": "x", "cmd": "x", "kind": "root"}]
        ls_proc = [{"pid": 301, "ppid": 300, "name": "language_server.exe", "exe": "y", "cmd": "y", "kind": "ls"}]
        with mock.patch.object(launcher, "list_target_processes", side_effect=[root_proc, ls_proc, []]), \
             mock.patch.object(launcher, "request_graceful_close", return_value=False) as grace, \
             mock.patch.object(launcher, "force_kill_processes") as kill:
            ok, msg = launcher.stop_antigravity(Path("C:/app"), timeout=2.0, graceful_wait=0.0, poll_interval=0.01, settle=0.0, log=lambda *_: None)
            self.assertTrue(ok)
            self.assertIn("已自动关闭", msg)
            grace.assert_called_once_with([300])
            kill.assert_called_once_with(ls_proc)

    def test_stop_antigravity_reports_remaining_on_timeout(self):
        stuck = [{"pid": 400, "ppid": 1, "name": "language_server.exe", "exe": "y", "cmd": "y", "kind": "ls"}]
        with mock.patch.object(launcher, "list_target_processes", return_value=stuck), \
             mock.patch.object(launcher, "force_kill_processes") as kill:
            ok, msg = launcher.stop_antigravity(Path("C:/app"), timeout=0.05, graceful_wait=0.0, poll_interval=0.01, settle=0.0, log=lambda *_: None)
            self.assertFalse(ok)
            self.assertIn("400", msg)
            self.assertGreaterEqual(kill.call_count, 1)

    def test_launch_antigravity_non_admin_vs_admin(self):
        with tempfile.TemporaryDirectory() as td:
            app = Path(td)
            exe = app / "Antigravity.exe"
            exe.write_bytes(b"MZ")
            with mock.patch.object(launcher.os, "name", "nt"), \
                 mock.patch.object(launcher, "is_admin", return_value=False), \
                 mock.patch.object(launcher.subprocess, "Popen") as popen:
                ok, _ = launcher.launch_antigravity(app)
                self.assertTrue(ok)
                self.assertEqual(popen.call_args[0][0], [str(exe)])

            with mock.patch.object(launcher.os, "name", "nt"), \
                 mock.patch.object(launcher, "is_admin", return_value=True), \
                 mock.patch.object(launcher.subprocess, "Popen") as popen:
                ok, msg = launcher.launch_antigravity(app)
                self.assertTrue(ok)
                self.assertIn("普通权限", msg)
                self.assertEqual(popen.call_args[0][0], ["explorer.exe", str(exe)])

    def test_run_manage_reports_skill_warnings_without_failing(self):
        for skill, expected in [({"state": "preserved_conflict"}, "已原样保留"),
                                ({"state": "unavailable", "warning": "无法同步模板"}, "无法同步模板")]:
            with self.subTest(skill=skill), mock.patch.object(launcher.subprocess, "run",
                    return_value=mock.Mock(returncode=0, stdout=json.dumps({"state": "uninstalled", "skill": skill}))):
                ok, message = launcher.run_manage("uninstall")
                self.assertTrue(ok)
                self.assertIn("卸载完成", message)
                self.assertIn("[警告]", message)
                self.assertIn(expected, message)

    def test_main_auto_close_and_auto_restart_flow(self):
        with tempfile.TemporaryDirectory() as td:
            pkg = Path(td) / "pkg"
            app = Path(td) / "app"
            pkg.mkdir()
            (app / "resources/bin").mkdir(parents=True)
            (pkg / "manage.py").write_text("", encoding="utf-8")
            (pkg / "release.json").write_text("{}", encoding="utf-8")
            (app / "Antigravity.exe").write_bytes(b"MZ")
            (app / "resources/bin/language_server.exe").write_bytes(b"MZ")
            fake_status = {
                "python_ok": True,
                "python_version": "3.13.0",
                "is_admin": False,
                "app_present": True,
                "package_version": "0.4.4",
                "package_flavor": "subscription",
                "package_host": "2.35.1",
                "package_build": "newbuild",
                "installed": True,
                "installed_version": "0.4.3",
                "installed_build": "oldbuild",
                "has_predecessor": True,
                "same_build": False,
                "running": True,
            }
            with mock.patch.object(launcher, "HERE", pkg), \
                 mock.patch.object(launcher, "app_dir", return_value=app), \
                 mock.patch.object(launcher, "current_status", return_value=fake_status), \
                 mock.patch.object(launcher, "antigravity_running", return_value=True), \
                 mock.patch.object(launcher, "stop_antigravity", return_value=(True, "已正常退出")) as stop_mock, \
                 mock.patch.object(launcher, "run_manage", return_value=(True, "升级完成")) as manage_mock, \
                 mock.patch.object(launcher, "launch_antigravity", return_value=(True, "已启动")) as launch_mock, \
                 mock.patch("builtins.input", side_effect=["1", ""]), \
                 mock.patch("sys.stdout", new_callable=io.StringIO):
                code = launcher.main([])
                self.assertEqual(code, 0)
                stop_mock.assert_called_once_with(app)
                manage_mock.assert_called_once_with("upgrade")
                launch_mock.assert_called_once_with(app)

    def test_main_already_stopped_prompts_launch(self):
        with tempfile.TemporaryDirectory() as td:
            pkg = Path(td) / "pkg"
            app = Path(td) / "app"
            pkg.mkdir()
            app.mkdir()
            (pkg / "manage.py").write_text("", encoding="utf-8")
            (pkg / "release.json").write_text("{}", encoding="utf-8")
            fake_status = {
                "python_ok": True,
                "python_version": "3.13.0",
                "is_admin": False,
                "app_present": True,
                "package_version": "0.4.4",
                "package_flavor": "subscription",
                "package_host": "2.35.1",
                "package_build": "newbuild",
                "installed": False,
                "installed_version": None,
                "installed_build": None,
                "has_predecessor": False,
                "same_build": False,
                "running": False,
            }
            with mock.patch.object(launcher, "HERE", pkg), \
                 mock.patch.object(launcher, "app_dir", return_value=app), \
                 mock.patch.object(launcher, "current_status", return_value=fake_status), \
                 mock.patch.object(launcher, "antigravity_running", return_value=False), \
                 mock.patch.object(launcher, "stop_antigravity") as stop_mock, \
                 mock.patch.object(launcher, "run_manage", return_value=(True, "安装完成")) as manage_mock, \
                 mock.patch.object(launcher, "launch_antigravity", return_value=(True, "已启动")) as launch_mock, \
                 mock.patch("builtins.input", side_effect=["1", ""]), \
                 mock.patch("sys.stdout", new_callable=io.StringIO):
                code = launcher.main([])
                self.assertEqual(code, 0)
                stop_mock.assert_not_called()
                manage_mock.assert_called_once_with("install")
                launch_mock.assert_called_once_with(app)


if __name__ == "__main__":
    unittest.main()
