<template>
  <div class="emotion-view">
    <!-- 顶部渐变栏 + 首字母水印 -->
    <div class="hero-bar glass">
      <span class="watermark">E</span>
      <div class="hero-text">
        <h2 class="hero-title">表情<span class="text-mint">中心</span></h2>
        <p class="hero-sub">发送情绪 · 管理表情包 · 实时预览</p>
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
        <div class="empty-orb"><svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M8 14s1.5 2 4 2 4-2 4-2"/><line x1="9" y1="9" x2="9.01" y2="9"/><line x1="15" y1="9" x2="15.01" y2="9"/></svg></div>
        <p class="empty-title">未选择设备</p>
        <p class="empty-sub">请在上方选择一台设备</p>
      </div>
    </div>

    <template v-else>
      <!-- GIF 管理区 -->
      <div class="section-card glass card-in">
        <div class="section-head">
          <div class="section-title-wrap">
            <span class="section-ico"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="2" width="20" height="20" rx="2.18"/><line x1="7" y1="2" x2="7" y2="22"/><line x1="17" y1="2" x2="17" y2="22"/><line x1="2" y1="12" x2="22" y2="12"/><line x1="2" y1="7" x2="7" y2="7"/><line x1="2" y1="17" x2="7" y2="17"/><line x1="17" y1="17" x2="22" y2="17"/><line x1="17" y1="7" x2="22" y2="7"/></svg></span>
            <span class="section-title">{{ gifSectionTitle }}</span>
          </div>
          <div class="gif-head-actions">
            <span class="section-hint">点击图片替换对应情绪的 GIF</span>
            <button class="btn-sm btn-mint" @click="openMaker"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-2px"><path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/></svg> GIF 制作器</button>
          </div>
        </div>
        <div class="upload-area">
          <div class="gif-list">
            <div v-for="s in gifSlots" :key="s.file" class="gif-item uploadable"
              @click="triggerUpload(s)">
              <img v-if="getGifUrl(s.file)" :src="getGifUrl(s.file)" :alt="s.name" class="gif-thumb" loading="lazy" />
              <div v-else class="gif-placeholder">+</div>
              <span class="gif-name">{{ s.name }}</span>
              <span v-if="uploadingSlot === s.file" class="gif-uploading">上传中...</span>
            </div>
          </div>
          <input ref="fileInput" type="file" accept=".gif" hidden @change="onFileChange" />
        </div>
      </div>

      <!-- 表情包管理区 -->
      <div class="section-card glass card-in" style="animation-delay:.06s">
        <div class="section-head">
          <div class="section-title-wrap">
            <span class="section-ico"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg></span>
            <span class="section-title">表情包</span>
          </div>
          <div class="pack-actions">
            <button class="btn-sm btn-mint" @click="openCreateDialog" :disabled="packCreating">{{ packCreating ? '创建中' : '创建' }}</button>
            <button class="btn-sm btn-ghost" @click="loadPacks">刷新</button>
          </div>
        </div>

        <!-- 表情包列表 -->
        <div v-if="packLoading" class="pack-loading">加载中...</div>
        <div v-else-if="!packs.length" class="pack-empty">暂无表情包</div>
        <div v-else class="pack-list">
          <div v-for="p in packs" :key="p.name"
            class="pack-item" :class="{ active: p.name === selectedPackName }">
            <div class="pack-info" @click="selectPack(p)">
              <span class="pack-name">{{ p.display_name || p.name }}</span>
              <span class="pack-count" v-if="p.emo_count !== undefined">{{ p.emo_count }} 个表情</span>
              <span v-if="p.name === activePack" class="pack-badge">当前使用</span>
            </div>
            <div class="pack-ops">
              <button v-if="p.name !== activePack" class="btn-sm btn-mint" @click="activatePack(p.name)"
                :disabled="!online">启用</button>
              <button v-if="p.name !== 'default'" class="btn-sm btn-danger" @click="removePack(p.name)">删除</button>
            </div>
          </div>
        </div>
      </div>

      <!-- 情绪发送区 -->
      <div class="section-card glass card-in" style="animation-delay:.12s">
        <div class="section-head">
          <div class="section-title-wrap">
            <span class="section-ico"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg></span>
            <span class="section-title">发送情绪</span>
          </div>
          <span class="section-hint">点击后设备屏幕立即切换表情</span>
        </div>
        <div class="emo-grid">
          <button v-for="e in emotions" :key="e.name"
            class="emo-tile" :class="{ active: lastSent === e.name }"
            :disabled="!online"
            @click="sendEmotion(e.name)">
            <span class="emo-name">{{ e.name }}</span>
          </button>
        </div>
      </div>
    </template>

    <!-- 创建表情包弹窗 -->
    <transition name="modal-fade">
      <div v-if="dialogVisible" class="modal-mask" @click.self="closeDialog">
        <div class="modal-card">
          <div class="modal-head">
            <span class="modal-title">创建表情包</span>
            <button class="modal-close" @click="closeDialog">×</button>
          </div>
          <div class="modal-body">
            <input ref="dialogInput" v-model="newPackName" class="modal-input"
              placeholder="输入表情包名称" @keyup.enter="confirmCreate" />
          </div>
          <div class="modal-foot">
            <button class="btn-sm btn-ghost" @click="closeDialog">取消</button>
            <button class="btn-sm btn-mint" @click="confirmCreate" :disabled="packCreating">
              {{ packCreating ? '创建中' : '确认创建' }}
            </button>
          </div>
        </div>
      </div>
    </transition>

    <!-- GIF 制作器弹窗 -->
    <GifMakerModal
      :visible="makerVisible"
      :pack-name="selectedPackName"
      :gif-slots="gifSlots"
      @close="makerVisible = false"
      @toast="(m) => emit('toast', m)"
      @saved="loadPackEmos"
    />
  </div>
