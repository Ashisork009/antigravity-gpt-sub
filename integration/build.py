"""Assemble one checksum-addressed installable archive without an Antigravity executable."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from zipfile import ZipFile, ZIP_DEFLATED, ZipInfo

HERE=Path(__file__).resolve().parent
SRC=HERE.parent
OLD=SRC/'vendor/v33-base'
RELEASES=SRC/'release'
VERSION='0.4.7'
def sha(b):return hashlib.sha256(b).hexdigest()
def put(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(value,encoding='utf8',newline='\n')
def cp(source,target):
    target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,target)
def once(value,before,after):
    if value.count(before)!=1:raise ValueError('Unsupported desktop adapter or source revision: '+before)
    return value.replace(before,after)

def populate(target,fixture):
    for filename in ('asar_tools.py','sidecar_config.py','project_owner.py','orphan_recovery.py'):
        cp(OLD/filename,target/filename)
    core=(OLD/'manage.py').read_text(encoding='utf8')
    core=once(core,"if (index >= 0 && args[index+1] === 'https://daily-cloudcode-pa.googleapis.com') args[index+1] = nativeCloud;",
        """if (index >= 0 && args[index+1] === 'https://daily-cloudcode-pa.googleapis.com' && !args.some(arg => arg === '--web_bundle_path' || arg.startsWith('--web_bundle_path='))) {
                args[index+1] = nativeCloud.cloud;
                args.push('--web_bundle_path',nativeCloud.webBundle);
            }""")
    # Avoid tempfile.TemporaryDirectory's 0o700 owner-only ACL on Windows when elevated;
    # a plain sibling staging directory inherits destination.parent's normal per-user NTFS ACL.
    core=once(core,"""        with tempfile.TemporaryDirectory(dir=destination.parent) as stage:
            prepared=Path(stage)/'files'
            shutil.copytree(HERE/kind,prepared)
            require(manifest_files(prepared)==hashes,'Staging failed')
            prepared.rename(destination)""",
        """        stage=destination.parent/('.stage-'+uuid4().hex)
        stage.mkdir()
        try:
            prepared=stage/'files'
            shutil.copytree(HERE/kind,prepared)
            require(manifest_files(prepared)==hashes,'Staging failed')
            prepared.rename(destination)
        finally:
            shutil.rmtree(stage,ignore_errors=True)""")
    put(target/'core_manage.py',core)
    cp(SRC/'catalog/renderer_overlay.py',target/'renderer_overlay.py')
    spec=importlib.util.spec_from_file_location('renderer_overlay',target/'renderer_overlay.py')
    overlay=importlib.util.module_from_spec(spec);sys.modules[spec.name]=overlay;spec.loader.exec_module(overlay)
    overlay_hash=overlay.EXPECTED_OVERLAY_SHA256
    if not re.fullmatch(r'[a-f0-9]{64}',overlay_hash):raise ValueError('Invalid renderer overlay digest')
    # The inherited orphan helper uses ensure_stopped through the installed manager's public name.
    cp(HERE/'managed_install.py',target/'manage.py')
    cp(HERE/'overlay_install.py',target/'overlay_install.py')
    cp(HERE/'launcher.py',target/'launcher.py')
    (target/'双击安装或管理.cmd').write_bytes((HERE/'launcher.cmd').read_text(encoding='utf8').replace('\r\n','\n').replace('\n','\r\n').encode('ascii'))
    cp(OLD/'contents.json',target/'previous-v33.json')
    run=target/'runtime'
    code=run/'restart2351'
    put(code/'web-bundle.json',json.dumps({'sha256':overlay_hash},sort_keys=True))
    desktop=(HERE/'desktop.mjs').read_text(encoding='utf8')
    desktop=desktop.replace("from '../../catalog/","from '../catalog/").replace("from '../../subscription/","from '../subscription/")
    put(code/'desktop.mjs',desktop)
    for folder,names in [('subscription',['generate.mjs','plan.mjs','vault.mjs']),('catalog',['catalog.mjs','serve.mjs','store.mjs','transport.mjs'])]:
        for name in names:cp(SRC/folder/name,run/folder/name)
    old_runtime=OLD/'runtime/restart2351/router'
    subprocess.run([sys.executable,'-B',str(SRC/'subscription/prepare_codec.py'),str(old_runtime/'codex/backend.mjs'),str(code/'router/codex/backend.mjs')],check=True)
    cp(old_runtime/'lease/gate.mjs',code/'router/lease/gate.mjs')
    vendor=(old_runtime/'desktop_runtime.mjs').read_text(encoding='utf8')
    section=vendor[vendor.index('const vendorHosts'):vendor.index('function cockpitKey')]
    put(code/'vendor.mjs',"import { Readable } from 'node:stream';\n"+section)
    fragment=(OLD/'host_fragment.cjs').read_text(encoding='utf8')
    fragment=once(fragment,"'restart2351','router','desktop_runtime.mjs'","'restart2351','desktop.mjs'")
    fragment=once(fragment,'            const mod = await import(','''            const expected = JSON.parse(fs.readFileSync(path.join(runtime,'restart2351','web-bundle.json'),'utf8')).sha256;
            if (!/^[a-f0-9]{64}$/.test(expected)) return;
            const webBundle = path.join(base,'overlays',expected+'.zip');
            if (fs.realpathSync.native(webBundle).toLowerCase() !== webBundle.toLowerCase() || await digest(webBundle) !== expected) return;
            const mod = await import(''')
    fragment=once(fragment,'return router.cloud;','return {cloud:router.cloud,webBundle};')
    additions="""safeStorage:electron_1.safeStorage,
                openExternal:(target)=>{
                    const url=new URL(target);
                    if (url.origin!=='https://auth.openai.com' || url.pathname!=='/api/accounts/authorize' || url.username || url.password)
                        throw Error('Unknown subscription authorization origin');
                    return electron_1.shell.openExternal(url.href);
                },"""
    if fixture:
        cp(HERE/'fixture.mjs',code/'fixture.mjs')
        additions+="""
                fixture:(await import(require('node:url').pathToFileURL(path.join(runtime,'restart2351','fixture.mjs')).href)).openFixture,"""
    fragment=once(fragment,'stateDir:base,','stateDir:base,\n                '+additions)
    put(target/'host_fragment.cjs',fragment)
    shutil.copytree(OLD/'sidecar',target/'sidecar')
    renewal=target/'sidecar/renew.mjs'
    renew=renewal.read_text(encoding='utf8')
    read_rev="""function panelRevision() {
  try {
    const file=join(homedir(),'.antigravity-native-model-router','run','plan-panel.json');
    const rev=JSON.parse(readFileSync(file,'utf8')).revision;
    return typeof rev==='string' && /^[a-f0-9]{64}$/i.test(rev) ? rev : 'initial';
  } catch { return 'initial'; }
}
"""
    renew=once(renew,'async function renew() {',read_rev+'\nasync function renew() {')
    for v in ['0','1']:
        renew=once(renew,"updates.update(active.epoch+':"+v+"')","updates.update(active.epoch+':'+panelRevision()+':"+v+"')")
    put(renewal,renew)
    control=target/'sidecar/control.mjs'
    value=control.read_text(encoding='utf8')
    if value.count("epoch:current.slice(0,-2)")!=2:raise ValueError('Unexpected refresh control format')
    put(control,value.replace("epoch:current.slice(0,-2)","epoch:current.split(':')[0],revision:current.split(':')[1]"))
    plugin=json.loads((OLD/'plugin/plugin.json').read_bytes())
    plugin.update(version=VERSION,display_name='Codex 订阅模型',description='在 Antigravity 原生对话中选择订阅模型和推理等级。')
    if fixture:plugin['display_name']+='（确定性验收）'
    put(target/'plugin/plugin.json',json.dumps(plugin,ensure_ascii=False,indent=2))
    for name in ['sidecar.json','main.mjs','store.mjs','panel.css','panel.js','index.html']:
        cp(HERE/'panel'/name,target/'plugin/sidecars/settings'/name)
    catalog={kind:{p.relative_to(target/kind).as_posix():sha(p.read_bytes()) for p in sorted((target/kind).rglob('*')) if p.is_file()} for kind in ['plugin','runtime','sidecar']}
    put(target/'contents.json',json.dumps(catalog,sort_keys=True,indent=2))
    put(target/'release.json',json.dumps({'version':VERSION,'flavor':'fixture' if fixture else 'subscription','host':'2.35.1','web_bundle_sha256':overlay_hash,'build':sha(json.dumps(catalog,sort_keys=True,separators=(',',':')).encode())[:20]},indent=2))
    cp(HERE/'installation.md',target/'README.md')

def build(fixture):
    RELEASES.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='native-model-release-') as d:
        temp=Path(d);pkg=temp/'package';pkg.mkdir()
        populate(pkg,fixture)
        # Parse every shipped JavaScript module; importing user-facing panels requires the native SDK.
        for module in [*pkg.rglob('*.mjs'),*pkg.rglob('*.cjs'),*pkg.rglob('*.js')]:
            subprocess.run(['node','--check',str(module)],check=True)
        for module in pkg.rglob('*.py'):compile(module.read_bytes(),str(module),'exec')
        zpath=temp/'archive.zip'
        with ZipFile(zpath,'w',compression=ZIP_DEFLATED) as z:
            for p in sorted(pkg.rglob('*')):
                if not p.is_file():continue
                info=ZipInfo(p.relative_to(pkg).as_posix(),date_time=(2026,1,1,0,0,0));info.compress_type=ZIP_DEFLATED
                z.writestr(info,p.read_bytes())
        digest=sha(zpath.read_bytes());meta=json.loads((pkg/'release.json').read_bytes())
        name='native-model-router-'+meta['version']+'-'+meta['flavor']+'-'+digest[:12]
        out=RELEASES/name
        if not out.exists():shutil.copytree(pkg,out)
        dest=RELEASES/(name+'.zip')
        if not dest.exists():shutil.copyfile(zpath,dest)
        if sha(dest.read_bytes())!=digest:raise ValueError('Release name collision')
        print(json.dumps({'archive':str(dest),'directory':str(out),'sha256':digest,**meta},ensure_ascii=True))

if __name__=='__main__':
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--fixture',action='store_true')
    build(cli.parse_args().fixture)
