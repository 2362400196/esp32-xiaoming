// 本地已安装插件（模块级单例）
import { ref, computed } from 'vue'
import { api } from '../api'
import { toast } from './useToastBridge'
import { showConfirm } from './useConfirm'
import { myPlugins, loadMyPlugins } from './useDeveloper'

export const localInstalled = ref([])
export const uninstalling = ref('')
export const publishing = ref('')

export const customLocalPlugins = computed(() =>
  localInstalled.value.filter(p => p.source !== 'built-in' && !p.system))

export async function loadLocalInstalled() {
  const res = await api.installedPlugins()
  if (res.status === 200 && res.data?.code === 0) {
    localInstalled.value = res.data.data || []
  }
}

export async function uninstallLocal(p) {
  const ok = await showConfirm({
    title: '卸载插件',
    message: `确定卸载「${p.title || p.name}」吗？此操作不可撤销。`,
    confirmText: '确认卸载',
    cancelText: '取消',
    danger: true,
  })
  if (!ok) return
  uninstalling.value = p.name
  try {
    const res = await api.uninstallPlugin(p.name)
    if (res.status === 200 && res.data?.code === 0) {
      toast('插件已卸载')
      await loadLocalInstalled()
    } else {
      toast(res.data?.message || '卸载失败')
    }
  } catch (e) {
    toast('卸载异常')
  }
  uninstalling.value = ''
}

// 语义化版本比较：a > b 返回 true
export function versionGt(a, b) {
  const pa = String(a || '0').split('.').map(Number)
  const pb = String(b || '0').split('.').map(Number)
  for (let i = 0; i < 3; i++) {
    const x = pa[i] || 0, y = pb[i] || 0
    if (x !== y) return x > y
  }
  return false
}

// 版本号 patch 位 +1
export function bumpVersion(ver) {
  if (!ver) return '1.0.0'
  const parts = ver.split('.')
  const patch = parseInt(parts[2] || '0') + 1
  return `${parts[0] || '1'}.${parts[1] || '0'}.${patch}`
}

// 本地插件是否已在应用商店发布（已发布则隐藏发布按钮）
export function isPublished(name) {
  const slug = String(name || '').trim().toLowerCase()
  return myPlugins.value.some(m => String(m.slug || '').trim().toLowerCase() === slug)
}

// 发布本地插件到应用商店：发布后本地插件保留，可继续编辑再发布
export async function publishLocalPlugin(p) {
  const ok = await showConfirm({
    title: '发布到应用商店',
    message: `确定将「${p.title || p.name}」发布到应用商店吗？发布后本地插件将保留，可在本地继续使用和编辑。`,
    confirmText: '发布',
    cancelText: '取消',
    danger: false,
  })
  if (!ok) return
  publishing.value = p.name
  try {
    const srcRes = await api.getLocalPluginSource(p.name)
    if (srcRes.status !== 200 || srcRes.data?.code !== 0) {
      toast(srcRes.data?.message || '获取本地源码失败')
      publishing.value = ''
      return
    }
    const d = srcRes.data.data || {}
    const manifest = d.manifest || {}
    const slug = String(manifest.id || p.name || '').trim().toLowerCase()
    if (!slug) { toast('manifest.json 缺少 id 字段，无法发布'); publishing.value = ''; return }
    const files = d.files || []
    const pluginCode = d.plugin_code || ''
    const name = manifest.name || p.title || p.name
    const version = manifest.version || p.version || '1.0.0'
    const description = manifest.description || ''
    const category = manifest.category || 'general'
    const tags = Array.isArray(manifest.tags) ? manifest.tags : []
    const changelog = manifest.changelog || ''

    // 已存在则更新新版本（自动 bump 版本号），否则创建
    const existsRes = await api.marketplaceDetail(slug)
    const exists = existsRes.status === 200 && existsRes.data?.code === 0
    let res
    if (exists) {
      const latest = existsRes.data.data?.latest_version || '0.0.0'
      const newVersion = versionGt(version, latest) ? version : bumpVersion(latest)
      const updManifest = { ...manifest, id: slug, name, version: newVersion, description, category, tags }
      res = await api.devUpdatePluginSource(slug, {
        plugin_code: pluginCode,
        files,
        manifest: updManifest,
        changelog: changelog || '重新发布',
      })
    } else {
      res = await api.devCreatePlugin({
        slug, name, description, version, category, tags,
        plugin_code: pluginCode, files, changelog,
      })
    }
    if (res.status !== 200 || res.data?.code !== 0) {
      toast(res.data?.message || '发布失败')
      publishing.value = ''
      return
    }

    toast(`「${name}」已发布到应用商店，本地插件已保留`)
    await Promise.all([loadLocalInstalled(), loadMyPlugins()])
  } catch (e) {
    toast('发布异常：' + (e.message || ''))
  }
  publishing.value = ''
}