</template>

<script setup>
import { ref, computed, watch, nextTick } from 'vue'
import { api } from '../api'
import GifMakerModal from '../components/GifMakerModal.vue'

const props = defineProps({
  currentDevice: Object,
  devices: Array,
})
const emit = defineEmits(['toast', 'select-device'])

const online = computed(() => !!props.currentDevice?.online)
const deviceId = computed(() =>
  props.currentDevice?.mac || props.currentDevice?.device_id || props.currentDevice?.id || props.currentDevice?.device_key || ''
)

// GIF 管理区标题：查看设备激活包时显示"当前设备表情"，手动切换其他包时显示包名
const gifSectionTitle = computed(() =>
  selectedPackName.value === activePack.value
    ? '当前设备表情 · GIF 管理'
    : `${selectedPackName.value} · GIF 管理`
)

// 标准表情列表（与设备端 s_emotions[] 对齐）
const emotions = [
  { name: '快乐' }, { name: '伤心' }, { name: '愤怒' },
  { name: '意外' }, { name: '否定' }, { name: '无情绪' },
  { name: '聆听中' }, { name: '说话中' }, { name: '休息中' },
  { name: '唱歌中' }, { name: '联网中' }, { name: '发生错误' },
]

// 标准 GIF 槽位（与 gif_downloader g_gif_files 对齐）
const gifSlots = [
  { name: '联网中', file: 'wifi' },
  { name: '请配网', file: 'wx_qrcode' },
  { name: '发生错误', file: 'error' },
  { name: '聆听中', file: 'listen' },
  { name: '说话中', file: 'tts_ing' },
  { name: '休息中', file: 'sleep' },
  { name: '唱歌中', file: 'music' },
  { name: '无情绪', file: 'tts_ing' },
  { name: '快乐', file: 'happy' },
  { name: '伤心', file: 'sad' },
  { name: '愤怒', file: 'angry' },
  { name: '意外', file: 'accident' },
  { name: '否定', file: 'no' },
]

const lastSent = ref('')
const packs = ref([])
const activePack = ref('')
const packLoading = ref(false)
const selectedPackName = ref('default')
const packEmos = ref([])
const newPackName = ref('')
const packCreating = ref(false)
const dialogVisible = ref(false)
const dialogInput = ref(null)
const fileInput = ref(null)
const pendingSlot = ref(null)
const uploadingSlot = ref('')
const makerVisible = ref(false)
const packEmosVersion = ref(0)

function openMaker() {
  makerVisible.value = true
}

function isCurrent(d) {
  const did = d.device_id || d.id || d.mac || ''
  return did === (props.currentDevice?.device_id || props.currentDevice?.id || props.currentDevice?.mac || '')
}

// 查找某个槽位是否已有 GIF（URL 带版本号，避免浏览器缓存旧图）
function getGifUrl(file) {
  const g = packEmos.value.find(e => e.name === file || e.filename === file + '.gif')
  return g ? `${g.url}?v=${packEmosVersion.value}` : null
}

// 点击 GIF 卡片触发文件选择
function triggerUpload(slot) {
  if (uploadingSlot.value) return
  pendingSlot.value = slot
  fileInput.value?.click()
}

