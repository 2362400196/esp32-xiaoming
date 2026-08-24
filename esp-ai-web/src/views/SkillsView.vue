<template>
  <div class="skills-view">
    <!-- 顶部渐变栏 + 首字母水印 -->
    <div class="hero-bar glass">
      <span class="watermark">S</span>
      <div class="hero-text">
        <h2 class="hero-title">技能<span class="text-mint">中心</span></h2>
        <p class="hero-sub">管理设备技能 · 自定义激活指令</p>
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
        <div class="empty-orb"><svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/></svg></div>
        <p class="empty-title">未选择设备</p>
        <p class="empty-sub">请在上方选择一台设备</p>
      </div>
    </div>

    <!-- 技能列表 -->
    <div v-else class="section-card glass card-in">
      <div class="section-head">
        <div class="section-title-wrap">
          <span class="section-ico"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/></svg></span>
          <span class="section-title">技能列表</span>
          <span class="section-count" v-if="skills.length">共 {{ skills.length }} 个</span>
        </div>
        <button class="btn-sm btn-mint" @click="openSkillModal(null)">+ 添加技能</button>
      </div>

      <div v-if="loading" class="list-loading">加载中...</div>
      <div v-else-if="!skills.length" class="pack-empty">
        <p class="empty-text">暂无技能</p>
        <p class="empty-sub">点击「添加技能」创建你的第一个技能</p>
      </div>
      <div v-else class="skill-list">
        <div v-for="s in skills" :key="s.id" class="skill-card" :class="{ disabled: s.disabled }">
          <div class="skill-card-top">
            <div class="skill-info">
              <span class="skill-name">{{ s.id }}</span>
              <span class="skill-desc">{{ s.description }}</span>
            </div>
            <button class="switch" :class="{ on: !s.disabled }" :disabled="!currentDevice"
              @click="toggleSkill(s)">
              <span class="switch-thumb"></span>
            </button>
          </div>
          <div class="skill-tags" v-if="(s.category && s.category.length) || (s.tags && s.tags.length)">
            <span class="skill-tag cat" v-for="c in (s.category || [])" :key="'c' + c">{{ c }}</span>
            <span class="skill-tag" v-for="t in (s.tags || [])" :key="'t' + t">{{ t }}</span>
          </div>
          <div class="skill-actions">
            <button class="btn-sm btn-ghost" @click="viewSkillDetail(s)">查看</button>
            <button class="btn-sm btn-ghost" @click="openSkillModal(s)">编辑</button>
            <button class="btn-sm btn-danger" @click="confirmDeleteSkill(s)">删除</button>
          </div>
        </div>
      </div>
    </div>

    <!-- 创建/编辑技能弹窗 -->
    <transition name="modal-fade">
      <div v-if="skillDialog" class="modal-mask" @click.self="closeSkillModal">
        <div class="modal-card skill-modal">
          <div class="modal-head">
            <span class="modal-title">{{ form.editing ? '编辑技能' : '添加技能' }}</span>
            <button class="modal-close" @click="closeSkillModal">×</button>
          </div>
          <div class="modal-body skill-body">
            <div class="form-section">
              <span class="form-label">技能名称 *</span>
              <input v-model="form.name" class="modal-input" :disabled="form.editing"
                placeholder="小写字母/数字/下划线，如 my_skill" />
              <span class="form-hint" v-if="form.editing">名称不可修改</span>
            </div>
            <div class="form-section">
              <span class="form-label">激活描述 *</span>
              <input v-model="form.description" class="modal-input"
                placeholder="描述哪些用户意图会触发此技能" />
            </div>
            <div class="form-section">
              <div class="form-label-row">
                <span class="form-label">执行指令 *</span>
                <button class="btn-sm btn-ghost" @click="openToolPicker">插入工具</button>
              </div>
              <textarea ref="instructionsRef" v-model="form.instructions" class="modal-textarea"
                placeholder="给 AI 的执行步骤..." @focus="onInstructionsFocus" @input="onInstructionsInput" @click="onInstructionsInput"></textarea>
            </div>
            <div class="form-row">
              <div class="form-section grow">
                <span class="form-label">分类（可选）</span>
                <input v-model="form.categoryStr" class="modal-input" placeholder="如：utility" />
              </div>
              <div class="form-section grow">
                <span class="form-label">标签（可选）</span>
                <input v-model="form.tagsStr" class="modal-input" placeholder="如：weather" />
              </div>
            </div>
          </div>
          <div class="modal-foot">
            <button class="btn-sm btn-ghost" @click="closeSkillModal">取消</button>
            <button class="btn-sm btn-mint" @click="submitSkill" :disabled="saving">
              {{ saving ? (form.editing ? '保存中...' : '创建中...') : (form.editing ? '保存' : '创建') }}
            </button>
          </div>
        </div>
      </div>
    </transition>

    <!-- 技能详情弹窗 -->
    <transition name="modal-fade">
      <div v-if="detailDialog" class="modal-mask" @click.self="detailDialog = false">
        <div class="modal-card detail-modal">
          <div class="modal-head">
            <span class="modal-title">技能详情</span>
            <button class="modal-close" @click="detailDialog = false">×</button>
          </div>
          <div class="modal-body">
            <div v-if="detailLoading" class="list-loading">加载中...</div>
            <div v-else class="detail-body">
              <div class="detail-row">
                <span class="detail-key">名称</span>
                <span class="detail-val">{{ detail.id }}</span>
              </div>
              <div class="detail-row">
                <span class="detail-key">激活描述</span>
                <span class="detail-val">{{ detail.description }}</span>
              </div>
              <div class="detail-row" v-if="detail.category && detail.category.length">
                <span class="detail-key">分类</span>
                <span class="detail-val">
                  <span class="skill-tag cat" v-for="c in detail.category" :key="'c' + c">{{ c }}</span>
                </span>
              </div>
              <div class="detail-row" v-if="detail.tags && detail.tags.length">
                <span class="detail-key">标签</span>
                <span class="detail-val">
                  <span class="skill-tag" v-for="t in detail.tags" :key="'t' + t">{{ t }}</span>
                </span>
              </div>
              <div class="detail-row" v-if="detail.document || detail.instructions">
                <span class="detail-key">执行指令</span>
                <pre class="detail-doc">{{ detail.document || detail.instructions }}</pre>
              </div>
            </div>
          </div>
          <div class="modal-foot">
            <button class="btn-sm btn-ghost" @click="detailDialog = false">关闭</button>
          </div>
        </div>
      </div>
    </transition>

    <!-- 工具选择器弹窗 -->
    <transition name="modal-fade">
      <div v-if="toolPicker" class="modal-mask" @click.self="toolPicker = false">
        <div class="modal-card tool-modal">
          <div class="modal-head">
            <span class="modal-title">插入工具</span>
            <button class="modal-close" @click="toolPicker = false">×</button>
          </div>
          <div class="modal-body">
            <div v-if="toolLoading" class="list-loading">加载中...</div>
            <div v-else-if="!tools.length" class="pack-empty">
              <p class="empty-text">没有可用工具</p>
              <p class="empty-sub">当前设备未加载任何工具</p>
            </div>
            <div v-else class="tool-list">
              <div v-for="t in tools" :key="t.name || t.id || t" class="tool-item" @click="insertToolName(t.name || t.id || t)">
                <span class="tool-name">{{ t.name || t.id || t }}</span>
                <span class="tool-desc">{{ t.description || t.desc || '' }}</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </transition>

    <!-- 删除确认弹窗 -->
    <transition name="modal-fade">
      <div v-if="deleteDialog" class="modal-mask" @click.self="closeDeleteDialog">
        <div class="modal-card confirm-modal">
          <div class="confirm-icon">{{ deleteTarget ? deleteTarget.id.charAt(0).toUpperCase() : '?' }}</div>
          <h3 class="confirm-title">删除技能</h3>
          <p class="confirm-message">确定删除技能「{{ deleteTarget ? deleteTarget.id : '' }}」吗？此操作不可恢复。</p>
          <div class="confirm-actions">
            <button class="btn-sm btn-ghost" @click="closeDeleteDialog">取消</button>
            <button class="btn-sm btn-danger" @click="doDeleteSkill">确认删除</button>
          </div>
        </div>
      </div>
    </transition>
  </div>
