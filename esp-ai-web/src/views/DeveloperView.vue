<template>
  <div class="dev-view" :class="{ 'editor-open': codeEditor.show }">
    <!-- 未登录 -->
    <div v-if="!isLoggedInUser" class="empty glass card-in">
      <div class="empty-icon">
        <svg width="56" height="56" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.2" stroke-linecap="round">
          <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/>
          <circle cx="12" cy="7" r="4"/>
        </svg>
      </div>
      <h3 class="empty-title">欢迎来到开发者中心</h3>
      <p class="empty-desc">登录后即可创建和管理你的插件，分享给所有用户</p>
    </div>

    <!-- 已登录但未开启开发者 -->
    <div v-else-if="!devInfo.is_developer" class="enable-dev glass card-in">
      <div class="enable-dev-visual">
        <div class="enable-dev-icon">
          <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.2" stroke-linecap="round">
            <path d="M12 2L2 7l10 5 10-5-10-5z"/>
            <path d="M2 17l10 5 10-5"/>
            <path d="M2 12l10 5 10-5"/>
          </svg>
        </div>
        <div class="enable-dev-glow"></div>
      </div>
      <div class="enable-dev-content">
        <h3>开启开发者之旅</h3>
        <p>用你的账号即可上传插件到市场，无需额外注册</p>
        <div class="enable-dev-tags">
          <span class="tag">上传管理</span>
          <span class="tag">发布市场</span>
          <span class="tag">在线编辑</span>
        </div>
        <button class="btn-mint enable-dev-btn" :disabled="devLoading" @click="enableDev">
          {{ devLoading ? '处理中…' : '立即开启' }}
        </button>
      </div>
    </div>

    <!-- 已是开发者 -->
	    <div v-else>
	      <!-- ===== 代码编辑器（页面主体，替代模态框） ===== -->
	      <div v-if="codeEditor.show" class="editor-page" :class="{ fullscreen: editorFullscreen }">
	        <!-- 顶栏 -->
	        <div class="editor-topbar glass">
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
          </div>
          <div class="editor-topbar-right">
            <button class="fullscreen-btn" :title="editorFullscreen ? '退出全屏 (Esc)' : '全屏编辑'"
              @click="toggleFullscreen">
              <svg v-if="editorFullscreen" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M8 3v3a2 2 0 0 1-2 2H3"/><path d="M21 8h-3a2 2 0 0 1-2-2V3"/>
                <path d="M3 16h3a2 2 0 0 1 2 2v3"/><path d="M16 21v-3a2 2 0 0 1 2-2h3"/>
              </svg>
              <svg v-else width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
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

        <!-- 元数据表单 -->
        <div class="editor-meta glass">
          <template v-if="codeEditor.mode === 'create'">
            <div class="meta-field">
              <label>插件 ID</label>
              <input v-model="codeEditor.slug" placeholder="英文，如 my_plugin" />
            </div>
            <div class="meta-field">
              <label>插件名称</label>
              <input v-model="codeEditor.name" placeholder="如：我的插件" />
            </div>
            <div class="meta-field">
              <label>描述</label>
              <input v-model="codeEditor.description" placeholder="插件功能描述" />
            </div>
            <div class="meta-field">
              <label>版本号</label>
              <input v-model="codeEditor.version" placeholder="1.0.0" />
            </div>
            <div class="meta-field perms-field">
              <label>权限</label>
              <div class="perms-dropdown" @click="togglePermPanel">
                <div class="perms-trigger" :class="{ empty: !codeEditor.permissions.length }">
                  <template v-if="codeEditor.permissions.length">
                    {{ permLabels(codeEditor.permissions) }}
                  </template>
                  <template v-else>选择权限…</template>
                  <span class="arrow">▾</span>
                </div>
                <transition name="drop">
                  <div v-if="permPanelOpen" class="perms-panel">
                    <div v-for="perm in ALL_PERMS" :key="perm.id"
                      class="perm-option"
                      :class="{ selected: codeEditor.permissions.includes(perm.id) }"
                      @click.stop="togglePerm(perm.id)">
                      <span class="perm-check">✓</span>
                      <span class="perm-label">{{ perm.id }}</span>
                      <span class="perm-desc">{{ perm.desc }}</span>
                    </div>
                  </div>
                </transition>
              </div>
            </div>
          </template>
          <template v-else>
            <div class="meta-field">
              <label>新版本号</label>
              <input v-model="codeEditor.version" placeholder="1.0.1" />
            </div>
            <div class="meta-field">
              <label>更新说明</label>
              <input v-model="codeEditor.changelog" placeholder="本次更新内容" />
            </div>
            <span class="meta-fill"></span>
          </template>
        </div>

        <!-- 工作区：文件标签 + 大编辑器 + 操作栏 -->
        <div class="editor-workbench glass">
          <div class="file-tabs">
            <button class="file-tab" v-for="f in codeEditor.files" :key="f.name"
              :class="{ active: codeEditor.activeFile === f.name }"
              @click="codeEditor.activeFile = f.name">
              <span class="ft-icon" :class="f.name.endsWith('.json') ? 'json' : 'py'">
                {{ f.name.endsWith('.json') ? 'JSON' : 'PY' }}
              </span>
              {{ f.name }}
              <span class="file-remove" v-if="!isCoreFile(f.name)" title="删除文件"
                @click.stop="removeFile(f.name)">×</span>
            </button>
            <button class="file-tab add" title="新建文件" @click="openNewFileDialog">
              <span class="ft-add">+</span>
            </button>
          </div>

          <div class="editor-body">
            <div v-if="codeEditor.loading" class="editor-loading">
              <div class="spinner"></div>
              <p>正在加载源码…</p>
            </div>
            <template v-else-if="activeFileEntry">
              <CodeEditor v-if="codeEditor.activeFile.endsWith('.json')"
                v-model="activeFileEntry.content" language="json" height="100%" :theme="editorTheme" />
              <CodeEditor v-else
                v-model="activeFileEntry.content" :language="fileLang(codeEditor.activeFile)"
                height="100%" :theme="editorTheme" />
            </template>
          </div>

          <div class="editor-actions">
            <button class="btn-ghost" @click="closeEditor">取消</button>
            <template v-if="codeEditor.mode === 'create'">
              <button class="btn-ghost editor-local-btn"
                :disabled="codeEditor.saving" @click="savePluginCode">
                {{ codeEditor.saving === 'market' ? '上架中…' : '上架到市场' }}
              </button>
              <button class="btn-mint" :disabled="codeEditor.saving" @click="createLocalFromEditor">
                {{ codeEditor.saving === 'local' ? '创建中…' : '创建' }}
              </button>
            </template>
            <template v-else-if="codeEditor.mode === 'local-edit'">
              <button class="btn-mint" :disabled="codeEditor.saving" @click="saveLocalFromEditor">
                {{ codeEditor.saving === 'local' ? '保存中…' : '保存并热重载' }}
              </button>
            </template>
            <template v-else>
              <button class="btn-ghost editor-local-btn"
                :disabled="codeEditor.saving" @click="saveLocalFromEditor">
                {{ codeEditor.saving === 'local' ? '保存中…' : '本地保存' }}
              </button>
              <button class="btn-mint" :disabled="codeEditor.saving" @click="savePluginCode">
                {{ codeEditor.saving === 'market' ? '保存中…' : '保存新版本' }}
              </button>
            </template>
        </div>
      </div>
      </div>

      <!-- 仪表盘 -->
      <div v-else class="dev-dashboard">
      <!-- 开发者概览卡片 -->
      <div class="overview-card glass card-in">
        <div class="overview-left">
          <div class="overview-avatar">
            <span>{{ (devInfo.username || '?').charAt(0).toUpperCase() }}</span>
          </div>
          <div class="overview-info">
            <h2 class="overview-name">{{ devInfo.username }}</h2>
            <p class="overview-email">{{ devInfo.email }}</p>
          </div>
        </div>
        <div class="overview-stats">
          <div class="stat-item">
            <span class="stat-value">{{ myPlugins.length }}</span>
            <span class="stat-label">已发布</span>
          </div>
          <div class="stat-divider"></div>
          <div class="stat-item">
            <span class="stat-value">{{ totalDownloads }}</span>
            <span class="stat-label">总下载</span>
          </div>
          <div class="stat-divider"></div>
          <div class="stat-item">
            <span class="stat-value">{{ customLocalPlugins.length }}</span>
            <span class="stat-label">本地测试</span>
          </div>
        </div>
        <div class="overview-actions">
          <button class="btn-mint" @click="openCreateEditor">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
              <line x1="12" y1="5" x2="12" y2="19"/>
              <line x1="5" y1="12" x2="19" y2="12"/>
            </svg>
            新建插件
          </button>
          <button class="btn-ghost" :disabled="devLoading" @click="enableDev">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
              <polyline points="23 4 23 10 17 10"/>
              <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/>
            </svg>
            重新生成
          </button>
        </div>
      </div>

      <!-- 标签页导航 -->
      <div class="tabs-nav glass card-in">
        <button class="tab-btn" :class="{ active: activeTab === 'local' }" @click="activeTab = 'local'">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
            <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>
          </svg>
          本地插件
          <span v-if="customLocalPlugins.length" class="tab-badge">{{ customLocalPlugins.length }}</span>
        </button>
        <button class="tab-btn" :class="{ active: activeTab === 'published' }" @click="activeTab = 'published'">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
            <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/>
          </svg>
          已发布
          <span v-if="myPlugins.length" class="tab-badge">{{ myPlugins.length }}</span>
        </button>
        <button class="tab-btn" :class="{ active: activeTab === 'upload' }" @click="activeTab = 'upload'">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
            <polyline points="17 8 12 3 7 8"/>
            <line x1="12" y1="3" x2="12" y2="15"/>
          </svg>
          上传插件
        </button>
        <button class="tab-btn" :class="{ active: activeTab === 'logs' }" @click="activeTab = 'logs'">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
            <polyline points="14 2 14 8 20 8"/>
            <line x1="9" y1="13" x2="15" y2="13"/>
            <line x1="9" y1="17" x2="15" y2="17"/>
          </svg>
          运行日志
        </button>
      </div>

      <!-- 标签页内容 -->
      <div class="tab-content">
        <!-- 本地插件 -->
        <div v-if="activeTab === 'local'" class="tab-pane glass card-in">
          <div class="pane-header">
            <h3>本地插件</h3>
            <button class="btn-ghost btn-sm" @click="loadLocalInstalled">刷新</button>
          </div>
          
          <div v-if="customLocalPlugins.length === 0" class="empty-pane">
            <div class="empty-pane-icon">
              <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1" stroke-linecap="round">
                <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>
              </svg>
            </div>
            <p>还没有本地安装的插件</p>
            <button class="btn-ghost" @click="activeTab = 'upload'">上传插件</button>
          </div>

          <div v-else class="plugin-list">
            <div v-for="(p, i) in customLocalPlugins" :key="p.name" class="plugin-row"
              :style="{ animationDelay: i * 0.05 + 's' }">
              <div class="plugin-row-icon local">
                <span>{{ (p.title || p.name).charAt(0).toUpperCase() }}</span>
              </div>
              <div class="plugin-row-info">
                <p class="plugin-row-name">{{ p.title || p.name }}</p>
                <div class="plugin-row-meta">
                  <span class="meta-code">{{ p.name }}</span>
                  <span v-if="p.version" class="meta-ver">v{{ p.version }}</span>
                  <span v-if="p.source === 'built-in'" class="meta-tag">内置</span>
                </div>
              </div>
              <div class="plugin-row-actions">
                <button v-if="p.source !== 'built-in'" class="row-btn" @click="openLocalEditEditor(p)">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
                    <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>
                    <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>
                  </svg>
                </button>
                <button v-if="p.source !== 'built-in'" class="row-btn danger"
                  :disabled="uninstalling === p.name" @click="uninstallLocal(p)">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
                    <polyline points="3 6 5 6 21 6"/>
                    <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>
                  </svg>
                </button>
              </div>
            </div>
          </div>
        </div>

        <!-- 已发布插件 -->
        <div v-if="activeTab === 'published'" class="tab-pane glass card-in">
          <div class="pane-header">
            <h3>已发布插件</h3>
            <button class="btn-ghost btn-sm" @click="loadMyPlugins">刷新</button>
          </div>
          
          <div v-if="myPlugins.length === 0" class="empty-pane">
            <div class="empty-pane-icon">
              <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1" stroke-linecap="round">
                <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/>
              </svg>
            </div>
            <p>还没有上传过插件</p>
            <button class="btn-ghost" @click="openCreateEditor">创建第一个插件</button>
          </div>

          <div v-else class="plugin-list">
            <div v-for="(p, i) in myPlugins" :key="p.slug" class="plugin-row published"
              :style="{ animationDelay: i * 0.05 + 's' }">
              <div class="plugin-row-icon published">
                <span>{{ (p.name || p.slug).charAt(0).toUpperCase() }}</span>
              </div>
              <div class="plugin-row-info">
                <p class="plugin-row-name">{{ p.name }}</p>
                <div class="plugin-row-meta">
                  <span class="meta-code">{{ p.slug }}</span>
                  <span v-if="p.latest_version" class="meta-ver">v{{ p.latest_version }}</span>
                  <span class="meta-downloads">
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
                      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
                      <polyline points="7 10 12 15 17 10"/>
                      <line x1="12" y1="15" x2="12" y2="3"/>
                    </svg>
                    {{ formatDownloads(p.total_downloads) }}
                  </span>
                </div>
              </div>
              <div class="plugin-row-actions">
                <button class="row-btn" @click="openEditEditor(p)">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
                    <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>
                    <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>
                  </svg>
                </button>
                <button class="row-btn danger" :disabled="deletingPlugin === p.slug" @click="deleteMyPlugin(p)">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
                    <polyline points="3 6 5 6 21 6"/>
                    <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>
                  </svg>
                </button>
              </div>
            </div>
          </div>
        </div>

        <!-- 上传插件 -->
        <div v-if="activeTab === 'upload'" class="tab-pane glass card-in">
          <div class="pane-header">
            <h3>上传插件</h3>
            <p class="pane-desc">上传 .zip 格式的插件包，需包含 manifest.json 和 plugin.py</p>
          </div>
          
          <div class="upload-zone" 
            :class="{ 'has-file': uploadFile, 'drag-over': isDragging }"
            @click="$refs.fileInput.click()" 
            @dragover.prevent="isDragging = true"
            @dragleave="isDragging = false"
            @drop.prevent="onDrop">
            <input ref="fileInput" type="file" accept=".zip" @change="onFileSelect" hidden />
            
            <template v-if="!uploadFile">
              <div class="upload-icon">
                <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round">
                  <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
                  <polyline points="14 2 14 8 20 8"/>
                  <line x1="16" y1="13" x2="8" y2="13"/>
                  <line x1="16" y1="17" x2="8" y2="17"/>
                </svg>
              </div>
              <p class="upload-text">点击选择或拖拽文件到此处</p>
              <p class="upload-hint">支持 .zip 格式</p>
            </template>

            <template v-else>
              <div class="upload-file-icon">
                <svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round">
                  <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
                  <polyline points="7 10 12 15 17 10"/>
                  <line x1="12" y1="15" x2="12" y2="3"/>
                </svg>
              </div>
              <p class="upload-fname">{{ uploadFile.name }}</p>
              <p class="upload-fsize">{{ (uploadFile.size / 1024).toFixed(1) }} KB</p>
            </template>
          </div>

          <div v-if="uploadFile" class="upload-actions">
            <button class="btn-mint" :disabled="uploading" @click="doUpload('market')">
              {{ uploading === 'market' ? '上架中…' : '上架到市场' }}
            </button>
            <button class="btn-ghost" :disabled="uploading" @click="doUpload('local')">
              {{ uploading === 'local' ? '安装中…' : '本地测试' }}
            </button>
            <button class="btn-ghost btn-cancel" @click="uploadFile = null">取消</button>
          </div>

          <!-- 快捷创建 -->
          <div class="quick-create">
            <div class="quick-create-divider">
              <span>或者</span>
            </div>
            <button class="btn-ghost quick-create-btn" @click="openCreateEditor">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
                <line x1="12" y1="5" x2="12" y2="19"/>
                <line x1="5" y1="12" x2="19" y2="12"/>
              </svg>
              在线创建新插件
            </button>
          </div>
        </div>

        <!-- 运行日志 -->
        <div v-if="activeTab === 'logs'" class="tab-pane glass card-in logs-pane">
          <div class="pane-header">
            <h3>运行日志</h3>
            <div class="logs-controls">
              <select v-model="logView.plugin" class="log-plugin-select" @change="loadLogs">
                <option value="">选择插件…</option>
                <option v-for="p in allPluginNames" :key="p" :value="p">{{ p }}</option>
              </select>
              <select v-model="logView.level" class="log-level-select" @change="loadLogs">
                <option value="">全部级别</option>
                <option value="error">Error</option>
                <option value="warn">Warn</option>
                <option value="info">Info</option>
                <option value="debug">Debug</option>
                <option value="stderr">Stderr</option>
              </select>
              <button class="btn-ghost btn-sm" @click="loadLogs" :disabled="!logView.plugin">刷新</button>
              <button class="btn-ghost btn-sm log-auto-btn" :class="{ active: logView.autoRefresh }"
                @click="toggleAutoRefresh">{{ logView.autoRefresh ? '自动 ✓' : '自动' }}</button>
              <button class="btn-ghost btn-sm" @click="copyLogs" :disabled="!logView.entries.length">复制</button>
              <button class="btn-ghost btn-sm log-clear-btn" @click="clearLogs" :disabled="!logView.plugin || !logView.entries.length">清空</button>
            </div>
          </div>

          <div v-if="!logView.plugin" class="empty-pane">
            <div class="empty-pane-icon">
              <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1" stroke-linecap="round">
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
                <polyline points="14 2 14 8 20 8"/>
              </svg>
            </div>
            <p>选择一个插件查看运行日志</p>
          </div>

          <div v-else-if="logView.loading" class="log-loading">
            <div class="spinner"></div>
            <p>正在加载日志…</p>
          </div>

          <div v-else-if="!logView.entries.length" class="empty-pane">
            <div class="empty-pane-icon">
              <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1" stroke-linecap="round">
                <circle cx="12" cy="12" r="10"/>
                <path d="M8 14s1.5 2 4 2 4-2 4-2"/>
                <line x1="9" y1="9" x2="9.01" y2="9"/>
                <line x1="15" y1="9" x2="15.01" y2="9"/>
              </svg>
            </div>
            <p>暂无日志记录</p>
            <p class="log-hint">插件运行时的错误、SDK 调用异常和 plugin_log() 输出会显示在这里</p>
          </div>

          <div v-else class="terminal">
            <div ref="pluginLogTerminalRef" class="terminal-content">
              <div v-for="(entry, i) in logView.entries" :key="i" class="log-line" :class="'log-' + entry.level">
                <span class="log-time">{{ formatLogTime(entry.time) }}</span>
                <span class="log-content">{{ entry.message }}</span>
              </div>
            </div>
          </div>
        </div>
      </div>
	      </div>
	      <!-- ======================= 确认弹窗 ======================= -->
    <transition name="pop">
      <div v-if="confirmData.show" class="confirm-mask" @click.self="confirmCancel">
        <div class="confirm-panel glass">
          <div class="confirm-icon" :class="{ danger: confirmData.danger }">
            {{ confirmData.danger ? '!' : '?' }}
          </div>
          <h3 class="confirm-title">{{ confirmData.title || '请确认' }}</h3>
          <p class="confirm-message">{{ confirmData.message }}</p>
          <div class="confirm-actions">
            <button class="btn-ghost confirm-cancel" @click="confirmCancel">
              {{ confirmData.cancelText || '取消' }}
            </button>
            <button class="confirm-ok" :class="{ danger: confirmData.danger }" @click="confirmOk">
              {{ confirmData.confirmText || '确定' }}
            </button>
          </div>
        </div>
      </div>
    </transition>

    <!-- ======================= 新建文件弹窗 ======================= -->
    <transition name="pop">
      <div v-if="newFileDialog" class="confirm-mask" @click.self="closeNewFileDialog">
        <div class="confirm-panel glass">
          <div class="confirm-title">新建文件</div>
          <p class="confirm-message">输入文件名，支持子目录（如 utils.py、data/help.md）</p>
          <input ref="newFileInput" v-model="newFileName" class="new-file-input"
            placeholder="如 utils.py" @keyup.enter="confirmNewFile" />
          <div class="confirm-actions">
            <button class="btn-ghost confirm-cancel" @click="closeNewFileDialog">取消</button>
            <button class="confirm-ok" @click="confirmNewFile">创建</button>
          </div>
        </div>
      </div>
    </transition>
  </div>
