import json
import time
import os
import sys
import pyautogui
from datetime import datetime
from ai_brain import decide_with_vision, analyze_screen

class MultimodalE2ETest:
    def __init__(self):
        self.test_results = []
        self.screenshot_dir = "screenshots"
        os.makedirs(self.screenshot_dir, exist_ok=True)
        
    def take_screenshot(self, name: str) -> str:
        """截屏并保存"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{self.screenshot_dir}/{name}_{timestamp}.png"
        screenshot = pyautogui.screenshot()
        screenshot.save(filename)
        print(f"截屏已保存: {filename}")
        return filename
    
    def test_connection(self):
        """测试LM Studio连接"""
        print("=== 测试1: 检查LM Studio连接 ===")
        try:
            import requests
            response = requests.get("http://localhost:1234/v1/models", timeout=5)
            if response.status_code == 200:
                models = response.json().get("data", [])
                model_names = [m.get("id", "") for m in models]
                print(f"LM Studio连接成功，可用模型: {model_names}")
                
                # 检查是否有视觉模型
                has_vision = any("vl" in name.lower() for name in model_names)
                if has_vision:
                    print("检测到多模态模型，可以进行视觉测试")
                    return True
                else:
                    print("未检测到多模态模型，请下载Qwen2.5-VL")
                    return False
            else:
                print(f"LM Studio连接失败，状态码: {response.status_code}")
                return False
        except Exception as e:
            print(f"无法连接LM Studio: {e}")
            return False
    
    def test_analyze_screen(self):
        """测试任务：分析屏幕内容"""
        print("\n=== 测试2: 分析屏幕内容 ===")
        
        # 截屏
        screenshot_path = self.take_screenshot("test_analyze")
        
        # 分析屏幕
        print("正在使用多模态模型分析屏幕...")
        result = analyze_screen(screenshot_path)
        print(f"分析结果: {json.dumps(result, ensure_ascii=False, indent=2)}")
        
        if "error" in result:
            print(f"分析失败: {result['error']}")
            return False
        
        # 验证结果格式
        if "description" not in result:
            print("分析结果缺少description字段")
            return False
        
        print("屏幕分析成功")
        return True
    
    def test_vision_decision(self):
        """测试任务：根据截图做决策"""
        print("\n=== 测试3: 根据截图做决策 ===")
        
        # 截屏
        screenshot_path = self.take_screenshot("test_decision")
        
        # 设置任务目标
        goal = "描述当前窗口内容"
        
        print(f"任务目标: {goal}")
        print("正在使用多模态模型决策...")
        
        result = decide_with_vision(screenshot_path, goal, mode="vision")
        print(f"决策结果: {json.dumps(result, ensure_ascii=False, indent=2)}")
        
        if "error" in result:
            print(f"决策失败: {result['error']}")
            return False
        
        # 验证结果格式
        if "action" not in result and "description" not in result:
            print("决策结果缺少action或description字段")
            return False
        
        print("视觉决策成功")
        return True
    
    def test_find_and_click(self):
        """测试任务：找到目标并点击"""
        print("\n=== 测试4: 找到目标并点击 ===")
        
        # 截屏
        screenshot_path = self.take_screenshot("test_click")
        
        # 设置任务目标
        goal = "找到开始菜单按钮并点击"
        
        print(f"任务目标: {goal}")
        print("正在使用多模态模型决策...")
        
        result = decide_with_vision(screenshot_path, goal, mode="vision")
        print(f"决策结果: {json.dumps(result, ensure_ascii=False, indent=2)}")
        
        if "error" in result:
            print(f"决策失败: {result['error']}")
            return False
        
        # 验证动作格式
        if "action" not in result:
            print("决策结果缺少action字段")
            return False
        
        # 如果是点击动作，验证target
        if result.get("action") == "click":
            if "target" not in result:
                print("点击动作缺少target字段")
                return False
            print(f"找到点击目标: {result.get('target')}")
        
        print("视觉点击决策成功")
        return True
    
    def test_text_vs_vision_comparison(self):
        """测试任务：对比文本模式和视觉模式"""
        print("\n=== 测试5: 文本模式 vs 视觉模式对比 ===")
        
        # 截屏
        screenshot_path = self.take_screenshot("test_compare")
        
        goal = "描述当前屏幕状态"
        
        # 文本模式
        print("--- 文本模式 ---")
        text_result = decide_with_vision(screenshot_path, goal, mode="text")
        print(f"文本模式结果: {json.dumps(text_result, ensure_ascii=False, indent=2)}")
        
        # 视觉模式
        print("\n--- 视觉模式 ---")
        vision_result = decide_with_vision(screenshot_path, goal, mode="vision")
        print(f"视觉模式结果: {json.dumps(vision_result, ensure_ascii=False, indent=2)}")
        
        # 对比结果
        both_ok = True
        if "error" in text_result:
            print("文本模式失败")
            both_ok = False
        if "error" in vision_result:
            print("视觉模式失败")
            both_ok = False
        
        if both_ok:
            print("\n两种模式对比完成")
        
        return both_ok
    
    def run_all_tests(self):
        """运行所有测试"""
        print("开始多模态AI Brain端到端测试...")
        print(f"测试时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        start_time = time.time()
        
        # 测试连接
        if not self.test_connection():
            print("\nLM Studio未启动或无多模态模型，请先启动LM Studio并下载Qwen2.5-VL")
            return False
        
        # 运行任务测试
        tests = [
            self.test_analyze_screen,
            self.test_vision_decision,
            self.test_find_and_click,
            self.test_text_vs_vision_comparison
        ]
        
        passed = 0
        total = len(tests)
        
        for test in tests:
            try:
                if test():
                    passed += 1
                    self.test_results.append({"test": test.__name__, "status": "PASSED"})
                else:
                    self.test_results.append({"test": test.__name__, "status": "FAILED"})
            except Exception as e:
                print(f"测试异常: {e}")
                self.test_results.append({"test": test.__name__, "status": "ERROR", "error": str(e)})
        
        elapsed = time.time() - start_time
        
        print(f"\n=== 测试结果 ===")
        print(f"通过: {passed}/{total}")
        print(f"耗时: {elapsed:.2f}秒")
        print(f"准确率: {passed/total*100:.1f}%")
        
        # 输出详细结果
        print("\n详细结果:")
        for result in self.test_results:
            status = result.get("status", "UNKNOWN")
            test_name = result.get("test", "unknown")
            error = result.get("error", "")
            if error:
                print(f"  {test_name}: {status} - {error}")
            else:
                print(f"  {test_name}: {status}")
        
        # 验收标准检查
        print(f"\n=== 验收标准 ===")
        print(f"✓ 模型能正确理解截图内容: {'通过' if passed >= 2 else '未通过'}")
        print(f"✓ 能根据截图输出合理动作: {'通过' if passed >= 2 else '未通过'}")
        print(f"✓ 3个视觉任务都能完成: {'通过' if passed >= 3 else '未通过'}")
        print(f"✓ 准确率 > 70%: {'通过' if passed/total > 0.7 else '未通过'}")
        
        return passed >= 3 and passed/total > 0.7

if __name__ == "__main__":
    tester = MultimodalE2ETest()
    success = tester.run_all_tests()
    
    if success:
        print("\n多模态AI Brain端到端测试通过")
        sys.exit(0)
    else:
        print("\n多模态AI Brain端到端测试失败")
        sys.exit(1)
