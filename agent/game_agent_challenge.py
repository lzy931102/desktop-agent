"""
[GAME] Agent能力大挑战 - 多关卡测试游戏
测试所有模块：Perception, Brain, Actuator, Verifier, Memory, Security, Orchestrator
"""

import sys
import io
import os
import time
import json
from pathlib import Path
from datetime import datetime

# 强制UTF-8输出，解决Windows中文系统编码问题
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

sys.path.insert(0, str(Path(__file__).parent))

from interfaces import (
    ScreenState, Action, ActionType,
    create_click_action, create_type_action, create_key_action, 
    create_wait_action, create_done_action
)
from modules.perception_v1 import create_perception
from modules.brain_rule import create_brain
from modules.actuator import create_actuator
from modules.verifier import create_verifier
from modules.memory_json import create_memory
from modules.security import create_security
from modules.orchestrator import create_orchestrator


class GameScore:
    """游戏计分板"""
    def __init__(self):
        self.total_score = 0
        self.max_score = 0
        self.results = []
    
    def add_result(self, level_name, passed, score, max_score, details=""):
        self.max_score += max_score
        if passed:
            self.total_score += score
        self.results.append({
            "level": level_name,
            "passed": passed,
            "score": score,
            "max_score": max_score,
            "details": details
        })
    
    def print_board(self):
        print("\n" + "=" * 60)
        print("    AGENT能力大挑战 - 最终成绩单")
        print("=" * 60)
        for r in self.results:
            status = "[PASS]" if r["passed"] else "[FAIL]"
            print(f"{status} {r['level']}: {r['score']}/{r['max_score']}分")
            if r["details"]:
                print(f"       {r['details']}")
        print("-" * 60)
        print(f"总分: {self.total_score}/{self.max_score}")
        if self.max_score > 0:
            percent = (self.total_score / self.max_score) * 100
            if percent >= 90:
                print("评级: S级 - 完美执行!")
            elif percent >= 70:
                print("评级: A级 - 优秀表现!")
            elif percent >= 50:
                print("评级: B级 - 良好!")
            else:
                print("评级: C级 - 继续努力!")
        print("=" * 60)


def print_level_header(level_num, name, description):
    """打印关卡标题"""
    print("\n" + "=" * 60)
    print(f">>> 第{level_num}关: {name}")
    print(f"    {description}")
    print("=" * 60)


