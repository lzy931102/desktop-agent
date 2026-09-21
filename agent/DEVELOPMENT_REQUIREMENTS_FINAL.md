# 电脑操作AGENT开发需求文档（合并优化版）

> 基于双方讨论整合，作为后续开发的统一依据。

---

## 一、项目定位与目标

### 1.1 定位
模块化、可逐步升级的电脑操作AGENT。初期做"固定流程自动化"，逐步升级为"能感知、能决策、能验证、能自我改进"的自主Agent。

### 1.2 核心原则

| 原则 | 说明 |
|------|------|
| **积木式架构** | 每个模块职责单一、接口统一，换实现不改调用方 |
| **接口先行** | 先定义ScreenState和Action的统一数据结构，再写各模块 |
| **先规则后AI** | 决策层先用规则版跑通闭环，再接AI |
| **动作结构化** | 模型输出"目标描述"，不输出坐标，由执行层查表拿坐标 |
| **模型无关** | 决策层不绑定特定AI，通过统一接口切换模型 |
| **多层fallback** | 定位失败自动降级（UIA→OCR→图像→VLM→锚点→自愈） |
| **验证闭环** | 每个动作都要验证成功 |
| **安全默认开启** | 涉及文件、网络、危险操作时，必须有审批门控 |

---

## 二、总体架构

```
┌─────────────────────────────────────────────────────────────┐
│                    调度层 Orchestrator                        │
│        感知 → 决策 → 安全检查 → 执行 → 验证 → 学习            │
└───────┬─────────┬─────────┬─────────┬─────────┬─────────────┘
        │         │         │         │         │
   ┌────▼───┐ ┌───▼────┐ ┌──▼─────┐ ┌─▼──────┐ ┌▼────────┐
   │ 感知层 │ │ 决策层 │ │ 执行层 │ │ 验证层 │ │ 记忆层  │
   │Percept.│ │ Brain  │ │Actuator│ │Verifier│ │ Memory  │
   └────┬───┘ └───┬────┘ └──┬─────┘ └─┬──────┘ └┬────────┘
        │         │         │         │         │
   ┌────▼───┐ ┌───▼────┐ ┌──▼─────┐ ┌─▼──────┐ ┌▼────────┐
   │截屏/OCR│ │规则/AI │ │鼠标键盘│ │断言    │ │JSON/DB  │
   │UIA/找图│ │任务规划│ │找图点击│ │截图diff│ │上下文   │
   └────────┘ └────────┘ └────────┘ └────────┘ └────────┘
                              │
                        ┌─────▼─────┐
                        │  工具层   │
                        │  Tools    │
                        └───────────┘
                              │
                        ┌─────▼─────┐
                        │  安全层   │
                        │ Security  │
                        └───────────┘
```

---

## 三、统一数据结构（最先定义）

```python
from dataclasses import dataclass, field
from typing import Optional

@dataclass
class ScreenState:
    """屏幕状态 - 感知层输出"""
    screenshot: str                          # base64编码截图
    screenshot_path: str = ""                # 截图文件路径
    texts: list[dict] = field(default_factory=list)      # OCR结果
    elements: list[dict] = field(default_factory=list)   # UIA/找图元素
    active_window: dict = field(default_factory=dict)    # 当前窗口信息

@dataclass
class Action:
    """动作指令 - 决策层输出"""
    action: str                              # click/type/select/expand/key/wait/done
    target: Optional[dict] = None            # 目标描述（文本/元素引用，非坐标）
    text: Optional[str] = None               # 输入文字
    keys: Optional[list[str]] = None         # 快捷键组合
    condition: Optional[dict] = None         # 等待条件

# 标准动作类型
ACTIONS = {
    "click":    "点击目标",           # target: {"text": "确定"} 或 {"ref": "hwnd:12345"}
    "type":     "输入文字",           # text: "hello"
    "select":   "选择元素",           # target: {"ref": "hwnd:12345"}
    "expand":   "展开元素",           # target: {...}
    "key":      "按快捷键",           # keys: ["ctrl", "c"]
    "wait":     "等待条件满足",       # condition: {"text": "加载完成"}
    "done":     "任务完成"
}

# 模块接口
class Perception:
    def capture(self) -> ScreenState: ...

class Brain:
    def decide(self, state: ScreenState, goal: str) -> Action: ...

class Actuator:
    def execute(self, action: Action) -> bool: ...

class Verifier:
    def verify(self, before: ScreenState, after: ScreenState, action: Action) -> bool: ...

class Memory:
    def save(self, key: str, value) -> None: ...
    def load(self, key: str): ...

class Security:
    def check(self, action: Action) -> bool: ...

class Tools:
    def read_file(self, path: str) -> str: ...
    def write_file(self, path: str, content: str) -> None: ...
    def http_get(self, url: str) -> dict: ...
    def clipboard_read(self) -> str: ...
    def clipboard_write(self, text: str) -> None: ...
```

