"""路由注册模块

按业务域拆分的路由文件集合，每个模块导出 ``router``（APIRouter 实例），
由 ``src.infrastructure.web._register_routes`` 统一通过 ``app.include_router()`` 注册。
"""
