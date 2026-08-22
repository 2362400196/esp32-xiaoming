<template>
  <div class="mcp-view">
    <div class="mcp-header">
      <h2 class="page-title">MCP 服务器管理</h2>
      <p class="page-sub">管理和配置外部工具服务器的连接，让 AI 具备更多能力</p>
    </div>

    <!-- 无设备提示 -->
    <div v-if="!currentDevice" class="empty-state glass">
      <p>请先选择一个设备</p>
    </div>

    <!-- 加载中 -->
    <div v-else-if="loading" class="loading-state glass">
      <div class="spinner"></div>
      <p>加载 MCP 配置…</p>
    </div>

    <template v-else>
      <!-- 操作栏 -->
      <div class="mcp-toolbar">
        <div class="device-info">
          当前设备：<strong>{{ currentDevice.name || currentDevice.device_id || '未知' }}</strong>
        </div>
        <button class="btn-mint btn-sm" @click="showAddForm = true">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round">
            <line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>
          </svg>
          添加服务器
        </button>
      </div>

      <!-- 空状态 -->
      <div v-if="Object.keys(servers).length === 0" class="empty-state glass">
        <div class="empty-icon">
          <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1" stroke-linecap="round">
            <rect x="2" y="2" width="20" height="8" rx="2"/><rect x="2" y="14" width="20" height="8" rx="2"/>
            <line x1="6" y1="6" x2="6.01" y2="6"/><line x1="6" y1="18" x2="6.01" y2="18"/>
          </svg>
        </div>
        <p>暂无 MCP 服务器配置</p>
        <p class="empty-hint">点击「添加服务器」连接外部工具</p>
      </div>

      <!-- 服务器列表 -->
      <div v-else class="server-list">
        <div v-for="(cfg, name) in servers" :key="name" class="server-card glass card-in">
          <div class="server-head">
            <div class="server-icon">
              <span>{{ name.charAt(0).toUpperCase() }}</span>
            </div>
            <div class="server-info">
              <div class="server-title-row">
                <span class="server-name">{{ name }}</span>
                <span class="server-badge" :class="cfg._disabled ? 'badge-off' : 'badge-on'">
                  {{ cfg._disabled ? '已禁用' : '已启用' }}
                </span>
              </div>
              <div class="server-url">{{ cfg.url }}</div>
            </div>
          </div>

          <div class="server-meta">
            <span class="meta-item">类型：{{ cfg.type || 'streamable_http' }}</span>
          </div>

          <!-- 工具列表 -->
          <div v-if="cfg._tools" class="server-tools">
            <div class="tools-title">工具（{{ cfg._tools.length }}）</div>
            <div class="tools-list">
              <div v-for="t in cfg._tools" :key="t.name" class="tool-item">
                <span class="tool-name">{{ t.name }}</span>
                <span class="tool-desc">{{ t.description }}</span>
              </div>
            </div>
          </div>
          <div v-else class="server-tools">
            <button class="btn-ghost btn-xs" @click="loadTools(name)" :disabled="cfg._loadingTools">
              {{ cfg._loadingTools ? '加载中…' : '查看工具' }}
            </button>
          </div>

          <div class="server-actions">
            <button class="btn-ghost btn-xs" @click="toggleServer(name, cfg._disabled)">
              {{ cfg._disabled ? '启用' : '禁用' }}
            </button>
            <button class="btn-ghost btn-xs" @click="editServer(name)">
              编辑
            </button>
            <button class="btn-ghost btn-xs btn-danger" @click="deleteServer(name)">
              删除
            </button>
          </div>
        </div>
      </div>
    </template>

    <!-- ===== 添加/编辑弹窗 ===== -->
    <transition name="pop">
      <div v-if="showAddForm" class="detail-mask" @click.self="closeForm">
        <div class="detail-panel glass form-panel">
          <button class="detail-close" @click="closeForm">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
              <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
            </svg>
          </button>
          <h3 class="form-title">{{ editingName ? '编辑服务器' : '添加 MCP 服务器' }}</h3>

          <div class="form-group">
            <label class="form-label">服务器名称</label>
            <input class="input" v-model="formName" placeholder="例如：weather-server" :disabled="!!editingName" />
          </div>
          <div class="form-group">
            <label class="form-label">URL</label>
            <input class="input" v-model="formUrl" placeholder="https://example.com/mcp" />
          </div>
          <div class="form-group">
            <label class="form-label">类型</label>
            <select class="input" v-model="formType">
              <option value="streamable_http">streamable_http</option>
              <option value="stdio">stdio</option>
            </select>
          </div>
          <div class="form-group">
            <label class="form-label">请求头（JSON，可选）</label>
            <textarea class="input" v-model="formHeaders" placeholder='{"Authorization": "Bearer xxx"}' rows="3"></textarea>
          </div>

          <div class="form-actions">
            <button class="btn-ghost btn-sm" @click="closeForm">取消</button>
            <button class="btn-mint btn-sm" :disabled="saving" @click="saveServer">
              {{ saving ? '保存中…' : '保存' }}
            </button>
          </div>
        </div>
      </div>
    </transition>
  </div>
