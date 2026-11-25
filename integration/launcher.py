"""Interactive Windows double-click installer and manager for the Antigravity native model plugin."""
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent


def is_admin():
    if os.name != "nt":
        return False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def app_dir():
    return Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/antigravity"


def state_dir():
    return Path.home() / ".antigravity-native-model-router"


def powershell_exe():
    return Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"


def read_json(path):
    try:
        return json.loads(Path(path).read_bytes())
    except Exception:
        return None


def _norm_path(value):
    return os.path.normcase(str(value or ""))


def list_target_processes(app=None):
    """Return running Antigravity desktop and language_server processes scoped to `app`."""
    app = Path(app) if app is not None else app_dir()
    if os.name != "nt":
        return []
    script = r"""$items = @(Get-CimInstance Win32_Process -Filter "Name='Antigravity.exe' OR Name='language_server.exe'" -ErrorAction SilentlyContinue | Where-Object {
    $_.ExecutablePath -eq $env:AGY_MANAGE_LS -or
    ($_.ExecutablePath -eq $env:AGY_MANAGE_EXE -and
     ($_.CommandLine -notmatch '(?:^|\s)"?--import(?:=|\s|")' -or $_.CommandLine -match '(?:^|\s)"?--type='))
} | ForEach-Object {
    [PSCustomObject]@{
        pid = [int]$_.ProcessId
        ppid = [int]$_.ParentProcessId
        name = [string]$_.Name
        exe = [string]$_.ExecutablePath
        cmd = [string]$_.CommandLine
    }
})
if ($items.Count -eq 0) { '[]' } else { $items | ConvertTo-Json -Compress }"""
    exe_path = app / "Antigravity.exe"
    ls_path = app / "resources/bin/language_server.exe"
    env = dict(os.environ, AGY_MANAGE_EXE=str(exe_path), AGY_MANAGE_LS=str(ls_path))
    try:
        res = subprocess.run(
            [str(powershell_exe()), "-NoLogo", "-NonInteractive", "-NoProfile", "-Command", script],
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            timeout=20,
        )
    except Exception:
        return []
    if res.returncode != 0:
        return []
    raw = (res.stdout or "").strip()
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except Exception:
        return []
    if isinstance(parsed, dict):
        parsed = [parsed]
    if not isinstance(parsed, list):
        return []

    ls_norm = _norm_path(ls_path)
    result = []
    for item in parsed:
        if not isinstance(item, dict) or not item.get("pid"):
            continue
        exe = str(item.get("exe") or "")
        cmd = str(item.get("cmd") or "")
        if _norm_path(exe) == ls_norm:
            kind = "ls"
        elif "--type=" in cmd:
            kind = "helper"
        else:
            kind = "root"
        result.append({
            "pid": int(item["pid"]),
            "ppid": int(item.get("ppid") or 0),
            "name": str(item.get("name") or ""),
            "exe": exe,
            "cmd": cmd,
            "kind": kind,
        })
    return result


def antigravity_running(app=None):
    return bool(list_target_processes(app))


def request_graceful_close(root_pids):
    """Ask Antigravity desktop root PIDs to exit cleanly via Windows Restart Manager."""
    if os.name != "nt" or not root_pids:
        return False
    try:
        rm = ctypes.WinDLL("rstrtmgr")
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)

        class RM_UNIQUE_PROCESS(ctypes.Structure):
            _fields_ = [("dwProcessId", wintypes.DWORD), ("ProcessStartTime", wintypes.FILETIME)]

        k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.GetProcessTimes.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
        ]
        k32.GetProcessTimes.restype = wintypes.BOOL
        k32.CloseHandle.argtypes = [wintypes.HANDLE]
        k32.CloseHandle.restype = wintypes.BOOL

        rm.RmStartSession.argtypes = [ctypes.POINTER(wintypes.DWORD), wintypes.DWORD, wintypes.LPWSTR]
        rm.RmStartSession.restype = wintypes.DWORD
        rm.RmRegisterResources.argtypes = [
            wintypes.DWORD, wintypes.UINT, ctypes.c_void_p,
            wintypes.UINT, ctypes.POINTER(RM_UNIQUE_PROCESS),
            wintypes.UINT, ctypes.c_void_p,
        ]
        rm.RmRegisterResources.restype = wintypes.DWORD
        rm.RmShutdown.argtypes = [wintypes.DWORD, wintypes.ULONG, ctypes.c_void_p]
        rm.RmShutdown.restype = wintypes.DWORD
        rm.RmEndSession.argtypes = [wintypes.DWORD]
        rm.RmEndSession.restype = wintypes.DWORD

        entries = []
        for pid in root_pids:
            hp = k32.OpenProcess(0x1000, False, int(pid))
            if not hp:
                continue
            start, ended, kernel, user = (wintypes.FILETIME() for _ in range(4))
            try:
                if k32.GetProcessTimes(hp, ctypes.byref(start), ctypes.byref(ended), ctypes.byref(kernel), ctypes.byref(user)):
                    entries.append(RM_UNIQUE_PROCESS(int(pid), start))
            finally:
                k32.CloseHandle(hp)
        if not entries:
            return False

        handle = wintypes.DWORD()
        session_key = ctypes.create_unicode_buffer(33)
        if rm.RmStartSession(ctypes.byref(handle), 0, session_key) != 0:
            return False
        try:
            arr = (RM_UNIQUE_PROCESS * len(entries))(*entries)
            if rm.RmRegisterResources(handle, 0, None, len(entries), arr, 0, None) != 0:
                return False
            return rm.RmShutdown(handle, 0, None) == 0
        finally:
            rm.RmEndSession(handle)
    except Exception:
        return False


