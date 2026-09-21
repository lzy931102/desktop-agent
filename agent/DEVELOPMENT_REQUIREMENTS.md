# 电脑操作AGENT开发需求文档

## 一、项目概述

### 1.1 项目名称
Desktop Agent - 模块化智能电脑操作代理

### 1.2 项目目标
构建一个像积木一样可拼接的电脑操作AGENT，具备"感知-决策-执行-验证-学习"的完整闭环，能够通过自然语言指令自动操作电脑完成任务。

### 1.3 核心价值
- **模块化设计**：每个功能独立，可单独开发、测试、升级
- **渐进式增强**：从简单自动化脚本逐步升级到智能AGENT
- **自我进化**：具备从成功/失败中学习的能力，越用越强

---

## 二、架构设计

### 2.1 总体架构图

```
┌─────────────────────────────────────────────────────────────────┐
│                    调度层 / 主循环 (Scheduler)                    │
│   while True:                                                   │
│       1. 感知 (Perceive)                                        │
│       2. 决策 (Decide)                                          │
│       3. 执行 (Act)                                             │
│       4. 验证 (Verify)                                          │
│       5. 学习 (Learn)                                           │
└───────┬─────────┬─────────┬─────────┬─────────┬─────────────────┘
        │         │         │         │         │
   ┌────▼───┐ ┌───▼────┐ ┌──▼─────┐ ┌─▼──────┐ ┌▼────────┐
   │ 感知层 │ │ 决策层 │ │ 执行层 │ │ 验证层 │ │ 学习层  │
   └────┬───┘ └───┬────┘ └──┬─────┘ └─┬──────┘ └┬────────┘
        │         │         │         │         │
   ┌────▼───┐ ┌───▼────┐ ┌──▼─────┐ ┌─▼──────┐ ┌▼────────┐
   │OCR识别 │ │AI模型  │ │鼠标键盘│ │断言    │ │经验沉淀 │
   │UIA树   │ │任务规划│ │图像匹配│ │验证    │ │技能进化 │
   │图像定位│ │动作生成│ │窗口管理│ │重试机制│ │模型蒸馏 │
   └────────┘ └────────┘ └────────┘ └────────┘ └────────┘
```

### 2.2 模块清单

| 模块 | 职责 | 核心功能 |
|------|------|----------|
| **Scheduler** | 调度层，主循环控制 | 任务分解、状态管理、异常处理 |
| **Perception** | 感知层，理解屏幕内容 | OCR、UIA树、图像识别、元素定位 |
| **Cognition** | 决策层，AI推理与规划 | 截图分析、任务规划、动作生成 |
| **Execution** | 执行层，操作电脑 | 鼠标、键盘、窗口管理、图像匹配 |
| **Verification** | 验证层，确认操作结果 | 断言、截图对比、状态检查 |
| **Learning** | 学习层，自我进化 | 经验沉淀、技能生成、模型蒸馏 |

---

## 三、功能需求

### 3.1 感知层需求

#### 3.1.1 OCR识别
- **功能**：识别屏幕上的文字内容
- **技术**：Tesseract / EasyOCR / PaddleOCR
- **输出**：文字内容 + 坐标位置
- **参考**：Self-Operating Computer的OCR模式

#### 3.1.2 UIA树解析
- **功能**：获取Windows UI Automation树
- **技术**：pywinauto / uiautomation
- **输出**：可交互元素列表（类型、名称、坐标）
- **参考**：uia-agent的UIA树剪枝算法

#### 3.1.3 图像定位
- **功能**：在屏幕上查找特定图像
- **技术**：OpenCV模板匹配 / YOLO检测
- **输出**：图像位置 + 置信度
- **参考**：ok-script的分辨率自适应模板匹配

#### 3.1.4 多模态融合
- **功能**：融合OCR、UIA、图像识别结果
- **技术**：IoU去重、坐标平均、置信度加权
- **输出**：统一的元素列表
- **参考**：ScreenAgent的双通道视觉融合

### 3.2 决策层需求

#### 3.2.1 截图分析
- **功能**：分析当前屏幕状态
- **技术**：多模态AI模型（GPT-4V/GLM-4/Qwen-VL）
- **输出**：屏幕内容描述、可交互元素、建议操作
- **参考**：Self-Operating Computer的Set-of-Mark

#### 3.2.2 任务规划
- **功能**：将自然语言任务分解为步骤
- **技术**：LLM + 结构化输出
- **输出**：步骤列表（动作、参数、依赖）
- **参考**：winagent-lite的plan工具

