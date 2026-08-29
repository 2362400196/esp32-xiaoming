<template>
  <transition name="pop">
    <div v-if="visible" class="run-mask" @click.self="close">
      <div class="run-panel">
        <!-- 头部 -->
        <div class="run-head">
          <h3>运行测试</h3>
          <span class="run-plugin">{{ plugin }}</span>
          <button class="run-close" @click="close">✕</button>
        </div>

        <div class="run-body">
          <!-- 工具选择 -->
          <div class="run-field">
            <label>选择工具</label>
            <select v-model="selectedTool" class="run-select" :disabled="toolsLoading">
              <option value="" disabled>{{ !props.plugin ? '插件创建后才能运行测试' : toolsLoading ? '加载工具中…' : (tools.length ? '选择要运行的工具' : '未找到已注册的工具') }}</option>
              <option v-for="t in tools" :key="t.name" :value="t.name">{{ t.name }}</option>
            </select>
            <p v-if="currentTool" class="run-desc">{{ currentTool.description }}</p>
          </div>

          <!-- 测试设备（自动沿用主应用选定的设备） -->
          <div class="run-field">
            <label>测试设备</label>
            <div class="run-device" :class="{ offline: !deviceOnline }">
              {{ deviceLabel }}<span v-if="props.device && !deviceOnline">（离线，设备相关工具可能失败）</span>
            </div>
          </div>

          <!-- 参数表单 -->
          <div v-if="paramFields.length" class="run-field">
            <label>参数</label>
            <div class="run-params">
              <div v-for="f in paramFields" :key="f.name" class="run-param">
                <label class="run-param-label">
                  {{ f.name }}
                  <span v-if="f.required" class="req">*</span>
                  <span class="run-param-type">{{ f.type }}</span>
                </label>
                <select v-if="f.type === 'boolean'" v-model="argsDraft[f.name]" class="run-input">
                  <option :value="true">true</option>
                  <option :value="false">false</option>
                </select>
                <input v-else-if="f.type === 'number' || f.type === 'integer'" v-model="argsDraft[f.name]"
                  type="number" class="run-input" :placeholder="f.required ? '必填' : '可留空'" />
                <textarea v-else-if="f.type === 'object' || f.type === 'array'" v-model="argsDraft[f.name]"
                  rows="3" class="run-input run-json" placeholder='JSON，如 {"key": "value"}' />
                <input v-else v-model="argsDraft[f.name]" class="run-input" :placeholder="f.required ? '必填' : '可留空'" />
              </div>
            </div>
          </div>
          <p v-else-if="selectedTool" class="run-noparams">该工具无需参数</p>

          <!-- 运行按钮 -->
          <button class="run-btn" :disabled="running" @click="run">
            {{ running ? '运行中…' : '▶ 运行' }}
          </button>

          <!-- 结果 -->
          <div v-if="result !== null" class="run-result">
            <div class="run-result-head" :class="{ err: isError }">
              {{ isError ? '✕ 运行失败' : '✓ 运行成功' }}
            </div>
            <pre class="run-result-body">{{ result }}</pre>
          </div>

          <!-- 运行日志 -->
          <div v-if="logs.length" class="run-logs">
            <div class="run-logs-head">运行日志（最新 {{ logs.length }} 条）</div>
            <div class="run-logs-body">
              <div v-for="(e, i) in logs" :key="i" class="ec-line" :class="'log-' + e.level">
                <span class="ec-time">{{ fmtTime(e.time) }}</span>
                <span class="ec-msg">{{ e.message }}</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </transition>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { request } from '../../api'

const props = defineProps({
  plugin: { type: String, default: '' },
  visible: { type: Boolean, default: false },
  device: { type: Object, default: null },
})

// 当前设备（由主应用设备管理页选定的上下文自动带入，无需手动选）
const deviceLabel = computed(() => {
  const d = props.device
  if (!d) return '未选择设备（设备相关工具将无法测试）'
  const id = d.device_id || d.id || d.mac || ''
  return (d.name && d.name.trim()) || id
})
const deviceIdResolved = computed(() =>
  props.device ? (props.device.device_id || props.device.id || props.device.mac || '') : '')
const deviceOnline = computed(() => !!props.device?.online)
const emit = defineEmits(['close'])

const tools = ref([])
const toolsLoading = ref(false)
const selectedTool = ref('')
const argsDraft = ref({})
const running = ref(false)
const result = ref(null)   // 格式化后的结果字符串
const isError = ref(false)
const logs = ref([])

const currentTool = computed(() => tools.value.find(t => t.name === selectedTool.value) || null)

// 根据选中工具的 schema 生成参数表单
const paramFields = computed(() => {
  if (!currentTool.value) return []
  const params = currentTool.value.parameters || {}
  const props = params.properties || {}
  const required = params.required || []
  return Object.entries(props).map(([name, schema]) => ({
    name,
    type: schema.type || 'string',
    description: schema.description || '',
    required: required.includes(name),
    default: schema.default,
  }))
})

