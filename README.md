# antigravity-gpt-sub

**English** | [简体中文](README_CN.md)

Use your **ChatGPT / Codex subscription (Sign in with ChatGPT / SIWC)** natively inside **Google Antigravity (Windows `2.35.1`)** — with **GPT-6.2 Sol** and **GPT-6.2 Astra**, streaming reasoning summaries, **90%–97%+ prompt KV-cache hit rate**, native tool calling, subagents, Swarm, and seamless cross-provider hot-switching (Gemini ↔ Claude ↔ GPT).

No external proxy server, no manual API key billing, and fully reversible with one click.

---

## Highlights

- **Native Antigravity Integration**: Appears directly in Antigravity's model picker and Swarm roster as `codex-gpt-6.2-{sol,astra}-{low,medium,high,xhigh,max}`, with a built-in Settings sidecar panel to toggle models and reasoning levels.
- **High-Hit Prompt KV Cache (90%–97%+)**:
  - Follows the GPT-6.2 Responses API layout by placing reusable system instructions in the leading `developer` message instead of the uncached top-level `instructions` field.
  - Deterministically canonicalizes tool order, JSON Schema parameter keys, `required` arrays, and historical tool call/output maps to prevent Go ProtoJSON map-order cache busts.
  - Sends stable per-conversation `prompt_cache_key` and `session-id` affinity headers.
- **Full Agentic Feature Compatibility**:
  - Verified across native subagents (`research` / `self` + multi-round `send_message`), multi-agent Swarm (parallel workers, worker-spawned helpers, fork handoff), `run_workflow` parallel pipelines, `/boost` and `/goal` workflows, and PNG image vision (`read_file`).
  - Bidirectional mid-conversation hot-switching between Codex GPT-6.2, Gemini, and Claude without signature validation errors.
  - On-demand deduplicated Google OAuth token revalidation prevents 409 interruptions during 55-minute OAuth token rotations in long sessions.
- **Safe, Reversible Double-Click Windows Installer**:
  - Double-click `双击安装或管理.cmd` to check status, gracefully close Antigravity via Windows Restart Manager (`rstrtmgr.dll`), install/upgrade/repair/rollback/uninstall with full SHA-256 verification, and automatically relaunch Antigravity (de-elevating via desktop shell if launched as Administrator).

---

## Requirements

- **End Users (Prebuilt Release)**:
  - Windows 10 / 11
  - Antigravity Desktop **`2.35.1`** (exact hash-verified host build)
  - Python **`3.11+`** (standard library only; daily runtime uses Antigravity's built-in Electron/Node runtime — no system Node or background proxy needed)
- **Building & Testing from Source**:
  - Python **`3.11+`**
  - Node.js **`22+`**

---

## Quick Start (Prebuilt Release)

1. Download **`antigravity-gpt-sub-v0.4.7-windows.zip`** from the [Releases](https://github.com/Ashisork009/antigravity-gpt-sub/releases) page and extract the entire archive to a local folder.
2. Double-click **`双击安装或管理.cmd`** (standard user permissions are recommended).
3. Press **Enter** to let the installer gracefully close Antigravity, deploy `v0.4.7`, and automatically relaunch Antigravity.
4. Inside Antigravity, open **Customizations → Installed Plugins → Codex 订阅模型 → UI Plugins → 模型与推理等级 (Open in Side Panel)**, click **Connect ChatGPT Subscription**, and sign in via OpenAI's official OAuth page.

> To uninstall and restore the original verified Antigravity archive at any time, double-click `双击安装或管理.cmd` and choose `[4] uninstall` (your preferences, subscription grant, and chat history stay untouched in your user directory).
> Detailed installer notes: [integration/installation.md](integration/installation.md).

---

## Build & Test from Source

```powershell
# 1. Run all automated tests (Node + Python)
node --test subscription/generate.test.mjs subscription/plan.test.mjs catalog/catalog.test.mjs integration/fixture.test.mjs
$env:PYTHONPATH = "integration"; python -B -m unittest -v integration/test_launcher.py
python -B catalog/test_renderer_overlay.py
python -B integration/test_panel.py

# 2. Build the Windows subscription release package (outputs to ./release/)
python -B integration/build.py
```

---

## Repository Structure

| Path | Responsibility |
| --- | --- |
| `catalog/` | Native model catalog compilation, SQLite slot persistence, local loopback router (`127.0.0.1`), on-demand OAuth token revalidation, and web overlay generator |
| `subscription/` | OpenAI SIWC OAuth PKCE login, Electron `safeStorage` (Windows DPAPI) token vault, Responses API translation, streaming thinking summaries, and KV-cache canonicalization |
| `integration/` | Desktop router entry, Settings sidecar UI panel, hash-verified install/upgrade/repair/rollback/uninstall engine, double-click Windows launcher, and reproducible build script |
| `vendor/v33-base/` | Hash-locked base codec and host adapter baseline required for reproducible builds |

---

## Privacy & Security

- **Local-only loopback**: All local HTTP listeners bind strictly to `127.0.0.1` and verify the caller's process/socket identity.
- **OS-encrypted credentials**: ChatGPT subscription refresh tokens are encrypted via Electron `safeStorage` (Windows DPAPI) and stored per-user; plaintext tokens are never written to disk.
- **Zero-PII diagnostics**: Local `diagnostics.json` records only HTTP status codes, token/cache counters, and non-reversible 8-character SHA-256 prefixes — never prompts, replies, or credentials.

---

## Disclaimer

This is an independent community integration project targeting Antigravity `2.35.1` on Windows. It is not affiliated with or endorsed by Google or OpenAI. Please comply with the respective Terms of Service when using this software.

## License

[MIT](LICENSE)
