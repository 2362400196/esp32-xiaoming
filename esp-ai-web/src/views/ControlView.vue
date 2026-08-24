<template>
  <div class="control-view">
    <!-- 顶部渐变栏 + 首字母水印 -->
    <div class="hero-bar glass">
      <span class="watermark">C</span>
      <div class="hero-text">
        <h2 class="hero-title">控制<span class="text-mint">台</span></h2>
        <p class="hero-sub">向设备发号施令 · 实时对话 · 快捷控制</p>
      </div>
      <span class="hero-badge" v-if="currentDevice">
        <span class="hero-dot" :class="{ on: online }"></span>
        {{ online ? '在线' : '离线' }}
      </span>
    </div>

    <!-- 设备选择栏 -->
    <div class="device-bar" v-if="devices.length">
      <button v-for="d in devices" :key="d.device_id || d.id || d.mac"
        class="device-chip" :class="{ selected: isCurrent(d) }"
        @click="emit('select-device', d)">
        <span class="chip-dot" :class="{ on: d.online }"></span>
        <span class="chip-name">{{ d.name || '未命名设备' }}</span>
        <span class="chip-status">{{ d.online ? '在线' : '离线' }}</span>
      </button>
    </div>

    <!-- 未选择设备 -->
    <div v-if="!currentDevice" class="empty-state glass">
      <div class="empty-inner">
        <div class="empty-orb"><svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><line x1="4" y1="21" x2="4" y2="14"/><line x1="4" y1="10" x2="4" y2="3"/><line x1="12" y1="21" x2="12" y2="12"/><line x1="12" y1="8" x2="12" y2="3"/><line x1="20" y1="21" x2="20" y2="16"/><line x1="20" y1="12" x2="20" y2="3"/><line x1="1" y1="14" x2="7" y2="14"/><line x1="9" y1="8" x2="15" y2="8"/><line x1="17" y1="16" x2="23" y2="16"/></svg></div>
        <p class="empty-title">未选择设备</p>
        <p class="empty-sub">请在上方选择一台设备开始控制</p>
      </div>
    </div>

    <!-- 主体 -->
    <template v-if="currentDevice">
      <!-- 浮动状态卡片行 -->
      <div class="status-row">
        <div class="status-card glass card-in">
          <div class="s-head">
            <span class="s-icon"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><path d="M15.54 8.46a5 5 0 0 1 0 7.07"/><path d="M19.07 4.93a10 10 0 0 1 0 14.14"/></svg></span>
            <span class="s-label">音量</span>
          </div>
          <div class="s-body">
            <span class="s-value" :class="{ 's-loading': volLoading }">{{ volLoading ? '—' : volume + '%' }}</span>
            <input type="range" min="0" max="100" :value="volume"
              @input="onSlideInput('volume', $event)" @change="onVolumeChange"
              class="s-slider" :class="{ 's-slider-loading': volLoading }"
              :disabled="volLoading"
              :style="{ '--val': volume + '%' }" />
          </div>
        </div>
        <div class="status-card glass card-in" style="animation-delay:.06s">
          <div class="s-head">
            <span class="s-icon"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/></svg></span>
            <span class="s-label">已装插件</span>
          </div>
          <span class="s-value">{{ pluginCount }} 个</span>
        </div>
        <div class="status-card glass card-in" style="animation-delay:.12s">
          <div class="s-head">
            <span class="s-icon"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/></svg></span>
            <span class="s-label">亮度</span>
          </div>
          <div class="s-body">
            <span class="s-value" :class="{ 's-loading': brightLoading }">{{ brightLoading ? '—' : brightness + '%' }}</span>
            <input type="range" min="0" max="100" :value="brightness"
              @input="onSlideInput('brightness', $event)" @change="onBrightnessChange"
              class="s-slider" :class="{ 's-slider-loading': brightLoading }"
              :disabled="brightLoading"
              :style="{ '--val': brightness + '%' }" />
          </div>
        </div>
      </div>

      <!-- 底部：对话 -->
      <div class="bottom-grid">
        <!-- 对话控制台 -->
        <div class="chat-panel glass card-in">
          <div class="chat-head">
            <div class="chat-title-wrap">
              <span class="chat-title">对话控制台</span>
              <span class="chat-device">{{ currentDevice.name || '设备' }}</span>
            </div>
            <div class="chat-head-right">
              <span class="chat-count" v-if="history.length">{{ history.length }} 条</span>
              <div class="ds-stat">
                <span class="stat-dot" :class="{ on: online }"></span>
                <span class="stat-text">{{ online ? '在线' : '离线' }}</span>
              </div>
            </div>
          </div>

          <div class="timeline" ref="timelineEl">
            <div v-if="!history.length" class="timeline-empty">
              <div class="empty-orb small"><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"/></svg></div>
              <p class="empty-main">还没有对话记录</p>
              <p class="empty-sub">在下方输入指令，开始与设备对话</p>
            </div>
            <div v-for="(m, i) in history" :key="i" class="msg" :class="m.role">
              <div class="msg-bubble">{{ m.text }}</div>
              <div class="msg-meta">
                <span class="msg-time">{{ m.time }}</span>
                <span v-if="m.role === 'out' && m.status" class="msg-status" :class="m.status">
                  {{ m.status === 'sending' ? '发送中' : m.status === 'done' ? '已送达' : '失败' }}
                </span>
              </div>
            </div>
          </div>

          <div class="input-bar">
            <input class="cmd-input" v-model="cmdText"
              :placeholder="currentDevice ? '输入想对设备说的话' : '请先选择设备'"
              @keyup.enter="sendCmd" :disabled="!currentDevice" />
            <button class="btn-mint btn-sm cmd-send" @click="sendCmd"
              :disabled="!currentDevice || sending">
              {{ sending ? '发送中' : '发送' }}
            </button>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>

