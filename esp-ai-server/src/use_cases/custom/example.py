"""
自定义工具示例

开发者只需：
1. 在此目录下创建 .py 文件
2. from src.use_cases.tools_system import tool
3. 用 @tool() 装饰函数
4. 系统启动时自动发现并注册

函数签名中的特殊参数会自动注入：
  - tool_manager: 工具管理器（可访问 channel 发送指令）
  - channel: WebSocket 通道
  - ctx: 上下文
  - fsm: 状态机
"""

from src.use_cases.tools_system import tool


@tool()
def hello(name: str) -> str:
    """向用户打招呼。name 为用户的名字。"""
    return f"你好 {name}！很高兴认识你。"
