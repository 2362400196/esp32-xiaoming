<template>
  <div class="admin-layout">
    <!-- 左侧边栏 -->
    <aside class="admin-sidebar">
      <div class="sidebar-brand">
        <span class="brand-icon">◆</span>
        <span class="brand-text">管理后台</span>
      </div>

      <nav class="sidebar-nav">
        <button class="nav-item" :class="{ active: section === 'stats' }" @click="section = 'stats'">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>
          <span>仪表盘</span>
        </button>
        <button class="nav-item" :class="{ active: section === 'users' }" @click="section = 'users'">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>
          <span>用户管理</span>
        </button>
        <button class="nav-item" :class="{ active: section === 'devices' }" @click="section = 'devices'">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="5" y="2" width="14" height="20" rx="2"/><line x1="12" y1="18" x2="12.01" y2="18"/></svg>
          <span>设备管理</span>
        </button>
        <button class="nav-item" :class="{ active: section === 'plugins' }" @click="section = 'plugins'">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/></svg>
          <span>插件管理</span>
        </button>
        <button class="nav-item" :class="{ active: section === 'market' }" @click="section = 'market'">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
          <span>市场管理</span>
        </button>
        <button class="nav-item" :class="{ active: section === 'system' }" @click="section = 'system'">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="3" width="20" height="14" rx="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg>
          <span>系统运维</span>
        </button>
      </nav>

      <div class="sidebar-footer">
        <button class="nav-item back-btn" @click="$emit('back')">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="19" y1="12" x2="5" y2="12"/><polyline points="12 19 5 12 12 5"/></svg>
          <span>返回主面板</span>
        </button>
      </div>
    </aside>

    <!-- 右侧内容 -->
    <main class="admin-content">
      <div class="content-header">
        <h2 class="content-title">{{ sectionTitle }}</h2>
        <p class="content-sub">{{ sectionSub }}</p>
      </div>

      <div class="content-body">
        <transition name="section-fade" mode="out-in">
          <div :key="section" class="section-wrap">
            <!-- 仪表盘 -->
            <section v-if="section === 'stats'" class="admin-section">
          <div class="stat-grid">
            <div class="stat-card card-in">
              <span class="stat-icon"><svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg></span>
              <div class="stat-info">
                <p class="stat-value">{{ stats.users ?? '—' }}</p>
                <p class="stat-label">注册用户</p>
              </div>
            </div>
            <div class="stat-card card-in" style="animation-delay:.05s">
              <span class="stat-icon"><svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M21 2l-2 2m-7.61 7.61a5.5 5.5 0 1 1-7.778 7.778 5.5 5.5 0 0 1 7.777-7.777zm0 0L15.5 7.5m0 0l3 3L22 7l-3-3m-3.5 3.5L19 4"/></svg></span>
              <div class="stat-info">
                <p class="stat-value">{{ stats.admins ?? '—' }}</p>
                <p class="stat-label">管理员</p>
              </div>
            </div>
            <div class="stat-card card-in" style="animation-delay:.1s">
              <span class="stat-icon"><svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="5" y="2" width="14" height="20" rx="2"/><line x1="12" y1="18" x2="12.01" y2="18"/></svg></span>
              <div class="stat-info">
                <p class="stat-value">{{ stats.devices ?? '—' }}</p>
                <p class="stat-label">设备总数</p>
              </div>
            </div>
            <div class="stat-card card-in" style="animation-delay:.15s">
              <span class="stat-icon"><svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg></span>
              <div class="stat-info">
                <p class="stat-value">{{ stats.online_devices ?? '—' }}</p>
                <p class="stat-label">在线设备</p>
              </div>
            </div>
            <div class="stat-card card-in" style="animation-delay:.2s">
              <span class="stat-icon"><svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/></svg></span>
              <div class="stat-info">
                <p class="stat-value">{{ stats.bound_devices ?? '—' }}</p>
                <p class="stat-label">已绑定设备</p>
              </div>
            </div>
          </div>

          <!-- 性能指标 -->
          <template v-if="metrics">
            <h3 class="section-subtitle">服务性能</h3>
            <div class="stat-grid">
              <div class="stat-card card-in">
                <span class="stat-icon" style="color:#ffb74d;"><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="4" width="16" height="16" rx="2"/><rect x="9" y="9" width="6" height="6"/></svg></span>
                <div class="stat-info">
                  <p class="stat-value" style="color:#ffb74d;">{{ metrics.system?.cpu_percent != null ? metrics.system.cpu_percent.toFixed(1) + '%' : '—' }}</p>
                  <p class="stat-label">CPU</p>
                </div>
              </div>
              <div class="stat-card card-in">
                <span class="stat-icon" style="color:#e57373;"><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="2" width="20" height="8" rx="2"/><rect x="2" y="14" width="20" height="8" rx="2"/></svg></span>
                <div class="stat-info">
                  <p class="stat-value" style="color:#e57373;">{{ metrics.system?.memory_mb != null ? metrics.system.memory_mb.toFixed(0) + ' MB' : '—' }}</p>
                  <p class="stat-label">内存</p>
                </div>
              </div>
              <div class="stat-card card-in">
                <span class="stat-icon" style="color:#ba68c8;"><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="3" width="20" height="14" rx="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg></span>
                <div class="stat-info">
                  <p class="stat-value" style="color:#ba68c8;">{{ metrics.system?.num_threads ?? '—' }}</p>
                  <p class="stat-label">线程数</p>
                </div>
              </div>
              <div class="stat-card card-in">
                <span class="stat-icon" style="color:#81c784;"><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg></span>
                <div class="stat-info">
                  <p class="stat-value" style="color:#81c784;">{{ metrics.concurrency?.active_tasks ?? '—' }}</p>
                  <p class="stat-label">活跃任务</p>
                </div>
              </div>
            </div>
          </template>

          <div class="action-bar">
            <div class="action-info">
              <p class="action-title">系统维护</p>
              <p class="action-sub">修改插件代码后，无需重启服务即可热加载全部插件</p>
            </div>
            <button class="btn btn-mint" :disabled="reloadingPlugins" @click="reloadPlugins">
              {{ reloadingPlugins ? '重载中…' : '重载插件' }}
            </button>
          </div>
        </section>

        <!-- 用户管理 -->
        <section v-else-if="section === 'users'" class="admin-section">
          <div class="table-card">
            <div class="table-head">
              <div>
                <h3 class="table-title">用户列表</h3>
                <p class="table-sub">管理角色、设备上限与账号状态</p>
              </div>
              <button class="btn btn-ghost" :disabled="loadingUsers" @click="loadUsers">刷新</button>
            </div>

            <div v-if="loadingUsers" class="table-empty">加载中…</div>
            <div v-else-if="!users.length" class="table-empty">暂无用户</div>
            <div v-else class="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>用户</th>
                    <th>角色</th>
                    <th>设备数 / 上限</th>
                    <th>状态</th>
                    <th>开发者</th>
                    <th>注册时间</th>
                    <th>最后登录</th>
                    <th>操作</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="u in users" :key="u.user_id">
                    <td data-label="用户">
                      <div class="cell-user">
                        <span class="cell-avatar">{{ (u.nickname || u.email || '?')[0].toUpperCase() }}</span>
                        <div class="cell-main">
                          <p class="cell-title">{{ u.nickname || '未设置昵称' }}</p>
                          <p class="cell-sub">{{ u.email }}</p>
                        </div>
                      </div>
                    </td>
                    <td data-label="角色">
                      <select v-if="editingUser === u.user_id" v-model="editForm.role" class="input input-sm select-sm">
                        <option value="admin">管理员</option>
                        <option value="user">普通用户</option>
                      </select>
                      <span v-else class="badge" :class="u.role === 'admin' ? 'badge-mint' : 'badge-sub'">{{ u.role === 'admin' ? '管理员' : '普通用户' }}</span>
                    </td>
                    <td data-label="设备数/上限">
                      <template v-if="editingUser === u.user_id">
                        <input v-model.number="editForm.max_devices" type="number" min="0" class="input input-sm num-input" />
                      </template>
                      <template v-else>{{ u.device_count }} / {{ u.max_devices }}</template>
                    </td>
                    <td data-label="状态">
                      <label v-if="editingUser === u.user_id" class="switch-label">
                        <input v-model="editForm.is_active" type="checkbox" class="switch-input" />
                        <span class="switch-box"></span>
                        <span class="switch-text">{{ editForm.is_active ? '启用' : '停用' }}</span>
                      </label>
                      <span v-else class="badge" :class="u.is_active ? 'badge-mint' : 'badge-danger'">{{ u.is_active ? '启用' : '停用' }}</span>
                    </td>
                    <td data-label="开发者"><span class="badge" :class="u.is_developer ? 'badge-mint' : 'badge-sub'">{{ u.is_developer ? '已开通' : '未开通' }}</span></td>
                    <td data-label="注册时间" class="cell-muted">{{ formatDate(u.created_at) }}</td>
                    <td data-label="最后登录" class="cell-muted">{{ formatDate(u.last_login) }}</td>
                    <td data-label="操作">
                      <div class="row-actions">
                        <button v-if="editingUser !== u.user_id" class="btn btn-ghost btn-xs" @click="startEditUser(u)">编辑</button>
                        <template v-else>
                          <button class="btn btn-mint btn-xs" :disabled="savingUser" @click="saveUser(u)">保存</button>
                          <button class="btn btn-ghost btn-xs" :disabled="savingUser" @click="cancelEditUser">取消</button>
                        </template>
                        <button class="btn btn-ghost btn-xs" :disabled="savingUser" @click="viewUserDevices(u)">设备</button>
                        <button class="btn btn-ghost btn-xs" :disabled="savingUser" @click="openResetPassword(u)">重置密码</button>
                        <button class="btn btn-ghost btn-xs" :disabled="savingUser" @click="toggleDeveloper(u)">{{ u.is_developer ? '关闭开发者' : '开通开发者' }}</button>
                        <button class="btn btn-danger btn-xs" :disabled="savingUser || u.user_id === currentUserId" @click="deleteUser(u)">删除</button>
                      </div>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </section>

        <!-- 设备管理 -->
        <section v-else-if="section === 'devices'" class="admin-section">
          <div class="action-bar">
            <div class="action-info">
              <p class="action-title">批量操作</p>
              <p class="action-sub">向所有在线设备执行唤醒 / 停止 / 语音广播</p>
            </div>
            <div class="row-actions">
              <input v-model="broadcastText" class="input input-sm broadcast-input" placeholder="广播文字（批量播报时使用）" />
              <button class="btn btn-ghost btn-sm" @click="runBatchAction('wakeup')">批量唤醒</button>
              <button class="btn btn-ghost btn-sm" @click="runBatchAction('stop')">批量停止</button>
              <button class="btn btn-mint btn-sm" @click="runBatchAction('speak')">批量播报</button>
            </div>
          </div>

          <div class="table-card">
            <div class="table-head">
              <div>
                <h3 class="table-title">设备列表</h3>
                <p class="table-sub">查看全部设备与归属，支持重命名和解绑</p>
              </div>
              <button class="btn btn-ghost" :disabled="loadingDevices" @click="loadDevices">刷新</button>
            </div>

            <div v-if="loadingDevices" class="table-empty">加载中…</div>
            <div v-else-if="!devices.length" class="table-empty">暂无设备</div>
            <div v-else class="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>设备</th>
                    <th>MAC / 标识</th>
                    <th>归属用户</th>
                    <th>状态</th>
                    <th>绑定时间</th>
                    <th>操作</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="d in devices" :key="d.device_id">
                    <td data-label="设备">
                      <div class="cell-device">
                        <span class="device-icon"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="5" y="2" width="14" height="20" rx="2"/><line x1="12" y1="18" x2="12.01" y2="18"/></svg></span>
                        <div class="cell-main">
                          <input v-if="editingDevice === d.device_id" v-model="editDeviceForm.name" class="input input-sm" placeholder="设备名称" />
                          <p v-else class="cell-title">{{ d.name || '未命名设备' }}</p>
                          <p class="cell-sub">{{ d.device_id }}</p>
                        </div>
                      </div>
                    </td>
                    <td data-label="MAC/标识" class="cell-muted">{{ d.mac || d.device_key || '—' }}</td>
                    <td data-label="归属用户">{{ d.owner_email || '未绑定' }}</td>
                    <td data-label="状态">
                      <span class="badge" :class="d.online ? 'badge-mint' : 'badge-sub'">
                        <span class="dot" :class="{ on: d.online }"></span>{{ d.online ? '在线' : '离线' }}
                      </span>
                    </td>
                    <td data-label="绑定时间" class="cell-muted">{{ formatDate(d.bound_at) }}</td>
                    <td data-label="操作">
                      <div class="row-actions">
                        <button v-if="editingDevice !== d.device_id" class="btn btn-ghost btn-xs" @click="startEditDevice(d)">重命名</button>
                        <template v-else>
                          <button class="btn btn-mint btn-xs" :disabled="savingDevice" @click="saveDevice(d)">保存</button>
                          <button class="btn btn-ghost btn-xs" :disabled="savingDevice" @click="cancelEditDevice">取消</button>
                        </template>
                        <button class="btn btn-danger btn-xs" :disabled="savingDevice" @click="unbindDevice(d)">解绑</button>
                        <button v-if="!d.user_id" class="btn btn-danger btn-xs" :disabled="savingDevice" @click="deleteDevice(d)">删除</button>
                      </div>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </section>

        <!-- 插件管理 -->
        <section v-else-if="section === 'plugins'" class="admin-section">
          <div class="action-bar">
            <div class="action-info">
              <p class="action-title">插件管理</p>
              <p class="action-sub">上传 zip 安装插件、更新、卸载、热加载</p>
            </div>
            <div class="row-actions">
              <label class="btn btn-ghost upload-btn">
                上传安装
                <input type="file" accept=".zip" hidden @change="onInstallPluginFile" />
              </label>
              <button class="btn btn-mint" :disabled="reloadingPlugins" @click="reloadPlugins">热重载</button>
              <button class="btn btn-ghost" :disabled="loadingPlugins" @click="loadInstalledPlugins">刷新</button>
            </div>
          </div>

          <div class="table-card">
            <div class="table-head">
              <div>
                <h3 class="table-title">已安装插件</h3>
                <p class="table-sub">版本、来源、加载状态、工具列表</p>
              </div>
            </div>
            <div v-if="loadingPlugins" class="table-empty">加载中…</div>
            <div v-else-if="!installedPlugins.length" class="table-empty">暂无已安装插件</div>
            <div v-else class="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>插件</th>
                    <th>版本</th>
                    <th>来源</th>
                    <th>状态</th>
                    <th>工具</th>
                    <th>操作</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="p in installedPlugins" :key="p.name">
                    <td data-label="插件">
                      <div class="cell-main">
                        <p class="cell-title">{{ p.display_name || p.name }}</p>
                        <p class="cell-sub">{{ p.description || p.slug || p.name }}</p>
                      </div>
                    </td>
                    <td data-label="版本">{{ p.version }}</td>
                    <td data-label="来源">{{ p.source === 'installed' ? '已安装' : (p.source || '内置') }}</td>
                    <td data-label="状态"><span class="badge" :class="p.loaded ? 'badge-mint' : 'badge-sub'">{{ p.loaded ? '已加载' : '未加载' }}</span></td>
                    <td data-label="工具" class="cell-muted">{{ (p.tools || []).join(', ') || '—' }}</td>
                    <td data-label="操作">
                      <div class="row-actions">
                        <button class="btn btn-ghost btn-xs" :disabled="updatingPlugin === p.name" @click="updatePlugin(p)">{{ updatingPlugin === p.name ? '更新中' : '更新' }}</button>
                        <button v-if="p.source !== 'built-in'" class="btn btn-danger btn-xs" :disabled="uninstallingPlugin === p.name" @click="uninstallPlugin(p)">{{ uninstallingPlugin === p.name ? '卸载中' : '卸载' }}</button>
                      </div>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </section>

        <!-- 市场管理 -->
        <section v-else-if="section === 'market'" class="admin-section">
          <div class="table-card">
            <div class="table-head">
              <div>
                <h3 class="table-title">市场插件</h3>
                <p class="table-sub">管理插件上下架与推荐状态</p>
              </div>
              <button class="btn btn-ghost" :disabled="loadingMarketPlugins" @click="loadMarketplacePlugins">刷新</button>
            </div>
            <div v-if="loadingMarketPlugins" class="table-empty">加载中…</div>
            <div v-else-if="!marketplacePlugins.length" class="table-empty">暂无市场插件</div>
            <div v-else class="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>插件</th>
                    <th>开发者</th>
                    <th>版本</th>
                    <th>下载</th>
                    <th>评分</th>
                    <th>上架</th>
                    <th>推荐</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="p in marketplacePlugins" :key="p.slug">
                    <td data-label="插件">
                      <div class="cell-main">
                        <p class="cell-title">{{ p.name }}</p>
                        <p class="cell-sub">{{ p.slug }}</p>
                      </div>
                    </td>
                    <td data-label="开发者">{{ p.developer }}</td>
                    <td data-label="版本">{{ p.latest_version }}</td>
                    <td data-label="下载">{{ p.total_downloads }}</td>
                    <td data-label="评分">{{ p.avg_rating }} ({{ p.review_count }})</td>
                    <td data-label="上架">
                      <label class="switch-label">
                        <input type="checkbox" class="switch-input" :checked="p.is_active" @change="toggleMarketplacePlugin(p, 'is_active', $event.target.checked)" />
                        <span class="switch-box"></span>
                        <span class="switch-text">{{ p.is_active ? '已上架' : '已下架' }}</span>
                      </label>
                    </td>
                    <td data-label="推荐">
                      <label class="switch-label">
                        <input type="checkbox" class="switch-input" :checked="p.is_featured" @change="toggleMarketplacePlugin(p, 'is_featured', $event.target.checked)" />
                        <span class="switch-box"></span>
                        <span class="switch-text">{{ p.is_featured ? '推荐' : '普通' }}</span>
                      </label>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>

          <div class="table-card">
            <div class="table-head">
              <div>
                <h3 class="table-title">市场评论</h3>
                <p class="table-sub">查看并删除违规评论</p>
              </div>
              <button class="btn btn-ghost" :disabled="loadingReviews" @click="loadMarketplaceReviews">刷新</button>
            </div>
            <div v-if="loadingReviews" class="table-empty">加载中…</div>
            <div v-else-if="!reviews.length" class="table-empty">暂无评论</div>
            <div v-else class="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>插件</th>
                    <th>用户</th>
                    <th>评分</th>
                    <th>评论</th>
                    <th>时间</th>
                    <th>操作</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="r in reviews" :key="r.id">
                    <td data-label="插件">{{ r.plugin_name }} <span class="cell-sub">({{ r.plugin_slug }})</span></td>
                    <td data-label="用户">{{ r.username }}</td>
                    <td data-label="评分">{{ r.rating }}<svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round" style="vertical-align:-2px"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg></td>
                    <td data-label="评论" class="cell-muted">{{ r.comment || '—' }}</td>
                    <td data-label="时间" class="cell-muted">{{ formatDate(r.created_at) }}</td>
                    <td data-label="操作"><button class="btn btn-danger btn-xs" @click="deleteReview(r)">删除</button></td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </section>

        <!-- 系统运维 -->
        <section v-else-if="section === 'system'" class="admin-section">
          <div class="stat-grid">
            <div class="stat-card card-in">
              <span class="stat-icon"><svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="3" width="20" height="14" rx="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg></span>
              <div class="stat-info">
                <p class="stat-value">{{ systemInfo.python_version || '—' }}</p>
                <p class="stat-label">Python</p>
              </div>
            </div>
            <div class="stat-card card-in" style="animation-delay:.05s">
              <span class="stat-icon"><svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"/><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/></svg></span>
              <div class="stat-info">
                <p class="stat-value">{{ formatSize(systemInfo.db_size) }}</p>
                <p class="stat-label">数据库大小</p>
              </div>
            </div>
            <div class="stat-card card-in" style="animation-delay:.1s">
              <span class="stat-icon"><svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><polyline points="10 9 9 9 8 9"/></svg></span>
              <div class="stat-info">
                <p class="stat-value">{{ formatSize(systemInfo.log_size) }}</p>
                <p class="stat-label">日志大小</p>
              </div>
            </div>
            <div class="stat-card card-in" style="animation-delay:.15s">
              <span class="stat-icon"><svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="4" width="16" height="16" rx="2"/><rect x="9" y="9" width="6" height="6"/><line x1="9" y1="1" x2="9" y2="4"/><line x1="15" y1="1" x2="15" y2="4"/><line x1="9" y1="20" x2="9" y2="23"/><line x1="15" y1="20" x2="15" y2="23"/><line x1="20" y1="9" x2="23" y2="9"/><line x1="20" y1="14" x2="23" y2="14"/><line x1="1" y1="9" x2="4" y2="9"/><line x1="1" y1="14" x2="4" y2="14"/></svg></span>
              <div class="stat-info">
                <p class="stat-value">{{ formatSize(systemInfo.memory_bytes) }}</p>
                <p class="stat-label">进程内存</p>
              </div>
            </div>
            <div class="stat-card card-in" style="animation-delay:.2s">
              <span class="stat-icon"><svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12.55a11 11 0 0 1 14.08 0"/><path d="M1.42 9a16 16 0 0 1 21.16 0"/><path d="M8.53 16.11a6 6 0 0 1 6.95 0"/><line x1="12" y1="20" x2="12.01" y2="20"/></svg></span>
              <div class="stat-info">
                <p class="stat-value">{{ systemInfo.registry_devices ?? '—' }}</p>
                <p class="stat-label">注册表设备</p>
              </div>
            </div>
          </div>

          <div class="action-bar">
            <div class="action-info">
              <p class="action-title">数据库备份</p>
              <p class="action-sub">创建一致性备份，保留最近 30 天</p>
            </div>
            <div class="row-actions">
              <button class="btn btn-mint" :disabled="backingUp" @click="createBackup">{{ backingUp ? '备份中…' : '立即备份' }}</button>
              <button class="btn btn-ghost" :disabled="loadingBackups" @click="loadBackups">刷新备份列表</button>
            </div>
          </div>

          <div class="table-card">
            <div class="table-head">
              <div>
                <h3 class="table-title">备份列表</h3>
                <p class="table-sub">最近数据库备份文件</p>
              </div>
            </div>
            <div v-if="!backups.length" class="table-empty">暂无备份</div>
            <div v-else class="table-wrap">
              <table>
                <thead><tr><th>文件名</th><th>大小</th><th>时间</th><th>操作</th></tr></thead>
                <tbody>
                  <tr v-for="b in backups" :key="b.name">
                    <td data-label="文件名">{{ b.name }}</td>
                    <td data-label="大小">{{ formatSize(b.size) }}</td>
                    <td data-label="时间" class="cell-muted">{{ formatDate(b.mtime) }}</td>
                    <td data-label="操作">
                      <button class="btn btn-ghost btn-xs" @click="downloadBackup(b.name)">下载</button>
                      <button class="btn btn-ghost btn-xs" style="color:var(--danger)" @click="deleteBackup(b.name)">删除</button>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>

          <div class="table-card">
            <div class="table-head">
              <div>
                <h3 class="table-title">服务日志</h3>
                <p class="table-sub">最近 {{ logLines.length }} 行</p>
              </div>
              <button class="btn btn-ghost" :disabled="loadingLogs" @click="loadLogs">刷新日志</button>
            </div>
            <pre class="log-view">{{ logLines.join('\n') || '暂无日志' }}</pre>
          </div>
        </section>
          </div>
        </transition>
      </div>
    </main>

    <!-- 用户设备弹窗 -->
    <div v-if="deviceModalVisible" class="modal-mask" @click.self="deviceModalVisible = false">
      <div class="modal-card">
        <div class="modal-head">
          <span class="modal-title">{{ deviceModalTitle }}</span>
          <button class="modal-close" @click="deviceModalVisible = false">×</button>
        </div>
        <div class="modal-body">
          <div v-if="!deviceModalList.length" class="modal-empty">该用户暂无绑定设备</div>
          <div v-else class="device-modal-list">
            <div v-for="d in deviceModalList" :key="d.device_id || d.mac || d.device_key" class="device-modal-item">
              <span class="device-modal-name">{{ d.name || '未命名设备' }}</span>
              <span class="device-modal-id">{{ d.device_id || d.mac || d.device_key }}</span>
              <span class="online-badge" :class="{ on: d.online }"><span class="dot"></span>{{ d.online ? '在线' : '离线' }}</span>
            </div>
          </div>
        </div>
        <div class="modal-foot">
          <button class="btn btn-ghost" @click="deviceModalVisible = false">关闭</button>
        </div>
      </div>
    </div>

    <!-- 重置密码弹窗 -->
    <div v-if="passwordModalVisible" class="modal-mask" @click.self="passwordModalVisible = false">
      <div class="modal-card">
        <div class="modal-head">
          <span class="modal-title">重置密码</span>
          <button class="modal-close" @click="passwordModalVisible = false">×</button>
        </div>
        <div class="modal-body">
          <p class="modal-tip">为用户「{{ passwordModalUser?.nickname || passwordModalUser?.email }}」设置新密码（至少 6 位）</p>
          <input v-model="passwordInput" type="password" class="input" placeholder="请输入新密码" @keyup.enter="submitResetPassword" />
        </div>
        <div class="modal-foot">
          <button class="btn btn-ghost" :disabled="passwordSaving" @click="passwordModalVisible = false">取消</button>
          <button class="btn btn-mint" :disabled="passwordSaving" @click="submitResetPassword">{{ passwordSaving ? '提交中…' : '确认重置' }}</button>
        </div>
      </div>
    </div>

    <!-- 确认弹窗 -->
    <transition name="modal-fade">
      <div v-if="confirmData.show" class="modal-mask" @click.self="confirmCancel">
        <div class="modal-card confirm-modal">
          <div class="confirm-icon" :class="{ danger: confirmData.danger }">{{ confirmData.danger ? '!' : '?' }}</div>
          <h3 class="confirm-title">{{ confirmData.title }}</h3>
          <p class="confirm-message">{{ confirmData.message }}</p>
          <div class="confirm-actions">
            <button class="btn btn-ghost" @click="confirmCancel">{{ confirmData.cancelText || '取消' }}</button>
            <button class="confirm-ok" :class="{ danger: confirmData.danger }" @click="confirmOk">{{ confirmData.confirmText || '确定' }}</button>
          </div>
        </div>
      </div>
    </transition>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { api, getUser, getToken } from '../api'

