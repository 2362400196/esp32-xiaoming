<template>
  <transition name="modal-fade">
    <div v-if="visible" class="maker-mask" @click.self="close">
      <div class="maker-panel glass">
        <div class="maker-head">
          <div class="maker-title-wrap">
            <span class="section-ico">🛠️</span>
            <span class="maker-title">GIF 制作器</span>
            <span class="maker-sub" v-if="packName">保存至表情包：{{ packName }}</span>
          </div>
          <button class="modal-close" @click="close">×</button>
        </div>

        <div class="maker-body">
          <!-- 1 · 素材上传 -->
          <div class="maker-block">
            <div class="maker-block-head">
              <span class="block-title">1 · 添加素材</span>
              <label class="btn-sm btn-mint upload-btn">
                上传 GIF / 图片
                <input ref="fileInput" type="file" accept=".gif,.png,.jpg,.jpeg,.webp" multiple hidden @change="onFilesChange" />
              </label>
            </div>
            <div class="src-list" v-if="sources.length">
              <div v-for="s in sources" :key="s.id" class="src-chip" :class="{ invalid: !s.valid }">
                <span class="src-name" :title="s.name">{{ s.name }}</span>
                <span class="src-meta" v-if="s.valid">{{ s.w }}×{{ s.h }} · {{ s.frames.length }} 帧</span>
                <span class="src-meta" v-else>无法解析</span>
                <button class="src-del" @click="removeSource(s.id)">×</button>
              </div>
            </div>
            <p v-else class="block-hint">
              支持 GIF 动图与 PNG / JPG / WebP 图片，可多选；多素材自动合并为一组帧，可自由删改排序。
            </p>
          </div>

          <!-- 2 · 帧编辑 -->
          <div class="maker-block" v-if="frames.length">
            <div class="maker-block-head">
              <span class="block-title">2 · 帧编辑（{{ frames.length }} 帧）</span>
              <div class="frame-ops">
                <input class="frame-max" type="number" min="1" :max="200" v-model.number="maxFrames" title="抽帧目标帧数" />
                <button class="btn-sm btn-ghost" @click="autoExtract" :disabled="frames.length <= 1">自动抽帧</button>
                <button class="btn-sm btn-ghost" @click="clearFrames">清空</button>
              </div>
            </div>
            <div class="frame-list">
              <div v-for="(f, idx) in frames" :key="f.key" class="frame-cell">
                <img :src="f.thumb" class="frame-thumb" :alt="`帧 ${idx + 1}`" />
                <span class="frame-idx">{{ idx + 1 }}</span>
                <div class="frame-actions">
                  <button :disabled="idx === 0" @click="moveFrame(f.key, -1)" title="上移">↑</button>
                  <button :disabled="idx === frames.length - 1" @click="moveFrame(f.key, 1)" title="下移">↓</button>
                  <button class="del" @click="removeFrame(f.key)" title="删除">×</button>
                </div>
              </div>
            </div>
          </div>

          <!-- 3 · 参数 -->
          <div class="maker-block">
            <div class="maker-block-head">
              <span class="block-title">3 · 参数</span>
              <span class="block-hint-inline">目标即设备可接受的方形 GIF（≤10MB）</span>
            </div>
            <div class="param-grid">
              <label class="param-item">
                <span>目标尺寸</span>
                <select v-model="targetSize">
                  <option :value="160">160×160（设备推荐）</option>
                  <option :value="180">180×180</option>
                  <option :value="240">240×240</option>
                  <option :value="120">120×120</option>
                  <option :value="0">保持原尺寸</option>
                </select>
              </label>
              <label class="param-item">
                <span>帧延迟</span>
                <select v-model="delayMode">
                  <option value="">保持各帧原延迟</option>
                  <option value="set">统一延迟</option>
                </select>
                <template v-if="delayMode === 'set'">
                  <input class="param-input" type="number" min="10" max="10000" step="10" v-model.number="delay" />
                  <span class="param-unit">ms</span>
                </template>
              </label>
              <label class="param-item">
                <span>适配方式</span>
                <select v-model="fitMode">
                  <option value="crop">居中裁剪为正方形</option>
                  <option value="fit">等比缩放（不裁剪）</option>
                </select>
              </label>
              <label class="param-item">
                <span>循环次数</span>
                <select v-model="loop">
                  <option :value="0">无限循环</option>
                  <option :value="1">1 次</option>
                  <option :value="2">2 次</option>
                </select>
              </label>
            </div>
          </div>

          <!-- 4 · 预览 -->
          <div class="maker-block" v-if="previewUrl">
            <div class="maker-block-head">
              <span class="block-title">4 · 预览</span>
              <span class="block-hint-inline">{{ previewInfo.frames }} 帧 · {{ previewInfo.bytesText }}</span>
            </div>
            <div class="preview-wrap">
              <img :src="previewUrl" class="preview-img" alt="GIF 预览" />
            </div>
          </div>
        </div>

        <div class="maker-foot">
          <div class="save-slot">
            <span class="save-label">保存到槽位：</span>
            <select v-model="saveSlot" class="slot-select">
              <option value="">仅生成（不保存）</option>
              <option v-for="s in gifSlots" :key="s.file" :value="s.file">{{ s.name }}（{{ s.file }}.gif）</option>
            </select>
          </div>
          <div class="foot-btns">
            <button class="btn-sm btn-ghost" @click="close">关闭</button>
            <button class="btn-sm btn-mint" @click="generate" :disabled="generating || !frames.length">
              {{ generating ? '生成中...' : (previewUrl ? '重新生成' : '生成 GIF') }}
            </button>
            <button class="btn-sm btn-mint" @click="saveToPack" :disabled="saving || !previewBlob || !saveSlot">
              {{ saving ? '保存中...' : '保存到表情包' }}
            </button>
          </div>
        </div>
      </div>
    </div>
  </transition>
