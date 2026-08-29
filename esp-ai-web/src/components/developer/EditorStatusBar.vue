<template>
  <div class="ed-statusbar">
    <div class="sb-left">
      <span class="st-file" :title="codeEditor.activeFile">{{ codeEditor.activeFile || '—' }}</span>
      <span class="st-sep">·</span>
      <span class="st-lang">{{ langLabel }}</span>
      <span class="st-sep">·</span>
      <span class="st-lines">{{ lines }} 行</span>
      <span v-if="activeIsDirty" class="st-dirty">● 未保存</span>
    </div>
    <div class="sb-right">
      <template v-if="codeEditor.mode === 'create'">
        <button class="st-btn ghost" :disabled="codeEditor.saving" @click="savePluginCode">
          {{ codeEditor.saving === 'market' ? '上架中…' : '上架到市场' }}
        </button>
        <button class="st-btn primary" :disabled="codeEditor.saving" @click="createLocalFromEditor">
          {{ codeEditor.saving === 'local' ? '创建中…' : '创建' }}
        </button>
      </template>
      <template v-else-if="codeEditor.mode === 'local-edit'">
        <button class="st-btn primary" :disabled="codeEditor.saving" @click="saveLocalFromEditor">
          {{ codeEditor.saving === 'local' ? '保存中…' : '保存并热重载' }}
        </button>
      </template>
      <template v-else>
        <button class="st-btn ghost" :disabled="codeEditor.saving" @click="saveLocalFromEditor">
          {{ codeEditor.saving === 'local' ? '保存中…' : '本地保存' }}
        </button>
        <button class="st-btn primary" :disabled="codeEditor.saving" @click="savePluginCode">
          {{ codeEditor.saving === 'market' ? '保存中…' : '保存新版本' }}
        </button>
      </template>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import {
  codeEditor, activeFileEntry, activeFileLines, fileLang, isDirty,
  savePluginCode, saveLocalFromEditor, createLocalFromEditor,
} from '../../composables/usePluginEditor'

const langLabel = computed(() => {
  if (!codeEditor.value.activeFile) return ''
  const lang = fileLang(codeEditor.value.activeFile)
  const names = {
    python: 'Python', json: 'JSON', markdown: 'Markdown', html: 'HTML',
    css: 'CSS', javascript: 'JavaScript', typescript: 'TypeScript',
    yaml: 'YAML', shell: 'Shell', ini: 'TOML', plaintext: 'Text',
  }
  return names[lang] || lang
})

const lines = activeFileLines

const activeIsDirty = computed(() => isDirty(codeEditor.value.activeFile))
</script>

<style scoped>
.ed-statusbar {
  display: flex; align-items: center; justify-content: space-between; gap: 12px;
  padding: 7px 14px; flex-shrink: 0;
  border-top: 1px solid var(--glass-border-soft, rgba(0,0,0,0.06));
  background: rgba(255,255,255,0.55);
  font-size: 12px; color: var(--text-sub, #5b6b78);
}
.sb-left { display: flex; align-items: center; gap: 8px; min-width: 0; overflow: hidden; }
.st-file {
  font-family: 'SF Mono', 'Fira Code', Consolas, monospace;
  color: var(--text-main, #12212e); font-weight: 600;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 320px;
}
.st-sep { opacity: 0.5; }
.st-dirty { color: var(--amber, #f59e0b); font-weight: 700; }
.sb-right { display: flex; gap: 8px; flex-shrink: 0; }
.st-btn {
  padding: 6px 14px; font-size: 12px; font-weight: 600;
  border: none; border-radius: 8px; cursor: pointer; transition: all 0.2s;
}
.st-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.st-btn.primary {
  background: var(--grad-mint, linear-gradient(135deg, #34d399, #10b981));
  color: #fff; box-shadow: 0 4px 12px rgba(16,185,129,0.28);
}
.st-btn.primary:hover:not(:disabled) { filter: brightness(1.06); }
.st-btn.ghost {
  background: transparent; color: var(--text-sub, #5b6b78);
  border: 1px solid var(--glass-border, rgba(0,0,0,0.08));
}
.st-btn.ghost:hover:not(:disabled) { border-color: var(--mint-border); color: var(--mint-deep); }
</style>
