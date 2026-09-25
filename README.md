# Desktop Agent

![Screenshot](docs/screenshot.png)

![Python](https://img.shields.io/badge/Python-3.8+-blue)
![License](https://img.shields.io/badge/License-MIT-green)
![Tests](https://img.shields.io/badge/Tests-27%20passed-brightgreen)
![Platform](https://img.shields.io/badge/Platform-Windows-lightgrey)

一个模块化的 Windows 桌面操作 Agent，支持截屏感知、OCR 识别、图像检测、鼠标点击、键盘输入等自动化操作。

## 功能特性

- **截屏感知** - 使用 mss + OpenCV 实时捕获屏幕
- **OCR 文字识别** - Tesseract 中英文识别
- **图像识别** - HSV 颜色检测定位目标
- **多模态理解** - Qwen2.5-VL 视觉语言模型
- **图像定位** - pyautogui.locateOnScreen 模板匹配
- **鼠标控制** - ctypes 精确点击
- **键盘输入** - pyautogui 模拟按键
- **剪贴板操作** - pyperclip 复制粘贴
- **COM 接口** - WPS/Office 自动化
- **UIA 元素定位** - Windows UI Automation
- **安全拦截** - 分级权限 + 白名单
- **异常恢复** - 自动错误处理

## 架构

```
┌─────────────────────────────────────────────────────────┐
│                    Orchestrator (调度层)                  │
├─────────────────────────────────────────────────────────┤
│  Perception   │   Brain    │  Actuator  │   Verifier    │
│  (感知层)      │  (决策层)   │  (执行层)   │   (验证层)    │
├─────────────────────────────────────────────────────────┤
│              Memory (记忆层)    │   Security (安全层)     │
└─────────────────────────────────────────────────────────┘
```

### 模块说明

| 模块 | 职责 |
|------|------|
| Perception | 截屏、OCR、图像识别 |
| Brain | 任务规划、决策推理 |
| Actuator | 鼠标、键盘、COM 操作 |
| Verifier | 结果验证、状态检查 |
| Memory | 文件存储、任务状态 |
| Security | 权限控制、安全拦截 |
| Orchestrator | 模块协调、任务调度 |

## 快速开始

### 安装依赖

```bash
pip install -r requirements.txt
```

额外依赖（可选）：

```bash
pip install mss pytesseract pyperclip pywin32 uiautomation
```

### 运行测试

```bash
# 移动靶测试
python test_moving_target.py

# 记事本 E2E
python test_notepad_e2e.py

# 计算器 E2E
python test_calculator_e2e.py

# 浏览器 E2E
python test_browser_e2e.py
```

## 下载与安装

### 下载

1. 打开 [Releases 页面](https://github.com/lzy931102/desktop-agent/releases)
2. 找到最新版本（如 v2.0.1）
3. 在 "Assets" 区域，点击 `DesktopAgent.exe` 下载
4. 下载完成后，双击运行

> 💡 如果点击下载链接后页面空白，是正常的——文件会自动下载，去浏览器"下载"列表查看。

### 安装 Ollama

1. 下载 Ollama：https://ollama.com/download
2. 安装并启动
3. 拉取模型：ollama pull qwen2.5-coder:7b

### 运行

双击 `DesktopAgent.exe`，输入任务，点击"开始执行"。

## GUI 使用

### 启动 GUI

```bash
python gui.py
```

双击 `dist/DesktopAgent.exe` 亦可。

### 界面说明

1. **连接徽章**：右上角实时显示 Ollama 连接状态与视觉能力
2. **状态卡**：当前状态、轮次、耗时，成功/失败分色
3. **输入框**：自然语言描述任务，Ctrl+Enter 快速开始
4. **示例任务**：一键填入常用任务
5. **执行记录**：带时间戳的彩色日志
6. **⏹ 停止**：执行中可随时叫停

### 顶栏功能

| 按钮 | 功能 |
|------|------|
| 📜 历史 | 回看最近 50 次任务（状态/耗时/结果） |
| ⏰ 定时 | 定时任务：每天 / 每周 / 间隔分钟，到点自动执行，持久化不丢失 |
| ⚙ 设置 | 切换本地模型（读取 Ollama 列表，保存后立即生效）、托盘开关 |

### 安全机制

- **高危操作确认**：删除类按键、关闭窗口组合键、破坏性按钮等操作会先弹窗征求同意
- **审计日志**：所有工具调用与审批记录写入 `%LOCALAPPDATA%\DesktopAgent\logs\`（哈希链防篡改）
- **失败重试**：幂等操作失败自动重试（1s/2s/4s 退避），高危操作失败不自动重试
- **动作后校验**：打开应用后确认窗口出现、点击后确认界面变化
- **托盘驻留**：关闭窗口最小化到托盘，后台定时任务继续运行

### 示例任务

- 打开计算器
- 打开记事本，输入 Hello
- 看看屏幕上现在有哪些应用窗口
- 在记事本里用格式菜单打开字体设置

### 打包 exe

```bash
python -m PyInstaller DesktopAgent.spec --noconfirm
```

打包后生成：`dist/DesktopAgent.exe`

## 测试结果

| 编号 | 测试项 | 结果 |
|------|--------|------|
| T1 | 移动靶预判 | ✅ |
| T2 | 多靶子决策 | ✅ 100% |
| T3 | 弹窗干扰 | ✅ 10/10 |
| T4 | 分辨率变化 | ✅ 6/6 |
| T5 | 记事本 E2E | ✅ |
| T6 | 计算器 E2E | ✅ |
| T7 | 浏览器 E2E | ✅ |
| T8 | 连续 10 局稳定性 | ✅ |
| T9 | 异常恢复 | ✅ 4/4 |
| T10 | 安全拦截 | ✅ 14/14 |
| T11 | 任务链 | ✅ 11/11 |
| P2-1 | Excel（WPS） | ✅ 7.89s |
| P2-2 | Word（WPS） | ✅ 11.29s |
| P2-3 | PPT（WPS） | ✅ 9.28s |
| P2-1 | Excel（WPS） | ✅ 4.37s |
| P2-2 | Word（WPS） | ✅ 4.64s |
| P2-3 | PPT（WPS） | ✅ 6.41s |
| P3 | 文件夹操作 | ✅ 24.95s |
| P4 | AI 决策（LM Studio） | ✅ 18.56s |
| P7 | 批量文件（GUI） | ✅ 15.82s |
| P8 | 多模态升级 | ✅ 4/4 |

## 技术栈

| 组件 | 技术选择 |
|------|----------|
| 截屏 | mss |
| OCR | Tesseract |
| 图像处理 | OpenCV |
| 多模态 | Qwen2.5-VL |
| 图像定位 | pyautogui.locateOnScreen |
| 鼠标控制 | ctypes |
| 键盘模拟 | pyautogui |
| 剪贴板 | pyperclip |
| COM 自动化 | pywin32 |
| UI 自动化 | uiautomation |

## 项目结构

```
desktop-agent/
├── agent/                    # 核心模块
│   ├── modules/             # 功能模块
│   │   ├── perception/      # 感知层
│   │   ├── cognition/       # 认知层
│   │   └── ...
│   ├── main.py              # 入口
│   └── scheduler.py         # 调度器
├── test_*.py                # 测试文件
├── requirements.txt         # 依赖
├── LICENSE                  # MIT License
└── README.md                # 项目说明
```

## 参考项目

- [Self-Operating Computer](https://github.com/OpenAdenAI/self-operating-computer)
- [je-auto-control](https://github.com/jeauto-control/je-auto-control)
- [OpenWorker](https://github.com/OpenWorkerAI/OpenWorker)
- [GhostDesk](https://github.com/GhostDesk/GhostDesk)
- [ScreenAgent](https://github.com/niuzaishen/ScreenAgent)

## 许可证

[MIT License](LICENSE)
