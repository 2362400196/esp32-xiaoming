<template>
  <header class="navbar">
    <div class="nav-inner">
      <div class="nav-brand" @click="$emit('switch', 'home')">
        <span class="brand-logo">🤖</span>
        <span class="brand-name">ESP-<span class="text-mint">AI</span></span>
      </div>

      <nav class="nav-menu">
        <button v-for="item in items" :key="item.id" class="nav-item"
          :class="{ active: active === item.id }" @click="$emit('switch', item.id)">
          <span class="nav-icon" v-html="icons[item.id] || ''"></span>
          <span class="nav-label">{{ item.label }}</span>
        </button>
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
import { computed } from 'vue'
import { getUser, isLoggedIn } from '../api'

defineProps({
  active: { type: String, default: 'home' },
  items: { type: Array, default: () => [] },
})
defineEmits(['switch'])

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
  admin: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><path d="M9 12l2 2 4-4"/></svg>',
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
/* 导航栏隐藏/显示的过渡动画（编辑器打开时收起，关闭时展开） */
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
}
.nav-item:hover {
  color: var(--text-main);
  background: rgba(255, 255, 255, 0.55);
  transform: translateY(-1px);
}
.nav-icon { display: flex; width: 16px; height: 16px; opacity: 0.7; }
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
}
</style>