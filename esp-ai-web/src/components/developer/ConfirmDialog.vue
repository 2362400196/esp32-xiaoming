<template>
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
</template>

<script setup>
import { confirmData, confirmOk, confirmCancel } from '../../composables/useConfirm'
</script>
