// 全屏插件代码编辑器（模块级单例）
// 状态与保存逻辑；UI 见 components/developer/PluginEditor.vue
import { ref, computed, watch } from 'vue'
import { api } from '../api'
import { toast } from './useToastBridge'
import { showConfirm } from './useConfirm'
import { loadMyPlugins } from './useDeveloper'
import { bumpVersion, loadLocalInstalled } from './useLocalPlugins'
import {
  TEMPLATE_PLUGIN, templateManifest, TEMPLATE_FRONTEND, ALL_PERMS,
} from '../utils/pluginTemplates'

export const codeEditor = ref({
  show: false,
  mode: 'create',          // 'create' | 'edit'（已发布） | 'local-edit'（本地）
  slug: '',
  name: '',
  description: '',
  version: '1.0.0',
  permissions: [],
  category: 'general',
  tags: [],
  changelog: '',
  files: [],               // [{ name, content, binary? }]
  activeFile: 'plugin.py',
  loading: false,
  saving: false,           // false | 'market' | 'local'
})

export const editorFullscreen = ref(false)

// 插件图标：dataURL 预览（未上传为空，商店显示首字母）
export const iconPreview = ref('')

// ===== 打开的文件标签 与 脏标记 =====
export const openedTabs = ref([])          // 已打开文件的标签（可关闭，与文件本身无关）
export const dirtyNames = ref(new Set())   // 有未保存修改的文件名集合

let savedSnapshots = {}                    // 上次快照（name -> content，二进制为 null）
let savedNames = new Set()

export function isDirty(name) { return dirtyNames.value.has(name) }
export function hasDirty() { return dirtyNames.value.size > 0 }

// 快照当前全部文件作为"已保存"基线
function snapshotAll() {
  savedSnapshots = {}
  savedNames = new Set()
  for (const f of codeEditor.value.files) {
    savedSnapshots[f.name] = f.binary ? null : f.content
    savedNames.add(f.name)
  }
  dirtyNames.value = new Set()
}

// 深度监听 files：内容修改 / 新增 / 删除 都会标记脏
watch(() => codeEditor.value.files, (files) => {
  const current = new Set(files.map(f => f.name))
  const next = new Set(dirtyNames.value)
  for (const f of files) {
    if (f.binary) continue
    const snap = savedSnapshots[f.name]
    if (snap === undefined || f.content !== snap) next.add(f.name)
    else next.delete(f.name)
  }
  // 已删除的文件也视为未保存的变更
  for (const name of savedNames) {
    if (!current.has(name)) next.add(name)
  }
  dirtyNames.value = next
  queueDraftSave()
}, { deep: true })

// ===== 草稿自动保存（localStorage，防误关/刷新丢代码）=====
let _draftTimer = null

function draftKey() {
  const ce = codeEditor.value
  return `espai_plugin_draft_${ce.mode}_${ce.slug || 'new'}`
}

function saveDraft() {
  if (!codeEditor.value.show) return
  try {
    localStorage.setItem(draftKey(), JSON.stringify({
      files: codeEditor.value.files,
      savedAt: Date.now(),
    }))
  } catch { /* 存储异常静默 */ }
}

export function queueDraftSave() {
  if (_draftTimer) clearTimeout(_draftTimer)
  _draftTimer = setTimeout(saveDraft, 600)
}

function readDraft() {
  try {
    const raw = localStorage.getItem(draftKey())
    return raw ? JSON.parse(raw) : null
  } catch { return null }
}

export function clearDraft() {
  try { localStorage.removeItem(draftKey()) } catch {}
}

// 打开编辑器后检查草稿：与已加载内容有差异时询问是否恢复
export async function maybeOfferDraftRestore() {
  const draft = readDraft()
  if (!draft || !Array.isArray(draft.files) || !draft.files.length) return
  const differs = draft.files.some(df => {
    const cur = getFile(df.name)
    return !cur || cur.content !== df.content
  }) || codeEditor.value.files.length !== draft.files.length
  if (!differs) return
  const ok = await showConfirm({
    title: '发现未保存的草稿',
    message: `检测到 ${new Date(draft.savedAt).toLocaleString()} 自动保存的草稿，是否恢复？`,
    confirmText: '恢复草稿',
    cancelText: '放弃草稿',
    danger: false,
  })
  if (ok) {
    codeEditor.value.files = draft.files
    openedTabs.value = draft.files.filter(f => !f.binary).map(f => f.name).slice(0, 8)
    codeEditor.value.activeFile = openedTabs.value[0] || 'plugin.py'
    syncIconPreviewFromFiles()
    toast('草稿已恢复（保存后自动清除）')
  } else {
    clearDraft()
  }
}

