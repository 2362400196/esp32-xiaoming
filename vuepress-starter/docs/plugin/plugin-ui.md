# 插件 UI 开发指南

插件可以自带前端页面，通过 iframe 嵌入主应用，实现独立的管理界面。本文介绍如何为插件开发 UI 页面。

## 目录结构

一个带 UI 的插件目录结构如下：

```
plugins/my_plugin/
├── plugin.py               # 插件后端逻辑
├── manifest.json           # 插件元数据，声明前端配置
└── frontend/               # 前端静态文件目录
    └── index.html          # 入口页面（必须）
```

`frontend/` 目录下可以有任意静态文件：HTML、CSS、JS、图片等，入口文件必须是 `index.html`。

## manifest.json 配置

在 `manifest.json` 中声明前端页面：

```json
{
    "id": "my_plugin",
    "name": "我的插件",
    "version": "1.0.0",
    "author": "your_name",
    "description": "插件功能描述",
    "api_version": "1.0",
    "optional": true,
    "frontend": true,
    "frontend_config": {
        "nav_label": "我的插件",
        "nav_icon": "star",
        "width": "full"
    },
    "requires": [],
    "config_fields": [],
    "permissions": ["network"]
}
```

### 字段说明

| 字段 | 说明 |
|------|------|
| `frontend` | 设为 `true` 表示插件有前端页面 |
| `frontend_config.nav_label` | 导航栏显示的文字 |
| `frontend_config.nav_icon` | 导航栏图标，使用预置图标名称 |
| `frontend_config.width` | 页面宽度：`full`（全宽）或 `narrow`（窄版） |

### 预置图标

| 图标名称 | 适用场景 |
|----------|----------|
| `server` | 服务器 / 连接管理 |
| `message` | 消息 / 聊天 |
| `clock` | 闹钟 / 定时器 |
| `chart` | 技能 / 统计 |
| `settings` | 配置 / 设置 |
| `cloud` | 云服务 / 远程配置 |
| `bell` | 通知 / 推送 |
| `star` | 成长 / 收藏 |
| `tool` | 工具 / 功能 |

## 基础 HTML 模板

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>插件页面</title>
<style>
/* 样式代码 */
</style>
</head>
<body>
<!-- HTML 内容 -->
<script>
/* JavaScript 代码 */
</script>
</body>
</html>
```

## CSS 样式规范

### 系统 CSS 变量

插件页面可以使用以下 CSS 变量，确保与主应用风格统一：

```css
:root {
  --mint: #10b981;              /* 主色调 - 薄荷绿 */
  --mint-deep: #059669;         /* 主色调深色 */
  --mint-soft: rgba(16,185,129,0.1);   /* 主色调浅色背景 */
  --mint-border: rgba(16,185,129,0.25); /* 主色调边框 */
  --text-main: #1e293b;         /* 主文字色 */
  --text-sub: #64748b;          /* 次要文字色 */
  --bg: #f0f5f0;               /* 背景色 */
  --border: rgba(0,0,0,0.06);  /* 分割线 */
  --danger: #ef4444;            /* 危险/删除操作 */
  --danger-soft: rgba(239,68,68,0.1);
  --radius: 16px;               /* 大圆角 */
  --radius-sm: 10px;            /* 小圆角 */
  --shadow: 0 4px 20px rgba(0,0,0,0.06);
  --glass: linear-gradient(155deg, rgba(255,255,255,0.85), rgba(255,255,255,0.55));
  --glass-border: rgba(255,255,255,0.6);
}
```

### 常用组件样式

**毛玻璃卡片：**

```css
.card {
  background: var(--glass);
  border: 1px solid var(--glass-border);
  border-radius: var(--radius);
  padding: 18px;
  margin-bottom: 12px;
  backdrop-filter: blur(12px);
  box-shadow: var(--shadow);
}
```

**按钮：**

```css
.btn {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 8px 18px; font-size: 13px; font-weight: 600;
  border: none; border-radius: var(--radius-sm);
  cursor: pointer; transition: all 0.25s;
}
.btn-primary { background: var(--mint); color: #fff; }
.btn-primary:hover { background: var(--mint-deep); transform: translateY(-1px); }
.btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }
.btn-ghost { background: transparent; color: var(--text-main); padding: 6px 14px; }
.btn-ghost:hover { background: var(--mint-soft); }
.btn-danger { color: var(--danger); }
.btn-danger:hover { background: var(--danger-soft); }
.btn-sm { padding: 6px 16px; font-size: 12px; border-radius: 8px; }
```

**输入框：**

```css
input, select, textarea {
  width: 100%; padding: 8px 12px; font-size: 13px;
  border: 1px solid var(--border);
  border-radius: 8px; background: rgba(255,255,255,0.8);
  color: var(--text-main); outline: none; font-family: inherit;
  box-sizing: border-box;
}
input:focus, select:focus, textarea:focus {
  border-color: var(--mint);
  box-shadow: 0 0 0 3px var(--mint-soft);
}
```

**状态徽章：**

```css
.badge { font-size: 11px; padding: 2px 8px; border-radius: 99px; font-weight: 600; }
.badge-on { background: var(--mint-soft); color: var(--mint-deep); }
.badge-off { background: var(--danger-soft); color: var(--danger); }
```

**加载动画：**

```css
.spinner {
  width: 28px; height: 28px;
  border: 3px solid var(--mint-soft);
  border-top-color: var(--mint-deep);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }
```

**弹窗（Modal）：**

```css
.modal-mask {
  position: fixed; inset: 0;
  background: rgba(0,0,0,0.3); backdrop-filter: blur(4px);
  display: flex; align-items: center; justify-content: center;
  z-index: 1000;
}
.modal-panel {
  width: 90%; max-width: 460px; max-height: 90vh;
  overflow-y: auto;
}
```

**空状态：**

```css
.empty-state {
  text-align: center; padding: 50px 20px; color: var(--text-sub);
}
.empty-state svg { opacity: 0.35; margin-bottom: 10px; }
.empty-state p { margin: 4px 0; }
```

## 与后端 API 通信（postMessage 代理）

::: tip 设计原则
插件前端（iframe 内）**不直接管理 JWT Token**，所有 API 调用通过 postMessage 交给父应用代理执行。父应用自动携带认证信息，插件前端无需关心鉴权细节。
:::

### 通用 API 请求函数

所有插件前端统一使用以下 SDK 封装：

```javascript
let _apiId = 0
const _pending = {}

// 监听父应用返回的 API 结果
window.addEventListener('message', function(e) {
  const msg = typeof e.data === 'object' ? e.data : {}
  if (msg.type === 'apiResult' && _pending[msg.id]) {
    _pending[msg.id](msg)
    delete _pending[msg.id]
  }
})

// 通过 postMessage 代理调用后端 API
async function sdkApi(path, opts = {}) {
  return new Promise((resolve, reject) => {
    const id = ++_apiId
    _pending[id] = (msg) => {
      if (msg.error) reject(new Error(msg.error))
      else resolve({ data: msg.data, status: msg.status })
    }
    window.parent.postMessage({
      type: 'api', id, path,
      method: opts.method || 'GET',
      body: opts.body || null
    }, '*')
  })
}

// 简化封装，自动处理返回格式
async function api(path, opts = {}) {
  const result = await sdkApi(path, opts)
  return result.data
}
```

### 调用示例

```javascript
// GET 请求
const data = await api('/api/v1/plugins/my_plugin/data')
console.log(data)

// POST 请求
const data = await api('/api/v1/plugins/my_plugin/config', {
  method: 'POST',
  body: { key: 'value' }
})

// PUT 请求
const data = await api('/api/v1/plugins/my_plugin/config', {
  method: 'PUT',
  body: { key: 'new_value' }
})

