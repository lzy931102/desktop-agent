import requests
import json

def decide(screen_description, goal):
    """
    AI Brain: 根据屏幕描述和任务目标，生成结构化动作
    
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
            "http://localhost:1234/v1/chat/completions",
            json={
                "model": "qwen2.5-coder-7b-instruct",
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