// 侧栏点击打开文件（加入标签）
export function openFile(name) {
  const f = getFile(name)
  if (!f || f.binary) return
  codeEditor.value.activeFile = name
  if (!openedTabs.value.includes(name)) openedTabs.value.push(name)
}

// 关闭标签（不删除文件本身）
export function closeTab(name) {
  openedTabs.value = openedTabs.value.filter(n => n !== name)
  if (codeEditor.value.activeFile === name) {
    codeEditor.value.activeFile =
      openedTabs.value[openedTabs.value.length - 1] ||
      editableFiles.value[0]?.name || 'plugin.py'
  }
}

// 当前文件行数（状态栏显示）
export const activeFileLines = computed(() => {
  const content = activeFileEntry.value?.content || ''
  return content ? content.split('\n').length : 0
})

// 编辑器打开/关闭时通知外层（App 据此隐藏导航栏）
const _editorWatchers = []
export function onEditorShowChange(fn) {
  _editorWatchers.push(fn)
  // 若已处于打开状态，立即同步一次
  if (codeEditor.value.show) fn(true)
}

watch(() => codeEditor.value.show, (v) => {
  _editorWatchers.forEach(fn => fn(v))
})

export function toggleFullscreen() {
  editorFullscreen.value = !editorFullscreen.value
}

export async function closeEditor() {
  if (hasDirty()) {
    const ok = await showConfirm({
      title: '有未保存的修改',
      message: '当前插件存在未保存的修改，关闭后将丢失。确定关闭吗？',
      confirmText: '丢弃并关闭',
      cancelText: '继续编辑',
      danger: true,
    })
    if (!ok) return
  }
  codeEditor.value.show = false
  editorFullscreen.value = false
}

// ===== 权限多选 =====
export const permPanelOpen = ref(false)

export function togglePerm(id) {
  const perms = codeEditor.value.permissions
  const idx = perms.indexOf(id)
  if (idx >= 0) {
    perms.splice(idx, 1)
  } else {
    perms.push(id)
  }
}

export function permLabels(ids) {
  return ids.map(id => ALL_PERMS.find(p => p.id === id)?.label || id).join(', ')
}

export function togglePermPanel() {
  permPanelOpen.value = !permPanelOpen.value
}

export function closePermPanel() {
  permPanelOpen.value = false
}

// ===== 文件管理 =====
export const activeFileEntry = computed(() =>
  codeEditor.value.files.find(f => f.name === codeEditor.value.activeFile) || null
)

export const editableFiles = computed(() =>
  codeEditor.value.files.filter(f => !f.binary)
)

export function getFile(name) {
  return codeEditor.value.files.find(f => f.name === name) || null
}

export function isCoreFile(name) {
  return name === 'plugin.py' || name === 'manifest.json'
}

// 文件语言推断
export function fileLang(name) {
  const ext = (name.split('.').pop() || '').toLowerCase()
  const map = {
    py: 'python', json: 'json', md: 'markdown', txt: 'plaintext',
    js: 'javascript', ts: 'typescript', html: 'html', css: 'css',
    yaml: 'yaml', yml: 'yaml', sh: 'shell', toml: 'ini', ini: 'ini',
  }
  return map[ext] || 'plaintext'
}

// 文件标签图标
export function fileIcon(name) {
  const ext = (name.split('.').pop() || '').toLowerCase()
  const map = {
    py:    { label: 'PY',   cls: 'py' },
    json:  { label: '{}',   cls: 'json' },
    html:  { label: '<>',   cls: 'html' },
    css:   { label: '#',    cls: 'css' },
    js:    { label: 'JS',   cls: 'js' },
    ts:    { label: 'TS',   cls: 'ts' },
    md:    { label: 'MD',   cls: 'md' },
    yaml:  { label: 'YM',   cls: 'yaml' },
    yml:   { label: 'YM',   cls: 'yaml' },
    sh:    { label: '>_',   cls: 'sh' },
    toml:  { label: 'CF',   cls: 'toml' },
    ini:   { label: 'CF',   cls: 'toml' },
    txt:   { label: 'T',    cls: 'txt' },
  }
  return map[ext] || { label: '?', cls: 'unknown' }
}

