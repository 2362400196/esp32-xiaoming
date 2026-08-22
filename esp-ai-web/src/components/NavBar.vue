<template>
  <header class="navbar">
    <div class="nav-inner">
      <div class="nav-brand" @click="$emit('switch', 'home')">
        <span class="brand-logo">🤖</span>
        <span class="brand-name">ESP-<span class="text-mint">AI</span></span>
      </div>

      <nav class="nav-menu">
        <template v-for="item in items" :key="item.id">
          <!-- 有子项的折叠菜单 -->
          <div v-if="item.children?.length" class="nav-dropdown-wrap">
            <button class="nav-item" :class="{ active: dropdownOpen === item.id }"
              @click.stop="toggleDropdown(item.id)">
              <span class="nav-icon" v-html="icons[item.icon || item.id] || ''"></span>
              <span class="nav-label">{{ item.label }}</span>
              <span class="nav-chevron" :class="{ open: dropdownOpen === item.id }">▾</span>
            </button>
            <Transition name="drop">
              <div v-if="dropdownOpen === item.id" class="nav-dropdown" @click.stop>
                <button v-for="child in item.children" :key="child.id"
                  class="nav-dropdown-item" :class="{ active: active === child.id }"
                  @click="selectChild(child.id)">
                  <span class="nav-icon" v-html="icons[child.icon || child.id] || ''"></span>
                  <span class="nav-label">{{ child.label }}</span>
                </button>
              </div>
            </Transition>
          </div>
          <!-- 普通导航项 -->
          <button v-else class="nav-item" :class="{ active: active === item.id }"
            @click="$emit('switch', item.id)">
            <span class="nav-icon" v-html="icons[item.icon || item.id] || ''"></span>
            <span class="nav-label">{{ item.label }}</span>
          </button>
        </template>
      </nav>

      <div class="nav-user">
        <template v-if="loggedIn">
          <span class="user-name">{{ userName }}</span>
          <span class="user-avatar">{{ (userName || '?')[0].toUpperCase() }}</span>
        </template>
        <button v-else class="btn-mint nav-login" @click="$emit('switch', 'profile')">登录</button>
      </div>
    </div>
  </header>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { getUser, isLoggedIn } from '../api'

const props = defineProps({
  active: { type: String, default: 'home' },
  items: { type: Array, default: () => [] },
})
const emit = defineEmits(['switch'])

const dropdownOpen = ref(null)

function toggleDropdown(id) {
  dropdownOpen.value = dropdownOpen.value === id ? null : id
}

function selectChild(id) {
  dropdownOpen.value = null
  emit('switch', id)
}

function handleClickOutside() {
  dropdownOpen.value = null
}

onMounted(() => document.addEventListener('click', handleClickOutside))
onUnmounted(() => document.removeEventListener('click', handleClickOutside))

const loggedIn = computed(() => isLoggedIn())
const userName = computed(() => getUser()?.nickname || getUser()?.email?.split('@')[0] || '用户')

const icons = {
  devices: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="3" width="20" height="14" rx="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg>',
  store: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M4 10h16l-1 10a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2z"/><path d="M6 6l2-3h8l2 3"/><path d="M6 10a3 3 0 0 0 6 0 3 3 0 0 0 6 0"/></svg>',
  developer: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/></svg>',
  control: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/></svg>',
  emotion: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M8 14s1.5 2 4 2 4-2 4-2"/><line x1="9" y1="9" x2="9.01" y2="9"/><line x1="15" y1="9" x2="15.01" y2="9"/></svg>',
  skills: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M14.7 6.3a4.5 4.5 0 0 0-6.4 6.4L3 18v3h3l5.3-5.3a4.5 4.5 0 0 0 6.4-6.4L14 12l-2-2 3.4-3.4a4.2 4.2 0 0 1-.7-.3z"/></svg>',
  tool: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/></svg>',
  profile: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>',
  wechat: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M17 12a7 7 0 1 0-13 5l-1 3 3.5-1.2A7 7 0 0 0 17 12z"/><circle cx="9" cy="12" r=".5" fill="currentColor"/><circle cx="13" cy="12" r=".5" fill="currentColor"/><path d="M21 12a7 7 0 0 1-9 6.7"/></svg>',
  admin: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><path d="M9 12l2 2 4-4"/></svg>',
  mcp: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="3" width="20" height="14" rx="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg>',
  // 插件预置图标
  server: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="3" width="20" height="14" rx="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg>',
  message: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M17 12a7 7 0 1 0-13 5l-1 3 3.5-1.2A7 7 0 0 0 17 12z"/><circle cx="9" cy="12" r=".5" fill="currentColor"/><circle cx="13" cy="12" r=".5" fill="currentColor"/><path d="M21 12a7 7 0 0 1-9 6.7"/></svg>',
  clock: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/></svg>',
  chart: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M14.7 6.3a4.5 4.5 0 0 0-6.4 6.4L3 18v3h3l5.3-5.3a4.5 4.5 0 0 0 6.4-6.4L14 12l-2-2 3.4-3.4a4.2 4.2 0 0 1-.7-.3z"/></svg>',
  settings: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>',
  cloud: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M17.5 19H9a7 7 0 1 1 6.71-9h1.79a4.5 4.5 0 1 1 0 9z"/></svg>',
  bell: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/></svg>',
  star: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>',
  // 插件组图标
  plugin_group: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/></svg>',
}
</script>

