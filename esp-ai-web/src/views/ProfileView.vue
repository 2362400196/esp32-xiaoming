<template>
  <div class="profile-view">
    <!-- 未登录：居中登录卡 -->
    <div v-if="!loggedIn" class="auth-wrap">
      <div class="auth-card glass">
        <div class="auth-logo"><span class="auth-logo-icon">🤖</span>ESP-<span class="grad-text">AI</span></div>
        <h2 class="auth-title">{{ mode === 'login' ? '欢迎回来' : '创建账号' }}</h2>
        <p class="auth-sub">{{ mode === 'login' ? '登录以管理你的智能设备' : '首个注册用户将成为管理员' }}</p>
        <input class="input" v-model="email" placeholder="邮箱 / 手机号" type="text" />
        <input v-if="mode === 'register'" class="input" v-model="nickname" placeholder="昵称（可选）" type="text" />
        <input class="input" v-model="password" placeholder="密码" type="password" @keyup.enter="submit" />
        <p v-if="error" class="auth-error">{{ error }}</p>
        <button class="btn-mint auth-btn" :disabled="loading" @click="submit">
          {{ loading ? '处理中…' : (mode === 'login' ? '登 录' : '注 册') }}
        </button>
        <p class="auth-switch" @click="mode = mode === 'login' ? 'register' : 'login'">
          {{ mode === 'login' ? '没有账号？注册一个' : '已有账号？去登录' }}
        </p>
      </div>
    </div>

    <!-- 已登录 -->
    <div v-else class="profile-main">
      <!-- 顶部渐变栏 + 首字母水印 -->
      <div class="hero-bar glass">
        <span class="watermark">{{ (user?.nickname || user?.email || '?')[0].toUpperCase() }}</span>
        <div class="hero-text">
          <h2 class="hero-title">个人<span class="text-mint">中心</span></h2>
          <p class="hero-sub">账户信息 · 服务器状态 · 安全退出</p>
        </div>
      </div>

      <!-- 用户名片 -->
      <div class="user-card glass card-in">
        <div class="user-avatar">{{ (user?.nickname || user?.email || '?')[0].toUpperCase() }}</div>
        <div class="user-info">
          <p class="user-name">{{ user?.nickname || '用户' }}</p>
          <p class="user-email">{{ user?.email }}</p>
        </div>
        <span v-if="user?.role === 'admin'" class="admin-badge">管理员</span>
        <span v-else class="user-badge">普通用户</span>
      </div>

      <!-- 信息卡片 -->
      <div class="info-card glass card-in" style="animation-delay:0.06s">
        <div class="info-row">
          <span class="info-label">服务器</span>
          <span class="info-value">{{ serverHost }}</span>
        </div>
        <div class="info-row">
          <span class="info-label">账户角色</span>
          <span class="info-value">{{ user?.role === 'admin' ? '管理员' : '普通用户' }}</span>
        </div>
        <div class="info-row">
          <span class="info-label">登录状态</span>
          <span class="info-value online-dot">已登录</span>
        </div>
      </div>

        <!-- 微信绑定 -->
        <div class="wechat-card glass card-in" style="animation-delay:0.12s">
          <div class="wechat-head" @click="wechatCollapsed = !wechatCollapsed">
            <span class="wechat-title"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"/></svg> 微信绑定</span>
            <span class="wechat-arrow" :class="{ open: !wechatCollapsed }">▾</span>
          </div>
          <div v-if="!wechatCollapsed" class="wechat-body">
            <div v-if="!devices.length" class="wechat-empty">请先在「设备」页添加并选择设备</div>
            <template v-else>
              <div class="wechat-row">
                <span class="wechat-label">绑定设备</span>
                <select v-model="selectedDeviceId" class="input input-sm wechat-select">
                  <option v-for="d in devices" :key="d.device_id || d.id || d.mac" :value="d.device_id || d.id || d.mac">
                    {{ d.name || d.device_id || d.mac }}
                  </option>
                  </select>
                
              </div>
              <template v-if="wechatBoundDeviceKey">
                <div class="wechat-bound"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg> 微信已绑定：{{ wechatBoundDeviceKey.slice(0, 16) }}...</div>
                
                <button class="btn-sm btn-danger wechat-danger" @click="unbindWechat">解绑微信</button>
              </template>
              <template v-else>
                <div v-if="wechatQrDataUrl" class="wechat-qr">
                  <img :src="wechatQrDataUrl" alt="微信二维码" />
                  <p class="wechat-qr-msg">{{ wechatQrMessage }}</p>
                  <div class="wechat-actions">
                    <button class="btn-sm btn-ghost" @click="stopPollQr">取消</button>
                    <button class="btn-sm btn-mint" @click="startWechatQr">刷新二维码</button>
                    </div>
                  </div>
                  
                <div v-else class="wechat-start">
                  <p class="wechat-tip">{{ wechatQrMessage || '绑定微信后，可通过微信聊天控制设备' }}</p>
                  <button class="btn-mint btn-sm" @click="startWechatQr">开始微信扫码绑定</button>
                </div>
                </template>
              
                
                
                  
                    
                    
                  
                  
                  
                  
            </template>
          </div>
        </div>

      <!-- 退出按钮 -->
      <button class="btn-sm btn-ghost logout-btn" @click="logout">退出登录</button>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import { api, getToken, getUser, isLoggedIn, setAuth } from '../api'