// ===== 图标上传 =====
function updateManifestIcon(iconName) {
  const mf = getFile('manifest.json')
  if (!mf) return
  try {
    const obj = JSON.parse(mf.content)
    if (iconName) obj.icon = iconName
    else delete obj.icon
    mf.content = JSON.stringify(obj, null, 2)
  } catch { /* manifest 格式有误时不覆盖，让用户自行修复 */ }
}

export function onIconSelect(e) {
  const file = e.target.files && e.target.files[0]
  e.target.value = ''
  if (!file) return
  if (!/^image\/(png|jpe?g)$/i.test(file.type)) { toast('图标仅支持 png/jpg 格式'); return }
  if (file.size > 2 * 1024 * 1024) { toast('图标大小不能超过 2MB'); return }
  const reader = new FileReader()
  reader.onload = () => {
    const dataUrl = reader.result
    const base64 = String(dataUrl).split(',')[1] || ''
    const ext = (file.name.split('.').pop() || 'png').toLowerCase().replace(/[^a-z0-9]/g, '')
    const iconName = `icon.${ext || 'png'}`
    // 替换旧的图标文件
    codeEditor.value.files = codeEditor.value.files.filter(f => !f.binary)
    codeEditor.value.files.push({ name: iconName, content: base64, binary: true })
    iconPreview.value = dataUrl
    updateManifestIcon(iconName)
    dirtyNames.value.add(iconName)
    toast('图标已添加')
  }
  reader.readAsDataURL(file)
}

export function removeIcon() {
  codeEditor.value.files = codeEditor.value.files.filter(f => !f.binary)
  iconPreview.value = ''
  updateManifestIcon('')
  dirtyNames.value.add('__icon_removed__')
}

// 从 files 中的二进制图标生成预览（打开已有图标的插件时显示）
export function syncIconPreviewFromFiles() {
  const bin = codeEditor.value.files.find(f => f.binary)
  if (bin) {
    const ext = (bin.name.split('.').pop() || 'png').toLowerCase()
    const mime = ext === 'jpg' ? 'image/jpeg' : `image/${ext}`
    iconPreview.value = `data:${mime};base64,${bin.content}`
  } else {
    iconPreview.value = ''
  }
}

// ===== 新建文件 / 新建文件夹 =====
export const newFileName = ref('')
export const newFileDialog = ref({ show: false, mode: 'file' })  // mode: 'file' | 'folder'

// 目录折叠状态（默认全部收起；Set 里的目录为展开）
export const expandedDirs = ref(new Set())

export function isDirExpanded(dir) { return expandedDirs.value.has(dir) }

export function toggleDir(dir) {
  const s = new Set(expandedDirs.value)
  if (s.has(dir)) s.delete(dir)
  else s.add(dir)
  expandedDirs.value = s
}

export function ensureDirExpanded(dir) {
  if (!dir) return
  const s = new Set(expandedDirs.value)
  s.add(dir)
  expandedDirs.value = s
}

export function openNewFileDialog(mode = 'file') {
  newFileName.value = ''
  newFileDialog.value = { show: true, mode }
}

export function closeNewFileDialog() {
  newFileDialog.value = { show: false, mode: 'file' }
}

export function confirmNewFile() {
  const isFolder = newFileDialog.value.mode === 'folder'
  const raw = (newFileName.value || '').trim().replace(/^\/+|\/+$/g, '')
  if (!raw) { toast(isFolder ? '请输入文件夹名' : '请输入文件名'); return }
  if (isFolder) return confirmNewFolder(raw)

  // 新建文件（路径中的目录隐式创建，如 utils/helpers.py）
  if (getFile(raw)) { toast('文件已存在: ' + raw); return }
  codeEditor.value.files.push({ name: raw, content: '' })
  ensureDirExpanded(raw.includes('/') ? raw.split('/').slice(0, -1).join('/') : '')
  openedTabs.value.push(raw)
  codeEditor.value.activeFile = raw
  newFileDialog.value = { show: false, mode: 'file' }
}

