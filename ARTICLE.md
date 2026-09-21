# 从零构建 Windows 桌面操作 Agent：架构设计与实战经验

## 1. 项目背景

### 1.1 为什么做这个项目

在 AI 快速发展的今天，让 AI 不仅能"思考"，还能"操作"电脑，是一个极具挑战性的方向。传统的 RPA（机器人流程自动化）工具虽然能自动化操作，但缺乏智能决策能力；而大语言模型虽然能理解任务，却无法直接操作桌面。

本项目的目标是**构建一个能在真实 Windows 桌面环境下自主完成复杂任务的 AI Agent**，融合视觉感知、规则决策、安全防护和记忆持久化能力。

### 1.2 项目目标

- **感知能力**：实时截屏、OCR 文字识别、图像识别
- **执行能力**：鼠标点击、键盘输入、窗口管理
- **决策能力**：任务规划、状态跟踪、异常处理
- **安全能力**：危险操作拦截、操作日志记录
- **记忆能力**：执行状态持久化、任务管理

### 1.3 解决什么问题

传统自动化工具的痛点：
- **脆弱性**：依赖固定坐标，界面变化就失效
- **无智能**：无法处理异常情况
- **不安全**：没有危险操作拦截机制
- **难维护**：脚本难以复用和扩展

本项目通过模块化架构和视觉感知，解决上述问题。

---

## 2. 架构设计

### 2.1 七层模块架构

```
┌─────────────────────────────────────────────────────────────┐
│                    调度层 Orchestrator                        │
│        感知 → 决策 → 安全检查 → 执行 → 验证 → 记忆            │
└───────┬─────────┬─────────┬─────────┬─────────┬─────────────┘
        │         │         │         │         │
   ┌────▼───┐ ┌───▼────┐ ┌──▼─────┐ ┌─▼──────┐ ┌▼────────┐
   │ 感知层 │ │ 决策层 │ │ 执行层 │ │ 验证层 │ │ 记忆层  │
   │Percept.│ │ Brain  │ │Actuator│ │Verifier│ │ Memory  │
   └────┬───┘ └───┬────┘ └──┬─────┘ └─┬──────┘ └┬────────┘
        │         │         │         │         │
   ┌────▼───┐ ┌───▼────┐ ┌──▼─────┐ ┌─▼──────┐ ┌▼────────┐
   │截屏/OCR│ │规则版  │ │鼠标键盘│ │截图diff│ │JSON存储 │
   │找图    │ │决策    │ │pyautogui│ │断言   │ │         │
   └────────┘ └────────┘ └────────┘ └────────┘ └─────────┘
                                 │
                           ┌─────▼─────┐
                           │  安全层   │
                           │ Security  │
                           └───────────┘
```

### 2.2 模块职责

| 模块 | 文件 | 职责 |
|------|------|------|
| **感知层** | `perception_v1.py` | 截屏、OCR 文字识别、UI 元素获取、图像查找 |
| **决策层** | `brain_rule.py` | 目标解析、任务规划、状态更新、进度跟踪 |
| **执行层** | `actuator.py` | 鼠标点击、键盘输入、快捷键、窗口操作 |
| **验证层** | `verifier.py` | 动作验证、文字断言、图像断言、等待 |
| **记忆层** | `memory_json.py` | JSON 持久化、执行状态记录、任务管理 |
| **安全层** | `security.py` | 审批门控、危险动作检测、操作日志 |
| **调度层** | `orchestrator.py` | 主循环、模块协调、状态管理 |

### 2.3 模块间协作流程

```
用户任务 → 调度层
    ↓
感知层：截屏 + OCR → 屏幕状态
    ↓
决策层：屏幕状态 + 目标 → 动作
    ↓
安全层：动作检查 → 是否危险
    ↓
执行层：执行动作 → 结果
    ↓
验证层：验证结果 → 成功/失败
    ↓
记忆层：记录执行状态
    ↓
返回调度层，循环直到任务完成
```

