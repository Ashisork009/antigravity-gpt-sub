"""Exercise the Skill store in Node and the settings routes in an isolated Electron panel."""
from hashlib import sha256
import http.client
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest

PANEL = Path(__file__).resolve().parent / "panel"
SKILL_SLUG = "gpt-swarm-workflow"
MARKER = ".managed-by-antigravity-gpt-sub.json"
PREFERENCE = "collaboration-skill.json"


def write_templates(root, version):
    """Distinct files catch mixed-language installs and leftovers after a replacement."""
    languages = {}
    for lang in ("zh", "en"):
        files = {}
        for rel in ("SKILL.md", "references/guide.md", f"references/{lang}-only.md"):
            data = f"# {lang} {version} {rel}\n".encode()
            path = root / lang / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            files[rel] = sha256(data).hexdigest()
        languages[lang] = {"files": files}
    manifest = {"schema": 1, "slug": SKILL_SLUG, "version": version, "languages": languages}
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return manifest


def fs_snapshot(root):
    """Capture names, timestamps and bytes, but ignore access times from reads."""
    return {
        p.relative_to(root).as_posix(): (p.lstat().st_mtime_ns, p.read_bytes() if p.is_file() else None)
        for p in root.rglob("*")
    }


NODE_DRIVER = """
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {syncBuiltinESMExports} from 'node:module';
import {join} from 'node:path';
const {module, stateDir, skillsDir, templatesDir, request, failPreferenceSave} = JSON.parse(fs.readFileSync(0, 'utf8'));
if (failPreferenceSave) {
    const rename = fs.renameSync, preference = join(stateDir, 'collaboration-skill.json');
    fs.renameSync = (source, destination) => {
        if (destination === preference) throw Object.assign(Error('fixture_preference_replace_denied'), {status: 503});
        return rename(source, destination);
    };
    syncBuiltinESMExports();
}
const {skillStore, SKILL_SLUG, MARKER_FILE, SUPPORTED_LANGUAGES} = await import(module);
assert.equal(SKILL_SLUG, 'gpt-swarm-workflow');
assert.equal(MARKER_FILE, '.managed-by-antigravity-gpt-sub.json');
assert.deepEqual(SUPPORTED_LANGUAGES, ['zh', 'en']);
const store = skillStore(stateDir, {skillsDir, templatesDir});
try {
    const state = request === null ? store.snapshot() : await store.update(request);
    console.log(JSON.stringify({state}));
} catch (err) {
    if (!err.status) throw err;
    console.log(JSON.stringify({status: err.status, error: err.message}));
}
"""


