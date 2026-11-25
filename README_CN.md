# antigravity-gpt-sub

[English](README.md) | **简体中文**

在 **Windows 版 Google Antigravity（`2.35.1`）** 中通过 OpenAI 官方 **Sign in with ChatGPT（SIWC）** 订阅授权，原生直接使用 **GPT-6.2 Sol** / **GPT-6.2 Astra** 等模型——支持多推理等级、流式思考摘要、**90%–97%+ 前缀缓存命中率**、原生工具调用、子代理、Swarm 蜂群与跨厂商无损热切换（Gemini ↔ Claude ↔ GPT）。

无需外部代理进程、无需额外 API 计费，全链路哈希校验，一键可逆还原。

---

## 核心特性

- **原生接入模型菜单**：直接在 Antigravity 对话输入框与 Swarm 面板中选择 `codex-gpt-6.2-{sol,astra}-{low,medium,high,xhigh,max}`，内置设置侧边面板自由勾选模型与推理等级。
- **高命中率 Prompt KV Cache（实测 90%–97%+）**：
  - 遵循 GPT-6.2 Responses API 缓存规则，将复用的系统提示词前置为首条 `developer` 消息（避免顶层 `instructions` 追尾不缓存）；
  - 递归规范化工具列表顺序、参数 JSON Schema、`required` 数组及历史工具调用入参/出参的键序；
  - 同步发送稳定会话级 `prompt_cache_key` 与 `session-id` 路由粘性头。
- **完整 Agent 能力兼容**：
  - 实测通过原生子代理（`research` / `self` + 多轮 `send_message`）、Swarm 多代理协同（并发、worker 派生 helper、Fork 交接）、`run_workflow` 并行结构化编排、`/boost`、`/goal` 以及 PNG 图片视觉识别（`read_file`）；
  - 同一会话内支持 Codex GPT-6.2 ↔ Gemini ↔ Claude 双向热切换，零签名校验报错；
  - Google OAuth 短期令牌约 55 分钟自动轮换时，按需并发去重复核，彻底消除长会话 409 掉线黑窗。
- **安全可逆的一键双击安装器**：
  - 解压后双击 `双击安装或管理.cmd` 即可自动识别运行状态，先用 Windows Restart Manager（`rstrtmgr.dll`）优雅关闭 Antigravity，再完成安装/升级/修复/回滚/卸载，最后自动重新拉起（管理员模式下自动通过桌面会话降权以普通权限启动）。

---

## 环境要求

- **普通用户（直接使用发布包）**：
  - Windows 10 / 11
  - Antigravity 桌面端 **`2.35.1`**（安装器会严格校验宿主文件哈希）
  - Python **`3.11+`**（仅使用标准库；日常运行复用 Antigravity 自带运行时，不依赖系统 Node 或独立代理）
- **开发者（源码构建与测试）**：
  - Python **`3.11+`**
  - Node.js **`22+`**

---

## 快速安装（推荐直接用发布包）

1. 在 [Releases](https://github.com/Ashisork009/antigravity-gpt-sub/releases) 页面下载 **`antigravity-gpt-sub-v0.4.7-windows.zip`** 并完整解压到本地文件夹。
2. 直接双击目录内的 **`双击安装或管理.cmd`**（推荐使用普通用户权限即可）。
3. 按提示直接回车，脚本会自动关闭 Antigravity、完成部署并重新打开软件。
4. 重启后打开 **个性化定制 → 已安装插件 → Codex 订阅模型 → UI Plugins → 模型与推理等级 → 在侧边面板中打开**，点击连接 ChatGPT 订阅，在官方页面完成授权即可使用。

> 如需卸载并恢复原厂 Antigravity，只需再次双击 `双击安装或管理.cmd` 选择 `[4] 卸载` 即可（订阅授权、偏好设置和历史会话均保留在用户目录）。
> 更多安装与修复细节见 [integration/installation.md](integration/installation.md)。

---

## 从源码构建与运行测试

```powershell
# 1. 运行全部自动化测试（Node + Python）
node --test subscription/generate.test.mjs subscription/plan.test.mjs catalog/catalog.test.mjs integration/fixture.test.mjs
$env:PYTHONPATH = "integration"; python -B -m unittest -v integration/test_launcher.py
python -B catalog/test_renderer_overlay.py
python -B integration/test_panel.py

# 2. 构建 Windows 正式订阅版发布包（产物输出在 release/ 目录）
python -B integration/build.py
```

---

## 目录结构

| 目录 | 职责说明 |
| --- | --- |
| `catalog/` | 原生模型目录编译、SQLite 槽位持久化、本地回环路由（`127.0.0.1`）、按需 OAuth 令牌复核与界面叠加包生成 |
| `subscription/` | OpenAI SIWC OAuth PKCE 登录、Electron `safeStorage`（Windows DPAPI）加密存储、Responses API 协议翻译、流式思考摘要与缓存规范化 |
| `integration/` | 桌面路由入口、设置侧边面板 UI、哈希校验安装/升级/修复/回滚/卸载引擎、双击启动脚本与可复现打包脚本 |
| `vendor/v33-base/` | 冻结校验的底层编解码与宿主适配基线模块 |

---

## 隐私与安全说明

- **纯本地回环**：本地路由严格仅监听 `127.0.0.1`，并校验调用方宿主进程与 Socket 身份。
- **系统级加密凭证**：ChatGPT 订阅刷新令牌通过 Electron `safeStorage`（Windows DPAPI）加密保存于当前用户目录，绝不落盘明文。
- **零原文诊断日志**：`diagnostics.json` 仅记录 HTTP 状态码、Token/缓存计数与不可逆 8 位哈希，不存储任何对话内容或凭据。

---

## 免责声明

本项目为独立社区适配项目，仅面向已核对的 Windows 版 Antigravity `2.35.1`，与 Google 及 OpenAI 无任何官方关联。使用前请遵守相应平台的服务条款。

## 开源协议

[MIT](LICENSE)