---

## 四、模块规格

### 模块1：感知层 Perception

**职责**：把屏幕变成Agent能理解的结构化信息。

| 子能力 | 优先级 | 说明 |
|--------|--------|------|
| 截屏 | P0 | pyautogui / mss |
| 模板匹配找图 | P0 | OpenCV |
| OCR文字识别+坐标映射 | P0 | 借鉴Self-Operating Computer |
| 分辨率自适应模板匹配 | P1 | 借鉴ok-script的COCO素材管理 |
| UIA可访问性树 | P1 | 借鉴uia-agent |
| UIA+OCR双通道融合 | P2 | 借鉴ScreenAgent，IoU去重、坐标平均 |

**统一输出格式**：
```json
{
  "screenshot": "base64...",
  "texts": [{"text": "确定", "bbox": [100,200,160,230], "confidence": 0.98}],
  "elements": [{"type": "button", "name": "提交", "bbox": [...], "ref": "hwnd:12345"}],
  "active_window": {"title": "...", "hwnd": 12345}
}
```

**借鉴来源**：Self-Operating Computer、ok-script、ScreenAgent、uia-agent

---

### 模块2：决策层 Brain

**职责**：根据感知结果和任务目标，输出下一步动作。

| 子能力 | 优先级 | 说明 |
|--------|--------|------|
| 规则版决策（if-else） | P0 | 先跑通闭环 |
| 结构化Action定义 | P0 | 借鉴uia-agent的7种动作 |
| 坐标归一化映射 | P1 | 借鉴qwen_autogui，1000x1000→实际分辨率 |
| 模型无关接口 | P1 | 借鉴OpenWorker，统一API |
| AI推理（多模态） | P1 | 接GPT-4V/Qwen-VL/本地VLM |
| 任务规划/分解 | P2 | 自然语言目标→步骤JSON |

**标准动作类型**：
```json
{"action": "click",   "target": {"text": "确定"}}
{"action": "type",    "text": "hello"}
{"action": "select",  "target": {"ref": "hwnd:12345"}}
{"action": "expand",  "target": {...}}
{"action": "key",     "keys": ["ctrl", "c"]}
{"action": "wait",    "condition": {"text": "加载完成"}}
{"action": "done"}
```

**关键设计**：模型不直接输出坐标，输出"目标描述"，由执行层查表拿坐标。

**借鉴来源**：uia-agent、OpenWorker、qwen_autogui、winagent-lite

---

### 模块3：执行层 Actuator

**职责**：把标准动作指令变成真实操作。

| 子能力 | 优先级 | 说明 |
|--------|--------|------|
| 点击坐标 | P0 | pyautogui |
| 输入文字 | P0 | pyautogui |
| 快捷键 | P0 | pyautogui |
| 打开应用（Win+R） | P0 | 已有 |
| 按文本/元素点击 | P1 | 结合感知层 |
| 语义点击（元素引用） | P1 | 借鉴peekaboowin，hwnd:12345 |
| 多层定位fallback | P1 | 借鉴je-auto-control |
| 人类化鼠标移动 | P2 | 借鉴ScreenAgent，贝塞尔曲线 |

