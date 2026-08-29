// 插件运行日志（模块级单例）
import { ref, computed, nextTick } from 'vue'
import { api } from '../api'
import { toast } from './useToastBridge'
import { showConfirm } from './useConfirm'
import { localInstalled } from './useLocalPlugins'

export const logView = ref({
  plugin: '',
  level: '',
  entries: [],
  loading: false,
  autoRefresh: false,
})

export const pluginLogTerminalRef = ref(null)
let _logTimer = null

export const allPluginNames = computed(() => {
  return localInstalled.value.map(p => p.name).filter(Boolean).sort()
})

function scrollLogToBottom() {
  nextTick(() => {
    const el = pluginLogTerminalRef.value
    if (el) el.scrollTop = el.scrollHeight
  })
}

export async function loadLogs() {
  if (!logView.value.plugin) return
  logView.value.loading = true
  try {
    const res = await api.pluginLogs(logView.value.plugin, 200, logView.value.level || null)
    if (res.status === 200 && res.data?.code === 0) {
      // 后端返回最新在前，反转后最新在底部（终端风格）
      logView.value.entries = (res.data.data || []).reverse()
      scrollLogToBottom()
    } else {
      toast(res.data?.message || '获取日志失败')
      logView.value.entries = []
    }
  } catch (e) {
    toast('获取日志异常')
    logView.value.entries = []
  }
  logView.value.loading = false
}

export async function copyLogs() {
  if (!logView.value.entries.length) return
  const text = logView.value.entries
    .map(e => `${formatLogTime(e.time)} [${String(e.level || '').toUpperCase()}] ${e.message}`)
    .join('\n')
  try {
    await navigator.clipboard.writeText(text)
    toast('日志已复制到剪贴板')
  } catch (e) {
    toast('复制失败，请手动选择复制')
  }
}

export async function clearLogs() {
  if (!logView.value.plugin) return
  const ok = await showConfirm({
    title: '清空日志',
    message: `确定清空「${logView.value.plugin}」的所有运行日志？`,
    confirmText: '清空',
    cancelText: '取消',
    danger: true,
  })
  if (!ok) return
  const res = await api.clearPluginLogs(logView.value.plugin)
  if (res.status === 200 && res.data?.code === 0) {
    logView.value.entries = []
    toast('日志已清空')
  } else {
    toast(res.data?.message || '清空失败')
  }
}

export function toggleAutoRefresh() {
  logView.value.autoRefresh = !logView.value.autoRefresh
  if (logView.value.autoRefresh) {
    _logTimer = setInterval(() => {
      if (logView.value.plugin) loadLogs()
    }, 5000)
  } else {
    if (_logTimer) { clearInterval(_logTimer); _logTimer = null }
  }
}

export function stopAutoRefresh() {
  if (_logTimer) { clearInterval(_logTimer); _logTimer = null }
}

export function formatLogTime(ts) {
  if (!ts) return ''
  return ts.replace('T', ' ').replace(/\.\d+$/, '')
}
