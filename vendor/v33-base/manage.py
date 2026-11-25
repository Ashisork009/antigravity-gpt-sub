"""Version-checked, per-user Antigravity native model routing adapter."""
import argparse
from contextlib import contextmanager
import json
import msvcrt
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
from uuid import uuid4

from sidecar_config import SIDECAR_ID, enrollment, enable_sidecar
from asar_tools import edit, entry, file_hash, read, require, sha, unpack

HERE=Path(__file__).resolve().parent
VERSION='2.35.1'
EXE='fdf8a0a6af474d54301740bdf0144d95a30be3105d96a2cb39bb8086278513ac'
LANG='73ce9a2405b455a93d1f13db2ae555da50406110217a349b6dd85c377fbdb9d1'
BASE='2af16ea9944ef93b1eee49c1228c8b2cf355f95e2027940cb769c6ebae02ec3b'
MODULE='a6cd83287d7d1eaeab7af450e5af3eff960a2869e7eabd5ce1d8ce8459e87dcd'
MEMBER='dist/languageServer.js'


def direct(path):
    require(path.resolve()==path.absolute(),'Refusing a redirected path: '+str(path))
    return path


def manifest_files(root):
    direct(root)
    result={}
    for path in sorted(root.rglob('*')):
        direct(path)
        if path.is_file(): result[path.relative_to(root).as_posix()]=file_hash(path)
    return result


def checked_contents():
    items=json.loads((HERE/'contents.json').read_bytes())
    for kind in ['runtime','plugin','sidecar']:
        require(items[kind]==manifest_files(HERE/kind),'Release files changed: '+kind)
    return items


def build_id(items):
    return sha(json.dumps(items,sort_keys=True,separators=(',',':')).encode())[:20]


def patched_archive(original, items):
    require(sha(original)==BASE,'Archive differs from the supported 2.35.1 installation baseline')
    tree,body=unpack(original)
    source=read(tree,body,MEMBER)
    require(sha(source)==MODULE and json.loads(read(tree,body,'package.json'))['version']==VERSION,
            'Unsupported desktop entry point')
    fragment=(HERE/'host_fragment.cjs').read_text(encoding='utf8')
    for key,value in {'__BUILD_ID__':build_id(items),'__RUNTIME_HASHES__':json.dumps(items['runtime'],sort_keys=True),
                      '__EXE_HASH__':EXE,'__LANG_HASH__':LANG}.items():
        require(fragment.count(key)==1,'Unexpected host template')
        fragment=fragment.replace(key,value)
    first=b'async function startLanguageServer(port, csrf, options = {}) {'
    before=b'    const loginShellEnv = await shellEnvReads.take();'
    after=b'        // Point the LS at the main process'
    for anchor in [first,before,after]: require(source.count(anchor)==1,'Ambiguous host entry point')
    source=source.replace(first,fragment.encode()+b'\n'+first)
    source=source.replace(before,before+b'\n    const nativeCloud = (!headless && !wsl) ? await acquireNativeModelRoute() : undefined;')
    source=source.replace(after,b"""        if (nativeCloud) {
            const index = args.indexOf('--cloud_code_endpoint');
            if (index >= 0 && args[index+1] === 'https://daily-cloudcode-pa.googleapis.com') args[index+1] = nativeCloud;
        }
"""+after)
    ent=entry(tree,MEMBER)
    block=ent['integrity']['blockSize']
    ent.update(offset=str(len(body)),size=len(source))
    ent['integrity'].update(hash=sha(source),blocks=[sha(source[i:i+block]) for i in range(0,len(source),block)])
    header=json.dumps(tree,ensure_ascii=False,separators=(',',':')).encode()
    payload=(4+len(header)+3)//4*4
    patched=struct.pack('<4I',4,payload+4,payload,len(header))+header+bytes(payload-4-len(header))+body+source
    actual,data=unpack(patched)
    require(read(actual,data,MEMBER)==source and data[:-len(source)]==body,'ASAR verification failed')
    orig,_=unpack(original)
    actual['files']['dist']['files']['languageServer.js']=entry(orig,MEMBER)
    require(orig==actual,'Another archive member changed')
    return patched


def publish_file(dest, data):
    direct(dest)
    with tempfile.NamedTemporaryFile(dir=dest.parent,delete=False) as f:
        tmp=Path(f.name)
        try:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        except BaseException:
            f.close()
            tmp.unlink(missing_ok=True)
            raise
    try: tmp.rename(dest)  # Windows rename does not replace a concurrent destination.
    finally: tmp.unlink(missing_ok=True)


def publish_tree(kind, destination, hashes):
    direct(destination)
    if not destination.exists():
        destination.parent.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=destination.parent) as stage:
            prepared=Path(stage)/'files'
            shutil.copytree(HERE/kind,prepared)
            require(manifest_files(prepared)==hashes,'Staging failed')
            prepared.rename(destination)
    require(manifest_files(destination)==hashes,'Destination contains foreign changes: '+str(destination))


def compare_swap(archive, old, new):
    def transform(data):
        require(sha(data) in [old,sha(new)],'Desktop changed concurrently')
        return new
    edit(archive,transform)
    require(file_hash(archive)==sha(new),'Post-write verification failed')