**多层定位fallback优先级**：
```
UIA可访问性树 → OCR文字 → 图像匹配 → VLM定位 → 锚点定位 → 自愈定位
```

**借鉴来源**：je-auto-control、ScreenAgent、peekaboowin

---

### 模块4：验证层 Verifier

**职责**：判断动作是否成功。这是当前最大的缺口。

| 子能力 | 优先级 | 说明 |
|--------|--------|------|
| 截图diff | P0 | 操作前后对比 |
| 找图验证 | P0 | 复用感知层 |
| 超时/重试策略 | P0 | 基础容错 |
| 断言API | P1 | 借鉴je-auto-control：assert_text/assert_image |
| 容差自愈重试 | P1 | 借鉴winagent-lite，1~3%偏差自动重试 |
| 色彩变化双通道验证 | P2 | 借鉴ScreenAgent |

**借鉴来源**：ScreenAgent、je-auto-control、winagent-lite

---

### 模块5：记忆层 Memory

**职责**：存任务状态、历史、上下文。

| 子能力 | 优先级 | 说明 |
|--------|--------|------|
| JSON文件存储 | P0 | 起步够用 |
| 任务状态快照 | P0 | observe-think-act循环中的状态 |
| 上下文管理 | P1 | 对话/任务历史 |
| 项目记忆 | P2 | 借鉴OpenWorker，绑定到仓库/文件夹 |
| SQLite | P2 | 数据量大时升级 |

**借鉴来源**：OpenWorker、uia-agent

---

### 模块6：工具层 Tools

**职责**：让Agent能调外部能力。

| 子能力 | 优先级 | 说明 |
|--------|--------|------|
| 文件读写 | P1 | 读配置、写日志 |
| 网络请求 | P1 | 调API、查资料 |
| 剪贴板 | P1 | 读写剪贴板 |
| 命令行执行 | P2 | 跑脚本 |
| MCP工具协议 | P2 | 借鉴peekaboowin/GhostDesk |

**借鉴来源**：OpenWorker、peekaboowin、GhostDesk

---

### 模块7：安全层 Security

**职责**：防止Agent做危险操作。

| 子能力 | 优先级 | 说明 |
|--------|--------|------|
| 审批门控 | P0 | 写文件/发消息/跑命令前等用户确认 |
| 操作白名单/黑名单 | P1 | 限制可操作范围 |
| 审计日志 | P1 | 所有操作可追溯 |
| Docker隔离 | P3 | 高风险场景才引入 |

**借鉴来源**：OpenWorker、GhostDesk

---

### 模块8：调度层 Orchestrator

**职责**：把上面模块串成主循环。

```
while 任务未完成:
    before = Perception.capture()
    action = Brain.decide(before, goal)
    Security.check(action)              # 审批门控
    Actuator.execute(action)
    after = Perception.capture()
    ok = Verifier.verify(before, after, action)
    Memory.save(state, action, ok)
    if not ok:
        重试 / 换策略 / 报错
```

| 子能力 | 优先级 | 说明 |
|--------|--------|------|
| 基础主循环 | P0 | 感知→决策→执行→验证 |
| 重试/异常处理 | P0 | 失败自动重试 |
| 任务队列 | P1 | 多任务调度 |
| 定时任务 | P2 | 借鉴OpenWorker |
| 业务逻辑与执行环境解耦 | P2 | 借鉴ok-script |

---

### 模块9：迭代升级层 Evolution（可选，后期）

| 子能力 | 优先级 | 说明 |
|--------|--------|------|
| 轨迹记录 | P2 | 记录成功/失败轨迹 |
| 步级过滤蒸馏 | P3 | 借鉴WebSTAR |
| 自我迭代框架 | P3 | 借鉴UI-Genie |
| 运行时LoRA微调 | P3 | 借鉴OPENVID |
| 测试时自进化 | P3 | 借鉴R-OPSD |

