# 安全层模块 (Security)

## 概述

安全层负责防止Agent执行危险操作，提供审批门控和操作日志功能。

## 文件结构

```
modules/security.py    # 安全层实现
test_security.py       # 单元测试
example_security.py    # 使用示例
```

## 核心类

### BasicSecurity

基础安全层实现，继承自`Security`接口。

```python
from modules.security import create_security

security = create_security()
```

## 核心功能

### 动作检查

```python
action = Action(action=ActionType.KEY, keys=["alt", "f4"])

# 检查是否安全
result = security.check(action)
print(f"检查结果: {result}")
```

### 审批门控

```python
# 自动审批模式
security = create_security({"auto_approve": True})

# 手动审批模式
security.set_auto_approve(False)

# 请求审批
result = security.require_approval(action)
```

### 操作日志

```python
# 记录操作
security.log_action(action, success=True)

# 获取日志
logs = security.get_logs(date="2024-01-01")
```

## 危险动作

以下动作需要审批：

| 动作 | 说明 |
|------|------|
| ALT+F4 | 关闭程序 |
| CTRL+W | 关闭标签 |
| CTRL+Q | 退出 |
| DELETE | 删除 |

## 使用示例

```python
from modules.security import create_security
from interfaces import Action, ActionType

security = create_security({"auto_approve": True})

# 安全动作
action = Action(action=ActionType.CLICK, target={"text": "确定"})
result = security.check(action)  # True

# 危险动作
action = Action(action=ActionType.KEY, keys=["alt", "f4"])
result = security.check(action)  # 需要审批
```

## 配置

```python
config = {
    "log_dir": "security_logs",    # 日志目录
    "auto_approve": False,         # 自动审批
    "approval_required": [         # 需要审批的动作
        ActionType.KEY
    ]
}

security = create_security(config)
```

## 测试

运行单元测试：

```bash
python test_security.py
```

运行使用示例：

```bash
python example_security.py
```

## 后续增强

1. **白名单/黑名单**: 限制可操作范围
2. **审计日志**: 所有操作可追溯
3. **Docker隔离**: 高风险场景才引入
4. **权限管理**: 不同用户不同权限