#### 3.2.3 动作生成
- **功能**：生成具体的操作命令
- **技术**：LLM + JSON Schema约束
- **输出**：标准化动作（click/type/hotkey/wait等）
- **参考**：uia-agent的7种标准动作

### 3.3 执行层需求

#### 3.3.1 鼠标操作
- **功能**：点击、移动、拖拽、滚动
- **技术**：pyautogui / Win32 SendInput
- **特性**：人类化路径（贝塞尔曲线）、超调抖动
- **参考**：ScreenAgent的人类化鼠标

#### 3.3.2 键盘操作
- **功能**：输入文字、快捷键、按键组合
- **技术**：pyautogui / Win32 API
- **特性**：支持中文输入、输入法切换
- **参考**：peekaboowin的128+键名支持

#### 3.3.3 窗口管理
- **功能**：激活、移动、调整大小、关闭窗口
- **技术**：pygetwindow / Win32 API
- **输出**：窗口句柄、标题、位置
- **参考**：peekaboowin的窗口管理工具

#### 3.3.4 自愈定位
- **功能**：定位失败时自动尝试其他方式
- **技术**：多层fallback策略
- **策略**：UIA -> OCR -> 图像匹配 -> VLM -> 锚点
- **参考**：je-auto-control的自愈定位器

### 3.4 验证层需求

#### 3.4.1 断言系统
- **功能**：验证操作是否成功
- **技术**：OCR断言、图像断言、元素断言
- **输出**：成功/失败 + 失败原因
- **参考**：je-auto-control的assert_text/assert_image

#### 3.4.2 截图对比
- **功能**：对比操作前后的截图
- **技术**：图像差异分析、色彩变化检测
- **输出**：变化区域、变化程度
- **参考**：ScreenAgent的点击验证

#### 3.4.3 状态检查
- **功能**：检查系统状态（窗口、进程、文件）
- **技术**：pygetwindow、psutil、os.path
- **输出**：状态信息

#### 3.4.4 重试机制
- **功能**：操作失败时自动重试
- **技术**：指数退避、坐标微调、策略切换
- **参数**：最大重试次数、重试间隔
- **参考**：winagent-lite的容差自愈

### 3.5 学习层需求

#### 3.5.1 经验沉淀
- **功能**：从成功/失败中提取经验
- **技术**：轨迹分析、模式识别
- **输出**：成功模式、失败教训、用户偏好
- **参考**：Hermes Agent的Curated Memory

#### 3.5.2 技能生成
- **功能**：将经验转化为可复用技能
- **技术**：LLM + SKILL.md格式
- **输出**：技能文件（名称、描述、步骤）
- **参考**：agent-self-evolution的技能草拟

#### 3.5.3 技能进化
- **功能**：根据使用反馈优化技能
- **技术**：使用统计、健康度评估、归档机制
- **输出**：技能更新、技能归档
- **参考**：Hermes Agent的Skills系统

#### 3.5.4 模型蒸馏（可选）
- **功能**：从强模型蒸馏到小模型
- **技术**：步级过滤、SFT微调、LoRA热插拔
- **输出**：蒸馏后的小模型
- **参考**：WebSTAR、LiteGUI、OPENVID

---

## 四、技术选型

### 4.1 编程语言
- **主语言**：Python 3.9+
- **辅助语言**：TypeScript（MCP Server）

### 4.2 核心依赖

| 类别 | 库名 | 用途 |
|------|------|------|
| **自动化** | pyautogui | 鼠标键盘控制 |
| **UIA** | pywinauto | Windows UI Automation |
| **OCR** | easyocr / pytesseract | 文字识别 |
| **图像** | opencv-python | 图像处理、模板匹配 |
| **AI** | openai | 调用多模态模型 |
| **窗口** | pygetwindow | 窗口管理 |
| **系统** | psutil | 进程、系统信息 |

### 4.3 AI模型选择

| 场景 | 推荐模型 | 备选模型 |
|------|----------|----------|
| 截图分析 | GPT-4V | GLM-4V, Qwen-VL |
| 任务规划 | GPT-4 | GLM-4, DeepSeek |
| 本地推理 | Qwen2.5-VL-7B | LLaVA-7B |

### 4.4 接口协议
- **MCP (Model Context Protocol)**：与AI客户端集成
- **JSON-RPC**：模块间通信
- **REST API**：可选的HTTP接口

---

## 五、模块接口设计

### 5.1 基础模块接口