<script setup>
import { ref, computed, nextTick, watch } from 'vue'
import { api, isLoggedIn } from '../api'

const props = defineProps({
  currentDevice: Object,
  devices: { type: Array, default: () => [] },
  pluginCount: { type: Number, default: 0 },
})
const emit = defineEmits(['toast', 'select-device'])

const cmdText = ref('')
const volume = ref(50)
const volLoading = ref(false)
const brightness = ref(100)
const brightLoading = ref(false)
const sending = ref(false)
const history = ref([])
const timelineEl = ref(null)

const online = computed(() => props.currentDevice?.online === true)
const deviceId = computed(() => props.currentDevice?.device_id || props.currentDevice?.id || '')
// 音量接口标识符：后端 resolve_device_id 接受 mac / device_id / device_key 任意一个
const volumeId = computed(() => props.currentDevice?.mac || props.currentDevice?.device_id || props.currentDevice?.id || props.currentDevice?.device_key || '')

function isCurrent(d) {
  const did = d.device_id || d.id || d.mac || ''
  return did === (props.currentDevice?.device_id || props.currentDevice?.id || props.currentDevice?.mac || '')
}

// 独立加载设备当前音量，同步进度条（与对话历史解耦，不被 sending 阻断）
async function loadVolume() {
  const id = volumeId.value
  if (!id) return
  volLoading.value = true
  try {
    const res = await api.volume(id)
    if (res && res.status === 200 && res.data?.code === 0) {
      // 后端返回 0.0-1.0，UI 用 0-100 百分比
      volume.value = Math.round((res.data.data?.volume ?? 0.5) * 100)
    }
  } catch { /* ignore */ }
  volLoading.value = false
}

// 独立加载设备当前屏幕亮度（0-100 整数百分比）
async function loadBrightness() {
  const id = volumeId.value
  if (!id) return
  brightLoading.value = true
  try {
    const res = await api.brightness(id)
    if (res && res.status === 200 && res.data?.code === 0) {
      brightness.value = res.data.data?.brightness ?? 100
    }
  } catch { /* ignore */ }
  brightLoading.value = false
}

