<template>
  <div class="editor-page" :class="{ fullscreen: editorFullscreen }">
    <!-- 顶栏 -->
    <div class="editor-topbar">
      <button class="editor-back" @click="closeEditor">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <line x1="19" y1="12" x2="5" y2="12"/><polyline points="12 19 5 12 12 5"/>
        </svg>
        返回
      </button>
      <div class="editor-title-wrap">
        <h3 class="editor-title">
          {{ codeEditor.mode === 'create' ? '新建插件' : '编辑插件' }}
        </h3>
        <span class="editor-slug" v-if="codeEditor.slug">{{ codeEditor.slug }}</span>
        <span class="editor-mode" :class="codeEditor.mode">
          {{ codeEditor.mode === 'create' ? '新建' : codeEditor.mode === 'local-edit' ? '本地' : '已发布' }}
        </span>
        <span v-if="hasDirty()" class="editor-dirty-badge" title="有未保存的修改">● 有修改</span>
      </div>
      <div class="editor-topbar-right">
        <button v-if="codeEditor.mode !== 'create'" class="tb-run-btn"
          title="运行测试（不唤醒设备，直接调用插件工具）"
          :disabled="codeEditor.loading" @click="runOpen = true">
          ▶ 运行
        </button>
        <button class="tb-icon-btn" :class="{ active: consoleOpen }" title="运行日志"
          @click="consoleOpen = true">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
            <polyline points="14 2 14 8 20 8"/>
            <line x1="16" y1="13" x2="8" y2="13"/>
            <line x1="16" y1="17" x2="8" y2="17"/>
          </svg>
        </button>
        <button class="tb-icon-btn" :class="{ active: settingsOpen }" title="插件设置 (ID/名称/版本/权限)"
          @click="settingsOpen = !settingsOpen">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <circle cx="12" cy="12" r="3"/>
            <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/>
          </svg>
        </button>
        <button class="tb-icon-btn" :title="editorFullscreen ? '退出全屏 (Esc)' : '全屏编辑'"
          @click="toggleFullscreen">
          <svg v-if="editorFullscreen" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M8 3v3a2 2 0 0 1-2 2H3"/><path d="M21 8h-3a2 2 0 0 1-2-2V3"/>
            <path d="M3 16h3a2 2 0 0 1 2 2v3"/><path d="M16 21v-3a2 2 0 0 1 2-2h3"/>
          </svg>
          <svg v-else width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M8 3H5a2 2 0 0 0-2 2v3"/><path d="M21 8V5a2 2 0 0 0-2-2h-3"/>
            <path d="M3 16v3a2 2 0 0 0 2 2h3"/><path d="M16 21h3a2 2 0 0 0 2-2v-3"/>
          </svg>
        </button>
        <div class="theme-switcher">
          <button v-for="t in editorThemes" :key="t.id" class="theme-btn"
            :class="{ active: editorTheme === t.id }" :title="t.label"
            @click="setEditorTheme(t.id)">
            {{ t.icon }}
          </button>
        </div>
      </div>
    </div>

    <!-- 三栏主体：侧栏 | 编辑区 -->
    <div class="editor-main">
      <EditorSidebar @open-settings="settingsOpen = true" />

      <div class="editor-center">
        <!-- 打开的文件标签 -->
        <div class="open-tabs">
          <div class="open-tab" v-for="name in openedTabs" :key="name"
            :class="{ active: codeEditor.activeFile === name }"
            @click="openFile(name)">
            <span class="ft-icon" :class="fileIcon(name).cls">{{ fileIcon(name).label }}</span>
            <span class="open-tab-name">{{ name.split('/').pop() }}</span>
            <span v-if="isDirty(name)" class="open-tab-dirty" title="未保存"></span>
            <span class="open-tab-close" title="关闭标签" @click.stop="closeTab(name)">×</span>
          </div>
          <span v-if="!openedTabs.length" class="open-tabs-empty">从左侧选择文件开始编辑</span>
        </div>

        <!-- Monaco -->
        <div class="editor-body">
          <div v-if="codeEditor.loading" class="editor-loading">
            <div class="spinner"></div>
            <p>正在加载源码…</p>
          </div>
          <template v-else-if="activeFileEntry">
            <CodeEditor :key="codeEditor.activeFile" v-if="codeEditor.activeFile.endsWith('.json')"
              v-model="activeFileEntry.content" language="json" height="100%" :theme="editorTheme" />
            <CodeEditor :key="codeEditor.activeFile" v-else
              v-model="activeFileEntry.content" :language="fileLang(codeEditor.activeFile)"
              height="100%" :theme="editorTheme" />
          </template>
          <div v-else class="editor-nofile">
            <p>从左侧文件树选择或新建文件</p>
          </div>
        </div>
      </div>
    </div>

    <!-- 状态栏：文件信息 + 保存 -->
    <EditorStatusBar />

    <!-- 设置抽屉 -->
    <EditorMetaDrawer :open="settingsOpen" @close="settingsOpen = false" />

    <!-- 运行测试弹窗 -->
    <RunToolModal :plugin="codeEditor.slug" :visible="runOpen" :device="currentDevice" @close="runOpen = false" />

    <!-- 运行日志弹窗 -->
    <transition name="pop">
      <div v-if="consoleOpen" class="console-mask" @click.self="consoleOpen = false">
        <div class="console-panel">
          <EditorConsole :plugin="codeEditor.slug" @close="consoleOpen = false" />
        </div>
      </div>
    </transition>

    <!-- 新建文件/文件夹弹窗 -->
    <transition name="pop">
      <div v-if="newFileDialog.show" class="confirm-mask" @click.self="closeNewFileDialog">
        <div class="confirm-panel glass">
          <div class="confirm-title">{{ newFileDialog.mode === 'folder' ? '新建文件夹' : '新建文件' }}</div>
          <p class="confirm-message" v-if="newFileDialog.mode === 'folder'">
            输入文件夹名（如 utils、data/templates）。系统会自动放入 .gitkeep 占位文件以保留文件夹
          </p>
          <p class="confirm-message" v-else>
            输入文件名，支持子目录路径（如 utils/helpers.py、data/help.md）
          </p>
          <input ref="newFileInput" v-model="newFileName" class="new-file-input"
            :placeholder="newFileDialog.mode === 'folder' ? '如 utils' : '如 utils/helpers.py'"
            @keyup.enter="confirmNewFile" />
          <div class="confirm-actions">
            <button class="btn-ghost confirm-cancel" @click="closeNewFileDialog">取消</button>
            <button class="confirm-ok" @click="confirmNewFile">创建</button>
          </div>
        </div>
      </div>
    </transition>

    <!-- 重命名弹窗（文件/文件夹） -->
    <transition name="pop">
      <div v-if="renameDialog.show" class="confirm-mask" @click.self="closeRenameDialog">
        <div class="confirm-panel glass">
          <div class="confirm-title">{{ renameDialog.isDir ? '重命名文件夹' : '重命名文件' }}</div>
          <p class="confirm-message" v-if="renameDialog.isDir">
            文件夹内所有文件将一并更名（如 utils → tools）
          </p>
          <input ref="renameInput" v-model="renameName" class="new-file-input" @keyup.enter="confirmRename" />
          <div class="confirm-actions">
            <button class="btn-ghost confirm-cancel" @click="closeRenameDialog">取消</button>
            <button class="confirm-ok" @click="confirmRename">重命名</button>
          </div>
        </div>
      </div>
    </transition>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import CodeEditor from '../CodeEditor.vue'