</template>

<script setup>
import { ref, watch, onMounted } from 'vue'
import { api } from '../api'

const props = defineProps({
  currentDevice: { type: Object, default: null },
  devices: { type: Array, default: () => [] },
})
const emit = defineEmits(['toast', 'select-device'])

const servers = ref({})
const loading = ref(false)
const showAddForm = ref(false)
const editingName = ref('')
const formName = ref('')
const formUrl = ref('')
const formType = ref('streamable_http')
const formHeaders = ref('')
const saving = ref(false)

function deviceMac() {
  return props.currentDevice?.device_id || props.currentDevice?.id || props.currentDevice?.mac || ''
}

async function loadServers() {
  const mac = deviceMac()
  if (!mac) return
  loading.value = true
  const res = await api.mcpServers(mac)
  if (res.status === 200 && res.data?.code === 0) {
    const raw = res.data.data || {}
    for (const [name, cfg] of Object.entries(raw)) {
      cfg._disabled = false
    }
    servers.value = raw
    // 加载禁用状态
    const dRes = await api.mcpDisabled(mac)
    if (dRes.status === 200 && dRes.data?.code === 0) {
      const disabled = dRes.data.data?.disabled_servers || []
      for (const name of disabled) {
        if (servers.value[name]) servers.value[name]._disabled = true
      }
    }
  }
  loading.value = false
}

async function loadTools(name) {
  const mac = deviceMac()
  if (!mac || !servers.value[name]) return
  servers.value[name]._loadingTools = true
  const res = await api.mcpTools(mac, name)
  if (res.status === 200 && res.data?.code === 0) {
    servers.value[name]._tools = res.data.data || []
  } else {
    emit('toast', res.data?.message || '加载失败')
  }
  servers.value[name]._loadingTools = false
}

async function toggleServer(name, disabled) {
  const mac = deviceMac()
  if (!mac) return
  const res = await api.mcpToggle(mac, name, !disabled)
  if (res.status === 200 && res.data?.code === 0) {
    if (servers.value[name]) servers.value[name]._disabled = !disabled
    emit('toast', `「${name}」已${!disabled ? '禁用' : '启用'}`)
  }
}

function editServer(name) {
  const cfg = servers.value[name]
  if (!cfg) return
  editingName.value = name
  formName.value = name
  formUrl.value = cfg.url || ''
  formType.value = cfg.type || 'streamable_http'
  formHeaders.value = cfg.headers ? JSON.stringify(cfg.headers, null, 2) : ''
  showAddForm.value = true
}

function closeForm() {
  showAddForm.value = false
  editingName.value = ''
  formName.value = ''
  formUrl.value = ''
  formType.value = 'streamable_http'
  formHeaders.value = ''
}

