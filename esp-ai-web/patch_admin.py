import io

p = 'src/views/AdminView.vue'
s = io.open(p, encoding='utf-8').read()
n = 0

# 1. 侧边栏导航：市场管理后加「固件管理」
old = '''        <button class="nav-item" :class="{ active: section === 'system' }" @click="section = 'system'">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="3" width="20" height="14" rx="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg>
          <span>系统运维</span>
        </button>'''
new = '''        <button class="nav-item" :class="{ active: section === 'firmware' }" @click="section = 'firmware'">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="3" width="20" height="14" rx="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg>
          <span>固件管理</span>
        </button>
        <button class="nav-item" :class="{ active: section === 'system' }" @click="section = 'system'">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="3" width="20" height="14" rx="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg>
          <span>系统运维</span>
        </button>'''
assert old in s, 'nav'
s = s.replace(old, new, 1); n += 1

# 2. 固件管理 section（插在系统运维 section 前）
old = '''        <!-- 系统运维 -->
        <section v-else-if="section === 'system'" class="admin-section">'''
new = '''        <!-- 固件管理 -->
        <section v-else-if="section === 'firmware'" class="admin-section">
          <div class="action-bar">
            <div class="action-info">
              <p class="action-title">固件上传</p>
              <p class="action-sub">上传固件并登记 bin_id，上传后自动设为「启用中」，作为设备 OTA 自检的比对目标</p>
            </div>
          </div>
          <div class="table-card" style="margin-bottom:14px">
            <div class="modal-body" style="display:flex;gap:12px;align-items:center;flex-wrap:wrap;padding:16px 20px">
              <label class="btn btn-ghost btn-sm" style="cursor:pointer">
                选择固件文件（.bin）
                <input type="file" accept=".bin,.elf,.hex" hidden @change="onFirmwareFileChange" />
              </label>
              <span class="cell-sub" style="min-width:140px">{{ fwFile ? fwFile.name : '未选择文件' }}</span>
              <input class="input input-sm" v-model="fwBinId" placeholder="固件 bin_id（必填）" style="width:220px" />
              <input class="input input-sm" v-model="fwVersion" placeholder="版本号（可选）" style="width:140px" />
              <button class="btn btn-mint btn-sm" :disabled="!fwFile || uploadingFw" @click="uploadFirmware">
                {{ uploadingFw ? '上传中…' : '上传固件' }}
              </button>
            </div>
          </div>

          <div class="table-card">
            <div class="table-head">
              <div>
                <h3 class="table-title">固件列表</h3>
                <p class="table-sub">「启用中」的固件作为设备 OTA 自检的比对目标；设备检测到 bin_id 或版本不同即自动升级</p>
              </div>
              <button class="btn btn-ghost" :disabled="loadingFirmwares" @click="loadFirmwares">刷新</button>
            </div>
            <div v-if="loadingFirmwares" class="table-empty">加载中…</div>
            <div v-else-if="!firmwares.length" class="table-empty">暂无固件，请先上传</div>
            <div v-else class="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>固件</th>
                    <th>bin_id</th>
                    <th>版本</th>
                    <th>大小</th>
                    <th>上传者</th>
                    <th>上传时间</th>
                    <th>状态</th>
                    <th>操作</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="f in firmwares" :key="f.filename">
                    <td data-label="固件"><strong>{{ f.filename }}</strong></td>
                    <td data-label="bin_id"><span class="cell-sub">{{ f.bin_id || '—' }}</span></td>
                    <td data-label="版本">{{ f.version || '—' }}</td>
                    <td data-label="大小">{{ formatSize(f.size) }}</td>
                    <td data-label="上传者">{{ f.uploaded_by || '—' }}</td>
                    <td data-label="上传时间" class="cell-muted">{{ formatDate(f.uploaded_at || f.created_time) }}</td>
                    <td data-label="状态">
                      <span class="badge" :class="f.active ? 'badge-mint' : 'badge-sub'">{{ f.active ? '启用中' : '备用' }}</span>
                    </td>
                    <td data-label="操作">
                      <div class="row-actions">
                        <button v-if="!f.active" class="btn btn-ghost btn-xs" @click="setFirmwareActive(f)">设为启用</button>
                        <a class="btn btn-ghost btn-xs" :href="f.download_url" target="_blank">下载</a>
                        <button class="btn btn-danger btn-xs" @click="deleteFirmware(f)">删除</button>
                      </div>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </section>

        <!-- 系统运维 -->
        <section v-else-if="section === 'system'" class="admin-section">'''
