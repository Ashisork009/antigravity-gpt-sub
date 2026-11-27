# antigravity-gpt-sub

**English** | [简体中文](README_CN.md)

Use your **ChatGPT / Codex subscription (Sign in with ChatGPT / SIWC)** natively inside **Google Antigravity (Windows `2.35.2`)** — with **GPT-6.2 Sol** and **GPT-6.2 Astra**, streaming reasoning summaries, **90%–97%+ prompt KV-cache hit rate**, native tool calling, subagents, Swarm, seamless cross-provider hot-switching, and a built-in toggleable bilingual collaboration workflow Skill.

No external proxy server, no separate API billing, compatible with third-party localization patches, and fully reversible with one click.

---

## Highlights

- **Native Antigravity `2.35.2` Integration**: Appears directly in Antigravity's model picker and Swarm roster as `codex-gpt-6.2-{sol,astra}-{low,medium,high,xhigh,max}`, with a built-in Settings sidecar panel to toggle models, choose reasoning levels, and manually refresh the catalog (`v0.5.3` preserves cached models during transient proxy/network hiccups instead of clearing the picker).
- **Version-Only Host Verification & Patch Coexistence (`v0.5.2`)**:
  - Verifies Antigravity's version (`2.35.2`) and exact JS injection anchors rather than rigid whole-file hashes on `Antigravity.exe`, `language_server.exe`, or `app.asar`.
  - Dynamically extracts the embedded web bundle from your local `language_server.exe` and injects only `dist/languageServer.js` in `app.asar` — coexisting cleanly with third-party Chinese localization or UI patches across install, upgrade, rollback, and uninstall.
  - Seamlessly migrates prior `2.35.1` installations after Antigravity auto-updates while preserving your ChatGPT login, model preferences, and Skill toggle.
- **Built-in Toggleable Bilingual Workflow Skill (`v0.5.0+`)**:
  - Antigravity's native global skills are always mounted with no UI toggle; this plugin adds a **Collaboration Workflow Skill (`gpt-swarm-workflow`)** switch (OFF by default) and **Chinese / English** live language selector directly inside the Settings panel.
  - Covers GPT-6.2 Sol/Astra tier discipline (`high` default), over-defense review filtering, aesthetic & documentation ownership boundaries, adaptive Swarm sizing, and five specialist playbooks (large refactors, math modeling, 3D/CAD, frontend UI, deep technical research).
  - Protects user-edited directories with ownership markers (`409` fail-closed, never overwrites custom skills) and cleans up managed files on uninstall.
- **High-Hit Prompt KV Cache (90%–97%+)**:
  - Places reusable system instructions in the leading `developer` message instead of GPT-6.2's uncached top-level `instructions` field.
  - Canonicalizes tool order, JSON Schema parameter keys, `required` arrays, and historical tool call/output maps, and sends stable `prompt_cache_key` + `session-id` affinity headers.
- **Full Agentic Feature Compatibility**:
  - Verified across native subagents (`research` / `self` + multi-round `send_message`), multi-agent Swarm (parallel workers, worker-spawned helpers, fork handoff), `run_workflow` parallel pipelines, `/boost` and `/goal` workflows, and PNG image vision (`read_file`).
  - Bidirectional mid-conversation hot-switching between Codex GPT-6.2, Gemini, and Claude without signature validation errors, plus on-demand Google OAuth token revalidation across 55-minute token rotations.
- **Safe, Reversible Double-Click Windows Installer**:
  - Double-click `双击安装或管理.cmd` to check status, gracefully close Antigravity via Windows Restart Manager (`rstrtmgr.dll`), install/migrate/upgrade/repair/rollback/uninstall, and automatically relaunch Antigravity (de-elevating via desktop shell if launched as Administrator).

---

## Requirements

- **End Users (Prebuilt Release)**:
  - Windows 10 / 11
  - Antigravity Desktop **`2.35.2`** (stock or third-party localized)
  - Python **`3.11+`** (standard library only; daily runtime uses Antigravity's built-in Electron/Node runtime — no system Node or background proxy needed)
- **Building & Testing from Source**:
  - Python **`3.11+`**
  - Node.js **`22+`**

---

## Quick Start (Prebuilt Release)

1. Download **`antigravity-gpt-sub-v0.5.3-windows.zip`** from the [Releases](https://github.com/Ashisork009/antigravity-gpt-sub/releases) page and extract the entire archive to a local folder.
2. Double-click **`双击安装或管理.cmd`** (standard user permissions are recommended).
3. Press **Enter** to let the installer gracefully close Antigravity, deploy or migrate to `v0.5.3`, and automatically relaunch Antigravity.
4. Inside Antigravity, open **Customizations → Installed Plugins → Codex 订阅模型 → UI Plugins → 模型与推理等级 (Open in Side Panel)**, click **Continue with ChatGPT**, and sign in via OpenAI's official OAuth page.
5. *(Optional)* In the same side panel, toggle **协作工作流 Skill** on and choose **中文** or **English** to mount `gpt-swarm-workflow` globally (takes effect on the next turn).

> If you re-apply a third-party `language_server.exe` localization patch later, simply double-click `双击安装或管理.cmd` and pick `[1]` to refresh the local UI overlay.
> To uninstall and remove only this plugin's injection at any time, double-click `双击安装或管理.cmd` and choose `[4] uninstall` (your localization edits, preferences, subscription grant, and chat history stay untouched).
> Detailed installer notes: [integration/installation.md](integration/installation.md).

---

## Build & Test from Source

```powershell
# 1. Run all automated tests (Node + Python)
node --test subscription/generate.test.mjs subscription/plan.test.mjs catalog/catalog.test.mjs integration/fixture.test.mjs
$env:PYTHONPATH = "integration"; python -B -m unittest -v integration/test_launcher.py
python -B catalog/test_renderer_overlay.py
python -B integration/test_panel.py
python -B integration/test_install.py --skill-only

# 2. Build the Windows subscription release package (outputs to ./release/)
python -B integration/build.py
```

---

## Repository Structure

| Path | Responsibility |
| --- | --- |
| `catalog/` | Native model catalog compilation, SQLite slot persistence, local loopback router (`127.0.0.1`), on-demand OAuth token revalidation, and dynamic web overlay generator |
| `subscription/` | OpenAI SIWC OAuth PKCE login, Electron `safeStorage` (Windows DPAPI) token vault, Responses API translation, streaming thinking summaries, and KV-cache canonicalization |
| `integration/` | Desktop router entry, Settings sidecar UI panel, toggleable bilingual `gpt-swarm-workflow` Skill store & templates, version-checked install/migrate/upgrade/repair/rollback/uninstall engine, double-click Windows launcher, and reproducible build script |
| `vendor/v33-base/` | Hash-locked base codec and host adapter baseline required for reproducible builds |

---

## Privacy & Security

- **Local-only loopback**: All local HTTP listeners bind strictly to `127.0.0.1` and verify the caller's process/socket identity.
- **OS-encrypted credentials**: ChatGPT subscription refresh tokens are encrypted via Electron `safeStorage` (Windows DPAPI) and stored per-user; plaintext tokens are never written to disk.
- **Zero-PII diagnostics**: Local `diagnostics.json` records only HTTP status codes, token/cache counters, and non-reversible 8-character SHA-256 prefixes — never prompts, replies, or credentials.

---

## Disclaimer

This is an independent community integration project targeting Antigravity `2.35.2` on Windows. It is not affiliated with or endorsed by Google or OpenAI. Please comply with the respective Terms of Service when using this software.

## License

[MIT](LICENSE)
