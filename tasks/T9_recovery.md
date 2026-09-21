# T9 异常恢复测试

## 目标

验证 Agent 在遇到 4 种异常场景时能自动恢复并继续完成任务。

## 前置

- 游戏脚本：E:\agent_test\game.py
- Agent 具备异常检测和恢复能力
- 测试脚本：F:\opencode-workspace\test_recovery_e2e.py（从 D:\文档\Default Project\ 恢复）

## 步骤

### 场景1：操作中窗口突然关闭

- 打开记事本并输入文字
- 强制关闭记事本进程
- 验证 Agent 检测到窗口消失并正确处理

### 场景2：操作中弹窗出现

- 打开记事本并输入文字
- 触发弹窗干扰
- 验证 Agent 处理弹窗并继续操作

### 场景3：点击后目标消失

- 检测 5 个目标
- 模拟目标消失后恢复
- 验证恢复率

### 场景4：程序无响应

- 创建假死程序
- 超时检测
- 验证 Agent 正确处理超时

## 验收标准

- 4/4 场景全部恢复成功
- 恢复过程有日志输出
- 总恢复时间 < 30s

## 实际测试结果

**状态：已实现**

通过：4/4，失败：0/4，总耗时 9.78s。

| 场景 | 描述 | 结果 | 耗时 |
|---|---|---|---|
| 1 | 操作中窗口突然关闭 | PASS | 4.16s |
| 2 | 操作中弹窗出现 | PASS | 4.32s |
| 3 | 点击后目标消失 | PASS | 0.14s |
| 4 | 程序无响应 | PASS | 1.16s |

## 关键实现要点

- 窗口检测：EnumWindows 轮询 + IsWindowVisible
- 进程监控：subprocess.poll() / 强制终止
- 弹窗处理：FindWindowW + PostMessageW(WM_CLOSE)
- 超时检测：time.perf_counter() 计时
- 截图保存：screenshots/t9_scenario*.png

## 完成后

- 更新 PROJECT_STATUS.md
- 提交 Git
