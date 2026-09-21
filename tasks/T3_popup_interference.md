# T3 弹窗干扰测试

## 目标

验证 Agent 在纯视觉弹窗干扰下仍能完成游戏通关，并能正确关闭弹窗。

## 前置

- 安装依赖：mss, opencv-python, numpy
- 游戏脚本：E:\agent_test\game.py
- 弹窗生成器：F:\opencode-workspace\popup_generator.py
- 测试脚本：F:\opencode-workspace\test_popup_interference_e2e.py

## 步骤

### 第一步：弹窗生成

popup_generator.py 使用 tkinter 创建无边框窗口：
- 标题包含 "Interference" 关键词
- 通过 WM_CLOSE (0x0010) 消息关闭
- 参数：弹窗数量（默认 5 个）

### 第二步：游戏流程

1. 启动游戏：--speed 0 --target-radius 30
2. 启动弹窗生成器：popup_generator.py 5
3. 同时进行：
   - 检测并关闭弹窗（FindWindowW 查找 "Interference"）
   - 纯视觉感知红色靶子（mss + OpenCV HSV）
   - 点击红色靶子

### 第三步：弹窗处理

- 检测：EnumWindows 查找标题含 "Interference" 的窗口
- 关闭：SetForegroundWindow → PostMessageW(WM_CLOSE)
- 关闭后重新 focus 游戏窗口

### 第四步：运行测试

```bash
cd /d F:\opencode-workspace
set PYTHONUTF8=1
python -u test_popup_interference_e2e.py
```

### 第五步：验收标准

- 通关（score ≥ 10）
- 弹窗关闭率 100%（出现的弹窗全部关闭）
- 总耗时 < 30s
- 纯视觉方案（无 accessibility API）

## 实际测试结果

**状态：已实现**

- 通关：10/10（满分）
- 弹窗出现：5 次
- 弹窗关闭成功：5 次（100%）
- 总耗时：6.8s（远低于30s上限）
- 点击次数：10（无浪费点击）
- 感知方案：mss(17ms) + OpenCV HSV 红色双阈值检测

## 关键实现要点

- 纯视觉感知：mss 截屏 → OpenCV HSV 红色检测 → 轮廓/质心
- 弹窗窗口管理：FindWindowW + PostMessageW
- 游戏窗口坐标：GetClientRect + ClientToScreen
- 点击坐标转换：client 坐标 + 窗口偏移 → 屏幕坐标
- 状态文件读取：game_state.json 判断通关

## 完成后

- 更新 PROJECT_STATUS.md
- 提交 Git