</div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount, watch, nextTick } from 'vue'
import { api, isLoggedIn } from '../api'
import CodeEditor from '../components/CodeEditor.vue'
import { THEMES } from '../monaco-setup'

const emit = defineEmits(['toast', 'editor-change'])

const isLoggedInUser = computed(() => isLoggedIn())
const isDragging = ref(false)
const activeTab = ref('local')

// ===== 自定义确认弹窗 =====
const confirmData = ref({ show: false, title: '', message: '', confirmText: '确定', cancelText: '取消', danger: false, resolve: null })

function showConfirm(options) {
  return new Promise(resolve => {
    confirmData.value = {
      show: true,
      title: options.title || '请确认',
      message: options.message || '',
      confirmText: options.confirmText || '确定',
      cancelText: options.cancelText || '取消',
      danger: options.danger !== false,
      resolve,
    }
  })
}

function confirmOk() {
  confirmData.value.show = false
  confirmData.value.resolve?.(true)
}

function confirmCancel() {
  confirmData.value.show = false
  confirmData.value.resolve?.(false)
}

// ===== 开发者（复用用户 JWT） =====
const devInfo = ref({ is_developer: false, developer_api_key: '', username: '', email: '' })
const devLoading = ref(false)
const uploadFile = ref(null)
const uploading = ref(false)  // false | 'market' | 'local'
const myPlugins = ref([])
const deletingPlugin = ref(null)