function confirmNewFolder(dir) {
  // 名称被已有文件占用
  if (getFile(dir)) { toast('名称已被文件占用: ' + dir); return }
  // 该文件夹已存在（其下有文件）
  if (codeEditor.value.files.some(f => f.name.startsWith(dir + '/'))) {
    toast('文件夹已存在: ' + dir)
    return
  }
  // 通过 .gitkeep 占位文件保留空文件夹
  const keep = `${dir}/.gitkeep`
  codeEditor.value.files.push({ name: keep, content: '' })
  dirtyNames.value.add(keep)
  ensureDirExpanded(dir)
  newFileDialog.value = { show: false, mode: 'file' }
}

// ===== 重命名（文件 / 文件夹） =====
export const renameDialog = ref({ show: false, oldPath: '', isDir: false })
export const renameName = ref('')

export function openRenameFile(path) {
  renameDialog.value = { show: true, oldPath: path, isDir: false }
  renameName.value = path
}

export function openRenameFolder(dir) {
  renameDialog.value = { show: true, oldPath: dir, isDir: true }
  renameName.value = dir
}

export function closeRenameDialog() {
  renameDialog.value.show = false
}

export function confirmRename() {
  const { oldPath, isDir } = renameDialog.value
  const newName = (renameName.value || '').trim().replace(/^\/+|\/+$/g, '')
  if (!newName) { toast('请输入名称'); return }
  if (newName === oldPath) { renameDialog.value.show = false; return }

  if (isDir) {
    const prefix = oldPath + '/'
    const newPrefix = newName + '/'
    // 先做冲突检查
    for (const f of codeEditor.value.files) {
      if (f.name.startsWith(prefix)) {
        const nn = newPrefix + f.name.slice(prefix.length)
        if (getFile(nn)) { toast(`目标已存在: ${nn}`); return }
      }
    }
    for (const f of codeEditor.value.files) {
      if (f.name.startsWith(prefix)) f.name = newPrefix + f.name.slice(prefix.length)
    }
    openedTabs.value = openedTabs.value.map(n => n.startsWith(prefix) ? newPrefix + n.slice(prefix.length) : n)
    if (codeEditor.value.activeFile.startsWith(prefix)) {
      codeEditor.value.activeFile = newPrefix + codeEditor.value.activeFile.slice(prefix.length)
    }
    expandedDirs.value = new Set(
      [...expandedDirs.value].map(d => d === oldPath ? newName : (d.startsWith(prefix + '/') ? newPrefix + d.slice(prefix.length) : d))
    )
    renameDialog.value.show = false
    toast('文件夹已重命名')
  } else {
    if (getFile(newName)) { toast('目标文件名已存在'); return }
    const f = getFile(oldPath)
    if (!f) return
    f.name = newName
    openedTabs.value = openedTabs.value.map(n => n === oldPath ? newName : n)
    if (codeEditor.value.activeFile === oldPath) codeEditor.value.activeFile = newName
    renameDialog.value.show = false
  }
}

export function removeFile(name) {
  if (isCoreFile(name)) return
  showConfirm({
    title: '删除文件',
    message: `确定删除文件「${name}」吗？此操作不可恢复。`,
    confirmText: '确认删除',
    cancelText: '取消',
    danger: true,
  }).then(ok => {
    if (!ok) return
    codeEditor.value.files = codeEditor.value.files.filter(f => f.name !== name)
    openedTabs.value = openedTabs.value.filter(n => n !== name)
    if (codeEditor.value.activeFile === name) {
      const first = codeEditor.value.files[0]
      codeEditor.value.activeFile = first ? first.name : 'plugin.py'
    }
  })
}

// ===== 打开编辑器 =====
export function openCreateEditor() {
  iconPreview.value = ''
  codeEditor.value = {
    show: true,
    mode: 'create',
    slug: '',
    name: '',
    description: '',
    version: '1.0.0',
    permissions: [],
    category: 'general',
    tags: [],
    changelog: '',
    files: [
      { name: 'plugin.py', content: TEMPLATE_PLUGIN },
      { name: 'manifest.json', content: templateManifest('my_plugin', '我的插件', '插件描述', []) },
      { name: 'frontend/index.html', content: TEMPLATE_FRONTEND },
    ],
    activeFile: 'plugin.py',
    loading: false,
    saving: false,
  }
  openedTabs.value = ['plugin.py']
  snapshotAll()
  maybeOfferDraftRestore()
}

