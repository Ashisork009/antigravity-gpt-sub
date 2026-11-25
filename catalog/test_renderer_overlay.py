"""Check complete source ZIP, syntax, native picker events, stale responses and rollback guards."""
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import zipfile
import renderer_overlay as overlay

LS=Path(os.environ["LOCALAPPDATA"])/"Programs/Antigravity/resources/bin/language_server.exe"

class OverlayTests(unittest.TestCase):
    def test_assets_and_normal_entry(self):
        source=overlay.original_bundle(LS)
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/"known.zip"
            self.assertEqual(overlay.ensure_overlay(LS,path),overlay.EXPECTED_OVERLAY_SHA256)
            self.assertEqual(overlay.ensure_overlay(LS,path),overlay.EXPECTED_OVERLAY_SHA256)
            with zipfile.ZipFile(io.BytesIO(source)) as before,zipfile.ZipFile(path) as after:
                self.assertEqual(after.namelist(),before.namelist())
                changed=[name for name in before.namelist() if before.read(name)!=after.read(name)]
                self.assertEqual(changed,["main.js"])
                original=before.read("main.js")
                transformed=after.read("main.js")
                self.assertEqual(transformed.count(overlay.HOOK),1)
                self.assertEqual(transformed.count(overlay.EFFORT_HOOK),1)
                restored=transformed
                for anchor,replacement in reversed(overlay.overlay_edits()):
                    self.assertEqual(restored.count(replacement),1)
                    restored=restored.replace(replacement,anchor)
                self.assertEqual(restored,original)
                js=Path(folder)/"main.js";js.write_bytes(transformed)
                subprocess.run(["node","--check",str(js)],check=True,capture_output=True)
                orig_fn=original.split(b"async function V3b(",1)[1].split(b"function W3b()",1)[0]
                # Execute the actual compiled status reader in the hook. Only the host and React scheduler are mocked.
                def picker_branch(data):
                    start=data.index(overlay.EFFORT_ANCHOR)
                    end=data.index(b'return E.createElement(kW,{"data-testid":"model-selector-item"',start)
                    return data[start:end].decode()
                group=original[original.index(b"const dVb="):original.index(b"function qVb(")].decode()
                history=transformed[transformed.index(b"function ahc("):transformed.index(b"function chc(")]
                payload={"hook":overlay.HOOK.decode(),"history":history.decode(),"status":"async function V3b("+orig_fn.decode(),
                         "group":group,"before":picker_branch(original),"after":picker_branch(transformed)}
                result=subprocess.run(["node","overlay_hook_test.cjs"],cwd=Path(__file__).parent,input=json.dumps(payload),text=True,capture_output=True)
                self.assertEqual(result.returncode,0,result.stderr)
            path.write_bytes(b"other")
            with self.assertRaises(ValueError):overlay.ensure_overlay(LS,path)
            self.assertEqual(path.read_bytes(),b"other")
            foreign=Path(folder)/"foreign.exe";foreign.write_bytes(b"different version")
            with self.assertRaises(ValueError):overlay.ensure_overlay(foreign,path)

if __name__=="__main__":unittest.main()