const emit = defineEmits(['toast', 'back'])

const section = ref('stats')
const stats = ref({})
const metrics = ref(null)
const reloadingPlugins = ref(false)

const users = ref([])
const loadingUsers = ref(false)
const editingUser = ref('')
const editForm = ref({})
const savingUser = ref(false)

const devices = ref([])
const loadingDevices = ref(false)
const editingDevice = ref('')
const editDeviceForm = ref({})
const savingDevice = ref(false)

const currentUserId = computed(() => getUser()?.user_id || '')
const sectionTitle = computed(() => ({ stats: '仪表盘', users: '用户管理', devices: '设备管理', plugins: '插件管理', market: '市场管理', system: '系统运维' }[section.value] || ''))
const sectionSub = computed(() => ({
  stats: '系统总览与服务性能',
  users: '管理角色、设备上限与账号状态',
  devices: '查看全部设备与归属，支持重命名和解绑',
  plugins: '上传 zip 安装插件、更新、卸载、热加载',
  market: '管理插件上下架与推荐状态',
  system: '数据库备份与服务日志',
}[section.value] || ''))

const deviceModalVisible = ref(false)
const deviceModalTitle = ref('')
const deviceModalList = ref([])
const passwordModalVisible = ref(false)
const passwordModalUser = ref(null)
const passwordInput = ref('')
const passwordSaving = ref(false)

