<template>
  <transition name="drawer">
    <div v-if="open" class="drawer-mask" @click.self="$emit('close')">
      <div class="drawer-panel">
        <div class="drawer-header">
          <h3>插件设置</h3>
          <button class="drawer-close" @click="$emit('close')">✕</button>
        </div>

        <div class="drawer-body">
          <template v-if="codeEditor.mode === 'create'">
            <div class="dw-field">
              <label>插件 ID <span class="req">*</span></label>
              <input v-model="codeEditor.slug" placeholder="英文，如 my_plugin" />
            </div>
            <div class="dw-field">
              <label>插件名称 <span class="req">*</span></label>
              <input v-model="codeEditor.name" placeholder="如：我的插件" />
            </div>
            <div class="dw-field">
              <label>描述</label>
              <textarea v-model="codeEditor.description" rows="2" placeholder="插件功能描述"></textarea>
            </div>
            <div class="dw-field">
              <label>版本号</label>
              <input v-model="codeEditor.version" placeholder="1.0.0" />
            </div>
            <div class="dw-field">
              <label>权限（声明后 SDK 对应能力才可用）</label>
              <div class="dw-perms">
                <div v-for="perm in ALL_PERMS" :key="perm.id"
                  class="dw-perm"
                  :class="{ selected: codeEditor.permissions.includes(perm.id) }"
                  @click="togglePerm(perm.id)">
                  <span class="dw-perm-check">✓</span>
                  <span class="dw-perm-label">{{ perm.id }}</span>
                  <span class="dw-perm-desc">{{ perm.desc }}</span>
                </div>
              </div>
            </div>
          </template>
      <template v-else>
        <div class="dw-field">
          <label>新版本号</label>
          <input v-model="codeEditor.version" placeholder="1.0.1" />
        </div>
        <div class="dw-field">
          <label>更新说明</label>
          <textarea v-model="codeEditor.changelog" rows="3" placeholder="本次更新内容"></textarea>
        </div>
        <div class="dw-field">
          <label>权限（保存时写入 manifest.json）</label>
          <div class="dw-perms">
            <div v-for="perm in ALL_PERMS" :key="perm.id"
              class="dw-perm"
              :class="{ selected: codeEditor.permissions.includes(perm.id) }"
              @click="togglePerm(perm.id)">
              <span class="dw-perm-check">✓</span>
              <span class="dw-perm-label">{{ perm.id }}</span>
              <span class="dw-perm-desc">{{ perm.desc }}</span>
            </div>
          </div>
        </div>
      </template>
        </div>

        <div class="drawer-footer">
          <button class="btn-mint" @click="$emit('close')">完成</button>
        </div>
      </div>
    </div>
  </transition>
</template>

<script setup>
import { watch } from 'vue'
import { ALL_PERMS } from '../../utils/pluginTemplates'
import { codeEditor, togglePerm } from '../../composables/usePluginEditor'

defineProps({
  open: { type: Boolean, default: false },
  // 编辑模式下表单字段与代码无关，无脏概念；create 模式下字段变更由父级跟踪
  settingsDirty: { type: Boolean, default: false },
})
defineEmits(['close'])
</script>

<style scoped>
.drawer-mask {
  position: fixed; inset: 0; z-index: 300;
  background: rgba(15, 23, 42, 0.35); backdrop-filter: blur(6px);
  display: flex; justify-content: flex-end;
}
.drawer-panel {
  width: min(380px, 92vw); height: 100%;
  background: var(--grad-panel, #fff);
  box-shadow: -12px 0 40px rgba(23, 52, 74, 0.15);
  display: flex; flex-direction: column;
  overflow: hidden;
}
.drawer-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 16px 20px; border-bottom: 1px solid var(--glass-border-soft, rgba(0,0,0,0.06));
  flex-shrink: 0;
}
.drawer-header h3 { font-size: 16px; font-weight: 700; margin: 0; }
.drawer-close {
  width: 30px; height: 30px; border: none; border-radius: 8px;
  background: transparent; color: var(--text-sub, #5b6b78);
  font-size: 14px; cursor: pointer; transition: all 0.2s;
}
.drawer-close:hover { background: var(--mint-soft, rgba(16,185,129,0.12)); color: var(--mint-deep, #059669); }

.drawer-body { flex: 1; overflow-y: auto; padding: 18px 20px; display: flex; flex-direction: column; gap: 16px; }

.dw-field { display: flex; flex-direction: column; gap: 5px; }
.dw-field label { font-size: 12px; font-weight: 600; color: var(--text-sub, #5b6b78); }
.dw-field .req { color: var(--danger, #ef4444); }
.dw-field input, .dw-field textarea {
  padding: 9px 12px; font-size: 13px; font-family: inherit;
  border: 1px solid var(--glass-border, rgba(0,0,0,0.08)); border-radius: 10px;
  background: rgba(255,255,255,0.8); color: var(--text-main, #12212e);
  outline: none; transition: all 0.2s; box-sizing: border-box; resize: vertical;
}
.dw-field input:focus, .dw-field textarea:focus {
  border-color: var(--mint, #10b981);
  box-shadow: 0 0 0 3px var(--mint-soft, rgba(16,185,129,0.12));
}

.dw-perms { display: flex; flex-direction: column; gap: 4px; max-height: 320px; overflow-y: auto; }
.dw-perm {
  display: flex; align-items: center; gap: 8px;
  padding: 8px 10px; border-radius: 10px; cursor: pointer;
  border: 1px solid transparent; transition: all 0.15s;
}
.dw-perm:hover { background: var(--mint-soft, rgba(16,185,129,0.12)); }
.dw-perm.selected { background: var(--mint-soft, rgba(16,185,129,0.12)); border-color: var(--mint-border, rgba(16,185,129,0.35)); }
.dw-perm-check {
  width: 16px; height: 16px; border-radius: 4px; flex-shrink: 0;
  border: 1.5px solid var(--glass-border, rgba(0,0,0,0.1));
  display: flex; align-items: center; justify-content: center;
  font-size: 11px; color: transparent; transition: all 0.15s;
}
.dw-perm.selected .dw-perm-check { background: var(--mint, #10b981); border-color: var(--mint, #10b981); color: #fff; }
.dw-perm-label { font-size: 12px; font-weight: 600; color: var(--text-main, #12212e); min-width: 70px; }
.dw-perm-desc { font-size: 11px; color: var(--text-dim, #8fa0ad); flex: 1; }

.drawer-footer {
  padding: 14px 20px; border-top: 1px solid var(--glass-border-soft, rgba(0,0,0,0.06));
  display: flex; justify-content: flex-end; flex-shrink: 0;
}

.drawer-enter-active, .drawer-leave-active { transition: all 0.28s var(--ease, ease); }
.drawer-enter-from, .drawer-leave-to { opacity: 0; }
.drawer-enter-from .drawer-panel, .drawer-leave-to .drawer-panel { transform: translateX(100%); }
.drawer-enter-active .drawer-panel, .drawer-leave-active .drawer-panel { transition: transform 0.28s var(--ease, ease); }
</style>