@contextmanager
def lock(dir_):
    direct(dir_).mkdir(parents=True,exist_ok=True)
    with open(direct(dir_/'install.lock'),'a+b') as f:
        f.seek(0)
        msvcrt.locking(f.fileno(),msvcrt.LK_NBLCK,1)
        try: yield
        finally:
            f.seek(0)
            msvcrt.locking(f.fileno(),msvcrt.LK_UNLCK,1)


def change(action, archive, store, plugin, items):
    """The public command verifies stopped processes and binary hashes before entering."""
    build=build_id(items)
    image=direct(archive)
    runtime=direct(store/'runtime'/build)
    plugin=direct(plugin)
    side=direct(plugin.parent.parent/'sidecars'/SIDECAR_ID)
    config=direct(plugin.parent.parent/'config.json')
    with lock(store):
        journal=direct(store/'owned.json')
        backup=direct(store/('original-'+BASE+'.asar'))
        if journal.exists():
            owned=json.loads(journal.read_bytes())
            require(owned.get('build')==build and owned.get('root')==str(image) and owned.get('plugin')==str(plugin),
                    'Use the matching release and installation path to change this deployment')
        else:
            if action=='rollback': return 'No owned deployment'
            require(not plugin.exists() and not side.exists() and not runtime.exists(),'Existing unowned plugin or runtime; keeping it intact')
            receipt=enrollment(config)
            require(file_hash(image)==BASE,'Unsupported desktop archive')
            if not backup.exists(): publish_file(backup,image.read_bytes())
            require(file_hash(backup)==BASE,'Backup hash mismatch')
            candidate=patched_archive(backup.read_bytes(),items)
            owned={'enrollment':receipt,'build':build,'root':str(image),'plugin':str(plugin),'original':BASE,'candidate':sha(candidate)}
            publish_file(journal,json.dumps(owned,sort_keys=True).encode())
        original=backup.read_bytes()
        candidate=patched_archive(original,items)
        require(owned['candidate']==sha(candidate) and owned['original']==sha(original),'Backup or candidate differs from recorded deployment')
        require(file_hash(image) in [BASE,sha(candidate)],'Updated or unrecognized archive; keeping it intact')
        if action=='install':
            publish_tree('runtime',runtime,items['runtime'])
            publish_tree('plugin',plugin,items['plugin'])
            publish_tree('sidecar',side,items['sidecar'])
            enable_sidecar(config,owned['enrollment'],True)
            compare_swap(image,BASE,candidate)
            return 'Installed '+build
        compare_swap(image,sha(candidate),original)
        enable_sidecar(config,owned['enrollment'],False)
        for kind,path in [('plugin',plugin),('sidecar',side),('runtime',runtime)]:
            if path.exists():
                require(manifest_files(path)==items[kind],'Host restored; retaining edited '+kind)
                saved=store/'removed'/uuid4().hex
                saved.parent.mkdir(exist_ok=True)
                direct(saved)
                # The plugin may be on a different volume. Rename locally for an atomic unpublish.
                retired=path.with_name('.'+path.name+'-removed-'+uuid4().hex)
                try:
                    path.rename(retired)
                except PermissionError:
                    if kind!='sidecar':raise
                    from orphan_recovery import retire_sidecar
                    retire_sidecar(path,retired)
                shutil.move(str(retired),str(saved))
        journal.unlink()
        return 'Restored original archive '+BASE


def ensure_stopped(app):
    script=r"""$p = Get-CimInstance Win32_Process -Filter "Name='Antigravity.exe' OR Name='language_server.exe'" -ErrorAction Stop
if ($p | Where-Object {
    $_.ExecutablePath -eq $env:AGY_MANAGE_LS -or
    ($_.ExecutablePath -eq $env:AGY_MANAGE_EXE -and
     ($_.CommandLine -notmatch '(?:^|\s)"?--import(?:=|\s|")' -or $_.CommandLine -match '(?:^|\s)"?--type='))
}) {exit 18}"""
    env=dict(os.environ,AGY_MANAGE_EXE=str(app/'Antigravity.exe'),AGY_MANAGE_LS=str(app/'resources/bin/language_server.exe'))
    shell=Path(os.environ['SystemRoot'])/'System32/WindowsPowerShell/v1.0/powershell.exe'
    check=subprocess.run([str(shell),'-NoLogo','-NonInteractive','-NoProfile','-Command',script],env=env,
                         creationflags=subprocess.CREATE_NO_WINDOW,timeout=20)
    require(check.returncode==0,'Close the target desktop and its language service before changing its files')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['preview','install','rollback'])
    parser.add_argument('--archive',type=Path,help='Read-only preview of a backed-up archive')
    args=parser.parse_args()
    local=Path(os.environ['LOCALAPPDATA'])
    app=local/'Programs/antigravity'
    items=checked_contents()
    archive=app/'resources/app.asar'
    if args.action=='preview':
        archive=args.archive or archive
        print('Single-module candidate SHA-256:',sha(patched_archive(archive.read_bytes(),items)))
    else:
        require(not args.archive,'Explicit archive paths are only supported by read-only preview')
        require(file_hash(direct(app/'Antigravity.exe'))==EXE and file_hash(direct(app/'resources/bin/language_server.exe'))==LANG,
                'Unknown desktop binaries; refusing to modify or restore any installation')
        ensure_stopped(app)
        print(change(args.action,archive,Path.home()/'.antigravity-native-model-router',Path.home()/'.gemini/config/plugins/native-probe-router',items))
