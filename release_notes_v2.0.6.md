# DesktopAgent v2.0.6 - 设置窗口最小化修复

## 修复

- **设置 / 任务表 / 任务历史 / 定时任务窗口的「—」最小化按钮此前点了没反应**（□ 最大化、× 关闭不受影响），现已修复：点击「—」正常最小化，再从任务栏组按钮的缩略图预览里点一下就能恢复
- 根因：Tk 在 Windows 上 `grab_set` 激活期间会拦掉对话框标题栏「—」的最小化消息。本版把模态方式改成 Windows 原生惯例——对话框打开期间禁用主窗口输入（模态语义与原来一致），关闭对话框后自动恢复，不再使用 grab

## 下载

[前往 Releases 页面下载](https://github.com/lzy931102/desktop-agent/releases/latest)

点击后进入下载页面，在 "Assets" 区域找到 `DesktopAgent.exe` 下载。

## 验收

- 端到端验收脚本 `verify_fix_minimize.py` 随仓库发布（启动应用后运行 `python verify_fix_minimize.py <pid>` 可复跑）：覆盖 最小化 / 样式位 / 恢复 / □ / × / 主窗口回归
- 打包产物实测通过：「—」→ showCmd=2 → 任务栏缩略图点击恢复、□ 最大化与还原、× 关闭、对话框关闭后主窗口解除禁用、主窗口自身「—」最小化正常
- 回归测试：`pytest test_core_guard.py` 127 passed + 7 xfailed；`python tests_smoke.py` ALL PASS

## 安全扫描状态（Mimosa · 请务必阅读）

本发布**不构成"已通过完整安全审计"**，如实披露：

- Scan ID `scan-2026-09-26T06-42-30.474Z-e934bd7cad80`（deep，静态证据边界，未运行项目代码）
- Seal `sha256:9ac5bfeaadbf35acfc18b0438f2dcd1889462f39adf4ae7d0dcad5d36995f3b9`（产物已密封、可复核）
- 运行状态 **inconclusive**：threatModel partial（entryPoints=0 为阶段未实际展开，不是"项目没有入口"，依据同 v2.0.5 披露）、pathAnalysis 未启动——覆盖缺口与 v2.0.5 披露一致，为扫描引擎持续限制
- **14 条静态发现（3 HIGH + 11 LOW），全部与 v2.0.5 披露同类、同源**：
  - 3 条 HIGH 路径穿越（CWE-22）：`agent_loop.py:1060`（向固定路径写配置，路径不受外部输入控制，v2.0.5 已判误报并附风险边界说明）、`game.py:265/272`（本地测试靶场）
  - 11 条 LOW 不安全随机数（CWE-330）：`game.py` ×5、`popup_generator.py` ×2、`run_target_game.py` ×4（随机数仅决定靶位，无安全影响）
  - **本版唯一改动文件 gui.py 及新增验收脚本：0 条发现**
- 依赖双口径（pip-audit 2.10.1）：
  - **运行环境（即本 exe 打包版本）**：0 条已知漏洞。实际版本：pillow 12.3.0 / customtkinter 6.0.0 / opencv-python 5.0.0.93 / PyAutoGUI 0.9.54 / pyperclip 1.11.0 / pywinauto 0.6.9 / requests 2.34.2 / openai 3.13.0
  - **requirements.txt（本版已随附修正，拍板结果）**：`pillow` 升至 `>=12.3.0`，消除原 `pillow==10.4.0` 声明的 17 条在案通告（PYSEC-2026-165/2249/2250/2252/2253/2254/2255/2256/2257/2874/3451/3453/3454/3493/3494/3495/3496）；`opencv-python` / `pyautogui` 的 `==` 固定同步改为 `>=` 下限（`==` 固定会让 py3.13/3.14 源码安装被旧包卡死，也与 v2.0.5 notes 宣称的"版本下限"策略不符）。修正后 `pip-audit -r requirements.txt` 归零；py3.12 干跑解析实测通过（解析出 pillow 12.3.0 + opencv 5.0.0.93 + customtkinter 6.0.0）
  - **Python 支持声明随 pillow 12.3.0 调整为 3.10+**（实测 12.3.0 无 3.9/3.8 包；3.8/3.9 已于 2024-10 EOL）：README 徽章与 PROJECT_SUMMARY 已同步，py3.12 与 py3.14 双环境实测
  - 本地私有包 mining-scanner 1.0.0 不在 PyPI、无法核对，也不在本发布产物内

## 结论

- 本版相对 v2.0.5 改动两处：对话框模态实现（最小化修复）+ requirements 版本声明修正（pillow 安全版本），另新增端到端验收脚本
- 因威胁建模与可达性分析未完整运行，本发布不做"依赖无风险 / 项目安全"的整体断言；v2.0.5 的覆盖缺口披露继续适用