// 文件选择后自动上传
async function onFileChange(e) {
  const file = e.target.files?.[0]
  if (!file || !pendingSlot.value || !selectedPackName.value) {
    e.target.value = ''
    return
  }
  const slot = pendingSlot.value
  uploadingSlot.value = slot.file
  const res = await api.uploadEmo(selectedPackName.value, file, slot.file + '.gif', 0)
  uploadingSlot.value = ''
  pendingSlot.value = null
  e.target.value = ''
  if (res?.code === 0) {
    emit('toast', `${slot.name} 上传成功`)
    loadPackEmos()
  } else {
    emit('toast', res?.message || '上传失败')
  }
}

// 发送情绪
async function sendEmotion(name) {
  if (!deviceId.value) return
  const res = await api.sendEmotion(deviceId.value, name).catch(() => null)
  if (res?.data?.code === 0) {
    lastSent.value = name
    emit('toast', `已发送: ${name}`)
  } else {
    emit('toast', res?.data?.message || '发送失败')
  }
}

// 加载表情包列表 + 当前激活包
async function loadPacks() {
  packLoading.value = true
  const [packsRes, activeRes] = await Promise.all([
    api.emoPacks().catch(() => null),
    deviceId.value ? api.getActiveEmoPack(deviceId.value).catch(() => null) : Promise.resolve(null),
  ])
  if (packsRes?.data?.code === 0) {
    packs.value = packsRes.data.data || []
  }
  if (activeRes?.data?.code === 0) {
    activePack.value = activeRes.data.data?.active_pack || 'default'
  }
  packLoading.value = false
}

// 打开创建弹窗
function openCreateDialog() {
  newPackName.value = ''
  dialogVisible.value = true
  nextTick(() => {
    dialogInput.value?.focus()
  })
}

// 关闭弹窗
function closeDialog() {
  dialogVisible.value = false
}

// 确认创建
async function confirmCreate() {
  const name = newPackName.value.trim()
  if (!name || packCreating.value) return
  packCreating.value = true
  const res = await api.createEmoPack(name).catch(() => null)
  packCreating.value = false
  if (res?.data?.code === 0) {
    emit('toast', '创建成功')
    closeDialog()
    loadPacks()
  } else {
    emit('toast', res?.data?.message || '创建失败')
  }
}

// 删除表情包
async function removePack(name) {
  const res = await api.deleteEmoPack(name).catch(() => null)
  if (res?.data?.code === 0) {
    emit('toast', '已删除')
    if (selectedPackName.value === name) {
      selectedPackName.value = 'default'
      loadPackEmos()
    }
    loadPacks()
  } else {
    emit('toast', res?.data?.message || '删除失败')
  }
}

// 激活表情包（通知设备 refresh_emo）
async function activatePack(name) {
  if (!deviceId.value) return
  const res = await api.setActiveEmoPack(deviceId.value, name).catch(() => null)
  if (res?.data?.code === 0) {
    activePack.value = name
    emit('toast', `已切换到 ${name}，设备正在刷新...`)
  } else {
    emit('toast', res?.data?.message || '切换失败')
  }
}

// 加载当前选中表情包的 GIF 列表
async function loadPackEmos() {
  packEmos.value = []
  if (!selectedPackName.value) return
  const res = await api.emoPackDetail(selectedPackName.value).catch(() => null)
  if (res?.data?.code === 0) {
    packEmos.value = res.data.data || []
    packEmosVersion.value++
  }
}

// 选中表情包：切换并加载 GIF
function selectPack(p) {
  selectedPackName.value = p.name
  loadPackEmos()
}

// 切换设备时重新加载，GIF 管理区默认跟随设备当前激活的表情包
watch(() => props.currentDevice, async (d) => {
  lastSent.value = ''
  selectedPackName.value = 'default'
  if (d) {
    await loadPacks()
    selectedPackName.value = activePack.value
    loadPackEmos()
  }
}, { immediate: true })
</script>

<style scoped>
.emotion-view { padding: 28px 0 56px; }

.glass {
  background: var(--grad-card);
  backdrop-filter: var(--glass-blur);
  -webkit-backdrop-filter: var(--glass-blur);
  border: 1px solid var(--glass-border);
  box-shadow: var(--shadow), var(--glass-hi);
  border-radius: var(--radius-lg);
}

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
  display: flex; gap: 10px;
  margin-bottom: 20px;
  overflow-x: auto; padding-bottom: 4px;
}
.device-chip {
  display: flex; align-items: center; gap: 8px;
  flex-shrink: 0; padding: 9px 18px;
  border-radius: 999px;
  border: 1px solid var(--glass-border);
  background: var(--glass-bg-strong);
  backdrop-filter: var(--glass-blur-sm);
  -webkit-backdrop-filter: var(--glass-blur-sm);
  box-shadow: var(--shadow-xs), var(--glass-hi);
  cursor: pointer;
  transition: all 0.25s var(--ease);
}
.device-chip:hover { border-color: var(--mint-border); background: var(--mint-softer); transform: translateY(-1px); }
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
.empty-title { font-size: 16px; font-weight: 700; color: var(--text-sub); }
.empty-sub { margin-top: 6px; font-size: 13px; color: var(--text-dim); }