</template>

<script setup>
import { ref, computed, watch, nextTick } from 'vue'
import { api } from '../api'

const props = defineProps({
  currentDevice: Object,
  devices: Array,
})
const emit = defineEmits(['toast', 'select-device'])

const online = computed(() => !!props.currentDevice?.online)
const deviceId = computed(() =>
  props.currentDevice?.mac || props.currentDevice?.device_id || props.currentDevice?.id || props.currentDevice?.device_key || ''
)

const skills = ref([])
const loading = ref(false)
const form = ref({ name: '', description: '', instructions: '', categoryStr: '', tagsStr: '', editing: false })
const saving = ref(false)
const skillDialog = ref(false)
const detailDialog = ref(false)
const detail = ref({})
const detailLoading = ref(false)
const deleteDialog = ref(false)
const deleteTarget = ref(null)
const toolPicker = ref(false)
const tools = ref([])
const toolLoading = ref(false)
const instructionsRef = ref(null)
let instructionsCursorPos = 0

function isCurrent(d) {
  const did = d.device_id || d.id || d.mac || ''
  return did === (props.currentDevice?.device_id || props.currentDevice?.id || props.currentDevice?.mac || '')
}

async function loadSkills() {
  if (!deviceId.value) { skills.value = []; return }
  loading.value = true
  try {
    const res = await api.skills(deviceId.value)
    if (res.status === 200 && res.data?.code === 0) {
      skills.value = res.data.data?.skills || []
    } else {
      skills.value = []
    }
  } catch {
    skills.value = []
  } finally {
    loading.value = false
  }
}