const totalDownloads = computed(() => {
  const total = myPlugins.value.reduce((sum, p) => sum + (p.total_downloads || 0), 0)
  return formatDownloads(total)
})

async function loadDevInfo() {
  if (!isLoggedInUser.value) return
  try {
    const res = await api.devInfo()
    if (res.status === 200 && res.data?.code === 0) {
      devInfo.value = res.data.data || {}
      if (devInfo.value.is_developer) await loadMyPlugins()
    } else {
      console.error('[Developer] loadDevInfo 失败:', res.status, res.data)
    }
  } catch (e) {
    console.error('[Developer] loadDevInfo 异常:', e)
  }
}

async function loadMyPlugins() {
  try {
    const res = await api.devMyPlugins()
    if (res.status === 200 && res.data?.code === 0) {
      myPlugins.value = res.data.data || []
    } else {
      console.error('[Developer] loadMyPlugins 失败:', res.status, res.data)
      myPlugins.value = []
      emit('toast', res.data?.message || '加载我的插件列表失败')
    }
  } catch (e) {
    console.error('[Developer] loadMyPlugins 异常:', e)
    myPlugins.value = []
    emit('toast', '加载插件列表异常')
  }
}

async function deleteMyPlugin(p) {
  const ok = await showConfirm({
    title: '删除插件',
    message: `确定删除「${p.name}」？所有版本和文件将一并删除，已安装用户不受影响。`,
    confirmText: '确认删除',
    cancelText: '取消',
    danger: true,
  })
  if (!ok) return
  deletingPlugin.value = p.slug
  const res = await api.devDeletePlugin(p.slug)
  deletingPlugin.value = null
  if (res.status === 200 && res.data?.code === 0) {
    emit('toast', '插件已删除')
    await loadMyPlugins()
  } else {
    emit('toast', res.data?.message || '删除失败')
  }
}

async function enableDev() {
  devLoading.value = true
  const res = await api.devEnable()
  devLoading.value = false
  if (res.status === 200 && res.data?.code === 0) {
    devInfo.value = { ...devInfo.value, ...res.data.data, is_developer: true }
    emit('toast', '开发者模式已开启')
  } else {
    emit('toast', res.data?.message || '操作失败')
  }
}

