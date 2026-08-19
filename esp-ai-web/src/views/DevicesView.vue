<template>
  <div class="devices-view" @dblclick="resetLayout">
      <div v-if="!devices.length && !loading" class="empty card card-in">
        <p>还没有设备</p>
        <p class="empty-sub">在 App 中完成配网绑定后，这里会自动出现</p>
      </div>
      <!-- OLD_TOP_START
      
          
            
            
          </div>
          
            
            
          </button>
        </div>

        <div v-if="!devices.length && !loading" class="empty card card-in">
          
          
          
          
          </div>
          <!--
        </div>
        
        
      </div>
    
      
      
    </div>

          -->
            
      <!-- 贴纸画板 -->
    <div ref="board" class="sticker-board">
      <div v-for="(d, i) in devices" :key="d.device_id || d.id"
        class="device-sticker"
        :class="{ active: isActive(d), dragging: dragId === devKey(d), offline: !isOnline(d) }"
        :style="cardStyle(d, i)"
        @mousedown="onDragStart($event, d)"
        @touchstart.passive="onDragStart($event, d)">

        <!-- 拖拽手柄 -->
        <div class="drag-handle"><span class="handle-dots">⋮⋮</span></div>

        <!-- 方形设备 -->
        <div class="device-hardware" :style="hardwareStyle(d)"
          @mouseenter="hoveredDevice = devKey(d)" @mouseleave="hoveredDevice = ''">
          <!-- 设备边框装饰 -->
          <div class="device-bezel"></div>

          <!-- 屏幕 -->
          <div class="device-screen" :class="{ 'screen-off': !isOnline(d) }">
            <!-- 屏幕顶部状态栏 -->
            <div class="screen-statusbar" v-if="isOnline(d)">
              <div class="status-left">
                <svg class="icon-wifi" viewBox="0 0 16 16" width="12" height="12">
                  <path d="M8 12.5a1 1 0 100-2 1 1 0 000 2zM8 9.5a3 3 0 012.5 1.35l1.2-1.2A4.8 4.8 0 008 7.5a4.8 4.8 0 00-3.7 1.15l1.2 1.2A3 3 0 018 9.5zM8 6a6.5 6.5 0 014.6 1.9l1.1-1.1A8.2 8.2 0 008 4a8.2 8.2 0 00-5.7 2.8l1.1 1.1A6.5 6.5 0 018 6z"
                    fill="currentColor"/>
                </svg>
                <span class="status-label" v-if="isActive(d)">{{ d.name || '设备' }}</span>
              </div>
              <div class="status-right">
                <div class="icon-battery">
                  <div class="battery-body">
                    <div class="battery-level" :style="{ width: batteryPct(d) + '%' }"></div>
                  </div>
                  <div class="battery-cap"></div>
                </div>
              </div>
            </div>

            <!-- 屏幕内容 -->
            <div class="screen-content" v-if="isOnline(d)">
              <img v-if="sleepGifUrl(d)" :src="sleepGifUrl(d)" alt="sleep" class="screen-gif"
                draggable="false" @error="onGifError(d)" loading="lazy" />
              <div v-else class="screen-emoji">💤</div>
            </div>

            <!-- 离线黑屏 -->
            <div class="screen-off-content" v-else>
              <div class="screen-off-text">OFF</div>
            </div>

            <!-- 屏幕反光 -->
            <div class="screen-glare" v-if="isOnline(d)"></div>
          </div>

          <!-- 底部呼吸灯 -->
          <div class="device-led" :class="{ on: isOnline(d) }"></div>
        </div>

        <!-- 悬停屏幕时显示的操作浮层 -->
        <transition name="overlay-fade">
          <div v-if="hoveredDevice === devKey(d)" class="screen-overlay" @mouseenter="hoveredDevice = devKey(d)" @mouseleave="hoveredDevice = null">
            <button class="overlay-btn" @mousedown.stop @touchstart.stop @click.stop="$emit('settings', d)">设置</button>
            <button class="overlay-btn danger" @mousedown.stop @touchstart.stop @click.stop="openUnbindDialog(d)">解绑</button>
          </div>
        </transition>
      </div>
    </div>


      <!-- 绑定设备弹窗 -->
      <transition name="modal-fade">
        <div v-if="bindDialogVisible" class="modal-mask" @click.self="closeBindDialog" @dblclick.stop>
          <div class="modal-card">
            <div class="modal-head">
              <span class="modal-title">绑定设备</span>
              <button class="modal-close" @click="closeBindDialog">×</button>
            </div>
            <div class="modal-body">
              <p class="bind-tip">输入设备屏幕上显示的 6 位绑定码完成绑定</p>
              <input v-model="bindCode" class="input bind-input" placeholder="6 位绑定码" maxlength="6" @keyup.enter="doBind" />
              <input v-model="bindName" class="input bind-input" placeholder="设备名称（可选）" @keyup.enter="doBind" />
            </div>
            <div class="modal-foot">
              <button class="btn-sm" @click="closeBindDialog">取消</button>
              <button class="btn-sm btn-mint" :disabled="binding" @click="doBind">
                {{ binding ? '绑定中...' : '确认绑定' }}
              </button>
            </div>
          </div>
        </div>
      </transition>
    <!-- 解绑确认弹窗 -->
    <transition name="modal-fade">
      <div v-if="unbindDialogVisible" class="modal-mask" @click.self="closeUnbindDialog" @dblclick.stop>
        <div class="modal-card">
          <div class="modal-head danger-head">
            <span class="modal-title">解绑设备</span>
            <button class="modal-close" @click="closeUnbindDialog">×</button>
          </div>
          <div class="modal-body">
            <div class="warn-icon">!</div>
            <p class="warn-text">此操作将清空设备所有配置，相当于恢复出厂设置。</p>
            <p class="warn-device">{{ unbindTarget?.name || unbindTarget?.device_id || '未命名设备' }}</p>
            <p v-if="unbindStep === 1" class="warn-sub">请再三考虑！确定要解绑吗？</p>
            <p v-else class="warn-sub warn-final">这是最后警告！解绑后所有配置将被永久清空。</p>
          </div>
          <div class="modal-foot">
            <button class="btn-sm" @click="closeUnbindDialog">取消</button>
            <button v-if="unbindStep === 1" class="btn-sm btn-danger" @click="nextStep">我确定要解绑</button>
            <button v-else class="btn-sm btn-danger" :disabled="unbinding" @click="doUnbind">
              {{ unbinding ? '解绑中...' : '确认解绑' }}
            </button>
          </div>
        </div>
      </div>
    </transition>
  </div>
