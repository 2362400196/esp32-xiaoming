<template>
  <div class="app-select" tabindex="0" @blur="open = false">
    <div class="select-trigger" @click="open = !open">
      <span class="select-value" :class="{ placeholder: !display }">{{ display || placeholder }}</span>
      <span class="select-arrow" :class="{ up: open }">▾</span>
    </div>
    <transition name="drop">
      <div v-if="open" class="select-options">
        <div v-for="opt in normOptions" :key="opt.value" class="select-option"
          :class="{ selected: opt.value === modelValue }" @mousedown.prevent="choose(opt.value)">
          <span class="opt-main">
            <span class="opt-label">{{ opt.label }}</span>
            <span v-if="opt.tag" class="opt-tag">{{ opt.tag }}</span>
          </span>
          <span v-if="opt.value === modelValue" class="check">✓</span>
        </div>
        <template v-if="allowCustom">
          <div v-if="!customMode" class="select-option custom" @mousedown.prevent="customMode = true">
            <span>✎ 自定义…</span>
          </div>
          <input v-else class="custom-input" v-model="customValue" placeholder="输入自定义值"
            @keyup.enter="applyCustom" @blur="applyCustom" ref="customInput" />
        </template>
      </div>
    </transition>
  </div>
</template>

<script setup>
import { ref, computed, watch, nextTick } from 'vue'

const props = defineProps({
  modelValue: { type: String, default: '' },
  options: { type: Array, default: () => [] },   // 字符串 或 { label, value, tag }
  placeholder: { type: String, default: '请选择' },
  allowCustom: { type: Boolean, default: false },
})
const emit = defineEmits(['update:modelValue'])

const open = ref(false)
const customMode = ref(false)
const customValue = ref('')
const customInput = ref(null)

const normOptions = computed(() =>
  props.options.map(o => typeof o === 'string' ? { label: o, value: o, tag: '' } : o)
)

const display = computed(() => {
  if (!props.modelValue) return ''
  const found = normOptions.value.find(o => o.value === props.modelValue)
  return found ? found.label : props.modelValue
})

function choose(opt) {
  emit('update:modelValue', opt)
  open.value = false
}

function startCustom() {
  customMode.value = true
  nextTick(() => customInput.value?.focus())
}

function applyCustom() {
  const v = customValue.value.trim()
  if (v) emit('update:modelValue', v)
  customMode.value = false
  open.value = false
}

watch(() => props.modelValue, () => { customValue.value = props.modelValue })
</script>

<style scoped>
.app-select { position: relative; user-select: none; }
.select-trigger {
  display: flex; align-items: center; justify-content: space-between; gap: 8px;
  background: rgba(255,255,255,0.55); border: 1px solid var(--glass-border); border-radius: 10px;
  padding: 10px 14px; font-size: 14px; color: var(--text-main); cursor: pointer;
  transition: border-color 0.2s, box-shadow 0.2s, background 0.2s;
}
.select-trigger:hover { border-color: var(--mint); background: rgba(255,255,255,0.7); }
.select-trigger:focus-within { border-color: var(--mint); box-shadow: 0 0 0 3px rgba(16, 185, 129, 0.12); }
.select-value.placeholder { color: var(--text-dim); }
.select-arrow { color: var(--text-dim); font-size: 12px; transition: transform 0.2s; }
.select-arrow.up { transform: rotate(180deg); }

.select-options {
  position: absolute; top: calc(100% + 6px); left: 0; right: 0; z-index: 20;
  background: var(--grad-panel);
  backdrop-filter: var(--glass-blur);
  -webkit-backdrop-filter: var(--glass-blur);
  border: 1px solid var(--glass-border);
  border-radius: 10px;
  box-shadow: var(--shadow-hover), var(--glass-hi);
  padding: 6px; max-height: 220px; overflow-y: auto;
}
.select-option {
  display: flex; align-items: center; justify-content: space-between;
  padding: 9px 12px; border-radius: 8px; font-size: 13px; color: var(--text-main);
  cursor: pointer; transition: background 0.15s;
}
.select-option:hover { background: var(--mint-soft); }
.select-option.selected { color: var(--mint); font-weight: 600; background: var(--mint-soft); }
.opt-main { display: flex; align-items: center; gap: 8px; min-width: 0; }
.opt-label { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.opt-tag { flex-shrink: 0; font-size: 10px; padding: 2px 8px; border-radius: 999px; background: rgba(240,245,242,0.6); color: var(--text-sub); font-weight: 400; }
.select-option.selected .opt-tag { background: rgba(16,185,129,0.15); color: var(--mint); }
.check { font-weight: 700; flex-shrink: 0; }
.select-option.custom { color: var(--text-sub); }
.custom-input {
  width: 100%; border: 1px solid var(--mint); border-radius: 8px;
  padding: 8px 12px; font-size: 13px; outline: none;
  background: rgba(255,255,255,0.7);
}

.drop-enter-active, .drop-leave-active { transition: all 0.18s ease; }
.drop-enter-from, .drop-leave-to { opacity: 0; transform: translateY(-4px); }
</style>
