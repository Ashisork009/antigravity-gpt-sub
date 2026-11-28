# antigravity-gpt-sub

[English](README.md) | **简体中文**

在 **Windows 版 Google Antigravity（`2.36.0`）** 中通过 OpenAI 官方 **Sign in with ChatGPT（SIWC）** 订阅授权，原生直接使用 **GPT-6.2 Sol** / **GPT-6.2 Astra** 等模型——支持多推理等级、流式思考摘要、**90%–98%+ 前缀缓存命中率**、原生工具调用、子代理、Swarm 蜂群、跨厂商无损热切换，以及面板内置的**中英双语协作工作流 Skill 热插拔开关**。

无需外部代理进程、无需额外 API 计费，与汉化等第三方本地补丁和平共存，一键可逆还原。

---

## 核心特性

- **原生适配 Antigravity `2.36.0`**：直接在 Antigravity 对话输入框与 Swarm 面板中选择 `codex-gpt-6.2-{sol,astra}-{low,medium,high,xhigh,max}`，内置设置侧边面板自由勾选模型、推理等级并支持一键「刷新目录」（网络/代理短暂抖动保留已缓存模型列表，不再误清空）。
- **256 MiB 本地请求体/SSE 兜底与 HTTP 413 语义修复（`v0.6.0` 新增）**：
  - 将本地回环路由的请求体收集、`gzip`/`br`/`deflate` 解压以及 SSE 事件缓冲上限从 `32 MiB` 统一提升至 V8 安全上限 `256 MiB`，消除含大量音频/图片的重媒体原生 Gemini 会话在本地层被误杀 `HTTP 413` 的问题；
  - 真正超限时准确返回 `413 request_payload_too_large`（原文与压缩解压超限一致），不再误报 `400 invalid_model_request` 或笼统的 `model_inference_failed`。
- **高负载 HTTP 409 租约抗抖动加固（`v0.6.0` 新增）**：
  - 解决高 CPU/GPU 负载（如多成员蜂群并发 + 3D 渲染）下租约心跳超时引发的批量 `409 subscription_selection_revoked` 误杀：租约 TTL 提升至 `30s`、心跳超时放宽至 `10s`、宿主巡检超时放宽至 `10s`（失联确认窗口 `20s`）、支持 `+5s` 时钟回拨容差，并加固 Windows NTFS 并发读写重试；
  - 连续 2 次瞬时超时或上游目录接口非 `401/403` 瞬时故障均不误删租约与有效路由绑定；用户显式禁用插件、取消勾选模型或收到 `401/403` 时仍保持 `200ms` 级立即吊销。
- **仅校版本号、与汉化补丁共存，并支持自定义安装目录自动发现**：
  - 默认定位 `%LOCALAPPDATA%\Programs\antigravity`，同时自动读取官方 NSIS 安装器注册表 `HKCU/HKLM\Software\121a0be4-63bd-531e-acf8-fc3924c7e984\InstallLocation`，兼容自定义安装路径；
  - 仅校验 Antigravity 宿主版本号（`2.36.0`）与精准代码注入锚点，不再强校验 `Antigravity.exe`、`language_server.exe`、`app.asar` 的整包哈希；
  - 从本机 `language_server.exe` 动态提取内嵌前端包并仅替换逻辑锚点，`app.asar` 也仅注入 `dist/languageServer.js`——无论先装汉化还是后装汉化，安装、升级、回滚、卸载均 100% 保留原有汉化改动；
  - 支持 Antigravity 自动更新（如 `2.35.x → 2.36.0`）后的一键无缝迁移，原有 ChatGPT 订阅登录、模型偏好与 Skill 配置全部保留。
- **内置可开关的中英双语协作 Skill**：
  - 解决 Antigravity 原生全局 Skill 挂载后常驻无法关闭的痛点——在设置侧边面板直接提供 **协作工作流 Skill（`gpt-swarm-workflow`）** 开关（默认关闭）与 **中文 / English** 实时切换，下一轮对话立即生效；
  - 内置 GPT-6.2 Sol/Astra 档位策略、反过度防御审稿清单、文档/审美权责边界、弹性蜂群编排及五大专项蓝图（大型重构测试、数学建模仿真、3D/CAD 参数化建模、前端 UI、深度技术调研）；
  - 带所有权清单保护，绝不覆盖用户手工修改的同名 Skill 目录，卸载插件时自动清理托管目录。
- **高命中率 Prompt KV Cache（实测 90%–98%+）**：
  - 遵循 GPT-6.2 Responses API 缓存规则，将复用的系统提示词前置为首条 `developer` 消息（避免顶层 `instructions` 追尾不缓存）；
  - 递归规范化工具列表顺序、参数 JSON Schema、`required` 数组及历史工具调用入参/出参的键序，并发送会话级 `prompt_cache_key` 与 `session-id` 路由粘性头。