</template>

<script setup>
import { ref, watch } from 'vue'
import { api } from '../api'

const props = defineProps({
  visible: Boolean,
  packName: { type: String, default: 'default' },
  gifSlots: { type: Array, default: () => [] },
})
const emit = defineEmits(['close', 'toast', 'saved'])

const fileInput = ref(null)
const files = ref([])
const sources = ref([])
const frames = ref([])
const maxFrames = ref(30)
const targetSize = ref(160)
const delayMode = ref('')
const delay = ref(100)
const fitMode = ref('crop')
const loop = ref(0)
const saveSlot = ref('')
const generating = ref(false)
const saving = ref(false)
const previewBlob = ref(null)
const previewUrl = ref('')
const previewInfo = ref({ frames: 0, bytesText: '' })

watch(() => props.visible, (v) => {
  if (v) reset()
})

function close() {
  emit('close')
}

function reset() {
  files.value = []
  sources.value = []
  frames.value = []
  saveSlot.value = ''
  generating.value = false
  saving.value = false
  previewBlob.value = null
  if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
  previewUrl.value = ''
  previewInfo.value = { frames: 0, bytesText: '' }
}

// ── 素材上传与解析 ──
async function onFilesChange(e) {
  const picked = Array.from(e.target.files || [])
  e.target.value = ''
  if (!picked.length) return
  const allowed = /\.(gif|png|jpe?g|webp)$/i
  const ok = picked.filter(f => allowed.test(f.name))
  if (ok.length !== picked.length) emit('toast', '已忽略不支持的文件类型（仅 GIF/PNG/JPG/WebP）')
  if (!ok.length) return

  const merged = [...files.value, ...ok]
  const res = await api.emoMakerSources(merged).catch(() => null)
  if (res?.data?.code !== 0) {
    emit('toast', res?.data?.message || '素材解析失败')
    return
  }
  const oldCount = files.value.length
  files.value = merged
  sources.value = res.data.data.sources || []
  // 保留已有帧池，仅追加新增素材的帧
  const newFrames = []
  for (const s of sources.value) {
    if (!s.valid || s.id < oldCount) continue
    for (const fr of s.frames) {
      newFrames.push({ key: `${s.id}-${fr.i}`, src: s.id, frame: fr.i, d: fr.d, thumb: fr.thumb })
    }
  }
  frames.value = [...frames.value, ...newFrames]
}

function rebuildFrames() {
  const list = []
  for (const s of sources.value) {
    if (!s.valid) continue
    for (const fr of s.frames) {
      list.push({ key: `${s.id}-${fr.i}`, src: s.id, frame: fr.i, d: fr.d, thumb: fr.thumb })
    }
  }
  frames.value = list
}

function removeSource(id) {
  files.value = files.value.filter((_, i) => i !== id)
  sources.value = sources.value.filter(s => s.id !== id)
  // 删除后重排 id，使其与 files 下标保持一致
  sources.value.forEach((s, i) => { s.id = i })
  rebuildFrames()
}

// ── 帧编辑 ──
function removeFrame(key) {
  frames.value = frames.value.filter(f => f.key !== key)
}

function moveFrame(key, dir) {
  const i = frames.value.findIndex(f => f.key === key)
  const j = i + dir
  if (i < 0 || j < 0 || j >= frames.value.length) return
  const arr = frames.value.slice()
  ;[arr[i], arr[j]] = [arr[j], arr[i]]
  frames.value = arr
}

