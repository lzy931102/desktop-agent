from agent_loop import DesktopAgent, LLMClient, load_config

# 加载配置
config = load_config()

# 创建 Agent
agent = DesktopAgent(LLMClient(config))

# 设置回调
agent.on_log = print

# 测试执行
print("=== 测试：打开计算器 ===\n")
result = agent.run("打开计算器")
print(f"\n=== 最终结果 ===")
print(result)
