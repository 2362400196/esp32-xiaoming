<template>
  <div class="app">
    <!-- 未登录时不显示导航栏（登录页保持干净）；开发者编辑器打开时隐藏导航栏（带过渡动画） -->
    <Transition name="nav">
      <NavBar v-if="loggedIn && !editorOpen" :active="tab" :items="navItems" @switch="switchTab" />
    </Transition>

    <main class="stage">
      <!-- 单个过渡包裹全部视图：登录/各标签间切换动画统一 -->
      <transition name="view" mode="out-in">
        <ProfileView v-if="!loggedIn" :key="'login'" :devices="devices" @login="onLogin" @toast="toast" />
        <DevicesView v-else-if="tab === 'devices'" :key="'devices'" :devices="devices"
          :selected="currentDevice" :loading="loading"
          @select="selectDevice" @speak="speakToDevice" @stop="stopDevice" @settings="openDeviceSettings"
          @unbind="onDeviceUnbind" @bound="onDeviceBound" @toast="toast" />
        <StoreView v-else-if="tab === 'store'" :key="'store'" @toast="toast" />
        <DeveloperView v-else-if="tab === 'developer'" :key="'developer'" @toast="toast" @editor-change="onEditorChange" />
        <ControlView v-else-if="tab === 'control'" :key="'control'" :current-device="currentDevice"
          :devices="devices" :plugin-count="pluginCount"
          @toast="toast" @select-device="selectDevice" />
        <EmotionView v-else-if="tab === 'emotion'" :key="'emotion'" :current-device="currentDevice"
          :devices="devices"
          @toast="toast" @select-device="selectDevice" />
        <SkillsView v-else-if="tab === 'skills'" :key="'skills'" :current-device="currentDevice"
          :devices="devices"
          @toast="toast" @select-device="selectDevice" />
        <ToolView v-else-if="tab === 'tool'" :key="'tool'" @toast="toast" />
        <AdminView v-else-if="tab === 'admin'" :key="'admin'" @toast="toast" />
        <ProfileView v-else :key="'profile'" :devices="devices" @login="onLogin" @toast="toast" />
      </transition>
    </main>

    <!-- 设备设置弹窗（ASR/LLM/TTS/插件） -->
    <DeviceSettings v-if="settingsDevice" :device="settingsDevice" @close="settingsDevice = null" @toast="toast" @plugins-changed="loadPlugins" />

    <!-- Toast -->
    <transition name="toast">
      <div v-if="toastMsg" class="toast">{{ toastMsg }}</div>
    </transition>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import NavBar from './components/NavBar.vue'
import DevicesView from './views/DevicesView.vue'
import StoreView from './views/StoreView.vue'
import DeveloperView from './views/DeveloperView.vue'
import ControlView from './views/ControlView.vue'
import EmotionView from './views/EmotionView.vue'
import SkillsView from './views/SkillsView.vue'
import ToolView from './views/ToolView.vue'
import ProfileView from './views/ProfileView.vue'
import DeviceSettings from './components/DeviceSettings.vue'
import AdminView from './views/AdminView.vue'
import { api, getUser, isLoggedIn, setAuth } from './api'

const tab = ref('devices')
const editorOpen = ref(false)
let editorCloseTimer = null
function onEditorChange(v) {
  clearTimeout(editorCloseTimer)
  if (v) {
    editorOpen.value = true
  } else {
    // 等编辑器退场动画结束再让导航栏滑入，避免退场时布局跳动
    editorCloseTimer = setTimeout(() => { editorOpen.value = false }, 280)
  }
}
const loggedIn = ref(isLoggedIn())
const navItems = ref([
  { id: 'devices', label: '设备' },
  { id: 'store', label: '商店' },
  { id: 'developer', label: '开发者' },
  { id: 'control', label: '控制' },
  { id: 'emotion', label: '表情' },
  { id: 'skills', label: '技能' },
  { id: 'tool', label: '工具' },
  { id: 'profile', label: '我的' },
])

function syncAdminNav() {
  const idx = navItems.value.findIndex(i => i.id === 'admin')
  const isAdmin = getUser()?.role === 'admin'
  if (isAdmin && idx === -1) {
    navItems.value.splice(navItems.value.length - 1, 0, { id: 'admin', label: '管理' })
  } else if (!isAdmin && idx !== -1) {
    navItems.value.splice(idx, 1)
  }
}

