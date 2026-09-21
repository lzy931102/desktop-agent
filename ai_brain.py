import requests
import json
import base64
import io
from typing import Optional, Literal
from PIL import Image

# 模型配置
TEXT_MODEL = "qwen2.5-coder-7b-instruct"
VISION_MODEL = "qwen2.5-vl-7b-instruct"
API_BASE = "http://localhost:1234/v1"

# 图片处理配置
MAX_IMAGE_SIZE = (512, 512)  # 最大图片尺寸


def compress_image(image_path: str, max_size: tuple = MAX_IMAGE_SIZE) -> str:
    """
    压缩图片并返回base64编码
    
    Args:
        image_path: 图片文件路径
        max_size: 最大尺寸 (width, height)
    
    Returns:
        str: base64编码的图片数据
    """
    try:
        img = Image.open(image_path)
        
        # 计算缩放比例
        ratio = min(max_size[0] / img.width, max_size[1] / img.height)
        if ratio < 1:
            new_size = (int(img.width * ratio), int(img.height * ratio))
            img = img.resize(new_size, Image.Resampling.LANCZOS)
        
        # 保存到内存
        buffer = io.BytesIO()
        img.save(buffer, format='PNG', optimize=True)
        
        return base64.b64encode(buffer.getvalue()).decode("utf-8")
    except Exception as e:
        # 如果图片处理失败，返回原始图片
        with open(image_path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")

def decide(screen_description, goal):
    """
    AI Brain: 根据屏幕描述和任务目标，生成结构化动作（文本模式）
    
    Args:
        screen_description: 屏幕的文本描述
        goal: 自然语言任务目标
    
    Returns:
        dict: 结构化动作JSON
    """
    prompt = f"""
你是一个电脑操作 Agent。根据屏幕描述和任务，输出下一步动作。

屏幕描述：{screen_description}
任务：{goal}

输出格式（JSON）：
{{"action": "click/open_app/type/hotkey", "target": "...", "text": "..."}}

只输出 JSON，不要其他内容。
"""
    
    try:
        response = requests.post(
            f"{API_BASE}/chat/completions",
            json={
                "model": TEXT_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.1
            },
            timeout=30
        )
        
        if response.status_code != 200:
            return {"error": f"API请求失败，状态码: {response.status_code}"}
        
        result = response.json()
        
        # 提取AI回复内容
        content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
        
        # 尝试解析JSON
        try:
            # 清理内容，移除可能的markdown代码块标记
            content = content.strip()
            if content.startswith("```"):
                content = content.split("\n", 1)[1]
            if content.endswith("```"):
                content = content.rsplit("```", 1)[0]
            content = content.strip()
            
            action = json.loads(content)
            return action
        except json.JSONDecodeError:
            return {"error": f"无法解析AI回复为JSON: {content}"}
            
    except requests.exceptions.ConnectionError:
        return {"error": "无法连接到LM Studio服务器，请确保服务器已启动"}
    except requests.exceptions.Timeout:
        return {"error": "请求超时，请检查LM Studio服务器状态"}
    except Exception as e:
        return {"error": f"发生错误: {str(e)}"}


def decide_with_vision(image_path: str, goal: str, mode: Literal["vision", "text"] = "vision") -> dict:
    """
    AI Brain: 根据截图和任务目标，生成结构化动作（多模态模式）
    
    Args:
        image_path: 截图文件路径
        goal: 自然语言任务目标
        mode: 模式选择，"vision"使用多模态模型，"text"使用文本模型
    
    Returns:
        dict: 结构化动作JSON
    """
    if mode == "text":
        return decide("当前屏幕显示Windows桌面", goal)
    
    # 压缩并编码图片
    try:
        image_data = compress_image(image_path)
    except FileNotFoundError:
        return {"error": f"找不到图片文件: {image_path}"}
    
    # 构建多模态prompt
    prompt = f"""
你是一个电脑操作 Agent。根据截图和任务，输出下一步动作。

任务：{goal}

请分析截图内容，理解当前屏幕状态，然后输出合适的动作。

输出格式（JSON）：
{{"action": "click/open_app/type/hotkey", "target": "...", "text": "...", "description": "对当前屏幕的简要描述"}}

只输出 JSON，不要其他内容。
"""
    
    try:
        response = requests.post(
            f"{API_BASE}/chat/completions",
            json={
                "model": VISION_MODEL,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/png;base64,{image_data}"
                                }
                            },
                            {
                                "type": "text",
                                "text": prompt
                            }
                        ]
                    }
                ],
                "temperature": 0.1,
                "max_tokens": 1024
            },
            timeout=120
        )
        
        if response.status_code != 200:
            return {"error": f"API请求失败，状态码: {response.status_code}"}
        
        result = response.json()
        
        # 提取AI回复内容
        content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
        
        # 尝试解析JSON
        try:
            content = content.strip()
            if content.startswith("```"):
                content = content.split("\n", 1)[1]
            if content.endswith("```"):
                content = content.rsplit("```", 1)[0]
            content = content.strip()
            
            action = json.loads(content)
            return action
        except json.JSONDecodeError:
            return {"error": f"无法解析AI回复为JSON: {content}"}
            
    except requests.exceptions.ConnectionError:
        return {"error": "无法连接到LM Studio服务器，请确保服务器已启动"}
    except requests.exceptions.Timeout:
        return {"error": "请求超时，请检查LM Studio服务器状态"}
    except Exception as e:
        return {"error": f"发生错误: {str(e)}"}