</template>

<script setup>
import { ref, watch, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { api } from '../api'

const props = defineProps({
  devices: { type: Array, default: () => [] },
  selected: Object,
  loading: { type: Boolean, default: false },
})
const emit = defineEmits(['select', 'speak', 'stop', 'settings', 'unbind', 'bound', 'toast'])

// ===== 绑定设备 =====
const bindDialogVisible = ref(false)
const bindCode = ref('')
const bindName = ref('')
const binding = ref(false)

function openBindDialog() {
  bindCode.value = ''
  bindName.value = ''
  bindDialogVisible.value = true
}

function closeBindDialog() {
  if (binding.value) return
  bindDialogVisible.value = false
}

async function doBind() {
  const code = bindCode.value.trim()
  if (!code) { emit('toast', '请输入绑定码'); return }
  if (code.length !== 6) { emit('toast', '绑定码应为 6 位'); return }
  binding.value = true
  try {
    const res = await api.bindDeviceByCode(code, bindName.value.trim())
    if (res.status === 200 && res.data?.code === 0) {
      emit('toast', '绑定成功')
      bindDialogVisible.value = false
      emit('bound')
    } else {
      const msg = res.data?.message || res.data?.detail || '绑定失败'
      const friendly = msg === 'Bind code expired' ? '绑定码已过期，请刷新设备屏幕获取新码'
        : msg === 'Device not found or bind code invalid' ? '绑定码无效，请检查输入的码是否正确'
        : msg === 'Device already bound to another user' ? '该设备已被其他用户绑定'
        : msg
      emit('toast', friendly)
    }
  } catch {
    emit('toast', '绑定失败')
  }
  binding.value = false
}

// ===== 随机外壳颜色 =====
const deviceColors = ref({})

// 预设的柔和颜色池（排除白色）
const COLOR_POOL = [
  { bg: '#fce4ec', dark: '#f8bbd0' }, // 樱花粉
  { bg: '#e8f5e9', dark: '#c8e6c9' }, // 薄荷绿
  { bg: '#e3f2fd', dark: '#bbdefb' }, // 天空蓝
  { bg: '#fff3e0', dark: '#ffe0b2' }, // 暖橙
  { bg: '#f3e5f5', dark: '#e1bee7' }, // 薰衣草
  { bg: '#efebe9', dark: '#d7ccc8' }, // 摩卡棕
  { bg: '#e0f7fa', dark: '#b2ebf2' }, // 青碧
  { bg: '#fffde7', dark: '#fff9c4' }, // 奶油黄
  { bg: '#fce4ec', dark: '#f48fb1' }, // 蜜桃粉
  { bg: '#e8eaf6', dark: '#c5cae9' }, // 雾霾蓝
  { bg: '#f1f8e9', dark: '#dcedc8' }, // 嫩芽绿
  { bg: '#fff8e1', dark: '#ffecb3' }, // 香槟金
]

function randomColor() {
  return COLOR_POOL[Math.floor(Math.random() * COLOR_POOL.length)]
}

function hardwareStyle(d) {
  const key = devKey(d)
  if (!deviceColors.value[key]) {
    deviceColors.value[key] = randomColor()
  }
  const c = deviceColors.value[key]
  return {
    background: `linear-gradient(145deg, ${c.bg} 0%, ${c.dark} 100%)`,
  }
}

// ===== 拖拽状态 =====
const board = ref(null)
const dragId = ref('')
const hoveredDevice = ref('')
const dragOffset = { x: 0, y: 0 }
const positions = ref({})
const dragStartPoint = { x: 0, y: 0 }
const hasMoved = ref(false)

// ===== GIF 加载 =====
const defaultSleepGif = ref('')
const devicePackGifs = ref({})  // deviceId -> sleep gif url
const gifErrorSet = ref(new Set())
// GIF 缓存刷新版本号：重新加载 sleep 表情后自增，URL 追加 ?v= 强制浏览器拉取最新文件
const sleepGifVersion = ref(0)

function devKey(d) {
  return d.device_id || d.id || d.mac || ''
}

function isOnline(d) {
  return !!(d.online || d.connected)
}

function isActive(d) {
  const sid = props.selected?.device_id || props.selected?.id
  const did = devKey(d)
  return !!(sid && did && sid === did)
}

// 获取设备的 sleep gif URL
function sleepGifUrl(d) {
  const key = devKey(d)
  if (gifErrorSet.value.has(key)) return ''
  // 优先使用设备专属表情包
  let url = devicePackGifs.value[key]
  // 回退到默认表情包
  if (!url) url = defaultSleepGif.value
  return url ? `${url}?v=${sleepGifVersion.value}` : ''
}

function onGifError(d) {
  gifErrorSet.value.add(devKey(d))
}

// 电池电量（后端无数据，用设备ID hash 模拟一个稳定值）
function batteryPct(d) {
  const key = devKey(d)
  if (!key) return 85
  let hash = 0
  for (let i = 0; i < key.length; i++) hash = ((hash << 5) - hash + key.charCodeAt(i)) | 0
  return 55 + (Math.abs(hash) % 45)  // 55%-99%
}

// 计算卡片样式
function cardStyle(d, i) {
  const key = devKey(d)
  let pos = positions.value[key]
  if (!pos) {
    const cols = 4
    const cardW = 200
    const cardH = 280
    const gap = 20
    const col = i % cols
    const row = Math.floor(i / cols)
    pos = { x: col * (cardW + gap) + 16, y: row * (cardH + gap) }
  }
  const isDragging = dragId.value === key
  return {
    left: pos.x + 'px',
    top: pos.y + 'px',
    transform: isDragging ? 'scale(1.05) rotate(-1deg)' : 'rotate(0deg)',
    zIndex: isDragging ? 100 : (isActive(d) ? 10 : 1),
    animationDelay: (i * 0.05) + 's',
  }
}

// 获取事件坐标
function getPoint(e) {
  if (e.touches && e.touches.length) {
    return { x: e.touches[0].clientX, y: e.touches[0].clientY }
  }
  return { x: e.clientX, y: e.clientY }
}

// 拖拽逻辑
function onDragStart(e, d) {
  if (e.target.closest('.overlay-btn')) return
  const key = devKey(d)
  if (!key) return
  const rect = e.currentTarget.getBoundingClientRect()
  const boardRect = board.value?.getBoundingClientRect()
  const point = getPoint(e)
  dragOffset.x = point.x - rect.left
  dragOffset.y = point.y - rect.top
  dragStartPoint.x = point.x
  dragStartPoint.y = point.y
  hasMoved.value = false
  dragId.value = key
  if (!positions.value[key]) {
    positions.value[key] = { x: rect.left - (boardRect?.left || 0), y: rect.top - (boardRect?.top || 0) }
  }
  document.addEventListener('mousemove', onDragMove)
  document.addEventListener('mouseup', onDragEnd)
  document.addEventListener('touchmove', onDragMove, { passive: false })
  document.addEventListener('touchend', onDragEnd)
}

function onDragMove(e) {
  if (!dragId.value || !board.value) return
  const point = getPoint(e)
  const dx = Math.abs(point.x - dragStartPoint.x)
  const dy = Math.abs(point.y - dragStartPoint.y)
  if (dx > 4 || dy > 4) hasMoved.value = true
  if (hasMoved.value) e.preventDefault?.()
  const boardRect = board.value.getBoundingClientRect()
  let x = point.x - boardRect.left - dragOffset.x
  let y = point.y - boardRect.top - dragOffset.y
  const cardW = 200
  x = Math.max(-cardW * 0.3, Math.min(x, boardRect.width - cardW * 0.7))
  y = Math.max(-20, Math.min(y, boardRect.height - 40))
  positions.value[dragId.value] = { x, y }
}

function onDragEnd() {
  if (dragId.value) {
    savePositions()
    if (!hasMoved.value) {
      const d = props.devices.find(dev => devKey(dev) === dragId.value)
      if (d) emit('select', d)
    }
    dragId.value = ''
    hasMoved.value = false
  }
  document.removeEventListener('mousemove', onDragMove)
  document.removeEventListener('mouseup', onDragEnd)
  document.removeEventListener('touchmove', onDragMove)
  document.removeEventListener('touchend', onDragEnd)
}

function savePositions() {
  try { localStorage.setItem('espai_device_positions', JSON.stringify(positions.value)) } catch {}
}

function loadPositions() {
  try {
    const saved = localStorage.getItem('espai_device_positions')
    if (saved) positions.value = JSON.parse(saved)
  } catch {}
}

function resetLayout() {
  positions.value = {}
  try { localStorage.removeItem('espai_device_positions') } catch {}
  emit('toast', '已重置布局')
}

// ===== 加载默认表情包的 sleep.gif =====
async function loadDefaultSleepGif() {
  try {
    const res = await api.emoPackDetail('default')
    if (res?.data?.code === 0 && Array.isArray(res.data.data)) {
      const sleep = res.data.data.find(e => e.name === 'sleep' || e.filename === 'sleep.gif')
      if (sleep) {
        defaultSleepGif.value = sleep.url
        sleepGifVersion.value++
      }
    }
  } catch {}
}

// ===== 为选中设备加载其活跃表情包 =====
async function loadDevicePack(device) {
  const key = devKey(device)
  if (!key) return
  try {
    const activeRes = await api.getActiveEmoPack(key)
    if (activeRes?.data?.code === 0 && activeRes.data.data?.pack) {
      const packName = activeRes.data.data.pack
      if (packName === 'default') {
        devicePackGifs.value[key] = ''
        return
      }
      const packRes = await api.emoPackDetail(packName)
      if (packRes?.data?.code === 0 && Array.isArray(packRes.data.data)) {
        const sleep = packRes.data.data.find(e => e.name === 'sleep' || e.filename === 'sleep.gif')
        if (sleep) {
          devicePackGifs.value[key] = sleep.url
          sleepGifVersion.value++
        }
      }
    }
  } catch {}
}

// ===== 解绑功能 =====
const unbindDialogVisible = ref(false)
const unbindTarget = ref(null)
const unbindStep = ref(1)
const unbinding = ref(false)

function openUnbindDialog(d) {
  unbindTarget.value = d
  unbindStep.value = 1
  unbindDialogVisible.value = true
}

function closeUnbindDialog() {
  if (unbinding.value) return
  unbindDialogVisible.value = false
  unbindTarget.value = null
  unbindStep.value = 1
}

function nextStep() { unbindStep.value = 2 }

async function doUnbind() {
  if (!unbindTarget.value || unbinding.value) return
  const d = unbindTarget.value
  const id = d.mac || d.device_id || d.id || ''
  if (!id) { emit('toast', '设备标识无效'); return }
  unbinding.value = true
  const res = await api.deviceUnbind(id).catch(() => null)
  unbinding.value = false
  if (res?.data?.code === 0) {
    closeUnbindDialog()
    emit('unbind', d)
  } else {
    closeUnbindDialog()
    emit('toast', res?.data?.message || '解绑失败')
  }
}

// ===== 画板高度 =====
function updateBoardHeight() {
  if (!board.value || !props.devices.length) return
  const cols = 4
  const gap = 20
  const rows = Math.ceil(props.devices.length / cols)
  const minH = rows * (280 + gap) + 40
  board.value.style.minHeight = Math.max(minH, 400) + 'px'
}

onMounted(() => {
  loadPositions()
  loadDefaultSleepGif()
  nextTick(updateBoardHeight)
})

onBeforeUnmount(() => { onDragEnd() })

// 监听选中设备变化，加载其表情包
watch(() => props.selected, (d) => {
  if (d && isOnline(d)) loadDevicePack(d)
}, { immediate: true })

watch(() => props.devices, () => { nextTick(updateBoardHeight) }, { deep: true })
</script>

<style scoped>
.devices-view { padding: 40px 0 60px; }

/* ===== 贴纸画板 ===== */
.sticker-board {
  position: relative;
  min-height: 400px;
  width: 100%;
  background: radial-gradient(circle at 1px 1px, var(--border-soft, rgba(0,0,0,0.04)) 1px, transparent 0);
  background-size: 24px 24px;
  border-radius: var(--radius-lg);
  border: 1px dashed var(--border);
  padding: 16px;
  overflow: visible;
}

/* ===== 设备贴纸 ===== */
.device-sticker {
  position: absolute;
  width: 200px;
  cursor: grab;
  transition: transform 0.2s var(--ease), box-shadow 0.25s var(--ease);
  user-select: none;
  -webkit-user-select: none;
  -webkit-touch-callout: none;
  outline: none;
  animation: cardIn 0.5s var(--ease-spring) both;
}
.device-sticker * {
  user-select: none;
  -webkit-user-select: none;
  -webkit-touch-callout: none;
  outline: none;
}
.device-sticker:hover { transform: translateY(-2px) rotate(0.5deg); }
.device-sticker:active { cursor: grabbing; }
.device-sticker.dragging {
  cursor: grabbing;
  box-shadow: 0 16px 40px rgba(0,0,0,0.18);
  transition: none;
}
.device-sticker.active .device-hardware {
  transform: scale(1.06);
  box-shadow: 0 0 0 3px var(--mint-bright), 0 8px 24px rgba(16,185,129,0.3);
}
.device-sticker.active .device-led.on {
  background: var(--mint-bright);
  opacity: 1;
  box-shadow: 0 0 10px var(--mint-glow);
  animation: ledBreathe 1.2s ease-in-out infinite;
}
.device-sticker.dragging.active .device-hardware { transform: scale(1.05); }

/* 拖拽手柄 */
.drag-handle {
  position: absolute; top: 6px; left: 50%;
  transform: translateX(-50%);
  width: 32px; height: 6px;
  display: flex; align-items: center; justify-content: center;
  opacity: 0.2; transition: opacity 0.2s; pointer-events: none;
  z-index: 5;
}
.handle-dots { font-size: 12px; letter-spacing: -2px; color: var(--text-dim); line-height: 6px; }
.device-sticker:hover .drag-handle { opacity: 0.4; }

/* ===== 方形设备硬件 ===== */
.device-hardware {
  position: relative;
  width: 100%;
  aspect-ratio: 1;
  border-radius: 24px;
  padding: 12px;
  border: none;
  box-shadow: none;
  transition: transform 0.3s var(--ease);
}

/* 设备边框装饰 */
.device-bezel {
  position: absolute;
  top: 6px; left: 50%;
  transform: translateX(-50%);
  width: 40px; height: 3px;
  border-radius: 999px;
  background: rgba(0,0,0,0.06);
}

/* ===== 屏幕 ===== */
.device-screen {
  position: relative;
  width: 100%; height: 100%;
  border-radius: 10px;
  overflow: hidden;
  background: #0a0e14;
  box-shadow: inset 0 0 0 1px rgba(255,255,255,0.04);
}
.device-screen.screen-off {
  background: #000;
}

/* 屏幕顶部状态栏 */
.screen-statusbar {
  position: absolute;
  top: 0; left: 0; right: 0;
  height: 22px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 8px;
  background: rgba(0,0,0,0.5);
  backdrop-filter: blur(4px);
  z-index: 3;
}
.status-left { display: flex; align-items: center; gap: 4px; color: rgba(255,255,255,0.8); }
.status-label {
  font-size: 9px; font-weight: 600; color: rgba(255,255,255,0.7);
  max-width: 80px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.icon-wifi { color: var(--mint-bright); opacity: 0.9; }
.status-right { display: flex; align-items: center; gap: 4px; }

/* 电池图标 */
.icon-battery { display: flex; align-items: center; }
.battery-body {
  width: 18px; height: 9px;
  border: 1px solid rgba(255,255,255,0.5);
  border-radius: 2px;
  padding: 1px;
  display: flex; align-items: center;
}
.battery-level {
  height: 100%;
  background: var(--mint-bright);
  border-radius: 1px;
  transition: width 0.5s var(--ease);
}
.battery-cap {
  width: 1.5px; height: 4px;
  background: rgba(255,255,255,0.5);
  border-radius: 0 1px 1px 0;
  margin-left: 1px;
}

/* 屏幕内容 */
.screen-content {
  width: 100%; height: 100%;
  display: flex; align-items: center; justify-content: center;
}
.screen-gif {
  width: 100%; height: 100%;
  object-fit: cover;
  display: block;
  pointer-events: none;
  -webkit-user-drag: none;
  user-drag: none;
}
.screen-emoji {
  font-size: 48px;
  animation: breatheSoft 2.5s ease-in-out infinite;
}

/* 离线黑屏 */
.screen-off-content {
  width: 100%; height: 100%;
  display: flex; align-items: center; justify-content: center;
  background: #000;
}
.screen-off-text {
  font-size: 10px; font-weight: 700;
  color: rgba(255,255,255,0.08);
  letter-spacing: 2px;
}

/* 屏幕反光 */
.screen-glare {
  position: absolute;
  top: 0; left: 0; right: 0; bottom: 0;
  background: linear-gradient(135deg, rgba(255,255,255,0.06) 0%, transparent 40%);
  pointer-events: none;
  border-radius: 10px;
}

/* 底部呼吸灯 */
.device-led {
  position: absolute;
  bottom: 5px; left: 50%;
  transform: translateX(-50%);
  width: 6px; height: 6px;
  border-radius: 50%;
  background: var(--text-dim);
  opacity: 0.3;
}
.device-led.on {
  background: var(--mint-bright);
  opacity: 1;
  box-shadow: 0 0 6px var(--mint-glow);
  animation: ledBreathe 2s ease-in-out infinite;
}
@keyframes ledBreathe {
  0%, 100% { opacity: 1; box-shadow: 0 0 6px rgba(16,185,129,0.4); }
  50% { opacity: 0.5; box-shadow: 0 0 3px rgba(16,185,129,0.2); }
}

/* ===== 设备名称 ===== */
.float-name {
  display: block;
  text-align: center;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-sub);
  max-width: 160px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  margin-top: 8px;
  transition: color 0.3s var(--ease);
  user-select: none;
  -webkit-user-select: none;
}
.float-name.active { color: var(--mint-deep); }

/* ===== 屏幕悬停操作浮层 ===== */
.screen-overlay {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  display: flex;
  gap: 8px;
  z-index: 10;
}
.overlay-btn {
  border: none;
  background: rgba(255,255,255,0.92);
  color: var(--text-sub);
  padding: 8px 20px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  border-radius: 10px;
  backdrop-filter: blur(8px);
  box-shadow: 0 2px 12px rgba(0,0,0,0.25);
  transition: all 0.2s var(--ease);
}
.overlay-btn:hover {
  background: var(--mint-bright);
  color: #fff;
  transform: translateY(-2px);
  box-shadow: 0 4px 16px rgba(16,185,129,0.4);
}
.overlay-btn.danger:hover {
  background: var(--danger);
  color: #fff;
  box-shadow: 0 4px 16px rgba(239,68,68,0.4);
}

/* 过渡动画 */
.overlay-fade-enter-active, .overlay-fade-leave-active {
  transition: opacity 0.2s var(--ease), transform 0.2s var(--ease);
}
.overlay-fade-enter-from, .overlay-fade-leave-to {
  opacity: 0;
  transform: translate(-50%, -50%) scale(0.85);
}

/* ===== 解绑弹窗 ===== */
.modal-mask {
  position: fixed; inset: 0;
  background: rgba(0,0,0,0.4);
  backdrop-filter: blur(4px);
  display: flex; align-items: center; justify-content: center;
  z-index: 1000;
}
.modal-card {
  width: 380px; max-width: 90vw;
  background: #fff; border-radius: var(--radius-lg);
  box-shadow: 0 12px 40px rgba(0,0,0,0.2);
  overflow: hidden;
  animation: modalPop 0.3s var(--ease);
}
@keyframes modalPop {
  from { opacity: 0; transform: scale(0.92) translateY(8px); }
  to { opacity: 1; transform: scale(1) translateY(0); }
}
.modal-head {
  display: flex; align-items: center; justify-content: space-between;
  padding: 18px 20px 12px; border-bottom: 1px solid var(--border);
}
.danger-head { border-bottom-color: rgba(239,68,68,0.15); }
.modal-title { font-size: 15px; font-weight: 600; color: var(--danger); }
.modal-close {
  background: none; border: none; font-size: 22px;
  color: var(--text-dim); cursor: pointer; line-height: 1; transition: color 0.2s;
}
.modal-close:hover { color: var(--danger); }
.modal-body { padding: 24px 20px 20px; text-align: center; }
.warn-icon {
  width: 48px; height: 48px; margin: 0 auto 16px;
  border-radius: 50%;
  background: var(--danger-soft, #fef2f2);
  color: var(--danger); font-size: 28px; font-weight: 700; line-height: 48px;
  border: 2px solid var(--danger);
  animation: warnPulse 1.5s ease-in-out infinite;
}
@keyframes warnPulse {
  0%, 100% { box-shadow: 0 0 0 0 rgba(239,68,68,0); }
  50% { box-shadow: 0 0 0 8px rgba(239,68,68,0.1); }
}
.warn-text { font-size: 14px; color: var(--text-main); line-height: 1.6; }
.warn-device { margin-top: 10px; font-size: 16px; font-weight: 700; color: var(--danger); }
.warn-sub { margin-top: 8px; font-size: 12px; color: var(--text-sub); }
.warn-final { color: var(--danger); font-weight: 600; }
.modal-foot { display: flex; justify-content: center; gap: 10px; padding: 0 20px 20px; }
.btn-sm {
  padding: 8px 20px; border-radius: var(--radius-sm);
  border: 1px solid var(--border); background: #fff;
  font-size: 13px; font-weight: 500; cursor: pointer;
  transition: all 0.2s var(--ease);
}
.btn-sm:hover { border-color: var(--mint-border); background: var(--mint-softer); }
.btn-sm:disabled { opacity: 0.4; cursor: not-allowed; }
.btn-danger { background: var(--danger); color: #fff; border-color: var(--danger); }
.btn-danger:hover { background: #dc2626; border-color: #dc2626; }

.modal-fade-enter-active, .modal-fade-leave-active { transition: opacity 0.25s var(--ease); }
.modal-fade-enter-from, .modal-fade-leave-to { opacity: 0; }
.modal-fade-enter-active .modal-card,
.modal-fade-leave-active .modal-card { transition: transform 0.25s var(--ease); }
.modal-fade-enter-from .modal-card,
.modal-fade-leave-to .modal-card { transform: scale(0.92) translateY(8px); }

.empty { display: flex; flex-direction: column; align-items: center; gap: 8px; padding: 70px 20px; color: var(--text-sub); }
.empty-sub { font-size: 12px; color: var(--text-dim); }

.devices-header {
  display: flex; align-items: center; justify-content: space-between;
  gap: 16px; padding: 20px 24px; margin-bottom: 16px;
}
.devices-header-info { min-width: 0; }
.devices-title { font-size: 18px; font-weight: 700; letter-spacing: -0.3px; }
.devices-sub { margin-top: 4px; font-size: 12px; color: var(--text-sub); }
.bind-device-btn {
  display: inline-flex; align-items: center; gap: 6px;
  flex-shrink: 0;
}
.bind-plus { font-size: 16px; font-weight: 700; line-height: 1; }
.bind-tip { font-size: 13px; color: var(--text-sub); margin-bottom: 12px; text-align: left; }
.bind-input { margin-bottom: 10px; }

.empty-icon { font-size: 52px; line-height: 1; margin-bottom: 8px; filter: drop-shadow(0 6px 16px rgba(16,185,129,.18)); }
.empty-title { font-size: 16px; font-weight: 700; color: var(--text-main); }
.empty-bind-btn { margin-top: 8px; }

/* ===== 响应式 ===== */
@media (max-width: 600px) {
  .device-sticker { width: 155px; }
  .sticker-board { padding: 12px; }
}
</style>
