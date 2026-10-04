"""T28 回归：</think> 标签剥离（引擎层）+ 测试黑匣子隔离（conftest）。

两个病灶：
  1. GLM 等思考模型偶发把 </think> 闭标签和重复草稿漏进最终回复
     （黑匣子 2026-10-04 07:43:33 实录："答案。</think>\n答案。"），
     用户在聊天气泡里直接看到标签字符串。修复：引擎在 _run_loop 提取
     最终回复处剥离——[助手] 日志行、history、UI、黑匣子吃同一份文本，
     一个点全出口干净。
  2. 泵防崩用例的故障注入堆栈经 blackbox.write 落进用户真实黑匣子
     （2026-10-04 07:09/07:10/07:18 三段噪音实录）。conftest.py
     autouse 统一重定向后消除，以后新增用例不必各自记monkeypatch。
"""
from agent_loop import DesktopAgent

from core import blackbox


# ==================== 1. strip_think 单元 ====================

# 生产泄漏原样（黑匣子 gui-20261004.log 07:43:33 run-exit）
PROD_LEAK = ('任务完成。我已经成功打开了记事本并输入了"你好"。</think>\n'
             '任务完成。我已经成功打开了记事本并输入了"你好"。')


def test_strip_think_production_leak():
    from agent_loop import strip_think
    assert strip_think(PROD_LEAK) == \
        '任务完成。我已经成功打开了记事本并输入了"你好"。'


def test_strip_think_classic_block():
    """经典形态：完整 <think>推理</think> + 正式回复"""
    from agent_loop import strip_think
    assert strip_think("<think>先看看屏幕</think>\n最终答案") == "最终答案"


def test_strip_think_trailing_close_tag_only():
    """只有孤立闭标签：去标签保留正文"""
    from agent_loop import strip_think
    assert strip_think("答案。</think>") == "答案。"


def test_strip_think_tags_only_becomes_empty():
    """剥完为空 = 模型没给出可用回复，交给 T8 空回复分支兜底"""
    from agent_loop import strip_think
    assert strip_think("<think></think>") == ""
    assert strip_think("</think>") == ""


def test_strip_think_passthrough():
    from agent_loop import strip_think
    assert strip_think("普通回复，没有标签。") == "普通回复，没有标签。"
    assert strip_think("") == ""


# ==================== 2. 引擎出口（真 DesktopAgent） ====================

def test_engine_final_reply_clean_across_outlets():
    """真引擎跑一单：返回值与 [助手] 日志行都必须无标签。
    history/UI/黑匣子吃的都是这份文本，出口全干净。"""
    logged = []

    class ThinkLLM:
        def chat(self, messages, tools):
            return {"role": "assistant", "content": PROD_LEAK}

    agent = DesktopAgent(ThinkLLM())
    agent.on_log = logged.append
    out = agent.run("打开记事本，输入 你好")

    assert out == '任务完成。我已经成功打开了记事本并输入了"你好"。'
    assert "</think>" not in out and "<think>" not in out
    assert all("</think>" not in ln for ln in logged)


# ==================== 3. conftest 黑匣子隔离 ====================

def test_conftest_redirects_blackbox(tmp_path):
    """测试期间黑匣子必须落在 pytest 临时目录，不再污染真实日志"""
    assert str(tmp_path) in str(blackbox.path())