// DELETE 请求
const data = await api('/api/v1/plugins/my_plugin/data', {
  method: 'DELETE',
  body: { id: 'xxx' }
})
```

### API 返回格式

所有接口统一返回格式：

```json
{
  "code": 0,
  "message": "ok",
  "data": {}
}
```

`code` 为 0 表示成功，非 0 表示失败。

## 与主应用通信（postMessage）

插件页面通过 `window.parent.postMessage` 与主应用通信。

### 消息类型一览

| 方向 | type | 用途 |
|------|------|------|
| 插件 → 父应用 | `ready` | 通知页面已加载 |
| 插件 → 父应用 | `toast` | 显示提示消息 |
| 插件 → 父应用 | `api` | 通过父应用代理调用后端 API |
| 父应用 → 插件 | `apiResult` | API 调用结果返回 |
| 父应用 → 插件 | `deviceChanged` | 推送当前设备信息 |

### 通知就绪

页面加载完成后，通知主应用插件已就绪：

```javascript
try { window.parent.postMessage({ type: 'ready' }, '*'); } catch(e) {}
```

### 显示 Toast 提示

```javascript
try { window.parent.postMessage({ type: 'toast', message: '操作成功' }, '*'); } catch(e) {}
```

### 监听设备信息变更

当用户切换设备时，主应用会发送设备信息：

```javascript
window.addEventListener('message', function(e) {
  try {
    const msg = typeof e.data === 'object' ? e.data : JSON.parse(e.data);
    if (msg.type === 'deviceChanged' && msg.device) {
      // msg.device 包含当前设备信息
      const device = msg.device;
      // device.device_id, device.name, device.online 等
    }
  } catch {}
});
```

### 获取设备 ID（推荐方式）

从 URL 参数获取设备 ID，同时监听 postMessage 更新：

```javascript
let currentDevice = null;

function deviceMac() {
  return currentDevice?.device_id || currentDevice?.id || currentDevice?.mac || '';
}

// 监听设备变更
window.addEventListener('message', function(e) {
  try {
    const msg = typeof e.data === 'object' ? e.data : JSON.parse(e.data);
    if (msg.type === 'deviceChanged' && msg.device) {
      currentDevice = msg.device;
      // 设备变更后的处理逻辑
    }
  } catch {}
});

// 通知主应用已就绪
try { window.parent.postMessage({ type: 'ready' }, '*'); } catch(e) {}

