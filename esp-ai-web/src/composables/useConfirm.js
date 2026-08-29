// 通用确认弹窗（模块级单例）：任意组件 import { showConfirm } 即可弹出，
// 返回 Promise<boolean>；UI 由 components/developer/ConfirmDialog.vue 渲染。
import { ref } from 'vue'

export const confirmData = ref({
  show: false, title: '', message: '',
  confirmText: '确定', cancelText: '取消',
  danger: false, resolve: null,
})

export function useConfirmState() {
  return confirmData
}

export function showConfirm(options) {
  return new Promise(resolve => {
    confirmData.value = {
      show: true,
      title: options.title || '请确认',
      message: options.message || '',
      confirmText: options.confirmText || '确定',
      cancelText: options.cancelText || '取消',
      danger: options.danger !== false,
      resolve,
    }
  })
}

export function confirmOk() {
  confirmData.value.show = false
  confirmData.value.resolve?.(true)
}

export function confirmCancel() {
  confirmData.value.show = false
  confirmData.value.resolve?.(false)
}
