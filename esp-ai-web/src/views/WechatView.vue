<template>
  <div class="wechat-view">
    <!-- 顶部渐变栏 + 首字母水印 -->
    <div class="hero-bar glass">
      <span class="watermark">W</span>
      <div class="hero-text">
        <h2 class="hero-title">微信<span class="text-mint">绑定</span></h2>
        <p class="hero-sub">扫码登录 · 设备绑定 · 消息管理</p>
      </div>
    </div>

    <!-- 未扫码登录：显示二维码 -->
    <div v-if="!configured" class="qr-section glass card-in">
      <div class="qr-header">
        <h3>微信扫码登录</h3>
        <p class="qr-hint">使用微信扫描二维码，即可将设备与微信打通</p>
      </div>
      <div class="qr-body">
        <div v-if="qrLoading" class="qr-placeholder">
          <div class="spinner"></div>
          <p>正在生成二维码…</p>
        </div>
        <div v-else-if="qrImage" class="qr-image-wrap">
          <img :src="qrImage" class="qr-image" alt="微信二维码" />
          <p class="qr-status">{{ qrStatusText }}</p>
          <button v-if="qrExpired" class="btn-mint btn-sm" @click="startQr">重新生成</button>
        </div>
        <div v-else class="qr-placeholder">
          <button class="btn-mint" @click="startQr">获取二维码</button>
        </div>
      </div>
      <div v-if="botToken" class="qr-actions">
        <button class="btn-mint" @click="applyToken">应用 Token 并启动</button>
        <button class="btn-outline" @click="cancelQr">取消</button>
      </div>
    </div>

    <!-- 已登录：绑定管理 -->
    <div v-else class="bind-section">
      <!-- token 失效警示（轮询已被服务端判定停止，需重新扫码） -->
      <div v-if="tokenInvalid" class="status-bar glass card-in" style="border:1px solid rgba(239,68,68,.45)">
        <span class="status-dot offline"></span>
        <span style="color:var(--danger);font-weight:600">微信登录已失效，消息收发已停止</span>
        <span class="text-sub">可能原因：登录凭证到期、服务重启后未恢复、或另一实例在同时轮询</span>
        <button class="btn-mint btn-sm" style="margin-left:auto" @click="rescan">重新扫码登录</button>
      </div>
      <!-- 微信状态 -->
      <div class="status-bar glass card-in">
        <span class="status-dot online"></span>
        <span>微信已登录</span>
        <span class="sep">|</span>
        <span class="text-sub">共 {{ bindings.length }} 个绑定</span>
        <button class="btn-outline btn-sm" @click="doRefreshBindings" style="margin-left:auto">刷新</button>
      </div>

      <!-- 绑定列表 -->
      <div class="bind-list">
        <div v-for="b in bindings" :key="b.wechat_chat_id" class="bind-card glass card-in">
          <div class="bind-info">
            <div class="bind-avatar">{{ (b.alias || b.wechat_chat_id)[0].toUpperCase() }}</div>
            <div class="bind-detail">
              <p class="bind-device">设备：{{ b.device_key?.slice(0, 20) || '—' }}</p>
              <p class="bind-chat">
                微信：{{ b.wechat_chat_id?.slice(0, 20) || '—' }}
                <span v-if="b.wechat_group_id" class="bind-group">（群聊）</span>
              </p>
              <p class="bind-time">绑定时间：{{ formatTime(b.bound_at) }}</p>
            </div>
          </div>
          <button class="btn-outline btn-sm bind-unbind" @click="unbind(b)">解绑</button>
        </div>
        <div v-if="bindings.length === 0" class="bind-empty glass card-in">
          <p>暂无绑定关系</p>
          <p class="text-sub">在微信中向机器人发送消息，即可自动绑定设备</p>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onBeforeUnmount } from 'vue'
import { api } from '../api'

const emit = defineEmits(['toast'])

const configured = ref(false)
const tokenInvalid = ref(false)
const qrLoading = ref(false)
const qrImage = ref('')
const qrStatusText = ref('')
const qrExpired = ref(false)
const botToken = ref('')
const bindings = ref([])
let pollTimer = null
let statusTimer = null