- **完整 Agent 能力兼容**：
  - 实测通过原生子代理（`research` / `self` + 多轮 `send_message`）、Swarm 多代理协同（并发、worker 派生 helper、Fork 交接）、`run_workflow` 并行结构化编排、`/boost`、`/goal` 以及 PNG 图片视觉识别（`read_file`）；
  - 同一会话内支持 Codex GPT-6.2 ↔ Gemini ↔ Claude 双向热切换，零签名校验报错；Google OAuth 令牌约 55 分钟轮换时按需去重复核，彻底消除长会话 409 掉线黑窗。
- **安全可逆的一键双击安装器**：
  - 解压后双击 `双击安装或管理.cmd` 即可自动识别运行状态与目标安装目录，先用 Windows Restart Manager（`rstrtmgr.dll`）优雅关闭 Antigravity，再完成安装/迁移/升级/修复/回滚/卸载，最后自动重新拉起（管理员模式下自动通过桌面会话降权以普通权限启动）。

---

## 环境要求

- **普通用户（直接使用发布包）**：
  - Windows 10 / 11
  - Antigravity 桌面端 **`2.36.0`**（原版或已打汉化补丁均可）
  - Python **`3.11+`**（仅使用标准库；日常运行复用 Antigravity 自带运行时，不依赖系统 Node 或独立代理）
- **开发者（源码构建与测试）**：
  - Python **`3.11+`**
  - Node.js **`22+`**

---

## 快速安装（推荐直接用发布包）

1. 在 [Releases](https://github.com/Ashisork009/antigravity-gpt-sub/releases) 页面下载 **`antigravity-gpt-sub-v0.6.0-windows.zip`** 并完整解压到本地文件夹。
2. 直接双击目录内的 **`双击安装或管理.cmd`**（推荐使用普通用户权限即可）。
3. 按提示直接回车，脚本会自动关闭 Antigravity、完成部署或从旧宿主版本无缝迁移并重新打开软件。
4. 重启后打开 **个性化定制 → 已安装插件 → Codex 订阅模型 → UI Plugins → 模型与推理等级 → 在侧边面板中打开**，点击 **Continue with ChatGPT** 在官方页面完成授权即可使用。
5. *（可选）* 在同一面板底部按需打开 **协作工作流 Skill** 开关并选择 **中文** 或 **English**，即可动态挂载/切换 `gpt-swarm-workflow`。

> 若安装后再重打 `language_server.exe` 汉化补丁，只需再次双击 `双击安装或管理.cmd` 选 `[1]` 即可自动刷新前端覆盖层。
> 如需卸载，双击 `双击安装或管理.cmd` 选择 `[4] 卸载` 即可（仅移除本插件注入，汉化改动、订阅授权、偏好设置和历史会话均保留）。
> 更多安装与修复细节见 [integration/installation.md](integration/installation.md)。

---

## 从源码构建与运行测试

```powershell
# 1. 运行全部自动化测试（Node + Python）
node --test subscription/generate.test.mjs subscription/plan.test.mjs catalog/catalog.test.mjs integration/fixture.test.mjs integration/lease_resilience.test.mjs
$env:PYTHONPATH = "integration"; python -B -m unittest -v integration/test_launcher.py
python -B catalog/test_renderer_overlay.py
python -B integration/test_panel.py
python -B integration/test_install.py --skill-only

# 2. 构建 Windows 正式订阅版发布包（产物输出在 release/ 目录）
python -B integration/build.py
```

---

## 目录结构

| 目录 | 职责说明 |
| --- | --- |
| `catalog/` | 原生模型目录编译、SQLite 槽位持久化、本地回环路由（`127.0.0.1`）、256 MiB 传输/解压处理、按需 OAuth 令牌复核与动态界面覆盖层生成 |
| `subscription/` | OpenAI SIWC OAuth PKCE 登录、Electron `safeStorage`（Windows DPAPI）加密存储、Responses API 协议翻译、流式思考摘要与缓存规范化 |
| `integration/` | 桌面路由入口、抗抖动租约续订 sidecar（`integration/sidecar/`）、设置侧边面板 UI、可开关双语 `gpt-swarm-workflow` Skill 模板与存储、版本校验安装/迁移/升级/修复/回滚/卸载引擎、双击启动脚本与可复现打包脚本 |
| `vendor/v33-base/` | 冻结校验的底层编解码与宿主适配基线模块 |

---

## 隐私与安全说明

- **纯本地回环**：本地路由严格仅监听 `127.0.0.1`，并校验调用方宿主进程与 Socket 身份。
- **系统级加密凭证**：ChatGPT 订阅刷新令牌通过 Electron `safeStorage`（Windows DPAPI）加密保存于当前用户目录，绝不落盘明文。
- **零原文诊断日志**：`diagnostics.json` 仅记录 HTTP 状态码、Token/缓存计数与不可逆 8 位哈希，不存储任何对话内容或凭据。

---

## 免责声明

本项目为独立社区适配项目，面向 Windows 版 Antigravity `2.36.0`，与 Google 及 OpenAI 无任何官方关联。使用前请遵守相应平台的服务条款。

## 开源协议

[MIT](LICENSE)