def force_kill_processes(procs):
    """Force-stop only the explicitly verified Antigravity / language_server PIDs."""
    if os.name != "nt":
        return
    # Kill root desktop processes first with /T, then any remaining helper or language_server PIDs.
    ordered = sorted(procs, key=lambda p: (0 if p.get("kind") == "root" else 1 if p.get("kind") == "ls" else 2, p["pid"]))
    seen = set()
    for proc in ordered:
        pid = int(proc["pid"])
        if pid in seen:
            continue
        seen.add(pid)
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                timeout=10,
            )
        except Exception:
            pass


def stop_antigravity(app=None, timeout=15.0, graceful_wait=5.0, poll_interval=0.25, settle=0.8, log=print):
    """Gracefully shut down Antigravity (Restart Manager), falling back to scoped force-kill."""
    app = Path(app) if app is not None else app_dir()
    procs = list_target_processes(app)
    if not procs:
        return True, "Antigravity 当前未运行。"

    root_pids = [p["pid"] for p in procs if p.get("kind") == "root"]
    if root_pids:
        log(f"正在请求 Antigravity 正常退出（主进程 PID: {', '.join(str(x) for x in root_pids)}）...")
        request_graceful_close(root_pids)
    else:
        log("检测到残留的 Antigravity 后台进程，准备清理...")

    deadline = time.monotonic() + timeout
    grace_deadline = min(deadline, time.monotonic() + (graceful_wait if root_pids else 0.0))
    while time.monotonic() < grace_deadline:
        procs = list_target_processes(app)
        if not procs:
            if settle > 0:
                time.sleep(settle)
            return True, "Antigravity 已正常退出。"
        time.sleep(poll_interval)

    procs = list_target_processes(app)
    if not procs:
        if settle > 0:
            time.sleep(settle)
        return True, "Antigravity 已正常退出。"

    log(f"仍有 {len(procs)} 个 Antigravity 相关进程未退出，正在强制结束目标进程...")
    force_kill_processes(procs)
    while time.monotonic() < deadline:
        procs = list_target_processes(app)
        if not procs:
            if settle > 0:
                time.sleep(settle)
            return True, "已自动关闭所有 Antigravity 进程。"
        time.sleep(poll_interval)
        if procs:
            force_kill_processes(procs)

    remaining = ", ".join(f"{p['name']}(PID {p['pid']})" for p in procs[:6])
    return False, f"以下 Antigravity 进程未能自动关闭，请手动退出后重试：{remaining}"


def launch_antigravity(app=None):
    """Launch Antigravity detached; if running elevated as Admin, delegate via explorer.exe to avoid elevation."""
    app = Path(app) if app is not None else app_dir()
    exe = app / "Antigravity.exe"
    if not exe.is_file():
        return False, f"未找到 Antigravity 可执行文件：{exe}"
    try:
        if os.name == "nt" and is_admin():
            subprocess.Popen(
                ["explorer.exe", str(exe)],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
            )
            return True, f"已通过桌面会话启动 Antigravity（普通权限）：{exe}"
        flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        subprocess.Popen(
            [str(exe)],
            cwd=str(app),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=flags,
            close_fds=True,
        )
        return True, f"已启动 Antigravity：{exe}"
    except Exception as exc:
        return False, f"自动启动 Antigravity 失败（请手动打开）：{exc}"


