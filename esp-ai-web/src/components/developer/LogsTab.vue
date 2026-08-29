<template>
  <div class="tab-pane glass card-in logs-pane">
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
</template>

<script setup>
import {
  logView, pluginLogTerminalRef, allPluginNames,
  loadLogs, copyLogs, clearLogs, toggleAutoRefresh, formatLogTime,
} from '../../composables/usePluginLogs'
</script>