async function loadData() {
  if (!props.plugin) return  // 新建模式（插件尚未创建）无工具可运行
  toolsLoading.value = true
  tools.value = []
  result.value = null
  logs.value = []
  try {
    const res = await request('/api/v1/plugins/' + encodeURIComponent(props.plugin) + '/tools')
    if (res.status === 200 && res.data?.code === 0) {
      tools.value = res.data.data || []
      // 自动选中第一个工具，打开即可直接点运行
      if (tools.value.length) selectedTool.value = tools.value[0].name
    }
  } catch {}
  toolsLoading.value = false
}

// 选中工具 → 初始化参数草稿（用 schema 默认值）
watch(selectedTool, () => {
  argsDraft.value = {}
  for (const f of paramFields.value) {
    if (f.default !== undefined) argsDraft.value[f.name] = f.default
    else if (f.type === 'boolean') argsDraft.value[f.name] = false
    else argsDraft.value[f.name] = ''
  }
})

function buildArgs() {
  const args = {}
  for (const f of paramFields.value) {
    const v = argsDraft.value[f.name]
    if (v === '' || v === undefined || v === null) {
      if (f.required) throw new Error(`参数 ${f.name} 必填`)
      continue
    }
    if (f.type === 'number' || f.type === 'integer') args[f.name] = Number(v)
    else if (f.type === 'boolean') args[f.name] = Boolean(v)
    else if (f.type === 'object' || f.type === 'array') {
      try { args[f.name] = JSON.parse(v) }
      catch { throw new Error(`参数 ${f.name} 不是合法 JSON`) }
    } else args[f.name] = String(v)
  }
  return args
}

async function run() {
  // 未注册工具：大概率是插件加载失败（工具名冲突/语法错误）。拉取日志帮助定位
  if (!selectedTool.value) {
    running.value = true
    isError.value = true
    result.value = [
      '没有可运行的工具。常见原因：',
      '1. 插件加载失败——下方日志里有具体原因（如工具名冲突、语法错误）',
      '2. 插件尚未创建',
      '处理：按日志提示修复后，重新保存插件即可热重载；若日志显示"已被占用"，重启服务端后重新保存一次即可自愈',
    ].join('\n')
    try {
      const res = await request('/api/v1/plugins/' + encodeURIComponent(props.plugin) + '/logs?limit=20')
      if (res.status === 200 && res.data?.code === 0) logs.value = (res.data.data || []).slice(0, 20)
    } catch {}
    running.value = false
    return
  }

  let args
  try { args = buildArgs() }
  catch (e) { result.value = e.message; isError.value = true; return }

  running.value = true
  result.value = null
  try {
    const res = await request('/api/v1/plugins/' + encodeURIComponent(props.plugin) +
      '/tool/' + encodeURIComponent(selectedTool.value), 'POST',
      { args, device_id: deviceIdResolved.value || undefined })
    result.value = JSON.stringify(res.data, null, 2)
    isError.value = res.status !== 200 || res.data?.code !== 0
  } catch (e) {
    result.value = String(e)
    isError.value = true
  }
  running.value = false
  // 运行后拉取该插件最新日志（含本次执行的 plugin_log 输出与错误）
  try {
    const res = await request('/api/v1/plugins/' + encodeURIComponent(props.plugin) + '/logs?limit=20')
    if (res.status === 200 && res.data?.code === 0) logs.value = (res.data.data || []).slice(0, 20)
  } catch {}
}

function fmtTime(ts) {
  if (!ts) return ''
  return ts.replace('T', ' ').replace(/\.\d+$/, '')
}

function close() {
  emit('close')
}

watch(() => props.visible, (v) => { if (v) loadData() })
</script>