def analyze_screen(image_path: str) -> dict:
    """
    AI Brain: 分析截图内容，返回屏幕描述
    
    Args:
        image_path: 截图文件路径
    
    Returns:
        dict: 包含屏幕描述的JSON
    """
    try:
        image_data = compress_image(image_path)
    except FileNotFoundError:
        return {"error": f"找不到图片文件: {image_path}"}
    
    prompt = """
请分析这张截图，描述当前屏幕的内容。
包括：
1. 当前打开的应用程序
2. 屏幕上的主要元素
3. 可能的交互元素（按钮、输入框等）

输出格式（JSON）：
{"description": "屏幕描述", "apps": ["应用1", "应用2"], "elements": ["元素1", "元素2"]}

只输出 JSON，不要其他内容。
"""
    
    try:
        response = requests.post(
            f"{API_BASE}/chat/completions",
            json={
                "model": VISION_MODEL,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/png;base64,{image_data}"
                                }
                            },
                            {
                                "type": "text",
                                "text": prompt
                            }
                        ]
                    }
                ],
                "temperature": 0.1,
                "max_tokens": 1024
            },
            timeout=120
        )
        
        if response.status_code != 200:
            return {"error": f"API请求失败，状态码: {response.status_code}"}
        
        result = response.json()
        content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
        
        content = content.strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[1]
        if content.endswith("```"):
            content = content.rsplit("```", 1)[0]
        content = content.strip()
        
        return json.loads(content)
        
    except json.JSONDecodeError:
        return {"error": f"无法解析AI回复为JSON: {content}"}
    except Exception as e:
        return {"error": f"发生错误: {str(e)}"}

def get_screen_description():
    """
    获取屏幕描述（示例实现）
    实际项目中应集成OCR和屏幕分析
    """
    return "当前屏幕显示Windows桌面，任务栏在底部，有开始菜单和系统托盘"

def execute_action(action):
    """
    执行动作（示例实现）
    实际项目中应集成pyautogui等自动化工具
    """
    print(f"执行动作: {action}")
    # 这里应该调用实际的执行逻辑
    return True

if __name__ == "__main__":
    # 测试AI Brain
    screen_desc = get_screen_description()
    goal = "打开计算器"
    
    print(f"屏幕描述: {screen_desc}")
    print(f"任务目标: {goal}")
    print("正在调用AI Brain...")
    
    action = decide(screen_desc, goal)
    print(f"AI决策结果: {action}")
    
    if "error" not in action:
        print("正在执行动作...")
        execute_action(action)