function formatTime(ts) {
  if (!ts) return '—'
  const d = new Date(ts * 1000)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

async function startQr() {
  qrLoading.value = true
  qrImage.value = ''
  qrStatusText.value = '正在获取二维码…'
  qrExpired.value = false
  try {
	    const res = await api.wechatQrStart()
	    const body = res?.data || res
	    if (body && body.code === 0 && body.data) {
	      qrImage.value = body.data.qr_data_url || ''
	      qrStatusText.value = '请使用微信扫描二维码'
	      startPolling()
	    } else {
	      qrStatusText.value = body?.message || '获取二维码失败'
	    }
  } catch (e) {
    qrStatusText.value = '获取二维码失败: ' + (e.message || e)
  } finally {
    qrLoading.value = false
  }
}

function body(res) { return res?.data || res }

async function pollStatus() {
  try {
    const res = body(await api.wechatQrStatus())
    if (res && res.code === 0 && res.data) {
      tokenInvalid.value = !!res.data.token_invalid
      if (res.data.configured) {
        configured.value = true
        botToken.value = ''
        stopPolling()
        loadBindings()
        return
      }
      if (res.data.completed) {
        botToken.value = res.data.bot_token || ''
        qrStatusText.value = '扫码成功，点击「应用 Token」启动'
        stopPolling()
        return
      }
      if (res.data.active === false) {
        qrExpired.value = true
        qrStatusText.value = '二维码已过期，请重新生成'
        stopPolling()
        return
      }
    }
  } catch (e) {
    // 静默
  }
}

function startPolling() {
  stopPolling()
  pollTimer = setInterval(pollStatus, 2000)
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

async function applyToken() {
  try {
    const res = body(await api.wechatApplyToken())
    if (res && res.code === 0) {
      configured.value = true
      botToken.value = ''
      emit('toast', '微信已登录，轮询已启动')
      loadBindings()
    } else {
      emit('toast', (res && res.message) || '应用 Token 失败')
    }
  } catch (e) {
    emit('toast', '应用 Token 失败: ' + (e.message || e))
  }
}

async function cancelQr() {
  try {
    await api.wechatQrCancel()
  } catch (e) { /* 静默 */ }
  stopPolling()
  qrImage.value = ''
  qrStatusText.value = ''
  botToken.value = ''
  qrExpired.value = false
}

async function loadBindings() {
  try {
    const res = body(await api.wechatBindings())
    if (res && res.code === 0 && res.data) {
      bindings.value = res.data
    }
  } catch (e) { /* 静默 */ }
}

async function rescan() {
  tokenInvalid.value = false
  configured.value = false
  await startQr()
}

async function doRefreshBindings() {
  await loadBindings()
  emit('toast', '绑定列表已刷新')
}

async function unbind(b) {
  try {
    const res = body(await api.wechatUnbind(b.device_key))
    if (res && res.code === 0) {
      emit('toast', '解绑成功')
      await loadBindings()
    } else {
      emit('toast', (res && res.message) || '解绑失败')
    }
  } catch (e) {
    emit('toast', '解绑失败: ' + (e.message || e))
  }
}

onMounted(async () => {
  // 先检查是否已登录
  try {
    const res = body(await api.wechatQrStatus())
    if (res && res.code === 0 && res.data) {
      tokenInvalid.value = !!res.data.token_invalid
      if (res.data.configured) {
        configured.value = true
        loadBindings()
        // 已登录后定期检查 token 状态：失效时及时显示警示条
        statusTimer = setInterval(async () => {
          try {
            const r = body(await api.wechatQrStatus())
            if (r && r.code === 0 && r.data) tokenInvalid.value = !!r.data.token_invalid
          } catch { /* 静默 */ }
        }, 30000)
      }
    }
  } catch (e) { /* 静默 */ }
})

onBeforeUnmount(() => {
  stopPolling()
  if (statusTimer) { clearInterval(statusTimer); statusTimer = null }
})
</script>

<style scoped>
.wechat-view {
  max-width: 640px;
  margin: 0 auto;
  padding: 20px 16px 40px;
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.hero-bar {
  position: relative;
  overflow: hidden;
  padding: 28px 30px;
  border-radius: 20px;
}
.watermark {
  position: absolute;
  right: -8px;
  bottom: -18px;
  font-size: 90px;
  font-weight: 900;
  color: rgba(16, 185, 129, 0.08);
  line-height: 1;
  pointer-events: none;
  user-select: none;
}
.hero-title { font-size: 22px; font-weight: 700; margin: 0; }
.hero-sub { font-size: 13px; color: var(--text-sub); margin: 4px 0 0; }

/* 二维码区域 */
.qr-section {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 32px 24px;
  border-radius: 20px;
  gap: 20px;
}
.qr-header { text-align: center; }
.qr-header h3 { margin: 0 0 4px; font-size: 18px; }
.qr-hint { font-size: 13px; color: var(--text-sub); margin: 0; }
.qr-body { display: flex; flex-direction: column; align-items: center; gap: 12px; }
.qr-placeholder {
  display: flex; flex-direction: column; align-items: center; gap: 12px;
  padding: 40px; color: var(--text-sub);
}
.qr-image-wrap { display: flex; flex-direction: column; align-items: center; gap: 12px; }
.qr-image { width: 220px; height: 220px; border-radius: 12px; box-shadow: 0 4px 20px rgba(0,0,0,0.08); }
.qr-status { font-size: 13px; color: var(--text-sub); margin: 0; }
.qr-actions { display: flex; gap: 12px; }

/* 旋转动画 */
.spinner {
  width: 32px; height: 32px;
  border: 3px solid var(--mint-soft);
  border-top-color: var(--mint-deep);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }

/* 绑定管理 */
.status-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 14px 20px;
  border-radius: 16px;
  font-size: 13px;
}
.status-dot {
  width: 8px; height: 8px; border-radius: 50%;
  background: #ccc;
}
.status-dot.online { background: #22c55e; box-shadow: 0 0 8px rgba(34,197,94,0.4); }
.sep { color: var(--border); }

.bind-list { display: flex; flex-direction: column; gap: 12px; }
.bind-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px;
  border-radius: 16px;
  gap: 12px;
}
.bind-info { display: flex; align-items: center; gap: 14px; flex: 1; min-width: 0; }
.bind-avatar {
  width: 40px; height: 40px; border-radius: 12px;
  display: flex; align-items: center; justify-content: center;
  font-size: 16px; font-weight: 700; color: #fff;
  background: var(--grad-brand);
  flex-shrink: 0;
}
.bind-detail { min-width: 0; }
.bind-device { font-size: 14px; font-weight: 600; margin: 0; }
.bind-chat { font-size: 12px; color: var(--text-sub); margin: 2px 0 0; }
.bind-group { color: var(--mint-deep); font-size: 11px; }
.bind-time { font-size: 11px; color: var(--text-sub); margin: 2px 0 0; opacity: 0.7; }
.bind-unbind { flex-shrink: 0; }
.bind-empty {
  text-align: center;
  padding: 40px 20px;
  border-radius: 16px;
  color: var(--text-sub);
}
.bind-empty p { margin: 4px 0; }

.btn-sm { padding: 6px 16px; font-size: 12px; border-radius: 10px; }
.btn-outline {
  border: 1px solid var(--border);
  background: transparent;
  color: var(--text-main);
  padding: 8px 20px;
  font-size: 13px;
  border-radius: 12px;
  cursor: pointer;
  transition: all 0.25s var(--ease);
}
.btn-outline:hover {
  border-color: var(--mint-deep);
  color: var(--mint-deep);
  background: var(--mint-soft);
}

@media (max-width: 720px) {
  .wechat-view { padding: 12px 10px 32px; }
  .hero-bar { padding: 20px 18px; }
  .watermark { font-size: 64px; }
  .qr-section { padding: 24px 16px; }
  .qr-image { width: 180px; height: 180px; }
}
</style>