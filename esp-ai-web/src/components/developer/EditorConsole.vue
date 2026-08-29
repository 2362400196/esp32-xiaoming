<template>
  <div class="ed-console">
    <div class="ec-head">
      <span class="ec-title">运行日志 · {{ plugin }}</span>
      <select v-model="level" class="ec-select" @change="refresh">
        <option value="">全部级别</option>
        <option value="error">Error</option>
        <option value="warn">Warn</option>
        <option value="info">Info</option>
        <option value="debug">Debug</option>
        <option value="stderr">Stderr</option>
      </select>
      <button class="ec-btn" :class="{ active: auto }" @click="toggleAuto">
        {{ auto ? '自动 ✓' : '自动' }}
      </button>
      <button class="ec-btn" @click="refresh">刷新</button>
      <button class="ec-btn" @click="$emit('close')">收起 ✕</button>
    </div>
    <div class="ec-body" ref="bodyRef">
      <div v-if="loading && !entries.length" class="ec-loading">加载中…</div>
      <div v-else-if="!entries.length" class="ec-empty">暂无日志。插件运行时的错误与 plugin_log() 输出会显示在这里</div>
      <div v-else>
        <div v-for="(e, i) in entries" :key="i" class="ec-line" :class="'log-' + e.level">
          <span class="ec-time">{{ fmtTime(e.time) }}</span>
          <span class="ec-msg">{{ e.message }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, watch, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { api } from '../../api'

const props = defineProps({
  plugin: { type: String, default: '' },
})
defineEmits(['close'])

const entries = ref([])
const loading = ref(false)
const level = ref('')
const auto = ref(true)
const bodyRef = ref(null)
let timer = null

function fmtTime(ts) {
  if (!ts) return ''
  return ts.replace('T', ' ').replace(/\.\d+$/, '')
}

async function refresh() {
  if (!props.plugin) return
  loading.value = true
  try {
    const res = await api.pluginLogs(props.plugin, 100, level.value || null)
    if (res.status === 200 && res.data?.code === 0) {
      // 最新在前 → 反转成终端风格（最新在底部）
      entries.value = (res.data.data || []).reverse()
      nextTick(() => {
        const el = bodyRef.value
        if (el) el.scrollTop = el.scrollHeight
      })
    } else {
      entries.value = []
    }
  } catch {
    entries.value = []
  }
  loading.value = false
}

function toggleAuto() {
  auto.value = !auto.value
}

function startTimer() {
  stopTimer()
  if (auto.value) timer = setInterval(refresh, 3000)
}

function stopTimer() {
  if (timer) { clearInterval(timer); timer = null }
}

watch([() => props.plugin, auto], () => {
  refresh()
  startTimer()
})

onMounted(() => {
  refresh()
  startTimer()
})

onBeforeUnmount(stopTimer)
</script>

<style scoped>
.ed-console {
  flex: 1; min-height: 0; height: 100%;
  display: flex; flex-direction: column;
  border-top: 1px solid var(--glass-border-soft, rgba(255,255,255,0.45));
  background: #0d1117;
}
.ec-head {
  display: flex; align-items: center; gap: 8px;
  padding: 6px 12px; flex-shrink: 0;
  border-bottom: 1px solid rgba(255,255,255,0.08);
}
.ec-title { font-size: 12px; font-weight: 600; color: #e6edf3; margin-right: auto; }
.ec-select {
  padding: 3px 8px; font-size: 11px; border-radius: 6px;
  border: 1px solid rgba(255,255,255,0.15); background: #161b22; color: #e6edf3;
  outline: none; cursor: pointer;
}
.ec-btn {
  padding: 3px 10px; font-size: 11px; border-radius: 6px;
  border: 1px solid rgba(255,255,255,0.15); background: transparent; color: #8b949e;
  cursor: pointer; transition: all 0.15s;
}
.ec-btn:hover, .ec-btn.active { color: #e6edf3; border-color: rgba(255,255,255,0.3); }
.ec-body {
  flex: 1; overflow-y: auto; padding: 10px 14px;
  font-family: 'SF Mono', 'Fira Code', Consolas, monospace; font-size: 12px; line-height: 1.6;
}
.ec-loading, .ec-empty { color: #8b949e; font-size: 12px; padding: 12px 4px; }
.ec-line { display: flex; margin-bottom: 3px; word-break: break-word; }
.ec-line:hover { background: rgba(255,255,255,0.03); }
.ec-time { color: #8b949e; margin-right: 12px; min-width: 96px; font-size: 11px; flex-shrink: 0; }
.ec-msg { flex: 1; min-width: 0; white-space: pre-wrap; color: #e6edf3; }
.log-error .ec-msg { color: #f85149; }
.log-warn .ec-msg { color: #f2cc60; }
.log-info .ec-msg { color: #79c0ff; }
.log-debug .ec-msg { color: #8b949e; }
.log-stderr .ec-msg { color: #d2a8ff; }
.log-error { background: rgba(248,81,73,0.06); }
</style>