class SkillStoreTests(unittest.TestCase):
    def setUp(self):
        self.node = shutil.which("node")
        if self.node is None:
            self.skipTest("Node.js is required for the SDK-free Skill store tests")
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.state_dir = self.root / "state"
        self.skills_dir = self.root / "config" / "skills"
        self.target = self.skills_dir / SKILL_SLUG
        self.templates_dir = self.root / "templates"
        self.preference = self.state_dir / PREFERENCE
        self.manifest = write_templates(self.templates_dir, "fixture-1")
        self.env = {**os.environ, "HOME": str(self.root), "USERPROFILE": str(self.root)}

    def call(self, request=None, *, fail_preference_save=False):
        args = {"module": (PANEL / "skill-store.mjs").as_uri(), "stateDir": str(self.state_dir),
                "skillsDir": str(self.skills_dir), "templatesDir": str(self.templates_dir), "request": request,
                "failPreferenceSave": fail_preference_save}
        result = subprocess.run([self.node, "--input-type=module", "-e", NODE_DRIVER],
                                input=json.dumps(args), capture_output=True, encoding="utf-8",
                                timeout=10, cwd=self.root, env=self.env)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def snapshot(self):
        return self.call()["state"]

    def update(self, enabled, language, **fields):
        return self.call({"stamp": self.snapshot()["stamp"], "enabled": enabled, "language": language, **fields})

    def assert_installed(self, language):
        files = self.manifest["languages"][language]["files"]
        self.assertEqual(json.loads((self.target / MARKER).read_bytes()), {
            "schema": 1, "owner": "antigravity-gpt-sub", "slug": SKILL_SLUG, "language": language,
            "templateVersion": self.manifest["version"], "files": files,
        })
        self.assertEqual({p.relative_to(self.target).as_posix() for p in self.target.rglob("*") if p.is_file()},
                         {MARKER, *files})
        for rel, expected_hash in files.items():
            self.assertEqual(sha256((self.target / rel).read_bytes()).hexdigest(), expected_hash)
        self.assertEqual(list(self.skills_dir.iterdir()), [self.target])
        self.assert_no_staging()

    def assert_no_staging(self):
        self.assertEqual(list(self.skills_dir.parent.glob(".gpt-sub-skill-*")), [])

    def assert_conflict_preserved(self, root=None):
        before = self.snapshot()
        self.assertEqual(before["status"], "conflict")
        root = root or self.root
        tree = fs_snapshot(root)
        for enabled in (True, False):
            self.assertEqual(self.call({"stamp": before["stamp"], "enabled": enabled, "language": "en"}),
                             {"status": 409, "error": "skill_directory_conflict"})
            self.assertEqual(self.snapshot(), before)
            self.assertEqual(fs_snapshot(root), tree)
        self.assert_no_staging()

    def test_default_is_read_only_and_off_language_is_only_a_preference(self):
        tree = fs_snapshot(self.root)
        before = self.snapshot()
        self.assertEqual(before["slug"], SKILL_SLUG)
        self.assertEqual(before["languages"], ["zh", "en"])
        self.assertEqual((before["enabled"], before["language"], before["status"]), (False, "zh", "off"))
        self.assertEqual(before["bundledVersion"], "fixture-1")
        self.assertRegex(before["stamp"], r"^[0-9a-f]{64}$")
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(fs_snapshot(self.root), tree)
        self.assertFalse(self.state_dir.exists())
        self.assertFalse(self.skills_dir.exists())

        after = self.update(False, "en")["state"]
        self.assertEqual((after["enabled"], after["language"], after["status"]), (False, "en", "off"))
        self.assertNotEqual(after["stamp"], before["stamp"])
        self.assertEqual(json.loads(self.preference.read_bytes()), {"version": 1, "enabled": False, "language": "en"})
        self.assertFalse(self.skills_dir.exists())

    def test_mount_switch_both_ways_and_disable(self):
        for language in ("zh", "en", "zh"):
            with self.subTest(language=language):
                state = self.update(True, language)["state"]
                self.assertEqual((state["enabled"], state["language"], state["status"]), (True, language, "active"))
                self.assertEqual((state["installedLanguage"], state["installedVersion"]), (language, "fixture-1"))
                self.assert_installed(language)
        tree = fs_snapshot(self.root)
        self.assertEqual(self.snapshot(), state)
        self.assertEqual(fs_snapshot(self.root), tree)
        after = self.update(False, "zh")["state"]
        self.assertEqual((after["enabled"], after["language"], after["status"]), (False, "zh", "off"))
        self.assertEqual(json.loads(self.preference.read_bytes()), {"version": 1, "enabled": False, "language": "zh"})
        self.assertFalse(self.target.exists())
        self.assert_no_staging()

    def test_failed_preference_replace_rolls_back_install_switch_and_disable(self):
        self.update(False, "zh")
        for enabled, language in ((True, "zh"), (True, "en"), (False, "zh")):
            with self.subTest(enabled=enabled, language=language):
                before = self.snapshot()
                preference = self.preference.read_bytes()
                installed = fs_snapshot(self.target) if self.target.exists() else None
                result = self.call({"stamp": before["stamp"], "enabled": enabled, "language": language},
                                   fail_preference_save=True)
                self.assertEqual(result, {"status": 503, "error": "fixture_preference_replace_denied"})
                self.assertEqual(self.snapshot(), before)
                self.assertEqual(self.preference.read_bytes(), preference)
                self.assertEqual(fs_snapshot(self.target) if self.target.exists() else None, installed)
                self.assertEqual(list(self.state_dir.glob("*.tmp")), [])
                self.assert_no_staging()
                if not before["enabled"]:
                    self.update(True, "zh")

    def test_rejects_stale_stamp_and_invalid_settings(self):
        stale = self.snapshot()["stamp"]
        self.update(False, "en")
        before = fs_snapshot(self.root)
        self.assertEqual(self.update(True, "zh", stamp=stale), {"status": 409, "error": "skill_changed"})
        for enabled, language in (("true", "en"), (True, "fr"), (None, "zh")):
            with self.subTest(enabled=enabled, language=language):
                self.assertEqual(self.update(enabled, language), {"status": 400, "error": "invalid_skill_settings"})
        self.assertEqual(fs_snapshot(self.root), before)

    def test_outdated_and_missing_can_be_synced(self):
        self.update(True, "en")
        before = fs_snapshot(self.target)
        self.manifest = write_templates(self.templates_dir, "fixture-2")
        stale = self.snapshot()
        self.assertEqual((stale["status"], stale["installedVersion"], stale["bundledVersion"]),
                         ("outdated", "fixture-1", "fixture-2"))
        self.assertEqual(fs_snapshot(self.target), before)
        self.assertEqual(self.update(True, "en", sync=True)["state"]["status"], "active")
        self.assert_installed("en")
        shutil.rmtree(self.target)
        self.assertEqual(self.snapshot()["status"], "missing")
        self.assertEqual(self.update(True, "en", sync=True)["state"]["status"], "active")
        self.assert_installed("en")

    def test_unmanaged_directory_is_preserved(self):
        self.target.mkdir(parents=True)
        (self.target / "SKILL.md").write_bytes(b"user-local skill\n")
        self.assert_conflict_preserved()

    def test_changed_managed_directory_is_preserved(self):
        self.update(True, "zh")
        clean = self.root / "clean-copy"
        shutil.copytree(self.target, clean)
        for name, mutate in [
            ("edited file", lambda: (self.target / "SKILL.md").write_bytes(b"user edit\n")),
            ("extra file", lambda: (self.target / "my-notes.md").write_bytes(b"user notes\n")),
            ("extra empty directory", lambda: (self.target / "user-folder").mkdir()),
            ("invalid marker", lambda: (self.target / MARKER).write_bytes(b"{ broken json")),
        ]:
            with self.subTest(change=name):
                mutate()
                self.assert_conflict_preserved()
                shutil.rmtree(self.target)
                shutil.copytree(clean, self.target)

    def test_linked_config_ancestor_cannot_redirect_new_directories(self):
        referent = self.root / "redirected-config"
        referent.mkdir()
        self.skills_dir = self.root / "linked" / "config" / "skills"
        link_type = "junction" if os.name == "nt" else "dir"
        result = subprocess.run([self.node, "-e", "require('node:fs').symlinkSync(...process.argv.slice(1))",
                                 str(referent), str(self.root / "linked"), link_type],
                                capture_output=True, encoding="utf-8", timeout=10, cwd=self.root, env=self.env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_conflict_preserved(root=referent)
        self.assertEqual(list(referent.iterdir()), [])
        self.assertFalse(self.preference.exists())

    def test_linked_directory_and_its_referent_are_preserved(self):
        self.target.parent.mkdir(parents=True)
        referent = self.root / "local-skill"
        referent.mkdir()
        (referent / "SKILL.md").write_bytes(b"do not touch\n")
        link_type = "junction" if os.name == "nt" else "dir"
        result = subprocess.run([self.node, "-e", "require('node:fs').symlinkSync(...process.argv.slice(1))",
                                 str(referent), str(self.target), link_type],
                                capture_output=True, encoding="utf-8", timeout=10, cwd=self.root, env=self.env)
        self.assertEqual(result.returncode, 0, result.stderr)
        target_stat = self.target.lstat()
        self.assert_conflict_preserved(root=referent)
        self.assertEqual(self.target.lstat(), target_stat)
        self.assertEqual(self.target.resolve(), referent.resolve())
        self.assertFalse(self.preference.exists())


def check():
    desktop=Path(os.environ["LOCALAPPDATA"])/"Programs/antigravity/Antigravity.exe"
    sdk=Path.home()/".gemini/antigravity/lib/node_modules/sidecar_sdk/register_loader.js"
    with tempfile.TemporaryDirectory() as tmp, socket.socket() as service:
        service.bind(("127.0.0.1",0))
        service.listen(16)
        with socket.socket() as probe:
            probe.bind(("127.0.0.1",0))
            port=probe.getsockname()[1]
        panel=Path(tmp)/"panel"
        panel.mkdir()
        for name in ("main.mjs", "store.mjs", "skill-store.mjs", "index.html", "panel.js", "panel.css"):
            shutil.copyfile(PANEL/name, panel/name)
        bundled=panel/"bundled-skills"
        write_templates(bundled, "fixture-1")
        profile=Path(tmp)/"profile"
        state=profile/".antigravity-native-model-router"
        run=state/"run"
        run.mkdir(parents=True)
        skills_dir=profile/".gemini/config/skills"
        (run/"plan-panel.json").write_text(json.dumps({"connected":True,"pending":False,"fixture":True,"revision":"synthetic",
                                                         "models":[{"id":"gpt-6.2-sol","efforts":["low","high","Ultra","custom-effort"]}]}))
        token=secrets.token_urlsafe(32)
        env={**os.environ,"USERPROFILE":str(profile),"HOME":str(profile),"ELECTRON_RUN_AS_NODE":"1",
             "LOCALAPPDATA":str(profile/"AppData/Local"),"APPDATA":str(profile/"AppData/Roaming"),
             "ANTIGRAVITY_LS_ADDRESS":"127.0.0.1:"+str(service.getsockname()[1]),"ANTIGRAVITY_CSRF_TOKEN":"fixture",
             "ANTIGRAVITY_SIDECAR_WEB_PORT":str(port),"ANTIGRAVITY_SIDECAR_UI_TOKEN":token}
        child=subprocess.Popen([str(desktop),"--import="+sdk.as_uri(),"main.mjs"],cwd=panel,env=env,
                               creationflags=subprocess.CREATE_NO_WINDOW,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        def request(method,path,data=None,authenticated=True):
            headers={"Content-Type":"application/json"}
            if authenticated:headers["X-Sidecar-Token"]=token
            client=http.client.HTTPConnection("127.0.0.1",port,timeout=2)
            try:
                client.request(method,path,json.dumps(data).encode() if data is not None else None,headers)
                res=client.getresponse()
                raw=res.read()
                return res.status,json.loads(raw) if res.headers.get("Content-Type","").startswith("application/json") else raw.decode()
            finally:client.close()
        try:
            for i in range(100):
                try:status,html=request("GET","/");break
                except OSError:
                    if child.poll() is not None:raise RuntimeError(child.stderr.read().decode(errors="replace")[:400])
                    time.sleep(.05)
            else:raise RuntimeError("SDK did not start")
            assert status==200 and "Continue with ChatGPT" in html and "/preload.js" in html
            assert request("POST","/api/state",{},False)[0]==401
            pristine = fs_snapshot(Path(tmp))
            status,before=request("POST","/api/state",{})
            assert status==200 and before["revision"]=="synthetic" and before["fixture"]
            assert before["prefs"]["models"]==["gpt-6.2-sol","gpt-6.2-astra"] and len(before["prefs"]["efforts"])==5
            assert before["models"][0]["efforts"]==["low","high","custom-effort"]
            skill = before["skill"]
            assert (skill["enabled"], skill["language"], skill["status"]) == (False, "zh", "off")
            assert skill["bundledVersion"] == "fixture-1" and not skills_dir.exists()
            for _ in range(3):
                assert request("POST", "/api/state", {}) == (200, before)
            assert fs_snapshot(Path(tmp)) == pristine

            update = {"stamp": skill["stamp"], "enabled": True, "language": "en"}
            assert request("POST", "/api/skill", update, False)[0] == 401
            assert fs_snapshot(Path(tmp)) == pristine
            status, enabled = request("POST", "/api/skill", update)
            assert status == 200 and enabled["skill"]["status"] == "active"
            assert enabled["skill"]["installedLanguage"] == "en"
            assert enabled["connected"] == before["connected"] and enabled["models"] == before["models"]
            assert (skills_dir/SKILL_SLUG/"SKILL.md").read_bytes() == (bundled/"en/SKILL.md").read_bytes()
            assert request("POST", "/api/skill", update) == (409, {"error": "skill_changed"})
            disable = {"stamp": enabled["skill"]["stamp"], "enabled": False, "language": "en"}
            assert request("POST", "/api/skill", {**disable, "language": "fr"}) == (400, {"error": "invalid_skill_settings"})
            status, disabled = request("POST", "/api/skill", disable)
            assert status == 200 and disabled["skill"]["status"] == "off" and not (skills_dir/SKILL_SLUG).exists()

            custom = skills_dir/SKILL_SLUG
            custom.mkdir()
            (custom/"SKILL.md").write_bytes(b"user-local skill\n")
            custom_tree = fs_snapshot(Path(tmp))
            status, conflicted = request("POST", "/api/state", {})
            assert status == 200 and conflicted["skill"]["status"] == "conflict"
            assert request("POST", "/api/skill", {**disable, "stamp": conflicted["skill"]["stamp"]}) == (
                409, {"error": "skill_directory_conflict"}
            )
            assert fs_snapshot(Path(tmp)) == custom_tree
            shutil.rmtree(custom)

            skill_preference = state/PREFERENCE
            saved = skill_preference.read_bytes()
            skill_preference.write_bytes(b"{ deliberately malformed fixture")
            faulty_tree = fs_snapshot(Path(tmp))
            status, faulty = request("POST", "/api/state", {})
            assert status == 200 and faulty["skill"]["error"] == "skill_unavailable"
            assert {key: value for key, value in faulty.items() if key != "skill"} == {
                key: value for key, value in before.items() if key != "skill"
            }
            assert fs_snapshot(Path(tmp)) == faulty_tree
            skill_preference.write_bytes(saved)
            assert request("POST", "/api/state", {}) == (200, disabled)

            config=state/"model-preferences.json"
            legacy={"version":1,"models":[],"efforts":["ULTRA"]}
            config.write_text(json.dumps(legacy))
            status,migrated=request("POST","/api/state",{})
            assert status==200 and migrated["prefs"]=={"version":1,"models":[],"efforts":[]}
            assert json.loads(config.read_bytes())==legacy
            rejected={**legacy,"efforts":["ultra"]}
            assert request("POST","/api/model-preferences",{"prefs":rejected,"stamp":migrated["stamp"]})[0]==409
            assert request("POST","/api/model-preferences",{"prefs":before["prefs"],"stamp":migrated["stamp"]})[0]==200
            status,before=request("POST","/api/state",{})
            clean={"version":1,"models":[],"efforts":[]}
            status,after=request("POST","/api/model-preferences",{"prefs":clean,"stamp":before["stamp"]})
            assert status==200 and after["prefs"]==clean and after["stamp"]!="default"
            assert request("POST","/api/model-preferences",{"prefs":before["prefs"],"stamp":before["stamp"]})[0]==409
            assert json.loads((state/"model-preferences.json").read_bytes())==clean
            assert request("POST","/api/model-preferences",{"prefs":before["prefs"],"stamp":after["stamp"]})[0]==200
            assert request("POST","/api/signin",{})[0]==409 and not (run/"plan-login.request").exists()
            assert request("POST","/api/refresh",{},False)[0]==401
            assert request("POST","/api/refresh",{})[0]==409 and not (run/"plan-refresh.request").exists()
            (run/"plan-panel.json").write_text(json.dumps({"connected":False,"pending":False,"refreshing":False,"fixture":False,"revision":"synthetic","models":[]}))
            assert request("POST","/api/refresh",{})==(409,{"error":"chatgpt_signin_required"})
            assert request("POST","/api/signin",{})[0]==200
            assert json.loads((run/"plan-login.request").read_bytes())["action"]=="signin"
            (run/"plan-panel.json").write_text(json.dumps({"connected":True,"pending":False,"refreshing":True,"fixture":False,"revision":"synthetic","models":[{"id":"gpt-6.2-sol","efforts":["high"]}]}))
            status,connected=request("POST","/api/state",{})
            assert status==200 and connected["refreshing"] is True
            assert request("POST","/api/refresh",{})==(200,{"queued":True})
            assert json.loads((run/"plan-refresh.request").read_bytes())["action"]=="refresh"
        finally:
            if child.poll() is None:child.terminate()
            child.wait(timeout=6)
    return {"scope":"isolated sidecar, production Electron binary, installed SDK, private fixture state",
            "executable":str(desktop),"loader":str(sdk),"auth_guard_status":401,"stale_settings_status":409,
            "profile_writes":False,"default_and_clear":True,"persistent_restore":True,"login_request":True,"refresh_request":True,
            "skill_auth_guard_status":401,"skill_stale_settings_status":409,"skill_invalid_settings_status":400,
            "skill_state_read_only":True,"skill_fault_isolated":True}


if __name__=="__main__":
    unit = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(SkillStoreTests))
    if not unit.wasSuccessful():
        sys.exit(1)
    if "--unit" not in sys.argv:
        evidence=check()
        if "--save" in sys.argv:Path(__file__).with_name("panel-runtime-proof.json").write_text(json.dumps(evidence,indent=2),encoding="utf8")
        print(json.dumps(evidence,ensure_ascii=True))