function clearFrames() {
  frames.value = []
}

function autoExtract() {
  const list = frames.value
  const n = Math.max(1, Math.min(maxFrames.value || 1, 200))
  if (list.length <= n) return
  const keep = []
  for (let i = 0; i < n; i++) {
    const idx = Math.round((i * (list.length - 1)) / (n - 1))
    keep.push(list[idx])
  }
  frames.value = keep
}

// ── 生成与保存 ──
async function generate() {
  if (!files.value.length || !frames.value.length || generating.value) return
  generating.value = true
  const order = frames.value.map(f => ({ src: f.src, frame: f.frame }))
  const params = {
    frames: order,
    size: targetSize.value,
    fit: fitMode.value,
    loop: loop.value,
  }
  if (delayMode.value === 'set') params.delay = delay.value
  const res = await api.emoMakerProcess(files.value, params).catch(() => null)
  generating.value = false
  if (!res || !res.blob) {
    emit('toast', res?.data?.message || '生成失败')
    return
  }
  if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
  previewBlob.value = res.blob
  previewUrl.value = URL.createObjectURL(res.blob)
  previewInfo.value = {
    frames: res.frames || frames.value.length,
    bytesText: `${(res.blob.size / 1024).toFixed(1)} KB`,
  }
  emit('toast', 'GIF 生成完成')
}

async function saveToPack() {
  if (!previewBlob.value || !saveSlot.value || saving.value) return
  saving.value = true
  const file = new File([previewBlob.value], `${saveSlot.value}.gif`, { type: 'image/gif' })
  const res = await api.uploadEmo(props.packName, file, `${saveSlot.value}.gif`, 0).catch(() => null)
  saving.value = false
  if (res?.code === 0) {
    emit('toast', `已保存到表情包「${props.packName}」的 ${saveSlot.value}.gif`)
    emit('saved')
    close()
  } else {
    emit('toast', res?.message || '保存失败')
  }
}
</script>

<style scoped>
.maker-mask {
  position: fixed; inset: 0;
  background: rgba(15, 23, 42, 0.45);
  backdrop-filter: blur(10px);
  -webkit-backdrop-filter: blur(10px);
  display: flex; align-items: center; justify-content: center;
  z-index: 1000;
}
.maker-panel {
  width: 760px; max-width: 94vw; max-height: 88vh;
  display: flex; flex-direction: column;
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
  from { opacity: 0; transform: scale(0.94) translateY(10px); }
  to { opacity: 1; transform: scale(1) translateY(0); }
}

.maker-head {
  display: flex; align-items: center; justify-content: space-between;
  padding: 16px 20px 12px;
  border-bottom: 1px solid var(--glass-border-soft);
}
.maker-title-wrap { display: flex; align-items: center; gap: 10px; }
.maker-title { font-size: 16px; font-weight: 800; }
.maker-sub { font-size: 12px; color: var(--text-dim); }
.modal-close {
  background: none; border: none; font-size: 22px;
  color: var(--text-dim); cursor: pointer; line-height: 1;
  transition: color 0.2s;
}
.modal-close:hover { color: var(--danger); }

.maker-body {
  padding: 16px 20px;
  overflow-y: auto;
  display: flex; flex-direction: column; gap: 14px;
}
.maker-block {
  border: 1px solid var(--glass-border);
  border-radius: var(--radius-md);
  background: var(--glass-bg-soft);
  padding: 12px 14px;
}
.maker-block-head {
  display: flex; align-items: center; justify-content: space-between;
  margin-bottom: 10px; flex-wrap: wrap; gap: 8px;
}
.block-title { font-size: 13px; font-weight: 700; }
.block-hint { font-size: 12px; color: var(--text-dim); margin: 0; }
.block-hint-inline { font-size: 12px; color: var(--text-dim); }