async function saveServer() {
  if (!formName.value.trim()) { emit('toast', '请输入服务器名称'); return }
  if (!formUrl.value.trim()) { emit('toast', '请输入 URL'); return }
  const mac = deviceMac()
  if (!mac) { emit('toast', '请先选择设备'); return }

  saving.value = true
  let headers = {}
  if (formHeaders.value.trim()) {
    try { headers = JSON.parse(formHeaders.value) } catch { emit('toast', '请求头格式错误，需为 JSON'); saving.value = false; return }
  }
  const res = await api.mcpUpdate(mac, formName.value.trim(), {
    type: formType.value,
    url: formUrl.value.trim(),
    headers,
  })
  if (res.status === 200 && res.data?.code === 0) {
    emit('toast', editingName.value ? '已更新' : '已添加')
    closeForm()
    await loadServers()
  } else {
    emit('toast', res.data?.message || '保存失败')
  }
  saving.value = false
}

async function deleteServer(name) {
  const mac = deviceMac()
  if (!mac) return
  const res = await api.mcpDelete(mac, name)
  if (res.status === 200 && res.data?.code === 0) {
    emit('toast', `「${name}」已删除`)
    delete servers.value[name]
    servers.value = { ...servers.value }
  } else {
    emit('toast', res.data?.message || '删除失败')
  }
}

watch(() => props.currentDevice, (d) => {
  if (d) loadServers()
})

onMounted(() => {
  if (props.currentDevice) loadServers()
})
</script>

<style scoped>
.mcp-view { padding: 28px 0 56px; }
.mcp-header { margin-bottom: 24px; }
.page-title { font-size: 22px; font-weight: 800; margin: 0 0 6px 0; }
.page-sub { font-size: 14px; color: var(--text-sub); margin: 0; }

.mcp-toolbar {
  display: flex; justify-content: space-between; align-items: center;
  margin-bottom: 20px; gap: 12px; flex-wrap: wrap;
}
.device-info { font-size: 13px; color: var(--text-sub); }

.server-list { display: flex; flex-direction: column; gap: 14px; }

.server-card { padding: 18px; }
.server-head { display: flex; gap: 14px; margin-bottom: 12px; }
.server-icon {
  width: 40px; height: 40px; border-radius: 12px;
  display: flex; align-items: center; justify-content: center;
  font-size: 16px; font-weight: 700; color: #fff;
  background: var(--grad-brand); flex-shrink: 0;
}
.server-info { flex: 1; min-width: 0; }
.server-title-row { display: flex; align-items: center; gap: 8px; margin-bottom: 4px; }
.server-name { font-weight: 700; font-size: 15px; }
.server-badge { font-size: 11px; padding: 2px 8px; border-radius: 99px; font-weight: 600; }
.badge-on { background: var(--mint-soft); color: var(--mint-deep); }
.badge-off { background: var(--danger-soft); color: var(--danger); }
.server-url { font-size: 12px; color: var(--text-sub); word-break: break-all; }
.server-meta { margin-bottom: 10px; }

.server-tools { margin-bottom: 12px; }
.tools-title { font-size: 12px; font-weight: 600; color: var(--text-sub); margin-bottom: 6px; }
.tools-list { display: flex; flex-direction: column; gap: 4px; max-height: 160px; overflow-y: auto; }
.tool-item {
  display: flex; gap: 6px; font-size: 12px; padding: 4px 8px;
  background: rgba(0,0,0,0.04); border-radius: 6px;
}
.tool-name { font-weight: 600; color: var(--mint-deep); white-space: nowrap; }
.tool-desc { color: var(--text-sub); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

.server-actions { display: flex; gap: 8px; border-top: 1px solid var(--border); padding-top: 12px; }
.btn-danger { color: var(--danger) !important; }
.btn-danger:hover { background: var(--danger-soft) !important; }

/* 弹窗 */
.form-panel { max-width: 480px; }
.form-title { font-size: 16px; font-weight: 700; margin: 0 0 20px 0; }
.form-group { margin-bottom: 14px; }
.form-label { display: block; font-size: 12px; font-weight: 600; margin-bottom: 4px; color: var(--text-sub); }
.form-actions { display: flex; gap: 10px; justify-content: flex-end; margin-top: 20px; }

.loading-state, .empty-state {
  padding: 60px 20px; text-align: center; border-radius: var(--radius-lg);
}
.empty-icon { margin-bottom: 12px; opacity: 0.4; }
.empty-hint { font-size: 13px; color: var(--text-sub); margin-top: 4px; }
</style>