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
      <!-- 全屏代码编辑器（组件见 components/developer/PluginEditor.vue） -->
      <PluginEditor v-if="codeEditor.show" :current-device="currentDevice" />

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
          <LocalPluginsTab v-if="activeTab === 'local'" @go-upload="activeTab = 'upload'" />
          <PublishedPluginsTab v-else-if="activeTab === 'published'" />
          <UploadTab v-else-if="activeTab === 'upload'" />
          <LogsTab v-else-if="activeTab === 'logs'" />
        </div>
      </div>

      <!-- 全局确认弹窗 -->
      <ConfirmDialog />
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onBeforeUnmount } from 'vue'
import { isLoggedIn } from '../api'
import { setToastHandler } from '../composables/useToastBridge'
import {
  devInfo, devLoading, enableDev, loadDevInfo,
  myPlugins, totalDownloads, formatDownloads,
} from '../composables/useDeveloper'
import { customLocalPlugins, loadLocalInstalled } from '../composables/useLocalPlugins'
import { codeEditor, openCreateEditor, onEditorShowChange } from '../composables/usePluginEditor'
import { logView, clearLogs, stopAutoRefresh } from '../composables/usePluginLogs'
import LocalPluginsTab from '../components/developer/LocalPluginsTab.vue'
import PublishedPluginsTab from '../components/developer/PublishedPluginsTab.vue'
import UploadTab from '../components/developer/UploadTab.vue'
import LogsTab from '../components/developer/LogsTab.vue'
import PluginEditor from '../components/developer/PluginEditor.vue'
import ConfirmDialog from '../components/developer/ConfirmDialog.vue'
import '../components/developer/developer.css'

const emit = defineEmits(['toast', 'editor-change'])

const props = defineProps({
  currentDevice: { type: Object, default: null },
})

const isLoggedInUser = computed(() => isLoggedIn())
const activeTab = ref('local')

// 编辑器开关 → 通知 App 隐藏/显示导航栏
onEditorShowChange(v => emit('editor-change', v))

// 快捷键：Esc 退出编辑器全屏；Ctrl/Cmd+L 清空日志（日志 Tab 激活时）
function onKeydown(e) {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'l' && activeTab.value === 'logs' && logView.value.plugin) {
    e.preventDefault()
    clearLogs()
  }
}

onMounted(() => {
  setToastHandler(msg => emit('toast', msg))
  loadDevInfo()
  loadLocalInstalled()
  window.addEventListener('keydown', onKeydown)
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKeydown)
  stopAutoRefresh()
})
</script>
