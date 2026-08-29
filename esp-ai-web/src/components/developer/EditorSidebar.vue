<template>
  <aside class="ed-sidebar">
    <!-- 文件区 -->
    <div class="sb-section">
      <div class="sb-heading">
        <span>文件</span>
        <div class="sb-heading-actions">
          <button class="sb-add" title="新建文件夹" @click="openNewFileDialog('folder')">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
              <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>
            </svg>
          </button>
          <button class="sb-add" title="新建文件" @click="openNewFileDialog('file')">+</button>
        </div>
      </div>
      <div class="sb-tree">
        <template v-for="row in treeRows" :key="row.type === 'dir' ? row.label : row.full">
          <!-- 目录行：点击折叠/展开，悬停显示重命名 -->
          <div v-if="row.type === 'dir'" class="sb-row dir"
            :style="{ paddingLeft: 8 + row.depth * 14 + 'px' }"
            @click="toggleDir(row.label)">
            <svg class="sb-chevron" :class="{ expanded: isDirExpanded(row.label) }"
              width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
              <polyline points="9 18 15 12 9 6"/>
            </svg>
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
              <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>
            </svg>
            <span class="sb-row-label">{{ row.label }}</span>
            <span class="sb-row-rename" title="重命名文件夹" @click.stop="openRenameFolder(row.label)">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
                <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>
                <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>
              </svg>
            </span>
          </div>
          <!-- 文件行 -->
          <div v-else class="sb-row file"
            :class="{ active: codeEditor.activeFile === row.full }"
            :style="{ paddingLeft: 8 + row.depth * 14 + 18 + 'px' }"
            :title="row.full"
            @click="openFile(row.full)">
            <span class="ft-icon" :class="fileIcon(row.full).cls">{{ fileIcon(row.full).label }}</span>
            <span class="sb-row-label">{{ row.label }}</span>
            <span v-if="isDirty(row.full)" class="sb-dirty-dot" title="未保存"></span>
            <span class="sb-row-rename" title="重命名文件" @click.stop="openRenameFile(row.full)">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
                <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>
                <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>
              </svg>
            </span>
            <span v-if="!isCoreFile(row.full)" class="sb-row-remove" title="删除文件"
              @click.stop="removeFile(row.full)">×</span>
          </div>
        </template>
      </div>
    </div>

    <!-- 图标区 -->
    <div class="sb-section">
      <div class="sb-heading"><span>插件图标</span></div>
      <div class="sb-icon-area">
        <input ref="iconInput" type="file" accept="image/png,image/jpeg,image/jpg" class="icon-input" @change="onIconSelect" />
        <img v-if="iconPreview" :src="iconPreview" class="sb-icon-preview" @click="$refs.iconInput.click()" @error="iconPreview = ''" />
        <button v-else class="sb-icon-btn" @click="$refs.iconInput.click()">上传图标</button>
        <button v-if="iconPreview" class="sb-icon-remove" @click="removeIcon">移除</button>
      </div>
      <p class="sb-icon-hint">png/jpg，≤2MB；未上传时商店显示首字母</p>
    </div>

    <!-- 设置入口 -->
    <div class="sb-section sb-bottom">
      <button class="sb-settings-btn" @click="$emit('open-settings')">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <circle cx="12" cy="12" r="3"/>
          <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/>
        </svg>
        插件设置
        <span v-if="settingsDirty" class="sb-dirty-dot" title="设置有修改"></span>
      </button>
    </div>
  </aside>
</template>

<script setup>
import { computed } from 'vue'
import {
  codeEditor,
  editableFiles,
  fileIcon,
  iconPreview,
  isCoreFile,
  isDirExpanded,
  isDirty,
  onIconSelect,
  openFile,
  openNewFileDialog,
  openRenameFile,
  openRenameFolder,
  removeFile,
  removeIcon,
  toggleDir,
} from '../../composables/usePluginEditor'

defineProps({ settingsDirty: { type: Boolean, default: false } })
defineEmits(['open-settings'])

// 文件排序权重：.py → .json → 其他
function fileRank(name) {
  if (name.endsWith('.py')) return 1
  if (name.endsWith('.json')) return 2
  return 3
}

// 文件树：文件夹最上面（字母序），随后 .py → .json → 其他（各自字母序）；
// 目录按折叠状态过滤（默认收起）
const treeRows = computed(() => {
  const files = [...editableFiles.value]
  const dirs = new Map()
  for (const f of files) {
    const parts = f.name.split('/')
    const dir = parts.length > 1 ? parts.slice(0, -1).join('/') : ''
    if (!dirs.has(dir)) dirs.set(dir, [])
    dirs.get(dir).push(f)
  }
  // 组内排序：按类型权重 + 名称
  for (const list of dirs.values()) {
    list.sort((a, b) => {
      const la = a.name.split('/').pop()
      const lb = b.name.split('/').pop()
      const ra = fileRank(a.name), rb = fileRank(b.name)
      if (ra !== rb) return ra - rb
      return la.localeCompare(lb)
    })
  }
  // 文件夹（非根）字母序在前，根目录散文件最后
  const dirKeys = [...dirs.keys()].sort((a, b) => {
    if (a === '') return b === '' ? 0 : 1
    if (b === '') return -1
    return a.localeCompare(b)
  })

  const rows = []
  for (const dir of dirKeys) {
    if (dir) {
      rows.push({ type: 'dir', label: dir, depth: 0 })
      if (!isDirExpanded(dir)) continue  // 默认折叠
    }
    for (const f of dirs.get(dir)) {
      rows.push({
        type: 'file', label: f.name.split('/').pop(), full: f.name,
        depth: dir ? 1 : 0,
      })
    }
  }
  return rows
})
</script>