// 选中设备变化时同步音量 + 亮度 + 加载历史对话
watch(() => props.currentDevice, async (d, oldD) => {
  const newId = d?.device_id || d?.id || d?.mac || d?.device_key || ''
  const oldId = oldD?.device_id || oldD?.id || oldD?.mac || oldD?.device_key || ''
  if (newId === oldId) return  // 同一设备，不重载
  // 音量/亮度独立加载，不受 sending 影响
  loadVolume()
  loadBrightness()
  if (sending.value) return    // 正在发送中，不重载历史（保留本地状态）
  history.value = []
  if (!d) return
  const did = newId
  if (!did) return
  // 加载对话历史
  try {
    const hisRes = await api.deviceHistory(did)
    if (hisRes.status === 200 && hisRes.data?.code === 0) {
      const rawMsgs = hisRes.data.data?.messages || []
      history.value = rawMsgs.map(m => ({
        role: m.role === 'user' ? 'out' : 'in',
        text: m.content || '',
        time: m.timestamp ? _fmtTime(m.timestamp) : '',
      }))
      await scrollToBottom()
    }
  } catch { /* ignore */ }
}, { immediate: true })

function nowTime() {
  const d = new Date()
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

function _fmtTime(ts) {
  if (!ts) return ''
  const d = new Date(ts * 1000)
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

async function scrollToBottom() {
  await nextTick()
  const el = timelineEl.value
  if (el) el.scrollTop = el.scrollHeight
}

async function runCommand(action, text, displayText) {
  if (!props.currentDevice) { emit('toast', '请先选择设备'); return }
  if (!isLoggedIn()) { emit('toast', '请先登录'); return }
  if (sending.value) return

  if (action === 'stop') {
    await api.deviceStop(deviceId.value).catch(() => {})
    emit('toast', '已停止播放')
    return
  }

  sending.value = true
  const outMsg = { role: 'out', text: displayText, time: nowTime(), status: 'sending' }
  history.value.push(outMsg)
  await scrollToBottom()

  try {
    const res = await api.deviceAction(deviceId.value, action, text || '')
    console.log('[CMD] response:', res.status, res.data)
    if (res.status === 200 && res.data?.code === 0) {
      outMsg.status = 'done'
      // 优先取 LLM 回复文本；没有则不追加回复气泡
      const reply = res.data.data?.reply || (res.data.message && res.data.message !== '已发送' ? res.data.message : '')
      if (reply) {
        history.value.push({ role: 'in', text: reply, time: nowTime() })
      }
    } else {
      outMsg.status = 'fail'
      const errMsg = res.data?.message || res.data?.detail || res.error || '执行失败'
      emit('toast', errMsg)
      console.error('[CMD] 失败:', errMsg, res)
    }
  } catch (err) {
    outMsg.status = 'fail'
    emit('toast', '错误: ' + (err?.message || err))
    console.error('[CMD] 异常:', err)
  }
  await scrollToBottom()
  sending.value = false
}

function sendCmd() {
  const t = cmdText.value.trim()
  if (!t || !props.currentDevice || sending.value) return
  cmdText.value = ''
  runCommand('chat', t, t)
}

// 滑块拖动时只更新本地显示值（不发请求，避免限流）
function onSlideInput(which, e) {
  const v = Number(e.target.value)
  if (which === 'volume') volume.value = v
  else if (which === 'brightness') brightness.value = v
}

// 音量滑块松手时发送请求
async function onVolumeChange() {
  const v = volume.value
  const id = volumeId.value
  if (!id) return
  const res = await api.setVolume(id, v).catch(() => null)
  if (!res || res.status !== 200 || res.data?.code !== 0) {
    emit('toast', res?.data?.message || '音量设置失败')
    loadVolume()  // 回滚到设备实际值
  }
}

// 亮度滑块松手时发送请求
async function onBrightnessChange() {
  const v = brightness.value
  const id = volumeId.value
  if (!id) return
  const res = await api.setBrightness(id, v).catch(() => null)
  if (!res || res.status !== 200 || res.data?.code !== 0) {
    emit('toast', res?.data?.message || '亮度设置失败')
    loadBrightness()  // 回滚到设备实际值
  }
}
</script>

<style scoped>
.control-view { padding: 28px 0 56px; }

/* ===== 通用玻璃 ===== */
.glass {
  background: var(--grad-card);
  backdrop-filter: var(--glass-blur);
  -webkit-backdrop-filter: var(--glass-blur);
  border: 1px solid var(--glass-border);
  box-shadow: var(--shadow), var(--glass-hi);
  border-radius: var(--radius-lg);
}

/* ===== 顶部渐变栏 + 首字母水印 ===== */
.hero-bar {
  position: relative;
  overflow: hidden;
  padding: 30px 34px 24px;
  margin-bottom: 22px;
}
.hero-bar::before {
  content: '';
  position: absolute; top: 0; left: 0; right: 0; height: 3px;
  background: var(--grad-brand);
}
.hero-bar::after {
  content: '';
  position: absolute; inset: 0;
  background: var(--grad-hero);
  pointer-events: none;
}
.watermark {
  position: absolute;
  right: 24px; top: 50%;
  transform: translateY(-50%);
  font-size: 120px;
  font-weight: 900;
  line-height: 1;
  color: var(--mint);
  opacity: 0.06;
  pointer-events: none;
  user-select: none;
}
.hero-text { position: relative; z-index: 1; }
.hero-title { font-size: 24px; font-weight: 800; letter-spacing: -0.3px; }
.hero-sub { margin-top: 4px; font-size: 13px; color: var(--text-sub); }
.hero-badge {
  position: absolute; top: 24px; right: 28px; z-index: 2;
  display: inline-flex; align-items: center; gap: 6px;
  padding: 5px 14px; border-radius: 999px;
  font-size: 12px; font-weight: 600; color: var(--text-sub);
  background: rgba(255, 255, 255, 0.55);
  border: 1px solid var(--glass-border);
  backdrop-filter: var(--glass-blur-sm);
}
.hero-dot { width: 7px; height: 7px; border-radius: 50%; background: var(--danger); }
.hero-dot.on { background: var(--mint); box-shadow: 0 0 0 3px rgba(16, 185, 129, 0.18); }

/* ===== 设备选择栏 ===== */
.device-bar {
  display: flex;
  gap: 10px;
  margin-bottom: 20px;
  overflow-x: auto;
  padding-bottom: 4px;
}
.device-chip {
  display: flex; align-items: center; gap: 8px;
  flex-shrink: 0;
  padding: 9px 18px;
  border-radius: 999px;
  border: 1px solid var(--glass-border);
  background: var(--glass-bg-strong);
  backdrop-filter: var(--glass-blur-sm);
  -webkit-backdrop-filter: var(--glass-blur-sm);
  box-shadow: var(--shadow-xs), var(--glass-hi);
  cursor: pointer;
  transition: all 0.25s var(--ease);
}
.device-chip:hover {
  border-color: var(--mint-border);
  background: var(--mint-softer);
  transform: translateY(-1px);
}
.device-chip.selected {
  background: var(--mint-soft);
  border-color: var(--mint);
  animation: chipBreath 2.5s ease-in-out infinite;
}
@keyframes chipBreath {
  0%, 100% { box-shadow: 0 0 0 0 rgba(16,185,129,0.0); }
  50% { box-shadow: 0 0 0 4px rgba(16,185,129,0.14); }
}
.chip-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--text-dim); transition: background 0.2s; }
.chip-dot.on { background: var(--mint); }
.chip-name { font-size: 13px; font-weight: 600; }
.chip-status { font-size: 11px; color: var(--text-dim); }
.device-chip.selected .chip-status { color: var(--mint-deep); }