const confirmData = ref({ show: false, title: '', message: '', confirmText: '确定', cancelText: '取消', danger: false, resolve: null })

function showConfirm(options) {
  return new Promise(resolve => {
    confirmData.value = { show: true, title: options.title || '请确认', message: options.message || '', confirmText: options.confirmText || '确定', cancelText: options.cancelText || '取消', danger: options.danger !== false, resolve }
  })
}

function confirmOk() { const r = confirmData.value.resolve; confirmData.value = { show: false, title: '', message: '', confirmText: '确定', cancelText: '取消', danger: false, resolve: null }; r?.(true) }
function confirmCancel() { const r = confirmData.value.resolve; confirmData.value = { show: false, title: '', message: '', confirmText: '确定', cancelText: '取消', danger: false, resolve: null }; r?.(false) }

const installedPlugins = ref([])
const loadingPlugins = ref(false)
const updatingPlugin = ref('')
const uninstallingPlugin = ref('')

const marketplacePlugins = ref([])
const loadingMarketPlugins = ref(false)
const reviews = ref([])
const loadingReviews = ref(false)

const systemInfo = ref({})
const logLines = ref([])
const loadingLogs = ref(false)
const backups = ref([])
const loadingBackups = ref(false)
const backingUp = ref(false)
const broadcastText = ref('')

