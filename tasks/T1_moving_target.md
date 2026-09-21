# T1 移动靶预判测试

## 目标

验证 Agent 在不同速度移动靶场景下的命中率，对比无预判与预判（mss+ctypes / pyautogui）的效果差异。

## 前置

- 安装依赖：mss, opencv-python, numpy, pyautogui（可选）
- 游戏脚本：E:\agent_test\game.py，支持 --speed / --target-radius 参数
- 测试脚本：F:\opencode-workspace\test_moving_target.py

## 步骤

### 第一步：确定测试矩阵

| 靶子半径 | 速度 | 每组次数 | 说明 |
|---|---|---|---|
| 30px | 0, 2, 5, 8 | 3 | 正常靶子 |
| 15px | 0, 2, 5, 8 | 3 | 小靶子 |

速度模式：
- no_predict：无预判，直接点当前坐标
- predict_mss：mss截屏 + ctypes点击，延迟 17ms
- predict_pyautogui：pyautogui截屏+点击，延迟 50ms（可选）

### 第二步：核心感知逻辑

1. mss 截屏 → BGR numpy 数组
2. OpenCV HSV 红色检测（双范围：0-10 / 170-180）
3. 形态学开闭操作去噪
4. 轮廓查找 → 面积/圆形度过滤 → 质心计算

### 第三步：预判算法

- Predictor 类：滑动窗口 10 帧 + EMA 平滑（alpha=0.3）
- 瞬时速度计算，检测传送（>200px 重置）
- 预判偏移 = 速度 × 延迟 × 1.4（SPEED_CORRECTION）
- 最大偏移限制 = 半径 × 0.8

### 第四步：运行测试

```bash
cd /d F:\opencode-workspace
set PYTHONUTF8=1
python -u test_moving_target.py
```

### 第五步：验收标准

- 静止靶（speed=0）命中率 > 95%
- 低速（speed=2）预判命中率 > 85%
- 中速（speed=5）预判命中率 > 70%
- 高速（speed=8）预判命中率 > 50%
- 预判模式优于无预判

## 实际测试结果

**状态：已实现**

- mss 感知：17ms 延迟，无预判 100%
- pyautogui：50ms 延迟，极限场景 53.6%
- 预判价值：只在"慢速 IO + 小目标"时体现
- 推荐：真实 Agent 用 mss，不用预判

半径 15，速度 8 数据：
- 无预判：90.9%
- 预判 mss：93.9%
- 预判 pyautogui：53.6%

## 关键实现要点

- 窗口定位：EnumWindows + GetWindowTextW 查找 "Target Game"
- 客户端坐标转换：GetClientRect → ClientToScreen
- 点击方式：ctypes mouse_event（左键按下 0x0002 + 抬起 0x0004）
- 状态读取：game_state.json 中的 score 字段判断命中
- 超时保护：ROUND_TIMEOUT = 60s，MAX_CLICKS = 100

## 完成后

- 更新 PROJECT_STATUS.md
- 提交 Git

## 最终验证结果（2026-09-21）

### 半径 30px

| 速度 | 无预判 | 预判 mss | 预判 pyautogui |
|---|---|---|---|
| 0 | 100% | 100% | 100% |
| 2 | 100% | 100% | 100% |
| 5 | 100% | 100% | 100% |
| 8 | 100% | 100% | 100% |

### 半径 15px

| 速度 | 无预判 | 预判 mss | 预判 pyautogui |
|---|---|---|---|
| 0 | 100% | 100% | 100% |
| 2 | 100% | 100% | 93.9% |
| 5 | 100% | 100% | 90.5% |
| 8 | 97.0% | 97.0% | 53.0% |

### 结论

- mss 感知：17ms 延迟，无预判 100%
- pyautogui：50ms 延迟，极限场景 53%
- 预判价值：只在"慢速 IO + 小目标"时体现
- 推荐：真实 Agent 用 mss，不用预判