// 从 URL 参数读取设备 ID（兼容 postMessage 未到达的情况）
const did = new URLSearchParams(window.location.search).get('device_id');
if (did) {
  currentDevice = { device_id: did };
  // 初始化加载数据
}
```

## 调用插件工具（通用接口）

前端通过 `POST /api/v1/plugins/{plugin_name}/tool/{tool_name}` 调用插件的 `@tool()` 工具函数。

**设计原则：** 插件工具内部使用 `http_get_json` 等 SDK 函数获取数据，**API Key 等敏感信息不暴露到浏览器**。

```javascript
// 调用天气插件测试工具
const data = await api('/api/v1/plugins/weather/tool/test_weather_query', {
  method: 'POST',
  body: {
    args: { city: '北京' },
    device_id: 'D8:3B:DA:6D:D9:3C'
  }
})
// data 为插件工具返回的 JSON 结果
```

**请求体：**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `args` | object | 否 | 工具参数，如 `{"city": "北京"}` |
| `device_id` | string | 否 | 设备 ID，用于注入该设备的插件配置 |

**原理：** 后端通过 `get_tool(tool_name)` 获取工具定义，注入 `tool_manager` 上下文（含设备插件配置），然后调用插件工具函数。所有插件共用此接口，无需为每个插件单独建路由。

## 本地 Toast 提示

如果不想通过 postMessage 调用主应用 Toast，也可以在插件页面内自行实现：

```javascript
function showToast(msg) {
  const old = document.querySelector('.toast');
  if (old) old.remove();
  const el = document.createElement('div');
  el.className = 'toast';
  el.textContent = msg;
  document.body.appendChild(el);
  setTimeout(() => el.remove(), 2200);
}
```

配套样式：

```css
.toast {
  position: fixed; bottom: 24px; left: 50%; transform: translateX(-50%);
  padding: 10px 24px; background: var(--glass);
  border: 1px solid var(--glass-border); border-radius: var(--radius-sm);
  font-size: 13px; font-weight: 500;
  backdrop-filter: blur(12px); box-shadow: 0 8px 30px rgba(0,0,0,0.1);
  z-index: 2000;
  animation: fadeInUp 0.3s ease;
}
@keyframes fadeInUp {
  from { opacity: 0; transform: translateX(-50%) translateY(16px); }
  to { opacity: 1; transform: translateX(-50%) translateY(0); }
}
```

## 完整示例

以下是一个完整的插件页面，展示列表数据的增删查改：

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>数据管理</title>
<style>
:root {
  --mint: #10b981; --mint-deep: #059669; --mint-soft: rgba(16,185,129,0.1);
  --mint-border: rgba(16,185,129,0.25); --text-main: #1e293b; --text-sub: #64748b;
  --bg: #f0f5f0; --border: rgba(0,0,0,0.06); --danger: #ef4444; --danger-soft: rgba(239,68,68,0.1);
  --radius: 16px; --radius-sm: 10px; --shadow: 0 4px 20px rgba(0,0,0,0.06);
  --glass: linear-gradient(155deg, rgba(255,255,255,0.85), rgba(255,255,255,0.55));
  --glass-border: rgba(255,255,255,0.6);
}
* { box-sizing: border-box; }
body {
  margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  background: var(--bg); color: var(--text-main); min-height: 100vh;
}
.container { max-width: 720px; margin: 0 auto; padding: 20px 16px 40px; }
.header { margin-bottom: 20px; }
.header h1 { font-size: 20px; font-weight: 800; margin: 0 0 4px; }
.header p { font-size: 13px; color: var(--text-sub); margin: 0; }
.device-bar {
  display: flex; align-items: center; justify-content: space-between;
  margin-bottom: 16px; padding: 10px 16px;
  background: var(--glass); border: 1px solid var(--glass-border);
  border-radius: var(--radius-sm); font-size: 13px; backdrop-filter: blur(12px);
}
.device-bar .device-name { font-weight: 600; }
.device-bar .no-device { color: var(--danger); font-weight: 600; }
.toolbar { display: flex; justify-content: flex-end; margin-bottom: 16px; }
.btn {
  display: inline-flex; align-items: center; gap: 6px; padding: 8px 18px;
  font-size: 13px; font-weight: 600; border: none; border-radius: var(--radius-sm);
  cursor: pointer; transition: all 0.25s;
}
.btn-primary { background: var(--mint); color: #fff; }
.btn-primary:hover { background: var(--mint-deep); transform: translateY(-1px); }
.btn-ghost { background: transparent; color: var(--text-main); padding: 6px 14px; }
.btn-ghost:hover { background: var(--mint-soft); }
.btn-danger { color: var(--danger); }
.btn-danger:hover { background: var(--danger-soft); }
.btn-sm { padding: 6px 16px; font-size: 12px; border-radius: 8px; }
.card {
  background: var(--glass); border: 1px solid var(--glass-border);
  border-radius: var(--radius); padding: 18px; margin-bottom: 12px;
  backdrop-filter: blur(12px); box-shadow: var(--shadow);
}
.item-row {
  display: flex; align-items: center; justify-content: space-between;
  padding: 12px 16px; border-bottom: 1px solid var(--border);
}
.item-row:last-child { border-bottom: none; }
.item-title { font-weight: 600; font-size: 14px; }
.item-desc { font-size: 12px; color: var(--text-sub); margin-top: 2px; }
.item-actions { display: flex; gap: 6px; }
.empty-state { text-align: center; padding: 50px 20px; color: var(--text-sub); }
.spinner { width: 28px; height: 28px; border: 3px solid var(--mint-soft); border-top-color: var(--mint-deep); border-radius: 50%; animation: spin 0.8s linear infinite; margin: 0 auto; }
@keyframes spin { to { transform: rotate(360deg); } }
.loading { display: flex; flex-direction: column; align-items: center; gap: 10px; padding: 50px; color: var(--text-sub); }
.modal-mask { position: fixed; inset: 0; background: rgba(0,0,0,0.3); backdrop-filter: blur(4px); display: flex; align-items: center; justify-content: center; z-index: 1000; }
.modal-panel { width: 90%; max-width: 460px; }
.modal-title { font-size: 16px; font-weight: 700; margin: 0 0 16px; }
.form-group { margin-bottom: 12px; }
.form-label { display: block; font-size: 12px; font-weight: 600; margin-bottom: 4px; color: var(--text-sub); }
input, select, textarea {
  width: 100%; padding: 8px 12px; font-size: 13px; border: 1px solid var(--border);
  border-radius: 8px; background: rgba(255,255,255,0.8); color: var(--text-main);
  outline: none; font-family: inherit; box-sizing: border-box;
}
input:focus, select:focus, textarea:focus { border-color: var(--mint); box-shadow: 0 0 0 3px var(--mint-soft); }
.form-actions { display: flex; gap: 8px; justify-content: flex-end; margin-top: 16px; }
</style>
</head>
<body>
<div class="container" id="app">
  <div class="header">
    <h1>数据管理</h1>
    <p>管理插件中的数据</p>
  </div>
  <div class="device-bar">
    <span>设备：<span class="device-name" id="deviceName">未选择</span></span>
    <span class="no-device" id="noDevice" style="display:none">请先选择设备</span>
  </div>
  <div class="toolbar">
    <button class="btn btn-primary" onclick="openAdd()">+ 添加</button>
  </div>
  <div id="list"></div>
  <div class="empty-state" id="emptyState" style="display:none">
    <p>暂无数据</p>
    <p style="font-size:13px;color:var(--text-sub)">点击「添加」创建第一条数据</p>
  </div>
  <div class="loading" id="loading" style="display:none">
    <div class="spinner"></div>
    <p>加载中…</p>
  </div>
</div>

<!-- 添加/编辑弹窗 -->
<div class="modal-mask" id="modalMask" style="display:none" onclick="if(event.target===this)closeForm()">
  <div class="modal-panel card" onclick="event.stopPropagation()">
    <h3 class="modal-title" id="modalTitle">添加</h3>
    <div class="form-group">
      <label class="form-label">名称</label>
      <input id="formName" placeholder="请输入名称" />
    </div>
    <div class="form-group">
      <label class="form-label">描述</label>
      <textarea id="formDesc" placeholder="请输入描述" rows="3"></textarea>
    </div>
    <div class="form-actions">
      <button class="btn btn-ghost" onclick="closeForm()">取消</button>
      <button class="btn btn-primary" id="saveBtn" onclick="save()">保存</button>
    </div>
  </div>
</div>

<script>
let currentDevice = null;
	let items = [];
	let editingId = null;

	function showToast(msg) {
	  const old = document.querySelector('.toast');
	  if (old) old.remove();
	  const el = document.createElement('div');
	  el.className = 'toast';
	  el.textContent = msg;
	  document.body.appendChild(el);
	  setTimeout(() => el.remove(), 2200);
	}

	// --- postMessage SDK（无需管理 JWT） ---
	let _apiId = 0;
	const _pending = {};
	window.addEventListener('message', function(e) {
	  const msg = typeof e.data === 'object' ? e.data : {};
	  if (msg.type === 'apiResult' && _pending[msg.id]) {
	    _pending[msg.id](msg);
	    delete _pending[msg.id];
	  }
	});
	async function api(path, opts = {}) {
	  return new Promise((resolve, reject) => {
	    const id = ++_apiId;
	    _pending[id] = (msg) => {
	      if (msg.error) reject(new Error(msg.error));
	      else resolve(msg.data);
	    };
	    window.parent.postMessage({ type: 'api', id, path, method: opts.method || 'GET', body: opts.body || null }, '*');
	  });
	}

async function loadData() {
	  const mac = currentDevice?.device_id || '';
	  if (!mac) return;
	  document.getElementById('loading').style.display = 'flex';
	  document.getElementById('emptyState').style.display = 'none';
	  document.getElementById('list').innerHTML = '';
	  const data = await api('/api/v1/plugins/my_plugin/data?device_id=' + encodeURIComponent(mac));
	  document.getElementById('loading').style.display = 'none';
	  if (data && data.code === 0) {
	    items = data.data || [];
	    render();
	  } else {
	    showToast(data?.message || '加载失败');
	  }
}

function render() {
  const list = document.getElementById('list');
  const empty = document.getElementById('emptyState');
  if (items.length === 0) {
    list.innerHTML = '';
    empty.style.display = 'block';
    return;
  }
  empty.style.display = 'none';
  list.innerHTML = items.map(item => `
    <div class="card" style="padding:0">
      <div class="item-row">
        <div>
          <div class="item-title">${escapeHtml(item.name)}</div>
          <div class="item-desc">${escapeHtml(item.description || '')}</div>
        </div>
        <div class="item-actions">
          <button class="btn btn-ghost btn-sm" onclick="editItem('${item.id}')">编辑</button>
          <button class="btn btn-ghost btn-sm btn-danger" onclick="deleteItem('${item.id}')">删除</button>
        </div>
      </div>
    </div>
  `).join('');
}

function openAdd() {
  editingId = null;
  document.getElementById('modalTitle').textContent = '添加';
  document.getElementById('formName').value = '';
  document.getElementById('formDesc').value = '';
  document.getElementById('saveBtn').textContent = '保存';
  document.getElementById('modalMask').style.display = 'flex';
}

function editItem(id) {
  const item = items.find(i => i.id === id);
  if (!item) return;
  editingId = id;
  document.getElementById('modalTitle').textContent = '编辑';
  document.getElementById('formName').value = item.name;
  document.getElementById('formDesc').value = item.description || '';
  document.getElementById('saveBtn').textContent = '保存';
  document.getElementById('modalMask').style.display = 'flex';
}

function closeForm() {
  document.getElementById('modalMask').style.display = 'none';
}

async function save() {
  const name = document.getElementById('formName').value.trim();
  const desc = document.getElementById('formDesc').value.trim();
  const mac = currentDevice?.device_id || '';
  if (!name) { showToast('请输入名称'); return; }
  if (!mac) { showToast('请先选择设备'); return; }
  const btn = document.getElementById('saveBtn');
  btn.disabled = true;
  btn.textContent = '保存中…';
  const data = await api('/api/v1/plugins/my_plugin/data', {
	    method: 'POST',
	    body: { device_id: mac, id: editingId, name, description: desc }
	  });
	  btn.disabled = false;
	  btn.textContent = '保存';
	  if (data && data.code === 0) {
	    showToast(editingId ? '已更新' : '已添加');
	    closeForm();
	    await loadData();
	  } else {
	    showToast(data?.message || '保存失败');
  }
}

async function deleteItem(id) {
	  if (!confirm('确定要删除吗？')) return;
	  const mac = currentDevice?.device_id || '';
	  const data = await api('/api/v1/plugins/my_plugin/data', {
	    method: 'DELETE',
	    body: { device_id: mac, id }
	  });
	  if (data && data.code === 0) {
	    showToast('已删除');
	    await loadData();
	  } else {
	    showToast(data?.message || '删除失败');
  }
}

function escapeHtml(s) {
  if (!s) return '';
  const d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}

// 与主应用通信
window.addEventListener('message', function(e) {
  try {
    const msg = typeof e.data === 'object' ? e.data : JSON.parse(e.data);
    if (msg.type === 'deviceChanged' && msg.device) {
      currentDevice = msg.device;
      const mac = currentDevice?.device_id || '';
      document.getElementById('deviceName').textContent = currentDevice?.name || mac || '未选择';
      document.getElementById('noDevice').style.display = mac ? 'none' : 'inline';
      if (mac) loadData();
    }
  } catch {}
});

try { window.parent.postMessage({ type: 'ready' }, '*'); } catch(e) {}

// 从 URL 参数读取设备 ID
const did = new URLSearchParams(window.location.search).get('device_id');
if (did) {
  currentDevice = { device_id: did };
  document.getElementById('deviceName').textContent = did;
  document.getElementById('noDevice').style.display = 'none';
  loadData();
}
</script>
</body>
</html>
```

