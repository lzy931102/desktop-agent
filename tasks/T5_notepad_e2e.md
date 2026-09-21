# T5 记事本 E2E 测试

## 目标

验证 Agent 能打开记事本、输入文字、保存文件、关闭后重新打开并验证内容。

## 前置

- 安装依赖：pyautogui, DesktopAgent（F:\opencode-workspace\desktop_agent.py）
- 系统自带 notepad.exe
- 测试脚本：F:\opencode-workspace\test_notepad_e2e.py

## 步骤

### 第一步：打开记事本

- 使用 subprocess.Popen(["notepad.exe"]) 直接启动
- 等待窗口出现：查找标题含 "记事本" / "Notepad" / "无标题" 的窗口
- 超时 5s

### 第二步：输入内容

- 通过 PowerShell Set-Clipboard 设置剪贴板为测试文本
- Ctrl+V 粘贴
- 测试文本："Hello from Agent!"

### 第三步：保存文件

- Ctrl+S 打开保存对话框
- Alt+N 聚焦文件名字段
- Ctrl+A 全选，Ctrl+V 粘贴路径
- 路径：E:\agent_test\agent_test.txt
- Enter 确认保存

### 第四步：关闭记事本

- Alt+F4 关闭
- 等待窗口销毁

### 第五步：重新打开验证

- 重新打开记事本
- Ctrl+O 打开文件对话框
- 输入文件路径
- 读取文件内容，验证包含测试文本

### 第六步：运行测试

```bash
cd /d F:\opencode-workspace
set PYTHONUTF8=1
python -u test_notepad_e2e.py
```

### 第七步：验收标准

- 5 个步骤全部 PASS
- 文件存在且内容正确
- 无手动干预

## 实际测试结果

**状态：已实现**

5/5 步骤全部 PASS，总耗时 28.3s。

- 测试文本："Hello from Agent!"
- 文件路径：E:\agent_test\agent_test.txt
- 文件内容验证通过

步骤明细：
- 打开记事本：2806ms
- 输入内容：3010ms
- 保存文件：9082ms
- 关闭记事本：3605ms
- 重开验证：9833ms

## 关键实现要点

- DesktopAgent 封装：click / type_text / hotkey / press_key
- 窗口查找：EnumWindows + GetWindowTextW 模糊匹配
- 剪贴板操作：PowerShell Set-Clipboard（避免中文编码问题）
- 每步最多重试 3 次，失败截图保存到 screenshots/
- 窗口焦点管理：SetForegroundWindow

## 完成后

- 更新 PROJECT_STATUS.md
- 提交 Git