async function loadStats() {
  try {
    const res = await api.adminStats()
    if (res.status === 200 && res.data?.code === 0) stats.value = res.data.data || {}
  } catch { /* 忽略 */ }
}

async function loadMetrics() {
  try {
    const res = await api.adminMetrics()
    if (res.status === 200 && res.data?.code === 0) metrics.value = res.data.data || null
  } catch { /* 忽略 */ }
}

async function reloadPlugins() {
  reloadingPlugins.value = true
  try {
    const res = await api.adminReloadPlugins()
    if (res.status === 200 && res.data?.code === 0) emit('toast', '插件已热加载')
    else emit('toast', res.data?.message || res.data?.detail || '重载插件失败')
  } catch { emit('toast', '重载插件失败') }
  reloadingPlugins.value = false
}

async function loadUsers() {
  loadingUsers.value = true
  try {
    const res = await api.adminUsers()
    if (res.status === 200 && res.data?.code === 0) users.value = res.data.data?.users || []
    else emit('toast', res.data?.message || res.data?.detail || '加载用户失败')
  } catch { emit('toast', '加载用户失败') }
  loadingUsers.value = false
}

async function loadDevices() {
  loadingDevices.value = true
  try {
    const res = await api.adminDevices()
    if (res.status === 200 && res.data?.code === 0) devices.value = res.data.data?.devices || []
    else emit('toast', res.data?.message || res.data?.detail || '加载设备失败')
  } catch { emit('toast', '加载设备失败') }
  loadingDevices.value = false
}

function loadAll() { loadStats(); loadMetrics(); loadUsers(); loadDevices() }