```python
class BaseModule:
    def __init__(self, config: dict = None):
        self.config = config or {}
    def initialize(self):
        pass
    def process(self, input_data: dict) -> dict:
        pass
    def cleanup(self):
        pass
```

### 5.2 感知层接口

```python
class PerceptionModule(BaseModule):
    def ocr(self, image) -> dict:
        pass  # 返回: {"success": True, "elements": [{"text": "...", "x": 0, "y": 0}]}
    def find_ui_elements(self) -> dict:
        pass  # 返回: {"success": True, "elements": [{"type": "button", "name": "...", "x": 0, "y": 0}]}
    def find_image(self, template_path: str) -> dict:
        pass  # 返回: {"success": True, "found": True, "x": 0, "y": 0, "confidence": 0.9}
    def analyze_screen(self) -> dict:
        pass  # 返回: {"success": True, "analysis": {...}}
```

### 5.3 决策层接口

```python
class CognitionModule(BaseModule):
    def analyze_screenshot(self, screenshot, task: str) -> dict:
        pass
    def plan_task(self, task: str) -> dict:
        pass
    def generate_action(self, context: dict) -> dict:
        pass
```

### 5.4 执行层接口

```python
class ExecutionModule(BaseModule):
    def click(self, x: int, y: int) -> dict:
        pass
    def type_text(self, text: str) -> dict:
        pass
    def hotkey(self, *keys) -> dict:
        pass
    def screenshot(self, path: str) -> dict:
        pass
```

### 5.5 验证层接口

```python
class VerificationModule(BaseModule):
    def assert_text(self, expected: str, region: tuple = None) -> dict:
        pass
    def assert_image(self, template_path: str) -> dict:
        pass
    def verify_click(self, x: int, y: int) -> dict:
        pass
```

### 5.6 学习层接口

```python
class LearningModule(BaseModule):
    def extract_experience(self, trajectory: dict) -> dict:
        pass
    def generate_skill(self, experience: dict) -> dict:
        pass
    def update_skill(self, skill_name: str, feedback: dict) -> dict:
        pass
```

---

## 六、开发计划

### Phase 1：基础框架（第1-2周）

| 任务 | 产出 | 优先级 |
|------|------|--------|
| 搭建项目结构 | 目录结构、配置文件 | P0 |
| 实现BaseModule | 基础模块接口 | P0 |
| 实现ExecutionModule | 鼠标键盘操作 | P0 |
| 实现PerceptionModule基础版 | 截屏、简单OCR | P0 |
| 实现Scheduler基础版 | 简单循环调度 | P0 |

**验收标准**：能通过命令行执行点击、输入、截屏操作

### Phase 2：感知增强（第3-4周）

| 任务 | 产出 | 优先级 |
|------|------|--------|
| 集成EasyOCR | 文字识别 | P0 |
| 集成UIA树 | 获取可交互元素 | P0 |
| 实现多模态融合 | OCR+UIA+图像融合 | P1 |
| 实现图像模板匹配 | OpenCV找图 | P1 |

**验收标准**：能识别屏幕文字、获取UI元素、查找图像

### Phase 3：决策智能（第5-6周）

| 任务 | 产出 | 优先级 |
|------|------|--------|
| 集成多模态AI | 截图分析 | P0 |
| 实现任务规划 | 自然语言到步骤 | P0 |
| 实现动作生成 | 步骤到操作命令 | P0 |
| 实现动作验证 | 操作结果检查 | P1 |

**验收标准**：能通过自然语言指令自动完成简单任务

### Phase 4：鲁棒性提升（第7-8周）

| 任务 | 产出 | 优先级 |
|------|------|--------|
| 实现自愈定位 | 多层fallback | P1 |
| 实现断言系统 | 文字/图像断言 | P1 |
| 实现重试机制 | 指数退避+坐标微调 | P1 |
| 实现人类化鼠标 | 贝塞尔曲线 | P2 |

**验收标准**：操作成功率>80%，具备自动重试能力

### Phase 5：学习进化（第9-10周）

| 任务 | 产出 | 优先级 |
|------|------|--------|
| 实现经验提取 | 轨迹分析 | P2 |
| 实现技能生成 | SKILL.md生成 | P2 |
| 实现技能进化 | 使用统计+健康度 | P2 |
| 实现MCP集成 | 与AI客户端对接 | P2 |

**验收标准**：能从任务中学习、生成可复用技能

### Phase 6：模型蒸馏（可选，第11-12周）