const props = defineProps({
  devices: { type: Array, default: () => [] },
})
const emit = defineEmits(['login', 'toast'])

const mode = ref('login')
const email = ref('')
const password = ref('')
const nickname = ref('')
const loading = ref(false)
const error = ref('')


// ===== 微信绑定 =====
const wechatCollapsed = ref(true)
const wechatQrDataUrl = ref('')
const wechatQrStatus = ref('idle')
const wechatQrMessage = ref('')
const wechatQrPolling = ref(false)
const wechatBoundDeviceKey = ref('')
const wechatBoundWechatId = ref('')
const selectedDeviceId = ref('')
let wechatQrTimer = null

const selectedDevice = computed(() => {
  const id = selectedDeviceId.value
  return props.devices.find(d => (d.device_id || d.id || d.mac) === id) || props.devices[0] || null
})

watch(() => props.devices, (list) => {
  if (!selectedDeviceId.value && list && list.length) {
    selectedDeviceId.value = list[0].device_id || list[0].id || list[0].mac || ''
  }
}, { immediate: true })
const user = ref(getUser())
const loggedIn = computed(() => isLoggedIn())
const serverHost = window.location.hostname || 'localhost'
function refreshUser() {
  user.value = getUser()
}

function loadWechatBindInfo() {
  try {
    const saved = localStorage.getItem('espai_wechat_bind')
    if (saved) {
      const info = JSON.parse(saved)
      wechatBoundDeviceKey.value = info.device_key || ''
      wechatBoundWechatId.value = info.wechat_chat_id || ''
      
    }
  } catch { /* ignore */ }
}

async function startWechatQr() {
  try {
    const res = await api.wechatQrStart()
    if (res.status === 200 && res.data?.code === 0 && res.data?.data) {
      const d = res.data.data
      wechatQrDataUrl.value = d.qr_data_url || ''
      wechatQrStatus.value = d.status || 'waiting_scan'
      wechatQrMessage.value = d.message || '请用微信扫描二维码'
      wechatCollapsed.value = false
      startPollQrStatus()
    } else {
      emit('toast', res.data?.message || res.data?.detail || '获取二维码失败')
    }
  } catch {
    emit('toast', '获取二维码失败')
  }
}

function startPollQrStatus() {
  wechatQrPolling.value = true
  if (wechatQrTimer) clearInterval(wechatQrTimer)
  wechatQrTimer = setInterval(async () => {
    try {
      const res = await api.wechatQrStatus()
      if (res.status === 200 && res.data?.code === 0 && res.data?.data) {
        const d = res.data.data
        wechatQrStatus.value = d.status
        wechatQrMessage.value = d.message

        if (d.completed) {
          clearInterval(wechatQrTimer)
          wechatQrTimer = null
          wechatQrPolling.value = false
          emit('toast', '微信登录成功！')
          try {
            await api.wechatApplyToken()
          } catch { /* 忽略 apply-token 失败 */ }
          if (selectedDevice.value) {
            await bindCurrentDeviceToWechat(d.ilink_user_id)
          } else {
            emit('toast', '请先添加并选择设备')
          }
        } else if (d.status === 'expired' || d.status === 'error' || d.status === 'cancelled') {
          clearInterval(wechatQrTimer)
          wechatQrTimer = null
          wechatQrPolling.value = false
        }
      }
    } catch (e) {
      console.error('轮询二维码状态失败:', e)
    }
  }, 1500)
}

function stopPollQr() {
  if (wechatQrTimer) {
    clearInterval(wechatQrTimer)
    wechatQrTimer = null
  }
  wechatQrPolling.value = false
  api.wechatQrCancel().catch(() => {})
}