function onInstructionsFocus() {
  instructionsCursorPos = instructionsRef.value?.selectionStart ?? form.value.instructions.length
}

function onInstructionsInput() {
  instructionsCursorPos = instructionsRef.value?.selectionStart ?? form.value.instructions.length
}

function openSkillModal(skill) {
  if (skill) {
    form.value = {
      name: skill.id,
      description: skill.description || '',
      instructions: '',
      categoryStr: (skill.category || []).join(','),
      tagsStr: (skill.tags || []).join(','),
      editing: true,
    }
    skillDialog.value = true
    api.skillDetail(skill.id).then(res => {
      if (res.status === 200 && res.data?.code === 0) {
        form.value.instructions = res.data.data?.instructions || res.data.data?.document || ''
      }
    }).catch(() => {})
  } else {
    form.value = { name: '', description: '', instructions: '', categoryStr: '', tagsStr: '', editing: false }
    skillDialog.value = true
  }
}

function closeSkillModal() { skillDialog.value = false }

const parseList = (s) => s.split(',').map(x => x.trim()).filter(Boolean)

async function submitSkill() {
  const f = form.value
  if (!f.name.trim()) { emit('toast', '请输入技能名称'); return }
  if (!f.description.trim()) { emit('toast', '请输入激活描述'); return }
  if (!f.instructions.trim()) { emit('toast', '请输入执行指令'); return }
  saving.value = true
  const payload = {
    name: f.name.trim(),
    description: f.description.trim(),
    instructions: f.instructions.trim(),
    category: parseList(f.categoryStr),
    tags: parseList(f.tagsStr),
    device_id: deviceId.value,
  }
  const res = f.editing
    ? await api.updateSkill(f.name.trim(), payload)
    : await api.createSkill(payload)
  saving.value = false
  if (res.status === 200 && res.data?.code === 0) {
    emit('toast', f.editing ? '保存成功' : '创建成功')
    closeSkillModal()
    loadSkills()
  } else {
    emit('toast', res.data?.message || res.data?.detail || '操作失败')
  }
}

async function toggleSkill(skill) {
  if (!deviceId.value) { emit('toast', '请先选择设备'); return }
  const newState = !skill.disabled
  const res = await api.toggleSkill(skill.id, deviceId.value, newState)
  if (res.status === 200 && res.data?.code === 0) {
    skill.disabled = newState
    emit('toast', newState ? '已禁用' : '已启用')
  } else {
    emit('toast', res.data?.message || '操作失败')
  }
}