function onFileSelect(e) { if (e.target.files[0]) uploadFile.value = e.target.files[0] }
function onDrop(e) { 
  isDragging.value = false
  const f = e.dataTransfer.files[0]
  if (f && f.name.endsWith('.zip')) uploadFile.value = f 
}

async function doUpload(mode) {
  if (!uploadFile.value) return
  uploading.value = mode
  if (mode === 'market') {
    try {
      const res = await api.devUpload(uploadFile.value)
      if (res.status === 200 && res.data?.code === 0) {
        emit('toast', '插件已上架到市场')
        uploadFile.value = null
        await loadMyPlugins()
        if (myPlugins.value.length === 0) {
          emit('toast', '上架成功，但列表加载异常，请刷新页面')
        }
      } else {
        emit('toast', res.data?.message || '上架失败')
      }
    } catch (e) {
      emit('toast', '上传异常：' + e.message)
    }
  } else {
    try {
      const res = await api.installPluginZip(uploadFile.value)
      if (res.status === 200 && res.data?.code === 0) {
        emit('toast', '插件已安装，可测试使用')
        uploadFile.value = null
        await loadLocalInstalled()
      } else {
        emit('toast', res.data?.message || '安装失败')
      }
    } catch (e) {
      emit('toast', '安装异常：' + e.message)
    }
  }
  uploading.value = false
}

// ===== 本地已安装（上传后检查） =====
const localInstalled = ref([])
const uninstalling = ref('')

const customLocalPlugins = computed(() => localInstalled.value.filter(p => p.source !== 'built-in'))

async function loadLocalInstalled() {
  const res = await api.installedPlugins()
  if (res.status === 200 && res.data?.code === 0) {
    localInstalled.value = res.data.data || []
  }
}

async function uninstallLocal(p) {
  const ok = await showConfirm({
    title: '卸载插件',
    message: `确定卸载「${p.title || p.name}」吗？此操作不可撤销。`,
    confirmText: '确认卸载',
    cancelText: '取消',
    danger: true,
  })
  if (!ok) return
  uninstalling.value = p.name
  try {
    const res = await api.uninstallPlugin(p.name)
    if (res.status === 200 && res.data?.code === 0) {
      emit('toast', '插件已卸载')
      await loadLocalInstalled()
    } else {
      emit('toast', res.data?.message || '卸载失败')
    }
  } catch (e) {
    emit('toast', '卸载异常')
  }
  uninstalling.value = ''
}

// ===== 运行日志 =====
const logView = ref({
  plugin: '',
  level: '',
  entries: [],
  loading: false,
  autoRefresh: false,
})
const pluginLogTerminalRef = ref(null)
let _logTimer = null

const allPluginNames = computed(() => {
  return localInstalled.value.map(p => p.name).filter(Boolean).sort()
})

function scrollLogToBottom() {
  nextTick(() => {
    const el = pluginLogTerminalRef.value
    if (el) el.scrollTop = el.scrollHeight
  })
}

async function loadLogs() {
  if (!logView.value.plugin) return
  logView.value.loading = true
  try {
    const res = await api.pluginLogs(logView.value.plugin, 200, logView.value.level || null)
    if (res.status === 200 && res.data?.code === 0) {
      // 后端返回最新在前，反转后最新在底部（终端风格）
      logView.value.entries = (res.data.data || []).reverse()
      scrollLogToBottom()
    } else {
      emit('toast', res.data?.message || '获取日志失败')
      logView.value.entries = []
    }
  } catch (e) {
    emit('toast', '获取日志异常')
    logView.value.entries = []
  }
  logView.value.loading = false
}

async function copyLogs() {
  if (!logView.value.entries.length) return
  const text = logView.value.entries
    .map(e => `${formatLogTime(e.time)} [${String(e.level || '').toUpperCase()}] ${e.message}`)
    .join('\n')
  try {
    await navigator.clipboard.writeText(text)
    emit('toast', '日志已复制到剪贴板')
  } catch (e) {
    emit('toast', '复制失败，请手动选择复制')
  }
}

async function clearLogs() {
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
    emit('toast', '日志已清空')
  } else {
    emit('toast', res.data?.message || '清空失败')
  }
}

function toggleAutoRefresh() {
  logView.value.autoRefresh = !logView.value.autoRefresh
  if (logView.value.autoRefresh) {
    _logTimer = setInterval(() => {
      if (logView.value.plugin) loadLogs()
    }, 5000)
  } else {
    if (_logTimer) { clearInterval(_logTimer); _logTimer = null }
  }
}

function formatLogTime(ts) {
  if (!ts) return ''
  return ts.replace('T', ' ').replace(/\.\d+$/, '')
}

// ===== 在线代码编辑器 =====
const _TEMPLATE_PLUGIN = `"""插件：在此编写工具函数"""

from src.use_cases.tools_system import tool


@tool()
def hello(name: str) -> str:
    """打招呼

    Args:
        name: 对方名字

    Returns:
        问候语
    """
    return f"你好，{name}！"
`

const _TEMPLATE_MANIFEST = (slug, name, desc, perms) => JSON.stringify({
  id: slug,
  name: name,
  version: "1.0.0",
  description: desc,
  api_version: "1.0",
  category: "general",
  tags: [],
  requires: [],
  permissions: perms,
  config_fields: [],
}, null, 2)

const ALL_PERMS = [
  { id: 'network', label: 'Network', desc: '发起外部 HTTP 请求（调 API、爬数据）' },
  { id: 'device', label: 'Device', desc: '给设备下发指令、控制屏幕播放' },
  { id: 'ltm', label: 'LTM', desc: '读写设备长期记忆（记住用户偏好）' },
  { id: 'db', label: 'DB', desc: '读写数据库（日记、设备配置）' },
  { id: 'env_read', label: 'Env', desc: '读取环境变量（获取 API Key 等配置）' },
  { id: 'file_read', label: 'R File', desc: '读取插件目录和状态目录的文件' },
  { id: 'file_write', label: 'W File', desc: '写入文件到插件目录和状态目录' },
  { id: 'subprocess', label: 'Exec', desc: '执行子进程命令（运行外部工具，需审核）' },
  { id: 'exec', label: 'Dyn Code', desc: '动态执行代码（运行用户脚本，需审核）' },
]

const permPanelOpen = ref(false)

function togglePerm(id) {
  const perms = codeEditor.value.permissions
  const idx = perms.indexOf(id)
  if (idx >= 0) {
    perms.splice(idx, 1)
  } else {
    perms.push(id)
  }
}

function permLabels(ids) {
  return ids.map(id => ALL_PERMS.find(p => p.id === id)?.label || id).join(', ')
}

function togglePermPanel() {
  permPanelOpen.value = !permPanelOpen.value
}

function closePermPanel() {
  permPanelOpen.value = false
}

function onWindowClick(e) {
  if (permPanelOpen.value) {
    const el = document.querySelector('.perms-dropdown')
    if (el && !el.contains(e.target)) {
      permPanelOpen.value = false
    }
  }
}

const codeEditor = ref({
  show: false,
  mode: 'create',
  slug: '',
  name: '',
  description: '',
  version: '1.0.0',
  permissions: [],
  category: 'general',
  tags: [],
  changelog: '',
  files: [],               // [{ name, content }]
  activeFile: 'plugin.py',
  loading: false,
  saving: false,
})

const editorFullscreen = ref(false)

function toggleFullscreen() {
  editorFullscreen.value = !editorFullscreen.value
}

// 编辑器打开/关闭时通知父组件隐藏/显示导航栏
watch(() => codeEditor.value.show, (v) => {
  emit('editor-change', v)
})

const editorTheme = ref(localStorage.getItem('espai_editor_theme') || 'dark')
const editorThemes = THEMES

function setEditorTheme(id) {
  editorTheme.value = id
  localStorage.setItem('espai_editor_theme', id)
}