const devices = ref([])
const currentDevice = ref(null)
const pluginList = ref([])
const loading = ref(false)
const botState = ref('idle')
const settingsDevice = ref(null)
const toastMsg = ref('')
let toastTimer = null

const currentId = computed(() => currentDevice.value?.device_id || currentDevice.value?.id || currentDevice.value?.mac || '')
const pluginCount = computed(() => pluginList.value.filter(p => p.enabled).length)
const musicConfigured = computed(() => {
  const mp = pluginList.value.find(p => p.name === 'media_player')
  return !!(mp && mp.config && Object.keys(mp.config).length)
})

function switchTab(t) {
  if (t !== 'developer') {
    clearTimeout(editorCloseTimer)
    editorOpen.value = false
  }
  tab.value = t
}

function toast(msg) {
  toastMsg.value = msg
  clearTimeout(toastTimer)
  toastTimer = setTimeout(() => (toastMsg.value = ''), 2200)
}

function openDeviceSettings(d) { settingsDevice.value = d }

function onDeviceUnbind(d) {
  toast('设备已解绑')
  refreshDevices()
}

function onDeviceBound() {
  toast('设备已添加')
  refreshDevices()
}

function requireLogin() { toast('请先登录'); tab.value = 'profile' }

// 同一设备：只更新字段（如 online），不替换对象引用 → 避免触发子组件 watch 导致历史重载
function _upsertCurrent(found) {
  if (currentDevice.value) {
    const curId = currentDevice.value.device_id || currentDevice.value.id || currentDevice.value.mac || ''
    const newId = found.device_id || found.id || found.mac || ''
    if (curId && curId === newId) {
      Object.assign(currentDevice.value, found)
      return
    }
  }
  currentDevice.value = found
}

async function refreshDevices() {
  if (!isLoggedIn()) return
  loading.value = true
  let needLoadPlugins = false
  try {
    const res = await api.devices()
    if (res.status === 200 && res.data?.code === 0) {
      // 服务器返回 { devices: [...] }（含离线设备，字段 online）
      devices.value = res.data.data?.devices || []
      // 1. 优先恢复上次保存的选择（localStorage 持久化，刷新不丢失）
      const savedId = localStorage.getItem('espai_device_id')
      if (savedId) {
        const found = devices.value.find(d => (d.device_id || d.id || d.mac) === savedId)
        if (found) {
          // 首次加载（currentDevice 为空）或设备标识变化时需要加载插件
          if (!currentDevice.value) {
            currentDevice.value = found
            needLoadPlugins = true
          } else {
            _upsertCurrent(found)
          }
        }
      }
      // 2. 已选设备仍在列表中（同步 online 等字段）
      if (currentDevice.value) {
        const found = devices.value.find(d => (d.device_id || d.id || d.mac) === currentId.value)
        if (found) { _upsertCurrent(found) }
      }
      // 3. 默认优先选中在线设备（主页状态展示更合理）
      if (!currentDevice.value && devices.value.length) {
        currentDevice.value = devices.value.find(d => d.online) || devices.value[0]
        needLoadPlugins = true
      }
    }
  } catch { /* ignore */ }
  loading.value = false
  // 自动恢复/首次选中设备时加载插件列表（手动点击走 selectDevice → loadPlugins）
  if (needLoadPlugins) loadPlugins()
}

function selectDevice(d) {
  currentDevice.value = d
  // 持久化设备选择（刷新页面后恢复）
  localStorage.setItem('espai_device_id', d.device_id || d.id || d.mac || '')
  toast(`已选择「${d.name || '设备'}」`)
  loadPlugins()
}