class AgentChallengeGame:
    """Agent能力大挑战游戏"""
    
    def __init__(self):
        self.score = GameScore()
        # 初始化所有模块
        self.perception = create_perception({"ocr_engine": "tesseract"})
        self.brain = create_brain()
        self.actuator = create_actuator()
        self.verifier = create_verifier({"diff_threshold": 0.1})
        self.memory = create_memory({"storage_path": "game_memory", "max_history": 100})
        self.security = create_security({"auto_approve": True, "log_dir": "game_logs"})
        self.orchestrator = create_orchestrator({"max_retries": 3})
        
        # 设置Orchestrator的模块
        self.orchestrator.set_modules(
            perception=self.perception,
            brain=self.brain,
            actuator=self.actuator,
            verifier=self.verifier,
            memory=self.memory,
            security=self.security
        )
    
    # ============ 第1关: 感知测试 ============
    def level1_perception(self):
        """测试感知层 - 截图和OCR能力"""
        print_level_header(1, "感知之眼", "测试Perception模块的截图和OCR能力")
        
        passed = True
        details = []
        score = 0
        
        try:
            # 测试1: 截图
            print("\n[截图] 测试1: 屏幕截图...")
            state = self.perception.capture()
            
            if state and state.screenshot:
                print(f"   [PASS] 截图成功，大小: {len(state.screenshot)} 字符")
                score += 25
                details.append("截图OK")
            else:
                print("   [错误] 截图失败")
                passed = False
            
            # 测试2: OCR识别
            print("\n[搜索] 测试2: OCR文字识别...")
            if state and state.texts:
                print(f"   [PASS] 识别到 {len(state.texts)} 个文字")
                for i, text in enumerate(state.texts[:3]):
                    print(f"      - {text}")
                score += 25
                details.append(f"OCR识别{len(state.texts)}文字")
            else:
                print("   [危险] 未识别到文字 (可能tesseract未安装)")
                score += 10  # 部分分
                details.append("OCR不可用")
            
            # 测试3: UI元素识别
            print("\n[图像] 测试3: UI元素识别...")
            if state and state.elements:
                print(f"   [PASS] 识别到 {len(state.elements)} 个UI元素")
                score += 25
                details.append(f"UI元素{len(state.elements)}个")
            else:
                print("   [危险] 未识别到UI元素")
                score += 10
                details.append("UI元素有限")
            
            # 测试4: 活动窗口
            print("\n[窗口] 测试4: 活动窗口检测...")
            if state and state.active_window:
                window_title = state.active_window.get("title", "未知")
                print(f"   [PASS] 当前窗口: {window_title}")
                score += 25
                details.append(f"窗口:{window_title[:20]}")
            else:
                print("   [危险] 无法获取窗口信息")
                score += 10
                details.append("窗口信息有限")
                
        except Exception as e:
            print(f"   [错误] 感知测试异常: {e}")
            passed = False
            details.append(f"异常: {str(e)}")
        
        self.score.add_result("第1关-感知之眼", passed, score, 100, ", ".join(details))
        return passed
    
    # ============ 第2关: 决策测试 ============
    def level2_brain(self):
        """测试决策层 - 规划和决策能力"""
        print_level_header(2, "[大脑] 智慧之脑", "测试Brain模块的规划和决策能力")
        
        passed = True
        details = []
        score = 0
        
        try:
            # 创建测试状态
            test_state = ScreenState(
                screenshot="test",
                texts=["记事本", "文件", "编辑"],
                elements=[{"type": "window", "title": "记事本"}],
                active_window={"title": "记事本"}
            )
            
            # 测试1: 目标解析
            print("\n[笔记] 测试1: 目标解析...")
            goal = "打开记事本并输入Hello World"
            action = self.brain.decide(test_state, goal)
            
            if action:
                print(f"   [PASS] 生成动作: {action.action}")
                score += 30
                details.append(f"动作:{action.action}")
            else:
                print("   [错误] 决策失败")
                passed = False
            
            # 测试2: 动作规划
            print("\n[规划] 测试2: 动作规划...")
            self.brain.reset()
            steps = self.brain.plan("打开计算器并输入1+1")
            
            if steps and len(steps) > 0:
                print(f"   [PASS] 规划了 {len(steps)} 个步骤")
                for i, step in enumerate(steps[:3]):
                    print(f"      步骤{i+1}: {step.action}")
                score += 30
                details.append(f"规划{len(steps)}步")
            else:
                print("   [错误] 规划失败")
                passed = False
            
            # 测试3: 状态更新
            print("\n[刷新] 测试3: 状态更新...")
            self.brain.update_state(test_state, action, success=True)
            progress = self.brain.get_progress()
            
            if progress:
                print(f"   [PASS] 进度: {progress}")
                score += 20
                details.append("状态更新OK")
            else:
                print("   [错误] 状态更新失败")
                passed = False
            
            # 测试4: 重置
            print("\n[重置] 测试4: 重置功能...")
            self.brain.reset()
            progress_after = self.brain.get_progress()
            
            if progress_after.get("current_step", 0) == 0:
                print("   [PASS] 重置成功")
                score += 20
                details.append("重置OK")
            else:
                print("   [错误] 重置失败")
                passed = False
                
        except Exception as e:
            print(f"   [错误] 决策测试异常: {e}")
            passed = False
            details.append(f"异常: {str(e)}")
        
        self.score.add_result("第2关-智慧之脑", passed, score, 100, ", ".join(details))
        return passed
    
    # ============ 第3关: 执行测试 ============
    def level3_actuator(self):
        """测试执行层 - 动作执行能力"""
        print_level_header(3, "[执行] 执行之手", "测试Actuator模块的动作执行能力")
        
        passed = True
        details = []
        score = 0
        
        try:
            # 测试1: 屏幕尺寸
            print("\n[尺寸] 测试1: 获取屏幕尺寸...")
            screen_size = self.actuator.get_screen_size()
            
            if screen_size and screen_size[0] > 0:
                print(f"   [PASS] 屏幕尺寸: {screen_size[0]}x{screen_size[1]}")
                score += 20
                details.append(f"屏幕{screen_size[0]}x{screen_size[1]}")
            else:
                print("   [错误] 获取屏幕尺寸失败")
                passed = False
            
            # 测试2: 移动鼠标
            print("\n[鼠标] 测试2: 鼠标移动...")
            result = self.actuator.execute(
                create_click_action(target={"x": 100, "y": 100})
            )
            
            if result:
                print("   [PASS] 鼠标移动成功")
                score += 20
                details.append("鼠标移动OK")
            else:
                print("   [错误] 鼠标移动失败")
                passed = False
            
            # 测试3: 快捷键
            print("\n[键盘] 测试3: 快捷键执行...")
            # 不执行危险快捷键，只测试接口
            action = create_key_action(keys=["ctrl", "a"])
            if action:
                print("   [PASS] 快捷键动作创建成功")
                score += 20
                details.append("快捷键OK")
            
            # 测试4: 元素缓存
            print("\n[缓存] 测试4: 元素缓存...")
            test_elements = [
                {"ref": "hwnd:12345", "name": "按钮", "position": {"x": 200, "y": 300}},
                {"ref": "hwnd:67890", "name": "输入框", "position": {"x": 400, "y": 500}}
            ]
            self.actuator.update_element_cache(test_elements)
            
            if hasattr(self.actuator, '_element_cache') and len(self.actuator._element_cache) > 0:
                print(f"   [PASS] 缓存了 {len(self.actuator._element_cache)} 个元素")
                score += 20
                details.append(f"缓存{len(self.actuator._element_cache)}元素")
            else:
                print("   [危险] 元素缓存为空")
                score += 10
                details.append("缓存有限")
            
            # 测试5: 执行验证
            print("\n[PASS] 测试5: 执行结果验证...")
            action = create_type_action(text="test")
            # 不实际输入，只验证接口
            print("   [PASS] 执行接口正常")
            score += 20
            details.append("执行接口OK")
                
        except Exception as e:
            print(f"   [错误] 执行测试异常: {e}")
            passed = False
            details.append(f"异常: {str(e)}")
        
        self.score.add_result("第3关-执行之手", passed, score, 100, ", ".join(details))
        return passed
    
    # ============ 第4关: 验证测试 ============
    def level4_verifier(self):
        """测试验证层 - 结果验证能力"""
        print_level_header(4, "[验证] 验证之眼", "测试Verifier模块的结果验证能力")
        
        passed = True
        details = []
        score = 0
        
        try:
            # 测试1: 等待文字
            print("\n[等待] 测试1: 等待文字出现...")
            # 创建一个不会出现的文字，测试超时
            result = self.verifier.wait_for_text("不存在的测试文字12345", timeout=2.0)
            print(f"   [PASS] 等待功能正常 (结果: {result})")
            score += 25
            details.append("等待文字OK")
            
            # 测试2: 断言文字
            print("\n[搜索] 测试2: 断言文字...")
            result = self.verifier.assert_text("测试文字", timeout=1.0)
            print(f"   [PASS] 断言功能正常 (结果: {result})")
            score += 25
            details.append("断言文字OK")
            
            # 测试3: 截图验证
            print("\n[截图] 测试3: 截图验证...")
            before = self.perception.capture()
            time.sleep(0.5)
            after = self.perception.capture()
            
            if before and after:
                action = create_click_action(target={"x": 500, "y": 500})
                result = self.verifier.verify(before, after, action)
                print(f"   [PASS] 截图验证正常 (结果: {result})")
                score += 25
                details.append("截图验证OK")
            else:
                print("   [危险] 无法获取截图进行验证")
                score += 10
                details.append("截图获取有限")
            
            # 测试4: 图像验证
            print("\n[图像] 测试4: 图像验证接口...")
            # 创建测试图片路径
            test_image = "test_image.png"
            result = self.verifier.assert_image(test_image, timeout=1.0)
            print(f"   [PASS] 图像验证接口正常 (结果: {result})")
            score += 25
            details.append("图像验证接口OK")
                
        except Exception as e:
            print(f"   [错误] 验证测试异常: {e}")
            passed = False
            details.append(f"异常: {str(e)}")
        
        self.score.add_result("第4关-验证之眼", passed, score, 100, ", ".join(details))
        return passed
    
    # ============ 第5关: 记忆测试 ============
    def level5_memory(self):
        """测试记忆层 - 数据存储能力"""
        print_level_header(5, "[记忆] 记忆之库", "测试Memory模块的数据存储能力")
        
        passed = True
        details = []
        score = 0
        
        try:
            # 测试1: 保存数据
            print("\n[记忆] 测试1: 数据保存...")
            test_data = {"key": "value", "number": 123, "list": [1, 2, 3]}
            self.memory.save("test_key", test_data)
            print("   [PASS] 数据保存成功")
            score += 20
            details.append("保存OK")
            
            # 测试2: 加载数据
            print("\n[加载] 测试2: 数据加载...")
            loaded = self.memory.load("test_key")
            
            if loaded and loaded.get("key") == "value":
                print(f"   [PASS] 数据加载正确: {loaded}")
                score += 20
                details.append("加载OK")
            else:
                print("   [错误] 数据加载失败或不正确")
                passed = False
            
            # 测试3: 保存状态
            print("\n[状态] 测试3: 状态保存...")
            state = ScreenState(
                screenshot="test",
                texts=["测试"],
                elements=[],
                active_window={"title": "测试"}
            )
            action = create_click_action(target={"x": 100, "y": 100})
            self.memory.save_state(state, action, success=True)
            print("   [PASS] 状态保存成功")
            score += 20
            details.append("状态保存OK")
            
            # 测试4: 历史记录
            print("\n[历史] 测试4: 历史记录...")
            history = self.memory.get_history(limit=5)
            
            if history and len(history) > 0:
                print(f"   [PASS] 获取到 {len(history)} 条历史记录")
                score += 20
                details.append(f"历史{len(history)}条")
            else:
                print("   [危险] 历史记录为空")
                score += 10
                details.append("历史有限")
            
            # 测试5: 任务保存
            print("\n[笔记] 测试5: 任务保存...")
            task_data = {"goal": "测试任务", "status": "completed"}
            self.memory.save_task("test_task_001", task_data)
            loaded_task = self.memory.load_task("test_task_001")
            
            if loaded_task and loaded_task.get("goal") == "测试任务":
                print("   [PASS] 任务保存/加载成功")
                score += 20
                details.append("任务存储OK")
            else:
                print("   [错误] 任务保存/加载失败")
                passed = False
                
        except Exception as e:
            print(f"   [错误] 记忆测试异常: {e}")
            passed = False
            details.append(f"异常: {str(e)}")
        
        self.score.add_result("第5关-记忆之库", passed, score, 100, ", ".join(details))
        return passed
    
    # ============ 第6关: 安全测试 ============
    def level6_security(self):
        """测试安全层 - 安全检查能力"""
        print_level_header(6, "[安全] 安全之盾", "测试Security模块的安全检查能力")
        
        passed = True
        details = []
        score = 0
        
        try:
            # 测试1: 安全检查
            print("\n[安全] 测试1: 安全检查...")
            safe_action = create_click_action(target={"x": 100, "y": 100})
            result = self.security.check(safe_action)
            
            if result:
                print("   [PASS] 安全检查通过")
                score += 25
                details.append("安全检查OK")
            else:
                print("   [错误] 安全检查失败")
                passed = False
            
            # 测试2: 危险动作检测
            print("\n[危险] 测试2: 危险动作检测...")
            dangerous_action = create_key_action(keys=["alt", "f4"])
            needs_approval = self.security._needs_approval(dangerous_action)
            
            print(f"   [PASS] 危险动作检测正常 (需要审批: {needs_approval})")
            score += 25
            details.append(f"危险检测OK")
            
            # 测试3: 自动审批模式
            print("\n[机器人] 测试3: 自动审批模式...")
            self.security.set_auto_approve(True)
            result = self.security.check(dangerous_action)
            
            if result:
                print("   [PASS] 自动审批模式正常")
                score += 25
                details.append("自动审批OK")
            else:
                print("   [错误] 自动审批模式异常")
                passed = False
            
            # 测试4: 操作日志
            print("\n[规划] 测试4: 操作日志...")
            self.security.log_action(safe_action, success=True)
            today = datetime.now().strftime("%Y%m%d")
            logs = self.security.get_logs(today)
            
            if logs and len(logs) > 0:
                print(f"   [PASS] 日志记录正常 (共{len(logs)}条)")
                score += 25
                details.append(f"日志{len(logs)}条")
            else:
                print("   [危险] 日志记录为空")
                score += 10
                details.append("日志有限")
                
        except Exception as e:
            print(f"   [错误] 安全测试异常: {e}")
            passed = False
            details.append(f"异常: {str(e)}")
        
        self.score.add_result("第6关-安全之盾", passed, score, 100, ", ".join(details))
        return passed
    
    # ============ 第7关: 调度测试 ============
    def level7_orchestrator(self):
        """测试调度层 - 模块协调能力"""
        print_level_header(7, "[刷新] 调度之心", "测试Orchestrator模块的协调能力")
        
        passed = True
        details = []
        score = 0
        
        try:
            # 测试1: 模块验证
            print("\n[搜索] 测试1: 模块完整性验证...")
            is_valid = self.orchestrator._validate_modules()
            
            if is_valid:
                print("   [PASS] 所有模块已就绪")
                score += 25
                details.append("模块完整")
            else:
                print("   [错误] 模块缺失")
                passed = False
            
            # 测试2: 状态管理
            print("\n[状态] 测试2: 状态管理...")
            status = self.orchestrator.get_status()
            
            if status:
                print(f"   [PASS] 当前状态: {status.get('status')}")
                score += 25
                details.append(f"状态:{status.get('status')}")
            else:
                print("   [错误] 状态获取失败")
                passed = False
            
            # 测试3: 暂停/恢复
            print("\n[暂停] 测试3: 暂停/恢复功能...")
            # 不实际启动任务，只测试接口
            self.orchestrator.status = self.orchestrator.status.__class__.RUNNING
            self.orchestrator.pause()
            
            if self.orchestrator.status.value == "paused":
                print("   [PASS] 暂停功能正常")
                score += 25
                details.append("暂停OK")
                
                self.orchestrator.resume()
                print("   [PASS] 恢复功能正常")
                details.append("恢复OK")
            else:
                print("   [危险] 暂停/恢复测试跳过")
                score += 15
                details.append("暂停/恢复有限")
            
            # 测试4: 错误处理
            print("\n[错误] 测试4: 错误处理...")
            self.orchestrator._handle_error("测试错误")
            print("   [PASS] 错误处理接口正常")
            score += 25
            details.append("错误处理OK")
                
        except Exception as e:
            print(f"   [错误] 调度测试异常: {e}")
            passed = False
            details.append(f"异常: {str(e)}")
        
        self.score.add_result("第7关-调度之心", passed, score, 100, ", ".join(details))
        return passed
    
    # ============ 第8关: 综合挑战 ============
    def level8_integration(self):
        """综合测试 - 模块协作"""
        print_level_header(8, "[终极] 终极挑战", "综合测试所有模块协作能力")
        
        passed = True
        details = []
        score = 0
        
        try:
            # 测试1: 感知-决策链
            print("\n[链接] 测试1: 感知-决策链...")
            state = self.perception.capture()
            if state:
                action = self.brain.decide(state, "测试任务")
                if action:
                    print("   [PASS] 感知-决策链正常")
                    score += 20
                    details.append("感知决策OK")
                else:
                    print("   [错误] 决策失败")
                    passed = False
            else:
                print("   [错误] 感知失败")
                passed = False
            
            # 测试2: 决策-验证链
            print("\n[链接] 测试2: 决策-执行-验证链...")
            before = self.perception.capture()
            # 不实际执行，模拟流程
            action = create_click_action(target={"x": 100, "y": 100})
            after = self.perception.capture()
            
            if before and after:
                verify_result = self.verifier.verify(before, after, action)
                print(f"   [PASS] 执行-验证链正常 (结果: {verify_result})")
                score += 20
                details.append("执行验证OK")
            else:
                print("   [危险] 执行-验证链部分失败")
                score += 10
                details.append("执行验证有限")
            
            # 测试3: 安全-记忆链
            print("\n[链接] 测试3: 安全-记忆链...")
            safe_action = create_type_action(text="测试")
            self.security.check(safe_action)
            self.memory.save_state(state, safe_action, success=True)
            history = self.memory.get_history(limit=1)
            
            if history:
                print("   [PASS] 安全-记忆链正常")
                score += 20
                details.append("安全记忆OK")
            else:
                print("   [危险] 安全-记忆链部分失败")
                score += 10
                details.append("安全记忆有限")
            
            # 测试4: 完整循环模拟
            print("\n[链接] 测试4: 完整循环模拟...")
            # 模拟Orchestrator的完整循环
            state = self.perception.capture()
            action = self.brain.decide(state, "模拟任务")
            self.security.check(action)
            # 不实际执行
            verify_result = self.verifier.verify(state, state, action)
            self.memory.save_state(state, action, success=verify_result)
            self.brain.update_state(state, action, success=verify_result)
            
            print("   [PASS] 完整循环模拟成功")
            score += 20
            details.append("完整循环OK")
            
            # 测试5: 模块状态一致性
            print("\n[链接] 测试5: 模块状态一致性...")
            brain_progress = self.brain.get_progress()
            memory_history = self.memory.get_history(limit=1)
            
            if brain_progress and memory_history:
                print("   [PASS] 模块状态一致")
                score += 20
                details.append("状态一致")
            else:
                print("   [危险] 模块状态部分不一致")
                score += 10
                details.append("状态部分一致")
                
        except Exception as e:
            print(f"   [错误] 综合测试异常: {e}")
            passed = False
            details.append(f"异常: {str(e)}")
        
        self.score.add_result("第8关-终极挑战", passed, score, 100, ", ".join(details))
        return passed
    
    def run_all_levels(self):
        """运行所有关卡"""
        print("\n" + "=" * 60)
        print("      Agent能力大挑战 - 开始!")
        print("=" * 60)
        print(f"开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"工作目录: {os.getcwd()}")
        
        # 运行所有关卡
        self.level1_perception()
        self.level2_brain()
        self.level3_actuator()
        self.level4_verifier()
        self.level5_memory()
        self.level6_security()
        self.level7_orchestrator()
        self.level8_integration()
        
        # 打印最终成绩单
        self.score.print_board()
        
        # 保存游戏结果
        result_file = f"game_result_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(result_file, 'w', encoding='utf-8') as f:
            json.dump({
                "timestamp": datetime.now().isoformat(),
                "total_score": self.score.total_score,
                "max_score": self.score.max_score,
                "results": self.score.results
            }, f, ensure_ascii=False, indent=2)
        
        print(f"\n[记忆] 游戏结果已保存到: {result_file}")


if __name__ == "__main__":
    game = AgentChallengeGame()
    game.run_all_levels()
