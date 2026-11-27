"""Assemble one checksum-addressed installable archive without an Antigravity executable."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from zipfile import ZipFile, ZIP_DEFLATED, ZipInfo

HERE=Path(__file__).resolve().parent
SRC=HERE.parent
OLD=SRC/'vendor/v33-base'
RELEASES=SRC/'release'
VERSION='0.5.3'
HOST_VERSION='2.35.2'
def sha(b):return hashlib.sha256(b).hexdigest()
def put(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(value,encoding='utf8',newline='\n')
def cp(source,target):
    target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,target)
def once(value,before,after):
    if value.count(before)!=1:raise ValueError('Unsupported desktop adapter or source revision: '+before)
    return value.replace(before,after)

VERSION_HELPERS="""import ctypes
from ctypes import wintypes

def file_version(path):
    p=str(direct(Path(path)))
    ver=ctypes.WinDLL('version',use_last_error=True)
    size=ver.GetFileVersionInfoSizeW(p,None)
    require(bool(size),'Cannot read desktop executable version: '+p)
    buf=ctypes.create_string_buffer(size)
    require(bool(ver.GetFileVersionInfoW(p,0,size,buf)),'Cannot load desktop executable version: '+p)
    ptr=ctypes.c_void_p();length=wintypes.UINT()
    require(bool(ver.VerQueryValueW(buf,'\\\\',ctypes.byref(ptr),ctypes.byref(length))),'Missing desktop version info')
    class VS_FIXEDFILEINFO(ctypes.Structure):
        _fields_=[('dwSignature',wintypes.DWORD),('dwStrucVersion',wintypes.DWORD),
                  ('dwFileVersionMS',wintypes.DWORD),('dwFileVersionLS',wintypes.DWORD)]
    info=VS_FIXEDFILEINFO.from_address(ptr.value)
    return f'{info.dwFileVersionMS>>16}.{info.dwFileVersionMS&0xffff}.{info.dwFileVersionLS>>16}'

def archive_version(raw):
    tree,body=unpack(raw)
    return json.loads(read(tree,body,'package.json')).get('version')

def read_member(raw,name=MEMBER):
    tree,body=unpack(raw)
    return read(tree,body,name)

def replace_member(original,source):
    tree,body=unpack(original)
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
"""

def populate(target,fixture):
    for filename in ('asar_tools.py','sidecar_config.py','project_owner.py','orphan_recovery.py'):
        cp(OLD/filename,target/filename)
    core=(OLD/'manage.py').read_text(encoding='utf8')
    core=once(core,"VERSION='2.35.1'",f"VERSION='{HOST_VERSION}'")
    core=once(core,"MEMBER='dist/languageServer.js'","MEMBER='dist/languageServer.js'\n\n"+VERSION_HELPERS)
    core=once(core,"""def patched_archive(original, items):
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
    source=source.replace(first,fragment.encode()+b'\\n'+first)
    source=source.replace(before,before+b'\\n    const nativeCloud = (!headless && !wsl) ? await acquireNativeModelRoute() : undefined;')
    source=source.replace(after,b\"\"\"        if (nativeCloud) {
            const index = args.indexOf('--cloud_code_endpoint');
            if (index >= 0 && args[index+1] === 'https://daily-cloudcode-pa.googleapis.com') args[index+1] = nativeCloud;
        }
\"\"\"+after)
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
    return patched""",
        """def patched_archive(original, items):
    tree,body=unpack(original)
    require(json.loads(read(tree,body,'package.json')).get('version')==VERSION,
            f'Archive version differs from supported Antigravity {VERSION}')
    source=read(tree,body,MEMBER)
    require(b'acquireNativeModelRoute' not in source,'Desktop entry point is already patched')
    fragment=(HERE/'host_fragment.cjs').read_text(encoding='utf8')
    for key,value in {'__BUILD_ID__':build_id(items),'__RUNTIME_HASHES__':json.dumps(items['runtime'],sort_keys=True)}.items():
        require(fragment.count(key)==1,'Unexpected host template')
        fragment=fragment.replace(key,value)
    first=b'async function startLanguageServer(port, csrf, options = {}) {'
    before=b'    const loginShellEnv = await shellEnvReads.take();'
    after=b'        // Point the LS at the main process'
    for anchor in [first,before,after]: require(source.count(anchor)==1,'Ambiguous host entry point')
    source=source.replace(first,fragment.encode()+b'\\n'+first)
    source=source.replace(before,before+b'\\n    const nativeCloud = (!headless && !wsl) ? await acquireNativeModelRoute() : undefined;')
    source=source.replace(after,b\"\"\"        if (nativeCloud) {
            const index = args.indexOf('--cloud_code_endpoint');
            if (index >= 0 && args[index+1] === 'https://daily-cloudcode-pa.googleapis.com' && !args.some(arg => arg === '--web_bundle_path' || arg.startsWith('--web_bundle_path='))) {
                args[index+1] = nativeCloud.cloud;
                args.push('--web_bundle_path',nativeCloud.webBundle);
            }
        }
