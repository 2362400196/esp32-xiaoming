"""路由注册模块

按业务域拆分的路由文件集合，每个模块导出 ``register_routes(app)`` 函数，
由 ``src.infrastructure.web._register_routes`` 统一调用。
"""