assert old in s, 'section'
s = s.replace(old, new, 1); n += 1

# 3. 标题映射
old = '''  ws_monitor: '实时查看 WebSocket 连接状态','''
new = '''  firmware: '固件上传与版本管理',
  ws_monitor: '实时查看 WebSocket 连接状态','''
assert old in s
s = s.replace(old, new, 1); n += 1
old = " stats: '仪表盘', users: '用户管理', devices: '设备管理', plugins: '插件管理', market: '市场管理', system: '系统运维', llm_configs: '全局配置', conversations: '对话记录', ws_monitor: '连接监控', health: '健康检查', oplogs: '操作日志', emojis: '表情包', tasks: '定时任务', export: '数据导出' }"
new = " stats: '仪表盘', users: '用户管理', devices: '设备管理', plugins: '插件管理', market: '市场管理', firmware: '固件管理', system: '系统运维', llm_configs: '全局配置', conversations: '对话记录', ws_monitor: '连接监控', health: '健康检查', oplogs: '操作日志', emojis: '表情包', tasks: '定时任务', export: '数据导出' }"
assert old in s
s = s.replace(old, new, 1); n += 1
old = "	 market: '管理插件上下架与推荐状态',"
if old in s:
    s = s.replace(old, old + "\n	  firmware: '上传固件、登记 bin_id、管理 OTA 比对目标',", 1); n += 1

# 4. 状态与函数（插在 installedPlugins 状态前）
old = '''const installedPlugins = ref([])'''
new = '''// 固件管理
const firmwares = ref([])
const loadingFirmwares = ref(false)
const uploadingFw = ref(false)
const fwFile = ref(null)
const fwBinId = ref('')
const fwVersion = ref('')

async function loadFirmwares() {
  loadingFirmwares.value = true
  try {
    const res = await api.adminFirmwares()
    if (res.status === 200 && res.data?.code === 0) firmwares.value = res.data.data?.firmwares || []
    else emit('toast', res.data?.message || '加载固件列表失败')
  } catch { emit('toast', '加载固件列表失败') }
  loadingFirmwares.value = false
}

function onFirmwareFileChange(e) { fwFile.value = e.target.files?.[0] || null }

async function uploadFirmware() {
  if (!fwFile.value) { emit('toast', '请先选择固件文件'); return }
  if (!fwBinId.value.trim()) { emit('toast', '请填写固件 bin_id'); return }
  uploadingFw.value = true
  try {
    const res = await api.adminFirmwareUpload(fwFile.value, fwBinId.value.trim(), fwVersion.value.trim())
    if (res.status === 200 && res.data?.code === 0) {
      emit('toast', res.data.message || '固件已上传并设为启用中')
      fwFile.value = null; fwBinId.value = ''; fwVersion.value = ''
      document.querySelectorAll('input[type=file]').forEach(i => { if (!i.hidden) i.value = '' })
      loadFirmwares()
    } else emit('toast', res.data?.message || res.data?.detail || '上传失败')
  } catch { emit('toast', '上传失败') }
  uploadingFw.value = false
}

async function setFirmwareActive(f) {
  try {
    const res = await api.adminFirmwareSetActive(f.filename)
    if (res.status === 200 && res.data?.code === 0) { emit('toast', '已启用固件 ' + f.filename); loadFirmwares() }
    else emit('toast', res.data?.message || '操作失败')
  } catch { emit('toast', '操作失败') }
}

async function deleteFirmware(f) {
  const ok = await showConfirm({ title: '删除固件', message: `确定删除固件「${f.filename}」吗？此操作不可恢复。`, confirmText: '确认删除', danger: true })
  if (!ok) return
  try {
    const res = await api.adminFirmwareDelete(f.filename)
    if (res.status === 200 && res.data?.code === 0) { emit('toast', '固件已删除'); loadFirmwares() }
    else emit('toast', res.data?.message || '删除失败')
  } catch { emit('toast', '删除失败') }
}

const installedPlugins = ref([])'''
assert old in s, 'fw state'
s = s.replace(old, new, 1); n += 1

# 5. watch 分支
old = '''  else if (val === 'system') { loadSystemInfo(); loadBackups(); loadLogs() }'''
new = '''  else if (val === 'firmware') loadFirmwares()
  else if (val === 'system') { loadSystemInfo(); loadBackups(); loadLogs() }'''
assert old in s
s = s.replace(old, new, 1); n += 1

io.open(p, 'w', encoding='utf-8', newline='').write(s)
print('AdminView firmware section added,', n, 'edits')
