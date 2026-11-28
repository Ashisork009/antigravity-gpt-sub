# antigravity-gpt-sub

**English** | [简体中文](README_CN.md)

Use your **ChatGPT / Codex subscription (Sign in with ChatGPT / SIWC)** natively inside **Google Antigravity (Windows `2.36.0`)** — with **GPT-6.2 Sol** and **GPT-6.2 Astra**, streaming reasoning summaries, **90%–98%+ prompt KV-cache hit rate**, native tool calling, subagents, Swarm, seamless cross-provider hot-switching, and a built-in toggleable bilingual collaboration workflow Skill.

No external proxy server, no separate API billing, compatible with third-party localization patches, and fully reversible with one click.

---

## Highlights

- **Native Antigravity `2.36.0` Integration**: Appears directly in Antigravity's model picker and Swarm roster as `codex-gpt-6.2-{sol,astra}-{low,medium,high,xhigh,max}`, with a built-in Settings sidecar panel to toggle models, choose reasoning levels, and manually refresh the catalog (transient network/proxy hiccups preserve cached models instead of clearing the picker).
- **256 MiB Payload / SSE Ceiling & Accurate HTTP 413 Semantics (`v0.6.0`)**:
  - Raises the local loopback router body, decompression (`gzip`/`br`/`deflate`), and SSE event buffer cap from `32 MiB` to `256 MiB` (the highest safe ceiling below V8's `MAX_STRING_LENGTH`), eliminating false `HTTP 413` interruptions on media-heavy native Gemini sessions.
  - Reports explicit `413 request_payload_too_large` when the cap is exceeded (both raw and decompressed payloads) instead of masking it as `model_inference_failed` or `400 invalid_model_request`.
- **High-Load Lease & Catalog Resilience (`v0.6.0`)**:
  - Eliminates false `HTTP 409 subscription_selection_revoked` bursts during heavy CPU/GPU workloads (e.g., concurrent multi-agent Swarm + 3D rendering): expands lease TTL to `30s`, heartbeat timeout to `10s`, owner-check timeout to `10s` (`20s` missing grace window), NTP clock-rollback tolerance to `+5s`, and adds Windows NTFS read/write contention retries.
  - Tolerates up to 2 consecutive transient heartbeat timeouts or non-`401/403` upstream catalog errors without dropping active GPT streams, while preserving immediate `200ms`-class revocation on explicit plugin disable, model deselection, or `401/403` auth revocation.
- **Version-Only Host Verification, Patch Coexistence & Custom Path Discovery**:
  - Defaults to `%LOCALAPPDATA%\Programs\antigravity` and automatically reads Antigravity's official NSIS registry (`HKCU/HKLM\Software\121a0be4-63bd-531e-acf8-fc3924c7e984\InstallLocation`) so custom install directories also work seamlessly.
  - Verifies Antigravity's version (`2.36.0`) and exact JS injection anchors rather than rigid whole-file hashes on `Antigravity.exe`, `language_server.exe`, or `app.asar`.
  - Dynamically extracts the embedded web bundle from your local `language_server.exe` and injects only `dist/languageServer.js` in `app.asar` — coexisting cleanly with third-party Chinese localization or UI patches across install, upgrade, rollback, and uninstall.
  - Seamlessly migrates prior `2.35.x` installations after Antigravity auto-updates while preserving your ChatGPT login, model preferences, and Skill toggle.
- **Built-in Toggleable Bilingual Workflow Skill**:
  - Antigravity's native global skills are always mounted with no UI toggle; this plugin adds a **Collaboration Workflow Skill (`gpt-swarm-workflow`)** switch (OFF by default) and **Chinese / English** live language selector directly inside the Settings panel.
  - Covers GPT-6.2 Sol/Astra tier discipline (`high` default), over-defense review filtering, aesthetic & documentation ownership boundaries, adaptive Swarm sizing, and five specialist playbooks (large refactors, math modeling, 3D/CAD, frontend UI, deep technical research).
  - Protects user-edited directories with ownership markers (`409` fail-closed, never overwrites custom skills) and cleans up managed files on uninstall.
- **High-Hit Prompt KV Cache (90%–98%+)**:
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
  - Antigravity Desktop **`2.36.0`** (stock or third-party localized)
  - Python **`3.11+`** (standard library only; daily runtime uses Antigravity's built-in Electron/Node runtime — no system Node or background proxy needed)
- **Building & Testing from Source**:
  - Python **`3.11+`**
  - Node.js **`22+`**

---

## Quick Start (Prebuilt Release)

1. Download **`antigravity-gpt-sub-v0.6.0-windows.zip`** from the [Releases](https://github.com/Ashisork009/antigravity-gpt-sub/releases) page and extract the entire archive to a local folder.
2. Double-click **`双击安装或管理.cmd`** (standard user permissions are recommended).
3. Press **Enter** to let the installer gracefully close Antigravity, deploy or migrate to `v0.6.0`, and automatically relaunch Antigravity.
4. Inside Antigravity, open **Customizations → Installed Plugins → Codex 订阅模型 → UI Plugins → 模型与推理等级 (Open in Side Panel)**, click **Continue with ChatGPT**, and sign in via OpenAI's official OAuth page.
5. *(Optional)* In the same side panel, toggle **协作工作流 Skill** on and choose **中文** or **English** to mount `gpt-swarm-workflow` globally (takes effect on the next turn).

> If you re-apply a third-party `language_server.exe` localization patch later, simply double-click `双击安装或管理.cmd` and pick `[1]` to refresh the local UI overlay.
> To uninstall and remove only this plugin's injection at any time, double-click `双击安装或管理.cmd` and choose `[4] uninstall` (your localization edits, preferences, subscription grant, and chat history stay untouched).
> Detailed installer notes: [integration/installation.md](integration/installation.md).

---

## Build & Test from Source

```powershell
# 1. Run all automated tests (Node + Python)
node --test subscription/generate.test.mjs subscription/plan.test.mjs catalog/catalog.test.mjs integration/fixture.test.mjs integration/lease_resilience.test.mjs
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
| `catalog/` | Native model catalog compilation, SQLite slot persistence, local loopback router (`127.0.0.1`), 256 MiB transport/decompression handling, on-demand OAuth token revalidation, and dynamic web overlay generator |
| `subscription/` | OpenAI SIWC OAuth PKCE login, Electron `safeStorage` (Windows DPAPI) token vault, Responses API translation, streaming thinking summaries, and KV-cache canonicalization |
| `integration/` | Desktop router entry, resilient lease renewal sidecar (`integration/sidecar/`), Settings sidecar UI panel, toggleable bilingual `gpt-swarm-workflow` Skill store & templates, version-checked install/migrate/upgrade/repair/rollback/uninstall engine, double-click Windows launcher, and reproducible build script |
| `vendor/v33-base/` | Hash-locked base codec and host adapter baseline required for reproducible builds |

---

## Privacy & Security

- **Local-only loopback**: All local HTTP listeners bind strictly to `127.0.0.1` and verify the caller's process/socket identity.
- **OS-encrypted credentials**: ChatGPT subscription refresh tokens are encrypted via Electron `safeStorage` (Windows DPAPI) and stored per-user; plaintext tokens are never written to disk.
- **Zero-PII diagnostics**: Local `diagnostics.json` records only HTTP status codes, token/cache counters, and non-reversible 8-character SHA-256 prefixes — never prompts, replies, or credentials.

---

## Disclaimer

This is an independent community integration project targeting Antigravity `2.36.0` on Windows. It is not affiliated with or endorsed by Google or OpenAI. Please comply with the respective Terms of Service when using this software.

## License

[MIT](LICENSE)
