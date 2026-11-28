# Windows 原生订阅模型插件（v0.6.0）

本包适配 **Antigravity 2.36.0**（默认定位 `%LOCALAPPDATA%\Programs\antigravity`，并自动读取官方 NSIS 安装器注册表 `HKCU\Software\121a0be4-63bd-531e-acf8-fc3924c7e984\InstallLocation` 以兼容自定义安装目录；仅校验宿主版本号与代码注入锚点，不强校验宿主整包哈希，可与汉化补丁等第三方本地补丁共存）。安装器需要 Python 3.11 或更高版本。日常运行使用 Antigravity 自带的 Electron、语言服务及官方 sidecar JavaScript 运行时，不依赖系统 Node 或单独启动的代理。

## v0.6.0 核心改进
- **Antigravity 2.36.0 适配与自定义/跨目录迁移**：同步更新前端覆盖层锚点，通过官方安装注册表与默认路径联合定位桌面端目录，支持默认目录及自定义安装目录之间的无缝升级与旧收据归档。
- **256 MiB 本地请求体/SSE 兜底与 413 语义修复**：将本地路由请求体、压缩解压与 SSE 缓冲上限从 32 MiB 统一提升至 V8 安全上限 256 MiB，消除重媒体会话误杀原生 Gemini；超限时准确返回 `413 request_payload_too_large` 而非 `400` 或笼统报错。
- **高负载 409 租约抗抖动加固**：放宽租约 TTL 至 30 秒、心跳超时至 10 秒，连续 2 次瞬时超时或上游目录非 401/403 抖动不误删租约与路由绑定，加固 Windows NTFS 读写竞态与时钟回拨容差；用户显式禁用插件或取消勾选模型时仍保持 200ms 级立即吊销。

## 安装与升级
当 Antigravity 桌面端自动更新（例如从 2.35.2 升级到 2.36.0）导致旧版插件失效，或在已打汉化补丁的 2.36.0 上安装时，直接双击新版安装包中的 `双击安装或管理.cmd` 选择 `[1]` 即可自动归档旧收据、动态生成适配当前本机语言服务的覆盖层并仅注入 `dist/languageServer.js`——完整保留汉化补丁改动、订阅登录、模型偏好与协作 Skill 配置。若之后又重新打了 `language_server.exe` 汉化补丁，再次双击选 `[1]` 即可刷新界面覆盖层。

安装器会核对本机语言服务、内嵌的原厂 Web 归档和应用入口，在本机生成适配模型菜单刷新、订阅档位顺序与选中模型恢复的界面资源 ZIP。生成位置为 `%USERPROFILE%\.antigravity-native-model-router\overlays\<SHA256>.zip`。桌面启动时验证该文件，使用语言服务的 `--web_bundle_path` 指定界面资源。原有自定义启动参数优先。卸载和回滚使用各自的收据与哈希清理安装器生成的 ZIP。

在完整解压目录中**直接双击 `双击安装或管理.cmd`**（建议用普通用户权限即可；脚本会自动检测 Antigravity 运行状态，支持一键自动安全关闭进程并在安装/升级/回滚/卸载完成后自动重新启动 Antigravity，也提供修复与预览菜单）。也可以在 PowerShell 手动执行：先运行 `python -B manage.py preview` 生成候选归档指纹，退出 Antigravity 后运行 `python -B manage.py install`（或 `upgrade`），然后从原来的入口启动桌面。已装的旧版本由同一入口自动迁移。

## 使用与维护
设置入口为个性化定制的已安装插件列表中的“Codex 订阅模型”。首次订阅连接使用官方授权页面。用于内部验收的独立诊断包在界面标注“确定性验收”，只用于模拟测试。

在详情页选择 **UI Plugins → 模型与推理等级 → 在侧边面板中打开**。默认选择 GPT-6.2 Sol、GPT-6.2 Astra 以及 Low、Medium、High、Extra High、Max。档位只在订阅目录声明该模型支持时显示。原生对话输入框的模型按钮显示当前选中的模型与档位。

设置面板提供 **协作工作流 Skill**，默认关闭，可选择中文或 English。开启后挂载到 `~/.gemini/config/skills/gpt-swarm-workflow/`，下一轮对话生效；开启时切换语言会立即替换托管模板。若目录有手工修改，管理器会保留原样。通过 Antigravity 原生插件页直接禁用或删除插件不会触发 Skill 清理；请先在面板关闭开关，或使用管理脚本卸载。

误删设置页的模型插件后，从同一份解压目录运行 `python -B manage.py repair`。该操作验证收据、归档及文件哈希，恢复缺失的插件文件，并将损坏的原文件保存到用户目录。修复命令会输出备份目录。要撤销这次修复，可在退出桌面后运行 `python -B manage.py undo-repair --journal "备份目录"`。若语言服务或路由组件需要修复，退出桌面后运行 `python -B manage.py install`。

上一版遗留的全局 sidecar 进程若持续占用其安装目录，Windows 安装器会用 Python 的 psutil 核对进程身份并回收。未安装 psutil 时，也可正常退出占用目录的旧进程再运行安装器。

升级前的收据、归档和插件文件保存在 `%USERPROFILE%\.antigravity-native-model-router\backups`。退出桌面后运行 `python -B manage.py rollback` 会恢复安装前版本。首次安装的回滚会恢复安装前的原始归档。运行 `python -B manage.py uninstall` 则移除当前部署并还原已核对的原始归档。用户的偏好、订阅授权和已有会话保持在用户目录。宿主升级后旧包不会覆盖新归档。