function startEditUser(u) { editingUser.value = u.user_id; editForm.value = { role: u.role, max_devices: u.max_devices, is_active: u.is_active, nickname: u.nickname } }
function cancelEditUser() { editingUser.value = ''; editForm.value = {} }

async function saveUser(u) {
  savingUser.value = true
  try {
    const res = await api.adminUpdateUser(u.user_id, editForm.value)
    if (res.status === 200 && res.data?.code === 0) { emit('toast', '用户已更新'); cancelEditUser(); loadUsers(); loadStats(); loadMetrics() }
    else emit('toast', res.data?.message || res.data?.detail || '保存失败')
  } catch { emit('toast', '保存失败') }
  savingUser.value = false
}

async function deleteUser(u) {
  const ok = await showConfirm({ title: '删除用户', message: `确定删除用户「${u.nickname || u.email}」吗？该用户的设备将被解绑。`, confirmText: '确认删除', danger: true })
  if (!ok) return
  savingUser.value = true
  try {
    const res = await api.adminDeleteUser(u.user_id)
    if (res.status === 200 && res.data?.code === 0) { emit('toast', '用户已删除'); loadUsers(); loadStats(); loadMetrics(); loadDevices() }
    else emit('toast', res.data?.message || res.data?.detail || '删除失败')
  } catch { emit('toast', '删除失败') }
  savingUser.value = false
}

async function viewUserDevices(u) {
  try {
    const res = await api.adminUserDevices(u.user_id)
    if (res.status === 200 && res.data?.code === 0) {
      deviceModalTitle.value = `用户「${u.nickname || u.email}」的设备`
      deviceModalList.value = res.data.data?.devices || []
      deviceModalVisible.value = true
    } else emit('toast', res.data?.message || res.data?.detail || '加载设备失败')
  } catch { emit('toast', '加载设备失败') }
}

function openResetPassword(u) { passwordModalUser.value = u; passwordInput.value = ''; passwordModalVisible.value = true }

async function submitResetPassword() {
  const u = passwordModalUser.value
  if (!u) return
  if (!passwordInput.value || passwordInput.value.length < 6) { emit('toast', '密码至少 6 位'); return }
  passwordSaving.value = true
  try {
    const res = await api.adminResetPassword(u.user_id, passwordInput.value)
    if (res.status === 200 && res.data?.code === 0) { emit('toast', '密码已重置'); passwordModalVisible.value = false; passwordModalUser.value = null; passwordInput.value = '' }
    else emit('toast', res.data?.message || res.data?.detail || '重置失败')
  } catch { emit('toast', '重置失败') }
  passwordSaving.value = false
}

async function toggleDeveloper(u) {
  try {
    const res = await api.adminToggleDeveloper(u.user_id)
    if (res.status === 200 && res.data?.code === 0) { emit('toast', res.data.message || '开发者权限已更新'); loadUsers() }
    else emit('toast', res.data?.message || res.data?.detail || '操作失败')
  } catch { emit('toast', '操作失败') }
}

function startEditDevice(d) { editingDevice.value = d.device_id; editDeviceForm.value = { name: d.name || '' } }
function cancelEditDevice() { editingDevice.value = ''; editDeviceForm.value = {} }

async function saveDevice(d) {
  savingDevice.value = true
  try {
    const res = await api.adminUpdateDevice(d.device_id, editDeviceForm.value)
    if (res.status === 200 && res.data?.code === 0) { emit('toast', '设备已更新'); cancelEditDevice(); loadDevices() }
    else emit('toast', res.data?.message || res.data?.detail || '保存失败')
  } catch { emit('toast', '保存失败') }
  savingDevice.value = false
}

async function unbindDevice(d) {
  const ok = await showConfirm({ title: '解绑设备', message: `确定解绑设备「${d.name || d.device_id}」吗？`, confirmText: '确认解绑', danger: true })
  if (!ok) return
  savingDevice.value = true
  try {
    const res = await api.adminUnbindDevice(d.device_id)
    if (res.status === 200 && res.data?.code === 0) { emit('toast', '设备已解绑'); loadDevices(); loadStats(); loadMetrics() }
    else emit('toast', res.data?.message || res.data?.detail || '解绑失败')
  } catch { emit('toast', '解绑失败') }
  savingDevice.value = false
}

async function deleteDevice(d) {
  const ok = await showConfirm({ title: '删除设备', message: `确定删除设备「${d.name || d.device_id}」吗？未绑定设备删除后不可恢复。`, confirmText: '确认删除', danger: true })
  if (!ok) return
  savingDevice.value = true
  try {
    const res = await api.adminDeleteDevice(d.device_id)
    if (res.status === 200 && res.data?.code === 0) { emit('toast', '设备已删除'); loadDevices(); loadStats(); loadMetrics() }
    else emit('toast', res.data?.message || res.data?.detail || '删除失败')
  } catch { emit('toast', '删除失败') }
  savingDevice.value = false
}

async function loadInstalledPlugins() {
  loadingPlugins.value = true
  try {
    const res = await api.installedPlugins()
    if (res.status === 200 && res.data?.code === 0) installedPlugins.value = res.data.data || []
    else emit('toast', res.data?.message || res.data?.detail || '加载插件失败')
  } catch { emit('toast', '加载插件失败') }
  loadingPlugins.value = false
}

async function onInstallPluginFile(e) {
  const file = e.target.files?.[0]
  if (!file) return
  try {
    const res = await api.installPluginZip(file)
    if (res?.data?.code === 0) { emit('toast', '插件安装成功'); loadInstalledPlugins() }
    else emit('toast', res?.data?.message || res?.data?.detail || '安装失败')
  } catch { emit('toast', '安装失败') }
  e.target.value = ''
}

async function updatePlugin(p) {
  updatingPlugin.value = p.name
  try {
    const res = await api.updatePlugin(p.name)
    if (res.status === 200 && res.data?.code === 0) { emit('toast', '插件更新成功'); loadInstalledPlugins() }
    else emit('toast', res.data?.message || res.data?.detail || '更新失败')
  } catch { emit('toast', '更新失败') }
  updatingPlugin.value = ''
}

async function uninstallPlugin(p) {
  const ok = await showConfirm({ title: '卸载插件', message: `确定卸载插件「${p.display_name || p.name}」吗？`, confirmText: '确认卸载', danger: true })
  if (!ok) return
  uninstallingPlugin.value = p.name
  try {
    const res = await api.uninstallPlugin(p.name)
    if (res.status === 200 && res.data?.code === 0) { emit('toast', '插件已卸载'); loadInstalledPlugins() }
    else emit('toast', res.data?.message || res.data?.detail || '卸载失败')
  } catch { emit('toast', '卸载失败') }
  uninstallingPlugin.value = ''
}

async function loadMarketplacePlugins() {
  loadingMarketPlugins.value = true
  try {
    const res = await api.adminMarketplacePlugins()
    if (res.status === 200 && res.data?.code === 0) marketplacePlugins.value = res.data.data?.plugins || []
    else emit('toast', res.data?.message || res.data?.detail || '加载市场插件失败')
  } catch { emit('toast', '加载市场插件失败') }
  loadingMarketPlugins.value = false
}

async function toggleMarketplacePlugin(p, field, value) {
  try {
    const res = await api.adminUpdateMarketplacePlugin(p.slug, { [field]: value })
    if (res.status === 200 && res.data?.code === 0) { p[field] = value; emit('toast', '市场插件状态已更新') }
    else emit('toast', res.data?.message || res.data?.detail || '更新失败')
  } catch { emit('toast', '更新失败') }
}

async function loadMarketplaceReviews() {
  loadingReviews.value = true
  try {
    const res = await api.adminMarketplaceReviews()
    if (res.status === 200 && res.data?.code === 0) reviews.value = res.data.data?.reviews || []
    else emit('toast', res.data?.message || res.data?.detail || '加载评论失败')
  } catch { emit('toast', '加载评论失败') }
  loadingReviews.value = false
}