// 文件语言推断
function fileLang(name) {
  const ext = (name.split('.').pop() || '').toLowerCase()
  const map = {
    py: 'python', json: 'json', md: 'markdown', txt: 'plaintext',
    js: 'javascript', ts: 'typescript', html: 'html', css: 'css',
    yaml: 'yaml', yml: 'yaml', sh: 'shell', toml: 'ini', ini: 'ini',
  }
  return map[ext] || 'plaintext'
}

// 当前编辑文件
const activeFileEntry = computed(() =>
  codeEditor.value.files.find(f => f.name === codeEditor.value.activeFile) || null
)

function getFile(name) {
  return codeEditor.value.files.find(f => f.name === name) || null
}

function isCoreFile(name) {
  return name === 'plugin.py' || name === 'manifest.json'
}

const newFileName = ref('')
const newFileDialog = ref(false)

function openNewFileDialog() {
  newFileName.value = ''
  newFileDialog.value = true
}

function closeNewFileDialog() {
  newFileDialog.value = false
}

function confirmNewFile() {
  const name = newFileName.value
  if (!name || !name.trim()) { emit('toast', '请输入文件名'); return }
  const clean = name.trim()
  if (getFile(clean)) { emit('toast', '文件已存在: ' + clean); return }
  codeEditor.value.files.push({ name: clean, content: '' })
  codeEditor.value.activeFile = clean
  newFileDialog.value = false
}

function removeFile(name) {
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
    if (codeEditor.value.activeFile === name) {
      const first = codeEditor.value.files[0]
      codeEditor.value.activeFile = first ? first.name : 'plugin.py'
    }
  })
}

function openCreateEditor() {
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
      { name: 'plugin.py', content: _TEMPLATE_PLUGIN },
      { name: 'manifest.json', content: _TEMPLATE_MANIFEST('my_plugin', '我的插件', '插件描述', []) },
    ],
    activeFile: 'plugin.py',
    loading: false,
    saving: false,
  }
}

async function openEditEditor(p) {
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
  } else {
    emit('toast', res.data?.message || '获取源码失败')
    codeEditor.value.show = false
  }
}

async function openLocalEditEditor(p) {
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
    } else {
      emit('toast', res.data?.message || '获取源码失败')
      codeEditor.value.show = false
    }
  } catch (e) {
    emit('toast', '获取源码异常')
    codeEditor.value.show = false
  }
  codeEditor.value.loading = false
}

function bumpVersion(ver) {
  if (!ver) return '1.0.0'
  const parts = ver.split('.')
  const patch = parseInt(parts[2] || '0') + 1
  return `${parts[0] || '1'}.${parts[1] || '0'}.${patch}`
}

function closeEditor() {
  codeEditor.value.show = false
  editorFullscreen.value = false
}

// 从 files 中取 plugin.py / manifest.json 内容，缺失时回退到 manifest 字段
function pluginCodeFromFiles() {
  return getFile('plugin.py')?.content || ''
}

function manifestRawFromFiles() {
  return getFile('manifest.json')?.content || '{}'
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

async function savePluginCode() {
  const ce = codeEditor.value
  let manifest
  try {
    manifest = JSON.parse(manifestRawFromFiles())
  } catch {
    emit('toast', 'manifest.json 格式错误，请检查 JSON 语法')
    return
  }
  if (!pluginCodeFromFiles().trim()) {
    emit('toast', 'plugin.py 不能为空')
    return
  }

  ce.saving = 'market'
  if (ce.mode === 'create') {
    if (!ce.slug.trim() || !ce.name.trim()) {
      emit('toast', '请填写插件 ID 和名称')
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
      emit('toast', '插件创建成功，已上架到市场')
      closeEditor()
      await loadMyPlugins()
    } else {
      emit('toast', res.data?.message || '创建失败')
    }
  } else {
    manifest.version = ce.version
    const res = await api.devUpdatePluginSource(ce.slug, {
      plugin_code: pluginCodeFromFiles(),
      files: ce.files,
      manifest: manifest,
      changelog: ce.changelog || '',
    })
    ce.saving = false
    if (res.status === 200 && res.data?.code === 0) {
      emit('toast', '新版本已保存并上架')
      closeEditor()
      await loadMyPlugins()
    } else {
      emit('toast', res.data?.message || '保存失败')
    }
  }
}

async function saveLocalFromEditor() {
  const ce = codeEditor.value
  if (!pluginCodeFromFiles().trim()) {
    emit('toast', 'plugin.py 不能为空')
    return
  }
  ce.saving = 'local'
  const res = await api.updateLocalPluginSource(ce.slug, pluginCodeFromFiles(), ce.files)
  ce.saving = false
  if (res.status === 200 && res.data?.code === 0) {
    emit('toast', res.data.message || '已保存到本地并热重载')
  } else {
    emit('toast', res.data?.message || '本地保存失败（需先安装插件）')
  }
}

async function createLocalFromEditor() {
  const ce = codeEditor.value
  if (!ce.slug.trim() || !ce.name.trim()) {
    emit('toast', '请填写插件 ID 和名称')
    return
  }
  if (!pluginCodeFromFiles().trim()) {
    emit('toast', 'plugin.py 不能为空')
    return
  }

  // 将表单字段同步到 manifest.json 文件内容，确保编辑器显示一致
  syncManifestFromForm()

  let manifest
  try {
    manifest = JSON.parse(manifestRawFromFiles())
  } catch {
    emit('toast', 'manifest.json 格式错误，请检查 JSON 语法')
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
    emit('toast', res.data.message || '插件已创建到本地，可前往已安装页面测试')
    closeEditor()
    await loadLocalInstalled()
  } else {
    emit('toast', res.data?.message || '创建失败')
  }
}

// ===== Utils =====
function formatDownloads(n) {
  if (!n) return '0'
  if (n < 1000) return String(n)
  if (n < 10000) return (n / 1000).toFixed(1) + 'k'
  return (n / 10000).toFixed(1) + 'w'
}

function formatTime(ts) {
  if (!ts) return '—'
  const d = new Date(ts * 1000)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

// ===== Init =====
function onKeydown(e) {
  if (e.key === 'Escape' && editorFullscreen.value) {
    editorFullscreen.value = false
  }
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'l' && activeTab.value === 'logs' && logView.value.plugin) {
    e.preventDefault()
    clearLogs()
  }
}

onMounted(() => {
  loadDevInfo()
  loadLocalInstalled()
  window.addEventListener('keydown', onKeydown)
  window.addEventListener('click', onWindowClick)
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKeydown)
  window.removeEventListener('click', onWindowClick)
  if (_logTimer) { clearInterval(_logTimer); _logTimer = null }
})
</script>

<style scoped>
.dev-view { padding: 28px 0 56px; }

.glass {
  background: var(--grad-card);
  backdrop-filter: var(--glass-blur);
  -webkit-backdrop-filter: var(--glass-blur);
  border: 1px solid var(--glass-border);
  box-shadow: var(--shadow), var(--glass-hi);
  border-radius: var(--radius-lg);
}

/* ===== 空状态 ===== */
.empty { 
  display: flex; flex-direction: column; align-items: center; justify-content: center; 
  padding: 80px 40px; text-align: center;
}
.empty-icon { 
  width: 100px; height: 100px; border-radius: 50%; 
  background: var(--mint-soft); 
  border: 1px solid var(--mint-border);
  display: flex; align-items: center; justify-content: center;
  margin-bottom: 24px; color: var(--mint);
}
.empty-title { font-size: 20px; font-weight: 700; margin-bottom: 8px; }
.empty-desc { font-size: 14px; color: var(--text-sub); max-width: 320px; }