async function bindCurrentDeviceToWechat(wechatUserId) {
  const device = selectedDevice.value
  if (!device || !wechatUserId) return
  const deviceKey = device.device_key || device.authKey || device.device_id || device.mac || ''
  if (!deviceKey) {
    emit('toast', '设备缺少 device_key，无法绑定微信')
    return
  }
  try {
    const res = await api.wechatBind({
      wechat_chat_id: wechatUserId,
      wechat_user_id: wechatUserId,
      device_key: deviceKey,
      device_mac: device.mac || '',
      alias: device.name || '',
    })
    if (res.status === 200 && res.data?.code === 0) {
      wechatBoundDeviceKey.value = deviceKey
      wechatBoundWechatId.value = wechatUserId
      localStorage.setItem('espai_wechat_bind', JSON.stringify({
        device_key: deviceKey,
        wechat_chat_id: wechatUserId,
        
      }))
      emit('toast', '微信已绑定到当前设备')
    } else {
      emit('toast', res.data?.message || res.data?.detail || '绑定失败')
    }
  } catch {
    emit('toast', '绑定失败')
  }
}

async function unbindWechat() {
  if (!wechatBoundDeviceKey.value) return
  try {
    const res = await api.wechatUnbind(wechatBoundDeviceKey.value)
    if (res.status === 200 && res.data?.code === 0) {
      emit('toast', '微信已解绑')
    }
  } catch { /* 忽略 */ }
  wechatBoundDeviceKey.value = ''
  wechatBoundWechatId.value = ''
  
  localStorage.removeItem('espai_wechat_bind')
}



async function submit() {
  if (!email.value || !password.value) { error.value = '请填写邮箱和密码'; return }
  loading.value = true
  error.value = ''
  try {
    const res = mode.value === 'login'
      ? await api.login(email.value, password.value)
      : await api.register(email.value, password.value, nickname.value)
    if (res.status === 200 && res.data?.code === 0) {
      if (mode.value === 'register') {
        const loginRes = await api.login(email.value, password.value)
        if (loginRes.status === 200 && loginRes.data?.code === 0) {
          setAuth(loginRes.data.data.access_token, { user_id: loginRes.data.data.user_id || '', email: email.value, role: loginRes.data.data.role || 'user', nickname: nickname.value || '' })
            refreshUser()
        }
      } else {
        setAuth(res.data.data.access_token, { user_id: res.data.data.user_id || '', email: email.value, role: res.data.data.role || 'user', nickname: nickname.value || '' })
          refreshUser()
      }
        // 登录成功后强制同步最新用户信息（确保管理员角色立即生效）
        try {
          const meRes = await api.me()
          if (meRes.status === 200 && meRes.data?.code === 0) {
            const u = meRes.data.data
            setAuth(getToken(), {
              user_id: u.user_id || '',
              email: u.email || '',
              nickname: u.nickname || '',
              role: u.role || 'user',
            })
              refreshUser()
          }
        } catch { /* 忽略 */ }
      emit('login')
      emit('toast', mode.value === 'login' ? '欢迎回来' : '注册成功')
    } else {
      error.value = res.data?.detail || res.data?.message || '操作失败'
    }
  } catch (e) {
    error.value = '网络错误'
  }
  loading.value = false
}

async function syncProfile() {
  if (!isLoggedIn()) return
  try {
    const res = await api.me()
    if (res.status === 200 && res.data?.code === 0) {
      const u = res.data.data
      setAuth(getToken(), {
        user_id: u.user_id || '',
        email: u.email || '',
        nickname: u.nickname || '',
        role: u.role || 'user',
      })
        refreshUser()
    }
  } catch { /* 忽略 */ }
}

onMounted(() => {
  syncProfile()
  loadWechatBindInfo()
})
onBeforeUnmount(() => {
  if (wechatQrTimer) clearInterval(wechatQrTimer)
})

function logout() {
  setAuth('', null)
    user.value = null
  emit('login')
}
</script>

<style scoped>
.profile-view { padding: 28px 0 56px; }

.glass {
  background: var(--grad-card);
  backdrop-filter: var(--glass-blur);
  -webkit-backdrop-filter: var(--glass-blur);
  border: 1px solid var(--glass-border);
  box-shadow: var(--shadow), var(--glass-hi);
  border-radius: var(--radius-lg);
}

