"""Install, upgrade, repair or roll back one version-checked native model extension."""
import argparse
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import shutil
import time
from uuid import uuid4
import core_manage as core
from core_manage import ensure_stopped
from sidecar_config import SIDECAR_ID,enable_sidecar,members,settings,SPACES
from project_owner import native_enrollment
from overlay_install import OverlayStore

HERE=Path(__file__).resolve().parent
V33='85408176d923b4f3e9b7'
V33_IMAGE='71f00a09e25f86d32fc7136017a29537a70cbbb2515922f151fab6cdfdf8824c'
read=lambda p:json.loads(p.read_bytes())
def now():return datetime.now(timezone.utc).isoformat()
def save(p,v):
    core.direct(p)
    tmp=p.with_name(p.name+'.'+uuid4().hex+'.tmp')
    try:
        with tmp.open('xb') as f:
            f.write(json.dumps(v,sort_keys=True,ensure_ascii=False,indent=2).encode())
            f.flush();os.fsync(f.fileno())
        os.replace(tmp,p)
    finally:tmp.unlink(missing_ok=True)

class Deployment:
    def __init__(self,app,store,config):
        self.app=core.direct(app);self.store=core.direct(store);self.config=core.direct(config/'config.json')
        self.image=core.direct(app/'resources/app.asar');self.plugin=core.direct(config/'plugins/native-probe-router')
        self.side=core.direct(config/'sidecars'/SIDECAR_ID);self.receipt=core.direct(store/'owned.json')
        self.backup=core.direct(store/('original-'+core.BASE+'.asar'))
        self.transition=core.direct(store/'pending-transition.json')
        self.items=core.checked_contents();self.build=core.build_id(self.items)
        self.release=read(HERE/'release.json')
        core.require(self.release['build']==self.build,'Release manifest disagrees with packaged code')
        self.bundles=OverlayStore(self.store,self.app/'resources/bin/language_server.exe',self.release)
    def binary(self):
        core.require(core.file_hash(core.direct(self.app/'Antigravity.exe'))==core.EXE and core.file_hash(core.direct(self.app/'resources/bin/language_server.exe'))==core.LANG,'Unknown desktop or language service')
    def targets(self,build):
        core.require(isinstance(build,str) and len(build)==20 and all(x in '0123456789abcdef' for x in build),'Invalid runtime build ID')
        return {'plugin':self.plugin,'sidecar':self.side,'runtime':core.direct(self.store/'runtime'/build)}
    def identity(self,owned):
        core.require(owned.get('root')==str(self.image) and owned.get('plugin')==str(self.plugin) and owned.get('original')==core.BASE,'Receipt points at a different installation')
        core.require(core.file_hash(self.backup)==core.BASE,'Original rollback image differs')
        if owned.get('build')==V33:
            core.require(owned.get('candidate')==V33_IMAGE,'Unrecognized predecessor image')
            items=read(HERE/'previous-v33.json')
        elif owned.get('build')==self.build:
            items=self.items
            core.require(core.sha(core.patched_archive(self.backup.read_bytes(),items))==owned.get('candidate'),'Current release does not match receipt')
        else:items=owned.get('component_hashes',{})
        core.require(core.build_id(items)==owned.get('build') and set(items)=={'runtime','plugin','sidecar'},'Unknown recorded release')
        return items
    @staticmethod
    def subset(root,wanted):
        present=core.manifest_files(root)
        core.require(all(wanted.get(k)==v for k,v in present.items()),'Unrecognized content in '+str(root))
        return present
    def stamp(self,owned,predecessor=None):
        return dict(owned,component_hashes=self.items,release=self.release,predecessor=predecessor,web_bundle_sha256=self.bundles.digest)
    def make_snapshot(self,owned):
        items=self.identity(owned)
        core.require(core.file_hash(self.image)==owned['candidate'],'Installed archive was updated externally')
        root=core.direct(self.store/'backups'/uuid4().hex);root.mkdir(parents=True)
        actual=read(self.config).get('sidecars',{}).get(SIDECAR_ID)
        enrolled=native_enrollment(self.config,SIDECAR_ID,actual)
        core.require(enrolled or actual is None,'User changed the managed sidecar enrollment')
        manifest={}
        for kind,path in self.targets(owned['build']).items():
            hashes=self.subset(path,items[kind])
            if not path.exists():continue
            shutil.copytree(path,root/kind)
            core.require(core.manifest_files(root/kind)==hashes,'Failed to verify saved '+kind)
            manifest[kind]=hashes
        shutil.copyfile(self.image,root/'app.asar')
        core.require(core.file_hash(root/'app.asar')==owned['candidate'],'Snapshot archive mismatch')
        bundle=self.bundles.snapshot(owned.get('web_bundle_sha256'),root)
        save(root/'snapshot.json',{'time':now(),'receipt':owned,'present':manifest,'enrolled':enrolled,
            'original_enrollment':actual,'bundle':bundle,'config_sha256':core.file_hash(self.config)})
        return root.name
    def snapshot(self,ref):
        core.require(isinstance(ref,str) and len(ref)==32 and all(ch in '0123456789abcdef' for ch in ref),'Unrecognized rollback reference')
        root=core.direct(self.store/'backups'/ref)
        snap=read(core.direct(root/'snapshot.json'));old=snap['receipt'];spec=self.identity(old)
        core.require(core.file_hash(core.direct(root/'app.asar'))==old['candidate'],'Rollback image changed')
        for kind,hashes in snap['present'].items():
            core.require(kind in spec and self.subset(root/kind,spec[kind])==hashes,'Rollback files changed')
        return root,snap
    def retire(self,path,kind):
        core.direct(path)
        if not path.exists():return
        saved=core.direct(self.store/'removed'/uuid4().hex);saved.parent.mkdir(exist_ok=True)
        temp=core.direct(path.with_name('.'+path.name+'-retired-'+uuid4().hex))
        # A Windows cmd wrapper can keep a panel's initial CWD locked while the SDK
        # finishes shutting down after its verified language service has exited.
        end=time.monotonic()+12
        while True:
            try:path.rename(temp);break
            except PermissionError:
                if time.monotonic()<end:
                    time.sleep(.25);continue
                if kind!='sidecar':raise
                from orphan_recovery import retire_sidecar
                retire_sidecar(path,temp);break
        shutil.move(str(temp),str(saved))
    def restore(self,ref,from_spec,from_build,from_image,from_bundle):
        root,snap=self.snapshot(ref);before=snap['receipt'];prior=self.identity(before)
        core.require(core.file_hash(self.image) in (from_image,before['candidate']),'Refusing to overwrite an updated desktop')
        targets=self.targets(from_build);originals=self.targets(before['build'])
        for kind,path in targets.items():
            if path.exists():
                # A stopped migration may have completed some, but not all, directory swaps.
                files=core.manifest_files(path)
                core.require(all(digest in (prior[kind].get(name),from_spec[kind].get(name)) for name,digest in files.items()),'Foreign edits during rollback: '+kind)
        for kind,path in targets.items():
            if path.exists():self.retire(path,kind)
        for kind,path in originals.items():
            if path.exists():
                self.subset(path,prior[kind]);self.retire(path,kind)
            if kind in snap['present']:
                path.parent.mkdir(parents=True,exist_ok=True)
                shutil.copytree(root/kind,path)
                core.require(core.manifest_files(path)==snap['present'][kind],'Rollback tree verification failed')
        enable_sidecar(self.config,before['enrollment'],snap['enrolled'])
        recorded=snap.get('original_enrollment')
        if recorded and set(recorded)!={'enabled'}:
            core.require(native_enrollment(self.config,SIDECAR_ID,recorded),'Original sidecar project is no longer verifiable')
            def restore_enrollment(raw):
                bom,text,obj=settings(raw)
                actual=obj['sidecars'][SIDECAR_ID]
                if actual==recorded:return raw
                core.require(actual=={'enabled':True},'Retaining a newly assigned sidecar project')
                root=members(text,SPACES.match(text).end())
                _,start,end,_,_=members(text,root['sidecars'][1])[SIDECAR_ID]
                return bom+(text[:start]+json.dumps(recorded,separators=(',',':'))+text[end:]).encode()
            core.edit(self.config,restore_enrollment)
        self.bundles.restore(snap.get('bundle'),root)
        core.compare_swap(self.image,from_image,(root/'app.asar').read_bytes())
        self.bundles.retire(from_bundle,before.get('web_bundle_sha256'))
        save(self.receipt,before)
    def pending(self):
        if not self.transition.exists():return
        tx=read(self.transition)
        core.require(tx['build']==self.build,'Complete the pending operation with its original release')
        if 'other_snapshot' in tx:
            _,other=self.snapshot(tx['other_snapshot'])
            source=other['receipt']
            self.restore(tx['prior'],self.identity(source),source['build'],source['candidate'],source.get('web_bundle_sha256'))
        else:
            self.restore(tx['prior'],self.items,self.build,tx['candidate'],self.bundles.digest)
        self.transition.unlink()
    def upgrade(self):
        owned=read(self.receipt)
        prior=self.make_snapshot(owned)
        original=self.backup.read_bytes();data=core.patched_archive(original,self.items)
        next_sha=core.sha(data)
        next_owned=self.stamp(dict(owned,build=self.build,candidate=next_sha),prior)
        save(self.transition,{'build':self.build,'candidate':next_sha,'prior':prior,'time':now()})
        try:
            self.bundles.ensure()
            for kind,path in self.targets(owned['build']).items():self.retire(path,kind)
            for kind,path in self.targets(self.build).items():core.publish_tree(kind,path,self.items[kind])
            enable_sidecar(self.config,owned['enrollment'],True)
            core.compare_swap(self.image,owned['candidate'],data)
            self.bundles.retire(owned.get('web_bundle_sha256'),self.bundles.digest)
            save(self.receipt,next_owned)
            self.transition.unlink()
        except Exception:
            self.pending()
            raise
        return {'state':'upgraded','from':owned['build'],'build':self.build,'rollback_snapshot':prior,'archive_sha256':next_sha}
    def repair(self,owned,hot=True):
        self.identity(owned)
        core.require(owned['build']==self.build and core.file_hash(self.image)==owned['candidate'],'Repair requires the exact deployed package and image')
        if hot:self.bundles.verify()
        else:self.bundles.ensure()
        changed={}
        for kind,path in self.targets(self.build).items():
            wanted=self.items[kind];present=core.manifest_files(path)
            bad={k for k in wanted if k in present and present[k]!=wanted[k]}
            unknown=set(present)-set(wanted)
            # Never replace syntactically valid local edits. Empty packaged files and
            # malformed package JSON are recoverable with a byte-for-byte backup.
            for rel in sorted(bad):
                f=core.direct(path/rel);broken=f.stat().st_size==0
                packaged=HERE/kind/rel
                if not broken and f.suffix in ('.mjs','.js','.html','.css'):
                    length=f.stat().st_size
                    broken=length<packaged.stat().st_size and packaged.read_bytes().startswith(f.read_bytes())
                if not broken and f.suffix=='.json':
                    try:json.loads(f.read_bytes())
                    except (ValueError,UnicodeError):broken=True
                core.require(broken,'Keeping a locally edited file: '+str(f))
            missing=set(wanted)-set(present)
            if hot and kind!='plugin' and (bad or missing):raise ValueError('Close Antigravity and use install to repair executable components')
            if bad or missing:changed[kind]=(path,bad,missing,unknown)
        registration=read(self.config).get('sidecars',{})
        missing_enrollment=SIDECAR_ID not in registration
        core.require(missing_enrollment or native_enrollment(self.config,SIDECAR_ID,registration[SIDECAR_ID]),'Keeping a locally modified sidecar enrollment')
        if not changed and not missing_enrollment:return {'state':'verified','build':self.build}
        journal=core.direct(self.store/'repairs'/uuid4().hex);journal.mkdir(parents=True)
        report={'build':self.build,'time':now(),'archive_sha256':owned['candidate'],'components':{},
                'sidecar_enrollment_previously_missing':missing_enrollment,'config_sha256':core.file_hash(self.config)}
        for kind,(path,bad,missing,unknown) in changed.items():
            had=path.exists()
            for name in bad:
                f=core.direct(path/name);saved=journal/kind/name;saved.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(f,saved)
                core.require(core.file_hash(f)==core.file_hash(saved),'Repair backup mismatch')
            report['components'][kind]={'broken':sorted(bad),'absent':sorted(missing),'prior_directory':had,
                'original_hashes':{name:core.file_hash(journal/kind/name) for name in bad},'preserved_additions':sorted(unknown)}
        save(journal/'journal.json',report)
        for kind,(path,bad,missing,unknown) in changed.items():
            if not path.exists():
                core.publish_tree(kind,path,self.items[kind]);continue
            for rel in sorted(bad|missing):
                f=core.direct(path/rel);f.parent.mkdir(parents=True,exist_ok=True)
                data=(HERE/kind/rel).read_bytes()
                if rel in bad:core.compare_swap(f,core.file_hash(journal/kind/rel),data)
                else:core.publish_file(f,data)
            core.require(all(core.file_hash(core.direct(path/k))==v for k,v in self.items[kind].items()),'Repair verification failed')
        if missing_enrollment:enable_sidecar(self.config,owned['enrollment'],True)
        return {'state':'repaired','build':self.build,'backup':str(journal)}
    def undo_repair(self,owned,journal):
        self.identity(owned)
        core.require(journal is not None,'Supply the repair backup directory using --journal')
        root=core.direct(Path(journal).absolute())
        core.require(root.parent==self.store/'repairs' and len(root.name)==32 and all(ch in '0123456789abcdef' for ch in root.name),'Unknown repair backup location')
        report=read(core.direct(root/'journal.json'))
        core.require(owned['build']==self.build==report.get('build') and core.file_hash(self.image)==owned['candidate']==report.get('archive_sha256'),'Repair backup belongs to another deployment')
        changes=report['components']
        targets=self.targets(self.build)
        for kind,entry in changes.items():
            core.require(kind in targets,'Unexpected repair component')
            absent=set(entry['absent']);broken=set(entry['broken'])
            hashes=entry.get('original_hashes',{})
            core.require(set(hashes)==broken and not (absent & broken) and (absent|broken)<=self.items[kind].keys(),'Invalid repair journal')
            path=targets[kind]
            for name in broken:
                core.require(core.file_hash(core.direct(root/kind/name))==hashes[name],'Repair backup has changed')
            for name in absent|broken:
                current=core.direct(path/name)
                if current.exists():
                    core.require(core.file_hash(current) in (hashes.get(name),self.items[kind][name]),'Keeping a changed file: '+str(current))
                elif name in broken:
                    raise ValueError('Previously damaged file was removed independently: '+name)
        if report['sidecar_enrollment_previously_missing']:
            actual=read(self.config).get('sidecars',{}).get(SIDECAR_ID)
            core.require(actual is None or native_enrollment(self.config,SIDECAR_ID,actual),'Keeping edited sidecar enrollment')
            if actual is not None:enable_sidecar(self.config,owned['enrollment'],False)
        for kind,entry in changes.items():
            path=targets[kind]
            for name in entry['broken']:
                core.compare_swap(core.direct(path/name),self.items[kind][name],(root/kind/name).read_bytes())
            for name in entry['absent']:
                current=core.direct(path/name)
                if current.exists():
                    core.require(core.file_hash(current)==self.items[kind][name],'File changed during undo')
                    current.unlink()
            if not entry['prior_directory'] and path.exists():
                # Empty directories created by the repair can be removed. Preserve parallel additions.
                dirs={parent for name in entry['absent'] for parent in (path/name).parents
                      if path in parent.parents and core.direct(parent).is_dir()}
                for empty in sorted(dirs,key=lambda p:len(p.parts),reverse=True)+[path]:
                    if not any(empty.iterdir()):empty.rmdir()
        return {'state':'restored_before_repair','build':self.build,'backup':str(root)}
    def action(self,action,journal=None):
        if action=='preview':return {'build':self.build,'candidate':core.sha(core.patched_archive((self.backup if self.backup.exists() else self.image).read_bytes(),self.items))}
        if action!='repair':ensure_stopped(self.app)
        self.binary()
        if not self.receipt.exists() and not self.transition.exists():
            if action in ('rollback','uninstall'):return {'state':'already absent'}
            core.require(action in ('install','upgrade'),'No active deployment to repair')
            core.require(core.file_hash(self.image)==core.BASE,'Unsupported desktop archive')
            with core.lock(self.store):self.bundles.ensure()
            core.change('install',self.image,self.store,self.plugin,self.items)
            with core.lock(self.store):save(self.receipt,self.stamp(read(self.receipt)))
            return {'state':'installed','build':self.build}
        if self.receipt.exists() and not self.transition.exists() and action in ('install','upgrade'):
            partial=read(self.receipt)
            if partial.get('build')==self.build and 'release' not in partial:
                # The v3.3 core writes its receipt before publishing directories and the image.
                # Re-enter that operation under its own lock to finish an interrupted first install.
                self.identity(partial)
                with core.lock(self.store):self.bundles.ensure()
                core.change('install',self.image,self.store,self.plugin,self.items)
                with core.lock(self.store):save(self.receipt,self.stamp(read(self.receipt)))
                return {'state':'installed','build':self.build}
        with core.lock(self.store):
            if self.transition.exists():
                core.require(action!='repair','Stop the desktop to recover the pending deployment')
                self.pending()
            owned=read(self.receipt);self.identity(owned)
            if action=='repair':return self.repair(owned)
            if action=='undo-repair':return self.undo_repair(owned,journal)
            if action in ('install','upgrade'):
                if owned['build']==self.build:return self.repair(owned,False)
                return self.upgrade()
            core.require(owned['build']==self.build,'Use the release that owns the current deployment')
            if action=='rollback' and owned.get('predecessor'):
                before=self.make_snapshot(owned)
                save(self.transition,{'build':self.build,'prior':before,'other_snapshot':owned['predecessor'],'time':now()})
                try:
                    self.restore(owned['predecessor'],self.items,self.build,owned['candidate'],self.bundles.digest)
                    self.transition.unlink()
                except Exception:
                    self.pending()
                    raise
                return {'state':'restored_previous','build':read(self.receipt)['build']}
            # A native UI deletion can leave any subset of packaged files absent.
            # Preflight the complete installed tree before the first change.
            before=self.make_snapshot(owned)
            self.transition_record(before,owned)
            try:
                for kind,path in self.targets(self.build).items():
                    self.retire(path,kind)
                enable_sidecar(self.config,owned['enrollment'],False)
                core.compare_swap(self.image,owned['candidate'],self.backup.read_bytes())
                self.bundles.retire(self.bundles.digest)
                self.receipt.unlink()
                self.transition.unlink()
            except Exception:
                self.restore(before,self.items,self.build,core.BASE,self.bundles.digest)
                self.transition.unlink(missing_ok=True)
                raise
            return {'state':'uninstalled','archive_sha256':core.BASE,'backup_snapshot':before}
    def transition_record(self,prior,owned):
        save(self.transition,{'build':self.build,'prior':prior,'candidate':core.BASE,'time':now()})

def main():
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument('action',choices=['install','repair','undo-repair','preview','upgrade','uninstall','rollback'])
    cli.add_argument('--journal',type=Path,help='Backup directory printed by repair, for undo-repair')
    args=cli.parse_args()
    app=Path(os.environ['LOCALAPPDATA'])/'Programs/antigravity'
    dep=Deployment(app,Path.home()/'.antigravity-native-model-router',Path.home()/'.gemini/config')
    print(json.dumps(dep.action(args.action,args.journal),ensure_ascii=True))

if __name__=='__main__':main()