/* ===== 开启开发者 ===== */
.enable-dev { 
  max-width: 460px; margin: 0 auto; padding: 48px 40px; 
  text-align: center; overflow: hidden; position: relative;
}
.enable-dev::after {
  content: '';
  position: absolute; inset: 0;
  background: var(--grad-hero);
  pointer-events: none;
}
.enable-dev-visual { position: relative; margin-bottom: 32px; }
.enable-dev-icon { 
  width: 88px; height: 88px; border-radius: 50%; 
  background: var(--mint-soft); 
  border: 1px solid var(--mint-border);
  display: flex; align-items: center; justify-content: center;
  margin: 0 auto; color: var(--mint); position: relative; z-index: 1;
}
.enable-dev-glow { 
  position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%);
  width: 160px; height: 160px; border-radius: 50%;
  background: radial-gradient(circle, var(--mint-glow) 0%, transparent 70%);
  opacity: 0.5; animation: pulse 3s ease-in-out infinite;
}
@keyframes pulse {
  0%, 100% { transform: translate(-50%, -50%) scale(1); opacity: 0.5; }
  50% { transform: translate(-50%, -50%) scale(1.1); opacity: 0.7; }
}
.enable-dev-content { position: relative; z-index: 1; }
.enable-dev-content h3 { font-size: 20px; font-weight: 700; margin-bottom: 8px; }
.enable-dev-content p { font-size: 14px; color: var(--text-sub); margin-bottom: 20px; }
.enable-dev-tags { display: flex; gap: 8px; justify-content: center; margin-bottom: 24px; }
.enable-dev-tags .tag { 
  padding: 6px 14px; border-radius: 20px; font-size: 12px; font-weight: 500;
  background: var(--glass-bg-strong);
  border: 1px solid var(--glass-border);
  color: var(--text-sub);
}
.enable-dev-btn { padding: 12px 40px; font-size: 14px; }

/* ===== 开发者仪表盘 ===== */
.dev-dashboard { display: flex; flex-direction: column; gap: 16px; }

/* ===== 概览卡片 ===== */
.overview-card { 
  display: flex; align-items: center; justify-content: space-between; 
  padding: 26px 30px; gap: 24px;
}
.overview-left { display: flex; align-items: center; gap: 16px; flex: 1; }
.overview-avatar { 
  width: 56px; height: 56px; border-radius: 50%; 
  display: flex; align-items: center; justify-content: center; 
  font-size: 24px; font-weight: 700; color: #fff; 
  background: var(--grad-brand); box-shadow: var(--shadow-mint), inset 0 1px 0 rgba(255,255,255,0.35);
  flex-shrink: 0;
}
.overview-name { font-size: 20px; font-weight: 700; margin: 0; }
.overview-email { font-size: 13px; color: var(--text-sub); margin: 0; }
.overview-stats { 
  display: flex; align-items: center; gap: 24px;
  padding: 16px 24px; border-radius: var(--radius-md);
  background: var(--glass-bg-strong);
  border: 1px solid var(--glass-border);
}
.stat-item { display: flex; flex-direction: column; align-items: center; gap: 4px; }
.stat-value { font-size: 24px; font-weight: 800; color: var(--mint-deep); }
.stat-label { font-size: 12px; color: var(--text-sub); }
.stat-divider { width: 1px; height: 32px; background: var(--glass-border-soft); }
.overview-actions { display: flex; gap: 8px; flex-shrink: 0; }