---

## 3. 关键技术

### 3.1 截屏：mss vs pyautogui

| 技术 | 延迟 | 精度 | 适用场景 |
|------|------|------|----------|
| **mss** | 17ms | 像素级 | 实时截屏、游戏 |
| **pyautogui** | 100ms+ | 像素级 | 简单截屏 |

**选择 mss 的原因**：
- 延迟低（17ms vs 100ms+）
- 支持多显示器
- 内存占用小

```python
import mss
with mss.mss() as sct:
    screenshot = sct.grab(monitor)
```

### 3.2 OCR：Tesseract 中英文

**OCR 流程**：
1. 截取目标区域
2. 灰度转换
3. 二值化处理
4. 3x 放大增强
5. pytesseract 识别

```python
import pytesseract
from PIL import Image

def ocr_region(image, region):
    x, y, w, h = region
    roi = image[y:y+h, x:x+w]
    # 灰度 + 二值化
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    # 放大增强
    enlarged = cv2.resize(binary, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
    # OCR 识别
    text = pytesseract.image_to_string(enlarged, lang='chi_sim+eng')
    return text.strip()
```

### 3.3 图像识别：OpenCV HSV

**HSV 颜色检测**：
- 将 RGB 转换为 HSV 空间
- 设置颜色阈值范围
- 生成掩码图
- 查找轮廓定位目标

```python
import cv2
import numpy as np

def detect_color(image, color='red'):
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    
    if color == 'red':
        # 红色双阈值（0-10 和 170-180）
        lower1 = np.array([0, 120, 70])
        upper1 = np.array([10, 255, 255])
        lower2 = np.array([170, 120, 70])
        upper2 = np.array([180, 255, 255])
        
        mask1 = cv2.inRange(hsv, lower1, upper1)
        mask2 = cv2.inRange(hsv, lower2, upper2)
        mask = mask1 + mask2
    
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    return contours
```

### 3.4 鼠标：ctypes vs pyautogui

| 技术 | 速度 | 稳定性 | 适用场景 |
|------|------|--------|----------|
| **ctypes** | 快 | 高 | 游戏、实时操作 |
| **pyautogui** | 慢 | 中 | 通用自动化 |

**ctypes 实现**：
```python
import ctypes

def click(x, y):
    ctypes.windll.user32.SetCursorPos(x, y)
    ctypes.windll.user32.mouse_event(0x0002, 0, 0, 0, 0)  # 左键按下
    ctypes.windll.user32.mouse_event(0x0004, 0, 0, 0, 0)  # 左键抬起
```

### 3.5 COM：WPS/Office 自动化

**COM 接口优势**：
- 快速、稳定、精确
- 数据级操作（不依赖坐标）
- 支持复杂操作（公式、格式）

```python
import win32com.client

# WPS Excel 自动化
wps = win32com.client.Dispatch("Ket.Application")
wps.Visible = True
wb = wps.Workbooks.Open(r"C:\test.xlsx")
ws = wb.Sheets(1)
ws.Cells(1, 1).Value = "Hello"
wb.Save()
wb.Close()
wps.Quit()
```

**COM 类名**：
- WPS: `Ket.Application`, `KWps.Application`, `KWpp.Application`
- Office: `Excel.Application`, `Word.Application`, `PowerPoint.Application`

### 3.6 UIA：Windows 原生应用

**UIA（UI Automation）**：
- Windows 原生 UI 自动化框架
- 支持控件树遍历
- 适合 UWP、WinForms 应用

```python
import uiautomation as uia

# 查找窗口
window = uia.WindowControl(Name="记事本")
# 查找编辑框
edit = window.EditControl()
# 输入文本
edit.SetValue("Hello World")
```

---

## 4. 两种执行方式

### 4.1 COM（快、稳、需支持）

