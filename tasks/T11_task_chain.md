# T11 任务链 E2E 测试

## 目标

验证 Agent 能跨应用完成任务链：计算器运算 → 复制结果 → 记事本粘贴 → 保存 → 验证文件。

## 前置

- 安装依赖：pyautogui, opencv-python, pytesseract, pyperclip（可选）, DesktopAgent
- 系统自带 calc.exe + notepad.exe
- 测试脚本：F:\opencode-workspace\test_task_chain_e2e.py

## 步骤

### 第一步：打开计算器

- calc.exe → 查找窗口 → focus → 按 C 清除

### 第二步：计算 123×456

- 按钮序列：1 → 2 → 3 → * → 4 → 5 → 6 → =

### 第三步：OCR 验证结果

- 截取显示区域 → OCR → 验证 == "56088"

### 第四步：复制结果

- Ctrl+A 全选 → Ctrl+C 复制到剪贴板

### 第五步：验证剪贴板

- 读取剪贴板内容，验证 == "56088"
- 支持 pyperclip 或 PowerShell Get-Clipboard

### 第六步：打开记事本

- notepad.exe → 查找窗口 → focus

### 第七步：粘贴结果

- Ctrl+V 粘贴

### 第八步：保存文件

- Ctrl+S → Alt+N → 输入路径 E:\agent_test\task_chain_result.txt → Enter

### 第九步：关闭记事本

- Alt+F4 → 处理保存对话框（按 N 不保存，因为已保存）

### 第十步：关闭计算器

- PostMessageW(WM_CLOSE)

### 第十一步：验证文件

- 读取 task_chain_result.txt，验证内容 == "56088"

### 第十二步：运行测试

```bash
cd /d F:\opencode-workspace
set PYTHONUTF8=1
python -u test_task_chain_e2e.py
```

### 第十三步：验收标准

- 11 个步骤全部 PASS
- 计算器 OCR 结果 == "56088"
- 剪贴板内容 == "56088"
- 文件内容 == "56088"
- 总耗时 < 60s

## 实际测试结果

**状态：已实现**

11 步全部 PASS，0 次重试，总耗时 21.4s。

步骤明细：
- 打开计算器：3217ms
- 计算 123×456：2869ms
- 复制结果：1047ms
- 验证剪贴板：301ms（== "56088"）
- 打开记事本：2605ms
- 粘贴结果：1252ms
- 保存文件：6670ms
- 关闭记事本：1753ms
- 关闭计算器：815ms
- 验证文件：301ms（== "56088"）

- 文件路径：E:\agent_test\task_chain_result.txt
- 文件内容：56088（正确）

## 关键实现要点

- 跨应用协调：calc.exe ↔ notepad.exe，通过 DesktopAgent 统一操作
- 每步最多重试 3 次，失败截图
- 步骤间窗口焦点管理：_refind_calc / _refind_notepad
- 剪贴板双通道：pyperclip 优先，PowerShell 兜底
- 文件保存：直接写入路径，无需另存为对话框交互
- 结果文件：E:\agent_test\task_chain_result.txt

## 完成后

- 更新 PROJECT_STATUS.md
- 提交 Git
