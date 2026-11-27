"""Run migration and rollback on a temporary Windows profile using the recorded real desktop archive."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import struct
from zipfile import ZipFile

HERE=Path(__file__).resolve().parent
ROOT=HERE.parent

def locate_original(desktop, expected_version):
    store = Path.home()/'.antigravity-native-model-router'
    candidates = [desktop/'resources/app.asar']
    if store.is_dir():
        candidates.extend(sorted(store.glob('original-*.asar'), key=lambda p: p.stat().st_mtime, reverse=True))
    for candidate in candidates:
        if not candidate.is_file():
            continue
        try:
            pkg = json.loads(read_asar_member(candidate, 'package.json'))
            if pkg.get('version') != expected_version:
                continue
            if b'acquireNativeModelRoute' in read_asar_member(candidate, 'dist/languageServer.js'):
                continue
            return candidate
        except Exception:
            continue
    raise RuntimeError(f'Unpatched desktop archive for Antigravity {expected_version} not found')

def read_asar_member(image_path, member):
    data = image_path.read_bytes()
    _, blob, _, length = struct.unpack_from('<4I', data)
    node = json.loads(data[16:16+length])
    for part in member.split('/'):
        node = node['files'][part]
    start = 8 + blob + int(node['offset'])
    return data[start:start+node['size']]

def mutate_asar_member(image_path, member, new_bytes):
    """Simulate a third-party Chinese localization patch modifying a non-router member in app.asar."""
    data = image_path.read_bytes()
    _, blob, _, length = struct.unpack_from('<4I', data)
    tree = json.loads(data[16:16+length])
    body = data[8+blob:]
    node = tree
    for part in member.split('/'):
        node = node['files'][part]
    block = node['integrity']['blockSize']
    node.update(offset=str(len(body)), size=len(new_bytes))
    node['integrity'].update(
        hash=hashlib.sha256(new_bytes).hexdigest(),
        blocks=[hashlib.sha256(new_bytes[i:i+block]).hexdigest() for i in range(0, len(new_bytes), block)],
    )
    header = json.dumps(tree, ensure_ascii=False, separators=(',', ':')).encode()
    payload = (4 + len(header) + 3) // 4 * 4
    image_path.write_bytes(struct.pack('<4I', 4, payload+4, payload, len(header)) + header + bytes(payload-4-len(header)) + body + new_bytes)

def seed_previous_host_deployment(root, store, cfg, app):
    """Simulate a prior 2.35.1 deployment left behind after Antigravity auto-updated to 2.35.2."""
    prev_build = '68b3d434c9bae81fbde4'
    prev_overlay = '5570dd7fc93f14bc26954e2242cafaaa1ebf91bb7cda8c9054d5a1f0aa42b61b'
    plugin = cfg/'plugins/native-probe-router'
    sidecar = cfg/'sidecars/native-model-router-switch'
    runtime = store/'runtime'/prev_build
    comp = {}
    for kind, directory, rel, body in (
        ('plugin', plugin, 'plugin.json', b'{"name":"native-probe-router"}'),
        ('sidecar', sidecar, 'sidecar.json', b'{"command":"node"}'),
        ('runtime', runtime, 'restart2351/desktop.mjs', b'// previous 2.35.1 runtime\n'),
    ):
        f = directory/rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(body)
        comp[kind] = {rel: hashlib.sha256(body).hexdigest()}
    build = hashlib.sha256(json.dumps(comp, sort_keys=True, separators=(',', ':')).encode()).hexdigest()[:20]
    if build != prev_build:
        new_runtime = store/'runtime'/build
        runtime.rename(new_runtime)
        runtime = new_runtime
    ov_dir = store/'overlays'
    ov_dir.mkdir(parents=True, exist_ok=True)
    ov_data = b'previous 2.35.1 overlay'
    prev_overlay = hashlib.sha256(ov_data).hexdigest()
    (ov_dir/(prev_overlay+'.zip')).write_bytes(ov_data)
    (ov_dir/(prev_overlay+'.owned.json')).write_text(
        json.dumps({'sha256': prev_overlay, 'type': 'local-renderer-overlay'}), encoding='utf-8')
    settings = cfg/'config.json'
    obj = json.loads(settings.read_bytes())
    obj.setdefault('sidecars', {})['native-model-router-switch'] = {'enabled': True}
    settings.write_text(json.dumps(obj), encoding='utf-8')
    owned = {
        'build': build,
        'candidate': 'a' * 64,
        'component_hashes': comp,
        'enrollment': {'sidecars_existed': True},
        'original': '2af16ea9944ef93b1eee49c1228c8b2cf355f95e2027940cb769c6ebae02ec3b',
        'plugin': str(plugin),
        'release': {'build': build, 'flavor': 'subscription', 'host': '2.35.1', 'version': '0.5.0', 'web_bundle_sha256': prev_overlay},
        'root': str(app/'resources/app.asar'),
        'web_bundle_sha256': prev_overlay,
    }
    (store/'owned.json').write_text(json.dumps(owned, sort_keys=True, indent=2), encoding='utf-8')
    return build, prev_overlay, plugin, sidecar, runtime

def run(pkg,project,action,journal=None,expect_ok=True):
    program="""from pathlib import Path