.btn-sm {
  padding: 6px 14px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--glass-border);
  background: var(--glass-bg-strong);
  font-size: 12px; font-weight: 600; cursor: pointer;
  transition: all 0.2s var(--ease);
}
.btn-sm:hover:not(:disabled) { border-color: var(--mint-border); background: var(--mint-softer); }
.btn-sm:disabled { opacity: 0.4; cursor: not-allowed; }
.btn-mint { background: var(--grad-mint); color: #fff; border: none; box-shadow: var(--shadow-mint); }
.btn-mint:hover:not(:disabled) { filter: brightness(1.08); transform: translateY(-1px); }
.btn-ghost { background: rgba(255,255,255,0.6); color: var(--text-sub); }
.upload-btn { cursor: pointer; }

/* 素材列表 */
.src-list { display: flex; flex-wrap: wrap; gap: 8px; }
.src-chip {
  display: inline-flex; align-items: center; gap: 8px;
  padding: 6px 10px;
  border: 1px solid var(--mint-border);
  background: var(--mint-softer);
  border-radius: 999px;
  font-size: 12px;
}
.src-chip.invalid { border-color: var(--danger-soft); background: var(--danger-soft); color: var(--danger); }
.src-name { font-weight: 600; max-width: 160px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.src-meta { color: var(--text-dim); }
.src-del {
  background: none; border: none; cursor: pointer; color: var(--text-dim);
  font-size: 14px; line-height: 1; padding: 0 2px;
}
.src-del:hover { color: var(--danger); }

/* 帧列表 */
.frame-ops { display: flex; gap: 6px; align-items: center; }
.frame-max {
  width: 70px; padding: 5px 8px;
  border: 1px solid var(--glass-border);
  border-radius: var(--radius-sm);
  font-size: 12px; background: rgba(255,255,255,0.6);
}
.frame-list {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(72px, 1fr));
  gap: 8px;
}
.frame-cell {
  position: relative;
  display: flex; flex-direction: column; align-items: center; gap: 4px;
  border: 1px solid var(--glass-border);
  border-radius: var(--radius-sm);
  background: rgba(255,255,255,0.5);
  padding: 6px 4px;
}
.frame-thumb { width: 52px; height: 52px; object-fit: contain; border-radius: 4px; }
.frame-idx {
  position: absolute; top: 2px; left: 2px;
  font-size: 9px; font-weight: 700;
  background: var(--grad-mint); color: #fff;
  border-radius: 4px; padding: 1px 4px;
}
.frame-actions { display: flex; gap: 3px; }
.frame-actions button {
  width: 20px; height: 20px; font-size: 11px; line-height: 1;
  border: 1px solid var(--glass-border);
  border-radius: 4px;
  background: var(--glass-bg-strong);
  cursor: pointer; color: var(--text-sub);
}
.frame-actions button:hover:not(:disabled) { border-color: var(--mint); color: var(--mint-deep); }
.frame-actions button:disabled { opacity: 0.3; cursor: not-allowed; }
.frame-actions button.del:hover { border-color: var(--danger); color: var(--danger); }

/* 参数 */
.param-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
  gap: 10px 12px;
}
.param-item {
  display: flex; align-items: center; gap: 6px;
  font-size: 12px; color: var(--text-sub);
  flex-wrap: wrap;
}
.param-item > span:first-child { min-width: 52px; }
.param-item select, .slot-select {
  flex: 1; min-width: 0;
  padding: 6px 8px;
  border: 1px solid var(--glass-border);
  border-radius: var(--radius-sm);
  font-size: 12px;
  background: rgba(255,255,255,0.6);
  outline: none;
}
.param-item select:focus, .slot-select:focus { border-color: var(--mint); }
.param-input {
  width: 72px; padding: 6px 8px;
  border: 1px solid var(--glass-border);
  border-radius: var(--radius-sm);
  font-size: 12px; background: rgba(255,255,255,0.6);
}
.param-unit { color: var(--text-dim); }

/* 预览 */
.preview-wrap {
  display: flex; align-items: center; justify-content: center;
  padding: 10px;
  background: repeating-conic-gradient(#f1f5f9 0% 25%, #fff 0% 50%) 0 0 / 16px 16px;
  border-radius: var(--radius-sm);
}
.preview-img {
  width: 200px; height: 200px;
  object-fit: contain;
  border-radius: 6px;
  box-shadow: var(--shadow);
}

/* 底部 */
.maker-foot {
  display: flex; align-items: center; justify-content: space-between;
  gap: 12px; flex-wrap: wrap;
  padding: 14px 20px 18px;
  border-top: 1px solid var(--glass-border-soft);
}
.save-slot { display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--text-sub); flex: 1; min-width: 200px; }
.slot-select { flex: 1; }
.foot-btns { display: flex; gap: 8px; }

.modal-fade-enter-active, .modal-fade-leave-active { transition: opacity 0.25s var(--ease); }
.modal-fade-enter-from, .modal-fade-leave-to { opacity: 0; }
.modal-fade-enter-active .maker-panel, .modal-fade-leave-active .maker-panel { transition: transform 0.25s var(--ease); }
.modal-fade-enter-from .maker-panel, .modal-fade-leave-to .maker-panel { transform: scale(0.94) translateY(10px); }

@media (max-width: 600px) {
  .maker-foot { flex-direction: column; align-items: stretch; }
  .foot-btns { justify-content: flex-end; }
  .preview-img { width: 160px; height: 160px; }
}
</style>