/* ===== 空状态 ===== */
.empty-state { padding: 64px; text-align: center; }
.empty-orb {
  width: 64px; height: 64px; margin: 0 auto 16px;
  display: flex; align-items: center; justify-content: center;
  font-size: 30px;
  border-radius: 50%;
  background: var(--mint-soft);
  border: 1px solid var(--mint-border);
  box-shadow: 0 8px 22px rgba(16, 185, 129, 0.16);
}
.empty-orb.small { width: 52px; height: 52px; font-size: 24px; }
.empty-title { font-size: 16px; font-weight: 700; color: var(--text-sub); }
.empty-sub { margin-top: 6px; font-size: 13px; color: var(--text-dim); }

/* ===== 状态卡片行 ===== */
.status-row {
  display: grid;
  grid-template-columns: 1.4fr 1fr 1fr;
  gap: 14px;
  margin-bottom: 20px;
}
.status-card {
  display: flex; flex-direction: column; gap: 12px;
  padding: 20px 24px;
  transition: transform 0.3s var(--ease), box-shadow 0.3s var(--ease), border-color 0.3s var(--ease);
}
.status-card:hover {
  transform: translateY(-4px);
  box-shadow: var(--shadow-md), var(--glass-hi);
  border-color: rgba(255, 255, 255, 0.92);
}
.s-head { display: flex; align-items: center; gap: 8px; }
.s-icon { font-size: 18px; filter: drop-shadow(0 2px 6px rgba(16, 185, 129, 0.2)); display: inline-flex; align-items: center; color: var(--mint-deep); }
.s-label { font-size: 13px; color: var(--text-sub); font-weight: 500; }
.s-value { font-size: 22px; font-weight: 800; color: var(--mint-deep); letter-spacing: -0.3px; }
.s-value.s-loading { color: var(--text-dim); opacity: 0.6; }
.s-slider.s-slider-loading { opacity: 0.5; cursor: wait; }
.s-slider.s-slider-loading::-webkit-slider-thumb { background: var(--text-dim); }
.s-body { display: flex; align-items: center; gap: 14px; }
.s-slider {
  -webkit-appearance: none; appearance: none;
  width: 120px; height: 6px; border-radius: 4px;
  background: linear-gradient(90deg, var(--mint) 0%, var(--mint) var(--val,50%), rgba(255,255,255,0.7) var(--val,50%));
  outline: none; cursor: pointer;
  border: 1px solid rgba(255, 255, 255, 0.5);
}
.s-slider::-webkit-slider-thumb {
  -webkit-appearance: none; width: 18px; height: 18px; border-radius: 50%;
  background: var(--grad-mint); cursor: pointer;
  box-shadow: var(--shadow-mint), inset 0 1px 0 rgba(255, 255, 255, 0.35);
  transition: transform 0.2s var(--ease);
}
.s-slider::-webkit-slider-thumb:hover { transform: scale(1.15); }
.s-slider::-moz-range-thumb {
  width: 18px; height: 18px; border-radius: 50%; border: none;
  background: var(--mint); cursor: pointer; box-shadow: var(--shadow-mint);
}