async function deleteReview(r) {
  const ok = await showConfirm({ title: '删除评论', message: `确定删除「${r.username}」的这条评论吗？`, confirmText: '确认删除', danger: true })
  if (!ok) return
  try {
    const res = await api.adminDeleteMarketplaceReview(r.id)
    if (res.status === 200 && res.data?.code === 0) { emit('toast', '评论已删除'); loadMarketplaceReviews(); loadMarketplacePlugins() }
    else emit('toast', res.data?.message || res.data?.detail || '删除失败')
  } catch { emit('toast', '删除失败') }
}

async function loadSystemInfo() {
  try {
    const res = await api.adminSystemInfo()
    if (res.status === 200 && res.data?.code === 0) systemInfo.value = res.data.data || {}
  } catch { /* 忽略 */ }
}

async function loadLogs() {
  loadingLogs.value = true
  try {
    const res = await api.adminLogs(300)
    if (res.status === 200 && res.data?.code === 0) logLines.value = res.data.data?.lines || []
    else emit('toast', res.data?.message || res.data?.detail || '加载日志失败')
  } catch { emit('toast', '加载日志失败') }
  loadingLogs.value = false
}

async function loadBackups() {
  loadingBackups.value = true
  try {
    const res = await api.adminBackups()
    if (res.status === 200 && res.data?.code === 0) backups.value = res.data.data?.backups || []
    else emit('toast', res.data?.message || res.data?.detail || '加载备份列表失败')
  } catch { emit('toast', '加载备份列表失败') }
  loadingBackups.value = false
}

async function createBackup() {
  backingUp.value = true
  try {
    const res = await api.adminBackup()
    if (res.status === 200 && res.data?.code === 0) { emit('toast', '备份成功'); loadBackups() }
    else emit('toast', res.data?.message || res.data?.detail || '备份失败')
  } catch { emit('toast', '备份失败') }
  backingUp.value = false
}

async function runBatchAction(action) {
  if (action === 'speak' && !broadcastText.value.trim()) { emit('toast', '请输入要广播的文字'); return }
  try {
    let res
    if (action === 'wakeup') res = await api.adminBatchWakeup()
    else if (action === 'stop') res = await api.adminBatchStop()
    else res = await api.adminBatchSpeak(broadcastText.value.trim())
    if (res.status === 200 && res.data?.code === 0) { emit('toast', res.data.message || '批量操作成功'); if (action === 'speak') broadcastText.value = '' }
    else emit('toast', res.data?.message || res.data?.detail || '批量操作失败')
  } catch { emit('toast', '批量操作失败') }
}

function formatSize(bytes) {
  if (bytes === null || bytes === undefined) return '—'
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / 1024 / 1024).toFixed(1) + ' MB'
}

function downloadBackup(name) {
  const token = getToken()
  fetch(`/api/v1/admin/backup/download/${encodeURIComponent(name)}`, {
    headers: { Authorization: `Bearer ${token}` }
  })
  .then(r => {
    if (!r.ok) return r.json().then(d => { throw new Error(d.detail || d.message || '下载失败') })
    return r.blob()
  })
  .then(blob => {
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob); a.download = name; a.click()
    URL.revokeObjectURL(a.href)
  })
  .catch(e => emit('toast', e.message || '下载失败'))
}

async function deleteBackup(name) {
  const ok = await showConfirm({ title: '删除备份', message: `确定删除备份文件「${name}」吗？此操作不可恢复。`, confirmText: '确认删除', danger: true })
  if (!ok) return
  const token = getToken()
  try {
    const r = await fetch(`/api/v1/admin/backup/${encodeURIComponent(name)}`, {
      method: 'DELETE', headers: { Authorization: `Bearer ${token}` }
    })
    const data = await r.json()
    if (data.code === 0) { emit('toast', '备份已删除'); loadBackups() }
    else emit('toast', data.detail || data.message || '删除失败')
  } catch (e) { emit('toast', '删除失败') }
}

function formatDate(ts) {
  if (!ts) return '—'
  const d = new Date(ts * 1000)
  const p = n => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}

onMounted(loadAll)
watch(section, (val) => {
  if (val === 'plugins') loadInstalledPlugins()
  else if (val === 'market') { loadMarketplacePlugins(); loadMarketplaceReviews() }
  else if (val === 'system') { loadSystemInfo(); loadBackups(); loadLogs() }
})
</script>

<style scoped>
.admin-layout {
  display: flex;
  position: fixed;
  inset: 0;
  min-height: 100vh;
  background: var(--bg-body, #f0f4f8);
}

/* ===== 左侧边栏 ===== */
.admin-sidebar {
  position: fixed;
  top: 0; left: 0;
  width: 220px;
  height: 100vh;
  display: flex;
  flex-direction: column;
  background: linear-gradient(180deg, rgba(255,255,255,0.88), rgba(255,255,255,0.72));
  backdrop-filter: var(--glass-blur);
  -webkit-backdrop-filter: var(--glass-blur);
  border-right: 1px solid var(--glass-border);
  z-index: 100;
  animation: sidebarIn 0.4s var(--ease);
}
@keyframes sidebarIn {
  from { transform: translateX(-100%); }
  to { transform: translateX(0); }
}

.sidebar-brand {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 24px 20px 20px;
  border-bottom: 1px solid var(--glass-border-soft);
}
.brand-icon {
  font-size: 20px;
  color: var(--mint-deep);
}
.brand-text {
  font-size: 16px;
  font-weight: 800;
  letter-spacing: 0.5px;
  color: var(--text-main);
}

.sidebar-nav {
  flex: 1;
  padding: 12px 10px;
  display: flex;
  flex-direction: column;
  gap: 2px;
  overflow-y: auto;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  border: none;
  background: transparent;
  border-radius: 10px;
  font-size: 13px;
  font-weight: 500;
  color: var(--text-sub);
  cursor: pointer;
  transition: all 0.2s var(--ease);
  text-align: left;
  width: 100%;
}
.nav-item:hover {
  background: var(--mint-softer);
  color: var(--mint-deep);
}
.nav-item.active {
  background: var(--grad-mint);
  color: #fff;
  box-shadow: var(--shadow-mint);
  font-weight: 600;
  position: relative;
}
.nav-item.active::before {
  content: '';
  position: absolute;
  left: -10px;
  top: 50%;
  transform: translateY(-50%);
  width: 4px;
  height: 20px;
  border-radius: 0 4px 4px 0;
  background: var(--mint-deep);
  animation: indicatorIn 0.3s var(--ease);
}
@keyframes indicatorIn {
  from { height: 0; opacity: 0; }
  to { height: 20px; opacity: 1; }
}
.nav-item.active svg {
  filter: drop-shadow(0 1px 2px rgba(0,0,0,0.1));
}

.sidebar-footer {
  padding: 12px 10px;
  border-top: 1px solid var(--glass-border-soft);
}
.back-btn {
  color: var(--text-dim);
  font-size: 12px;
}
.back-btn:hover {
  color: var(--mint-deep);
  background: var(--mint-softer);
}

/* ===== 右侧内容 ===== */
.admin-content {
  margin-left: 220px;
  flex: 1;
  min-width: 0;
  overflow-x: hidden;
  padding: 32px 36px 60px;
  min-height: 100vh;
}

.content-header {
  margin-bottom: 24px;
}
.content-title {
  font-size: 22px;
  font-weight: 800;
  letter-spacing: -0.3px;
  color: var(--text-main);
}
.content-sub {
  margin-top: 4px;
  font-size: 13px;
  color: var(--text-sub);
}

.content-body {
  display: flex;
  flex-direction: column;
  gap: 18px;
}
.section-wrap {
  display: flex;
  flex-direction: column;
  gap: 18px;
}
/* 内容切换动画 */
.section-fade-enter-active {
  animation: sectionIn 0.3s var(--ease);
}
.section-fade-leave-active {
  animation: sectionOut 0.2s var(--ease);
}
@keyframes sectionIn {
  from { opacity: 0; transform: translateY(12px); }
  to { opacity: 1; transform: translateY(0); }
}
@keyframes sectionOut {
  from { opacity: 1; transform: translateY(0); }
  to { opacity: 0; transform: translateY(-8px); }
}

.admin-section {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

/* ===== 统计卡 ===== */
.stat-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 14px;
}
.stat-card {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 22px 24px;
  position: relative;
  overflow: hidden;
  background: var(--grad-card);
  backdrop-filter: var(--glass-blur);
  -webkit-backdrop-filter: var(--glass-blur);
  border: 1px solid var(--glass-border);
  box-shadow: var(--shadow), var(--glass-hi);
  border-radius: var(--radius-lg);
}
.stat-card::after {
  content: '';
  position: absolute; top: -40px; right: -40px;
  width: 140px; height: 140px;
  background: radial-gradient(circle, rgba(52, 211, 153, 0.12), transparent 70%);
  border-radius: 50%; pointer-events: none;
}
.stat-icon { font-size: 28px; filter: drop-shadow(0 4px 8px rgba(16,185,129,.18)); display: inline-flex; align-items: center; justify-content: center; color: var(--mint-deep); }
.stat-info { display: flex; flex-direction: column; gap: 2px; position: relative; }
.stat-value { font-size: 28px; font-weight: 800; line-height: 1.1; letter-spacing: -0.5px; }
.stat-label { font-size: 12px; color: var(--text-sub); }

.section-subtitle {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-sub);
  margin: 0;
  display: flex;
  align-items: center;
  gap: 8px;
}