**借鉴来源**：UI-Genie、WebSTAR、LiteGUI、OPENVID、R-OPSD

---

## 五、开发顺序（按积木搭建）

| 步骤 | 做什么 | 产出 |
|------|--------|------|
| 1 | 定义ScreenState / Action / 模块接口 | 接口协议 |
| 2 | 包装现有能力为Actuator | 执行模块 |
| 3 | 包装截屏/找图为Perception v1 | 感知模块v1 |
| 4 | 写规则版Brain | 决策模块v1 |
| 5 | 写基础Verifier（截图diff） | 验证模块 |
| 6 | 写JSON Memory | 记忆模块 |
| 7 | 写Orchestrator主循环 | 闭环跑通 |
| 8 | 加Security审批门控 | 安全层 |
| 9 | Perception加OCR | 感知模块v2 |
| 10 | Brain换成AI推理 | 决策模块v2 |
| 11 | 加Tools（文件/网络） | 工具层 |
| 12 | 加Evolution（可选） | 迭代升级层 |

---

## 六、技术选型

| 模块 | 推荐 |
|------|------|
| 截屏 | mss / pyautogui |
| OCR | easyocr / PaddleOCR |
| UIA | uiautomation（Windows） |
| 图像匹配 | OpenCV |
| 鼠标键盘 | pyautogui / pynput |
| AI推理 | aisuite（模型无关）/ Ollama（本地） |
| 存储 | JSON → SQLite |
| MCP | mcp-python |
| 沙箱 | Docker |

---

## 七、验收标准

### 阶段一（MVP）

- [ ] 能完成固定流程自动化（打开应用→点击→输入→验证）
- [ ] 主循环跑通，失败能重试
- [ ] 有基础截图diff验证

### 阶段二（智能版）

- [ ] 接入AI推理，能根据屏幕内容决策
- [ ] OCR + 模板匹配双通道感知
- [ ] 多层定位fallback
- [ ] 审批门控生效

### 阶段三（进化版）

- [ ] 能读写文件、联网
- [ ] 有轨迹记录和评测框架
- [ ] 可选：自迭代/蒸馏升级

---

## 八、参考项目清单

| 项目 | 借鉴模块 |
|------|----------|
| Self-Operating Computer | OCR模式、文字选择→坐标查表 |
| je-auto-control | 多层定位fallback、自愈定位、断言API |
| OpenWorker | 模型无关架构、审批门控、项目记忆 |
| GhostDesk | Docker隔离、MCP工具协议 |
| ok-script | 分辨率自适应模板、业务与设备解耦 |
| ScreenAgent | UIA+OCR融合、人类化鼠标、截图diff验证 |
| uia-agent | UIA树剪枝、7种结构化动作、observe-think-act |
| peekaboowin | 32个MCP工具、元素引用、等待机制 |
| winagent-lite | 闭环执行、容差自愈、MCP插件、评测框架 |
| qwen_autogui | 坐标归一化、任务循环、AI决策流程 |
| UI-Genie | 自我迭代框架、奖励模型 |
| WebSTAR | 步级过滤蒸馏、StepRM |
| LiteGUI | 免SFT on-policy蒸馏 |
| OPENVID | 运行时LoRA微调、失败聚类 |
| R-OPSD | 测试时自进化、token级蒸馏 |

---

## 九、关键设计原则（反复提醒）

1. **接口先行**：先定ScreenState/Action，再写模块
2. **动作结构化**：模型输出"目标描述"，不输出坐标
3. **模型无关**：决策层不绑定特定AI
4. **多层fallback**：定位失败自动降级
5. **验证闭环**：每个动作都要验证
6. **安全默认开启**：危险操作必须审批
7. **先规则后AI**：规则版跑通再接AI
8. **积木可替换**：换实现不改调用方
