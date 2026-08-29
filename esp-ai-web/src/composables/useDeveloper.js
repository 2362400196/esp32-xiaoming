// 开发者信息与已发布插件（模块级单例，状态跨组件共享）
import { ref, computed } from 'vue'
import { api, isLoggedIn } from '../api'
import { toast } from './useToastBridge'
import { showConfirm } from './useConfirm'

export const devInfo = ref({ is_developer: false, developer_api_key: '', username: '', email: '' })
export const devLoading = ref(false)
export const myPlugins = ref([])
export const deletingPlugin = ref(null)

// 上传插件（zip）：同时服务于"上架市场"与"本地测试"两个动作
export const uploadFile = ref(null)
export const uploading = ref(false) // false | 'market' | 'local'
export const isDragging = ref(false)

export const totalDownloads = computed(() => {
  const total = myPlugins.value.reduce((sum, p) => sum + (p.total_downloads || 0), 0)
  return formatDownloads(total)
})

export async function loadDevInfo() {
  if (!isLoggedIn()) return
  try {
    const res = await api.devInfo()
    if (res.status === 200 && res.data?.code === 0) {
      devInfo.value = res.data.data || {}
      if (devInfo.value.is_developer) await loadMyPlugins()
    } else {
      console.error('[Developer] loadDevInfo 失败:', res.status, res.data)
    }
  } catch (e) {
    console.error('[Developer] loadDevInfo 异常:', e)
  }
}

export async function loadMyPlugins() {
  try {
    const res = await api.devMyPlugins()
    if (res.status === 200 && res.data?.code === 0) {
      myPlugins.value = res.data.data || []
    } else {
      console.error('[Developer] loadMyPlugins 失败:', res.status, res.data)
      myPlugins.value = []
      toast(res.data?.message || '加载我的插件列表失败')
    }
  } catch (e) {
    console.error('[Developer] loadMyPlugins 异常:', e)
    myPlugins.value = []
    toast('加载插件列表异常')
  }
}

export async function deleteMyPlugin(p) {
  const ok = await showConfirm({
    title: '删除插件',
    message: `确定删除「${p.name}」？所有版本和文件将一并删除，已安装用户不受影响。`,
    confirmText: '确认删除',
    cancelText: '取消',
    danger: true,
  })
  if (!ok) return
  deletingPlugin.value = p.slug
  const res = await api.devDeletePlugin(p.slug)
  deletingPlugin.value = null
  if (res.status === 200 && res.data?.code === 0) {
    toast('插件已删除')
    await loadMyPlugins()
  } else {
    toast(res.data?.message || '删除失败')
  }
}

export async function enableDev() {
  devLoading.value = true
  const res = await api.devEnable()
  devLoading.value = false
  if (res.status === 200 && res.data?.code === 0) {
    devInfo.value = { ...devInfo.value, ...res.data.data, is_developer: true }
    toast('开发者模式已开启')
  } else {
    toast(res.data?.message || '操作失败')
  }
}

export function onFileSelect(e) { if (e.target.files[0]) uploadFile.value = e.target.files[0] }

export function onDrop(e) {
  isDragging.value = false
  const f = e.dataTransfer.files[0]
  if (f && f.name.endsWith('.zip')) uploadFile.value = f
}

export async function doUpload(mode, { onInstalled } = {}) {
  if (!uploadFile.value) return
  uploading.value = mode
  if (mode === 'market') {
    try {
      const res = await api.devUpload(uploadFile.value)
      if (res.status === 200 && res.data?.code === 0) {
        toast('插件已上架到市场')
        uploadFile.value = null
        await loadMyPlugins()
        if (myPlugins.value.length === 0) {
          toast('上架成功，但列表加载异常，请刷新页面')
        }
      } else {
        toast(res.data?.message || '上架失败')
      }
    } catch (e) {
      toast('上传异常：' + e.message)
    }
  } else {
    try {
      const res = await api.installPluginZip(uploadFile.value)
      if (res.status === 200 && res.data?.code === 0) {
        toast('插件已安装，可测试使用')
        uploadFile.value = null
        if (onInstalled) await onInstalled()
      } else {
        toast(res.data?.message || '安装失败')
      }
    } catch (e) {
      toast('安装异常：' + e.message)
    }
  }
  uploading.value = false
}

export function formatDownloads(n) {
  if (!n) return '0'
  if (n < 1000) return String(n)
  if (n < 10000) return (n / 1000).toFixed(1) + 'k'
  return (n / 10000).toFixed(1) + 'w'
}