async function loadPlugins() {
  if (!currentId.value) { pluginList.value = []; return }
  const res = await api.plugins(currentId.value)
  if (res.status === 200 && res.data?.code === 0) {
    const d = res.data.data
    // enabled_plugins 为 null/空数组时表示全部启用（后端约定）
    const rawEnabled = d.enabled_plugins
    const allEnabled = !rawEnabled || rawEnabled.length === 0
    const installed = new Set(rawEnabled || [])
    const configs = d.plugin_configs || {}
    pluginList.value = (d.available_plugins || []).map(p => ({
      ...p,
      config: configs[p.name] || {},
      configDone: Object.keys(configs[p.name] || {}).length > 0,
      // 全部启用模式 || 内置插件默认启用 || 在白名单中
      enabled: allEnabled || p.source === 'built-in' || installed.has(p.name),
      saving: false,
    }))
  }
}

async function runDeviceAction(action, text = '') {
  if (!currentDevice.value) { toast('请先选择设备'); return }
  if (!isLoggedIn()) { requireLogin(); return }
  botState.value = 'listening'
  const res = await api.deviceAction(currentId.value, action, text)
  if (res.status === 200 && res.data?.code === 0) {
    botState.value = 'speaking'
    toast(res.data.message || '执行完成')
    setTimeout(() => (botState.value = 'idle'), 4000)
  } else {
    botState.value = 'idle'
    toast(res.data?.message || res.data?.detail || '执行失败')
  }
}

async function speakToDevice(text) {
  if (!currentDevice.value) { toast('请先选择设备'); return }
  if (!isLoggedIn()) { requireLogin(); return }
  botState.value = 'listening'
  const res = await api.deviceSpeak(currentId.value, text)
  if (res.status === 200 && res.data?.code === 0) {
    botState.value = 'speaking'
    toast('已发送指令')
    setTimeout(() => (botState.value = 'idle'), 4000)
  } else {
    botState.value = 'idle'
    toast(res.data?.message || res.data?.detail || '发送失败')
  }
}

async function stopDevice() {
  if (!currentDevice.value) return
  await api.deviceStop(currentId.value)
  toast('已停止播放')
}

async function syncUserProfile() {
  if (!isLoggedIn()) return
  try {
    const res = await api.me()
      if (res.status === 401) {
        loggedIn.value = false
        return
      }
    if (res.status === 200 && res.data?.code === 0) {
      const u = res.data.data
      const old = getUser() || {}
      setAuth(getToken(), {
        user_id: u.user_id || old.user_id || '',
        email: u.email || old.email || '',
        nickname: u.nickname || old.nickname || '',
        role: u.role || old.role || 'user',
      })
    }
  } catch { /* 忽略 */ }
}

async function onLogin() {
  loggedIn.value = isLoggedIn()
  if (loggedIn.value) {
    await syncUserProfile()
    syncAdminNav()
    tab.value = 'devices'   // 登录成功 → 跳设备页
    refreshDevices()
  }
}

let pollTimer = null
onMounted(async () => {
    await syncUserProfile()
    syncAdminNav()
  refreshDevices()
  pollTimer = setInterval(() => { if (isLoggedIn()) refreshDevices() }, 20000)
})
onBeforeUnmount(() => { clearInterval(pollTimer); clearTimeout(editorCloseTimer) })
</script>

<style scoped>
.app { min-height: 100%; display: flex; flex-direction: column; position: relative; z-index: 1; }
.stage {
  flex: 1;
  max-width: 1080px;
  width: 100%;
  margin: 0 auto;
  padding: 24px 24px 40px;
  position: relative;
  z-index: 1;
}

.toast {
  position: fixed;
  left: 50%; bottom: 40px;
  transform: translateX(-50%);
  z-index: 300;
  padding: 12px 28px;
  font-size: 13px;
  font-weight: 500;
  color: var(--text-main);
  background: linear-gradient(155deg, rgba(255, 255, 255, 0.82), rgba(255, 255, 255, 0.55));
  backdrop-filter: var(--glass-blur);
  -webkit-backdrop-filter: var(--glass-blur);
  border: 1px solid var(--glass-border);
  border-radius: 14px;
  box-shadow: var(--shadow-md), var(--glass-hi), 0 0 0 1px rgba(16, 185, 129, 0.06);
}
.toast-enter-active, .toast-leave-active { transition: all 0.4s var(--ease); }
.toast-enter-from { opacity: 0; transform: translateX(-50%) translateY(20px) scale(0.9); }
.toast-leave-to { opacity: 0; transform: translateX(-50%) translateY(10px) scale(0.95); }
</style>