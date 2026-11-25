"""Exercise a fixture panel through the installed desktop's own Electron Node runtime and SDK."""
import http.client
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import tempfile
import time
import sys

def check():
    desktop=Path(os.environ["LOCALAPPDATA"])/"Programs/antigravity/Antigravity.exe"
    sdk=Path.home()/".gemini/antigravity/lib/node_modules/sidecar_sdk/register_loader.js"
    panel=Path(__file__).resolve().parent/"panel"
    with tempfile.TemporaryDirectory() as tmp, socket.socket() as service:
        service.bind(("127.0.0.1",0))
        service.listen(16)
        with socket.socket() as probe:
            probe.bind(("127.0.0.1",0))
            port=probe.getsockname()[1]
        profile=Path(tmp)
        state=profile/".antigravity-native-model-router"
        run=state/"run"
        run.mkdir(parents=True)
        (run/"plan-panel.json").write_text(json.dumps({"connected":True,"pending":False,"fixture":True,"revision":"synthetic",
                                                         "models":[{"id":"gpt-6.2-sol","efforts":["low","high","Ultra","custom-effort"]}]}))
        token=secrets.token_urlsafe(32)
        env={**os.environ,"USERPROFILE":str(profile),"HOME":str(profile),"ELECTRON_RUN_AS_NODE":"1",
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
            status,before=request("POST","/api/state",{})
            assert status==200 and before["revision"]=="synthetic" and before["fixture"]
            assert before["prefs"]["models"]==["gpt-6.2-sol","gpt-6.2-astra"] and len(before["prefs"]["efforts"])==5
            assert before["models"][0]["efforts"]==["low","high","custom-effort"]
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
            (run/"plan-panel.json").write_text(json.dumps({"connected":False,"pending":False,"fixture":False,"revision":"synthetic","models":[]}))
            assert request("POST","/api/signin",{})[0]==200
            assert json.loads((run/"plan-login.request").read_bytes())["action"]=="signin"
        finally:
            if child.poll() is None:child.terminate()
            child.wait(timeout=6)
    return {"scope":"isolated sidecar, production Electron binary, installed SDK, private fixture state",
            "executable":str(desktop),"loader":str(sdk),"auth_guard_status":401,"stale_settings_status":409,
            "profile_writes":False,"default_and_clear":True,"persistent_restore":True,"login_request":True}
if __name__=="__main__":
    evidence=check()
    if "--save" in sys.argv:Path(__file__).with_name("panel-runtime-proof.json").write_text(json.dumps(evidence,indent=2),encoding="utf8")
    print(json.dumps(evidence,ensure_ascii=True))