import { THEMES } from '../../monaco-setup'
import EditorSidebar from './EditorSidebar.vue'
import EditorMetaDrawer from './EditorMetaDrawer.vue'
import EditorStatusBar from './EditorStatusBar.vue'
import EditorConsole from './EditorConsole.vue'
import RunToolModal from './RunToolModal.vue'
import {
  codeEditor, editorFullscreen, toggleFullscreen, closeEditor, hasDirty,
  openedTabs, openFile, closeTab, isDirty, fileIcon,
  activeFileEntry, fileLang,
  savePluginCode, saveLocalFromEditor, createLocalFromEditor,
  newFileDialog, newFileName, closeNewFileDialog, confirmNewFile,
  renameDialog, renameName, closeRenameDialog, confirmRename,
} from '../../composables/usePluginEditor'

const emit = defineEmits(['toast'])

const props = defineProps({
  currentDevice: { type: Object, default: null },
})

const settingsOpen = ref(false)
const consoleOpen = ref(false)
const runOpen = ref(false)

// 编辑器主题
const editorTheme = ref(localStorage.getItem('espai_editor_theme') || 'dark')
const editorThemes = THEMES

function setEditorTheme(id) {
  editorTheme.value = id
  localStorage.setItem('espai_editor_theme', id)
}

// Esc：先关设置抽屉，再退全屏
function onKeydown(e) {
  if (e.key !== 'Escape') return
  if (settingsOpen.value) { settingsOpen.value = false; return }
  if (editorFullscreen.value) editorFullscreen.value = false
}

