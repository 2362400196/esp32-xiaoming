// 插件脚手架模板与权限清单（从 DeveloperView 迁出，供在线编辑器使用）

export const TEMPLATE_PLUGIN = `"""插件：在此编写工具函数（默认示例：语音播报）

输入一段话，直接让当前绑定的设备播放出来（服务端边合成边推流，设备实时出声）。
"""

from src.use_cases.sdk.tools import tool
from src.use_cases.sdk.services import speak_to_device


@tool(cache=False)
async def speak_text(text: str = "", tool_manager=None) -> str:
    """语音播报：输入一段话，直接让当前绑定的设备播放出来。

    Args:
        text: 要播报的文本（一段话）

    Returns:
        播报结果说明
    """
    if not text or not text.strip():
        return "播报失败：请先输入要播报的文本"
    ok = await speak_to_device("", text, tool_manager=tool_manager)
    if not ok:
        return "播报失败：设备离线或语音服务不可用"
    return "正在播报"
`

export const templateManifest = (slug, name, desc, perms) => JSON.stringify({
  id: slug,
  name: name,
  version: "1.0.0",
  description: desc,
  api_version: "1.0",
  frontend: true,
  frontend_config: {
    nav_label: name,
    nav_icon: "box",
    width: "full"
  },
  category: "general",
  tags: [],
  requires: [],
  permissions: perms,
  config_fields: [],
}, null, 2)

export const TEMPLATE_FRONTEND = `<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>插件页面</title>
<style>
* { box-sizing: border-box; }
body {
  margin: 0; padding: 20px; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  background: #e9f0f4; color: #12212e; min-height: 100vh;
}
.card {
  background: rgba(255,255,255,0.85); backdrop-filter: blur(14px);
  border: 1px solid rgba(255,255,255,0.6); border-radius: 16px;
  padding: 24px; max-width: 640px; margin: 0 auto;
}
h2 { margin: 0 0 4px; font-size: 20px; }
p { margin: 0 0 16px; color: #5b6b78; font-size: 14px; }
.device-bar { font-size: 13px; color: #5b6b78; margin-bottom: 16px; }
.device-bar .name { color: #059669; font-weight: 600; }
</style>
</head>
<body>
<div class="card">
  <h2>插件页面</h2>
  <p>欢迎使用你的插件！</p>
  <div class="device-bar">当前设备：<span class="name" id="deviceName">—</span></div>
  <div id="content">
    <p>在这里编写你的插件 UI 内容。</p>
  </div>
</div>
<script>
const did = new URLSearchParams(window.location.search).get('device_id');
if (did) document.getElementById('deviceName').textContent = did;
async function api(path, opts) {
  let token = localStorage.getItem('espai_token') || '';
  let headers = { 'Content-Type': 'application/json' };
  if (token) headers['Authorization'] = 'Bearer ' + token;
  let res = await fetch(path, { headers, ...opts });
  return res.json();
}
try { window.parent.postMessage({ type: 'ready' }, '*'); } catch(e) {}
<\/script>
</body>
</html>`

// 与后端权限模型对齐（src/infrastructure/plugin_security.py + SDK require_permission 调用点）
// 按使用频率排序：常用在前，危险在后
export const ALL_PERMS = [
  { id: 'network', desc: '发起外部 HTTP 请求（调 API、SSE 流式）' },
  { id: 'device', desc: '给设备下发指令、控制屏幕/硬件/播放音乐' },
  { id: 'kv', desc: '插件键值存储（保存用户配置，按设备隔离）' },
  { id: 'ltm', desc: '读写设备长期记忆（记住用户偏好）' },
  { id: 'db', desc: '读写数据库（日记、用户画像）' },
  { id: 'llm', desc: '调用大模型对话（llm_chat / llm_generate）' },
  { id: 'tts', desc: '调用语音合成（tts_synthesize）' },
  { id: 'billing', desc: '上报本轮用量到计费系统（ASR/LLM/TTS）' },
  { id: 'env_read', desc: '读取环境变量（获取 API Key 等配置）' },
  { id: 'file_read', desc: '读取插件目录和状态目录的文件' },
  { id: 'file_write', desc: '写入插件目录和状态目录' },
  // 注意：subprocess / exec 未纳入可选权限——沙箱 RPC 未实现这两个操作
  // （声明了也无法执行），且属于高危能力，不提供给第三方插件
]
