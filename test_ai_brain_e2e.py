import json
import time
import requests
from ai_brain import decide

class AIBrainE2ETest:
    def __init__(self):
        self.test_results = []
        
    def test_connection(self):
        """测试LM Studio连接"""
        print("=== 测试1: 检查LM Studio连接 ===")
        try:
            response = requests.get("http://localhost:1234/v1/models", timeout=5)
            if response.status_code == 200:
                models = response.json().get("data", [])
                print(f"LM Studio连接成功，可用模型: {len(models)}个")
                return True
            else:
                print(f"LM Studio连接失败，状态码: {response.status_code}")
                return False
        except Exception as e:
            print(f"无法连接LM Studio: {e}")
            return False
    
    def test_task_open_calculator(self):
        """测试任务：打开计算器"""
        print("\n=== 测试2: 打开计算器 ===")
        screen_desc = "当前屏幕显示Windows桌面，任务栏在底部，有开始菜单图标"
        goal = "打开计算器"
        
        print(f"屏幕描述: {screen_desc}")
        print(f"任务目标: {goal}")
        
        action = decide(screen_desc, goal)
        print(f"AI决策: {action}")
        
        if "error" in action:
            print(f"AI决策失败: {action['error']}")
            return False
        
        # 验证动作格式
        required_fields = ["action", "target"]
        for field in required_fields:
            if field not in action:
                print(f"动作格式错误: 缺少字段 '{field}'")
                return False
        
        print("AI决策成功")
        return True
    
    def test_task_open_notepad_type(self):
        """测试任务：打开记事本，输入Hello"""
        print("\n=== 测试3: 打开记事本，输入Hello ===")
        screen_desc = "当前屏幕显示Windows桌面，任务栏在底部"
        goal = "打开记事本，输入Hello"
        
        print(f"屏幕描述: {screen_desc}")
        print(f"任务目标: {goal}")
        
        action = decide(screen_desc, goal)
        print(f"AI决策: {action}")
        
        if "error" in action:
            print(f"AI决策失败: {action['error']}")
            return False
        
        # 验证动作格式
        if "action" not in action:
            print("动作格式错误: 缺少action字段")
            return False
        
        print("AI决策成功")
        return True
    
    def test_task_open_browser_search(self):
        """测试任务：打开浏览器，搜索Python"""
        print("\n=== 测试4: 打开浏览器，搜索Python ===")
        screen_desc = "当前屏幕显示Windows桌面，任务栏在底部"
        goal = "打开浏览器，搜索Python"
        
        print(f"屏幕描述: {screen_desc}")
        print(f"任务目标: {goal}")
        
        action = decide(screen_desc, goal)
        print(f"AI决策: {action}")
        
        if "error" in action:
            print(f"AI决策失败: {action['error']}")
            return False
        
        # 验证动作格式
        if "action" not in action:
            print("动作格式错误: 缺少action字段")
            return False
        
        print("AI决策成功")
        return True
    
    def run_all_tests(self):
        """运行所有测试"""
        print("开始AI Brain端到端测试...")
        start_time = time.time()
        
        # 测试连接
        if not self.test_connection():
            print("\nLM Studio未启动或无法连接，请先启动LM Studio")
            print("步骤：")
            print("1. 打开LM Studio")
            print("2. 加载模型: E:\\AI\\models\\qwen2.5-coder-7b-instruct-q4_k_m.gguf")
            print("3. 启动本地服务器（端口1234）")
            return False
        
        # 运行任务测试
        tests = [
            self.test_task_open_calculator,
            self.test_task_open_notepad_type,
            self.test_task_open_browser_search
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
        
        return passed >= 2  # 至少2个测试通过

if __name__ == "__main__":
    tester = AIBrainE2ETest()
    success = tester.run_all_tests()
    
    if success:
        print("\nAI Brain端到端测试通过")
    else:
        print("\nAI Brain端到端测试失败")