## 使用开发者工具创建插件 UI

在 Web 管理界面的「开发者」中心创建新插件时，系统会自动生成 UI 模板：

1. 进入「开发者」页面
2. 点击「新建插件」
3. 填写插件信息后，系统会自动创建三个文件：
   - `plugin.py` — 插件后端代码
   - `manifest.json` — 插件配置（含 `frontend: true`）
   - `frontend/index.html` — 前端页面模板

生成的前端模板包含：
- 完整的 CSS 变量和毛玻璃卡片样式
- 设备信息获取逻辑
- 后端 API 调用示例
- 与主应用的 postMessage 通信

## 调试技巧

### 浏览器开发者工具

在插件页面打开后，按 `F12` 打开开发者工具：

- **Console** 标签：查看 JavaScript 日志和错误
- **Network** 标签：查看 API 请求和响应
- **Elements** 标签：查看和调试 HTML / CSS

### 常见问题

**页面加载后一直显示「加载插件页面…」**
- 检查 `manifest.json` 中 `frontend` 是否设为 `true`
- 检查 `frontend/index.html` 文件是否存在
- 检查浏览器控制台是否有错误

**API 请求返回 401 未授权**
- 确保已登录（Token 由父应用管理，无需手动处理）
- 如使用 `api()` 函数仍出现 401，检查父应用是否正确维护 Token

