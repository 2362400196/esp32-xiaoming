"""SDK 工具注册 — 插件开发的第一入口。

插件用 @tool 装饰器把函数注册为 LLM 可调用的工具：

    from src.use_cases.sdk.tools import tool, StopPipeline

    @tool(description="查询天气")
    async def get_weather(city: str, tool_manager=None) -> str:
        ...

设计说明：
- 本模块只是对 src/use_cases/tools_system.py 的惰性 re-export（单一实现源），
  不复制任何实现代码，避免出现两套注册行为。
- 插件今后只需 import SDK（src/use_cases/sdk/），无需直接 import 框架模块
  tools_system.py。
- 注意：本模块不要加 ``from __future__ import annotations``——
  @tool 装饰器依赖真实的参数注解对象来推断 JSON Schema 类型。
- 错误约定：工具函数内部建议返回 ``(result, status, detail)`` 元组
  （status: "ok"/"offline"/"timeout"/"error"/"busy"），详见 sdk/__init__.py。
"""

from src.use_cases.tools_system import tool, StopPipeline, ToolDefinition  # noqa: F401