function confirmDeleteSkill(skill) {
  deleteTarget.value = skill
  deleteDialog.value = true
}

function closeDeleteDialog() {
  deleteDialog.value = false
  deleteTarget.value = null
}

async function doDeleteSkill() {
  const skill = deleteTarget.value
  if (!skill) return
  deleteDialog.value = false
  deleteTarget.value = null
  const res = await api.deleteSkill(skill.id)
  if (res.status === 200 && res.data?.code === 0) {
    emit('toast', '已删除')
    loadSkills()
  } else {
    emit('toast', res.data?.message || '删除失败')
  }
}

async function viewSkillDetail(skill) {
  detail.value = { id: skill.id, description: skill.description, category: skill.category, tags: skill.tags, document: '' }
  detailLoading.value = true
  detailDialog.value = true
  try {
    const res = await api.skillDetail(skill.id)
    if (res.status === 200 && res.data?.code === 0) {
      detail.value = res.data.data
    }
  } catch {
    emit('toast', '加载失败')
  } finally {
    detailLoading.value = false
  }
}

async function openToolPicker() {
  tools.value = []
  toolLoading.value = true
  toolPicker.value = true
  try {
    const res = await api.deviceTools(deviceId.value)
    if (res.status === 200 && res.data?.code === 0) {
      const all = res.data.data || []
      tools.value = all.filter(t => t.type !== 'mcp')
    }
  } catch {
    tools.value = []
  } finally {
    toolLoading.value = false
  }
}

function insertToolName(name) {
  const cur = form.value.instructions
  const before = cur.substring(0, instructionsCursorPos)
  const after = cur.substring(instructionsCursorPos)
  form.value.instructions = before + name + after
  instructionsCursorPos += name.length
  toolPicker.value = false
  nextTick(() => { if (instructionsRef.value) instructionsRef.value.focus() })
}

watch(() => props.currentDevice, () => loadSkills(), { immediate: true })
watch(deviceId, () => loadSkills())
</script>

<style scoped>
/* ===== 布局 ===== */
.hero-bar { display: flex; align-items: center; gap: 16px; padding: 26px 28px; margin-bottom: 18px; position: relative; overflow: hidden; }
.watermark {
  font-size: 44px; font-weight: 800; color: var(--mint-soft);
  position: absolute; right: 18px; top: 50%; transform: translateY(-50%);
  line-height: 1; user-select: none;
}
.hero-title { font-size: 22px; font-weight: 800; }
.hero-sub { font-size: 13px; color: var(--text-dim); margin-top: 4px; }
.hero-badge {
  margin-left: auto; display: flex; align-items: center; gap: 6px;
  font-size: 12px; font-weight: 600; color: var(--text-sub);
  padding: 6px 14px; border-radius: 999px;
  background: var(--glass-bg-strong); border: 1px solid var(--glass-border);
}
.hero-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--danger); }
.hero-dot.on { background: var(--mint); box-shadow: 0 0 0 4px var(--mint-soft); animation: dotPulse 2s ease-in-out infinite; }
@keyframes dotPulse {
  0%, 100% { box-shadow: 0 0 0 3px var(--mint-soft); }
  50% { box-shadow: 0 0 0 6px rgba(16,185,129,0.18); }
}

.device-bar { display: flex; flex-wrap: wrap; gap: 10px; margin-bottom: 18px; }
.device-chip {
  display: flex; align-items: center; gap: 8px;
  padding: 9px 16px;
  border: 1px solid var(--glass-border);
  border-radius: 999px;
  background: var(--glass-bg-strong);
  cursor: pointer;
  font-size: 13px;
  transition: all 0.25s var(--ease);
}
.device-chip:hover { border-color: var(--mint-border); background: var(--mint-softer); transform: translateY(-1px); }
.device-chip.selected {
  background: var(--mint-soft);
  border-color: var(--mint);
  box-shadow: var(--shadow-mint);
}
.chip-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--danger); }
.chip-dot.on { background: var(--mint); }
.chip-status { font-size: 11px; color: var(--text-dim); }