**保存配置后下次打开又没了**
- 确认插件声明了 `kv` 权限，配置通过 `save_config` 工具写入 KV 存储
- 配置存储在 `data/plugins/kv/<插件id>.json`，不依赖主数据库

**postMessage 通信失败**
- 确保在页面加载后调用了 `window.parent.postMessage({ type: 'ready' }, '*')`
- 检查 postMessage 的 `type` 字段是否正确

**页面样式与主应用不一致**
- 使用本文档提供的 CSS 变量和样式规范
- 避免使用硬编码的颜色值

### 热更新

修改插件代码后，无需重启服务器，只需调用：

```
POST /api/v1/plugins/reload
```

然后刷新浏览器页面即可看到更新。

## 开发规范

1. **样式统一**：使用系统提供的 CSS 变量，保持与主应用风格一致
2. **响应式**：适配移动端和桌面端，建议 `max-width: 720px` 居中布局
3. **错误处理**：所有 API 请求都应处理失败情况，给用户友好提示
4. **加载状态**：数据加载时应显示加载动画，避免白屏
5. **空状态**：无数据时应显示友好的空状态提示
6. **命名规范**：插件 ID 使用英文小写和下划线，如 `my_plugin`
7. **文件编码**：所有文件使用 UTF-8 编码
8. **安全性**：不要在前端暴露敏感信息（密钥、密码等），所有 API 调用走 postMessage 代理，由父应用统一管理 JWT Token；插件配置通过 `save_config` 工具写入 KV 存储，不经过主数据库