export async function openEditEditor(p) {
  iconPreview.value = ''
  codeEditor.value = {
    show: true,
    mode: 'edit',
    slug: p.slug,
    name: p.name,
    description: p.description || '',
    version: bumpVersion(p.latest_version),
    category: 'general',
    tags: [],
    changelog: '',
    files: [],
    activeFile: 'plugin.py',
    loading: true,
    saving: false,
  }
  const res = await api.devGetPluginSource(p.slug)
  codeEditor.value.loading = false
  if (res.status === 200 && res.data?.code === 0) {
    const d = res.data.data
    codeEditor.value.files = (d.files && d.files.length ? d.files : [
      { name: 'plugin.py', content: d.plugin_code || '' },
      { name: 'manifest.json', content: d.manifest_raw || '{}' },
    ])
    codeEditor.value.name = d.name || p.name
    syncIconPreviewFromFiles()
    seedPermissionsFromManifest()
    openedTabs.value = ['plugin.py']
    snapshotAll()
    maybeOfferDraftRestore()
  } else {
    toast(res.data?.message || '获取源码失败')
    codeEditor.value.show = false
  }
}

export async function openLocalEditEditor(p) {
  iconPreview.value = ''
  codeEditor.value = {
    show: true,
    mode: 'local-edit',
    slug: p.name,
    name: p.title || p.name,
    description: p.description || '',
    version: p.version || '1.0.0',
    category: 'general',
    tags: [],
    changelog: '',
    files: [],
    activeFile: 'plugin.py',
    loading: true,
    saving: false,
  }
  try {
    const res = await api.getLocalPluginSource(p.name)
    if (res.status === 200 && res.data?.code === 0) {
      const d = res.data.data || {}
      codeEditor.value.files = (d.files && d.files.length ? d.files : [
        { name: 'plugin.py', content: d.plugin_code || d.code || '' },
        { name: 'manifest.json', content: d.manifest_raw || d.manifest || '{}' },
      ])
      syncIconPreviewFromFiles()
      seedPermissionsFromManifest()
      openedTabs.value = ['plugin.py']
      snapshotAll()
      maybeOfferDraftRestore()
    } else {
      toast(res.data?.message || '获取源码失败')
      codeEditor.value.show = false
    }
  } catch (e) {
    toast('获取源码异常')
    codeEditor.value.show = false
  }
  codeEditor.value.loading = false
}

// ===== 保存 =====
// 从 files 中取 plugin.py / manifest.json 内容
function pluginCodeFromFiles() {
  return getFile('plugin.py')?.content || ''
}

function manifestRawFromFiles() {
  return getFile('manifest.json')?.content || '{}'
}

// 从 manifest.json 内容回填权限到编辑器状态（编辑/本地编辑模式）
function seedPermissionsFromManifest() {
  const mf = getFile('manifest.json')
  if (!mf) return
  try {
    const obj = JSON.parse(mf.content)
    codeEditor.value.permissions = Array.isArray(obj.permissions) ? obj.permissions : []
  } catch { /* manifest 格式有误时不覆盖 */ }
}

// 把版本/权限写回 manifest.json 文件内容（本地保存前调用，随文件一起提交）
function syncMetaToManifest() {
  const ce = codeEditor.value
  const mf = getFile('manifest.json')
  if (!mf) return
  try {
    const obj = JSON.parse(mf.content)
    if (ce.version) obj.version = ce.version
    if (Array.isArray(ce.permissions)) obj.permissions = ce.permissions
    mf.content = JSON.stringify(obj, null, 2)
  } catch { /* manifest 格式有误时不覆盖 */ }
}

function syncManifestFromForm() {
  const ce = codeEditor.value
  const mf = getFile('manifest.json')
  if (!mf) return
  try {
    const obj = JSON.parse(mf.content)
    obj.id = ce.slug.trim().toLowerCase()
    obj.name = ce.name.trim()
    obj.description = ce.description.trim()
    obj.version = ce.version || '1.0.0'
    obj.permissions = ce.permissions
    mf.content = JSON.stringify(obj, null, 2)
  } catch {
    // manifest 格式有误时不覆盖，让用户自行修复
  }
}