/* ===== 对话面板 ===== */
.bottom-grid { display: grid; grid-template-columns: 1fr; gap: 18px; align-items: start; }

.chat-panel {
  display: flex; flex-direction: column;
  overflow: hidden;
  min-height: 440px;
}
.chat-head {
  display: flex; align-items: center; justify-content: space-between;
  padding: 16px 22px; border-bottom: 1px solid var(--glass-border-soft);
}
.chat-title-wrap { display: flex; align-items: center; gap: 10px; min-width: 0; }
.chat-title { font-size: 15px; font-weight: 700; }
.chat-device {
  font-size: 11px; font-weight: 600; color: var(--mint-deep);
  background: var(--mint-soft); padding: 3px 10px; border-radius: 999px;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 160px;
}
.chat-head-right { display: flex; align-items: center; gap: 14px; }
.chat-count { font-size: 11px; color: var(--text-dim); }
.ds-stat { display: flex; align-items: center; gap: 6px; font-size: 13px; color: var(--text-sub); }
.stat-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--danger); }
.stat-dot.on {
  background: var(--mint);
  box-shadow: 0 0 0 3px rgba(16,185,129,0.16);
  animation: statPulse 2s ease-in-out infinite;
}
@keyframes statPulse {
  0%, 100% { box-shadow: 0 0 0 3px rgba(16,185,129,0.16); }
  50% { box-shadow: 0 0 0 5px rgba(16,185,129,0.08); }
}
.stat-text { font-size: 12px; font-weight: 600; }