/* ===== 区块卡片 ===== */
.section-card {
  padding: 24px 26px;
  margin-bottom: 18px;
}
.section-head {
  display: flex; align-items: center; justify-content: space-between;
  margin-bottom: 18px; flex-wrap: wrap; gap: 10px;
}
.section-title-wrap { display: flex; align-items: center; gap: 10px; }
.section-ico {
  width: 34px; height: 34px; border-radius: 10px;
  display: flex; align-items: center; justify-content: center;
  font-size: 16px;
  background: var(--mint-soft);
  border: 1px solid var(--mint-border);
}
.section-title { font-size: 15px; font-weight: 700; }
.section-hint { font-size: 12px; color: var(--text-dim); }

/* GIF 管理区头操作 */
.gif-head-actions { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }

/* ===== 情绪表情网格 ===== */
.emo-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(96px, 1fr));
  gap: 12px;
}
.emo-tile {
  display: flex; align-items: center; justify-content: center;
  padding: 18px 8px;
  border: 1px solid var(--glass-border);
  background: var(--glass-bg-strong);
  backdrop-filter: var(--glass-blur-sm);
  -webkit-backdrop-filter: var(--glass-blur-sm);
  border-radius: var(--radius-md);
  cursor: pointer;
  box-shadow: var(--shadow-xs), var(--glass-hi);
  transition: all 0.25s var(--ease);
}
.emo-tile:hover:not(:disabled) {
  border-color: var(--mint-border);
  background: var(--mint-softer);
  transform: translateY(-3px);
  box-shadow: 0 8px 20px rgba(16,185,129,0.14);
}
.emo-tile:active:not(:disabled) { transform: translateY(0); }
.emo-tile:disabled { opacity: 0.35; cursor: not-allowed; }
.emo-tile.active {
  background: var(--mint-soft);
  border-color: var(--mint);
  animation: emoBreath 2s ease-in-out infinite;
}
@keyframes emoBreath {
  0%, 100% { box-shadow: 0 0 0 0 rgba(16,185,129,0); }
  50% { box-shadow: 0 0 0 4px rgba(16,185,129,0.16); }
}
.emo-name { font-size: 14px; font-weight: 600; color: var(--text-main); }

/* ===== 表情包列表 ===== */
.pack-actions { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }

.btn-sm {
  padding: 6px 14px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--glass-border);
  background: var(--glass-bg-strong);
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s var(--ease);
}
.btn-sm:hover { border-color: var(--mint-border); background: var(--mint-softer); }
.btn-sm:disabled { opacity: 0.4; cursor: not-allowed; }
.btn-mint { background: var(--grad-mint); color: #fff; border: none; box-shadow: var(--shadow-mint); }
.btn-mint:hover { filter: brightness(1.08); transform: translateY(-1px); }
.btn-ghost { background: rgba(255,255,255,0.6); color: var(--text-sub); }
.btn-danger { color: var(--danger); border-color: var(--danger-soft); }
.btn-danger:hover { background: var(--danger-soft); }

.pack-loading, .pack-empty { padding: 24px; text-align: center; color: var(--text-dim); font-size: 13px; }

.pack-list { display: flex; flex-direction: column; gap: 10px; }
.pack-item {
  display: flex; align-items: center; justify-content: space-between;
  padding: 14px 18px;
  border: 1px solid var(--glass-border);
  border-radius: var(--radius-md);
  background: var(--glass-bg-soft);
  box-shadow: var(--glass-hi);
  transition: all 0.25s var(--ease);
}
.pack-item:hover { border-color: var(--mint-border); background: var(--mint-softer); }
.pack-item.active {
  background: var(--mint-soft);
  border-color: var(--mint);
}
.pack-info { display: flex; align-items: center; gap: 10px; cursor: pointer; flex: 1; }
.pack-name { font-size: 13px; font-weight: 600; }
.pack-count { font-size: 11px; color: var(--text-dim); }
.pack-badge {
  font-size: 10px; padding: 2px 8px;
  border-radius: 999px;
  background: var(--grad-mint); color: #fff;
  box-shadow: 0 3px 8px rgba(16,185,129,0.25);
}
.pack-ops { display: flex; gap: 6px; }

/* ===== GIF 上传区 ===== */
.upload-area { margin-top: 8px; }
.gif-list {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(84px, 1fr));
  gap: 12px;
  margin-bottom: 16px;
}
.gif-item {
  display: flex; flex-direction: column; align-items: center; gap: 6px;
  padding: 10px 8px;
  border: 1px solid var(--glass-border);
  border-radius: var(--radius-md);
  background: var(--glass-bg-soft);
  box-shadow: var(--glass-hi);
  transition: all 0.25s var(--ease);
}
.gif-item.uploadable {
  cursor: pointer;
  position: relative;
}
.gif-item.uploadable:hover {
  border-color: var(--mint);
  background: var(--mint-softer);
  transform: translateY(-2px);
  box-shadow: 0 8px 18px rgba(16,185,129,0.14);
}
.gif-thumb { width: 64px; height: 64px; object-fit: contain; border-radius: 6px; }
.gif-placeholder {
  width: 64px; height: 64px;
  display: flex; align-items: center; justify-content: center;
  font-size: 28px; color: var(--text-dim);
  border: 2px dashed var(--glass-border);
  border-radius: 6px;
  background: rgba(255,255,255,0.4);
}
.gif-item.uploadable:hover .gif-placeholder { border-color: var(--mint); color: var(--mint); }
.gif-name { font-size: 10px; color: var(--text-dim); text-align: center; word-break: break-all; }
.gif-uploading {
  position: absolute; inset: 0;
  background: rgba(255,255,255,0.85);
  display: flex; align-items: center; justify-content: center;
  font-size: 11px; color: var(--mint-deep); font-weight: 600;
  border-radius: var(--radius-md);
}

/* ===== 创建表情包弹窗 ===== */
.modal-mask {
  position: fixed; inset: 0;
  background: rgba(15, 23, 42, 0.4);
  backdrop-filter: blur(10px);
  -webkit-backdrop-filter: blur(10px);
  display: flex; align-items: center; justify-content: center;
  z-index: 1000;
}
.modal-card {
  width: 380px; max-width: 90vw;
  background: var(--grad-panel);
  backdrop-filter: var(--glass-blur);
  -webkit-backdrop-filter: var(--glass-blur);
  border: 1px solid var(--glass-border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-hover), var(--glass-hi);
  overflow: hidden;
  animation: modalPop 0.3s var(--ease);
}
@keyframes modalPop {
  from { opacity: 0; transform: scale(0.92) translateY(8px); }
  to { opacity: 1; transform: scale(1) translateY(0); }
}
.modal-head {
  display: flex; align-items: center; justify-content: space-between;
  padding: 18px 20px 12px;
  border-bottom: 1px solid var(--glass-border-soft);
}
.modal-title { font-size: 15px; font-weight: 700; }
.modal-close {
  background: none; border: none; font-size: 22px;
  color: var(--text-dim); cursor: pointer; line-height: 1;
  transition: color 0.2s;
}
.modal-close:hover { color: var(--danger); }
.modal-body { padding: 20px; }
.modal-input {
  width: 100%;
  padding: 10px 14px;
  border: 1px solid var(--glass-border);
  border-radius: var(--radius-sm);
  font-size: 14px;
  background: rgba(255, 255, 255, 0.6);
  outline: none;
  transition: border-color 0.2s;
  box-sizing: border-box;
}
.modal-input:focus { border-color: var(--mint); box-shadow: 0 0 0 3px var(--mint-soft); }
.modal-foot {
  display: flex; justify-content: flex-end; gap: 8px;
  padding: 0 20px 18px;
}

/* 弹窗过渡动画 */
.modal-fade-enter-active, .modal-fade-leave-active { transition: opacity 0.25s var(--ease); }
.modal-fade-enter-from, .modal-fade-leave-to { opacity: 0; }
.modal-fade-enter-active .modal-card, .modal-fade-leave-active .modal-card { transition: transform 0.25s var(--ease); }
.modal-fade-enter-from .modal-card, .modal-fade-leave-to .modal-card { transform: scale(0.92) translateY(8px); }

/* ===== 响应式 ===== */
@media (max-width: 600px) {
  .emo-grid { grid-template-columns: repeat(auto-fill, minmax(76px, 1fr)); }
  .pack-actions { width: 100%; }
  .hero-badge { top: 18px; right: 18px; }
}
</style>