| 任务 | 产出 | 优先级 |
|------|------|--------|
| 实现轨迹收集 | 步级数据收集 | P3 |
| 实现步级过滤 | 正确步骤筛选 | P3 |
| 实现SFT微调 | 小模型训练 | P3 |
| 实现LoRA热插拔 | 运行时模型更新 | P3 |

**验收标准**：能蒸馏出端侧小模型，具备持续学习能力

---

## 七、参考开源项目

### 7.1 感知层参考

| 项目 | 参考模块 | 链接 |
|------|----------|------|
| Self-Operating Computer | OCR+坐标映射 | https://github.com/trycua/self-operating-computer |
| ScreenAgent | 双通道视觉融合 | https://github.com/litleman/ScreenAgent |
| ok-script | 分辨率自适应模板匹配 | https://github.com/ok-script/ok-script |

### 7.2 决策层参考

| 项目 | 参考模块 | 链接 |
|------|----------|------|
| uia-agent | UIA树驱动、结构化Action | https://github.com/SuperMarioYL/uia-agent |
| qwen_autogui | 坐标映射、任务循环 | https://github.com/tech-shrimp/qwen_autogui |
| winagent-lite | 本地VLM、规划能力 | https://github.com/ZYYDI1959/winagent-lite |

### 7.3 执行层参考

| 项目 | 参考模块 | 链接 |
|------|----------|------|
| ScreenAgent | 人类化鼠标、点击验证 | https://github.com/litleman/ScreenAgent |
| je-auto-control | 多层fallback、自愈定位 | https://github.com/je-auto-control/je-auto-control |

### 7.4 验证层参考

| 项目 | 参考模块 | 链接 |
|------|----------|------|
| je-auto-control | 断言系统 | https://github.com/je-auto-control/je-auto-control |
| winagent-lite | 闭环验证、容差重试 | https://github.com/ZYYDI1959/winagent-lite |

### 7.5 学习层参考

| 项目 | 参考模块 | 链接 |
|------|----------|------|
| Hermes Agent | 技能系统、Nudge机制 | https://github.com/NousResearch/hermes-agent |
| agent-self-evolution | 经验采集、技能进化 | https://github.com/Shiorangerin/agent-self-evolution |
| OPENVID | 运行时自我改进 | https://github.com/OPENVID/OPENVID |

### 7.6 模型蒸馏参考

| 项目 | 参考模块 | 链接 |
|------|----------|------|
| WebSTAR | 步级过滤蒸馏 | https://github.com/WebSTAR/WebSTAR |
| LiteGUI | on-policy蒸馏 | https://github.com/LiteGUI/LiteGUI |
| UI-Genie | 自我迭代框架 | https://github.com/UI-Genie/UI-Genie |

---

## 八、验收标准

### 8.1 功能验收

| 功能 | 验收标准 |
|------|----------|
| OCR识别 | 识别准确率>90% |
| UIA元素获取 | 获取成功率>95% |
| 图像定位 | 定位准确率>85% |
| 任务规划 | 简单任务规划成功率>80% |
| 自动执行 | 操作成功率>75% |
| 验证反馈 | 验证准确率>90% |

### 8.2 性能验收

| 指标 | 目标值 |
|------|--------|
| 单步执行时间 | <2秒 |
| 端到端任务时间 | <60秒 |
| 内存占用 | <500MB |
| CPU占用 | <30% |

### 8.3 稳定性验收

| 指标 | 目标值 |
|------|--------|
| 连续运行时间 | >24小时 |
| 崩溃率 | <1次/1000任务 |
| 恢复时间 | <5秒 |

---

## 九、蒸馏迭代升级路线

### 9.1 技术路线

```
数据生成层 → 蒸馏训练层 → 运行时进化层 → 小模型能力提升
(强模型rollout)  (SFT/RL)    (经验沉淀)    (2B/3B/7B)
```

### 9.2 关键技术

| 技术 | 说明 | 参考项目 |
|------|------|----------|
| 步级过滤蒸馏 | 从强模型rollout中筛选正确步骤 | WebSTAR |
| 奖励模型(PRM) | 步级评分，引导策略优化 | ClawGUI |
| on-policy蒸馏 | 避免小模型灾难性遗忘 | LiteGUI |
| 运行时LoRA热插拔 | 夜间微调，无需重启 | OPENVID |
| 经验蒸馏为SOP | 成功路径压缩为可复用流程 | GA/Hermes |

### 9.3 实施优先级

1. **短期**：经验沉淀 + 技能生成（纯文本，无需训练）
2. **中期**：步级过滤 + 奖励模型（需要GPU）
3. **长期**：SFT微调 + LoRA热插拔（需要大量数据）