| 项目 | 说明 |
|------|------|
| **适用软件** | WPS、Office、Outlook、CAD、Photoshop 等支持 COM 的软件 |
| **优点** | 快、稳、精确（数据级操作） |
| **缺点** | 需要软件支持 COM 注册 |
| **典型耗时** | 4-5s（Excel E2E） |

**COM 类名示例**：
- WPS: `Ket.Application`
- Excel: `Excel.Application`
- Outlook: `Outlook.Application`

### 4.2 pyautogui（通用、慢、依赖坐标）

| 项目 | 说明 |
|------|------|
| **适用软件** | 游戏、浏览器、UWP、不支持 COM 的软件 |
| **优点** | 通用，任何软件都能操作 |
| **缺点** | 慢、依赖坐标、不稳定 |
| **典型耗时** | 15-25s（GUI 操作） |

### 4.3 选择原则

```
优先级：COM > pyautogui
```

| 场景 | 选择 | 原因 |
|------|------|------|
| 办公软件数据操作 | COM | 快、稳、精确 |
| 游戏/像素操作 | pyautogui | 通用、可视化 |
| 不支持 COM 的软件 | pyautogui | 兜底方案 |

**实际案例**：

| 测试项 | 方法 | 耗时 |
|--------|------|------|
| Excel E2E | COM | 4.37s |
| Word E2E | COM | 4.64s |
| PPT E2E | COM | 6.41s |
| 文件夹操作 | pyautogui | 24.95s |

---

## 5. AI 决策接入

### 5.1 规则版 vs AI 版

| 维度 | 规则版 | AI 版 |
|------|--------|-------|
| **决策方式** | 预定义规则 | 自然语言理解 |
| **灵活性** | 低 | 高 |
| **开发成本** | 低 | 中 |
| **适用场景** | 固定任务 | 动态任务 |

### 5.2 LM Studio + 本地模型

**为什么选择本地模型**：
- **隐私**：数据不离开本地
- **延迟**：无网络请求
- **成本**：无 API 费用
- **可控**：可定制模型

**模型选择**：`qwen2.5-coder-7b-instruct-q4_k_m.gguf`
- 7B 参数，平衡性能和效果
- Q4 量化，适合本地运行
- 代码理解能力强

### 5.3 屏幕描述 + 自然语言任务 → 动作 JSON

**工作流程**：
```
屏幕描述 + 自然语言任务
    ↓
LM Studio API (localhost:1234)
    ↓
结构化动作 JSON
    ↓
执行层执行
```

**示例**：
```python
# 输入
screen_description = "当前屏幕显示Windows桌面，任务栏在底部"
goal = "打开计算器"

# AI 输出
{"action": "click", "target": "开始菜单图标", "text": ""}
```

**测试结果**：
- 打开计算器：✓
- 打开记事本，输入 Hello：✓
- 打开浏览器，搜索 Python：✓
- **准确率：100%**

---

## 6. 测试方法

### 6.1 测试类型

| 类型 | 说明 | 工具 |
|------|------|------|
| **单元测试** | 单个模块功能测试 | pytest |
| **集成测试** | 模块间协作测试 | pytest |
| **端到端测试** | 完整任务流程测试 | 自定义脚本 |
| **回归测试** | 修改后验证现有功能 | 全量测试 |

### 6.2 16 个测试清单

| 编号 | 测试项 | 结果 |
|------|--------|------|
| T1 | 移动靶预判 | ✅ 93.9% |
| T2 | 多靶子决策 | ✅ 100% |
| T3 | 弹窗干扰 | ✅ 10/10 |
| T4 | 分辨率变化 | ✅ 6/6 |
| T5 | 记事本 E2E | ✅ 5/5 |
| T6 | 计算器 E2E | ✅ 100% |
| T7 | 浏览器 E2E | ✅ 100% |
| T8 | 连续 10 局稳定性 | ✅ 100% |
| T9 | 异常恢复 | ✅ 4/4 |
| T10 | 安全拦截 | ✅ 14/14 |
| T11 | 任务链 | ✅ 11/11 |
| P2-1 | Excel（WPS） | ✅ 4.37s |
| P2-2 | Word（WPS） | ✅ 4.64s |
| P2-3 | PPT（WPS） | ✅ 6.41s |
| P3 | 文件夹操作 | ✅ 24.95s |
| P4 | AI 决策 | ✅ 100% |