/* ===== 操作栏 ===== */
.action-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 20px 24px;
  flex-wrap: wrap;
  background: var(--grad-card);
  backdrop-filter: var(--glass-blur);
  -webkit-backdrop-filter: var(--glass-blur);
  border: 1px solid var(--glass-border);
  box-shadow: var(--shadow), var(--glass-hi);
  border-radius: var(--radius-lg);
}
.action-info { min-width: 0; }
.action-title { font-size: 15px; font-weight: 700; }
.action-sub { margin-top: 3px; font-size: 12px; color: var(--text-sub); }

/* ===== 表格 ===== */
.table-card {
  background: var(--grad-card);
  backdrop-filter: var(--glass-blur);
  -webkit-backdrop-filter: var(--glass-blur);
  border: 1px solid var(--glass-border);
  box-shadow: var(--shadow), var(--glass-hi);
  border-radius: var(--radius-lg);
  overflow: hidden;
}
.table-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 20px 24px 16px;
  border-bottom: 1px solid var(--glass-border-soft);
}
.table-title { font-size: 16px; font-weight: 700; }
.table-sub { margin-top: 3px; font-size: 12px; color: var(--text-sub); }
.table-wrap { overflow-x: auto; }
.table-empty { padding: 48px 20px; text-align: center; color: var(--text-dim); font-size: 13px; }

table { width: 100%; border-collapse: collapse; min-width: 760px; }
th, td { padding: 14px 18px; text-align: left; font-size: 13px; vertical-align: middle; }
th {
  background: var(--glass-bg-strong);
  color: var(--text-sub); font-weight: 600;
  white-space: nowrap;
}
tbody tr { border-top: 1px solid var(--glass-border-soft); transition: background .2s var(--ease); }
tbody tr:hover { background: var(--mint-softer); }

.cell-user, .cell-device { display: flex; align-items: center; gap: 12px; }
.cell-avatar {
  width: 36px; height: 36px; border-radius: 50%; flex-shrink: 0;
  display: flex; align-items: center; justify-content: center;
  font-size: 13px; font-weight: 700; color: #fff; background: var(--grad-brand);
  box-shadow: var(--shadow-mint), inset 0 1px 0 rgba(255, 255, 255, 0.35);
}
.device-icon { font-size: 22px; flex-shrink: 0; display: inline-flex; align-items: center; color: var(--text-sub); }
.cell-main { min-width: 0; }
.cell-title { font-weight: 600; }
.cell-sub { margin-top: 2px; font-size: 12px; color: var(--text-dim); }
.cell-muted { color: var(--text-sub); }

.badge {
  display: inline-flex; align-items: center; gap: 6px;
  font-size: 12px; font-weight: 600;
  padding: 4px 12px; border-radius: 999px;
  white-space: nowrap;
}
.badge-mint { background: var(--mint-soft); color: var(--mint-deep); border: 1px solid var(--mint-border); }
.badge-sub { background: var(--glass-bg-strong); color: var(--text-sub); border: 1px solid var(--glass-border); }
.badge-danger { background: var(--danger-soft); color: var(--danger); border: 1px solid rgba(239,68,68,.2); }
.badge .dot {
  width: 7px; height: 7px; border-radius: 50%;
  background: var(--text-dim);
}
.badge .dot.on { background: var(--mint); box-shadow: 0 0 8px var(--mint-glow); }

.row-actions { display: flex; gap: 6px; flex-wrap: wrap; }

