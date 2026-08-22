<template>
  <div class="plugin-page-view">
    <iframe
      ref="iframeRef"
      :src="pluginUrl"
      class="pp-iframe"
      @load="onIframeLoad"
    />
    <div v-if="!loaded" class="pp-loading">
      <div class="spinner"></div>
      <p>加载插件页面…</p>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onBeforeUnmount } from 'vue'

const props = defineProps({
  pluginName: { type: String, default: '' },
  pluginTitle: { type: String, default: '' },
  pluginEntry: { type: String, default: '' },
  currentDevice: { type: Object, default: null },
})
const emit = defineEmits(['toast'])

const iframeRef = ref(null)
const loaded = ref(false)

const pluginUrl = computed(() => {
  const base = props.pluginEntry
  if (!base) return ''
  // 附加设备 ID 作为查询参数，让插件页面直接从 URL 读取
  const mac = deviceMac()
  if (!mac) return base
  const separator = base.includes('?') ? '&' : '?'
  return `${base}${separator}device_id=${encodeURIComponent(mac)}`
})

function deviceMac() {
  return props.currentDevice?.device_id || props.currentDevice?.id || props.currentDevice?.mac || ''
}

function onIframeLoad() {
  loaded.value = true
  // 告知插件页面当前设备信息
  sendToPlugin({ type: 'deviceChanged', device: props.currentDevice })
}

function sendToPlugin(msg) {
  try {
    iframeRef.value?.contentWindow?.postMessage(msg, '*')
  } catch { /* 静默 */ }
}

function handleMessage(e) {
  try {
    const msg = typeof e.data === 'object' ? e.data : JSON.parse(e.data)
    if (msg.type === 'toast') {
      emit('toast', msg.message || '')
    } else if (msg.type === 'ready') {
      // 插件页面就绪，发送设备信息
      sendToPlugin({ type: 'deviceChanged', device: props.currentDevice })
    }
  } catch { /* 静默 */ }
}

watch(() => props.currentDevice, (d) => {
  sendToPlugin({ type: 'deviceChanged', device: d })
}, { deep: true })

onMounted(() => {
  window.addEventListener('message', handleMessage)
})

onBeforeUnmount(() => {
  window.removeEventListener('message', handleMessage)
})
</script>

<style scoped>
.plugin-page-view {
  position: relative;
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
}
.pp-iframe {
  flex: 1;
  width: 100%;
  border: none;
  display: block;
  min-height: 0;
}
.pp-loading {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  color: var(--text-sub);
}
.spinner {
  width: 32px; height: 32px;
  border: 3px solid var(--mint-soft);
  border-top-color: var(--mint-deep);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }
</style>