.empty-state { display: flex; align-items: center; justify-content: center; padding: 80px 20px; }
.empty-inner { text-align: center; }
.empty-orb {
  width: 64px; height: 64px; margin: 0 auto 14px;
  display: flex; align-items: center; justify-content: center;
  font-size: 30px; border-radius: 50%;
  background: var(--grad-mint);
  box-shadow: var(--shadow-mint), inset 0 1px 0 rgba(255,255,255,0.35);
  animation: orbFloat 3s ease-in-out infinite;
}
@keyframes orbFloat {
  0%, 100% { transform: translateY(0); }
  50% { transform: translateY(-5px); }
}
.empty-title { font-size: 16px; font-weight: 700; }
.empty-sub { font-size: 13px; color: var(--text-dim); margin-top: 6px; }

.section-card { padding: 24px 26px; margin-bottom: 18px; }
.section-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 18px; flex-wrap: wrap; gap: 10px; }
.section-title-wrap { display: flex; align-items: center; gap: 10px; }
.section-ico {
  width: 34px; height: 34px; border-radius: 10px;
  display: flex; align-items: center; justify-content: center;
  font-size: 16px;
  background: var(--mint-soft);
  border: 1px solid var(--mint-border);
}
.section-title { font-size: 15px; font-weight: 700; }
.section-count { font-size: 12px; color: var(--text-dim); }

/* ===== 按钮 ===== */
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

.list-loading, .pack-empty { padding: 24px; text-align: center; color: var(--text-dim); font-size: 13px; }
.empty-text { font-size: 15px; font-weight: 600; color: var(--text-main); }
.empty-sub { font-size: 12px; margin-top: 6px; }

