// Toast 桥接：子组件/组合式函数通过 toast() 发通知，
// 由 DeveloperView 挂载时把 emit 接到 setToastHandler 上。
import { ref } from 'vue'

const handler = ref((msg) => console.warn('[toast]', msg))

export function setToastHandler(fn) {
  handler.value = fn
}

export function toast(msg) {
  handler.value(msg)
}