export async function savePluginCode() {
  const ce = codeEditor.value
  let manifest
  try {
    manifest = JSON.parse(manifestRawFromFiles())
  } catch {
    toast('manifest.json 格式错误，请检查 JSON 语法')
    return
  }
  if (!pluginCodeFromFiles().trim()) {
    toast('plugin.py 不能为空')
    return
  }

  ce.saving = 'market'
  if (ce.mode === 'create') {
    if (!ce.slug.trim() || !ce.name.trim()) {
      toast('请填写插件 ID 和名称')
      ce.saving = false
      return
    }
    manifest.id = ce.slug.trim().toLowerCase()
    manifest.name = ce.name.trim()
    manifest.version = ce.version || '1.0.0'
    manifest.description = ce.description || ''
    const res = await api.devCreatePlugin({
      slug: ce.slug.trim().toLowerCase(),
      name: ce.name.trim(),
      description: ce.description || '',
      version: ce.version || '1.0.0',
      category: manifest.category || 'general',
      tags: manifest.tags || [],
      plugin_code: pluginCodeFromFiles(),
      files: ce.files,
      changelog: ce.changelog || '',
    })
    ce.saving = false
    if (res.status === 200 && res.data?.code === 0) {
      toast('插件创建成功，已上架到市场')
      snapshotAll()
      clearDraft()
      closeEditor()
      await loadMyPlugins()
    } else {
      toast(res.data?.message || '创建失败')
    }
  } else {
    manifest.version = ce.version
    manifest.permissions = ce.permissions
    const res = await api.devUpdatePluginSource(ce.slug, {
      plugin_code: pluginCodeFromFiles(),
      files: ce.files,
      manifest: manifest,
      changelog: ce.changelog || '',
    })
    ce.saving = false
    if (res.status === 200 && res.data?.code === 0) {
      toast('新版本已保存并上架')
      snapshotAll()
      clearDraft()
      closeEditor()
      await loadMyPlugins()
    } else {
      toast(res.data?.message || '保存失败')
    }
  }
}

export async function saveLocalFromEditor() {
  const ce = codeEditor.value
  if (!pluginCodeFromFiles().trim()) {
    toast('plugin.py 不能为空')
    return
  }
  // 本地插件的权限/版本保存在 manifest.json 文件内容里，保存前同步
  syncMetaToManifest()
  ce.saving = 'local'
  const res = await api.updateLocalPluginSource(ce.slug, pluginCodeFromFiles(), ce.files)
  ce.saving = false
  if (res.status === 200 && res.data?.code === 0) {
    toast(res.data.message || '已保存到本地并热重载')
    snapshotAll()
    clearDraft()
  } else {
    toast(res.data?.message || '本地保存失败（需先安装插件）')
  }
}

export async function createLocalFromEditor() {
  const ce = codeEditor.value
  if (!ce.slug.trim() || !ce.name.trim()) {
    toast('请填写插件 ID 和名称')
    return
  }
  if (!pluginCodeFromFiles().trim()) {
    toast('plugin.py 不能为空')
    return
  }

  // 将表单字段同步到 manifest.json 文件内容，确保编辑器显示一致
  syncManifestFromForm()

  let manifest
  try {
    manifest = JSON.parse(manifestRawFromFiles())
  } catch {
    toast('manifest.json 格式错误，请检查 JSON 语法')
    return
  }
  ce.saving = 'local'
  const res = await api.createLocalPlugin({
    slug: ce.slug.trim().toLowerCase(),
    name: ce.name.trim(),
    description: ce.description || '',
    version: ce.version || '1.0.0',
    plugin_code: pluginCodeFromFiles(),
    files: ce.files,
    manifest: manifest,
  })
  ce.saving = false
  if (res.status === 200 && res.data?.code === 0) {
    toast(res.data.message || '插件已创建到本地，可前往已安装页面测试')
    snapshotAll()
    clearDraft()
    closeEditor()
    await loadLocalInstalled()
  } else {
    toast(res.data?.message || '创建失败')
  }
}
