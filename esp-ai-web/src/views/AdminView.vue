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
        <button class="nav-item" :class="{ active: section === 'firmware' }" @click="section = 'firmware'">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="4" width="16" height="16" rx="2"/><rect x="9" y="9" width="6" height="6"/><line x1="9" y1="1" x2="9" y2="4"/><line x1="15" y1="1" x2="15" y2="4"/><line x1="9" y1="20" x2="9" y2="23"/><line x1="15" y1="20" x2="15" y2="23"/><line x1="20" y1="9" x2="23" y2="9"/><line x1="20" y1="14" x2="23" y2="14"/><line x1="1" y1="9" x2="4" y2="9"/><line x1="1" y1="14" x2="4" y2="14"/></svg>
          <span>固件管理</span>
        </button>
        <button class="nav-item" :class="{ active: section === 'system' }" @click="section = 'system'">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="2" width="20" height="8" rx="2"/><rect x="2" y="14" width="20" height="8" rx="2"/><line x1="6" y1="6" x2="6.01" y2="6"/><line x1="6" y1="18" x2="6.01" y2="18"/></svg>
          <span>系统运维</span>
        </button>
        <button class="nav-item" :class="{ active: section === 'conversations' }" @click="section = 'conversations'">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
          <span>对话记录</span>
        </button>
        <button class="nav-item" :class="{ active: section === 'ws_monitor' }" @click="section = 'ws_monitor'">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12.55a11 11 0 0 1 14.08 0"/><path d="M1.42 9a16 16 0 0 1 21.16 0"/><path d="M8.53 16.11a6 6 0 0 1 6.95 0"/><line x1="12" y1="20" x2="12.01" y2="20"/></svg>
          <span>连接监控</span>
        </button>
        <button class="nav-item" :class="{ active: section === 'health' }" @click="section = 'health'">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 12h-4l-3 9L9 3l-3 9H2"/></svg>
          <span>健康检查</span>
        </button>
        <button class="nav-item" :class="{ active: section === 'oplogs' }" @click="section = 'oplogs'">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>
          <span>操作日志</span>
        </button>
        <button class="nav-item" :class="{ active: section === 'emojis' }" @click="section = 'emojis'">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M8 14s1.5 2 4 2 4-2 4-2"/><line x1="9" y1="9" x2="9.01" y2="9"/><line x1="15" y1="9" x2="15.01" y2="9"/></svg>
          <span>表情包</span>
        </button>
        <button class="nav-item" :class="{ active: section === 'tasks' }" @click="section = 'tasks'">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="18" rx="2" ry="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>
          <span>定时任务</span>
        </button>
        <button class="nav-item" :class="{ active: section === 'export' }" @click="section = 'export'">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
          <span>数据导出</span>
        </button>
        <button class="nav-item" :class="{ active: section === 'site' }" @click="section = 'site'">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>
          <span>网站设置</span>
        </button>
        <button class="nav-item" :class="{ active: section === 'billing' }" @click="section = 'billing'">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="5" width="20" height="14" rx="2"/><line x1="2" y1="10" x2="22" y2="10"/></svg>
          <span>计费系统</span>
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
              <div class="stat-card card-in" style="cursor:pointer" title="点击查看任务明细" @click="openTaskDetail">
                <span class="stat-icon" style="color:#81c784;"><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg></span>
                <div class="stat-info">
                  <p class="stat-value" style="color:#81c784;">{{ metrics.concurrency?.active_tasks ?? '—' }}</p>
                  <p class="stat-label">活跃任务 ›</p>
                </div>
              </div>
            </div>
          </template>

          <!-- 近 7 天累计费用 -->
          <div class="chart-card card-in">
            <div class="chart-head">
              <div>
                <h3 class="section-subtitle" style="margin:0">近 7 天累计费用</h3>
                <p class="table-sub">每日总费用（元）</p>
              </div>
              <button class="btn btn-ghost btn-xs" :disabled="loadingDailyCost" @click="loadDailyCost">刷新</button>
            </div>
            <div v-if="dailyCost.length" class="bar-chart">
              <div class="bar-col" v-for="d in dailyCost" :key="d.date">
                <div class="bar-track">
                  <div class="bar-fill" :style="{ height: barHeight(d.total_cost) + '%' }" :title="d.date + '：¥' + d.total_cost">
                    <span class="bar-value">{{ fmtCost(d.total_cost) }}</span>
                  </div>
                </div>
                <span class="bar-label">{{ fmtDay(d.date) }}</span>
              </div>
            </div>
            <div v-else class="table-empty" style="padding:40px 0">暂无费用数据</div>
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
              <p class="action-sub">注册表在线：{{ registrySnapshot.length }} 台
                <template v-if="registrySnapshot.length">
                  （<span v-for="(r, i) in registrySnapshot" :key="r.key">{{ i > 0 ? '；' : '' }}key={{ r.key.slice(0, 18) }}… mac={{ r.mac || '—' }} {{ r.connected ? '已连接' : '未连接' }}</span>）
                </template>
              </p>
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
                <p class="table-sub">按用户筛选设备，支持重命名、解绑、封禁</p>
              </div>
              <div class="row-actions">
                <select class="input input-sm select-sm" v-model="deviceOwnerFilter" @change="devicePage = 1">
                  <option value="">全部用户（{{ devices.filter(d => d.owner_email).length }} 台已绑定）</option>
                  <option value="__unbound__">未绑定设备</option>
                  <option v-for="o in deviceOwners" :key="o.user_id" :value="o.user_id">
                    {{ o.nickname || o.email }}（{{ o.count }} 台）
                  </option>
                </select>
                <button class="btn btn-ghost" :disabled="loadingDevices" @click="loadDevices">刷新</button>
              </div>
            </div>

            <div v-if="loadingDevices" class="table-empty">加载中…</div>
            <div v-else-if="!filteredDevices.length" class="table-empty">该筛选条件下暂无设备</div>
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
                  <tr v-for="d in filteredDevices" :key="d.device_id">
                    <td data-label="设备">
                      <div class="cell-device">
                        <span class="device-icon"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="5" y="2" width="14" height="20" rx="2"/><line x1="12" y1="18" x2="12.01" y2="18"/></svg></span>
                        <div class="cell-main">
                          <p class="cell-title">{{ d.name || '未命名设备' }}</p>
                          <p class="cell-sub">{{ d.device_id }}</p>
                        </div>
                      </div>
                    </td>
                    <td data-label="MAC/标识" class="cell-muted">{{ d.mac || d.device_key || '—' }}</td>
                    <td data-label="归属用户">
                      <template v-if="d.owner_email || d.owner_nickname">
                        <p class="cell-title">{{ d.owner_nickname || d.owner_email }}</p>
                        <p class="cell-sub">{{ d.owner_nickname ? d.owner_email : '' }}</p>
                      </template>
                      <span v-else class="badge badge-sub">未绑定</span>
                    </td>
                    <td data-label="状态">
                      <span class="badge" :class="d.online ? 'badge-mint' : 'badge-sub'">
                        <span class="dot" :class="{ on: d.online }"></span>{{ d.online ? '在线' : '离线' }}
                      </span>
                    </td>
                    <td data-label="绑定时间" class="cell-muted">{{ formatDate(d.bound_at) }}</td>
                    <td data-label="操作">
                      <div class="row-actions">
                        <button class="btn btn-ghost btn-xs" :disabled="!d.online" @click="wakeupDevice(d)">唤醒</button>
                        <button class="btn btn-ghost btn-xs" @click="openDeviceDetail(d)">详情</button>
                        <button class="btn btn-ghost btn-xs" @click="openRenameDevice(d)">重命名</button>
                        <button v-if="!d.is_banned" class="btn btn-ghost btn-xs" style="color:var(--danger)" @click="banDevice(d)">封禁</button>
                        <button v-if="d.is_banned" class="btn btn-ghost btn-xs" style="color:#16a34a" @click="unbanDevice(d)">解封</button>
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
                    <th>作者/安装者</th>
                    <th>使用设备</th>
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
                    <td data-label="作者/安装者">
                      <template v-if="p.installed_by">
                        <p class="cell-title">{{ p.installed_by }}</p>
                        <p class="cell-sub">{{ formatDate(p.installed_at) }} 安装</p>
                      </template>
                      <span v-else-if="p.author" class="cell-muted">{{ p.author }}</span>
                      <span v-else class="cell-muted">—</span>
                    </td>
                    <td data-label="使用设备">
                      <template v-if="(p.used_by || []).length">
                        <p v-for="u in p.used_by" :key="u.device_id" class="cell-sub" style="margin:0">
                          {{ u.device_name || u.device_id.slice(0, 12) }}{{ u.owner_nickname || u.owner_email ? `（${u.owner_nickname || u.owner_email}）` : '' }}
                        </p>
                      </template>
                      <span v-else class="cell-muted">—</span>
                    </td>
                    <td data-label="工具" class="cell-muted">{{ (p.tools || []).join(', ') || '—' }}</td>
                    <td data-label="操作">
                      <div class="row-actions">
                        <button v-if="!p.system" class="btn btn-ghost btn-xs" :disabled="updatingPlugin === p.name" @click="updatePlugin(p)">{{ updatingPlugin === p.name ? '更新中' : '更新' }}</button>
                        <button v-if="!p.system && p.source !== 'built-in'" class="btn btn-danger btn-xs" :disabled="uninstallingPlugin === p.name" @click="uninstallPlugin(p)">{{ uninstallingPlugin === p.name ? '卸载中' : '卸载' }}</button>
                        <span v-if="p.system" class="badge badge-mint">系统插件</span>
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

        <!-- 固件管理 -->
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
              <div class="fw-mode-seg">
                <button class="fw-mode-btn" :class="{ active: fwBinIdMode === 'auto' }" @click="fwBinIdMode = 'auto'">自动识别</button>
                <button class="fw-mode-btn" :class="{ active: fwBinIdMode === 'custom' }" @click="fwBinIdMode = 'custom'">自定义输入</button>
              </div>
              <input v-if="fwBinIdMode === 'custom'" class="input input-sm" v-model="fwBinId" placeholder="固件 bin_id（必填）" style="width:220px" />
              <span v-else class="cell-sub" style="font-size:12px">从固件中自动识别 bin_id（板卡编译 ID）</span>
              <input class="input input-sm" v-model="fwVersion" placeholder="版本号（可选）" style="width:140px" />
              <button class="btn btn-mint btn-sm" :disabled="!fwFile || uploadingFw || (fwBinIdMode === 'custom' && !fwBinId.trim())" @click="uploadFirmware">
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
            <div class="table-head" style="cursor:pointer;user-select:none" @click="toggleBackups">
              <div>
                <h3 class="table-title">备份列表{{ showBackups ? '' : `（${backups.length} 个）` }}</h3>
                <p class="table-sub">最近数据库备份文件，点击{{ showBackups ? '收起' : '展开' }}</p>
              </div>
              <button class="btn btn-ghost btn-sm" @click.stop="toggleBackups">{{ showBackups ? '收起 ▴' : '展开 ▾' }}</button>
            </div>
            <div v-if="showBackups">
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
          </div>

          <!-- 服务日志并入数据备份卡片，内嵌独立子卡片展示 -->
          <div class="log-block">
            <div class="table-head" style="border-bottom:1px solid var(--glass-border-soft)">
              <div>
                <h3 class="table-title" style="font-size:14px">服务日志</h3>
                <p class="table-sub">最近 {{ logLines.length }} 行</p>
              </div>
              <button class="btn btn-ghost btn-sm" :disabled="loadingLogs" @click="loadLogs">刷新日志</button>
            </div>
            <pre class="log-view">{{ logLines.join('\n') || '暂无日志' }}</pre>
          </div>
        </section>

        <!-- 对话记录 -->
        <section v-else-if="section === 'conversations'" class="admin-section">
          <div class="action-bar">
            <div class="action-info">
              <p class="action-title">对话记录</p>
              <p class="action-sub">浏览各设备的对话历史</p>
            </div>
            <div class="row-actions">
              <select class="form-input" style="width:200px" v-model="convDeviceFilter" @change="loadConversations()">
                <option value="">全部设备</option>
                <option v-for="d in allDevices" :key="d.device_id" :value="d.device_id">{{ d.name || d.device_id.slice(0,16) }}</option>
              </select>
              <button class="btn btn-ghost" :disabled="loadingConvs" @click="loadConversations()">刷新</button>
            </div>
          </div>
          <div v-for="conv in conversations" :key="conv.device_key || conv.device_id" class="table-card" style="margin-bottom:14px">
            <div class="table-head">
              <h3 class="table-title">{{ conv.device_name || conv.device_id.slice(0,16) }}<span v-if="conv.owner_email" class="table-sub" style="margin-left:10px">归属：{{ conv.owner_email }}</span></h3>
              <span class="table-sub">{{ conv.messages?.length || 0 }} 条消息</span>
            </div>
            <div v-if="!conv.messages?.length" class="table-empty">暂无对话</div>
            <div v-else class="chat-list">
              <div v-for="(m, i) in conv.messages" :key="i" class="chat-row" :class="{ mine: m.role === 'user' }">
                <div class="chat-avatar" :class="m.role">
                  <!-- 设备/助手：机器人线性图标；用户：人形线性图标（与侧边栏图标风格一致） -->
                  <svg v-if="m.role !== 'user'" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="8" width="16" height="12" rx="2"/><path d="M12 8V4m-2 0h4"/><circle cx="9" cy="13" r="0.5" fill="currentColor"/><circle cx="15" cy="13" r="0.5" fill="currentColor"/><path d="M9 17h6"/></svg>
                  <svg v-else width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>
                </div>
                <div class="chat-bubble-wrap">
                  <div class="chat-bubble">{{ m.content }}</div>
                  <div class="chat-time">{{ formatChatTime(m.timestamp) }}</div>
                </div>
              </div>
            </div>
          </div>
          <div v-if="!conversations.length" class="table-empty" style="padding:40px;text-align:center">
            <p style="font-size:14px;font-weight:600;margin-bottom:8px">暂无对话记录</p>
            <p style="font-size:12px;color:var(--text-dim)">设备与用户对话后，对话记录会自动出现在这里</p>
          </div>
        </section>

        <!-- 连接监控 -->
        <section v-else-if="section === 'ws_monitor'" class="admin-section">
          <div class="stat-grid">
            <div class="stat-card card-in">
              <span class="stat-icon"><svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M5 12.55a11 11 0 0 1 14.08 0"/></svg></span>
              <div class="stat-info"><p class="stat-value">{{ wsConnections.length }}</p><p class="stat-label">总连接数</p></div>
            </div>
            <div class="stat-card card-in">
              <span class="stat-icon"><svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 12h-4l-3 9L9 3l-3 9H2"/></svg></span>
              <div class="stat-info"><p class="stat-value">{{ wsConnections.filter(c=>c.connected).length }}</p><p class="stat-label">在线</p></div>
            </div>
            <div class="stat-card card-in">
              <span class="stat-icon"><svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg></span>
              <div class="stat-info"><p class="stat-value">{{ wsConnections.filter(c=>!c.connected).length }}</p><p class="stat-label">离线</p></div>
            </div>
          </div>
          <div class="action-bar">
            <div class="action-info"><p class="action-title">连接详情</p></div>
            <button class="btn btn-ghost" :disabled="loadingWs" @click="loadWsStatus()">刷新</button>
          </div>
          <div class="table-card">
            <div class="table-wrap">
              <table>
                <thead><tr><th>设备 ID</th><th>MAC</th><th>状态</th><th>会话 ID</th><th>最后活跃</th></tr></thead>
                <tbody>
                  <tr v-for="c in wsConnections" :key="c.device_id">
                    <td data-label="设备 ID">{{ c.device_id.slice(0,20) }}</td>
                    <td data-label="MAC">{{ c.mac || '—' }}</td>
                    <td data-label="状态"><span class="status-badge" :class="c.connected ? 'online' : 'offline'">{{ c.connected ? '在线' : '离线' }}</span></td>
                    <td data-label="会话 ID">{{ c.session_id?.slice(0,16) || '—' }}</td>
                    <td data-label="最后活跃">{{ formatDate(c.last_seen) }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
            <div v-if="!wsConnections.length" class="table-empty" style="padding:40px;text-align:center">
              <p style="font-size:14px;font-weight:600;margin-bottom:8px">暂无活跃连接</p>
              <p style="font-size:12px;color:var(--text-dim)">设备在线时会显示在这里，包含会话 ID 和最后活跃时间</p>
            </div>
          </div>
        </section>

        <!-- 健康检查 -->
        <section v-else-if="section === 'health'" class="admin-section">
          <div class="action-bar">
            <div class="action-info"><p class="action-title">系统健康检查</p><p class="action-sub">一键检测各组件运行状态</p></div>
            <button class="btn btn-mint" :disabled="checkingHealth" @click="runHealthCheck()">{{ checkingHealth ? '检查中…' : '开始检查' }}</button>
          </div>
          <div v-if="healthResult" class="table-card">
            <div class="table-head">
              <h3 class="table-title">检查结果</h3>
              <span class="status-badge" :class="healthResult.overall === 'ok' ? 'online' : 'offline'">{{ healthResult.overall === 'ok' ? '正常' : '异常' }}</span>
            </div>
            <div class="table-wrap">
              <table>
                <thead><tr><th>检查项</th><th>状态</th><th>详情</th></tr></thead>
                <tbody>
                  <tr v-for="(check, name) in healthResult.checks" :key="name">
                    <td data-label="检查项"><strong>{{ name }}</strong></td>
                    <td data-label="状态"><span class="status-badge" :class="check.status === 'ok' ? 'online' : check.status === 'skipped' ? 'skipped' : 'offline'">{{ check.status === 'ok' ? '正常' : check.status === 'skipped' ? '跳过' : '异常' }}</span></td>
                    <td data-label="详情" class="cell-muted">{{ formatHealthDetail(check) }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </section>

        <!-- 操作日志 -->
        <section v-else-if="section === 'oplogs'" class="admin-section">
          <div class="action-bar">
            <div class="action-info"><p class="action-title">操作日志</p><p class="action-sub">管理员操作审计记录</p></div>
            <button class="btn btn-ghost" :disabled="loadingOplogs" @click="loadOpLogs()">刷新</button>
          </div>
          <div class="table-card">
            <div class="table-wrap">
              <table>
                <thead><tr><th>时间</th><th>管理员</th><th>操作</th><th>详情</th></tr></thead>
                <tbody>
                  <tr v-for="(log, i) in opLogs" :key="i">
                    <td data-label="时间" class="cell-muted">{{ formatDate(log.time) }}</td>
                    <td data-label="管理员">{{ log.admin }}</td>
                    <td data-label="操作">{{ log.action }}</td>
                    <td data-label="详情" class="cell-muted">{{ log.detail || '—' }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
            <div v-if="!opLogs.length" class="table-empty" style="padding:40px;text-align:center">
            <p style="font-size:14px;font-weight:600;margin-bottom:8px">暂无操作日志</p>
            <p style="font-size:12px;color:var(--text-dim)">执行封禁/解封设备、更新系统设置等管理操作后，日志会自动记录在这里</p>
          </div>
          <div v-if="opTotalPages > 1" class="table-head" style="border-top:1px solid var(--glass-border-soft);border-bottom:none">
            <span class="table-sub">共 {{ opTotal }} 条 · 第 {{ opPage }} / {{ opTotalPages }} 页</span>
            <div class="row-actions">
              <button class="btn btn-ghost btn-xs" :disabled="opPage <= 1" @click="opPage--; loadOpLogs()">上一页</button>
              <button class="btn btn-ghost btn-xs" :disabled="opPage >= opTotalPages" @click="opPage++; loadOpLogs()">下一页</button>
            </div>
          </div>
          </div>
        </section>

        <!-- 表情包 -->
<section v-else-if="section === 'emojis'" class="admin-section">
  <div class="action-bar">
    <div class="action-info"><p class="action-title">表情包管理</p><p class="action-sub">管理全局表情包库</p></div>
    <button class="btn btn-ghost" :disabled="loadingEmojis" @click="loadEmojis()">刷新</button>
  </div>
  <div class="emo-grid">
    <div v-for="p in emojiPacks" :key="p.name" class="emo-card">
      <div class="emo-card-header">
        <span class="emo-pack-name">{{ p.display_name || p.name }}</span>
        <span class="emo-pack-count">{{ p.count }} 个</span>
      </div>
      <div class="emo-previews">
        <div v-for="emo in (p.emos || [])" :key="emo.filename" class="emo-item-wrap">
          <img :src="emo.url" :alt="emo.name" class="emo-thumb" @error="$event.target.style.display='none'" />
          <button class="emo-del-btn" title="删除此表情" @click="deleteEmojiFile(p.name, emo.filename)">×</button>
          <span class="emo-name-label">{{ emo.name }}</span>
        </div>
        <div v-if="!p.emos || !p.emos.length" class="emo-empty">无预览图</div>
      </div>
      <div class="emo-card-actions">
        <button class="btn btn-ghost btn-xs" style="color:var(--danger)" @click="deleteEmoji(p.name)">删除整个包</button>
      </div>
    </div>
  </div>
  <div v-if="!emojiPacks.length" class="table-empty">暂无表情包</div>
</section>

        <!-- 定时任务 -->
<section v-else-if="section === 'tasks'" class="admin-section">
  <div class="action-bar">
    <div class="action-info"><p class="action-title">定时任务</p><p class="action-sub">管理服务端定时任务（如定时播报、定时提醒）</p></div>
    <div class="row-actions">
      <button class="btn btn-mint btn-sm" @click="showTaskModal = true">创建任务</button>
      <button class="btn btn-ghost" :disabled="loadingTasks" @click="loadScheduledTasks()">刷新</button>
    </div>
  </div>
  <div class="table-card">
    <div class="table-wrap">
      <table>
        <thead><tr><th>名称</th><th>类型</th><th>执行时间</th><th>创建时间</th><th>操作</th></tr></thead>
        <tbody>
          <tr v-for="t in scheduledTasks" :key="t.id">
            <td data-label="名称">{{ t.name || '—' }}</td>
            <td data-label="类型">{{ t.type || t.action || '手动' }}</td>
            <td data-label="执行时间">{{ t.cron || t.schedule || '—' }}</td>
            <td data-label="创建时间" class="cell-muted">{{ formatDate(t.created_at) }}</td>
            <td data-label="操作"><button class="btn btn-ghost btn-xs" style="color:var(--danger)" @click="deleteScheduledTask(t.id)">删除</button></td>
          </tr>
        </tbody>
      </table>
    </div>
    <div v-if="!scheduledTasks.length" class="table-empty">暂无定时任务</div>
  </div>
</section>

<!-- 创建定时任务弹窗 -->
<div v-if="showTaskModal" class="modal-overlay" @click.self="showTaskModal = false">
  <div class="modal-card">
    <div class="modal-title">创建定时任务</div>
    <div style="display:flex;flex-direction:column;gap:12px">
      <div>
        <label class="form-label">任务名称</label>
        <input class="form-input" v-model="taskForm.name" placeholder="如：早安播报" />
      </div>
      <div>
        <label class="form-label">任务类型</label>
        <select class="form-input" v-model="taskForm.type">
          <option value="cron">Cron 定时</option>
          <option value="interval">间隔执行</option>
        </select>
      </div>
      <div>
        <label class="form-label">执行计划</label>
        <input class="form-input" v-model="taskForm.schedule" placeholder="cron: 0 8 * * * 或 间隔: 3600" />
        <div style="font-size:11px;color:var(--text-dim);margin-top:4px">cron 格式：分 时 日 月 周，如 0 8 * * * 表示每天早上8点</div>
      </div>
      <div>
        <label class="form-label">执行内容</label>
        <input class="form-input" v-model="taskForm.action" placeholder="如：say 早安" />
      </div>
    </div>
    <div class="modal-actions">
      <button class="btn btn-ghost" @click="showTaskModal = false">取消</button>
      <button class="btn btn-mint" :disabled="savingTask" @click="createScheduledTask()">{{ savingTask ? '创建中…' : '创建' }}</button>
    </div>
  </div>
</div>

        <!-- 网站设置 -->
        <section v-else-if="section === 'site'" class="admin-section">
          <div class="site-form-card">
            <div class="site-form-head">
              <div>
                <h3 class="table-title">基本信息</h3>
                <p class="table-sub">配置展示在前端导航栏、登录页与页脚等位置的网站信息</p>
              </div>
              <button class="btn btn-mint" :disabled="savingSite" @click="saveSiteSettings">{{ savingSite ? '保存中…' : '保存设置' }}</button>
            </div>

            <div class="site-form-body">
              <div class="form-row">
                <label class="form-label">网站名称</label>
                <input class="form-input" v-model="siteForm.site_name" placeholder="例如：小明同学" maxlength="30" />
                <p class="form-hint">显示在浏览器标题、导航栏与登录页</p>
              </div>
              <div class="form-row">
                <label class="form-label">网站副标题</label>
                <input class="form-input" v-model="siteForm.site_subtitle" placeholder="例如：智能语音助手" maxlength="50" />
                <p class="form-hint">显示在登录页 Logo 下方</p>
              </div>
              <div class="form-row">
                <label class="form-label">网站 Logo（图片 URL）</label>
                <input class="form-input" v-model="siteForm.site_logo" placeholder="https://…/logo.png（留空使用默认图标）" />
                <p class="form-hint">导航栏与登录页展示的 Logo 图片地址</p>
              </div>
              <div class="form-row">
                <label class="form-label">登录页欢迎语</label>
                <input class="form-input" v-model="siteForm.login_welcome" placeholder="例如：欢迎回来，开始你的智能语音之旅" maxlength="60" />
                <p class="form-hint">显示在登录表单上方</p>
              </div>
              <div class="form-row">
                <label class="form-label">页脚信息</label>
                <input class="form-input" v-model="siteForm.site_footer" placeholder="例如：© 2026 小明同学 · 保留所有权利" maxlength="100" />
                <p class="form-hint">显示在页面底部</p>
              </div>
              <div class="form-row">
                <label class="form-label">ICP 备案号</label>
                <input class="form-input" v-model="siteForm.site_icp" placeholder="例如：粤ICP备XXXXXXXX号（留空不显示）" maxlength="60" />
                <p class="form-hint">显示在页脚，留空则隐藏</p>
              </div>
            </div>
          </div>
        </section>

        <!-- 计费系统 -->
        <section v-else-if="section === 'billing'" class="admin-section">
          <div class="stat-grid" style="grid-template-columns:repeat(auto-fit,minmax(200px,1fr))">
            <div class="stat-card card-in">
              <span class="stat-icon"><svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg></span>
              <div class="stat-info"><p class="stat-value">{{ billingStats.record_count ?? '—' }}</p><p class="stat-label">计费会话</p></div>
            </div>
            <div class="stat-card card-in" style="animation-delay:.05s">
              <span class="stat-icon"><svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4Z"/></svg></span>
              <div class="stat-info"><p class="stat-value">{{ fmtNum(billingStats.asr_minutes) }}</p><p class="stat-label">ASR 时长(分钟)</p></div>
            </div>
            <div class="stat-card card-in" style="animation-delay:.1s">
              <span class="stat-icon"><svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><polyline points="4 17 10 11 4 5"/><line x1="12" y1="19" x2="20" y2="19"/></svg></span>
              <div class="stat-info"><p class="stat-value">{{ fmtBigNum(billingStats.llm_input_tokens) }}</p><p class="stat-label">LLM 输入 tokens</p></div>
            </div>
            <div class="stat-card card-in" style="animation-delay:.15s">
              <span class="stat-icon"><svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><polyline points="4 17 10 11 4 5"/><line x1="12" y1="19" x2="20" y2="19"/></svg></span>
              <div class="stat-info"><p class="stat-value">{{ fmtBigNum(billingStats.llm_output_tokens) }}</p><p class="stat-label">LLM 输出 tokens</p></div>
            </div>
            <div class="stat-card card-in" style="animation-delay:.2s">
              <span class="stat-icon"><svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M11 5 6 9H2v6h4l5 4z"/><path d="M15.54 8.46a5 5 0 0 1 0 7.07"/></svg></span>
              <div class="stat-info"><p class="stat-value">{{ fmtBigNum(billingStats.tts_chars) }}</p><p class="stat-label">TTS 字数</p></div>
            </div>
            <div class="stat-card card-in" style="animation-delay:.25s">
              <span class="stat-icon"><svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="5" width="20" height="14" rx="2"/><line x1="2" y1="10" x2="22" y2="10"/></svg></span>
              <div class="stat-info"><p class="stat-value" style="color:var(--mint)">¥ {{ (billingStats.total_cost ?? 0).toFixed(4) }}</p><p class="stat-label">累计费用</p></div>
            </div>
          </div>

          <div class="site-form-card" style="margin-top:20px">
            <div class="site-form-head" style="cursor:pointer" @click="billingConfigOpen = !billingConfigOpen">
              <div>
                <h3 class="table-title">计费单价配置 <span class="collapse-arrow" :class="{ open: billingConfigOpen }">▾</span></h3>
                <p class="table-sub">按用量计费：ASR 按小时、LLM 按百万 tokens、TTS 按千字，单位元</p>
              </div>
              <button class="btn btn-mint" :disabled="savingBilling" @click.stop="saveBillingConfig">{{ savingBilling ? '保存中…' : '保存配置' }}</button>
            </div>
            <div v-show="billingConfigOpen" class="site-form-body">
              <div class="form-row">
                <label class="form-label">计费开关</label>
                <label class="switch-label" style="margin-top:8px">
                  <input v-model="billingForm.enabled" type="checkbox" class="switch-input" />
                  <span class="switch-box"></span>
                  <span class="switch-text">{{ billingForm.enabled ? '已启用' : '已停用' }}</span>
                </label>
                <p class="form-hint">关闭后会话结束不再保存计费记录</p>
              </div>
              <div class="form-row">
                <label class="form-label">ASR 单价（元/小时）</label>
                <input class="form-input" v-model.number="billingForm.asr_price_per_hour" type="number" min="0" step="0.01" />
                <p class="form-hint">语音识别每识别 1 小时音频收取的费用，时长按分钟记录（火山流式识别约 1 元/小时）</p>
              </div>
              <div class="form-row">
                <label class="form-label">LLM 输入单价（元/百万 tokens）</label>
                <input class="form-input" v-model.number="billingForm.llm_input_price_per_mtokens" type="number" min="0" step="0.01" />
                <p class="form-hint">缓存未命中的输入 tokens 单价（DeepSeek V4 高峰 3.0 元/百万）</p>
              </div>
              <div class="form-row">
                <label class="form-label">LLM 输入单价·缓存命中（元/百万 tokens）</label>
                <input class="form-input" v-model.number="billingForm.llm_input_cache_hit_price_per_mtokens" type="number" min="0" step="0.01" />
                <p class="form-hint">命中缓存的输入 tokens 单价（DeepSeek V4 高峰 0.10 元/百万）</p>
              </div>
              <div class="form-row">
                <label class="form-label">LLM 输出单价（元/百万 tokens）</label>
                <input class="form-input" v-model.number="billingForm.llm_output_price_per_mtokens" type="number" min="0" step="0.01" />
                <p class="form-hint">大模型每输出 100 万 tokens 收取的费用（DeepSeek V4 高峰 9.0 元/百万）</p>
              </div>
              <div class="form-row">
                <label class="form-label">TTS 单价（元/千字）</label>
                <input class="form-input" v-model.number="billingForm.tts_price_per_kchars" type="number" min="0" step="0.01" />
                <p class="form-hint">语音合成每合成 1000 字收取的费用</p>
              </div>
              <div class="form-row" style="border-top:1px dashed var(--glass-border-soft);padding-top:16px">
                <label class="form-label">峰谷计费（DeepSeek）</label>
                <label class="switch-label" style="margin-top:8px">
                  <input v-model="billingForm.peak_offpeak_enabled" type="checkbox" class="switch-input" />
                  <span class="switch-box"></span>
                  <span class="switch-text">{{ billingForm.peak_offpeak_enabled ? '已启用' : '已停用' }}</span>
                </label>
                <p class="form-hint">开启后，峰时段内 LLM 按原价计费，其余时间为谷时按折扣计费（仅作用于 LLM）</p>
              </div>
              <div class="form-row" :class="{ 'field-disabled': !billingForm.peak_offpeak_enabled }">
                <label class="form-label">谷时折扣</label>
                <input class="form-input" v-model.number="billingForm.offpeak_discount" type="number" min="0" max="1" step="0.05" :disabled="!billingForm.peak_offpeak_enabled" />
                <p class="form-hint">谷时价格 = LLM 单价 × 折扣（DeepSeek 谷时约 0.5 半价）</p>
              </div>
              <div class="form-row" :class="{ 'field-disabled': !billingForm.peak_offpeak_enabled }">
                <label class="form-label">峰时段</label>
                <div v-for="(w, i) in billingForm.peak_windows" :key="i" style="display:flex;align-items:center;gap:8px;margin-top:8px">
                  <input class="form-input" style="max-width:110px" v-model="w[0]" type="time" :disabled="!billingForm.peak_offpeak_enabled" />
                  <span style="color:var(--text-dim);font-size:13px">至</span>
                  <input class="form-input" style="max-width:110px" v-model="w[1]" type="time" :disabled="!billingForm.peak_offpeak_enabled" />
                  <button class="btn btn-ghost btn-xs" :disabled="!billingForm.peak_offpeak_enabled || billingForm.peak_windows.length <= 1" @click="billingForm.peak_windows.splice(i, 1)">删除</button>
                </div>
                <button class="btn btn-ghost btn-xs" style="margin-top:8px;align-self:flex-start" :disabled="!billingForm.peak_offpeak_enabled || billingForm.peak_windows.length >= 4" @click="billingForm.peak_windows.push(['00:00', '00:00'])">+ 添加峰时段</button>
                <p class="form-hint">峰时段内 LLM 按原价，其余时间为谷时按折扣计费（HH:MM，支持跨零点）</p>
              </div>
            </div>
          </div>

          <div class="table-card" style="margin-top:20px">
            <div class="table-head">
              <div>
                <h3 class="table-title">设备费用汇总</h3>
                <p class="table-sub">每台设备的累计用量与费用（设备级记账）</p>
              </div>
            </div>
            <div v-if="!billingStats.per_device || !billingStats.per_device.length" class="table-empty" style="padding:32px;text-align:center">
              <p style="font-size:13px;color:var(--text-dim)">暂无设备计费数据</p>
            </div>
            <div v-else class="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>设备</th>
                    <th>会话数</th>
                    <th>ASR 时长(分钟)</th>
                    <th>LLM 输入</th>
                    <th>LLM 输出</th>
                    <th>TTS 字数</th>
                    <th>费用</th>
                    <th>占比</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="d in billingStats.per_device" :key="d.device_id">
                    <td data-label="设备"><span class="cell-muted">{{ d.device_id || '—' }}</span></td>
                    <td data-label="会话数">{{ d.record_count }}</td>
                    <td data-label="ASR 时长(分钟)">{{ fmtNum(d.asr_minutes) }}</td>
                    <td data-label="LLM 输入">{{ fmtBigNum(d.llm_input_tokens) }}<span v-if="d.llm_cache_hit_tokens" class="cell-muted" style="font-size:11px">(命中{{ fmtBigNum(d.llm_cache_hit_tokens) }})</span></td>
                    <td data-label="LLM 输出">{{ fmtBigNum(d.llm_output_tokens) }}</td>
                    <td data-label="TTS 字数">{{ fmtBigNum(d.tts_chars) }}</td>
                    <td data-label="费用"><span class="badge badge-mint">¥ {{ d.total_cost.toFixed(4) }}</span></td>
                    <td data-label="占比">
                      <div style="display:flex;align-items:center;gap:8px">
                        <div style="flex:1;min-width:60px;height:6px;border-radius:3px;background:var(--glass-border-soft);overflow:hidden">
                          <div :style="{ height: '100%', borderRadius: '3px', background: 'var(--mint)', width: billingStats.total_cost > 0 ? (d.total_cost / billingStats.total_cost * 100) + '%' : '0%' }"></div>
                        </div>
                        <span style="font-size:12px;color:var(--text-dim);white-space:nowrap">{{ billingStats.total_cost > 0 ? (d.total_cost / billingStats.total_cost * 100).toFixed(1) + '%' : '0%' }}</span>
                      </div>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>

          <div class="table-card" style="margin-top:20px">
            <div class="table-head">
              <div>
                <h3 class="table-title">计费记录</h3>
                <p class="table-sub">每次会话的用量与费用明细</p>
              </div>
              <div class="row-actions">
                <input class="form-input" style="max-width:220px" v-model="billingSearch" placeholder="搜索设备 ID" @keyup.enter="searchBillingRecords" />
                <button class="btn btn-ghost" :disabled="loadingBilling" @click="searchBillingRecords">查找</button>
                <button class="btn btn-ghost" :disabled="loadingBilling" @click="loadBillingRecords">刷新</button>
              </div>
            </div>
            <div v-if="loadingBilling" class="table-empty">加载中…</div>
            <div v-else-if="!billingRecords.length" class="table-empty" style="padding:40px;text-align:center">
              <p style="font-size:14px;font-weight:600;margin-bottom:8px">暂无计费记录</p>
              <p style="font-size:12px;color:var(--text-dim)">设备完成一次对话会话后，用量与费用会自动记录在这里</p>
            </div>
            <div v-else class="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>设备</th>
                    <th>ASR 时长(分钟)</th>
                    <th>LLM 输入</th>
                    <th>LLM 输出</th>
                    <th>TTS 字数</th>
                    <th>ASR 费用</th>
                    <th>LLM 费用</th>
                    <th>TTS 费用</th>
                    <th>合计</th>
                    <th>峰谷</th>
                    <th>时间</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="r in billingRecords" :key="r.id">
                    <td data-label="设备"><span class="cell-muted">{{ r.device_id || '—' }}</span></td>
                    <td data-label="ASR 时长(分钟)">{{ r.asr_minutes }}</td>
                    <td data-label="LLM 输入">{{ fmtBigNum(r.llm_input_tokens) }}<span v-if="r.llm_cache_hit_tokens" class="cell-muted" style="font-size:11px">(命中{{ fmtBigNum(r.llm_cache_hit_tokens) }})</span></td>
                    <td data-label="LLM 输出">{{ fmtBigNum(r.llm_output_tokens) }}</td>
                    <td data-label="TTS 字数">{{ fmtBigNum(r.tts_chars) }}</td>
                    <td data-label="ASR 费用">¥ {{ r.asr_cost.toFixed(4) }}</td>
                    <td data-label="LLM 费用">¥ {{ r.llm_cost.toFixed(4) }}</td>
                    <td data-label="TTS 费用">¥ {{ r.tts_cost.toFixed(4) }}</td>
                    <td data-label="合计"><span class="badge badge-mint">¥ {{ r.total_cost.toFixed(4) }}</span></td>
                    <td data-label="峰谷">
                      <span v-if="r.llm_offpeak" class="badge" style="background:rgba(38,166,154,.12);color:var(--mint)">谷时</span>
                      <span v-else class="badge" style="background:rgba(255,255,255,.06);color:var(--text-dim)">峰时</span>
                    </td>
                    <td data-label="时间" class="cell-muted">{{ formatDate(r.created_at) }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
            <div class="table-head" style="border-top:1px solid var(--glass-border-soft);border-bottom:none">
              <span class="table-sub">共 {{ billingTotal }} 条 · 每页 15 条 · 第 {{ billingPage }} / {{ billingTotalPages }} 页</span>
              <div class="row-actions">
                <button class="btn btn-ghost btn-xs" :disabled="billingPage <= 1" @click="billingPage = 1; loadBillingRecords()">«</button>
                <button class="btn btn-ghost btn-xs" :disabled="billingPage <= 1" @click="billingPage--; loadBillingRecords()">上一页</button>
                <template v-for="p in billingPageList" :key="p">
                  <button v-if="p === '…'" class="btn btn-ghost btn-xs" disabled>…</button>
                  <button v-else class="btn btn-ghost btn-xs" :class="{ 'btn-mint': p === billingPage }" @click="billingPage = p; loadBillingRecords()">{{ p }}</button>
                </template>
                <button class="btn btn-ghost btn-xs" :disabled="billingPage >= billingTotalPages" @click="billingPage++; loadBillingRecords()">下一页</button>
                <button class="btn btn-ghost btn-xs" :disabled="billingPage >= billingTotalPages" @click="billingPage = billingTotalPages; loadBillingRecords()">»</button>
              </div>
            </div>
          </div>
        </section>

        <!-- 数据导出 -->
        <section v-else-if="section === 'export'" class="admin-section">
          <div class="stat-grid" style="grid-template-columns:repeat(auto-fit,minmax(240px,1fr))">
            <div class="stat-card card-in" style="cursor:pointer" @click="exportData('users')">
              <span class="stat-icon"><svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/></svg></span>
              <div class="stat-info"><p class="stat-value">导出用户</p><p class="stat-label">用户列表 CSV</p></div>
            </div>
            <div class="stat-card card-in" style="cursor:pointer" @click="exportData('devices')">
              <span class="stat-icon"><svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="5" y="2" width="14" height="20" rx="2"/></svg></span>
              <div class="stat-info"><p class="stat-value">导出设备</p><p class="stat-label">设备列表 CSV</p></div>
            </div>
          </div>
        </section>

          </div>
        </transition>
      </div>
    </main>

    <!-- 设备详情弹窗 -->
    <div v-if="detailModalVisible" class="modal-mask" @click.self="detailModalVisible = false">
      <div class="modal-card" style="max-width:640px">
        <div class="modal-head">
          <span class="modal-title">设备详情</span>
          <button class="modal-close" @click="detailModalVisible = false; stopDetailPoll()">×</button>
        </div>
        <div class="modal-body">
          <div v-if="loadingDetail" class="modal-empty">加载中…</div>
          <template v-else-if="deviceDetail">
            <!-- 设备头部：图标 + 名称 + 状态 -->
            <div class="device-hero">
              <span class="device-avatar-lg">
                <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="5" y="2" width="14" height="20" rx="2"/><line x1="12" y1="18" x2="12.01" y2="18"/></svg>
              </span>
              <div class="cell-main">
                <p class="cell-title">{{ deviceDetail.name || '未命名设备' }}</p>
                <p class="cell-sub">{{ deviceDetail.device_id }}</p>
              </div>
              <div class="device-hero-right">
                <span class="badge" :class="deviceDetail.online ? 'badge-mint' : 'badge-sub'">
                  <span class="dot" :class="{ on: deviceDetail.online }"></span>{{ deviceDetail.online ? '在线' : '离线' }}
                </span>
                <span v-if="deviceDetail.is_banned" class="badge badge-danger">已封禁</span>
                <p class="cell-sub">归属：{{ deviceDetail.owner_nickname || deviceDetail.owner_email || '未绑定' }}</p>
              </div>
            </div>

            <!-- 运行时指标（与仪表盘同款卡片风格） -->
            <div class="stat-grid" style="grid-template-columns:repeat(3,1fr);gap:10px">
              <div class="stat-card" style="padding:10px 12px">
                <p class="stat-value" style="font-size:20px;color:var(--mint-deep)">{{ deviceDetail.online ? formatDuration(deviceDetail.online_seconds) : '—' }}</p>
                <p class="stat-label">本次在线时长</p>
              </div>
              <div class="stat-card" style="padding:10px 12px">
                <p class="stat-value" style="font-size:20px">{{ stateText }}</p>
                <p class="stat-label">设备状态</p>
              </div>
              <div class="stat-card" style="padding:10px 12px">
                <p class="stat-value" style="font-size:20px">{{ deviceDetail.ota_updating ? (deviceDetail.ota_progress || 0) + '%' : '空闲' }}</p>
                <p class="stat-label">OTA 升级{{ deviceDetail.ota_updating ? '中' : '未进行' }}</p>
                <div v-if="deviceDetail.ota_updating" class="ota-progress">
                  <div class="ota-bar">
                    <div class="ota-bar-fill" :style="{ width: (deviceDetail.ota_progress || 0) + '%' }"></div>
                  </div>
                  <p class="ota-status">{{ otaStatusText }}</p>
                </div>
              </div>
            </div>

            <div class="row-actions" style="margin:10px 0 0;justify-content:flex-start">
              <button class="btn btn-ghost btn-sm" :disabled="otaChecking" @click="checkOtaUpdate">
                {{ otaChecking ? '检测中…' : '检测升级' }}
              </button>
              <button class="btn btn-mint btn-sm" :disabled="!deviceDetail.online || otaForcing" @click="forceOtaUpdate">
                {{ otaForcing ? '下发中…' : '强制 OTA 升级' }}
              </button>
            </div>

            <!-- 基本信息行 -->
            <div class="detail-rows">
              <div class="detail-row"><span class="detail-k">MAC / 标识</span><span class="cell-sub">{{ deviceDetail.mac || deviceDetail.device_key || '—' }}</span></div>
              <div class="detail-row"><span class="detail-k">固件版本</span>{{ deviceDetail.firmware_version || '—' }}</div>
              <div class="detail-row"><span class="detail-k">归属用户</span>
                <template v-if="deviceDetail.owner_email || deviceDetail.owner_nickname">
                  {{ deviceDetail.owner_nickname || deviceDetail.owner_email }}
                  <span class="cell-sub" v-if="deviceDetail.owner_nickname">（{{ deviceDetail.owner_email }}）</span>
                </template>
                <span v-else class="cell-muted">未绑定</span>
              </div>
              <div class="detail-row"><span class="detail-k">绑定时间</span>{{ deviceDetail.bound_at ? formatDate(deviceDetail.bound_at) : '未知（早期绑定）' }}</div>
              <div class="detail-row"><span class="detail-k">首次注册</span>{{ formatDate(deviceDetail.created_at) }}</div>
              <div class="detail-row"><span class="detail-k">最后活跃</span>{{ formatDate(deviceDetail.last_seen) }}</div>
              <div class="detail-row"><span class="detail-k">最后唤醒</span>{{ deviceDetail.last_wakeup_time ? formatDate(deviceDetail.last_wakeup_time) : '—' }}</div>
              <div class="detail-row"><span class="detail-k">会话 ID</span><span class="cell-sub">{{ deviceDetail.session_id || '—' }}</span></div>
              <div v-if="(deviceDetail.enabled_plugins || []).length" class="detail-row detail-row-full"
                   :class="{ clickable: true }" :title="devicePluginsExpanded ? '点击收起' : '点击展开'"
                   @click="devicePluginsExpanded = !devicePluginsExpanded">
                <span class="detail-k">已启用插件</span>
                <span v-if="!devicePluginsExpanded" class="plugin-chip">▸ {{ deviceDetail.enabled_plugins.length }} 个插件 · 点击展开</span>
                <span v-else class="plugin-list">{{ deviceDetail.enabled_plugins.join('、') }} <span class="plugin-collapse">▴ 收起</span></span>
              </div>
              <div v-else class="detail-row"><span class="detail-k">已启用插件</span><span class="cell-muted">无</span></div>
            </div>

            <div class="row-actions" style="margin-top:18px;justify-content:flex-end">
              <button class="btn btn-mint btn-sm" :disabled="!deviceDetail.online" @click="wakeupDevice(deviceDetail); refreshDetail()">远程唤醒</button>
              <button class="btn btn-ghost btn-sm" @click="refreshDetail">刷新</button>
            </div>
          </template>
        </div>
      </div>
    </div>

    <!-- 后台任务明细弹窗 -->
    <div v-if="taskDetailVisible" class="modal-mask" @click.self="taskDetailVisible = false">
      <div class="modal-card">
        <div class="modal-head">
          <span class="modal-title">后台任务明细（{{ taskDetailList.length }} 个实例）</span>
          <button class="modal-close" @click="taskDetailVisible = false">×</button>
        </div>
        <div class="modal-body">
          <p class="modal-tip">服务器当前正在运行的后台异步任务（记忆落盘、音频预热等），打开弹窗时实时获取</p>
          <div v-if="loadingTaskDetail" class="modal-empty">获取中…</div>
          <template v-else>
            <div class="section-subtitle" style="font-size:13px">正在运行（{{ taskDetailList.reduce((n, g) => n + g.count, 0) }} 个）</div>
            <div v-if="!taskDetailList.length" class="modal-empty" style="margin-bottom:16px">当前没有正在运行的后台任务</div>
            <table v-else class="task-table" style="margin-bottom:16px">
              <thead><tr><th>任务名称</th><th>实例数</th><th>最长运行</th></tr></thead>
              <tbody>
                <tr v-for="g in taskDetailList" :key="g.name">
                  <td>{{ g.name }}</td>
                  <td>× {{ g.count }}</td>
                  <td class="cell-muted">{{ g.maxElapsed }}s</td>
                </tr>
              </tbody>
            </table>
            <div class="section-subtitle" style="font-size:13px">最近完成（最新 {{ recentTaskList.length }} 条）</div>
            <div v-if="!recentTaskList.length" class="modal-empty">暂无完成记录（服务启动后还没有后台任务跑完）</div>
            <table v-else class="task-table">
              <thead><tr><th>任务名称</th><th>耗时</th><th>结果</th><th>完成时间</th></tr></thead>
              <tbody>
                <tr v-for="(t, i) in recentTaskList" :key="i">
                  <td>{{ t.name }}</td>
                  <td class="cell-muted">{{ t.elapsed }}s</td>
                  <td><span class="badge" :class="t.success ? 'badge-mint' : 'badge-danger'">{{ t.success ? '完成' : '失败' }}</span></td>
                  <td class="cell-muted">{{ formatChatTime(t.ended_at) }}</td>
                </tr>
              </tbody>
            </table>
          </template>
        </div>
        <div class="modal-foot">
          <button class="btn btn-ghost" @click="taskDetailVisible = false">关闭</button>
        </div>
      </div>
    </div>

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

    <!-- 重命名设备弹窗 -->
    <div v-if="renameModalVisible" class="modal-mask" @click.self="renameModalVisible = false">
      <div class="modal-card" style="max-width:420px">
        <div class="modal-head">
          <span class="modal-title">重命名设备</span>
          <button class="modal-close" @click="renameModalVisible = false">×</button>
        </div>
        <div class="modal-body">
          <p class="modal-tip">为「{{ renameTarget?.device_id }}」设置新名称</p>
          <input v-model="renameInput" class="input" placeholder="设备名称（留空则清除为未命名）"
                 @keyup.enter="submitRenameDevice" style="width:100%" />
        </div>
        <div class="modal-foot">
          <button class="btn btn-ghost" @click="renameModalVisible = false">取消</button>
          <button class="btn btn-mint" :disabled="savingDevice" @click="submitRenameDevice">{{ savingDevice ? '保存中…' : '保存' }}</button>
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
import { ref, computed, onMounted, watch, nextTick } from 'vue'
import { api, getUser, getToken } from '../api'

const emit = defineEmits(['toast', 'back'])

const section = ref('stats')
const stats = ref({})
const metrics = ref(null)
const reloadingPlugins = ref(false)
const dailyCost = ref([])
const loadingDailyCost = ref(false)

const users = ref([])
const loadingUsers = ref(false)
const editingUser = ref('')
const editForm = ref({})
const savingUser = ref(false)

const devices = ref([])
const loadingDevices = ref(false)
const savingDevice = ref(false)
const renameModalVisible = ref(false)
const renameTarget = ref(null)
const renameInput = ref('')
const deviceOwnerFilter = ref('')
const registrySnapshot = ref([])

// 按用户筛选设备：user_id → {nickname, email, count}
const deviceOwners = computed(() => {
  const map = new Map()
  for (const d of devices.value) {
    if (!d.user_id) continue
    const cur = map.get(d.user_id) || { user_id: d.user_id, nickname: d.owner_nickname || '', email: d.owner_email || '', count: 0 }
    cur.count++
    if (!cur.nickname && d.owner_nickname) cur.nickname = d.owner_nickname
    if (!cur.email && d.owner_email) cur.email = d.owner_email
    map.set(d.user_id, cur)
  }
  return [...map.values()].sort((a, b) => b.count - a.count)
})

const filteredDevices = computed(() => {
  if (!deviceOwnerFilter.value) return devices.value
  if (deviceOwnerFilter.value === '__unbound__') return devices.value.filter(d => !d.user_id)
  return devices.value.filter(d => d.user_id === deviceOwnerFilter.value)
})

const currentUserId = computed(() => getUser()?.user_id || '')
const sectionTitle = computed(() => ({ stats: '仪表盘', users: '用户管理', devices: '设备管理', plugins: '插件管理', market: '市场管理', firmware: '固件管理', system: '系统运维', site: '网站设置', billing: '计费系统', conversations: '对话记录', ws_monitor: '连接监控', health: '健康检查', oplogs: '操作日志', emojis: '表情包', tasks: '定时任务', export: '数据导出' }[section.value] || ''))
	const sectionSub = computed(() => ({
	  stats: '系统总览与服务性能',
	  users: '管理角色、设备上限与账号状态',
	  devices: '查看全部设备与归属，支持重命名、解绑、封禁',
	  plugins: '上传 zip 安装插件、更新、卸载、热加载',
	  market: '管理插件上下架与推荐状态',
	  firmware: '上传固件、登记 bin_id、管理 OTA 比对目标',
	  system: '数据库备份与服务日志',
	  site: '配置网站名称、Logo、页脚等公开信息',
	  billing: '配置计费单价，查看各会话用量与费用',
	  llm_configs: '查看和编辑各设备的 LLM/ASR/TTS 配置',
	  conversations: '浏览所有设备的对话历史记录',
  ws_monitor: '实时查看 WebSocket 连接状态',
	  health: '一键检测系统各组件运行状态',
	  oplogs: '管理员操作审计日志',
	  emojis: '管理全局表情包库',
	  tasks: '管理服务端定时任务',
	  export: '导出用户/设备数据为 CSV',
	}[section.value] || ''))

const detailModalVisible = ref(false)
const deviceDetail = ref(null)
const loadingDetail = ref(false)
const detailDeviceId = ref('')
const devicePluginsExpanded = ref(false)

const otaChecking = ref(false)
const otaForcing = ref(false)

// 检测升级：服务端比对该设备固件版本与 OTA 目标配置
async function checkOtaUpdate() {
  otaChecking.value = true
  try {
    const res = await api.adminDeviceOtaCheck(detailDeviceId.value)
    if (res.status === 200 && res.data?.code === 0) {
      const d = res.data.data
      if (d.has_update) emit('toast', `发现新版本 ${d.target_version}（当前 ${d.current_version}），可执行强制升级`)
      else emit('toast', d.reason || '已是最新版本')
    } else emit('toast', res.data?.message || '检测失败')
  } catch { emit('toast', '检测失败') }
  otaChecking.value = false
}

// 强制升级：直接下发固件 URL，设备收到即下载刷写（跳过版本比对）
async function forceOtaUpdate() {
  const ok = await showConfirm({
    title: '强制 OTA 升级',
    message: '设备将立即从服务端配置的地址下载固件并刷写，升级期间设备会重启。确定继续吗？',
    confirmText: '确认升级', danger: false,
  })
  if (!ok) return
  otaForcing.value = true
  try {
    const res = await api.adminDeviceOtaForce(detailDeviceId.value)
    if (res.status === 200 && res.data?.code === 0) {
      emit('toast', res.data.message || '升级指令已下发')
      startDetailPoll()  // 指令经 keepalive 下发，设备开始升级后持续轮询进度
    } else emit('toast', res.data?.message || res.data?.detail || '下发失败')
  } catch { emit('toast', '下发失败') }
  otaForcing.value = false
}

// 设备状态中文映射（后端上报 FSM 枚举；离线时无状态可报）
const stateText = computed(() => {
  const d = deviceDetail.value
  if (!d) return '—'
  if (!d.online) return '离线'
  const map = { idle: '待机中', asr: '聆听中', llm: '思考中', tts: '说话中' }
  return map[d.device_state] || d.device_state || '未知'
})

// OTA 进度阶段文案（按百分比区分下载/刷写/重启）
const otaStatusText = computed(() => {
  const p = deviceDetail.value?.ota_progress || 0
  if (p >= 100) return '刷写完成，设备重启中…'
  if (p > 0) return '固件下载中…'
  return '等待设备开始下载…'
})

function formatDuration(seconds) {
  if (seconds == null) return '—'
  const s = Math.floor(seconds)
  const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60)
  if (d > 0) return `${d} 天 ${h} 小时 ${m} 分`
  if (h > 0) return `${h} 小时 ${m} 分 ${s % 60} 秒`
  return `${m} 分 ${s % 60} 秒`
}

let detailPollTimer = null
let detailPollTicks = 0

function stopDetailPoll() {
  if (detailPollTimer) { clearInterval(detailPollTimer); detailPollTimer = null }
}

function startDetailPoll() {
  stopDetailPoll()
  detailPollTicks = 0
  detailPollTimer = setInterval(async () => {
    detailPollTicks++
    if (!detailModalVisible.value) { stopDetailPoll(); return }
    await refreshDetail(true)
    // 升级未开始（指令还在下发路上）最多等 60 轮（90s）；开始升级后持续轮询到结束
    if (!deviceDetail.value?.ota_updating && detailPollTicks > 60) stopDetailPoll()
  }, 1500)
}

async function openDeviceDetail(d) {
  detailDeviceId.value = d.device_id
  deviceDetail.value = d  // 先用列表数据占位
  devicePluginsExpanded.value = false
  detailModalVisible.value = true
  await refreshDetail()
  // 打开时设备已在升级 → 持续轮询进度
  if (deviceDetail.value?.ota_updating) startDetailPoll()
}

async function refreshDetail(silent = false) {
  if (!detailDeviceId.value) return
  if (!silent) loadingDetail.value = true
  try {
    const res = await api.adminDeviceDetail(detailDeviceId.value)
    if (res.status === 200 && res.data?.code === 0) deviceDetail.value = res.data.data
    else if (!silent) emit('toast', '加载设备详情失败')
  } catch { if (!silent) emit('toast', '加载设备详情失败') }
  if (!silent) loadingDetail.value = false
}

async function wakeupDevice(d) {
  try {
    const res = await api.adminDeviceWakeup(d.device_id)
    if (res.status === 200 && res.data?.code === 0) emit('toast', `已发送唤醒指令到「${d.name || d.device_id}」`)
    else emit('toast', res.data?.message || res.data?.detail || '唤醒失败')
  } catch { emit('toast', '唤醒失败') }
}

const taskDetailVisible = ref(false)
const taskDetailList = ref([])
const recentTaskList = ref([])
const loadingTaskDetail = ref(false)

// 点击时实时请求最新指标（卡片数字来自上次刷新的快照，直接用会与明细对不上）
async function openTaskDetail() {
  taskDetailVisible.value = true
  loadingTaskDetail.value = true
  try {
    const res = await api.adminMetrics()
    if (res.status === 200 && res.data?.code === 0) {
      const conc = res.data.data?.concurrency || {}
      metrics.value = res.data.data  // 同步刷新卡片数字，保持一致
      recentTaskList.value = conc.recent_task_list || []
      const list = conc.active_task_list || []
      // 按任务名称聚合：同名任务（如多个会话的 memory_save）计一条，显示实例数和最长运行时长
      const map = new Map()
      for (const t of list) {
        const cur = map.get(t.name) || { name: t.name, count: 0, maxElapsed: 0 }
        cur.count++
        if ((t.elapsed || 0) > cur.maxElapsed) cur.maxElapsed = t.elapsed
        map.set(t.name, cur)
      }
      taskDetailList.value = [...map.values()].sort((a, b) => b.count - a.count)
    }
  } catch { /* 弹窗内显示空态即可 */ }
  loadingTaskDetail.value = false
}

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

// 固件管理
const firmwares = ref([])
const loadingFirmwares = ref(false)
const uploadingFw = ref(false)
const fwFile = ref(null)
const fwBinIdMode = ref('auto')
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
  if (fwBinIdMode.value === 'custom' && !fwBinId.value.trim()) { emit('toast', '请填写固件 bin_id'); return }
  uploadingFw.value = true
  try {
    const res = await api.adminFirmwareUpload(fwFile.value, fwBinId.value.trim(), fwVersion.value.trim(), fwBinIdMode.value)
    if (res.status === 200 && res.data?.code === 0) {
      const bid = res.data.data?.bin_id || ''
      emit('toast', (res.data.message || '固件已上传并设为启用中') + (bid ? `（bin_id: ${bid}）` : ''))
      fwFile.value = null; fwBinId.value = ''; fwVersion.value = ''
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
const showBackups = ref(false)

function toggleBackups() {
  showBackups.value = !showBackups.value
  if (showBackups.value && !backups.value.length) loadBackups()
}
const broadcastText = ref('')

// 网站设置
const siteForm = ref({ site_name: '', site_subtitle: '', site_logo: '', site_footer: '', site_icp: '', login_welcome: '' })
const savingSite = ref(false)

async function loadSiteSettings() {
  const res = await api.adminSiteSettings()
  if (res.status === 200 && res.data?.code === 0) {
    siteForm.value = { ...siteForm.value, ...(res.data.data || {}) }
  }
}

async function saveSiteSettings() {
  savingSite.value = true
  try {
    const res = await api.adminSaveSiteSettings({ ...siteForm.value })
    if (res.status === 200 && res.data?.code === 0) {
      emit('toast', res.data.message || '网站设置已保存')
      siteForm.value = { ...siteForm.value, ...(res.data.data || {}) }
    } else {
      emit('toast', res.data?.message || res.data?.detail || '保存失败')
    }
  } catch { emit('toast', '保存失败') }
  savingSite.value = false
}

// 计费系统
const billingForm = ref({
  enabled: true,
  asr_price_per_hour: 1.0,
  llm_input_price_per_mtokens: 3.0,
  llm_input_cache_hit_price_per_mtokens: 0.1,
  llm_output_price_per_mtokens: 9.0,
  tts_price_per_kchars: 0.5,
  peak_offpeak_enabled: true,
  offpeak_discount: 0.5,
  peak_windows: [['09:00', '12:00'], ['14:00', '18:00']],
})
const savingBilling = ref(false)
const billingStats = ref({})
const billingRecords = ref([])
const loadingBilling = ref(false)
const billingPage = ref(1)
const billingTotal = ref(0)
const billingTotalPages = ref(1)
const billingConfigOpen = ref(false)
const billingSearch = ref('')
// 页码列表（当前页前后各 1 页 + 首尾页，中间用省略号）
const billingPageList = computed(() => {
  const total = billingTotalPages.value
  const cur = billingPage.value
  const pages = []
  const push = (p) => { if (pages[pages.length - 1] !== p) pages.push(p) }
  for (let i = 1; i <= total; i++) {
    if (i === 1 || i === total || Math.abs(i - cur) <= 1) push(i)
    else if (pages[pages.length - 1] !== '…') push('…')
  }
  return pages
})

function fmtNum(n) {
  if (n == null) return '—'
  return Number(n).toLocaleString('zh-CN')
}

// 大数自动转换：>=1万 显示 X.X万，>=1亿 显示 X.X亿（LLM tokens / TTS 字数会持续增长）
function fmtBigNum(n) {
  if (n == null) return '—'
  n = Number(n)
  if (n >= 100000000) return trimBigNum(n / 100000000) + '亿'
  if (n >= 10000) return trimBigNum(n / 10000) + '万'
  return n.toLocaleString('zh-CN')
}
function trimBigNum(v) {
  return parseFloat(v.toFixed(2)).toString()
}

async function loadBillingConfig() {
  try {
    const res = await api.adminBillingConfig()
    if (res.status === 200 && res.data?.code === 0) billingForm.value = { ...billingForm.value, ...(res.data.data || {}) }
  } catch { /* 忽略 */ }
}

async function saveBillingConfig() {
  savingBilling.value = true
  try {
    const res = await api.adminSaveBillingConfig({ ...billingForm.value })
    if (res.status === 200 && res.data?.code === 0) {
      emit('toast', res.data.message || '计费配置已保存')
      billingForm.value = { ...billingForm.value, ...(res.data.data || {}) }
    } else {
      emit('toast', res.data?.message || res.data?.detail || '保存失败')
    }
  } catch { emit('toast', '保存失败') }
  savingBilling.value = false
}

async function loadBillingStats() {
  try {
    const res = await api.adminBillingStats()
    if (res.status === 200 && res.data?.code === 0) billingStats.value = res.data.data || {}
  } catch { /* 忽略 */ }
}

async function loadBillingRecords() {
  loadingBilling.value = true
  try {
    const res = await api.adminBillingRecords({ page: billingPage.value, page_size: 15, device_id: billingSearch.value.trim() })
    if (res.status === 200 && res.data?.code === 0) {
      billingRecords.value = res.data.data?.records || []
      billingTotal.value = res.data.data?.total || 0
      billingTotalPages.value = Math.max(1, Math.ceil(billingTotal.value / 15))
      if (billingPage.value > billingTotalPages.value) {
        billingPage.value = billingTotalPages.value
        await loadBillingRecords()
        return
      }
    }
  } catch { /* 忽略 */ }
  loadingBilling.value = false
}

function searchBillingRecords() {
  billingPage.value = 1
  loadBillingRecords()
}

function loadBilling() {
  loadBillingConfig()
  loadBillingStats()
  loadBillingRecords()
}

// 新增板块状态
const conversations = ref([])
const loadingConvs = ref(false)
const convDeviceFilter = ref('')
const allDevices = ref([])
const wsConnections = ref([])
const loadingWs = ref(false)
const healthResult = ref(null)
const checkingHealth = ref(false)
const opLogs = ref([])
const loadingOplogs = ref(false)
const opPage = ref(1)
const opTotal = ref(0)
const opTotalPages = ref(1)
const emojiPacks = ref([])
const loadingEmojis = ref(false)
const scheduledTasks = ref([])
	const loadingTasks = ref(false)
	const showTaskModal = ref(false)
	const savingTask = ref(false)
	const taskForm = ref({ name: '', type: 'cron', schedule: '', action: '' })

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

async function loadDailyCost() {
  loadingDailyCost.value = true
  try {
    const res = await api.adminBillingDaily({ days: 7 })
    if (res.status === 200 && res.data?.code === 0) dailyCost.value = res.data.data?.daily || []
  } catch { /* 忽略 */ }
  loadingDailyCost.value = false
}

// 柱状图：按最大值归一化高度，最小 4% 保证有柱
function barHeight(v) {
  const max = Math.max(...dailyCost.value.map(d => d.total_cost), 0.0001)
  return Math.max(4, (Number(v) / max) * 100)
}
function fmtCost(v) {
  if (v == null) return '—'
  return '¥' + Number(v).toFixed(2)
}
function fmtDay(dateStr) {
  const d = new Date(dateStr + 'T00:00:00')
  return (d.getMonth() + 1) + '/' + d.getDate()
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
    if (res.status === 200 && res.data?.code === 0) {
      devices.value = res.data.data?.devices || []
      registrySnapshot.value = res.data.data?.registry_devices || []
    }
    else emit('toast', res.data?.message || res.data?.detail || '加载设备失败')
  } catch { emit('toast', '加载设备失败') }
  loadingDevices.value = false
}

function loadAll() { loadStats(); loadMetrics(); loadDailyCost(); loadUsers(); loadDevices() }

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

function openRenameDevice(d) {
  renameTarget.value = d
  renameInput.value = d.name || ''
  renameModalVisible.value = true
}

async function submitRenameDevice() {
  const d = renameTarget.value
  if (!d) return
  savingDevice.value = true
  try {
    const res = await api.adminUpdateDevice(d.device_id, { name: renameInput.value })
    if (res.status === 200 && res.data?.code === 0) {
      emit('toast', '设备已重命名')
      renameModalVisible.value = false
      renameTarget.value = null
      loadDevices()
      if (detailModalVisible.value) refreshDetail()
    } else emit('toast', res.data?.message || res.data?.detail || '保存失败')
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
    if (res.status === 200 && res.data?.code === 0) {
      logLines.value = res.data.data?.lines || []
      // 最新日志在尾部：渲染后滚到底部
      await nextTick()
      const el = document.querySelector('.log-view')
      if (el) el.scrollTop = el.scrollHeight
    } else emit('toast', res.data?.message || res.data?.detail || '加载日志失败')
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

// 设备封禁/解封
async function banDevice(d) {
  const reason = prompt('请输入封禁原因（可选）:', '')
  if (reason === null) return
  try {
    const res = await api.adminBanDevice(d.device_id, reason)
    if (res.status === 200 && res.data?.code === 0) { emit('toast', '设备已封禁'); loadDevices() }
    else emit('toast', res.data?.message || res.data?.detail || '封禁失败')
  } catch { emit('toast', '封禁失败') }
}

async function unbanDevice(d) {
  const ok = await showConfirm({ title: '解封设备', message: `确定解封设备「${d.name || d.device_id}」吗？`, confirmText: '确认解封', danger: false })
  if (!ok) return
  try {
    const res = await api.adminUnbanDevice(d.device_id)
    if (res.status === 200 && res.data?.code === 0) { emit('toast', '设备已解封'); loadDevices() }
    else emit('toast', res.data?.message || res.data?.detail || '解封失败')
  } catch { emit('toast', '解封失败') }
}

// 对话记录
async function loadConversations() {
  loadingConvs.value = true
  try {
    const params = convDeviceFilter.value ? { device_id: convDeviceFilter.value } : {}
    const res = await api.adminConversations(params)
    if (res.status === 200 && res.data?.code === 0) {
      conversations.value = (res.data.data?.conversations || []).map(c => ({
        ...c,
        // 显式按时间升序：最新消息固定在最下面（微信习惯）
        messages: [...(c.messages || [])].sort((a, b) => (a.timestamp || 0) - (b.timestamp || 0)),
      }))
      // 渲染后滚动到底部，直接看到最新消息
      await nextTick()
      document.querySelectorAll('.chat-list').forEach(el => { el.scrollTop = el.scrollHeight })
    } else emit('toast', '加载对话记录失败')
  } catch { emit('toast', '加载对话记录失败') }
  loadingConvs.value = false
}

// WebSocket 状态
async function loadWsStatus() {
  loadingWs.value = true
  try {
    const res = await api.adminWsStatus()
    if (res.status === 200 && res.data?.code === 0) wsConnections.value = res.data.data?.connections || []
    else emit('toast', '加载连接状态失败')
  } catch { emit('toast', '加载连接状态失败') }
  loadingWs.value = false
}

// 健康检查
async function runHealthCheck() {
  checkingHealth.value = true
  try {
    const res = await api.adminHealth()
    if (res.status === 200 && res.data?.code === 0) healthResult.value = res.data.data
    else emit('toast', '健康检查失败')
  } catch { emit('toast', '健康检查失败') }
  checkingHealth.value = false
}

function fmtSvc(s) {
  if (!s) return '—'
  if (s.status === 'ok') return `正常(${s.latency_ms}ms)`
  if (s.status === 'skipped') return '未配置'
  return '异常'
}

function formatHealthDetail(check) {
  if (check.llm !== undefined) return `LLM ${fmtSvc(check.llm)} / TTS ${fmtSvc(check.tts)} / ASR ${fmtSvc(check.asr)}`
  if (check.status === 'ok') {
    if (check.latency_ms !== undefined) return `延迟 ${check.latency_ms}ms`
    if (check.free_gb !== undefined) return `总量 ${check.total_gb}GB, 剩余 ${check.free_gb}GB, 使用 ${check.usage_pct}%`
    if (check.device_count !== undefined) return `${check.device_count} 个设备`
    if (check.asr_configured !== undefined) return `ASR ${check.asr_configured} / LLM ${check.llm_configured} / TTS ${check.tts_configured}`
    if (check.process_memory_mb !== undefined) return `进程内存 ${check.process_memory_mb}MB / CPU ${check.process_cpu_pct}% / 系统内存 ${check.system_memory_used_pct}%`
    if (check.online_devices !== undefined) return `在线 ${check.online_devices} 台 / ASR池 ${check.asr_pools} / TTS池 ${check.tts_pools} / 30分钟错误 ${check.errors_last_30m}`
    return '正常'
  }
  if (check.status === 'skipped') return check.reason || '跳过'
  return check.message || '异常'
}

// 操作日志
async function loadOpLogs() {
  loadingOplogs.value = true
  try {
    const res = await api.adminOpLogs({ page: opPage.value, page_size: 20 })
    if (res.status === 200 && res.data?.code === 0) {
      const d = res.data.data || {}
      opLogs.value = d.logs || []
      opTotal.value = d.total || 0
      opTotalPages.value = d.total_pages || 1
      // 当前页被删空时回退一页
      if (!opLogs.value.length && opPage.value > 1) { opPage.value--; loadOpLogs(); return }
    } else emit('toast', '加载操作日志失败')
  } catch { emit('toast', '加载操作日志失败') }
  loadingOplogs.value = false
}

// 表情包
async function loadEmojis() {
  loadingEmojis.value = true
  try {
    const res = await api.adminEmojis()
    if (res.status === 200 && res.data?.code === 0) emojiPacks.value = res.data.data?.packs || []
    else emit('toast', '加载表情包失败')
  } catch { emit('toast', '加载表情包失败') }
  loadingEmojis.value = false
}

async function deleteEmoji(name) {
  const ok = await showConfirm({ title: '删除表情包', message: `确定删除表情包「${name}」吗？`, confirmText: '确认删除', danger: true })
  if (!ok) return
  try {
    const res = await api.adminDeleteEmoji(name)
    if (res.status === 200 && res.data?.code === 0) { emit('toast', '表情包已删除'); loadEmojis() }
    else emit('toast', '删除失败')
  } catch { emit('toast', '删除失败') }
}

async function deleteEmojiFile(packName, filename) {
  const ok = await showConfirm({ title: '删除表情', message: `确定删除「${filename}」吗？`, confirmText: '确认删除', danger: true })
  if (!ok) return
  try {
    const res = await api.adminDeleteEmojiFile(packName, filename)
    if (res.status === 200 && res.data?.code === 0) { emit('toast', '表情已删除'); loadEmojis() }
    else emit('toast', '删除失败')
  } catch { emit('toast', '删除失败') }
}

// 定时任务
async function loadScheduledTasks() {
  loadingTasks.value = true
  try {
    const res = await api.adminScheduledTasks()
    if (res.status === 200 && res.data?.code === 0) scheduledTasks.value = res.data.data?.tasks || []
    else emit('toast', '加载定时任务失败')
  } catch { emit('toast', '加载定时任务失败') }
  loadingTasks.value = false
}

async function deleteScheduledTask(id) {
  const ok = await showConfirm({ title: '删除定时任务', message: '确定删除此定时任务吗？', confirmText: '确认删除', danger: true })
  if (!ok) return
  try {
    const res = await api.adminDeleteScheduledTask(id)
    if (res.status === 200 && res.data?.code === 0) { emit('toast', '定时任务已删除'); loadScheduledTasks() }
    else emit('toast', '删除失败')
  } catch { emit('toast', '删除失败') }
}

async function createScheduledTask() {
  if (!taskForm.value.name) { emit('toast', '请输入任务名称'); return }
  if (!taskForm.value.schedule) { emit('toast', '请输入执行计划'); return }
  savingTask.value = true
  try {
    const res = await api.adminCreateScheduledTask({ ...taskForm.value })
    if (res.status === 200 && res.data?.code === 0) {
      emit('toast', '定时任务已创建')
      showTaskModal.value = false
      taskForm.value = { name: '', type: 'cron', schedule: '', action: '' }
      loadScheduledTasks()
    } else emit('toast', res.data?.message || '创建失败')
  } catch { emit('toast', '创建失败') }
  savingTask.value = false
}

// 数据导出
function exportData(type) {
  const token = getToken()
  fetch(`/api/v1/admin/export/${type}`, {
    headers: { Authorization: 'Bearer ' + token }
  })
  .then(r => { if (!r.ok) throw new Error(); return r.blob() })
  .then(blob => {
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob); a.download = type + '.csv'; a.click()
    URL.revokeObjectURL(a.href)
  })
  .catch(() => emit('toast', '导出失败'))
}

// 加载所有设备（用于过滤器）
async function loadAllDevices() {
  try {
    const res = await api.adminDevices()
    if (res.status === 200 && res.data?.code === 0) allDevices.value = res.data.data?.devices || []
  } catch {}
}

// 聊天时间：今天只显示 时:分，昨天显示"昨天 时:分"，更早显示 日期 时:分
function formatChatTime(ts) {
  if (!ts) return ''
  const d = new Date(ts * 1000)
  const now = new Date()
  const p = n => String(n).padStart(2, '0')
  const hm = `${p(d.getHours())}:${p(d.getMinutes())}`
  const sameDay = d.toDateString() === now.toDateString()
  if (sameDay) return hm
  const yesterday = new Date(now); yesterday.setDate(now.getDate() - 1)
  if (d.toDateString() === yesterday.toDateString()) return `昨天 ${hm}`
  return `${d.getMonth() + 1}-${p(d.getDate())} ${hm}`
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
  else if (val === 'firmware') loadFirmwares()
  else if (val === 'system') { loadSystemInfo(); loadBackups(); loadLogs() }
  else if (val === 'site') loadSiteSettings()
  else if (val === 'billing') loadBilling()
  else if (val === 'conversations') { loadAllDevices(); loadConversations() }
  else if (val === 'ws_monitor') loadWsStatus()
  else if (val === 'oplogs') loadOpLogs()
  else if (val === 'emojis') loadEmojis()
  else if (val === 'tasks') loadScheduledTasks()
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
.stat-value { font-size: 28px; font-weight: 800; line-height: 1.1; letter-spacing: -0.5px; overflow-wrap: anywhere; word-break: break-word; }
.stat-info { min-width: 0; }
.stat-card { min-width: 0; }
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

/* ===== 近 7 天费用柱状图 ===== */
.chart-card {
  margin-top: 20px;
  padding: 20px 24px 24px;
  background: var(--grad-card);
  backdrop-filter: var(--glass-blur);
  -webkit-backdrop-filter: var(--glass-blur);
  border: 1px solid var(--glass-border);
  box-shadow: var(--shadow), var(--glass-hi);
  border-radius: var(--radius-lg);
}
.chart-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 8px;
}
.bar-chart {
  display: flex;
  align-items: stretch;
  gap: 10px;
  height: 360px;
  padding-top: 26px;
}
.bar-col {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  min-width: 0;
}
.bar-track {
  flex: 1;
  width: 100%;
  display: flex;
  align-items: flex-end;
  justify-content: center;
}
.bar-fill {
  position: relative;
  width: 58%;
  min-height: 4px;
  border-radius: 6px 6px 3px 3px;
  background: var(--grad-mint);
  box-shadow: var(--shadow-mint);
  transition: height .6s cubic-bezier(.22, .61, .36, 1);
}
.bar-fill:hover { filter: brightness(1.08); }
.bar-value {
  position: absolute;
  top: -22px;
  left: 50%;
  transform: translateX(-50%);
  font-size: 11px;
  color: var(--text-sub);
  white-space: nowrap;
}
.bar-label {
  font-size: 11px;
  color: var(--text-dim);
  white-space: nowrap;
}

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
.fw-mode-seg {
  display: inline-flex; padding: 3px; gap: 2px;
  background: var(--glass-bg-soft); border: 1px solid var(--glass-border);
  border-radius: 999px;
}
.fw-mode-btn {
  border: none; background: transparent; cursor: pointer;
  padding: 5px 14px; font-size: 12px; color: var(--text-sub);
  border-radius: 999px; transition: all .2s var(--ease);
}
.fw-mode-btn:hover { color: var(--mint-deep); }
.fw-mode-btn.active {
  background: var(--mint-soft); color: var(--mint-deep);
  border: 1px solid var(--mint-border); font-weight: 600;
  animation: fwModePulse 2s ease-in-out infinite;
}
@keyframes fwModePulse {
  0%, 100% { box-shadow: 0 0 0 0 var(--mint-softer); }
  50% { box-shadow: 0 0 0 4px var(--mint-softer); }
}
.upload-btn { cursor: pointer; }
.broadcast-input { width: 220px; }

/* 服务日志：备份卡片内的内嵌子卡片（浅色玻璃拟态，与主体一致） */
.log-block {
  margin: 0;
  border-top: 1px solid var(--glass-border-soft);
  border-radius: 0 0 var(--radius-lg) var(--radius-lg);
  overflow: hidden;
  background: #0d1117;
}
.log-view {
  max-height: 320px; overflow: auto;
  padding: 14px 18px; margin: 0;
  background: transparent;
  color: #c9d1d9;
  font-family: 'Cascadia Code', 'JetBrains Mono', Consolas, monospace;
  font-size: 12px; line-height: 1.6;
  white-space: pre-wrap; word-break: break-all;
  max-width: 100%; box-sizing: border-box;
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
.device-hero { display: flex; align-items: center; gap: 14px; padding-bottom: 14px; border-bottom: 1px solid var(--glass-border-soft); margin-bottom: 14px; }
.device-avatar-lg { width: 46px; height: 46px; border-radius: 12px; flex-shrink: 0; display: inline-flex; align-items: center; justify-content: center; background: var(--mint-soft); color: var(--mint-deep); }
.device-hero-right { margin-left: auto; text-align: right; display: flex; flex-direction: column; align-items: flex-end; gap: 4px; }
.detail-rows { display: grid; grid-template-columns: 1fr 1fr; gap: 6px 20px; margin-top: 10px; padding: 10px 14px; background: var(--glass-bg-soft); border-radius: var(--radius-md); }
.detail-rows .detail-row { min-width: 0; font-size: 12px; }
.detail-rows .cell-sub { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; display: inline-block; max-width: 100%; vertical-align: bottom; }
.detail-row-full { grid-column: 1 / -1; }
.ota-progress { margin-top: 8px; }
.ota-bar { height: 10px; border-radius: 5px; overflow: hidden; background: rgba(18, 33, 46, 0.1); position: relative; }
.ota-bar-fill { height: 100%; background: var(--grad-mint); border-radius: 5px; transition: width .4s var(--ease); position: relative; overflow: hidden; }
.ota-bar-fill::after { content: ''; position: absolute; inset: 0; background: linear-gradient(90deg, transparent, rgba(255,255,255,.35), transparent); animation: ota-shimmer 1.2s infinite; }
@keyframes ota-shimmer { 0% { transform: translateX(-100%); } 100% { transform: translateX(100%); } }
.ota-status { margin-top: 4px; font-size: 11px; color: var(--mint-deep); font-weight: 600; }
.detail-row-full.clickable { cursor: pointer; border-radius: 8px; transition: background .15s var(--ease); }
.detail-row-full.clickable:hover { background: var(--mint-softer); }
.plugin-chip {
  display: inline-flex; align-items: center;
  padding: 3px 10px; border-radius: 20px;
  background: var(--mint-soft); color: var(--mint-deep);
  font-size: 12px; font-weight: 600;
}
.plugin-list { color: var(--text-main); }
.plugin-collapse { color: var(--text-dim); font-size: 11px; margin-left: 8px; }
.device-hero { padding-bottom: 10px; margin-bottom: 10px; }
.device-avatar-lg { width: 38px; height: 38px; border-radius: 10px; }
.detail-row { display: flex; align-items: baseline; gap: 14px; font-size: 13px; color: var(--text-main); }
.detail-k { flex-shrink: 0; width: 88px; color: var(--text-dim); font-size: 12px; }
.task-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.task-table th, .task-table td { text-align: left; padding: 8px 10px; border-bottom: 1px solid var(--glass-border-soft); }
.task-table th { color: var(--text-dim); font-weight: 600; font-size: 12px; }
.modal-tip { margin-bottom: 12px; }
.modal-foot {
  display: flex; justify-content: flex-end; gap: 8px;
  padding: 14px 20px;
  border-top: 1px solid var(--glass-border-soft);
  background: var(--glass-bg-strong);
}
.modal-actions {
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
  .log-view { max-height: 150px; font-size: 11px; padding: 12px 14px; }
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
/* ===== 新增板块样式 ===== */
/* ===== 对话记录：微信式聊天气泡 ===== */
.chat-list { padding: 18px 20px; display: flex; flex-direction: column; gap: 14px; max-height: 560px; overflow-y: auto; }
.chat-row { display: flex; align-items: flex-start; gap: 10px; }
.chat-row.mine { flex-direction: row-reverse; }
.chat-avatar { width: 34px; height: 34px; border-radius: 8px; flex-shrink: 0; display: flex; align-items: center; justify-content: center; color: var(--text-dim); background: var(--glass-soft, rgba(0,0,0,0.04)); border: 1px solid var(--glass-border-soft); }
.chat-avatar.assistant { color: var(--mint-deep, #0d9488); }
.chat-avatar.user { color: var(--brand, #6366f1); }
.chat-bubble-wrap { display: flex; flex-direction: column; max-width: 72%; }
.chat-row.mine .chat-bubble-wrap { align-items: flex-end; }
.chat-bubble {
  padding: 9px 13px; border-radius: 12px; font-size: 13px; line-height: 1.6;
  word-break: break-word; white-space: pre-wrap; width: fit-content;
}
.chat-row:not(.mine) .chat-bubble {
  background: var(--glass-soft, rgba(0,0,0,0.04));
  border: 1px solid var(--glass-border-soft);
  border-top-left-radius: 4px;
}
.chat-row.mine .chat-bubble {
  background: var(--grad-mint, linear-gradient(135deg, #34d399, #0d9488));
  color: #fff;
  border-top-right-radius: 4px;
}
.chat-time { font-size: 11px; color: var(--text-dim); margin-top: 4px; padding: 0 4px; }
.status-badge { display: inline-flex; align-items: center; gap: 4px; padding: 2px 10px; border-radius: 20px; font-size: 11px; font-weight: 600; }
.status-badge.online { background: rgba(34,197,94,0.12); color: #16a34a; }
.status-badge.offline { background: rgba(239,68,68,0.1); color: #dc2626; }
.status-badge.skipped { background: rgba(148,163,184,0.12); color: #64748b; }
.form-label { font-size: 12px; font-weight: 600; color: var(--text-sub); margin-top: 8px; }
.form-label:first-child { margin-top: 0; }
.form-input { width: 100%; padding: 8px 12px; border: 1px solid var(--glass-border); border-radius: 8px; font-size: 13px; background: rgba(255,255,255,0.6); color: var(--text-main); outline: none; transition: border .2s; box-sizing: border-box; }
.form-input:focus { border-color: var(--mint); }
.form-checkbox { display: flex; align-items: center; gap: 8px; font-size: 13px; margin-top: 10px; cursor: pointer; }
.form-hint { display: block; font-size: 11px; color: var(--text-dim); margin: 2px 0 8px 0; line-height: 1.4; }
.card-body { padding: 24px; display: flex; flex-direction: column; gap: 16px; }

/* ===== 网站设置 ===== */
.site-form-card {
  background: var(--grad-card);
  backdrop-filter: var(--glass-blur);
  -webkit-backdrop-filter: var(--glass-blur);
  border: 1px solid var(--glass-border);
  box-shadow: var(--shadow), var(--glass-hi);
  border-radius: var(--radius-lg);
  overflow: hidden;
}
.site-form-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 18px 24px;
  border-bottom: 1px solid var(--glass-border);
  background: linear-gradient(180deg, rgba(255,255,255,0.5), rgba(255,255,255,0));
}
.collapse-arrow {
  display: inline-block;
  font-size: 12px;
  color: var(--text-dim);
  margin-left: 6px;
  transition: transform .25s ease;
  vertical-align: 2px;
}
.collapse-arrow.open {
  transform: rotate(180deg);
}
.site-form-body {
  padding: 8px 24px 24px;
  display: flex;
  flex-direction: column;
  gap: 2px;
  max-width: 720px;
}
.form-row { display: flex; flex-direction: column; }
.form-row .form-label { margin-top: 16px; }
.field-disabled { opacity: .45; pointer-events: none; }

/* ===== 表情包网格 ===== */
.emo-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 16px;
}
.emo-card {
  background: var(--grad-card);
  backdrop-filter: var(--glass-blur);
  -webkit-backdrop-filter: var(--glass-blur);
  border: 1px solid var(--glass-border);
  box-shadow: var(--shadow), var(--glass-hi);
  border-radius: var(--radius-lg);
  overflow: hidden;
  transition: all 0.2s var(--ease);
}
.emo-card:hover {
  box-shadow: var(--shadow-mint), var(--glass-hi);
  transform: translateY(-2px);
}
.emo-card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 16px 8px;
}
.emo-pack-name {
  font-size: 14px;
  font-weight: 700;
  color: var(--text-main);
}
.emo-pack-count {
  font-size: 12px;
  color: var(--text-sub);
}
.emo-previews {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 8px;
  padding: 8px 12px;
}
.emo-item-wrap {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
}
.emo-thumb {
  width: 100%;
  aspect-ratio: 1;
  object-fit: cover;
  border-radius: 6px;
  background: var(--glass-bg-strong);
  transition: transform 0.2s var(--ease);
}
.emo-thumb:hover {
  transform: scale(1.08);
  box-shadow: 0 2px 8px rgba(0,0,0,0.12);
}
.emo-del-btn {
  position: absolute;
  top: -4px;
  right: -4px;
  width: 20px;
  height: 20px;
  border-radius: 50%;
  border: none;
  background: #e74c3c;
  color: #fff;
  font-size: 14px;
  line-height: 1;
  cursor: pointer;
  display: none;
  align-items: center;
  justify-content: center;
  box-shadow: 0 1px 4px rgba(0,0,0,0.3);
  z-index: 2;
}
.emo-item-wrap:hover .emo-del-btn {
  display: flex;
}
.emo-name-label {
  font-size: 10px;
  color: var(--text-dim);
  text-align: center;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.emo-empty {
  grid-column: 1 / -1;
  padding: 20px;
  text-align: center;
  color: var(--text-dim);
  font-size: 12px;
}
.emo-card-actions {
  padding: 8px 16px 14px;
  display: flex;
  gap: 8px;
}

/* ===== 创建定时任务弹窗 ===== */
.modal-overlay {
  position: fixed; inset: 0;
  background: rgba(0,0,0,0.3);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}
.modal-card {
  background: rgba(255,255,255,0.95);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  border: 1px solid var(--glass-border);
  border-radius: var(--radius-lg);
  box-shadow: 0 20px 60px rgba(0,0,0,0.15);
  padding: 28px;
  width: 90%;
  max-width: 480px;
}
.modal-title {
  font-size: 17px;
  font-weight: 700;
  margin-bottom: 20px;
}
.modal-actions {
  display: flex;
  gap: 8px;
  justify-content: flex-end;
  margin-top: 20px;
}
        </style>