<template>
  <div ref="containerRef" class="code-editor" :style="containerStyle">
    <div v-if="loading" class="ce-loading">
      <div class="ce-spinner"></div>
      <p>加载编辑器…</p>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount, watch, shallowRef, nextTick } from 'vue'
import { getMonaco, setEditorTheme } from '../monaco-setup'

const THEME_MAP = { light: 'esp-ai-light', dark: 'esp-ai-dark', mint: 'esp-ai-mint' }

const props = defineProps({
  modelValue: { type: String, default: '' },
  language: { type: String, default: 'python' },
  readOnly: { type: Boolean, default: false },
  theme: { type: String, default: 'light' },
  height: { type: String, default: '400px' },
})

const emit = defineEmits(['update:modelValue'])
const containerRef = ref(null)
const editor = shallowRef(null)
const loading = ref(true)

// height 直接用内联样式设置（支持 calc() 像素值）
const containerStyle = computed(() => {
  return { height: props.height }
})

let skipNextChange = false
let pendingValue = null

// ResizeObserver：监听容器尺寸变化，强制 Monaco 重新布局
let resizeObserver = null

onMounted(async () => {
  try {
    const monaco = await getMonaco()
    loading.value = false

    editor.value = monaco.editor.create(containerRef.value, {
      value: props.modelValue || '',
      language: props.language,
      theme: THEME_MAP[props.theme] || 'esp-ai-light',
      readOnly: props.readOnly,
      automaticLayout: true,
      fontSize: 14,
      lineHeight: 22,
      fontFamily: "'JetBrains Mono', 'Fira Code', 'Consolas', 'Monaco', monospace",
      minimap: { enabled: false },
      scrollBeyondLastLine: false,
      tabSize: 4,
      insertSpaces: true,
      wordWrap: 'on',
      padding: { top: 12, bottom: 12 },
      quickSuggestions: { other: true, comments: false, strings: true },
      quickSuggestionsDelay: 100,
      suggestOnTriggerCharacters: true,
      acceptSuggestionOnEnter: 'on',
      tabCompletion: 'on',
      suggest: {
        showKeywords: true, showSnippets: true, showFunctions: true,
        showVariables: true, showClasses: true, showModules: true,
        showWords: true, maxVisibleSuggestions: 12,
      },
      parameterHints: { enabled: true },
      hover: { enabled: true },
      scrollbar: {
        verticalScrollbarSize: 8,
        horizontalScrollbarSize: 8,
        useShadows: false,
      },
      smoothScrolling: true,
      cursorBlinking: 'smooth',
      renderLineHighlight: 'all',
      roundedSelection: true,
    })

    editor.value.onDidChangeModelContent(() => {
      if (skipNextChange) return
      emit('update:modelValue', editor.value.getValue())
    })

    if (pendingValue !== null) {
      skipNextChange = true
      editor.value.setValue(pendingValue)
      skipNextChange = false
      pendingValue = null
    }

    // 用 ResizeObserver 确保容器尺寸变化时 Monaco 重新布局
    resizeObserver = new ResizeObserver(() => {
      if (editor.value) {
        editor.value.layout()
      }
    })
    resizeObserver.observe(containerRef.value)
  } catch (e) {
    loading.value = false
    console.error('Monaco Editor 加载失败:', e)
  }
})

watch(() => props.modelValue, (newVal) => {
  if (!editor.value) { pendingValue = newVal; return }
  if (editor.value.getValue() === newVal) return
  skipNextChange = true
  editor.value.setValue(newVal || '')
  skipNextChange = false
})

watch(() => props.language, (newLang) => {
  if (editor.value) {
    getMonaco().then(monaco => {
      monaco.editor.setModelLanguage(editor.value.getModel(), newLang)
    })
  }
})

watch(() => props.theme, (newTheme) => {
  setEditorTheme(newTheme)
})

watch(() => props.readOnly, (val) => {
  if (editor.value) editor.value.updateOptions({ readOnly: val })
})

watch(() => props.height, () => {
  if (editor.value) {
    nextTick(() => {
      editor.value.layout()
      // 二次确认，确保 flex 布局变化后正确测量
      setTimeout(() => editor.value && editor.value.layout(), 100)
    })
  }
})

onBeforeUnmount(() => {
  if (resizeObserver) {
    resizeObserver.disconnect()
    resizeObserver = null
  }
  if (editor.value) {
    editor.value.dispose()
    editor.value = null
  }
})
</script>

<style scoped>
.code-editor {
  width: 100%;
  border-radius: var(--radius-md, 10px);
  overflow: hidden;
  border: 1px solid var(--border, #e5e7eb);
  position: relative;
}
.ce-loading {
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  gap: 12px; height: 100%; color: var(--text-sub, #888); font-size: 13px;
}
.ce-spinner {
  width: 24px; height: 24px;
  border: 3px solid var(--bg-tint, #f0f0f0);
  border-top-color: var(--mint, #34d399);
  border-radius: 50%;
  animation: ce-spin 0.8s linear infinite;
}
@keyframes ce-spin { to { transform: rotate(360deg); } }
</style>