/* ===== 技能列表 ===== */
.skill-list { display: flex; flex-direction: column; gap: 12px; }
.skill-card {
  padding: 16px 18px;
  border: 1px solid var(--glass-border);
  border-radius: var(--radius-md);
  background: var(--glass-bg-soft);
  box-shadow: var(--glass-hi);
  transition: all 0.25s var(--ease);
}
.skill-card:hover { border-color: var(--mint-border); background: var(--mint-softer); }
.skill-card.disabled { opacity: 0.6; }
.skill-card.disabled:hover { opacity: 0.75; }
.skill-card-top { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.skill-info { display: flex; flex-direction: column; gap: 4px; min-width: 0; }
.skill-name { font-size: 14px; font-weight: 700; word-break: break-all; }
.skill-desc { font-size: 12px; color: var(--text-dim); word-break: break-all; }

/* 开关 */
.switch {
  position: relative;
  width: 42px; height: 24px; flex-shrink: 0;
  border-radius: 999px;
  border: 1px solid var(--glass-border);
  background: rgba(0,0,0,0.08);
  cursor: pointer;
  transition: all 0.25s var(--ease);
}
.switch-thumb {
  position: absolute; top: 2px; left: 2px;
  width: 18px; height: 18px;
  border-radius: 50%;
  background: #fff;
  box-shadow: 0 2px 6px rgba(0,0,0,0.2);
  transition: all 0.25s var(--ease);
}
.switch.on {
  background: var(--grad-mint);
  border-color: transparent;
  box-shadow: var(--shadow-mint);
}
.switch.on .switch-thumb { left: 20px; }

.skill-tags { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; }
.skill-tag {
  font-size: 11px; padding: 2px 10px;
  border-radius: 999px;
  background: var(--mint-soft);
  color: var(--mint-deep);
  border: 1px solid var(--mint-border);
}
.skill-tag.cat { background: var(--grad-brand); color: #fff; border: none; }
.skill-actions { display: flex; gap: 8px; margin-top: 12px; }

/* ===== 弹窗 ===== */
.modal-mask {
  position: fixed; inset: 0;
  background: rgba(15, 23, 42, 0.45);
  backdrop-filter: blur(12px) saturate(140%);
  -webkit-backdrop-filter: blur(12px) saturate(140%);
  display: flex; align-items: center; justify-content: center;
  z-index: 1000;
}
.modal-card {
  width: 460px; max-width: 92vw;
  background: var(--grad-panel);
  backdrop-filter: var(--glass-blur);
  -webkit-backdrop-filter: var(--glass-blur);
  border: 1px solid var(--glass-border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-hover), var(--glass-hi);
  overflow: hidden;
  animation: modalPop 0.3s var(--ease);
}
.skill-modal { width: 520px; max-height: 88vh; display: flex; flex-direction: column; }
.detail-modal { width: 440px; max-height: 88vh; display: flex; flex-direction: column; }
.tool-modal { width: 460px; max-height: 88vh; display: flex; flex-direction: column; }
.confirm-modal { width: 360px; padding: 30px 28px; text-align: center; display: flex; flex-direction: column; align-items: center; gap: 6px; }
.confirm-icon {
  width: 46px; height: 46px; border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  font-size: 20px; font-weight: 700; color: var(--danger);
  background: var(--danger-soft); border: 1px solid var(--danger-border);
  margin-bottom: 8px;
}
.confirm-title { font-size: 16px; font-weight: 700; }
.confirm-message { font-size: 13px; color: var(--text-sub); line-height: 1.6; }
.confirm-actions { display: flex; gap: 12px; margin-top: 16px; }
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
.modal-body { padding: 20px; overflow-y: auto; flex: 1; }
.modal-foot {
  display: flex; justify-content: flex-end; gap: 10px;
  padding: 14px 20px;
  border-top: 1px solid var(--glass-border-soft);
}
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
.modal-input:disabled { opacity: 0.6; cursor: not-allowed; }
.modal-textarea {
  width: 100%;
  min-height: 160px;
  padding: 10px 14px;
  border: 1px solid var(--glass-border);
  border-radius: var(--radius-sm);
  font-size: 13px;
  font-family: inherit;
  line-height: 1.6;
  background: rgba(255, 255, 255, 0.6);
  outline: none;
  resize: vertical;
  transition: border-color 0.2s;
  box-sizing: border-box;
}
.modal-textarea:focus { border-color: var(--mint); box-shadow: 0 0 0 3px var(--mint-soft); }

.form-section { margin-bottom: 14px; }
.form-section.grow { flex: 1; min-width: 0; }
.form-label { display: block; font-size: 12px; font-weight: 600; color: var(--text-sub); margin-bottom: 6px; }
.form-hint { display: block; font-size: 11px; color: var(--text-dim); margin-top: 4px; }
.form-label-row { display: flex; align-items: center; justify-content: space-between; margin-bottom: 6px; }
.form-label-row .form-label { margin-bottom: 0; }
.form-row { display: flex; gap: 12px; }
.form-row .form-section { flex: 1; }

/* ===== 详情 ===== */
.detail-body { display: flex; flex-direction: column; gap: 12px; }
.detail-row { display: flex; flex-direction: column; gap: 4px; }
.detail-key { font-size: 12px; font-weight: 600; color: var(--text-dim); }
.detail-val { font-size: 13px; color: var(--text-main); display: flex; flex-wrap: wrap; gap: 6px; }
.detail-doc {
  font-size: 12px; line-height: 1.7;
  white-space: pre-wrap; word-break: break-all;
  background: rgba(255,255,255,0.5);
  border: 1px solid var(--glass-border);
  border-radius: var(--radius-sm);
  padding: 12px;
  margin: 0;
}

/* ===== 工具列表 ===== */
.tool-list { display: flex; flex-direction: column; gap: 8px; }
.tool-item {
  padding: 10px 14px;
  border: 1px solid var(--glass-border);
  border-radius: var(--radius-sm);
  background: var(--glass-bg-soft);
  cursor: pointer;
  transition: all 0.2s var(--ease);
}
.tool-item:hover { border-color: var(--mint); background: var(--mint-softer); transform: translateY(-1px); }
.tool-name { display: block; font-size: 13px; font-weight: 600; color: var(--mint-deep); }
.tool-desc { display: block; font-size: 12px; color: var(--text-dim); margin-top: 2px; }

@media (max-width: 640px) {
  .skill-modal, .detail-modal, .tool-modal { width: 94vw; }
  .form-row { flex-direction: column; }
}
</style>