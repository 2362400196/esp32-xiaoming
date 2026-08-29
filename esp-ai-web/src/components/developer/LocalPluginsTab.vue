<template>
  <div class="tab-pane glass card-in">
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
      <button class="btn-ghost" @click="$emit('go-upload')">上传插件</button>
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
          <button v-if="p.source !== 'built-in' && !p.system && !isPublished(p.name)" class="row-btn publish"
            :disabled="publishing === p.name" title="发布到应用商店"
            @click="publishLocalPlugin(p)">
            {{ publishing === p.name ? '发布中…' : '发布' }}
          </button>
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
</template>

<script setup>
import {
  customLocalPlugins,
  isPublished,
  loadLocalInstalled,
  publishing,
  uninstallLocal,
  uninstalling,
  publishLocalPlugin,
} from '../../composables/useLocalPlugins'
import { openLocalEditEditor } from '../../composables/usePluginEditor'

defineEmits(['go-upload'])
</script>
