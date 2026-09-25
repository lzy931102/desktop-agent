# 下载与安装指南

## 快速开始

### 1. 下载 DesktopAgent

打开 [Releases 页面](https://github.com/lzy931102/desktop-agent/releases/latest)，
在最新版本的 "Assets" 里点击 `DesktopAgent.exe` 下载。

**注意**：点击后如果页面空白，是正常的——文件正在下载中，
打开浏览器"下载"列表就能看到。

### 2. 安装 Ollama

1. 下载：https://ollama.com/download
2. 安装并启动（右下角出现羊驼图标）
3. 拉取模型：`ollama pull qwen2.5-coder:7b`

### 3. 运行

双击 `DesktopAgent.exe`，在输入框输入任务，点击"开始执行"。

## 常见问题

### Q: 点击下载链接后页面空白？
A: 正常。GitHub 下载链接直接触发下载，不显示页面。
   打开浏览器"下载"列表查看。

### Q: 双击 exe 没反应？
A: 首次启动需要解压（约 10 秒），请稍候。如果还是没反应，
   确认 Ollama 已安装并运行（右下角有羊驼图标）。

### Q: 提示"模型不可用"？
A: 运行 `ollama pull qwen2.5-coder:7b` 拉取模型后再试。

### Q: 界面看不清？
A: 请更新到 v2.0.1（修复了深色主题对比度问题）。

### Q: 想用云端模型（更快更强）？
A: 打开 ⚙ 设置 → 模型模式选"只用云端"或"自动" →
   填入服务商的 API Key（也可以只设环境变量，如 `ZHIPU_API_KEY`）→
   点"测试连接"确认 → 保存。
   注意：云端模式下屏幕数据会上传到模型服务商（界面会常驻提醒）。

## 命令行用法（进阶）

```bash
# 启动后自动执行任务
DesktopAgent.exe --run "打开计算器"

# 直接打开某个面板
DesktopAgent.exe --debug-open settings   # 设置
DesktopAgent.exe --debug-open scheduler  # 定时任务
DesktopAgent.exe --debug-open history    # 任务历史
```

## 数据存放位置

- 审计日志：`%LOCALAPPDATA%\DesktopAgent\logs\audit-*.jsonl`
- 任务历史：`%LOCALAPPDATA%\DesktopAgent\history.jsonl`
- 设置（含模型模式）：`%LOCALAPPDATA%\DesktopAgent\settings.json`