\"\"\"+after)
    return replace_member(original,source)""")
    core=once(core,"""    with lock(store):
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
            return 'Installed '+build""",
        """    with lock(store):
        journal=direct(store/'owned.json')
        if journal.exists():
            owned=json.loads(journal.read_bytes())
            require(owned.get('build')==build and owned.get('root')==str(image) and owned.get('plugin')==str(plugin),
                    'Use the matching release and installation path to change this deployment')
            orig_sha=owned['original']
            backup=direct(store/('original-'+orig_sha+'.asar'))
        else:
            if action=='rollback': return 'No owned deployment'
            require(not plugin.exists() and not side.exists() and not runtime.exists(),'Existing unowned plugin or runtime; keeping it intact')
            receipt=enrollment(config)
            raw_image=image.read_bytes()
            require(archive_version(raw_image)==VERSION,f'Unsupported desktop archive version (expected {VERSION})')
            orig_sha=sha(raw_image)
            backup=direct(store/('original-'+orig_sha+'.asar'))
            if not backup.exists(): publish_file(backup,raw_image)
            require(file_hash(backup)==orig_sha,'Backup hash mismatch')
            candidate=patched_archive(backup.read_bytes(),items)
            owned={'enrollment':receipt,'build':build,'host':VERSION,'root':str(image),'plugin':str(plugin),
                   'original':orig_sha,'candidate':sha(candidate),
                   'module_sha':sha(read_member(raw_image)),'patched_module_sha':sha(read_member(candidate))}
            publish_file(journal,json.dumps(owned,sort_keys=True).encode())
        original=backup.read_bytes()
        candidate=patched_archive(original,items)
        require(owned['candidate']==sha(candidate) and owned['original']==sha(original),'Backup or candidate differs from recorded deployment')
        require(file_hash(image) in [orig_sha,sha(candidate)],'Updated or unrecognized archive; keeping it intact')
        if action=='install':
            publish_tree('runtime',runtime,items['runtime'])
            publish_tree('plugin',plugin,items['plugin'])
            publish_tree('sidecar',side,items['sidecar'])
            enable_sidecar(config,owned['enrollment'],True)
            compare_swap(image,orig_sha,candidate)
            return 'Installed '+build""")
    core=once(core,"""        require(file_hash(direct(app/'Antigravity.exe'))==EXE and file_hash(direct(app/'resources/bin/language_server.exe'))==LANG,
                'Unknown desktop binaries; refusing to modify or restore any installation')""",
        """        require(file_version(app/'Antigravity.exe')==VERSION and direct(app/'resources/bin/language_server.exe').is_file(),
                f'Expected Antigravity {VERSION}; refusing to modify an unsupported desktop version')""")
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
    # The inherited orphan helper uses ensure_stopped through the installed manager's public name.
    cp(HERE/'managed_install.py',target/'manage.py')
    cp(HERE/'overlay_install.py',target/'overlay_install.py')
    cp(HERE/'launcher.py',target/'launcher.py')
    (target/'双击安装或管理.cmd').write_bytes((HERE/'launcher.cmd').read_text(encoding='utf8').replace('\r\n','\n').replace('\n','\r\n').encode('ascii'))
    cp(OLD/'contents.json',target/'previous-v33.json')
    run=target/'runtime'
    code=run/'restart2351'
    desktop=(HERE/'desktop.mjs').read_text(encoding='utf8')
    desktop=desktop.replace("from '../../catalog/","from '../catalog/").replace("from '../../subscription/","from '../subscription/")
    put(code/'desktop.mjs',desktop)
    # Normalize checkout-dependent text included in the content-addressed catalog.
    for folder,names in [('subscription',['generate.mjs','plan.mjs','vault.mjs']),('catalog',['catalog.mjs','serve.mjs','store.mjs','transport.mjs'])]:
        for name in names:put(run/folder/name,(SRC/folder/name).read_text(encoding='utf8'))
    old_runtime=OLD/'runtime/restart2351/router'
    subprocess.run([sys.executable,'-B',str(SRC/'subscription/prepare_codec.py'),str(old_runtime/'codex/backend.mjs'),str(code/'router/codex/backend.mjs')],check=True)
    gate_src=once((old_runtime/'lease/gate.mjs').read_text(encoding='utf8'),"export const appVersion = '2.35.1';",f"export const appVersion = '{HOST_VERSION}';")
    put(code/'router/lease/gate.mjs',gate_src)
    vendor=(old_runtime/'desktop_runtime.mjs').read_text(encoding='utf8')
    section=vendor[vendor.index('const vendorHosts'):vendor.index('function cockpitKey')]
    put(code/'vendor.mjs',"import { Readable } from 'node:stream';\n"+section)
    fragment=(OLD/'host_fragment.cjs').read_text(encoding='utf8')
    fragment=once(fragment,"app.getVersion() !== '2.35.1'",f"app.getVersion() !== '{HOST_VERSION}'")
    fragment=once(fragment,"""            const binaryMatches = await Promise.all([
                digest(process.execPath),digest(path.join(process.resourcesPath,'bin','language_server.exe'))
            ]);
            if (binaryMatches[0] !== '__EXE_HASH__' || binaryMatches[1] !== '__LANG_HASH__') return;