### 6.3 测试结果汇总

| 指标 | 数值 |
|------|------|
| 测试总数 | 16 |
| 通过率 | 100% |
| 平均耗时 | 12.8s |
| 最快 | 4.37s（Excel） |
| 最慢 | 24.95s（文件夹操作） |

---

## 7. 经验总结

### 7.1 踩过的坑

**编码问题**：
- Windows 控制台默认 GBK 编码
- 解决：使用 ASCII 字符替代 Unicode 符号

**DPI 缩放**：
- 高 DPI 屏幕坐标偏移
- 解决：使用 `ctypes.windll.user32.SetProcessDPIAware()`

**COM 启动**：
- COM 对象未正确释放
- 解决：使用 `try-finally` 确保 `Quit()` 执行

**pyautogui 中文输入**：
- pyautogui 不支持中文输入
- 解决：使用剪贴板（pyperclip）绕过

### 7.2 有效的做法

**文件化**：
- 每个模块都有 README
- 测试结果保存为 JSON
- 项目状态实时更新

**Git 管理**：
- 每个功能一个 commit
- 清晰的提交信息
- 定期推送备份

**分步验证**：
- 先单元测试，再集成测试
- 小步快跑，及时验证
- 失败立即排查

### 7.3 教训

**上下文太长**：
- 单次会话上下文过长导致性能下降
- 教训：定期清理上下文，拆分任务

**脚本丢失**：
- 临时脚本未及时保存
- 教训：重要脚本立即 Git 提交

**过度设计**：
- 早期设计过于复杂
- 教训：先跑通闭环，再优化

---

## 8. 后续方向

### 8.1 多模态升级

- 集成 GPT-4V 实现视觉理解决策
- 支持截图理解 + 自然语言交互
- 实现"看图说话"能力

### 8.2 更多场景

- 办公自动化（邮件、日程、会议）
- 数据处理（Excel、数据库）
- 文件管理（批量重命名、整理）
- 网页操作（表单填写、数据抓取）

### 8.3 产品化

- Web UI 界面
- 任务录制和回放
- 插件系统
- 企业级部署

### 8.4 开源

- 代码开源
- 社区共建
- 文档完善

---

## 9. 参考项目

### 9.1 核心参考

| 项目 | 说明 | 启发 |
|------|------|------|
| **Self-Operating Computer** | AI 操作电脑 | 视觉感知 + 动作执行 |
| **je-auto-control** | 自动化控制 | 模块化架构 |
| **OpenWorker** | 工作自动化 | 任务调度 |
| **GhostDesk** | 桌面自动化 | COM 接口 |
| **ScreenAgent** | 屏幕 Agent | 视觉决策 |

### 9.2 技术栈参考

| 项目 | 技术点 |
|------|--------|
| **ok-script** | 脚本录制 |
| **uia-agent** | UIA 自动化 |
| **peekaboowin** | 窗口探测 |
| **winagent-lite** | 轻量 Agent |
| **qwen_autogui** | Qwen + pyautogui |

---

## 10. 总结

本项目通过七层模块架构，构建了一个完整的 Windows 桌面操作 Agent。核心成果：

- **16 项测试全部通过**，覆盖视觉感知、自动化执行、异常恢复、安全拦截等场景
- **两种执行方式**（COM + pyautogui），适应不同软件
- **AI 决策接入**，支持自然语言指令
- **模块化设计**，易于扩展和维护

项目证明：**AI Agent 可以在真实桌面环境下自主完成复杂任务**。

---

**项目状态**：16 项测试全部通过，核心功能稳定可用

**最后更新**：2026-09-21