/* ===== 按钮系统 ===== */
.btn {
  padding: 7px 16px;
  font-size: 13px;
  font-weight: 600;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s var(--ease);
  display: inline-flex;
  align-items: center;
  gap: 6px;
  white-space: nowrap;
}
.btn:disabled { opacity: .5; cursor: not-allowed; }
.btn-sm { padding: 6px 14px; font-size: 13px; }
.btn-xs { padding: 4px 10px; font-size: 12px; }
.btn-mint { background: var(--grad-mint); color: #fff; border: none; box-shadow: var(--shadow-mint); }
.btn-mint:hover:not(:disabled) { filter: brightness(1.06); }
.btn-ghost { background: rgba(255,255,255,0.6); color: var(--text-sub); border: 1px solid var(--glass-border); }
.btn-ghost:hover:not(:disabled) { background: var(--mint-softer); color: var(--mint-deep); }
.btn-danger {
  border: 1px solid rgba(239,68,68,.25);
  background: rgba(255,255,255,0.6); color: var(--danger);
}
.btn-danger:hover:not(:disabled) { background: var(--danger-soft); border-color: var(--danger); }

.input { border: 1px solid var(--glass-border); border-radius: 8px; padding: 8px 12px; font-size: 13px; background: rgba(255,255,255,0.6); outline: none; transition: border-color 0.2s; }
.input:focus { border-color: var(--mint); }
.input-sm { padding: 6px 10px; font-size: 12px; }
.select-sm { width: 110px; }
.num-input { width: 80px; }

.switch-label { display: inline-flex; align-items: center; gap: 8px; cursor: pointer; }
.switch-input { display: none; }
.switch-box {
  width: 34px; height: 20px; border-radius: 999px;
  background: #d1d5db; position: relative; transition: background .2s var(--ease);
  flex-shrink: 0;
}
.switch-box::after {
  content: ''; position: absolute; top: 2px; left: 2px;
  width: 16px; height: 16px; border-radius: 50%; background: #fff;
  transition: transform .2s var(--ease); box-shadow: 0 1px 3px rgba(0,0,0,.2);
}
.switch-input:checked + .switch-box { background: var(--mint); }
.switch-input:checked + .switch-box::after { transform: translateX(14px); }
.switch-text { font-size: 12px; color: var(--text-sub); }
.upload-btn { cursor: pointer; }
.broadcast-input { width: 220px; }

.log-view {
  max-height: 360px; overflow: auto;
  padding: 16px 20px; margin: 0;
  background: rgba(15, 23, 42, 0.92);
  color: #d1fae5;
  font-family: 'Cascadia Code', 'JetBrains Mono', Consolas, monospace;
  font-size: 12px; line-height: 1.6;
  white-space: pre-wrap; word-break: break-all;
  max-width: 100%; box-sizing: border-box;
  border-radius: 0 0 var(--radius-lg) var(--radius-lg);
  border-top: 1px solid var(--glass-border-soft);
}

/* ===== 弹窗 ===== */
.modal-mask {
  position: fixed; inset: 0; z-index: 1000;
  background: rgba(15, 23, 42, 0.45);
  backdrop-filter: blur(12px) saturate(140%);
  -webkit-backdrop-filter: blur(12px) saturate(140%);
  display: flex; align-items: center; justify-content: center;
  padding: 20px;
}
.modal-card {
  width: 100%; max-width: 460px;
  background: var(--grad-panel);
  backdrop-filter: var(--glass-blur);
  -webkit-backdrop-filter: var(--glass-blur);
  border: 1px solid var(--glass-border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-hover), var(--glass-hi);
  overflow: hidden;
  animation: modalPop 0.3s var(--ease);
}
@keyframes modalPop {
  from { opacity: 0; transform: scale(0.92) translateY(8px); }
  to { opacity: 1; transform: scale(1) translateY(0); }
}
.modal-head {
  display: flex; align-items: center; justify-content: space-between;
  padding: 16px 20px;
  border-bottom: 1px solid var(--glass-border-soft);
}
.modal-title { font-size: 15px; font-weight: 700; }
.modal-close {
  border: none; background: transparent;
  font-size: 22px; line-height: 1; color: var(--text-dim);
  cursor: pointer; padding: 4px;
}
.modal-body { padding: 20px; max-height: 60vh; overflow-y: auto; }
.modal-empty, .modal-tip { font-size: 13px; color: var(--text-sub); }
.modal-tip { margin-bottom: 12px; }
.modal-foot {
  display: flex; justify-content: flex-end; gap: 8px;
  padding: 14px 20px;
  border-top: 1px solid var(--glass-border-soft);
  background: var(--glass-bg-strong);
}
.device-modal-list { display: flex; flex-direction: column; gap: 8px; }
.device-modal-item {
  display: flex; align-items: center; gap: 10px;
  padding: 10px 12px;
  border: 1px solid var(--glass-border);
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.35);
}
.device-modal-name { font-weight: 600; font-size: 13px; }
.device-modal-id { flex: 1; min-width: 0; font-size: 12px; color: var(--text-dim); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

.confirm-modal { width: 380px; max-width: 90vw; padding: 36px 30px 28px; text-align: center; }
.confirm-icon {
  width: 56px; height: 56px; border-radius: 50%; margin: 0 auto 20px;
  display: flex; align-items: center; justify-content: center;
  font-size: 28px; font-weight: 800; color: var(--mint);
  background: var(--mint-soft);
  border: 2px solid var(--mint-border);
}
.confirm-icon.danger { color: #e53e3e; background: var(--danger-soft); border-color: rgba(239, 68, 68, 0.35); }
.confirm-modal .confirm-title { font-size: 18px; font-weight: 700; margin-bottom: 10px; }
.confirm-modal .confirm-message { font-size: 14px; line-height: 1.6; color: var(--text-sub); margin-bottom: 26px; }
.confirm-actions { display: flex; gap: 12px; justify-content: center; }
.confirm-ok {
  padding: 7px 20px; font-size: 13px; font-weight: 600; border: none;
  border-radius: var(--radius-md); cursor: pointer;
  background: var(--grad-mint); color: #fff;
  box-shadow: var(--shadow-mint); transition: all 0.2s var(--ease);
}
.confirm-ok:hover { filter: brightness(1.08); }
.confirm-ok.danger { background: linear-gradient(135deg, #fc8181, #e53e3e); box-shadow: 0 4px 12px rgba(229, 62, 62, 0.3); }

.modal-fade-enter-active, .modal-fade-leave-active { transition: opacity 0.25s var(--ease); }
.modal-fade-enter-from, .modal-fade-leave-to { opacity: 0; }
.modal-fade-enter-active .modal-card, .modal-fade-leave-active .modal-card { transition: transform 0.25s var(--ease); }
.modal-fade-enter-from .modal-card, .modal-fade-leave-to .modal-card { transform: scale(0.92) translateY(8px); }

/* ===== 响应式 ===== */
@media (max-width: 1024px) {
  .admin-content { padding: 24px 20px 40px; }
  .stat-grid { grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); }
  .stat-card { padding: 18px 20px; }
  .stat-value { font-size: 24px; }
  table { min-width: 0; }
  th, td { padding: 12px 14px; }
  .broadcast-input { width: 160px; }
}

@media (max-width: 768px) {
  .admin-sidebar { width: 56px; }
  .sidebar-brand .brand-text,
  .nav-item span,
  .back-btn span { display: none; }
  .sidebar-brand { justify-content: center; padding: 20px 0; }
  .nav-item { justify-content: center; padding: 10px; }
  .admin-content {
    margin-left: 56px;
    padding: 20px 14px 40px;
  }
  .content-title { font-size: 18px; }
  .content-sub { font-size: 12px; }
  .stat-grid { grid-template-columns: repeat(2, 1fr); gap: 10px; }
  .stat-card { padding: 14px 16px; gap: 12px; }
  .stat-value { font-size: 20px; }
  .stat-icon { font-size: 22px; }
  .action-bar { flex-direction: column; align-items: stretch; padding: 16px 18px; }
  .action-bar .row-actions { justify-content: stretch; }
  .action-bar .row-actions .btn { flex: 1; justify-content: center; }
  table { min-width: 0; }
  th, td { padding: 10px 10px; font-size: 12px; }
  th { display: none; }
  tbody tr {
    display: block;
    padding: 12px 14px;
    border: 1px solid var(--glass-border);
    border-radius: 10px;
    margin-bottom: 8px;
    background: var(--grad-card);
  }
  tbody tr:hover { background: var(--grad-card); }
  tbody td {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 6px 0;
    border: none;
    gap: 8px;
  }
  tbody td::before {
    content: attr(data-label);
    font-weight: 600;
    color: var(--text-sub);
    font-size: 11px;
    flex-shrink: 0;
  }
  tbody td .cell-user,
  tbody td .cell-device {
    justify-content: flex-end;
  }
  tbody tr td:first-child {
    padding-top: 0;
  }
  tbody tr td:last-child {
    padding-bottom: 0;
  }
  .table-wrap { overflow: visible; }
  .table-head { flex-direction: column; gap: 8px; align-items: flex-start; }
  .broadcast-input { width: 100%; }
  .row-actions { flex-wrap: wrap; }
  .section-subtitle { font-size: 13px; }
  .log-view { max-height: 240px; font-size: 11px; padding: 12px 14px; }
}

@media (max-width: 480px) {
  .admin-content { padding: 16px 10px 40px; }
  .stat-grid { grid-template-columns: 1fr 1fr; gap: 8px; }
  .stat-card { padding: 12px 14px; }
  .stat-value { font-size: 18px; }
  .stat-label { font-size: 11px; }
  .content-title { font-size: 16px; }
  .btn { font-size: 12px; padding: 6px 12px; }
  .btn-xs { font-size: 11px; padding: 3px 8px; }
  .table-head { padding: 14px 16px 12px; }
  .table-head .table-title { font-size: 14px; }
  tbody tr { padding: 10px 12px; }
  tbody td { font-size: 11px; }
  .modal-card { max-width: 94vw; }
  .modal-body { padding: 14px; }
  .confirm-modal { padding: 28px 20px 24px; }
}

@media (min-width: 1600px) {
  .admin-content { padding: 40px 48px 60px; }
  .stat-grid { grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 18px; }
  .stat-card { padding: 26px 28px; }
  .stat-value { font-size: 32px; }
  .content-title { font-size: 26px; }
  table { min-width: 900px; }
  th, td { padding: 16px 22px; font-size: 14px; }
}
</style>