<style scoped>
.navbar {
  position: sticky;
  top: 12px;
  z-index: 100;
  padding: 0 20px;
  height: 60px;
}
.nav-enter-active, .nav-leave-active {
  overflow: hidden;
  transition: height 0.32s var(--ease), opacity 0.32s var(--ease), transform 0.32s var(--ease);
}
.nav-enter-from, .nav-leave-to {
  height: 0;
  opacity: 0;
  transform: translateY(-24px);
}
.nav-inner {
  max-width: 1080px;
  margin: 0 auto;
  height: 60px;
  padding: 0 20px;
  display: flex;
  align-items: center;
  gap: 24px;
  background: linear-gradient(155deg, rgba(255, 255, 255, 0.72), rgba(255, 255, 255, 0.42));
  backdrop-filter: var(--glass-blur);
  -webkit-backdrop-filter: var(--glass-blur);
  border: 1px solid var(--glass-border);
  border-radius: 20px;
  box-shadow: 0 14px 40px rgba(23, 52, 74, 0.12), var(--glass-hi);
}
.nav-brand {
  display: flex; align-items: center; gap: 8px;
  cursor: pointer;
  transition: opacity 0.25s var(--ease);
  flex-shrink: 0;
}
.nav-brand:hover { opacity: 0.85; }
.brand-logo {
  font-size: 22px;
  filter: drop-shadow(0 3px 8px rgba(16, 185, 129, 0.3));
  animation: brandFloat 3s ease-in-out infinite;
}
@keyframes brandFloat {
  0%, 100% { transform: translateY(0) rotate(0deg); }
  50% { transform: translateY(-3px) rotate(-3deg); }
}
.brand-name { font-size: 18px; font-weight: 800; letter-spacing: 0.5px; }

.nav-menu { display: flex; gap: 4px; flex: 1; justify-content: center; }
.nav-item {
  display: flex;
  align-items: center;
  gap: 6px;
  border: none;
  background: transparent;
  padding: 8px 16px;
  font-size: 13px;
  color: var(--text-sub);
  cursor: pointer;
  border-radius: 14px;
  transition: all 0.3s var(--ease);
  position: relative;
  white-space: nowrap;
}
.nav-item:hover {
  color: var(--text-main);
  background: rgba(255, 255, 255, 0.55);
  transform: translateY(-1px);
}
.nav-icon { display: flex; width: 16px; height: 16px; opacity: 0.7; flex-shrink: 0; }
.nav-item.active {
  color: var(--mint-deep);
  font-weight: 600;
  background: var(--mint-soft);
  box-shadow: inset 0 0 0 1px var(--mint-border), 0 6px 16px rgba(16, 185, 129, 0.16);
  animation: navBreathe 2.8s ease-in-out infinite;
}
.nav-item.active .nav-icon { opacity: 1; }
@keyframes navBreathe {
  0%, 100% { box-shadow: inset 0 0 0 1px var(--mint-border), 0 6px 16px rgba(16, 185, 129, 0.16); }
  50% { box-shadow: inset 0 0 0 1px var(--mint-border), 0 8px 22px rgba(16, 185, 129, 0.26); }
}

/* 折叠菜单 */
.nav-dropdown-wrap { position: relative; }
.nav-chevron {
  font-size: 10px;
  margin-left: 2px;
  transition: transform 0.25s var(--ease);
  opacity: 0.5;
}
.nav-chevron.open { transform: rotate(180deg); }

.nav-dropdown {
  position: absolute;
  top: calc(100% + 8px);
  left: 50%;
  transform: translateX(-50%);
  min-width: 160px;
  background: rgba(255, 255, 255, 0.88);
  backdrop-filter: var(--glass-blur);
  -webkit-backdrop-filter: var(--glass-blur);
  border: 1px solid var(--glass-border);
  border-radius: 14px;
  padding: 6px;
  box-shadow: 0 12px 36px rgba(23, 52, 74, 0.15), var(--glass-hi);
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.nav-dropdown-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 14px;
  border: none;
  background: transparent;
  font-size: 13px;
  color: var(--text-sub);
  cursor: pointer;
  border-radius: 10px;
  transition: all 0.25s var(--ease);
  white-space: nowrap;
}
.nav-dropdown-item:hover {
  color: var(--text-main);
  background: rgba(255, 255, 255, 0.6);
}
.nav-dropdown-item.active {
  color: var(--mint-deep);
  font-weight: 600;
  background: var(--mint-soft);
}

/* 下拉动画 */
.drop-enter-active, .drop-leave-active {
  transition: opacity 0.2s var(--ease), transform 0.2s var(--ease);
}
.drop-enter-from, .drop-leave-to {
  opacity: 0;
  transform: translateX(-50%) translateY(-6px);
}

.nav-user { display: flex; align-items: center; gap: 10px; flex-shrink: 0; }
.user-name { font-size: 13px; color: var(--text-sub); max-width: 120px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.user-avatar {
  width: 36px; height: 36px; border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  font-size: 14px; font-weight: 700; color: #fff;
  background: var(--grad-brand);
  box-shadow: var(--shadow-mint), inset 0 1px 0 rgba(255, 255, 255, 0.35);
  animation: avatarBreathe 3s ease-in-out infinite;
}
@keyframes avatarBreathe {
  0%, 100% { box-shadow: 0 4px 12px rgba(16, 185, 129, 0.18); }
  50% { box-shadow: 0 6px 20px rgba(16, 185, 129, 0.32); }
}
.nav-login { padding: 8px 22px; }

@media (max-width: 720px) {
  .navbar { top: 8px; padding: 0 12px; height: 56px; }
  .nav-inner { height: 56px; padding: 0 12px; gap: 10px; border-radius: 16px; }
  .nav-item { padding: 8px 10px; }
  .nav-label { font-size: 12px; }
  .user-name { display: none; }
  .nav-dropdown { left: 0; transform: none; }
  .drop-enter-from, .drop-leave-to { transform: translateY(-6px); }
}
</style>