"""
测试接口定义是否正确
"""

import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent))

from interfaces import (
    ScreenState, Action, ActionType, ACTIONS,
    Perception, Brain, Actuator, Verifier, Memory, Security, Tools,
    create_action, create_click_action, create_type_action,
    create_key_action, create_wait_action, create_done_action
)


def test_screen_state():
    """测试ScreenState数据类"""
    print("测试ScreenState...")
    
    state = ScreenState(
        screenshot="base64_encoded_image",
        screenshot_path="/tmp/screenshot.png",
        texts=[{"text": "确定", "bbox": [100, 200, 160, 230], "confidence": 0.98}],
        elements=[{"type": "button", "name": "提交", "bbox": [100, 200, 160, 230], "ref": "hwnd:12345"}],
        active_window={"title": "记事本", "hwnd": 12345}
    )
    
    assert state.screenshot == "base64_encoded_image"
    assert state.screenshot_path == "/tmp/screenshot.png"
    assert len(state.texts) == 1
    assert len(state.elements) == 1
    assert state.active_window["title"] == "记事本"
    
    print("[PASS] ScreenState测试通过")


def test_action():
    """测试Action数据类"""
    print("测试Action...")
    
    # 测试点击动作
    click_action = create_click_action({"text": "确定"})
    assert click_action.action == ActionType.CLICK
    assert click_action.target == {"text": "确定"}
    
    # 测试输入动作
    type_action = create_type_action("hello world")
    assert type_action.action == ActionType.TYPE
    assert type_action.text == "hello world"
    
    # 测试快捷键动作
    key_action = create_key_action(["ctrl", "c"])
    assert key_action.action == ActionType.KEY
    assert key_action.keys == ["ctrl", "c"]
    
    # 测试等待动作
    wait_action = create_wait_action({"text": "加载完成"})
    assert wait_action.action == ActionType.WAIT
    assert wait_action.condition == {"text": "加载完成"}
    
    # 测试完成动作
    done_action = create_done_action()
    assert done_action.action == ActionType.DONE
    
    print("[PASS] Action测试通过")


def test_action_types():
    """测试动作类型枚举"""
    print("测试ActionType...")
    
    assert ActionType.CLICK == "click"
    assert ActionType.TYPE == "type"
    assert ActionType.SELECT == "select"
    assert ActionType.EXPAND == "expand"
    assert ActionType.KEY == "key"
    assert ActionType.WAIT == "wait"
    assert ActionType.DONE == "done"
    
    print("[PASS] ActionType测试通过")


def test_actions_dict():
    """测试ACTIONS常量"""
    print("测试ACTIONS...")
    
    assert "click" in ACTIONS
    assert "type" in ACTIONS
    assert "select" in ACTIONS
    assert "expand" in ACTIONS
    assert "key" in ACTIONS
    assert "wait" in ACTIONS
    assert "done" in ACTIONS
    
    print("[PASS] ACTIONS测试通过")


def test_interfaces():
    """测试接口类定义"""
    print("测试接口类...")
    
    # 验证接口类存在且是抽象类
    assert hasattr(Perception, 'capture')
    assert hasattr(Perception, 'find_element')
    assert hasattr(Perception, 'find_text')
    
    assert hasattr(Brain, 'decide')
    assert hasattr(Brain, 'plan')
    assert hasattr(Brain, 'update_state')
    
    assert hasattr(Actuator, 'execute')
    assert hasattr(Actuator, 'click')
    assert hasattr(Actuator, 'type_text')
    assert hasattr(Actuator, 'press_keys')
    
    assert hasattr(Verifier, 'verify')
    assert hasattr(Verifier, 'assert_text')
    assert hasattr(Verifier, 'assert_image')
    
    assert hasattr(Memory, 'save')
    assert hasattr(Memory, 'load')
    assert hasattr(Memory, 'save_state')
    assert hasattr(Memory, 'get_history')
    
    assert hasattr(Security, 'check')
    assert hasattr(Security, 'require_approval')
    assert hasattr(Security, 'log_action')
    
    assert hasattr(Tools, 'read_file')
    assert hasattr(Tools, 'write_file')
    assert hasattr(Tools, 'http_get')
    assert hasattr(Tools, 'clipboard_read')
    assert hasattr(Tools, 'clipboard_write')
    
    print("[PASS] 接口类测试通过")


def test_create_action_helpers():
    """测试动作创建辅助函数"""
    print("测试辅助函数...")
    
    # 测试通用create_action
    action = create_action("click", target={"text": "确定"})
    assert action.action == "click"
    assert action.target == {"text": "确定"}
    
    print("[PASS] 辅助函数测试通过")


if __name__ == "__main__":
    print("=" * 50)
    print("接口定义测试")
    print("=" * 50)
    
    try:
        test_screen_state()
        test_action()
        test_action_types()
        test_actions_dict()
        test_interfaces()
        test_create_action_helpers()
        
        print("=" * 50)
        print("所有测试通过！")
        print("=" * 50)
    except Exception as e:
        print(f"测试失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