def current_status(pkg_dir=HERE, store=None, app=None):
    store = store or state_dir()
    app = app or app_dir()
    release = read_json(pkg_dir / "release.json") or {}
    owned = read_json(store / "owned.json")
    installed_release = (owned or {}).get("release") or {}
    installed_build = (owned or {}).get("build")
    pkg_build = release.get("build")
    same_build = bool(installed_build and pkg_build and installed_build == pkg_build)
    return {
        "python_ok": sys.version_info >= (3, 11),
        "python_version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "is_admin": is_admin(),
        "app_present": (app / "Antigravity.exe").is_file() and (app / "resources/bin/language_server.exe").is_file(),
        "package_version": release.get("version", "unknown"),
        "package_flavor": release.get("flavor", "subscription"),
        "package_host": release.get("host", "unknown"),
        "package_build": pkg_build or "unknown",
        "installed": owned is not None,
        "installed_version": installed_release.get("version") or ("v3.3" if installed_build else None),
        "installed_build": installed_build,
        "has_predecessor": bool((owned or {}).get("predecessor")),
        "same_build": same_build,
        "running": antigravity_running(app),
    }


def format_result(action, data):
    state = data.get("state")
    if state == "installed":
        return f"安装完成！（构建号：{data.get('build')}）"
    if state == "upgraded":
        return f"升级完成！（{data.get('from', '')} -> {data.get('build')}）"
    if state == "verified":
        return f"校验通过：当前安装完整无损（构建号：{data.get('build')}）。"
    if state == "repaired":
        return f"修复完成！损坏的旧文件已备份至：\n  {data.get('backup')}"
    if state == "restored_previous":
        return f"已成功回滚到上一版本（构建号：{data.get('build')}）。"
    if state == "uninstalled":
        return "卸载完成！已还原为原厂 Antigravity 归档（订阅登录与偏好设置保留在用户目录）。"
    if state == "already absent":
        return "当前未检测到已安装的插件部署，无需执行该操作。"
    if action == "preview":
        return f"预览校验通过！\n  构建号：{data.get('build')}\n  候选归档 SHA-256：{data.get('candidate')}"
    return json.dumps(data, ensure_ascii=False, indent=2)