/* ===== 登录卡 ===== */
.auth-wrap {
  width: 100%; max-width: 720px; margin: 0 auto;
  min-height: calc(100dvh - 120px);
  display: flex; align-items: center; justify-content: center;
}
.auth-card {
  display: flex; flex-direction: column; gap: 18px;
  padding: 56px 56px;
  position: relative; overflow: hidden;
  border-radius: var(--radius-xl);
  box-shadow: var(--shadow-md), var(--glass-hi);
}
.auth-card::before {
  content: '';
  position: absolute; top: 0; left: 0; right: 0; height: 3px;
  background: var(--grad-brand);
  z-index: 1;
}
.auth-card .input { padding: 12px 16px; font-size: 15px; border-radius: var(--radius-md); }
.auth-btn { padding: 13px; font-size: 15px; }
.auth-card::after {
  content: '';
  position: absolute; bottom: -70px; left: -70px;
  width: 200px; height: 200px;
  background: radial-gradient(circle, rgba(56, 189, 248, 0.14), transparent 70%);
  border-radius: 50%; pointer-events: none;
}
.auth-logo {
  font-size: 26px; font-weight: 800; text-align: center;
  display: flex; align-items: center; justify-content: center; gap: 10px;
  position: relative;
}
.auth-logo-icon {
  font-size: 26px;
  filter: drop-shadow(0 3px 8px rgba(16, 185, 129, 0.3));
  animation: brandFloat 3s ease-in-out infinite;
}
@keyframes brandFloat {
  0%, 100% { transform: translateY(0) rotate(0deg); }
  50% { transform: translateY(-3px) rotate(-3deg); }
}
.auth-title { font-size: 22px; font-weight: 800; text-align: center; letter-spacing: -0.2px; position: relative; }
.auth-sub { font-size: 13px; color: var(--text-sub); text-align: center; margin-bottom: 4px; position: relative; }
.auth-btn { width: 100%; }
.auth-error { font-size: 12px; color: var(--danger); text-align: center; }
.auth-switch { text-align: center; font-size: 13px; color: var(--text-dim); cursor: pointer; transition: color 0.2s var(--ease); }
.auth-switch:hover { color: var(--mint); }

/* ===== 已登录主区域 ===== */
.profile-main { display: flex; flex-direction: column; gap: 16px; }

/* ===== 顶部渐变栏 ===== */
.hero-bar {
  position: relative; overflow: hidden;
  padding: 30px 34px 24px;
  margin-bottom: 22px;
}
.hero-bar::before {
  content: ''; position: absolute; top: 0; left: 0; right: 0; height: 3px;
  background: var(--grad-brand);
}
.hero-bar::after {
  content: ''; position: absolute; inset: 0;
  background: var(--grad-hero);
  pointer-events: none;
}
.watermark {
  position: absolute; right: 24px; top: 50%;
  transform: translateY(-50%);
  font-size: 120px; font-weight: 900; line-height: 1;
  color: var(--mint); opacity: 0.06;
  pointer-events: none; user-select: none;
}
.hero-text { position: relative; z-index: 1; }
.hero-title { font-size: 24px; font-weight: 800; letter-spacing: -0.3px; }
.hero-sub { margin-top: 4px; font-size: 13px; color: var(--text-sub); }