.timeline {
  flex: 1; overflow-y: auto; padding: 20px 22px;
  display: flex; flex-direction: column; gap: 12px;
  min-height: 280px; max-height: 420px;
}
.timeline-empty {
  flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center;
  gap: 4px; color: var(--text-dim);
}
.empty-main { font-size: 14px; color: var(--text-sub); font-weight: 600; }
.empty-sub { font-size: 12px; color: var(--text-dim); }

.msg { display: flex; flex-direction: column; max-width: 80%; animation: msgIn 0.3s var(--ease) both; }
@keyframes msgIn { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: none; } }
.msg.out { align-self: flex-end; align-items: flex-end; }
.msg.in { align-self: flex-start; align-items: flex-start; }
.msg-bubble {
  padding: 10px 16px; font-size: 13px; line-height: 1.5; word-break: break-word;
}
.msg.out .msg-bubble {
  background: var(--grad-mint); color: #fff;
  border-radius: 14px 14px 4px 14px;
  box-shadow: var(--shadow-mint);
}
.msg.in .msg-bubble {
  background: rgba(255, 255, 255, 0.72);
  backdrop-filter: var(--glass-blur-sm);
  color: var(--text-main);
  border: 1px solid var(--glass-border);
  border-radius: 14px 14px 14px 4px;
}
.msg-meta {
  display: flex; align-items: center; gap: 8px;
  margin-top: 3px; padding: 0 4px;
}
.msg-time { font-size: 10px; color: var(--text-dim); }
.msg-status { font-size: 10px; font-weight: 500; }
.msg-status.done { color: var(--mint); }
.msg-status.sending { color: var(--text-dim); }
.msg-status.fail { color: var(--danger); }

.input-bar {
  display: flex; align-items: center; gap: 10px;
  padding: 14px 18px; border-top: 1px solid var(--glass-border-soft);
}
.cmd-input {
  flex: 1; border: 1px solid var(--glass-border); border-radius: 999px;
  padding: 10px 18px; font-size: 13px; color: var(--text-main);
  background: rgba(255, 255, 255, 0.6);
  outline: none;
  transition: border-color 0.2s, box-shadow 0.2s, background 0.2s;
}
.cmd-input::placeholder { color: var(--text-dim); }
.cmd-input:focus { border-color: var(--mint-border); background: rgba(255, 255, 255, 0.85); box-shadow: 0 0 0 3px var(--mint-soft); }
.cmd-input:disabled { background: var(--glass-bg-soft); cursor: not-allowed; }
.btn-sm { padding: 9px 22px; font-size: 12px; }
.cmd-send { white-space: nowrap; }

/* ===== 响应式 ===== */
@media (max-width: 760px) {
  .status-row { grid-template-columns: 1fr; }
  .bottom-grid { grid-template-columns: 1fr; }
  .hero-title { font-size: 20px; }
  .watermark { font-size: 80px; }
  .hero-badge { top: 18px; right: 18px; }
  .s-slider { width: 80px; }
  .timeline { max-height: 280px; }
}
</style>