""","")
    fragment=once(fragment,"'restart2351','router','desktop_runtime.mjs'","'restart2351','desktop.mjs'")
    fragment=once(fragment,'            const mod = await import(','''            const activeOverlay = JSON.parse(fs.readFileSync(path.join(base,'overlays','active.json'),'utf8'));
            const expected = activeOverlay && activeOverlay.sha256;
            if (!/^[a-f0-9]{64}$/.test(expected) || (activeOverlay.host && activeOverlay.host !== app.getVersion())) return;
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
        put(code/'fixture.mjs',(HERE/'fixture.mjs').read_text(encoding='utf8'))
        additions+="""
                fixture:(await import(require('node:url').pathToFileURL(path.join(runtime,'restart2351','fixture.mjs')).href)).openFixture,"""
    fragment=once(fragment,'stateDir:base,','stateDir:base,\n                '+additions)
    put(target/'host_fragment.cjs',fragment)
    shutil.copytree(OLD/'sidecar',target/'sidecar')
    put(target/'sidecar/gate.mjs',once((target/'sidecar/gate.mjs').read_text(encoding='utf8'),"export const appVersion = '2.35.1';",f"export const appVersion = '{HOST_VERSION}';"))
    verify_ps=(target/'sidecar/verify-host.ps1').read_text(encoding='utf8')
    verify_ps=once(verify_ps,"$lsDigest = '73CE9A2405B455A93D1F13DB2AE555DA50406110217A349B6DD85C377FBDB9D1'\n","")
    verify_ps=once(verify_ps,"""if ((Get-Item -LiteralPath $appPath).VersionInfo.FileVersion -ne '2.35.1' -or
    (Get-FileHash -Algorithm SHA256 -LiteralPath $lsPath).Hash -ne $lsDigest) { throw 'Unsupported build' }""",
        f"if ((Get-Item -LiteralPath $appPath).VersionInfo.FileVersion -ne '{HOST_VERSION}') {{ throw 'Unsupported build' }}")
    put(target/'sidecar/verify-host.ps1',verify_ps)
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
    panel=target/'plugin/sidecars/settings'
    for name in ['sidecar.json','main.mjs','store.mjs','skill-store.mjs','panel.css','panel.js','index.html']:
        put(panel/name,(HERE/'panel'/name).read_text(encoding='utf8'))
    cp(HERE/'skill_sync.py',target/'skill_sync.py')
    templates=panel/'bundled-skills';languages={}
    for language in ('zh','en'):
        source=HERE/'panel/bundled-skills'/language
        paths=[source/'SKILL.md',*sorted((source/'references').glob('*.md'))]
        files={}
        for path in paths:
            if path.is_symlink() or not path.is_file():raise ValueError('Invalid bundled Skill file: '+str(path))
            rel=path.relative_to(source).as_posix()
            packaged=templates/language/rel
            put(packaged,path.read_text(encoding='utf8'))
            files[rel]=sha(packaged.read_bytes())
        languages[language]={'files':files}
    put(templates/'manifest.json',json.dumps({'schema':1,'slug':'gpt-swarm-workflow','version':VERSION,'languages':languages},sort_keys=True,indent=2))
    catalog={kind:{p.relative_to(target/kind).as_posix():sha(p.read_bytes()) for p in sorted((target/kind).rglob('*')) if p.is_file()} for kind in ['plugin','runtime','sidecar']}
    put(target/'contents.json',json.dumps(catalog,sort_keys=True,indent=2))
    put(target/'release.json',json.dumps({'version':VERSION,'flavor':'fixture' if fixture else 'subscription','host':HOST_VERSION,'build':sha(json.dumps(catalog,sort_keys=True,separators=(',',':')).encode())[:20]},indent=2))
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
