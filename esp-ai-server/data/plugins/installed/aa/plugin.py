from src.use_cases.sdk.tools import tool
from src.use_cases.sdk.storage import plugin_data_write, plugin_data_read, plugin_data_list, plugin_data_delete
from src.use_cases.sdk.utils import json_dumps


@tool(cache=False)
async def file_write_text(filename: str = "note.txt", content: str = "", tool_manager=None) -> str:
    """把文本写入插件目录下的文件（用于缓存/自定义日志）。
    参数 filename: 文件名；content: 内容"""
    if content == "":
        return "请提供要写入的内容"
    plugin_data_write(filename, content, tool_manager=tool_manager)
    return f"已写入 {filename}"


@tool()
async def file_read_text(filename: str = "note.txt", tool_manager=None) -> str:
    """读取插件目录下的文件内容。
    参数 filename: 文件名"""
    content = plugin_data_read(filename, tool_manager=tool_manager)
    if content is None:
        return f"文件 {filename} 不存在"
    return content


@tool()
async def file_list_all(tool_manager=None) -> str:
    """列出插件目录下的所有文件。"""
    return json_dumps(plugin_data_list(tool_manager=tool_manager) or [])


@tool(cache=False)
async def file_remove(filename: str = "note.txt", tool_manager=None) -> str:
    """删除插件目录下的一个文件。"""
    ok = plugin_data_delete(filename, tool_manager=tool_manager)
    return f"已删除 {filename}" if ok else f"删除失败（{filename} 可能不存在）"