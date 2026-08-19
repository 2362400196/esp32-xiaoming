// ============ API 封装（复用 esp-ai-server 全部接口） ============
const BASE = ''

let _token = localStorage.getItem('espai_token') || ''
let _user = JSON.parse(localStorage.getItem('espai_user') || 'null')

export function getToken() { return _token }
export function getUser() { return _user }

export function setAuth(token, user) {
  _token = token || ''
  _user = user || null
  if (token) localStorage.setItem('espai_token', token); else localStorage.removeItem('espai_token')
  if (user) localStorage.setItem('espai_user', JSON.stringify(user)); else localStorage.removeItem('espai_user')
}

export function isLoggedIn() { return !!_token }

async function request(path, method = 'GET', body = null) {
  const headers = { 'Content-Type': 'application/json' }
  if (_token) headers['Authorization'] = 'Bearer ' + _token
  try {
    const res = await fetch(BASE + path, {
      method,
      headers,
      body: body ? JSON.stringify(body) : null,
    })
    let data = null
    try { data = await res.json() } catch { data = null }
    if (res.status === 401) setAuth('', null)
    return { status: res.status, data }
  } catch (err) {
    console.error('[API] request 失败:', path, err)
    return { status: 0, data: null, error: String(err) }
  }
}

export const api = {
  // 认证
  login: (email, password) => request('/api/v1/auth/login', 'POST', { email, password }),
  register: (email, password, nickname) => request('/api/v1/auth/register', 'POST', { email, password, nickname }),
  me: () => request('/api/v1/user/me'),
  // 设备
  devices: () => request('/api/v1/devices'),
  deviceDetail: (id) => request('/api/v1/devices/' + encodeURIComponent(id)),
  deviceWakeup: (id) => request('/api/v1/devices/' + encodeURIComponent(id) + '/wakeup', 'POST'),
  deviceSpeak: (id, text) => request('/api/v1/devices/' + encodeURIComponent(id) + '/speak', 'POST', { text }),
  deviceStop: (id) => request('/api/v1/devices/' + encodeURIComponent(id) + '/stop', 'POST'),
  deviceHistory: (id) => request('/api/v1/devices/' + encodeURIComponent(id) + '/history'),
  deviceUnbind: (id) => request('/api/v1/devices/' + encodeURIComponent(id) + '/unbind', 'POST'),
    bindDeviceByCode: (bindCode, name = '') => request('/api/v1/bind', 'POST', { bind_code: bindCode, name }),
  // 插件商店（设备级启用控制）
  plugins: (deviceId) => request('/api/v1/devices/' + encodeURIComponent(deviceId) + '/plugins'),
  installPlugin: (deviceId, plugins) => request('/api/v1/devices/' + encodeURIComponent(deviceId) + '/plugins', 'PUT', { enabled_plugins: plugins }),
  savePluginConfig: (deviceId, plugin, config) =>
    request('/api/v1/devices/' + encodeURIComponent(deviceId) + '/plugins/' + encodeURIComponent(plugin) + '/config', 'PUT', { config }),
  // 已安装插件管理（本地）
  installedPlugins: () => request('/api/v1/plugins/installed'),
  installPluginZip: async (file) => {
    const formData = new FormData()
    formData.append('file', file)
    const headers = {}
    if (_token) headers['Authorization'] = 'Bearer ' + _token
    const res = await fetch(BASE + '/api/v1/plugins/install', { method: 'POST', headers, body: formData })
    let data = null; try { data = await res.json() } catch { data = null }
    return { status: res.status, data }
  },
  uninstallPlugin: (name) => request('/api/v1/plugins/' + encodeURIComponent(name), 'DELETE'),
  updatePlugin: (name) => request('/api/v1/plugins/' + encodeURIComponent(name) + '/update', 'POST'),
  checkPluginUpdates: () => request('/api/v1/plugins/updates'),
  // 云市场
  marketplacePlugins: (params = {}) => {
    const qs = new URLSearchParams({ page: 1, size: 20, ...params }).toString()
    return request('/api/v1/marketplace/plugins?' + qs)
  },
  marketplaceDetail: (slug) => request('/api/v1/marketplace/plugins/' + encodeURIComponent(slug)),
  marketplaceVersions: (slug) => request('/api/v1/marketplace/plugins/' + encodeURIComponent(slug) + '/versions'),
  marketplaceReviews: (slug) => request('/api/v1/marketplace/plugins/' + encodeURIComponent(slug) + '/reviews'),
  marketplaceCategories: () => request('/api/v1/marketplace/categories'),
  ratePlugin: (slug, rating, comment = '') => request('/api/v1/marketplace/plugins/' + encodeURIComponent(slug) + '/reviews', 'POST', { rating, comment }),
  // 开发者（复用用户 JWT，无需单独注册）
  devInfo: () => request('/api/v1/marketplace/developer/info'),
  devEnable: () => request('/api/v1/marketplace/developer/enable', 'POST'),
  devUpdateBio: (bio) => request('/api/v1/marketplace/developer/bio', 'PUT', { bio }),
  devDeletePlugin: (slug) => request('/api/v1/marketplace/plugins/' + encodeURIComponent(slug), 'DELETE'),
  devMyPlugins: () => request('/api/v1/marketplace/developer/plugins'),
  devUpload: async (file) => {
    const formData = new FormData()
    formData.append('file', file)
    const headers = {}
    if (_token) headers['Authorization'] = 'Bearer ' + _token
    const res = await fetch(BASE + '/api/v1/marketplace/plugins/upload', { method: 'POST', headers, body: formData })
    let data = null; try { data = await res.json() } catch { data = null }
    return { status: res.status, data }
  },
// 在线代码编辑
  devGetPluginSource: (slug) => request('/api/v1/marketplace/plugins/' + encodeURIComponent(slug) + '/source'),
  devUpdatePluginSource: (slug, data) => request('/api/v1/marketplace/plugins/' + encodeURIComponent(slug) + '/source', 'PUT', data),
  devCreatePlugin: (data) => request('/api/v1/marketplace/plugins/create', 'POST', data),
  getLocalPluginSource: (name) => request('/api/v1/plugins/' + encodeURIComponent(name) + '/source'),
  updateLocalPluginSource: (name, pluginCode, files) =>
    request('/api/v1/plugins/' + encodeURIComponent(name) + '/source', 'PUT', files ? { files } : { plugin_code: pluginCode }),
  createLocalPlugin: (data) => request('/api/v1/plugins/create-local', 'POST', data),
  // 设备控制
  volume: (mac) => request('/api/v1/devices/' + encodeURIComponent(mac) + '/volume'),
  // UI 层传 0-100 百分比，API 层需 0.0-1.0 浮点（与设备端 cmd_set_volume 契约一致）
  setVolume: (mac, volume) => request('/api/v1/devices/' + encodeURIComponent(mac) + '/volume', 'POST', { volume: volume / 100 }),
  // 屏幕亮度（0-100 整数百分比，设备端 cmd_set_brightness 直接接收此格式）
  brightness: (mac) => request('/api/v1/devices/' + encodeURIComponent(mac) + '/brightness'),
  setBrightness: (mac, brightness) => request('/api/v1/devices/' + encodeURIComponent(mac) + '/brightness', 'POST', { brightness }),
  // 发送情绪表情到设备（WebSocket 推送 {"type":"emotion","data":"快乐"}）
  sendEmotion: (mac, emotion) => request('/api/v1/devices/' + encodeURIComponent(mac) + '/emotion', 'POST', { emotion }),
  // 表情包管理
  emoPacks: () => request('/api/v1/emos/packs/list'),
  emoPackDetail: (name) => request('/api/v1/emos/packs/' + encodeURIComponent(name)),
  createEmoPack: (name) => request('/api/v1/emos/packs/create?name=' + encodeURIComponent(name), 'POST'),
  deleteEmoPack: (name) => request('/api/v1/emos/packs/' + encodeURIComponent(name), 'DELETE'),
  uploadEmo: (packName, file, gifName, size) => {
    const fd = new FormData()
    fd.append('file', file)
    const q = 'name=' + encodeURIComponent(gifName) + (size ? '&size=' + size : '')
    return fetch('/api/v1/emos/packs/' + encodeURIComponent(packName) + '/upload?' + q, {
      method: 'POST',
      headers: { 'Authorization': 'Bearer ' + _token },
      body: fd,
    }).then(r => r.json()).catch(() => null)
  },
getActiveEmoPack: (deviceId) => request('/api/v1/emos/active/' + encodeURIComponent(deviceId)),
  setActiveEmoPack: (deviceId, pack) => request('/api/v1/emos/active/' + encodeURIComponent(deviceId) + '?pack=' + encodeURIComponent(pack), 'POST'),
  // GIF 制作器（服务端 Pillow 抽帧/合并/裁剪/缩放/压缩）
  emoMakerSources: async (files) => {
    const fd = new FormData()
    files.forEach(f => fd.append('files', f))
    const headers = {}
    if (_token) headers['Authorization'] = 'Bearer ' + _token
    const res = await fetch(BASE + '/api/v1/emos/maker/sources', { method: 'POST', headers, body: fd })
    let data = null; try { data = await res.json() } catch { data = null }
    return { status: res.status, data }
  },
  emoMakerProcess: async (files, params) => {
    const fd = new FormData()
    files.forEach(f => fd.append('files', f))
    fd.append('params', JSON.stringify(params))
    const headers = {}
    if (_token) headers['Authorization'] = 'Bearer ' + _token
    const res = await fetch(BASE + '/api/v1/emos/maker/process', { method: 'POST', headers, body: fd })
    if ((res.headers.get('content-type') || '').includes('image/gif')) {
      const blob = await res.blob()
      return { status: res.status, blob, frames: Number(res.headers.get('x-gif-frames')) || 0 }
    }
    let data = null; try { data = await res.json() } catch { data = null }
    return { status: res.status, data }
  },
  // 技能管理
  skills: (deviceId) => deviceId
    ? request('/api/v1/skills?device_id=' + encodeURIComponent(deviceId))
    : request('/api/v1/skills'),
  skillDetail: (skillId) => request('/api/v1/skills/' + encodeURIComponent(skillId)),
  createSkill: (data) => request('/api/v1/skills', 'POST', data),
  updateSkill: (skillId, data) => request('/api/v1/skills/' + encodeURIComponent(skillId), 'PUT', data),
  deleteSkill: (skillId) => request('/api/v1/skills/' + encodeURIComponent(skillId), 'DELETE'),
  toggleSkill: (skillId, deviceId, disabled) =>
    request('/api/v1/skills/' + encodeURIComponent(skillId) + '/toggle?device_id=' + encodeURIComponent(deviceId) + '&disabled=' + disabled, 'POST'),
  deviceTools: (deviceId) => request('/api/v1/devices/' + encodeURIComponent(deviceId) + '/tools'),
  // 设备配置（ASR/LLM/TTS 等）
  getConfig: (mac) => request('/api/v1/devices/' + encodeURIComponent(mac) + '/config'),
  saveConfig: (mac, config) => request('/api/v1/devices/' + encodeURIComponent(mac) + '/config', 'POST', config),
  cloneVoices: (mac) => request('/api/v1/tts/clone-voices?mac=' + encodeURIComponent(mac)),
  // 快捷指令：真实执行功能（weather/music/alarm/diary/chat）
  deviceAction: (id, action, text = '') =>
    request('/api/v1/devices/' + encodeURIComponent(id) + '/action', 'POST', { action, text }),
    // 管理员后台
    adminStats: () => request('/api/v1/admin/stats'),
    adminUsers: () => request('/api/v1/admin/users'),
    adminUpdateUser: (userId, data) => request('/api/v1/admin/users/' + encodeURIComponent(userId), 'PUT', data),
    adminDeleteUser: (userId) => request('/api/v1/admin/users/' + encodeURIComponent(userId), 'DELETE'),
    adminDevices: () => request('/api/v1/admin/devices'),
    adminUpdateDevice: (deviceId, data) => request('/api/v1/admin/devices/' + encodeURIComponent(deviceId), 'PUT', data),
    adminUnbindDevice: (deviceId) => request('/api/v1/admin/devices/' + encodeURIComponent(deviceId) + '/unbind', 'POST'),
    adminReloadPlugins: () => request('/api/v1/plugins/reload', 'POST'),
    adminBatchWakeup: () => request('/api/v1/admin/devices/batch/wakeup', 'POST'),
    adminBatchStop: () => request('/api/v1/admin/devices/batch/stop', 'POST'),
    adminBatchSpeak: (text) => request('/api/v1/admin/devices/batch/speak', 'POST', { text }),
    adminUserDevices: (userId) => request('/api/v1/admin/users/' + encodeURIComponent(userId) + '/devices'),
    adminResetPassword: (userId, newPassword) => request('/api/v1/admin/users/' + encodeURIComponent(userId) + '/reset-password', 'POST', { new_password: newPassword }),
    adminToggleDeveloper: (userId) => request('/api/v1/admin/users/' + encodeURIComponent(userId) + '/toggle-developer', 'POST'),
    adminSystemInfo: () => request('/api/v1/admin/system/info'),
    adminLogs: (lines = 200) => request('/api/v1/admin/logs?lines=' + lines),
    adminBackup: () => request('/api/v1/admin/backup', 'POST'),
    adminBackups: () => request('/api/v1/admin/backups'),
    adminMarketplacePlugins: () => request('/api/v1/admin/marketplace/plugins'),
    adminUpdateMarketplacePlugin: (slug, data) => request('/api/v1/admin/marketplace/plugins/' + encodeURIComponent(slug), 'PUT', data),
    adminMarketplaceReviews: () => request('/api/v1/admin/marketplace/reviews'),
    adminDeleteMarketplaceReview: (reviewId) => request('/api/v1/admin/marketplace/reviews/' + encodeURIComponent(reviewId), 'DELETE'),
    // 微信绑定
    wechatQrStart: () => request('/api/v1/wechat/qr-start', 'POST'),
    wechatQrStatus: () => request('/api/v1/wechat/qr-status'),
    wechatApplyToken: () => request('/api/v1/wechat/apply-token', 'POST'),
    wechatQrCancel: () => request('/api/v1/wechat/qr-cancel', 'POST'),
    wechatBind: (data) => request('/api/v1/wechat/bind', 'POST', data),
    wechatUnbind: (deviceKey) => request('/api/v1/wechat/unbind', 'POST', { device_key: deviceKey }),
    wechatBindings: () => request('/api/v1/wechat/bindings'),
    wechatRecentGroups: () => request('/api/v1/wechat/recent-groups'),
}

export function formatTime(ts) {
  if (!ts) return '—'
  const d = new Date(ts * 1000)
  return `${d.getMonth() + 1}月${d.getDate()}日 ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}