// Ctrl/Cmd+S：local-edit → 保存并热重载；edit → 保存新版本；
// create → 填了 ID/名称才创建，否则只存草稿（不打断思路）
function onSaveShortcut(e) {
  if (!(e.ctrlKey || e.metaKey) || e.key.toLowerCase() !== 's') return
  if (!codeEditor.value.show) return
  e.preventDefault()
  if (codeEditor.value.mode === 'local-edit') { saveLocalFromEditor(); return }
  if (codeEditor.value.mode === 'edit') { savePluginCode(); return }
  const ce = codeEditor.value
  if (ce.slug.trim() && ce.name.trim()) {
    createLocalFromEditor()
    return
  }
  // 未填 ID/名称：草稿已自动保存，弹出设置抽屉引导补全
  queueDraftSave()
  settingsOpen.value = true
  emit('toast', '请先在「插件设置」中填写插件 ID 与名称，再创建')
}

onMounted(() => {
  window.addEventListener('keydown', onKeydown)
  window.addEventListener('keydown', onSaveShortcut)
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKeydown)
  window.removeEventListener('keydown', onSaveShortcut)
})
</script>

<style scoped>
/* ===== 三栏 IDE 布局 ===== */
.editor-page {
  position: relative;
  display: flex; flex-direction: column;
  height: calc(100vh - 24px);
  min-height: 420px;
  background: linear-gradient(160deg, #f6fafc 0%, #e9f1f5 55%, #eef6f2 100%);
  border-radius: var(--radius-lg, 18px);
  overflow: hidden;
  border: 1px solid var(--glass-border-soft, rgba(255,255,255,0.45));
}
.editor-page.fullscreen {
  position: fixed; inset: 0; z-index: 200;
  height: 100vh; min-height: 0; border-radius: 0;
  padding: 12px;
  overflow: auto;
  animation: editorExpand 0.3s var(--ease, ease);
}
@keyframes editorExpand {
  from { transform: scale(0.97); opacity: 0.5; }
  to { transform: scale(1); opacity: 1; }
}

/* 顶栏 */
.editor-topbar {
  display: flex; align-items: center; gap: 14px;
  padding: 9px 14px; flex-shrink: 0;
  border-bottom: 1px solid var(--glass-border-soft, rgba(255,255,255,0.45));
  background: rgba(255,255,255,0.55);
}
.editor-back {
  display: flex; align-items: center; gap: 6px;
  padding: 7px 14px; font-size: 13px; font-weight: 600;
  border: 1px solid var(--glass-border, rgba(0,0,0,0.08)); border-radius: var(--radius-sm, 12px);
  background: rgba(255,255,255,0.6); color: var(--text-sub, #5b6b78); cursor: pointer;
  transition: all 0.2s var(--ease, ease);
}
.editor-back:hover { border-color: var(--mint-border); color: var(--mint-deep, #059669); background: var(--mint-softer); }
.editor-title-wrap { display: flex; align-items: center; gap: 10px; flex: 1; min-width: 0; }
.editor-title { font-size: 17px; font-weight: 700; margin: 0; white-space: nowrap; }
.editor-slug {
  font-family: monospace; font-size: 12px; padding: 3px 10px;
  border-radius: 999px; background: rgba(255,255,255,0.6);
  border: 1px solid var(--glass-border, rgba(0,0,0,0.08)); color: var(--text-sub, #5b6b78);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 260px;
}
.editor-mode {
  font-size: 11px; font-weight: 600; padding: 3px 10px; border-radius: 999px;
  background: var(--grad-mint, linear-gradient(135deg, #34d399, #10b981));
  color: #fff; box-shadow: 0 4px 12px rgba(16,185,129,0.28); flex-shrink: 0;
}
.editor-mode.local { background: linear-gradient(135deg, #6366f1, #8b5cf6); box-shadow: 0 4px 12px rgba(99,102,241,0.3); }
.editor-mode.edit { background: linear-gradient(135deg, #38bdf8, #6366f1); box-shadow: 0 4px 12px rgba(56,189,248,0.3); }
.editor-dirty-badge { font-size: 11px; font-weight: 700; color: var(--amber, #f59e0b); white-space: nowrap; }
.editor-topbar-right { display: flex; align-items: center; gap: 8px; flex-shrink: 0; }
.tb-icon-btn {
  display: flex; align-items: center; justify-content: center;
  width: 32px; height: 32px;
  border: 1px solid var(--glass-border, rgba(0,0,0,0.08)); border-radius: 8px;
  background: rgba(255,255,255,0.6); color: var(--text-sub, #5b6b78);
  cursor: pointer; transition: all 0.2s var(--ease, ease);
}
.tb-icon-btn:hover { border-color: var(--mint-border); color: var(--mint-deep, #059669); background: var(--mint-softer); }
.tb-icon-btn.active { border-color: var(--mint); color: var(--mint-deep, #059669); background: var(--mint-soft); }
.theme-switcher { display: flex; gap: 2px; padding: 3px; background: rgba(255,255,255,0.6); border: 1px solid var(--glass-border, rgba(0,0,0,0.08)); border-radius: 8px; }
.theme-btn { border: none; background: transparent; cursor: pointer; width: 28px; height: 28px; border-radius: 6px; font-size: 14px; display: flex; align-items: center; justify-content: center; transition: all 0.2s; opacity: 0.5; }
.theme-btn:hover { opacity: 0.8; }
.theme-btn.active { background: rgba(255,255,255,0.7); opacity: 1; box-shadow: 0 1px 3px rgba(0,0,0,0.08); }

/* 三栏主体 */
.editor-main { display: flex; flex: 1; min-height: 0; }
.editor-center {
  flex: 1; min-width: 0;
  display: flex; flex-direction: column;
}

/* 打开的文件标签 */
.open-tabs {
  display: flex; gap: 2px; padding: 6px 10px 0; flex-shrink: 0;
  overflow-x: auto; align-items: flex-end;
  border-bottom: 1px solid var(--glass-border-soft, rgba(0,0,0,0.06));
}
.open-tab {
  display: flex; align-items: center; gap: 6px;
  padding: 7px 12px; font-size: 12px; font-weight: 500;
  border: 1px solid transparent; border-bottom: none;
  border-radius: 10px 10px 0 0;
  background: transparent; color: var(--text-sub, #5b6b78);
  cursor: pointer; white-space: nowrap; transition: all 0.15s var(--ease, ease);
}
.open-tab:hover { background: var(--mint-softer); }
.open-tab.active {
  background: rgba(255,255,255,0.85); color: var(--mint-deep, #059669); font-weight: 600;
  border-color: var(--glass-border-soft, rgba(0,0,0,0.06));
}
.open-tab-name { max-width: 160px; overflow: hidden; text-overflow: ellipsis; }
.open-tab-dirty { width: 7px; height: 7px; border-radius: 50%; background: var(--amber, #f59e0b); flex-shrink: 0; }
.open-tab-close {
  display: inline-flex; align-items: center; justify-content: center;
  width: 15px; height: 15px; border-radius: 50%;
  font-size: 12px; line-height: 1; color: var(--text-dim, #8fa0ad);
  transition: all 0.15s;
}
.open-tab-close:hover { background: var(--danger-soft, rgba(239,68,68,0.1)); color: var(--danger, #ef4444); }
.open-tabs-empty { font-size: 12px; color: var(--text-dim, #8fa0ad); padding: 8px 4px; }

/* Monaco 容器：纯色底，无玻璃干扰 */
.editor-body {
  flex: 1; min-height: 0; margin: 0 10px 10px;
  border: 1px solid var(--glass-border-soft, rgba(0,0,0,0.06));
  border-radius: var(--radius-md, 14px);
  overflow: hidden;
  background: #fbfdfe;
}
.editor-loading { display: flex; flex-direction: column; align-items: center; gap: 12px; height: 100%; color: var(--text-sub, #5b6b78); justify-content: center; }
.editor-nofile { display: flex; align-items: center; justify-content: center; height: 100%; color: var(--text-dim, #8fa0ad); font-size: 13px; }
.spinner { width: 28px; height: 28px; border: 3px solid rgba(16,185,129,0.15); border-top-color: var(--mint, #10b981); border-radius: 50%; animation: spin 0.8s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }

/* 确认/新建文件弹窗复用全局样式（developer.css 的 confirm-*），此处仅弹窗容器层级 */
.confirm-mask { z-index: 320; }

/* ===== 运行日志弹窗 ===== */
.console-mask {
  position: fixed; inset: 0; z-index: 310;
  background: rgba(15, 23, 42, 0.4); backdrop-filter: blur(8px);
  display: flex; align-items: center; justify-content: center;
}
.console-panel {
  width: min(920px, 94vw); height: 72vh;
  border-radius: var(--radius-lg, 18px); overflow: hidden;
  box-shadow: 0 24px 64px rgba(23, 52, 74, 0.25);
  border: 1px solid var(--glass-border-soft, rgba(255,255,255,0.45));
  display: flex; flex-direction: column;
}

/* 运行测试按钮（主操作） */
.tb-run-btn {
  display: flex; align-items: center; gap: 5px;
  padding: 6px 16px; font-size: 12px; font-weight: 700;
  border: none; border-radius: 8px; cursor: pointer;
  background: var(--grad-mint, linear-gradient(135deg, #34d399, #10b981));
  color: #fff; box-shadow: 0 4px 12px rgba(16,185,129,0.28);
  transition: all 0.2s var(--ease, ease); flex-shrink: 0;
}
.tb-run-btn:hover:not(:disabled) { filter: brightness(1.06); transform: translateY(-1px); }
.tb-run-btn:disabled { opacity: 0.5; cursor: not-allowed; }

/* ===== 响应式 ===== */
@media (max-width: 768px) {
  .editor-page { height: auto; min-height: 0; }
  .editor-main { flex-direction: column; }
  .ed-sidebar, .editor-center { min-height: 0; }
  .editor-workbench { min-height: 420px; }
  .editor-title-wrap { flex-wrap: wrap; }
  .editor-slug { max-width: 100%; }
  .editor-page.fullscreen { padding: 8px; }
}
</style>

