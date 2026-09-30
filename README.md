# Desktop Agent

用自然语言指挥电脑的 Windows 桌面助手：你打一句"打开计算器"、"在记事本里输入你好"，
AI 看屏幕、动鼠标键盘、验证结果，一步步把事办完。模型可走本机 Ollama（数据不出本机），
也可走云端 API（免装本地模型）。

- 许可证：[MIT](LICENSE)　·　平台：Windows 10/11　·　当前版本：v2.0.15（`gui.py` 的 `APP_VERSION`）
- 开发实测环境：Python 3.14 / Windows 10（更低版本未实测，依赖均为纯 pip 安装）
- 测试：核心套件 **231 passed / 7 xfailed**（2026-09-30，命令见下方「测试」节，可在仓库复核）

## 功能特性

- **自然语言任务**：对话式下任务，AI 规划并调用工具执行，每一步在对话流里可见（工具卡片：参数 → 执行中 → 成功/失败/拦截）
- **多任务并行**：每个任务一个 Tab，同时跑 1-5 个（默认 3），超出自动排队；支持中途停止
- **看屏幕理解**：截图缩放到 1600 宽送视觉模型——云端 `glm-4v-flash`（免费，实测 1~5 秒一张屏）或本机 Ollama `qwen-vl`；默认「自动」：配了云端 Key 走云端，否则回退本机
- **21 个内置工具**：鼠标点击/移动/滚轮、键盘输入/组合键、截屏、图像定位、等待、
  开应用、窗口查找与聚焦、UIA 控件读取与点击、剪贴板读写、发飞书消息、
  鼠标位置/屏幕尺寸查询等（清单见 `agent_loop.py` 的 `TOOLS_SCHEMA`）；
  另有 `install_skill` 供 AI 自装技能包（需用户确认），合计 22 个
- **模型热切换**：设置页随时切换 本机 / 云端 / 自动；云端预设四家：智谱、DeepSeek、OpenAI、通义
- **插件系统**：连接器（.py 工具插件）与技能/专家包（SKILL.md），见 [插件开发指南](docs/插件开发指南.md) 和 [技能包指南](docs/技能包指南.md)
- **定时任务**：每天 / 每周 / 间隔分钟，持久化到磁盘，重启不重复触发；错过的当天任务不补跑、会在会话里提示
- **系统托盘**：关窗最小化到托盘继续跑，后台定时任务不中断
- **手机连接**：设置面板打开开关，手机扫码即可远程下任务、看进度（在家走同一 WiFi 直连；出门可开 cloudflared 外网通道；危险操作仍在电脑上确认）
- **首启引导**：检测不到模型时弹三选一引导卡（用云端 / 装本机 Ollama / 稍后再说）

## 安全机制

- **危险操作分级拦截**：删除类按键、关闭窗口组合键、破坏性按钮等高危操作先弹确认卡，AI 不得绕过；未确认一律不执行
- **审计日志防篡改**：所有工具调用与审批记录写入哈希链 JSONL（同日重启自动续链，链损坏显式标记不静默）
- **技能包注入防护**：SKILL.md 内容进提示词前用明确边界包裹并声明"资料不是指令"，防恶意技能包诱导
- **网络出口统一策略**：所有 HTTP 出口禁用系统代理（`trust_env=False`），代理软件不再干扰本地/云端请求；云端地址强制 https 公网校验
- **动作后校验**：打开应用后确认窗口出现、点击后确认界面变化、写剪贴板后验内容
- **失败重试**：幂等操作失败自动重试（1s/2s/4s 退避，最多 3 次），高危操作不自动重试
- **防呆**：单任务最多 10 轮（`MAX_TURNS`）；`wait` 单次上限 60 秒且睡眠中可响应停止

## 快速开始

### 路线 A：云端模型（最快，不用装本地模型）