/* ===== 标签页导航 ===== */
.tabs-nav { 
  display: flex; gap: 4px; padding: 8px;
}
.tab-btn { 
  flex: 1; display: flex; align-items: center; justify-content: center; gap: 8px;
  padding: 12px 16px; border-radius: var(--radius-sm);
  font-size: 14px; font-weight: 500; color: var(--text-sub);
  background: transparent; border: none; cursor: pointer;
  transition: all 0.25s var(--ease);
}
.tab-btn:hover { background: var(--glass-bg-strong); color: var(--text-main); }
.tab-btn.active { 
  background: var(--mint-soft); color: var(--mint-deep); font-weight: 600;
  box-shadow: inset 0 0 0 1px var(--mint-border), 0 6px 16px rgba(16,185,129,0.14);
}
.tab-btn svg { opacity: 0.6; }
.tab-btn.active svg { opacity: 1; }
.tab-badge { 
  padding: 2px 8px; border-radius: 10px; font-size: 11px; font-weight: 600;
  background: var(--glass-bg-strong); color: var(--mint-deep);
}
.tab-btn.active .tab-badge { background: var(--grad-mint); color: #fff; }

/* ===== 标签页内容 ===== */
.tab-content { min-height: 300px; }
.tab-pane { padding: 26px; }
.pane-header { 
  display: flex; align-items: center; justify-content: space-between;
  margin-bottom: 20px;
}
.pane-header h3 { font-size: 16px; font-weight: 700; margin: 0; }
.pane-desc { font-size: 13px; color: var(--text-sub); margin: 4px 0 0 0; }

/* ===== 空面板 ===== */
.empty-pane { 
  display: flex; flex-direction: column; align-items: center; 
  padding: 48px 20px; text-align: center;
}
.empty-pane-icon { 
  width: 72px; height: 72px; border-radius: 50%; 
  background: var(--glass-bg-strong); 
  border: 1px solid var(--glass-border);
  display: flex; align-items: center; justify-content: center;
  margin-bottom: 16px; color: var(--text-dim);
}
.empty-pane p { font-size: 14px; color: var(--text-sub); margin-bottom: 16px; }

/* ===== 插件列表 ===== */
.plugin-list { display: flex; flex-direction: column; gap: 8px; }
.plugin-row { 
  display: flex; align-items: center; gap: 14px; 
  padding: 14px 16px; border-radius: var(--radius-md);
  background: var(--glass-bg-soft);
  border: 1px solid var(--glass-border);
  box-shadow: var(--glass-hi);
  transition: all 0.25s var(--ease);
  animation: cardIn 0.4s var(--ease-spring) both;
}
.plugin-row:hover { 
  background: var(--mint-softer); border-color: var(--mint-border);
  transform: translateX(4px);
}
.plugin-row-icon { 
  width: 40px; height: 40px; border-radius: var(--radius-sm); 
  display: flex; align-items: center; justify-content: center;
  font-size: 16px; font-weight: 700; color: #fff; flex-shrink: 0;
}
.plugin-row-icon.local { background: linear-gradient(135deg, #6366f1, #8b5cf6); box-shadow: 0 6px 16px rgba(99,102,241,0.3); }
.plugin-row-icon.published { background: var(--grad-mint); box-shadow: var(--shadow-mint); }
.plugin-row-info { flex: 1; min-width: 0; }
.plugin-row-name { font-size: 14px; font-weight: 600; color: var(--text-main); margin: 0; }
.plugin-row-meta { display: flex; gap: 8px; margin-top: 4px; font-size: 12px; color: var(--text-sub); align-items: center; }
.meta-code { font-family: monospace; }
.meta-ver { color: var(--mint-deep); font-weight: 500; }
.meta-tag { 
  padding: 2px 6px; border-radius: 4px; font-size: 11px;
  background: var(--glass-bg-strong); color: var(--text-sub);
}
.meta-downloads { 
  display: flex; align-items: center; gap: 4px;
}
.meta-downloads svg { width: 12px; height: 12px; }
.plugin-row-actions { display: flex; gap: 4px; flex-shrink: 0; }
.row-btn { 
  width: 32px; height: 32px; border-radius: var(--radius-sm);
  display: flex; align-items: center; justify-content: center;
  border: 1px solid var(--glass-border); background: var(--glass-bg-strong);
  color: var(--text-sub); cursor: pointer; transition: all 0.2s var(--ease);
}
.row-btn:hover { border-color: var(--mint); color: var(--mint-deep); background: var(--mint-softer); }
.row-btn.danger { border-color: var(--danger-soft); background: var(--danger-soft); color: var(--danger); }
.row-btn.danger:hover:not(:disabled) { background: rgba(239,68,68,0.18); border-color: var(--danger); }
.row-btn:disabled { opacity: 0.5; cursor: not-allowed; }

/* ===== 上传区域 ===== */
.upload-zone {
  border: 2px dashed var(--glass-border); border-radius: var(--radius-lg); padding: 48px 24px;
  text-align: center; cursor: pointer; transition: all 0.3s var(--ease);
  display: flex; flex-direction: column; align-items: center; gap: 12px;
  background: var(--glass-bg-soft);
}
.upload-zone:hover { border-color: var(--mint); background: var(--mint-softer); }
.upload-zone.drag-over { border-color: var(--mint); background: var(--mint-soft); transform: scale(1.01); box-shadow: 0 0 0 4px var(--mint-softer); }
.upload-zone.has-file { border-style: solid; border-color: var(--mint-border); background: var(--mint-soft); }
.upload-icon, .upload-file-icon { color: var(--mint); }
.upload-text { font-size: 14px; color: var(--text-main); font-weight: 500; margin: 0; }
.upload-hint { font-size: 12px; color: var(--text-sub); margin: 0; }
.upload-fname { font-size: 15px; font-weight: 600; color: var(--text-main); margin: 0; }
.upload-fsize { font-size: 13px; color: var(--text-sub); margin: 0; }
.upload-actions { display: flex; gap: 10px; margin-top: 20px; justify-content: center; }
.upload-actions .btn-cancel { margin-left: 8px; }

/* ===== 快捷创建 ===== */
.quick-create { margin-top: 24px; }
.quick-create-divider { 
  display: flex; align-items: center; gap: 16px; margin-bottom: 16px;
  color: var(--text-dim); font-size: 12px;
}
.quick-create-divider::before, .quick-create-divider::after {
  content: ''; flex: 1; height: 1px; background: var(--glass-border-soft);
}
.quick-create-btn { width: 100%; justify-content: center; }

/* ===== Confirm Modal ===== */
.confirm-mask { position: fixed; inset: 0; z-index: 220; display: flex; align-items: center; justify-content: center; background: rgba(15, 23, 42, 0.4); backdrop-filter: blur(12px) saturate(140%); -webkit-backdrop-filter: blur(12px) saturate(140%); }
.confirm-panel { width: min(400px, 90vw); padding: 36px 30px 28px; border-radius: var(--radius-xl); box-shadow: var(--shadow-hover), var(--glass-hi); text-align: center; background: var(--grad-panel); }
.confirm-icon {
  width: 56px; height: 56px; border-radius: 50%; margin: 0 auto 20px;
  display: flex; align-items: center; justify-content: center;
  font-size: 28px; font-weight: 800; color: var(--mint);
  background: var(--mint-soft);
  border: 2px solid var(--mint-border);
}
.confirm-icon.danger { color: #e53e3e; background: var(--danger-soft); border-color: rgba(239, 68, 68, 0.35); }
.confirm-title { font-size: 18px; font-weight: 700; margin-bottom: 10px; }
.confirm-message { font-size: 14px; line-height: 1.6; color: var(--text-sub); margin-bottom: 26px; }
.confirm-actions { display: flex; gap: 12px; justify-content: center; }
.confirm-ok { padding: 7px 20px; font-size: 13px; font-weight: 600; border: none; border-radius: var(--radius-md); cursor: pointer; background: var(--grad-mint); color: #fff; box-shadow: var(--shadow-mint); transition: all 0.2s var(--ease); }
.confirm-ok:hover { filter: brightness(1.08); }
.confirm-ok.danger { background: linear-gradient(135deg, #fc8181, #e53e3e); box-shadow: 0 4px 12px rgba(229, 62, 62, 0.3); }
.new-file-input {
  width: 100%; box-sizing: border-box;
  padding: 10px 14px; margin-bottom: 20px;
  font-size: 14px;
  border: 1px solid var(--glass-border); border-radius: var(--radius-sm);
  background: rgba(255,255,255,0.6);
  outline: none; transition: all 0.2s var(--ease);
}
.new-file-input:focus { border-color: var(--mint); box-shadow: 0 0 0 3px var(--mint-softer); background: rgba(255,255,255,0.85); }

/* ===== 代码编辑器（页面主体） ===== */
/* 编辑器打开时吸收 .stage 与 .dev-view 的内边距，让编辑区占满可视高度 */
.dev-view.editor-open {
  margin: -24px 0 -40px;
  padding: 0 0 16px;
}
/* 全屏编辑：盖住整个视口（含导航栏） */
.editor-page.fullscreen {
  position: fixed;
  inset: 0;
  z-index: 200;
  height: 100vh;
  min-height: 0;
  padding: 16px;
  overflow: auto;
  animation: editorExpand 0.35s var(--ease);
}
@keyframes editorExpand {
  from { transform: scale(0.97); opacity: 0.5; }
  to { transform: scale(1); opacity: 1; }
}
.editor-page.fullscreen .editor-topbar,
.editor-page.fullscreen .editor-meta,
.editor-page.fullscreen .editor-workbench { backdrop-filter: none; }
.fullscreen-btn {
  display: flex; align-items: center; justify-content: center;
  width: 34px; height: 34px;
  border: 1px solid var(--glass-border); border-radius: 8px;
  background: var(--glass-bg-strong); color: var(--text-sub);
  cursor: pointer; transition: all 0.2s var(--ease);
}
.fullscreen-btn:hover { border-color: var(--mint-border); color: var(--mint-deep); background: var(--mint-softer); }
.fullscreen-btn svg { display: block; }
.editor-page {
  position: relative;
  display: flex; flex-direction: column; gap: 10px;
  height: calc(100vh - 24px);
  min-height: 420px;
  background: linear-gradient(160deg, #f6fafc 0%, #e9f1f5 55%, #eef6f2 100%);
}
.editor-topbar {
  display: flex; align-items: center; gap: 14px;
  padding: 10px 16px; flex-shrink: 0;
}
.editor-back {
  display: flex; align-items: center; gap: 6px;
  padding: 7px 14px; font-size: 13px; font-weight: 600;
  border: 1px solid var(--glass-border); border-radius: var(--radius-sm);
  background: var(--glass-bg-strong); color: var(--text-sub); cursor: pointer;
  transition: all 0.2s var(--ease);
}
.editor-back:hover { border-color: var(--mint-border); color: var(--mint-deep); background: var(--mint-softer); }
.editor-title-wrap { display: flex; align-items: center; gap: 10px; flex: 1; min-width: 0; }
.editor-title { font-size: 17px; font-weight: 700; margin: 0; white-space: nowrap; }
.editor-slug {
  font-family: monospace; font-size: 12px; padding: 3px 10px;
  border-radius: 999px; background: var(--glass-bg-strong);
  border: 1px solid var(--glass-border); color: var(--text-sub);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 260px;
}
.editor-mode {
  font-size: 11px; font-weight: 600; padding: 3px 10px; border-radius: 999px;
  background: var(--grad-mint); color: #fff; box-shadow: var(--shadow-mint); flex-shrink: 0;
}
.editor-mode.local { background: linear-gradient(135deg, #6366f1, #8b5cf6); box-shadow: 0 4px 12px rgba(99,102,241,0.3); }
.editor-mode.edit { background: linear-gradient(135deg, #38bdf8, #6366f1); box-shadow: 0 4px 12px rgba(56,189,248,0.3); }
.editor-topbar-right { display: flex; align-items: center; gap: 12px; flex-shrink: 0; }
.theme-switcher { display: flex; gap: 2px; padding: 3px; background: var(--glass-bg-strong); border: 1px solid var(--glass-border); border-radius: 8px; }
.theme-btn { border: none; background: transparent; cursor: pointer; width: 28px; height: 28px; border-radius: 6px; font-size: 14px; display: flex; align-items: center; justify-content: center; transition: all 0.2s var(--ease); opacity: 0.5; }
.theme-btn:hover { opacity: 0.8; }
.theme-btn.active { background: rgba(255,255,255,0.7); opacity: 1; box-shadow: 0 1px 3px rgba(0,0,0,0.08); }

.editor-meta {
  display: flex; flex-wrap: wrap; gap: 10px; padding: 10px 16px; flex-shrink: 0;
}
.meta-field { flex: 1; min-width: 140px; display: flex; flex-direction: column; gap: 4px; }
.meta-field.perms-field { min-width: 100%; }
.meta-field label { font-size: 11px; font-weight: 600; color: var(--text-sub); }
.meta-field input { padding: 7px 12px; font-size: 12px; border: 1px solid var(--glass-border); border-radius: var(--radius-sm); background: rgba(255,255,255,0.6); transition: all 0.2s var(--ease); width: 100%; box-sizing: border-box; }
.meta-field input:focus { border-color: var(--mint); box-shadow: 0 0 0 3px var(--mint-softer); outline: none; background: rgba(255,255,255,0.85); }
.meta-fill { flex: 1; }

.editor-workbench {
  display: flex; flex-direction: column;
  flex: 1; min-height: 0;
  padding: 12px; overflow: hidden;
}
.file-tabs { display: flex; gap: 2px; margin-bottom: 0; flex-shrink: 0; overflow-x: auto; }
.file-tab { display: flex; align-items: center; gap: 6px; padding: 6px 14px; font-size: 12px; font-weight: 500; border: 1px solid var(--glass-border); border-bottom: none; border-radius: var(--radius-sm) var(--radius-sm) 0 0; background: var(--glass-bg-soft); color: var(--text-sub); cursor: pointer; transition: all 0.2s var(--ease); white-space: nowrap; }
.file-tab.active { background: rgba(255,255,255,0.7); color: var(--mint); font-weight: 600; }
.file-tab.add { background: transparent; color: var(--mint); border-style: dashed; }
.file-tab.add:hover { background: var(--mint-softer); }
.ft-add { font-size: 14px; font-weight: 700; }
.file-remove {
  display: inline-flex; align-items: center; justify-content: center;
  width: 16px; height: 16px; border-radius: 50%;
  font-size: 12px; line-height: 1; color: var(--text-dim);
  transition: all 0.15s var(--ease);
}
.file-remove:hover { background: var(--danger-soft); color: var(--danger); }
.file-tab.active { background: rgba(255,255,255,0.7); color: var(--mint); font-weight: 600; }
.ft-icon { font-size: 10px; font-weight: 700; padding: 2px 6px; border-radius: 4px; }
.ft-icon.py { background: var(--mint-soft); color: var(--mint-deep); }
.ft-icon.json { background: rgba(245, 158, 11, 0.14); color: #d97706; }

/* ===== 权限下拉框 ===== */
.perms-field { flex: 1; min-width: 100%; position: relative; }
.perms-dropdown { position: relative; cursor: pointer; }
.perms-trigger {
  display: flex; align-items: center; gap: 6px;
  padding: 7px 12px; font-size: 12px;
  border: 1px solid var(--glass-border); border-radius: var(--radius-sm);
  background: rgba(255,255,255,0.6);
  color: var(--text-main); min-height: 34px; box-sizing: border-box;
  transition: all 0.2s var(--ease);
}
.perms-trigger:hover { border-color: var(--mint); }
.perms-trigger.empty { color: var(--text-dim); }
.perms-trigger .arrow { margin-left: auto; font-size: 10px; color: var(--text-dim); transition: transform 0.2s var(--ease); }
.perms-panel {
  position: absolute; top: calc(100% + 4px); left: 0; right: 0; z-index: 9999;
  background: #fff; border: 1px solid var(--glass-border);
  border-radius: var(--radius-md); box-shadow: 0 8px 24px rgba(0,0,0,0.12);
  max-height: 320px; overflow-y: auto;
}
.perm-option {
  display: flex; align-items: center; gap: 8px;
  padding: 8px 12px; cursor: pointer; transition: background 0.1s;
}
.perm-option:hover { background: var(--mint-soft); }
.perm-option.selected { background: var(--mint-soft); }
.perm-check {
  width: 16px; height: 16px; border-radius: 3px;
  border: 1.5px solid var(--glass-border); flex-shrink: 0;
  display: flex; align-items: center; justify-content: center;
  font-size: 11px; color: transparent; transition: all 0.15s;
}
.perm-option.selected .perm-check {
  background: var(--mint); border-color: var(--mint); color: #fff;
}
.perm-label { font-size: 12px; font-weight: 600; color: var(--text-main); min-width: 72px; }
.perm-desc { font-size: 11px; color: var(--text-dim); }
.drop-enter-active, .drop-leave-active { transition: all 0.15s var(--ease); }
.drop-enter-from, .drop-leave-to { opacity: 0; transform: translateY(-4px); }
.file-tab.active .ft-icon.py { background: var(--grad-mint); color: #fff; }
.file-tab.active .ft-icon.json { background: var(--amber); color: #fff; }
.editor-body { flex: 1; min-height: 0; border: 1px solid var(--glass-border); border-radius: 0 var(--radius-md) var(--radius-md) var(--radius-md); overflow: hidden; }
.editor-loading { display: flex; flex-direction: column; align-items: center; gap: 12px; height: 100%; color: var(--text-sub); justify-content: center; }
.spinner { width: 28px; height: 28px; border: 3px solid rgba(16,185,129,0.15); border-top-color: var(--mint); border-radius: 50%; animation: spin 0.8s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
.editor-actions { display: flex; gap: 10px; justify-content: flex-end; padding-top: 10px; flex-shrink: 0; }
.editor-local-btn { padding: 7px 14px; font-size: 13px; }

.pop-enter-active, .pop-leave-active { transition: all 0.3s var(--ease); }
.pop-enter-from, .pop-leave-to { opacity: 0; transform: scale(0.95) translateY(10px); }

/* ===== 运行日志 ===== */
.logs-pane { padding: 20px; }
.logs-controls {
  display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
}
.log-plugin-select, .log-level-select {
  padding: 6px 12px; font-size: 13px;
  border: 1px solid var(--glass-border); border-radius: var(--radius-sm);
  background: var(--glass-bg-strong); color: var(--text-main);
  cursor: pointer; transition: all 0.2s var(--ease);
  outline: none;
}
.log-plugin-select:hover, .log-level-select:hover { border-color: var(--mint-border); }
.log-plugin-select:focus, .log-level-select:focus { border-color: var(--mint); box-shadow: 0 0 0 3px var(--mint-softer); }
.log-plugin-select { min-width: 160px; }
.log-auto-btn.active { color: var(--mint-deep); border-color: var(--mint-border); background: var(--mint-soft); }
.log-loading { display: flex; flex-direction: column; align-items: center; gap: 12px; padding: 48px 20px; color: var(--text-sub); }
.log-hint { font-size: 12px; color: var(--text-dim); margin-top: 4px; }

/* 终端风格日志 */
.terminal {
  height: 480px;
  min-height: 320px;
  max-height: 70vh;
  background: #0d1117;
  border-radius: var(--radius-md);
  overflow: hidden;
  font-family: 'SF Mono', 'Fira Code', 'Consolas', 'Courier New', monospace;
  font-size: 13px;
  line-height: 1.6;
  border: 1px solid rgba(255, 255, 255, 0.06);
}
.terminal-content {
  height: 100%;
  padding: 14px 16px;
  overflow-y: auto;
}
.terminal .log-line {
  display: flex;
  margin-bottom: 4px;
  word-break: break-word;
  font-family: inherit;
  font-size: 13px;
  line-height: 1.6;
  transition: none;
}
.terminal .log-line:hover { background: rgba(255, 255, 255, 0.03); }
.terminal .log-time { color: #8b949e; margin-right: 12px; min-width: 100px; font-size: 12px; flex-shrink: 0; }
.terminal .log-content { flex: 1; min-width: 0; white-space: pre-wrap; color: #e6edf3; }
.terminal .log-error .log-content { color: #f85149; }
.terminal .log-warn .log-content { color: #f2cc60; }
.terminal .log-info .log-content { color: #79c0ff; }
.terminal .log-debug .log-content { color: #8b949e; }
.terminal .log-stderr .log-content { color: #d2a8ff; }
.terminal .log-line.log-error { background: rgba(248, 81, 73, 0.06); }
.terminal .log-line.log-warn { background: rgba(242, 204, 96, 0.05); }

/* ===== Responsive ===== */
@media (max-width: 768px) {
  .overview-card { flex-direction: column; align-items: stretch; }
  .overview-left { justify-content: center; }
  .overview-stats { justify-content: center; }
  .overview-actions { justify-content: center; }
  .tabs-nav { flex-wrap: wrap; }
  .tab-btn { flex: none; width: calc(50% - 4px); }
  .editor-page { height: auto; min-height: 0; }
  .dev-view.editor-open { margin: 0; padding: 12px 0 0; }
  .editor-meta { flex-wrap: wrap; }
  .meta-field { min-width: 140px; }
  .editor-workbench { min-height: 480px; }
  .editor-title-wrap { flex-wrap: wrap; }
  .editor-slug { max-width: 100%; }
  .logs-controls { width: 100%; }
  .log-plugin-select { min-width: 0; flex: 1; }
  .terminal { height: 400px; }
}
</style>