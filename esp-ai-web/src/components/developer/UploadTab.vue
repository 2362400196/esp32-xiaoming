<template>
  <div class="tab-pane glass card-in">
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
      <button class="btn-mint" :disabled="uploading" @click="doUpload('market', { onInstalled: loadLocalInstalled })">
        {{ uploading === 'market' ? '上架中…' : '上架到市场' }}
      </button>
      <button class="btn-ghost" :disabled="uploading" @click="doUpload('local', { onInstalled: loadLocalInstalled })">
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
</template>

<script setup>
import {
  uploadFile, uploading, isDragging,
  onFileSelect, onDrop, doUpload,
} from '../../composables/useDeveloper'
import { loadLocalInstalled } from '../../composables/useLocalPlugins'
import { openCreateEditor } from '../../composables/usePluginEditor'
</script>