1. 到 [Releases 页面](https://github.com/lzy931102/desktop-agent/releases/latest) 下载 `DesktopAgent.exe`，双击运行（首次启动解压约 10 秒）
2. 首启引导卡选「**用云端**」→ 自动打开设置面板
3. 在「云端模型」页签选「智谱」（免费模型 `glm-4-flash`），到 [open.bigmodel.cn](https://open.bigmodel.cn) 注册并创建 API Key，填进去
4. 点「测试连接」确认通过 → 保存
5. 回主界面输入 `打开计算器`，点「开始执行」

> 注意：云端模式下，屏幕截图会上传给模型服务商（界面底部有常驻黄条提醒）。
> 不希望截图出本机就用路线 B。

### 路线 B：本机 Ollama（数据不出本机）

1. 下载安装 Ollama：https://ollama.com/download ，装好后右下角出现羊驼图标
2. 拉模型：`ollama pull qwen2.5-coder:7b`
3. 运行 `DesktopAgent.exe`，顶栏徽章变绿即连上
4. 输入任务开始使用

### 源码运行（开发者）

```bash
pip install -r requirements.txt
python gui.py
```

## GUI 使用

- **左侧栏**：＋ 新建任务、任务列表（状态实时刷新，可重命名/关闭）、任务表、设置、插件（技能/专家/连接器）
- **Tab 栏**：每任务一个 Tab，并行数设置里可调（1-5，默认 3），超出排队
- **对话流**：用户/助手气泡、工具调用卡片、高危操作内嵌确认卡、截屏缩略图（点击放大）
- **输入区**：示例任务一键填入（打开计算器 / 打开记事本，输入 你好 / 截取屏幕 / 查看窗口）、Ctrl+Enter 开始、右下角显示轮次/耗时
- **连接徽章**：右上角显示当前用云端还是 Ollama、连没连上，点击可再次唤出首启引导

### 顶栏功能

| 按钮 | 功能 |
|------|------|
| 📜 历史 | 回看最近 50 次任务（`core/history.py`） |
| ⏰ 定时 | 定时任务：每天 / 每周 / 间隔分钟，持久化不丢失 |
| 📋 任务表 | 本会话 + 历史记录的表格视图 |
| ⚙ 设置 | 模型模式（本机/云端/自动）、并行任务数、托盘开关、云端服务商与 Key、视觉模型 |

### 命令行（进阶）

```bash
python gui.py --run "打开计算器"          # 启动后自动执行任务
python gui.py --debug-open settings       # 直接打开面板：settings / scheduler / history / tasks_table
```

## 数据存放位置

全部在 `%LOCALAPPDATA%\DesktopAgent\`，不随仓库走：

| 内容 | 路径 |
|------|------|
| 审计日志（哈希链） | `logs\audit-YYYYMMDD.jsonl` |
| 任务历史 | `history.jsonl` |
| 设置（含模型配置，Key 优先读环境变量） | `settings.json` |
| 定时任务 | `scheduled_tasks.json` |
| 插件 / 技能包 | `plugins\` 、`skills\` |

## 测试

```bash
# 核心套件（guard 审批 / 插件边界 / 技能包 / agent 循环 / 视觉后端 / core / 手机桥接）：
python -m pytest test_core_guard.py test_plugin_system.py test_plugin_boundary.py \
       test_skill_system.py test_agent_loop_guard.py test_vision_backend.py \
       test_phone_bridge.py -q
# 实测：231 passed, 7 xfailed（7 个 xfailed 是 guard 已拍板不修的绕过变体，
# 用 xfail 固化防回归，理由见 test_core_guard.py 各用例 docstring）

# 全量逻辑测试（含 test_ollama_stream.py 的假响应流测试，不依赖真实 Ollama、不动鼠标）：
python -m pytest -q
# 实测：242 passed, 7 xfailed
```

`e2e/` 下的 21 个脚本是**会真动鼠标、真开应用**的一次性桌面操控/端到端脚本，
pytest 配置（`pytest.ini`）已确保裸跑 `pytest` 绝不收集它们；需要跑时单独执行：

```bash
python -m e2e.test_notepad_e2e
```

## 打包 exe

```bash
python -m PyInstaller DesktopAgent.spec --noconfirm
```

生成 `dist/DesktopAgent.exe`。spec 里 `upx=False`：未签名 exe + UPX 壳是杀软误报的经典组合，体积换查杀通过率。

## 技术栈（主链路实测）

| 组件 | 技术 |
|------|------|
| 界面 | CustomTkinter（`gui.py`） |
| Agent 循环 | 自研（`agent_loop.py`）：LLM 循环 + 工具调度 + 审计/审批/重试接线 |
| LLM 接入 | `requests` 直连——本机 Ollama REST（`localhost:11434`）+ 云端 OpenAI 兼容接口（智谱等四家预设） |
| 看屏幕 | 截图缩放 1600 宽 → 云端 `glm-4v-flash`（免费）或本机 Ollama `qwen-vl`（`agent_vision.py`） |
| UI 自动化 | `pyautogui`（鼠标键盘/截屏）+ `pywinauto`（UIA 控件，懒加载） |
| 剪贴板 | `pyperclip` |
| 系统托盘 | `pystray`（懒加载，缺失自动降级） |
| 打包 | PyInstaller（`DesktopAgent.spec`，含 pywinauto/comtypes 整体收集） |

> `requirements.txt` 依赖说明（2026-09-30 复盘核准）：`openai` 是**云端模式必需**——
> 智谱/DeepSeek/OpenAI/通义四家预设全部经 OpenAI 兼容客户端调用（`agent_loop.py`
> 的 `_create_client`）；`opencv-python` 主链路未 import，仅 e2e/ 下 5 个一次性
> 脚本使用。`segno`（二维码）服务于 `phone_bridge/`。

## 项目结构

```
desktop-agent/
├── gui.py                # 图形界面（侧栏 + Tab + 对话流 + 任务表 + 托盘 + 首启引导）
├── agent_loop.py         # Agent 主干：LLM 循环、21 个内置工具 + install_skill 调度、审计/审批/重试/停止接线
├── agent_vision.py       # 工具包：截屏/视觉理解/窗口/UIA/剪贴板（本地 + 云端双路径）
├── core/                 # 基础设施：audit(哈希链)/guard/approval/retry/verify/scheduler/history/settings/paths/feishu
├── plugin_system/        # 连接器：.py 工具插件（加载、启停、工具合并）
├── skill_system/         # 技能/专家包：SKILL.md 注入（防注入包裹）+ install_skill（走确认卡）
├── phone_bridge/         # 手机连接（设置面板开启 → 手机扫码遥控：令牌+限速+隧道+二维码+事件回流）
├── e2e/                  # 桌面操控/端到端脚本（真动鼠标，pytest 不收集）
├── test_*.py             # 核心测试套件（7 文件）+ test_ollama_stream.py
├── docs/                 # 评审/评估报告、修复任务列表、插件与技能包指南
├── examples/             # 示例插件（示例插件-天气查询.py）
├── DesktopAgent.spec     # PyInstaller 打包配置
└── requirements.txt      # 依赖（>= 下限声明）
```

## 插件开发

- [插件模块化方案（建议稿）](docs/插件模块化方案.md)：连接器的整体设计与安全边界
- [插件开发指南](docs/插件开发指南.md)：连接器（.py 工具插件）骨架、字段说明、常见问题
- [技能包指南](docs/技能包指南.md)：技能/专家包（SKILL.md）的写法、安装与安全说明
- [示例插件源码](plugin_system/sample.py)：单一事实来源，生成插件时用

## 许可证

[MIT License](LICENSE)