<style scoped>
.run-mask {
  position: fixed; inset: 0; z-index: 310;
  background: rgba(15, 23, 42, 0.4); backdrop-filter: blur(8px);
  display: flex; align-items: center; justify-content: center;
}
.run-panel {
  width: min(920px, 94vw); height: min(760px, 88vh);
  background: var(--grad-panel, #fff);
  border-radius: var(--radius-lg, 18px);
  box-shadow: 0 24px 64px rgba(23, 52, 74, 0.25);
  display: flex; flex-direction: column; overflow: hidden;
}
.run-head {
  display: flex; align-items: center; gap: 10px;
  padding: 16px 20px; border-bottom: 1px solid var(--glass-border-soft, rgba(0,0,0,0.06));
  flex-shrink: 0;
}
.run-head h3 { font-size: 16px; font-weight: 700; margin: 0; }
.run-plugin {
  font-family: monospace; font-size: 12px; padding: 2px 10px;
  border-radius: 999px; background: var(--mint-soft, rgba(16,185,129,0.12));
  color: var(--mint-deep, #059669);
}
.run-close {
  margin-left: auto; width: 30px; height: 30px; border: none; border-radius: 8px;
  background: transparent; color: var(--text-sub, #5b6b78); font-size: 14px; cursor: pointer;
}
.run-close:hover { background: var(--mint-soft); }
.run-body { flex: 1; min-height: 0; overflow-y: auto; padding: 18px 20px; display: flex; flex-direction: column; gap: 14px; }

.run-field label {
  display: block; font-size: 12px; font-weight: 600; color: var(--text-sub, #5b6b78);
  margin-bottom: 5px;
}
.run-select, .run-input {
  width: 100%; padding: 9px 12px; font-size: 13px; font-family: inherit;
  border: 1px solid var(--glass-border, rgba(0,0,0,0.08)); border-radius: 10px;
  background: rgba(255,255,255,0.8); color: var(--text-main, #12212e);
  outline: none; transition: all 0.2s; box-sizing: border-box;
}
.run-select:focus, .run-input:focus {
  border-color: var(--mint, #10b981);
  box-shadow: 0 0 0 3px var(--mint-soft, rgba(16,185,129,0.12));
}
.run-json { font-family: 'SF Mono', Consolas, monospace; }
.run-desc { font-size: 12px; color: var(--text-sub, #5b6b78); margin: 5px 0 0; }
.run-params { display: flex; flex-direction: column; gap: 10px; }
.run-param-label .req { color: var(--danger, #ef4444); }
.run-param-type {
  font-size: 10px; padding: 1px 5px; border-radius: 4px; margin-left: 5px;
  background: var(--mint-soft, rgba(16,185,129,0.12)); color: var(--mint-deep, #059669);
}
.run-noparams { font-size: 12px; color: var(--text-dim, #8fa0ad); }
.run-device {
  padding: 9px 12px; font-size: 13px;
  border: 1px solid var(--glass-border, rgba(0,0,0,0.08)); border-radius: 10px;
  background: var(--mint-soft, rgba(16,185,129,0.12)); color: var(--text-main, #12212e);
}
.run-device.offline { color: var(--amber, #f59e0b); }
.run-btn {
  align-self: flex-start; padding: 9px 28px; font-size: 13px; font-weight: 700;
  border: none; border-radius: 10px; cursor: pointer;
  background: var(--grad-mint, linear-gradient(135deg, #34d399, #10b981));
  color: #fff; box-shadow: 0 4px 12px rgba(16,185,129,0.28); transition: all 0.2s;
}
.run-btn:hover:not(:disabled) { filter: brightness(1.06); transform: translateY(-1px); }
.run-btn:disabled { opacity: 0.5; cursor: not-allowed; }

.run-result { border-radius: 10px; overflow: hidden; border: 1px solid var(--glass-border, rgba(0,0,0,0.08)); }
.run-result-head {
  padding: 7px 14px; font-size: 12px; font-weight: 700;
  background: var(--mint-soft, rgba(16,185,129,0.12)); color: var(--mint-deep, #059669);
}
.run-result-head.err { background: var(--danger-soft, rgba(239,68,68,0.1)); color: var(--danger, #ef4444); }
.run-result-body {
  margin: 0; padding: 12px 14px; max-height: 320px; overflow: auto;
  background: #0d1117; color: #e6edf3;
  font-family: 'SF Mono', Consolas, monospace; font-size: 12px; line-height: 1.6;
  white-space: pre-wrap; word-break: break-word;
}
.run-logs { border-radius: 10px; overflow: hidden; border: 1px solid var(--glass-border, rgba(0,0,0,0.08)); display: flex; flex-direction: column; flex: 1; min-height: 220px; }
.run-logs-head {
  padding: 6px 14px; font-size: 11px; font-weight: 700;
  background: rgba(23,52,74,0.05); color: var(--text-sub, #5b6b78);
}
.run-logs-body {
  flex: 1; min-height: 0; overflow-y: auto; padding: 8px 12px;
  background: #0d1117;
  font-family: 'SF Mono', Consolas, monospace; font-size: 11px; line-height: 1.6;
}
.ec-line { display: flex; margin-bottom: 3px; word-break: break-word; }
.ec-time { color: #8b949e; margin-right: 10px; min-width: 90px; font-size: 10px; flex-shrink: 0; }
.ec-msg { flex: 1; min-width: 0; white-space: pre-wrap; color: #e6edf3; }
.log-error .ec-msg { color: #f85149; }
.log-warn .ec-msg { color: #f2cc60; }
.log-info .ec-msg { color: #79c0ff; }
.log-debug .ec-msg { color: #8b949e; }
.log-stderr .ec-msg { color: #d2a8ff; }

.pop-enter-active, .pop-leave-active { transition: all 0.25s var(--ease, ease); }
.pop-enter-from, .pop-leave-to { opacity: 0; transform: scale(0.96); }
</style>
