import ctypes, hashlib, json, msvcrt, os, struct, tempfile
from ctypes import wintypes
from pathlib import Path

def require(ok, message):
    if not ok: raise ValueError(message)

def sha(data):
    return hashlib.sha256(data).hexdigest()

def file_hash(path):
    with path.open('rb') as f: return hashlib.file_digest(f,'sha256').hexdigest()

def unpack(data):
    outer,blob,payload,count = struct.unpack_from('<4I',data)
    require(outer==4 and blob==payload+4 and 4<=payload-count<=7,'Unknown archive format')
    return json.loads(data[16:16+count]), data[8+blob:]

def entry(tree,name):
    for part in name.split('/'): tree=tree['files'][part]
    return tree

def read(tree,data,name):
    ent=entry(tree,name)
    at=int(ent['offset'])
    return data[at:at+ent['size']]

def edit(path, transform):
    # Deny simultaneous writers while computing the edit; preserve file ACLs.
    k = ctypes.WinDLL("kernel32",use_last_error=True)
    op = k.CreateFileW
    op.argtypes = [wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,wintypes.LPVOID,wintypes.DWORD,wintypes.DWORD,wintypes.HANDLE]
    op.restype = wintypes.HANDLE
    replace = k.ReplaceFileW
    replace.argtypes = [wintypes.LPCWSTR,wintypes.LPCWSTR,wintypes.LPCWSTR,wintypes.DWORD,wintypes.LPVOID,wintypes.LPVOID]
    replace.restype = wintypes.BOOL
    h = op(str(path),0x80000000,5,None,3,0x80,None)
    if h in (None,ctypes.c_void_p(-1).value):
        raise ctypes.WinError(ctypes.get_last_error())
    with os.fdopen(msvcrt.open_osfhandle(h,os.O_RDONLY|os.O_BINARY),"rb") as f:
        old = f.read()
        new = transform(old)
        if new == old:
            return
        with tempfile.NamedTemporaryFile(dir=path.parent,delete=False) as out:
            tmp = Path(out.name)
            out.write(new)
            out.flush()
            os.fsync(out.fileno())
        try:
            if path.read_bytes() != old:
                raise ValueError("Concurrent host update")
            if not replace(str(path),str(tmp),None,0,None,None):
                raise ctypes.WinError(ctypes.get_last_error())
        finally:
            tmp.unlink(missing_ok=True)
