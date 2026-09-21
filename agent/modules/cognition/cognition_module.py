"""
决策推理模块
提供AI推理、任务规划、决策生成等功能
"""

import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Any

# 添加父目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from base_module import BaseModule

try:
    import openai
except ImportError:
    print("请安装openai: pip install openai")
    sys.exit(1)


class CognitionModule(BaseModule):
    """决策推理模块"""
    
    def __init__(self, config=None):
        super().__init__(config)
        self.client = None
        self.model = None
    
    def initialize(self):
        """初始化模块"""
        super().initialize()
        
        # 初始化AI客户端
        provider = self.get_config("provider", "openai")
        api_key = self.get_config("api_key", "")
        base_url = self.get_config("base_url", "")
        self.model = self.get_config("model", "gpt-4v")
        
        if provider == "openai":
            self.client = openai.OpenAI(
                api_key=api_key,
                base_url=base_url if base_url else None
            )
        elif provider == "zhipu":
            self.client = openai.OpenAI(
                api_key=api_key,
                base_url=base_url or "https://open.bigmodel.cn/api/paas/v4"
            )
        
        self.logger.info(f"CognitionModule initialized with provider: {provider}")
    
    def process(self, input_data: dict) -> dict:
        """
        处理决策请求
        
        Args:
            input_data: 包含action和参数的字典
            
        Returns:
            决策结果
        """
        action = input_data.get("action")
        
        if action == "analyze_screenshot":
            screenshot = input_data.get("screenshot")
            task = input_data.get("task", "")
            return self.analyze_screenshot(screenshot, task)
        
        elif action == "plan_next_action":
            state = input_data.get("state", {})
            return self.plan_next_action(state)
        
        elif action == "generate_command":
            intent = input_data.get("intent", "")
            return self.generate_command(intent)
        
        elif action == "validate_result":
            result = input_data.get("result")
            expected = input_data.get("expected")
            return self.validate_result(result, expected)
        
        elif action == "handle_error":
            error = input_data.get("error", "")
            context = input_data.get("context", {})
            return self.handle_error(error, context)
        
        elif action == "chat":
            message = input_data.get("message", "")
            context = input_data.get("context", {})
            return self.chat(message, context)
        
        else:
            return {"success": False, "error": f"Unknown action: {action}"}
    
    def analyze_screenshot(self, screenshot: Any, task: str = "") -> dict:
        """
        AI分析截图
        
        Args:
            screenshot: 截图数据
            task: 当前任务描述
            
        Returns:
            分析结果
        """
        try:
            # 将截图转换为base64
            import base64
            import io
            from PIL import Image
            
            if isinstance(screenshot, Image.Image):
                img = screenshot
            else:
                img = Image.open(screenshot)
            
            # 转换为RGB
            if img.mode != 'RGB':
                img = img.convert('RGB')
            
            # 保存为bytes
            img_bytes = io.BytesIO()
            img.save(img_bytes, format='PNG')
            img_bytes.seek(0)
            img_base64 = base64.b64encode(img_bytes.getvalue()).decode('utf-8')
            
            # 构建prompt
            prompt = f"""
            分析这个截图，告诉我：
            1. 当前屏幕上显示什么内容？
            2. 有哪些可交互的UI元素（按钮、输入框、菜单等）？
            3. 如果有任务："{task}"，下一步应该做什么？
            
            请用JSON格式返回，包含以下字段：
            {{
                "screen_content": "屏幕内容描述",
                "ui_elements": [{{"type": "元素类型", "position": "位置", "description": "描述"}}],
                "next_action": "下一步操作建议",
                "confidence": 0.0-1.0
            }}
            """
            
            # 调用AI模型
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": prompt
                            },
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/png;base64,{img_base64}"
                                }
                            }
                        ]
                    }
                ],
                max_tokens=1000
            )
            
            # 解析响应
            content = response.choices[0].message.content
            
            # 尝试解析JSON
            try:
                # 提取JSON部分
                import re
                json_match = re.search(r'\{.*\}', content, re.DOTALL)
                if json_match:
                    result = json.loads(json_match.group())
                    return {"success": True, "analysis": result}
                else:
                    return {"success": True, "analysis": {"raw_response": content}}
            except json.JSONDecodeError:
                return {"success": True, "analysis": {"raw_response": content}}
        
        except Exception as e:
            self.logger.error(f"Analyze screenshot failed: {e}")
            return {"success": False, "error": str(e)}
    
    def plan_next_action(self, state: dict) -> dict:
        """
        规划下一步操作
        
        Args:
            state: 当前状态
            
        Returns:
            规划结果
        """
        try:
            # 构建prompt
            prompt = f"""
            根据当前状态，规划下一步操作。
            
            当前状态：
            {json.dumps(state, ensure_ascii=False, indent=2)}
            
            请用JSON格式返回，包含以下字段：
            {{
                "action": "操作类型",
                "parameters": {{}},
                "reason": "原因说明",
                "priority": "high/medium/low"
            }}
            
            操作类型可以是：
            - click: 点击
            - type: 输入文字
            - hotkey: 快捷键
            - wait: 等待
            - screenshot: 截屏
            - done: 任务完成
            """
            
            # 调用AI模型
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                max_tokens=500
            )
            
            # 解析响应
            content = response.choices[0].message.content
            
            # 尝试解析JSON
            try:
                import re
                json_match = re.search(r'\{.*\}', content, re.DOTALL)
                if json_match:
                    result = json.loads(json_match.group())
                    return {"success": True, "plan": result}
                else:
                    return {"success": True, "plan": {"raw_response": content}}
            except json.JSONDecodeError:
                return {"success": True, "plan": {"raw_response": content}}
        
        except Exception as e:
            self.logger.error(f"Plan next action failed: {e}")
            return {"success": False, "error": str(e)}
    
    def generate_command(self, intent: str) -> dict:
        """
        根据意图生成命令
        
        Args:
            intent: 用户意图
            
        Returns:
            生成的命令
        """
        try:
            prompt = f"""
            根据以下意图，生成具体的执行命令。
            
            意图：{intent}
            
            可用的命令格式：
            1. 点击：{{"action": "click", "x": 100, "y": 200}}
            2. 输入：{{"action": "type", "text": "hello"}}
            3. 快捷键：{{"action": "hotkey", "keys": ["ctrl", "c"]}}
            4. 等待：{{"action": "wait", "seconds": 2}}
            5. 截屏：{{"action": "screenshot", "path": "screen.png"}}
            
            请用JSON格式返回命令列表。
            """
            
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                max_tokens=500
            )
            
            content = response.choices[0].message.content
            
            try:
                import re
                json_match = re.search(r'\{.*\}', content, re.DOTALL)
                if json_match:
                    result = json.loads(json_match.group())
                    return {"success": True, "commands": result}
                else:
                    return {"success": True, "commands": {"raw_response": content}}
            except json.JSONDecodeError:
                return {"success": True, "commands": {"raw_response": content}}
        
        except Exception as e:
            self.logger.error(f"Generate command failed: {e}")
            return {"success": False, "error": str(e)}
    
    def validate_result(self, result: Any, expected: Any) -> dict:
        """
        验证执行结果
        
        Args:
            result: 实际结果
            expected: 期望结果
            
        Returns:
            验证结果
        """
        try:
            # 简单验证逻辑
            if result == expected:
                return {"success": True, "valid": True, "message": "结果匹配"}
            
            # 如果是字典，比较特定字段
            if isinstance(result, dict) and isinstance(expected, dict):
                for key in expected:
                    if key not in result:
                        return {"success": True, "valid": False, "message": f"缺少字段: {key}"}
                    if result[key] != expected[key]:
                        return {"success": True, "valid": False, "message": f"字段 {key} 不匹配"}
                
                return {"success": True, "valid": True, "message": "所有字段匹配"}
            
            return {"success": True, "valid": False, "message": "结果不匹配"}
        
        except Exception as e:
            self.logger.error(f"Validate result failed: {e}")
            return {"success": False, "error": str(e)}
    
    def handle_error(self, error: str, context: dict) -> dict:
        """
        处理错误
        
        Args:
            error: 错误信息
            context: 上下文
            
        Returns:
            处理建议
        """
        try:
            prompt = f"""
            处理以下错误，给出处理建议。
            
            错误信息：{error}
            
            上下文：
            {json.dumps(context, ensure_ascii=False, indent=2)}
            
            请用JSON格式返回，包含以下字段：
            {{
                "suggestion": "处理建议",
                "retry": true/false,
                "alternative": "替代方案"
            }}
            """
            
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                max_tokens=500
            )
            
            content = response.choices[0].message.content
            
            try:
                import re
                json_match = re.search(r'\{.*\}', content, re.DOTALL)
                if json_match:
                    result = json.loads(json_match.group())
                    return {"success": True, "handling": result}
                else:
                    return {"success": True, "handling": {"raw_response": content}}
            except json.JSONDecodeError:
                return {"success": True, "handling": {"raw_response": content}}
        
        except Exception as e:
            self.logger.error(f"Handle error failed: {e}")
            return {"success": False, "error": str(e)}
    
    def chat(self, message: str, context: dict = None) -> dict:
        """
        与AI对话
        
        Args:
            message: 用户消息
            context: 上下文
            
        Returns:
            AI回复
        """
        try:
            messages = []
            
            # 添加上下文
            if context:
                messages.append({
                    "role": "system",
                    "content": f"上下文：{json.dumps(context, ensure_ascii=False)}"
                })
            
            messages.append({
                "role": "user",
                "content": message
            })
            
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_tokens=1000
            )
            
            content = response.choices[0].message.content
            return {"success": True, "response": content}
        
        except Exception as e:
            self.logger.error(f"Chat failed: {e}")
            return {"success": False, "error": str(e)}