def run_manage(action, pkg_dir=HERE):
    cmd = [sys.executable, "-B", str(pkg_dir / "manage.py"), action]
    proc = subprocess.run(cmd, cwd=pkg_dir, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode == 0:
        try:
            data = json.loads(proc.stdout.strip().splitlines()[-1])
            return True, format_result(action, data)
        except Exception:
            return True, proc.stdout.strip() or "操作完成。"
    detail = (proc.stderr or proc.stdout or "").strip()
    lines = [line.strip() for line in detail.splitlines() if line.strip()]
    summary = lines[-1] if lines else f"退出码 {proc.returncode}"
    return False, f"操作未完成：{summary}"


def wait_until_stopped(app=None):
    print("\n正在等待 Antigravity 完全退出（请退出窗口及系统托盘图标，按 Ctrl+C 可取消等待）...")
    while antigravity_running(app):
        time.sleep(1.0)
    print("检测到 Antigravity 已完全退出，继续执行！")


def print_banner(st):
    flavor_label = "正式订阅版" if st["package_flavor"] == "subscription" else "确定性验收版"
    print("=" * 64)
    print(f"  Antigravity Codex 原生订阅模型插件安装器  v{st['package_version']}（{flavor_label}）")
    print("=" * 64)
    print(f"  适配宿主版本 : Antigravity {st['package_host']}")
    print(f"  本包构建号   : {st['package_build']}")
    print(f"  Python 环境  : {st['python_version']}")
    if st["installed"]:
        ver = f"v{st['installed_version']}" if st["installed_version"] and not str(st["installed_version"]).startswith("v") else (st["installed_version"] or "未知")
        suffix = "（与本包一致）" if st["same_build"] else ""
        print(f"  当前部署状态 : 已安装 {ver} [{st['installed_build']}]{suffix}")
    else:
        print("  当前部署状态 : 未安装")
    print(f"  Antigravity  : {'运行中（执行修改前支持自动关闭并自动重启）' if st['running'] else '已退出（可直接操作）'}")
    if st["is_admin"]:
        print("  权限提示     : 当前为管理员模式（自动重启时将通过桌面会话以普通权限启动）")
    print("-" * 64)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--status" in argv:
        print(json.dumps(current_status(), ensure_ascii=False, indent=2))
        return 0
    no_kill = "--no-kill" in argv
    no_restart = "--no-restart" in argv
    if sys.version_info < (3, 11):
        print(f"[错误] 需要 Python 3.11 或更高版本，当前为 {sys.version.split()[0]}。")
        return 1
    if not (HERE / "manage.py").is_file() or not (HERE / "release.json").is_file():
        print("[错误] 请先将整个发布包 ZIP 完整解压到文件夹，再双击本脚本。")
        return 1

    app = app_dir()
    while True:
        st = current_status(app=app)
        print()
        print_banner(st)
        if not st["app_present"]:
            print("[警告] 未在默认目录找到 Antigravity（%LOCALAPPDATA%\\Programs\\antigravity）。")
        primary_label = "重新校验/修复本版本" if st["same_build"] else ("升级到此版本" if st["installed"] else "安装此版本")
        print(f"  [1] {primary_label}")
        print("  [2] 修复损坏或误删的插件文件（repair）")
        print("  [3] 回滚到上一版本（rollback）")
        print("  [4] 卸载插件并还原原版 Antigravity（uninstall）")
        print("  [5] 仅预览校验（preview，不改动任何文件）")
        print("  [0] 退出")
        print()
        try:
            choice = input("请输入选项编号并回车 [默认 1]: ").strip() or "1"
        except (EOFError, KeyboardInterrupt):
            print("\n已退出。")
            return 0

        if choice == "0":
            return 0

        action_map = {
            "1": "upgrade" if st["installed"] else "install",
            "2": "repair",
            "3": "rollback",
            "4": "uninstall",
            "5": "preview",
        }
        action = action_map.get(choice)
        if not action:
            print(f"\n无效选项：{choice}，请重新输入。")
            continue

        if action == "uninstall":
            confirm = input("确认卸载插件并还原原版 Antigravity 吗？输入 Y 确认: ").strip().lower()
            if confirm != "y":
                print("已取消卸载。")
                continue

        if action == "rollback" and not st["has_predecessor"]:
            print("\n当前部署记录没有可回滚的上一版本快照。")
            continue

        needs_stop = action not in ("preview", "repair")
        was_running = bool(needs_stop and antigravity_running(app))
        auto_closed = False
        if was_running:
            if no_kill:
                print("\n已指定 --no-kill，请手动退出 Antigravity（含系统托盘图标）。")
                try:
                    wait_until_stopped(app)
                except KeyboardInterrupt:
                    print("\n已取消等待。")
                    continue
            else:
                print("\n检测到 Antigravity 正在运行，修改文件前需先关闭进程。")
                print("  [Y] 自动关闭 Antigravity 并在完成后自动重启（默认，直接回车）")
                print("  [W] 由我手动退出，脚本等待退出后继续")
                print("  [N] 取消并返回主菜单")
                mode = (input("请选择 [Y/W/N，默认 Y]: ").strip() or "y").lower()
                if mode == "y":
                    ok_stop, stop_msg = stop_antigravity(app)
                    print(("[成功] " if ok_stop else "[失败] ") + stop_msg)
                    if not ok_stop:
                        continue
                    auto_closed = True
                elif mode == "w":
                    try:
                        wait_until_stopped(app)
                    except KeyboardInterrupt:
                        print("\n已取消等待。")
                        continue
                else:
                    continue

        print(f"\n正在执行 {action} ...")
        ok, message = run_manage(action)
        print()
        print(("[成功] " if ok else "[失败] ") + message)

        if ok and action in ("install", "upgrade", "rollback", "uninstall"):
            if not no_restart and st["app_present"]:
                if was_running:
                    print("\n正在自动重新启动 Antigravity...")
                    ok_launch, launch_msg = launch_antigravity(app)
                    print(("[启动] " if ok_launch else "[警告] ") + launch_msg)
                else:
                    ans = (input("\n是否立即启动 Antigravity？[Y/n，默认 Y]: ").strip() or "y").lower()
                    if ans == "y":
                        ok_launch, launch_msg = launch_antigravity(app)
                        print(("[启动] " if ok_launch else "[警告] ") + launch_msg)
            return 0

        if not ok and auto_closed and not no_restart and st["app_present"]:
            ans = input("\n操作未完成，是否重新启动原 Antigravity？[y/N]: ").strip().lower()
            if ans == "y":
                ok_launch, launch_msg = launch_antigravity(app)
                print(("[启动] " if ok_launch else "[警告] ") + launch_msg)


if __name__ == "__main__":
    raise SystemExit(main())
