<template>
  <div class="tab-pane glass card-in">
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
</template>

<script setup>
import {
  myPlugins, deletingPlugin, deleteMyPlugin, loadMyPlugins, formatDownloads,
} from '../../composables/useDeveloper'
import { openEditEditor, openCreateEditor } from '../../composables/usePluginEditor'
</script>
