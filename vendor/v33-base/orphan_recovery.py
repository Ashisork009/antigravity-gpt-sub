"""Release our verified orphaned Windows global sidecar worker when it holds its working directory."""
import ctypes
from ctypes import wintypes
from dataclasses import dataclass
import os
from pathlib import Path
import time
from urllib.parse import urlsplit
from urllib.request import url2pathname


@dataclass(frozen=True)
class Identity:
    cwd:Path
    shell:Path
    wrapper:Path
    loader:Path
    helper:Path


def installed_identity(side):
    return Identity(Path(side),Path(os.environ['SystemRoot'])/'System32/cmd.exe',
                    Path(os.environ['APPDATA'])/'Antigravity/bin/agy-node.cmd',
                    Path.home()/'.gemini/antigravity/lib/node_modules/sidecar_sdk/register_loader.js',
                    Path(os.environ['LOCALAPPDATA'])/'Programs/antigravity/Antigravity.exe')


def same(a,b):
    return os.path.isabs(str(a)) and os.path.normcase(os.path.normpath(str(a)))==os.path.normcase(os.path.normpath(str(b)))


def split(command):
    shell32=ctypes.WinDLL('shell32',use_last_error=True)
    fn=shell32.CommandLineToArgvW
    fn.argtypes=[wintypes.LPCWSTR,ctypes.POINTER(ctypes.c_int)]
    fn.restype=ctypes.POINTER(wintypes.LPWSTR)
    count=ctypes.c_int()
    ptr=fn('command '+command,ctypes.byref(count))
    if not ptr:raise ctypes.WinError(ctypes.get_last_error())
    free=ctypes.WinDLL('kernel32').LocalFree
    free.argtypes=[ctypes.c_void_p]
    free.restype=ctypes.c_void_p
    try:return list(ptr[1:count.value])
    finally:free(ptr)


def worker_args(args,identity):
    if len(args)!=2 or args[1]!='renew.mjs' or not args[0].startswith('--import='):return False
    target=urlsplit(args[0][len('--import='):])
    if target.scheme!='file' or target.netloc or target.query or target.fragment:return False
    return same(url2pathname(target.path),identity.loader)


def shell_args(args,identity):
    if len(args)<3 or args[1].casefold()!='/c':return False
    argv=split(args[2]) if len(args)==3 else args[2:]
    return len(argv)==3 and same(argv[0],identity.wrapper) and worker_args(argv[1:],identity)


def native_shell(p,identity,user):
    return same(p.exe(),identity.shell) and same(p.cwd(),identity.cwd) and p.username().casefold()==user and shell_args(p.cmdline(),identity)


def native_worker(p,identity,user):
    return same(p.exe(),identity.helper) and same(p.cwd(),identity.cwd) and p.username().casefold()==user and worker_args(p.cmdline()[1:],identity)


def tasks(proc,identity,user):
    # A CREATE_NO_WINDOW cmd can have a Windows-owned console host in addition to its worker.
    # Ignore the OS helper, which exits normally when its attached console closes.
    return [c for c in proc.children()
            if not (same(c.exe(),identity.shell.parent/'conhost.exe') and c.username().casefold()==user)]


def reclaim(identity,wait=18):
    try:
        import psutil
    except ImportError as exc:
        raise RuntimeError('A process holds the global sidecar directory. Python psutil is required to identify its owner.') from exc
    user=psutil.Process().username().casefold()
    selected=[]
    for proc in psutil.process_iter(['name']):
        if (proc.info['name'] or '').casefold()!='cmd.exe':continue
        try:
            if not native_shell(proc,identity,user) or proc.parent() is not None:continue
            children=tasks(proc,identity,user)
            if len(children)==1 and native_worker(children[0],identity,user):selected.append((proc,children[0]))
        except (psutil.NoSuchProcess,psutil.AccessDenied):continue
    if len(selected)>1:raise RuntimeError('Multiple matching orphan sidecars; directory left intact')
    if not selected:return 0
    proc,worker=selected[0]
    until=time.monotonic()+wait
    while time.monotonic()<until:
        try:
            if not native_shell(proc,identity,user) or proc.parent() is not None or tasks(proc,identity,user)!=[worker]:
                raise RuntimeError('Sidecar command process changed; keeping the process intact')
            if not native_worker(worker,identity,user):
                raise RuntimeError('Sidecar worker identity changed')
            if tasks(worker,identity,user):
                # Let a native verification helper complete normally; never stop its descendants.
                time.sleep(.1)
                continue
            worker.terminate()
            worker.wait(4)
            try:proc.wait(4)
            except psutil.TimeoutExpired:
                if not native_shell(proc,identity,user) or proc.parent() is not None or tasks(proc,identity,user):
                    raise RuntimeError('A different process now holds the sidecar directory')
                proc.terminate()
                proc.wait(4)
            return 1
        except psutil.NoSuchProcess:
            return 0
    raise RuntimeError('Sidecar still has active child processes; they were left intact')


def retire_sidecar(side,retired):
    # Previously confirmed that the desktop and LS have exited. Recheck their identity
    # immediately before releasing the working directory of an orphaned worker.
    from manage import ensure_stopped
    identity=installed_identity(side)
    ensure_stopped(identity.helper.parent)
    reclaim(identity)
    deadline=time.monotonic()+4
    while True:
        try:
            side.rename(retired)
            return
        except PermissionError:
            if time.monotonic()>=deadline:raise
            time.sleep(.15)
