"""Check dynamic source ZIP extraction, localization coexistence, syntax, and native picker events."""
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import zipfile
import renderer_overlay as overlay


def find_language_server():
    candidates = []
    if os.name == "nt":
        import winreg
        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            try:
                with winreg.OpenKey(hive, r"Software\121a0be4-63bd-531e-acf8-fc3924c7e984") as key:
                    loc = winreg.QueryValueEx(key, "InstallLocation")[0]
                if isinstance(loc, str) and loc.strip():
                    candidates.append(Path(loc.strip()))
            except OSError:
                continue
    candidates.append(Path(os.environ["LOCALAPPDATA"]) / "Programs/antigravity")
    for root in candidates:
        cand = root / "resources/bin/language_server.exe"
        if cand.is_file() and (root / "resources/app.asar").is_file():
            return cand
    return candidates[0] / "resources/bin/language_server.exe"


LS = find_language_server()


class OverlayTests(unittest.TestCase):
    def test_assets_and_normal_entry(self):
        source = overlay.original_bundle(LS)
        with tempfile.TemporaryDirectory() as folder:
            out_dir = Path(folder)
            digest1 = overlay.ensure_overlay(LS, out_dir)
            digest2 = overlay.ensure_overlay(LS, out_dir)
            self.assertEqual(digest1, digest2)
            path = out_dir / (digest1 + ".zip")
            with zipfile.ZipFile(io.BytesIO(source)) as before, zipfile.ZipFile(path) as after:
                self.assertEqual(after.namelist(), before.namelist())
                changed = [name for name in before.namelist() if before.read(name) != after.read(name)]
                self.assertEqual(changed, ["main.js"])
                original = before.read("main.js")
                transformed = after.read("main.js")
                self.assertEqual(transformed.count(overlay.HOOK), 1)
                self.assertEqual(transformed.count(overlay.EFFORT_HOOK), 1)
                restored = transformed
                for anchor, replacement in reversed(overlay.overlay_edits()):
                    self.assertEqual(restored.count(replacement), 1)
                    restored = restored.replace(replacement, anchor)
                self.assertEqual(restored, original)
                js = out_dir / "main.js"
                js.write_bytes(transformed)
                subprocess.run(["node", "--check", str(js)], check=True, capture_output=True)
                orig_fn = original[original.index(b"function Ehc("):original.index(b"function Ghc(")]

                def picker_branch(data):
                    start = data.index(b"var V=L?void 0:ZW(a,f)")
                    end = data.index(b"};var zjd=", start)
                    return data[start:end].decode()

                group = original[original.index(b"const R8b="):original.index(b"function f9b(")].decode()
                history = transformed[transformed.index(b"function Gvc("):transformed.index(b"function Ivc(")]
                payload = {
                    "hook": overlay.HOOK.decode(),
                    "history": history.decode(),
                    "status": orig_fn.decode(),
                    "group": group,
                    "before": picker_branch(original),
                    "after": picker_branch(transformed),
                }
                result = subprocess.run(
                    ["node", "overlay_hook_test.cjs"],
                    cwd=Path(__file__).parent,
                    input=json.dumps(payload),
                    text=True,
                    capture_output=True,
                )
                self.assertEqual(result.returncode, 0, result.stderr)

            # Simulate a localized language_server.exe whose UI strings in main.js were translated:
            localized_zip = io.BytesIO()
            with zipfile.ZipFile(io.BytesIO(source)) as zin, zipfile.ZipFile(localized_zip, "w") as zout:
                for item in zin.infolist():
                    raw = zin.read(item)
                    if item.filename == "main.js":
                        raw = raw.replace(
                            b"Applies to messages sent after this turn",
                            "适用于本轮之后发送的消息".encode("utf-8"),
                        )
                    zout.writestr(item, raw)
            localized_ls = out_dir / "localized_ls.exe"
            localized_ls.write_bytes(b"MZ" + b"\x00" * 64 + localized_zip.getvalue() + b"\x00" * 32)
            loc_digest = overlay.ensure_overlay(localized_ls, out_dir)
            self.assertNotEqual(loc_digest, digest1)
            with zipfile.ZipFile(out_dir / (loc_digest + ".zip")) as zloc:
                loc_main = zloc.read("main.js")
                self.assertIn("适用于本轮之后发送的消息".encode("utf-8"), loc_main)
                self.assertEqual(loc_main.count(overlay.HOOK), 1)

            # Corrupted existing overlay with matching filename fails closed:
            path.write_bytes(b"other")
            with self.assertRaises(ValueError):
                overlay.ensure_overlay(LS, out_dir)
            self.assertEqual(path.read_bytes(), b"other")
            foreign = out_dir / "foreign.exe"
            foreign.write_bytes(b"different version without zip")
            with self.assertRaises(ValueError):
                overlay.ensure_overlay(foreign, out_dir)


if __name__ == "__main__":
    unittest.main()