<style scoped>
.ed-sidebar {
  width: 220px; flex-shrink: 0;
  display: flex; flex-direction: column;
  border-right: 1px solid var(--glass-border-soft, rgba(255,255,255,0.45));
  background: rgba(255,255,255,0.35);
  overflow-y: auto;
}
.sb-section { padding: 10px 8px; border-bottom: 1px solid var(--glass-border-soft, rgba(255,255,255,0.45)); }
.sb-section:last-child { border-bottom: none; }
.sb-bottom { margin-top: auto; }
.sb-heading {
  display: flex; align-items: center; justify-content: space-between;
  font-size: 11px; font-weight: 700; color: var(--text-dim);
  text-transform: uppercase; letter-spacing: 0.5px;
  padding: 0 6px 6px;
}
.sb-heading-actions { display: flex; gap: 4px; }
.sb-add {
  display: flex; align-items: center; justify-content: center;
  width: 20px; height: 20px; border: 1px dashed var(--mint-border); border-radius: 6px;
  background: transparent; color: var(--mint); cursor: pointer;
  transition: all 0.2s var(--ease);
}
.sb-add:hover { background: var(--mint-softer); }
.sb-tree { display: flex; flex-direction: column; gap: 1px; }
.sb-row {
  display: flex; align-items: center; gap: 6px;
  padding: 5px 8px; border-radius: 8px;
  font-size: 12.5px; color: var(--text-sub); cursor: pointer;
  transition: background 0.15s var(--ease);
  min-height: 26px;
}
.sb-row.dir { cursor: pointer; color: var(--text-main); font-weight: 600; user-select: none; }
.sb-row.dir:hover { background: var(--mint-softer); }
.sb-row.file:hover { background: var(--mint-softer); color: var(--text-main); }
.sb-row.file.active { background: var(--mint-soft); color: var(--mint-deep); font-weight: 600; }
.sb-chevron { transition: transform 0.15s var(--ease); flex-shrink: 0; opacity: 0.6; }
.sb-chevron.expanded { transform: rotate(90deg); }
.sb-row-label { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.sb-dirty-dot {
  width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0;
  background: var(--amber, #f59e0b);
}
.sb-row-rename, .sb-row-remove {
  display: none; align-items: center; justify-content: center;
  width: 18px; height: 18px; border-radius: 5px;
  color: var(--text-dim); flex-shrink: 0;
  transition: all 0.15s var(--ease);
}
.sb-row.file:hover .sb-row-rename,
.sb-row.file:hover .sb-row-remove,
.sb-row.dir:hover .sb-row-rename { display: inline-flex; }
.sb-row-rename:hover { background: var(--mint-soft); color: var(--mint-deep); }
.sb-row-remove:hover { background: var(--danger-soft); color: var(--danger); }
.ft-icon { font-size: 9px; font-weight: 700; padding: 1px 4px; border-radius: 4px; flex-shrink: 0; }
.ft-icon.py { background: var(--mint-soft); color: var(--mint-deep); }
.ft-icon.json { background: rgba(245,158,11,0.14); color: #d97706; }
.ft-icon.html { background: rgba(239,68,68,0.12); color: #dc2626; }
.ft-icon.css { background: rgba(99,102,241,0.12); color: #4f46e5; }
.ft-icon.js { background: rgba(234,179,8,0.14); color: #ca8a04; }
.ft-icon.md { background: rgba(107,114,128,0.12); color: #4b5563; }
.ft-icon.unknown { background: rgba(107,114,128,0.08); color: #6b7280; }

.sb-icon-area { display: flex; align-items: center; gap: 8px; padding: 0 6px; }
.icon-input { display: none; }
.sb-icon-btn {
  padding: 6px 12px; font-size: 12px; font-weight: 500;
  color: var(--mint); background: transparent; border: 1px dashed var(--mint-border);
  border-radius: 8px; cursor: pointer; transition: all 0.2s var(--ease);
}
.sb-icon-btn:hover { background: var(--mint-softer); }
.sb-icon-preview {
  width: 34px; height: 34px; border-radius: 8px; object-fit: cover;
  cursor: pointer; border: 1px solid var(--mint-border);
}
.sb-icon-remove {
  padding: 3px 8px; font-size: 11px; border: none; border-radius: 6px;
  background: transparent; color: var(--danger); cursor: pointer;
}
.sb-icon-remove:hover { background: var(--danger-soft); }
.sb-icon-hint { font-size: 11px; color: var(--text-dim); margin: 6px 6px 0; line-height: 1.5; }

.sb-settings-btn {
  width: 100%; display: flex; align-items: center; gap: 8px;
  padding: 9px 10px; font-size: 13px; font-weight: 500;
  border: 1px solid var(--glass-border); border-radius: 8px;
  background: var(--glass-bg-strong, rgba(255,255,255,0.6)); color: var(--text-main);
  cursor: pointer; transition: all 0.2s var(--ease);
}
.sb-settings-btn:hover { border-color: var(--mint-border); color: var(--mint-deep); background: var(--mint-softer); }
</style>