import sys,json
root=Path(sys.argv[1]);p=root/'app';s=root/'store';c=root/'config'
import manage
if hasattr(manage,'Deployment'):
 result=manage.Deployment(p,s,c).action(sys.argv[2],*sys.argv[3:])
else:result=manage.change(sys.argv[2],p/'resources/app.asar',s,c/'plugins/native-probe-router',manage.checked_contents())
print(json.dumps(result))
"""
    args=[sys.executable,'-B','-c',program,str(project),action]
    if journal is not None:args.append(str(journal))
    profile=project/'profile';profile.mkdir(exist_ok=True)
    env={**os.environ,'USERPROFILE':str(profile),'HOME':str(profile),
         'APPDATA':str(profile/'AppData/Roaming'),'LOCALAPPDATA':str(profile/'AppData/Local')}
    r=subprocess.run(args,cwd=pkg,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    if (r.returncode==0)!=expect_ok:raise RuntimeError('Unexpected result for '+action+': '+r.stderr.decode(errors='replace')[-360:])
    return json.loads(r.stdout) if expect_ok else True

def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def extracted_launcher(image):
    data=image.read_bytes();_,blob,_,length=struct.unpack_from('<4I',data)
    node=json.loads(data[16:16+length])['files']['dist']['files']['languageServer.js']
    start=8+blob+int(node['offset'])
    return data[start:start+node['size']]

def seed_managed_skill(store, config):
    from skill_sync import MARKER_FILE, OWNER, PREFERENCE_FILE, SKILL_SLUG
    target = config/'skills'/SKILL_SLUG
    target.mkdir(parents=True)
    skill = target/'SKILL.md'
    skill.write_bytes(b'previous managed template')
    (target/MARKER_FILE).write_text(json.dumps(dict(schema=1, owner=OWNER, slug=SKILL_SLUG,
        language='en', templateVersion='0.4.9', files={'SKILL.md': digest(skill)})), encoding='utf-8')
    pref = store/PREFERENCE_FILE
    pref.write_text(json.dumps({'version': 1, 'enabled': True, 'language': 'en'}), encoding='utf-8')
    return target, pref


def tests(fix,sub,previous_fixture=None):
    results={}
    desktop=Path(os.environ['LOCALAPPDATA'])/'Programs/antigravity'
    expected_version=json.loads((sub/'release.json').read_bytes())['host']
    original_src=locate_original(desktop,expected_version)
    with tempfile.TemporaryDirectory(prefix='native-plugin-install-test-') as td:
        root=Path(td);app=root/'app';store=root/'store';cfg=root/'config';(app/'resources/bin').mkdir(parents=True)
        for rel in ['Antigravity.exe','resources/bin/language_server.exe']:
            # Copy exact binary bytes without sharing metadata with the installation.
            shutil.copyfile(desktop/rel,app/rel)
        image=app/'resources/app.asar';shutil.copyfile(original_src,image)
        orig_sha=digest(image)
        orig_preload=read_asar_member(image,'dist/preload.js')
        (cfg/'plugins').mkdir(parents=True);(cfg/'sidecars').mkdir()
        settings=cfg/'config.json';orig=b'{"plugins":{"another":{"enabled":false}},"sidecars":{}}\n'
        settings.write_bytes(orig)
        vis=cfg/'plugins/native-probe-router'
        first=run(sub,root,'install');assert first['state']=='installed'
        overlay_sha=first['web_bundle_sha256']
        overlay=store/'overlays'/(overlay_sha+'.zip')
        active_overlay=store/'overlays/active.json'
        assert digest(overlay)==overlay_sha and json.loads(active_overlay.read_bytes())['sha256']==overlay_sha
        assert read_asar_member(image,'dist/preload.js')==orig_preload
        launcher=extracted_launcher(image)
        assert launcher.count(b"args.push('--web_bundle_path',nativeCloud.webBundle)")==1
        subprocess.run(['node','--check','-'],input=launcher,check=True,stdout=subprocess.DEVNULL)
        run(sub,root,'install')
        target,pref=seed_managed_skill(store,cfg)
        clean=run(sub,root,'uninstall')
        assert clean['skill']['state']=='removed' and not target.exists()
        assert json.loads(pref.read_bytes())=={'version':1,'enabled':False,'language':'en'}
        assert digest(image)==orig_sha and not vis.exists() and settings.read_bytes()==orig and not overlay.exists() and not active_overlay.exists()
        results['new_install_repeat_uninstall']=True

        # Host auto-update migration (2.35.1 receipt over localized 2.35.2 desktop):
        prev_build,prev_overlay,_,_,prev_runtime=seed_previous_host_deployment(root,store,cfg,app)
        target,pref=seed_managed_skill(store,cfg)
        original_pref=pref.read_bytes()
        run(sub,root,'rollback',expect_ok=False)
        migrated=run(fix,root,'upgrade')
        assert migrated['state']=='migrated_host' and migrated['previous_host']=='2.35.1' and migrated['host']==expected_version
        assert migrated['from']==prev_build and migrated['skill']['state']=='synced'
        assert (store/'backups'/migrated['archived_receipt']).is_file()
        assert not prev_runtime.exists() and not (store/'overlays'/(prev_overlay+'.zip')).exists()
        assert digest(overlay)==overlay_sha and read_asar_member(image,'dist/preload.js')==orig_preload
        from skill_sync import MARKER_FILE
        templates=fix/'plugin/sidecars/settings/bundled-skills'
        manifest=json.loads((templates/'manifest.json').read_bytes())
        marker=json.loads((target/MARKER_FILE).read_bytes())
        assert marker['language']=='en' and marker['templateVersion']==manifest['version']
        assert marker['files']==manifest['languages']['en']['files']
        assert all(digest(target/name)==sha for name,sha in marker['files'].items())
        assert pref.read_bytes()==original_pref
        results['host_update_seamless_migration_and_skill_sync']=True

        # Simulate a post-install localization patch modifying dist/preload.js; verify upgrade & rollback & uninstall keep it!
        localized_preload=orig_preload+b'\n// simulated zh-CN localization patch\n'
        mutate_asar_member(image,'dist/preload.js',localized_preload)
        fixsha=digest(image)
        upgraded=run(sub,root,'upgrade')
        assert upgraded['state']=='upgraded' and upgraded['skill']['state']=='synced'
        assert read_asar_member(image,'dist/preload.js')==localized_preload
        rc=run(sub,root,'rollback');assert rc['build']==migrated['build'] and digest(image)==fixsha
        assert rc['skill']['state']=='synced' and read_asar_member(image,'dist/preload.js')==localized_preload
        results['fixture_to_production_upgrade_and_rollback']=True
        results['post_install_localization_survives_upgrade_and_rollback']=True
        own=vis/'plugin.json'
        missing=vis/'sidecars/settings/sidecar.json';missing.unlink()
        own.write_bytes(b'')
        saved=run(fix,root,'repair')
        assert saved['state']=='repaired' and (Path(saved['backup'])/'plugin/plugin.json').read_bytes()==b''
        assert own.read_bytes()==(fix/'plugin/plugin.json').read_bytes() and missing.is_file()
        edited=own.read_bytes();own.write_text('concurrently changed')
        run(fix,root,'undo-repair',saved['backup'],expect_ok=False)
        assert own.read_text()=='concurrently changed' and missing.is_file()
        own.write_bytes(edited);run(fix,root,'undo-repair',saved['backup'])
        assert own.read_bytes()==b'' and not missing.exists()
        run(fix,root,'repair')
        results['repair_rollback_and_foreign_edit_guard']=True
        results['missing_and_damaged_manifests_repaired_with_backup']=True
        authorized=own.read_bytes();own.write_text('{"name":"user-edit"}')
        run(fix,root,'repair',expect_ok=False);assert own.read_text()=='{"name":"user-edit"}'
        own.write_bytes(authorized)
        config=json.loads(settings.read_bytes());config['plugins']['concurrent-new']={'enabled':True};settings.write_text(json.dumps(config))
        before=image.read_bytes();image.write_bytes(b'new desktop')
        run(fix,root,'rollback',expect_ok=False);assert image.read_bytes()==b'new desktop';image.write_bytes(before)
        results['new_vendor_archive_and_local_edits_preserved']=True
        (target/'SKILL.md').write_bytes(b'user edited the managed Skill')
        original_pref=pref.read_bytes()
        uninstall=run(fix,root,'uninstall')
        assert uninstall['state']=='uninstalled' and uninstall['skill']['state']=='preserved_conflict' and uninstall['skill']['warning']
        assert (target/'SKILL.md').read_bytes()==b'user edited the managed Skill' and pref.read_bytes()==original_pref
        assert not vis.exists() and read_asar_member(image,'dist/preload.js')==localized_preload
        assert b'acquireNativeModelRoute' not in extracted_launcher(image)
        assert json.loads(settings.read_bytes())['plugins']['concurrent-new']['enabled']
        results['uninstall_preserves_concurrent_settings']=True
        results['deployment_uninstall_preserves_customized_skill']=True
        results['post_install_localization_survives_uninstall']=True

        # Clean uninstall of leftover 2.35.1 receipt over localized 2.35.2 desktop without altering app.asar:
        shutil.rmtree(target)
        shutil.copyfile(original_src,image)
        prev_build2,prev_overlay2,_,_,prev_runtime2=seed_previous_host_deployment(root,store,cfg,app)
        target2,pref2=seed_managed_skill(store,cfg)
        uninst_host=run(sub,root,'uninstall')
        assert uninst_host['state']=='uninstalled' and uninst_host.get('host_updated') is True
        assert digest(image)==orig_sha and not vis.exists() and not prev_runtime2.exists() and not target2.exists()
        assert not (store/'overlays'/(prev_overlay2+'.zip')).exists()
        results['host_update_clean_uninstall']=True
    return results

def skill_tests():
    """Exercise lifecycle reconciliation without using a desktop installation."""
    from skill_sync import MARKER_FILE, PREFERENCE_FILE, SKILL_SLUG, reconcile_skill

    def write_json(path, value):
        path.write_text(json.dumps(value), encoding='utf-8')

    def files(root, version, language, ref):
        (root/'references').mkdir(parents=True)
        (root/'SKILL.md').write_text(f'{language} {version}', encoding='utf-8')
        (root/'references'/ref).write_text(f'{language} reference', encoding='utf-8')
        return {name: digest(root/name) for name in ('SKILL.md', 'references/'+ref)}

    def fixture(root, enabled=True):
        store, config = root/'state', root/'config'
        store.mkdir(parents=True)
        pref = store/PREFERENCE_FILE
        write_json(pref, {'version': 1, 'enabled': enabled, 'language': 'en'})
        target = config/'skills'/SKILL_SLUG
        hashes = files(target, '0.4.9', 'en', 'old.md')
        write_json(target/MARKER_FILE, dict(schema=1, owner='antigravity-gpt-sub', slug=SKILL_SLUG,
                                          language='en', templateVersion='0.4.9', files=hashes))
        return store, config, pref, target

    def bundle(root, version):
        languages = {lang: {'files': files(root/lang, version, lang, 'new.md')} for lang in ('zh', 'en')}
        write_json(root/'manifest.json', dict(schema=1, slug=SKILL_SLUG, version=version, languages=languages))
        return root

    def clean_temporaries(config, store):
        assert not list(config.glob('.gpt-sub-skill-*'))
        assert not list((config/'skills').glob('.gpt-sub-skill-*'))
        assert not list(store.glob('*.tmp'))

    results = {}
    with tempfile.TemporaryDirectory(prefix='managed-skill-lifecycle-') as td:
        root = Path(td)
        current = bundle(root/'current', '0.5.0')
        previous = bundle(root/'previous', '0.4.8')

        store, config, pref, target = fixture(root/'upgrade')
        original_pref = pref.read_bytes()
        assert reconcile_skill('upgrade', store, config, current)['state'] == 'synced'
        assert (target/'SKILL.md').read_text(encoding='utf-8') == 'en 0.5.0'
        assert not (target/'references/old.md').exists() and (target/'references/new.md').is_file()
        marker = json.loads((target/MARKER_FILE).read_bytes())
        assert marker['templateVersion'] == '0.5.0' and marker['language'] == 'en'
        assert all(digest(target/name) == sha for name, sha in marker['files'].items())
        assert pref.read_bytes() == original_pref
        clean_temporaries(config, store)
        results['skill_upgrade_refreshes_managed_selected_language'] = True

        assert reconcile_skill('rollback', store, config, previous)['state'] == 'synced'
        assert (target/'SKILL.md').read_text(encoding='utf-8') == 'en 0.4.8'
        assert pref.read_bytes() == original_pref
        clean_temporaries(config, store)
        results['skill_rollback_refreshes_supported_predecessor'] = True

        for enabled, expected in ((False, 'disabled'), (True, 'absent')):
            store, config, pref, target = fixture(root/('absent-'+str(enabled)), enabled)
            shutil.rmtree(config)
            original_pref = pref.read_bytes()
            assert reconcile_skill('upgrade', store, config, current)['state'] == expected
            assert reconcile_skill('rollback', store, config, previous)['state'] == expected
            assert not config.exists() and pref.read_bytes() == original_pref
        store, config, pref, target = fixture(root/'disabled-present', enabled=False)
        assert reconcile_skill('upgrade', store, config, current)['state'] == 'disabled'
        assert (target/'SKILL.md').read_text(encoding='utf-8') == 'en 0.4.9'
        results['skill_upgrade_does_not_revive_disabled_or_missing_install'] = True

        for action in ('uninstall', 'rollback'):
            store, config, pref, target = fixture(root/action)
            templates = None if action == 'uninstall' else root/'pre-skill-version'
            assert reconcile_skill(action, store, config, templates)['state'] == 'removed'
            assert not target.exists()
            assert json.loads(pref.read_bytes()) == {'version': 1, 'enabled': False, 'language': 'en'}
            snapshot = pref.read_bytes()
            assert reconcile_skill(action, store, config, templates)['state'] == 'absent'
            assert pref.read_bytes() == snapshot
            clean_temporaries(config, store)
            results[f'skill_{action}_removes_managed_tree_and_disables_pref'] = True

        for action in ('uninstall', 'rollback'):
            store, config, pref, target = fixture(root/f'{action}-malformed-pref')
            pref.write_bytes(b'invalid JSON')
            outcome = reconcile_skill(action, store, config)
            assert outcome['state'] == 'removed' and outcome['warning']
            assert not target.exists() and pref.read_bytes() == b'invalid JSON'
            assert reconcile_skill(action, store, config) == {'state': 'absent'}
            clean_temporaries(config, store)
        results['skill_removal_preserves_invalid_preferences_without_leaving_skill_active'] = True

        for name in ('SKILL.md', MARKER_FILE, 'extra.md', 'references/empty'):
            store, config, pref, target = fixture(root/'conflict'/name.replace('/', '-'))
            path = target/name
            if name.endswith('/empty'):
                path.mkdir()
            else:
                path.write_bytes(b'user-owned content')
            original_pref = pref.read_bytes()
            for action, templates in (('uninstall', None), ('rollback', root/'pre-skill-version'), ('upgrade', current)):
                outcome = reconcile_skill(action, store, config, templates)
                assert outcome['state'] == 'preserved_conflict' and outcome['warning']
                assert path.is_dir() if name.endswith('/empty') else path.read_bytes() == b'user-owned content'
                assert pref.read_bytes() == original_pref
                clean_temporaries(config, store)
        results['skill_conflicts_preserve_user_edits_and_preferences'] = True

        store, config, pref, target = fixture(root/'unmanaged')
        (target/MARKER_FILE).unlink()
        assert reconcile_skill('uninstall', store, config)['state'] == 'preserved_conflict'
        assert (target/'SKILL.md').read_text(encoding='utf-8') == 'en 0.4.9'
        results['skill_unmanaged_directory_is_never_removed'] = True

        store, config, pref, target = fixture(root/'linked')
        other = root/'external'
        target.rename(other)
        if os.name == 'nt':
            subprocess.run(['cmd', '/d', '/c', 'mklink', '/j', str(target), str(other)],
                           check=True, stdout=subprocess.DEVNULL)
        else:
            target.symlink_to(other, target_is_directory=True)
        assert reconcile_skill('uninstall', store, config)['state'] == 'preserved_conflict'
        assert (target/'SKILL.md').read_text(encoding='utf-8') == 'en 0.4.9'
        assert json.loads(pref.read_bytes())['enabled'] is True
        results['skill_linked_directory_is_preserved'] = True

        store, config, pref, target = fixture(root/'bad-template')
        (current/'en/SKILL.md').write_bytes(b'changed template')
        original_pref = pref.read_bytes()
        try:
            reconcile_skill('upgrade', store, config, current)
        except ValueError as exc:
            assert 'hash mismatch' in str(exc)
        else:
            raise AssertionError('Unexpected success for a modified template')
        assert (target/'SKILL.md').read_text(encoding='utf-8') == 'en 0.4.9'
        assert pref.read_bytes() == original_pref
        clean_temporaries(config, store)
        results['skill_bad_template_is_not_published'] = True
    return results


if __name__=='__main__':
    cli=argparse.ArgumentParser(description=__doc__);cli.add_argument('fixture',type=Path,nargs='?');cli.add_argument('subscription',type=Path,nargs='?')
    cli.add_argument('--previous-fixture',type=Path)
    cli.add_argument('--skill-only',action='store_true',help='Test Skill transitions using only temporary fixtures')
    args=cli.parse_args()
    if args.skill_only:
        print(json.dumps(skill_tests(),indent=2))
    else:
        if not args.fixture or not args.subscription:
            cli.error('fixture and subscription are required unless --skill-only is used')
        print(json.dumps(tests(args.fixture.resolve(),args.subscription.resolve(),args.previous_fixture.resolve() if args.previous_fixture else None),indent=2))