/* ===== 用户名片 ===== */
.user-card {
  display: flex; align-items: center; gap: 16px; padding: 28px;
  position: relative; overflow: hidden;
}
.user-card::before {
  content: '';
  position: absolute; top: -50px; right: -50px;
  width: 200px; height: 200px;
  background: radial-gradient(circle, rgba(52, 211, 153, 0.14), transparent 70%);
  border-radius: 50%; pointer-events: none;
}
.user-avatar {
  width: 58px; height: 58px; border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  font-size: 22px; font-weight: 700; color: #fff;
  background: var(--grad-brand);
  box-shadow: var(--shadow-mint), inset 0 1px 0 rgba(255, 255, 255, 0.35);
  position: relative; flex-shrink: 0;
}
.user-info { flex: 1; position: relative; min-width: 0; }
.user-name { font-size: 18px; font-weight: 700; letter-spacing: -0.2px; }
.user-email { margin-top: 4px; font-size: 12px; color: var(--text-sub); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.admin-badge {
  font-size: 11px; padding: 4px 12px; border-radius: 999px;
  background: var(--mint-soft); color: var(--mint-deep); font-weight: 600;
  position: relative; flex-shrink: 0;
  border: 1px solid var(--mint-border);
}
.user-badge {
  font-size: 11px; padding: 4px 12px; border-radius: 999px;
  background: var(--glass-bg-strong); color: var(--text-sub); font-weight: 600;
  border: 1px solid var(--glass-border);
  position: relative; flex-shrink: 0;
}

/* ===== 信息卡片 ===== */
.info-card { padding: 12px 28px; }
.info-row { display: flex; justify-content: space-between; align-items: center; padding: 14px 0; border-bottom: 1px solid var(--glass-border-soft); font-size: 13px; }
.info-row:last-child { border-bottom: none; }
.info-label { color: var(--text-sub); }
.info-value { font-weight: 600; }
.online-dot { color: var(--mint-deep); position: relative; padding-left: 14px; }
.online-dot::before {
  content: ''; position: absolute; left: 0; top: 50%; transform: translateY(-50%);
  width: 7px; height: 7px; border-radius: 50%; background: var(--mint);
  animation: dotBreath 2s ease-in-out infinite;
}
@keyframes dotBreath {
  0%, 100% { box-shadow: 0 0 0 0 rgba(16,185,129,0); }
  50% { box-shadow: 0 0 0 4px rgba(16,185,129,0.15); }
}

/* ===== 退出按钮 ===== */
.logout-btn {
  align-self: center; margin-top: 8px;
  color: var(--text-sub); border: 1px solid var(--glass-border);
  background: var(--glass-bg-strong);
  padding: 9px 32px;
}
.logout-btn:hover { color: var(--danger); border-color: var(--danger); background: var(--danger-soft); }

/* ===== 微信绑定 ===== */
.wechat-card { padding: 0; overflow: hidden; }
.wechat-head {
  display: flex; align-items: center; justify-content: space-between;
  padding: 16px 24px; cursor: pointer;
  transition: background .2s var(--ease);
}
.wechat-head:hover { background: var(--mint-softer); }
.wechat-title { font-size: 14px; font-weight: 700; display: inline-flex; align-items: center; gap: 7px; color: var(--mint-deep); }
.wechat-arrow { font-size: 14px; color: var(--text-dim); transition: transform .2s var(--ease); }
.wechat-arrow.open { transform: rotate(180deg); }
.wechat-body {
  padding: 0 24px 20px;
  border-top: 1px solid var(--glass-border-soft);
  display: flex; flex-direction: column; gap: 12px;
}
.wechat-empty {
  padding: 18px 0; text-align: center;
  font-size: 13px; color: var(--text-dim);
}
.wechat-row { display: flex; align-items: center; gap: 10px; }
.wechat-label { font-size: 13px; color: var(--text-sub); flex-shrink: 0; }
.wechat-select { flex: 1; min-width: 0; }
.wechat-bound {
  font-size: 13px; color: var(--mint-deep);
  background: var(--mint-soft);
  border: 1px solid var(--mint-border);
  padding: 8px 12px; border-radius: 10px;
  word-break: break-all;
  display: flex; align-items: center; gap: 6px;
}
.wechat-danger { align-self: flex-start; }
.wechat-qr { display: flex; flex-direction: column; align-items: center; gap: 10px; }
.wechat-qr img {
  width: 220px; height: 220px; object-fit: contain;
  border: 1px solid var(--glass-border); border-radius: 14px;
  background: rgba(255, 255, 255, 0.7);
  box-shadow: var(--shadow);
}
.wechat-qr-msg { font-size: 13px; color: var(--text-sub); text-align: center; }
.wechat-actions { display: flex; gap: 8px; }
.wechat-start { display: flex; flex-direction: column; align-items: center; gap: 10px; padding: 12px 0; }
.wechat-tip { font-size: 13px; color: var(--text-dim); text-align: center; }
.wechat-group {
  border-top: 1px dashed var(--glass-border-soft);
  padding-top: 14px;
  display: flex; flex-direction: column; gap: 8px;
}
.wechat-group-title { font-size: 12px; color: var(--text-sub); }
.wechat-group-controls { display: flex; flex-wrap: wrap; gap: 8px; }

.btn-danger {
  display: inline-flex; align-items: center; justify-content: center;
  padding: 6px 14px; font-size: 12px; font-weight: 500;
  border: 1px solid rgba(239,68,68,.25);
  border-radius: 8px;
  background: rgba(255,255,255,0.6); color: var(--danger); cursor: pointer;
  transition: all .2s var(--ease);
}
.btn-danger:hover:not(:disabled) { background: var(--danger-soft); border-color: var(--danger); }
.btn-danger:disabled { opacity: .5; cursor: not-allowed; }

.btn-mint { background: var(--grad-mint); color: #fff; border: none; box-shadow: var(--shadow-mint); }
.btn-ghost { background: rgba(255,255,255,0.6); color: var(--text-sub); border: 1px solid var(--glass-border); }
.btn-ghost:hover { border-color: var(--mint-border); color: var(--mint-deep); background: var(--mint-softer); }

/* ===== 响应式 ===== */
@media (max-width: 600px) {
  .hero-bar { padding: 22px 20px 18px; }
  .watermark { font-size: 90px; right: 16px; }
  .user-card { padding: 20px; }
  .info-card { padding: 12px 20px; }
}
</style>