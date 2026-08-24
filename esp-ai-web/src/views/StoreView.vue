<template>
  <div class="store-view">
    <!-- 主内容区：市场 -->
    <div class="market-main">
      <!-- 搜索工具栏 -->
      <div class="market-toolbar glass card-in">
        <div class="search-box">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
            <circle cx="11" cy="11" r="8"/>
            <line x1="21" y1="21" x2="16.65" y2="16.65"/>
          </svg>
          <input class="search-input" v-model="searchQuery" placeholder="搜索插件名称或描述…"
            @keyup.enter="searchMarket" />
        </div>
        <div class="filter-group">
          <select class="sort-select" v-model="sortBy" @change="loadMarket">
            <option value="downloads">最多下载</option>
            <option value="rating">最高评分</option>
            <option value="newest">最新发布</option>
          </select>
          <select class="cat-select" v-model="category" @change="loadMarket">
            <option value="">全部分类</option>
            <option v-for="c in categories" :key="c.name" :value="c.name">{{ c.name }}（{{ c.count }}）</option>
          </select>
        </div>
      </div>

      <!-- 加载状态 -->
      <div v-if="marketLoading" class="loading-state glass">
        <div class="spinner"></div>
        <p>正在加载市场插件…</p>
      </div>

      <!-- 空状态 -->
      <div v-else-if="marketList.length === 0" class="empty-state glass">
        <div class="empty-icon">
          <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1" stroke-linecap="round">
            <circle cx="11" cy="11" r="8"/>
            <line x1="21" y1="21" x2="16.65" y2="16.65"/>
          </svg>
        </div>
        <p v-if="searchQuery">没有找到匹配「{{ searchQuery }}」的插件</p>
        <p v-else>市场暂时还没有插件</p>
      </div>

      <!-- 市场插件网格 -->
      <div v-else class="market-grid">
        <div v-for="(p, i) in marketList" :key="p.slug || p.name" class="market-card glass card-in"
          :style="{ animationDelay: i * 0.04 + 's' }" :class="{ installed: isInstalled(p) }"
          @click="openDetail(p)">
          <div class="market-card-header">
            <div class="market-icon">
              <span>{{ (p.name || p.slug).charAt(0).toUpperCase() }}</span>
            </div>
            <div class="market-info">
              <div class="market-title-row">
                <p class="market-name">{{ p.name }}</p>
                <span v-if="isInstalled(p)" class="installed-badge">已安装</span>
              </div>
              <p class="market-desc">{{ p.description }}</p>
            </div>
          </div>
          <div class="market-meta-row">
            <template v-if="p.is_optional">
              <span class="meta-item">v{{ p.latest_version }}</span>
              <span class="meta-sep">·</span>
              <span class="meta-item">内置</span>
            </template>
            <template v-else>
              <span class="meta-item">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
                  <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/>
                  <circle cx="12" cy="7" r="4"/>
                </svg>
                {{ p.developer_name }}
              </span>
              <span class="meta-sep">·</span>
              <span class="meta-item">v{{ p.latest_version }}</span>
              <span class="meta-sep">·</span>
              <span class="meta-item">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
                  <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
                  <polyline points="7 10 12 15 17 10"/>
                  <line x1="12" y1="15" x2="12" y2="3"/>
                </svg>
                {{ formatDownloads(p.total_downloads) }}
              </span>
            </template>
          </div>
          <div v-if="p.avg_rating > 0" class="market-rating-row">
            <div class="rating-stars">
              <span v-for="n in 5" :key="n" class="star" :class="{ filled: n <= Math.round(p.avg_rating) }">★</span>
            </div>
            <span class="rating-score">{{ p.avg_rating.toFixed(1) }}</span>
            <span class="rating-count">({{ p.review_count }})</span>
          </div>
          <div class="market-actions">
            <button v-if="!isInstalled(p)" class="install-btn"
              :disabled="p.installing" @click.stop="installPlugin(p)">
              {{ p.installing ? '安装中…' : '安装' }}
            </button>
            <button v-else class="uninstall-btn" :disabled="p.installing"
              @click.stop="uninstallPlugin(p)">
              {{ p.installing ? '卸载中…' : '卸载' }}
            </button>
          </div>
        </div>
      </div>

      <!-- 分页 -->
      <div v-if="marketList.length > 0" class="pagination">
        <button class="btn-ghost btn-sm" :disabled="page <= 1" @click="page--; loadMarket()">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
            <polyline points="15 18 9 12 15 6"/>
          </svg>
          上一页
        </button>
        <span class="page-info">{{ page }} / {{ Math.ceil(marketTotal / pageSize) || 1 }}</span>
        <button class="btn-ghost btn-sm" :disabled="page * pageSize >= marketTotal" @click="page++; loadMarket()">
          下一页
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
            <polyline points="9 18 15 12 9 6"/>
          </svg>
        </button>
      </div>
    </div>

    <!-- ======================= 插件详情弹窗 ======================= -->
    <transition name="pop">
      <div v-if="detailPlugin" class="detail-mask" @click.self="detailPlugin = null">
        <div class="detail-panel glass">
          <button class="detail-close" @click="detailPlugin = null">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
              <line x1="18" y1="6" x2="6" y2="18"/>
              <line x1="6" y1="6" x2="18" y2="18"/>
            </svg>
          </button>
          
          <div class="detail-header">
            <div class="detail-icon">
              <span>{{ (detailPlugin.name || detailPlugin.slug).charAt(0).toUpperCase() }}</span>
            </div>
            <div class="detail-title-area">
              <h3 class="detail-name">{{ detailPlugin.name }}</h3>
              <p class="detail-author">by {{ detailPlugin.developer_name }}</p>
            </div>
          </div>

          <div v-if="detailPlugin.avg_rating > 0" class="detail-stats">
            <div class="stat-item">
              <div class="rating-stars-lg">
                <span v-for="n in 5" :key="n" class="star" :class="{ filled: n <= Math.round(detailPlugin.avg_rating) }">★</span>
              </div>
              <span class="stat-text">{{ detailPlugin.avg_rating.toFixed(1) }} ({{ detailPlugin.review_count }} 评价)</span>
            </div>
            <div class="stat-item">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
                <polyline points="7 10 12 15 17 10"/>
                <line x1="12" y1="15" x2="12" y2="3"/>
              </svg>
              <span class="stat-text">{{ detailPlugin.total_downloads }} 次下载</span>
            </div>
          </div>

          <div class="detail-section">
            <p class="detail-desc">{{ detailPlugin.description }}</p>
          </div>

          <div v-if="detailVersions.length" class="detail-section">
            <h4 class="detail-sub">版本历史</h4>
            <div class="version-list">
              <div v-for="v in detailVersions" :key="v.version" class="version-row">
                <span class="ver-num">v{{ v.version }}</span>
                <span class="ver-date">{{ formatTime(v.created_at) }}</span>
                <span class="ver-changelog">{{ v.changelog || '—' }}</span>
              </div>
            </div>
          </div>

          <div class="detail-section">
            <h4 class="detail-sub">评价</h4>
            <div v-if="detailReviews.length === 0" class="detail-empty">暂无评价</div>
            <div v-else class="review-list">
              <div v-for="r in detailReviews" :key="r.id" class="review-row">
                <div class="review-head">
                  <span class="review-user">{{ r.username }}</span>
                  <span class="review-stars">{{ '★'.repeat(r.rating) }}{{ '☆'.repeat(5 - r.rating) }}</span>
                  <span class="review-date">{{ formatTime(r.created_at) }}</span>
                </div>
                <p v-if="r.comment" class="review-comment">{{ r.comment }}</p>
              </div>
            </div>
          </div>

          <div v-if="isLoggedInUser" class="detail-rate-form">
            <h4 class="detail-sub">发表评价</h4>
            <div class="rate-stars">
              <button v-for="n in 5" :key="n" class="star-btn" :class="{ active: myRating >= n }" @click="myRating = n">★</button>
            </div>
            <textarea class="input rate-comment" v-model="myComment" placeholder="说点什么…" rows="2"></textarea>
            <button class="btn-mint btn-sm" :disabled="ratingSubmitting" @click="submitReview">提交评价</button>
          </div>

          <div class="detail-footer">
            <button v-if="!isInstalled(detailPlugin)" class="btn-mint detail-install"
              :disabled="detailPlugin.installing" @click="installPlugin(detailPlugin)">
              {{ detailPlugin.installing ? '安装中…' : '安装' }}
            </button>
            <button v-else-if="detailPlugin.is_optional" class="btn-ghost detail-install"
              :disabled="detailPlugin.installing" @click="uninstallPlugin(detailPlugin)">
              {{ detailPlugin.installing ? '卸载中…' : '卸载' }}
            </button>
            <span v-else class="detail-installed">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
                <polyline points="20 6 9 17 4 12"/>
              </svg>
              已安装
            </span>
          </div>
        </div>
      </div>
    </transition>

    <!-- ======================= 卸载确认弹窗 ======================= -->
    <transition name="pop">
      <div v-if="confirmUninstall" class="detail-mask" @click.self="confirmUninstall = null">
        <div class="confirm-panel glass">
          <div class="confirm-icon">
            <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="var(--danger)" stroke-width="1.5" stroke-linecap="round">
              <circle cx="12" cy="12" r="10"/>
              <line x1="12" y1="8" x2="12" y2="13"/>
              <line x1="12" y1="16" x2="12.01" y2="16"/>
            </svg>
          </div>
          <h3 class="confirm-title">确认卸载「{{ confirmUninstall?.name }}」？</h3>
          <p class="confirm-desc">卸载后将清空该插件的所有配置数据，此操作不可撤销。</p>
          <div class="confirm-actions">
            <button class="btn btn-cancel" @click="confirmUninstall = null">取消</button>
            <button class="btn btn-danger" @click="doUninstall(confirmUninstall)">确认卸载</button>
          </div>
        </div>
      </div>
    </transition>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { api, isLoggedIn } from '../api'

const emit = defineEmits(['toast', 'plugin-changed'])

const isLoggedInUser = computed(() => isLoggedIn())

// ===== 市场 =====
const marketList = ref([])
const marketTotal = ref(0)
const marketLoading = ref(false)
const searchQuery = ref('')
const sortBy = ref('downloads')
const category = ref('')
const categories = ref([])
const page = ref(1)
const pageSize = 20
const localInstalled = ref([])
const optionalInstalled = ref(new Set())
const confirmUninstall = ref(null)

/** 判断插件是否已安装（市场插件或内置可选插件） */
function isInstalled(p) {
  if (p.is_optional) return optionalInstalled.value.has(p.slug)
  return localInstalled.value.some(x => x.name === p.slug || x.slug === p.slug)
}

/** 安装插件：市场插件走下载流程，可选插件走 API */
async function installPlugin(p) {
  p.installing = true
  if (p.is_optional) {
    const res = await api.installOptionalPlugin(p.slug)
    if (res.status === 200 && res.data?.code === 0) {
      optionalInstalled.value = new Set([...optionalInstalled.value, p.slug])
      p.installed = true
      emit('plugin-changed')
      emit('toast', `「${p.name}」已安装`)
    } else {
      emit('toast', (res.data && res.data.message) || '安装失败')
    }
  } else {
    emit('toast', `正在下载「${p.name}」…`)
    try {
      const dlRes = await fetch(`/api/v1/marketplace/plugins/${encodeURIComponent(p.slug)}/download`)
      if (!dlRes.ok) throw new Error('下载失败')
      const blob = await dlRes.blob()
      const file = new File([blob], `${p.slug}-${p.latest_version}.zip`, { type: 'application/zip' })
      const res = await api.installPluginZip(file)
      if (res.status === 200 && res.data?.code === 0) {
        emit('plugin-changed')
        emit('toast', `「${p.name}」安装成功`)
        await loadLocalInstalled()
      } else {
        emit('toast', res.data?.message || '安装失败')
      }
    } catch (e) {
      emit('toast', '下载失败：' + e.message)
    }
  }
  p.installing = false
}

/** 卸载可选插件 — 弹出确认对话框 */
function uninstallPlugin(p) {
  if (!p.is_optional) return
  confirmUninstall.value = p
}

/** 执行卸载（确认后） */
async function doUninstall(p) {
  confirmUninstall.value = null
  if (!p.is_optional) return
  p.installing = true
  const res = await api.uninstallOptionalPlugin(p.slug)
  if (res.status === 200 && res.data?.code === 0) {
    const s = new Set(optionalInstalled.value)
    s.delete(p.slug)
    optionalInstalled.value = s
    p.installed = false
    emit('plugin-changed')
    emit('toast', (res.data && res.data.message) || `「${p.name}」已卸载`)
  } else {
    emit('toast', (res.data && res.data.message) || '卸载失败')
  }
  p.installing = false
}

async function loadOptionalPlugins() {
  const res = await api.optionalPlugins()
  if (res.status === 200 && res.data?.code === 0) {
    const list = (res.data.data || []).map(p => ({
      slug: p.name,
      name: p.title || p.name,
      description: p.description || '',
      latest_version: p.version || '1.0.0',
      developer_name: '',
      total_downloads: 0,
      avg_rating: 0,
      review_count: 0,
      is_optional: true,
      installed: p.installed || false,
      installing: false,
    }))
    // 标记已安装的可选插件
    const installed = new Set()
    for (const p of list) {
      if (p.installed) installed.add(p.slug)
    }
    optionalInstalled.value = installed
    // 合并到市场列表
    marketList.value = [...marketList.value, ...list]
  }
}

async function loadCategories() {
  const res = await api.marketplaceCategories()
  if (res.status === 200 && res.data?.code === 0) {
    categories.value = res.data.data || []
  }
}

async function loadMarket() {
  marketLoading.value = true
  const params = { page: page.value, size: pageSize, sort: sortBy.value }
  if (searchQuery.value) params.search = searchQuery.value
  if (category.value) params.category = category.value
  const res = await api.marketplacePlugins(params)
  if (res.status === 200 && res.data?.code === 0) {
    const d = res.data.data
    marketList.value = (d.items || []).map(p => ({ ...p, installing: false }))
    marketTotal.value = d.total || 0
  } else {
    marketList.value = []
    marketTotal.value = 0
  }
  marketLoading.value = false
  // 加载内置可选插件，合并到市场列表
  await loadOptionalPlugins()
}

function searchMarket() {
  page.value = 1
  loadMarket()
}

async function loadLocalInstalled() {
  const res = await api.installedPlugins()
  if (res.status === 200 && res.data?.code === 0) {
    localInstalled.value = res.data.data || []
  }
}

// ===== 插件详情 =====
const detailPlugin = ref(null)
const detailVersions = ref([])
const detailReviews = ref([])
const myRating = ref(5)
const myComment = ref('')
const ratingSubmitting = ref(false)

async function openDetail(p) {
  detailPlugin.value = { ...p, installing: false }
  detailVersions.value = []
  detailReviews.value = []
  // 可选插件没有云端版本/评价
  if (p.is_optional) return
  const [vRes, rRes] = await Promise.all([
    api.marketplaceVersions(p.slug),
    api.marketplaceReviews(p.slug),
  ])
  if (vRes.data?.code === 0) detailVersions.value = vRes.data.data || []
  if (rRes.data?.code === 0) detailReviews.value = rRes.data.data || []
}

async function submitReview() {
  if (!detailPlugin.value) return
  if (myRating.value < 1) { emit('toast', '请选择评分'); return }
  ratingSubmitting.value = true
  const res = await api.ratePlugin(detailPlugin.value.slug, myRating.value, myComment.value)
  ratingSubmitting.value = false
  if (res.status === 200 && res.data?.code === 0) {
    emit('toast', '评价已提交')
    myComment.value = ''
    myRating.value = 5
    const rRes = await api.marketplaceReviews(detailPlugin.value.slug)
    if (rRes.data?.code === 0) detailReviews.value = rRes.data.data || []
  } else {
    emit('toast', res.data?.message || '提交失败')
  }
}

// ===== Utils =====
function formatDownloads(n) {
  if (!n) return '0'
  if (n < 1000) return String(n)
  if (n < 10000) return (n / 1000).toFixed(1) + 'k'
  return (n / 10000).toFixed(1) + 'w'
}

function formatTime(ts) {
  if (!ts) return '—'
  const d = new Date(ts * 1000)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

// ===== Init =====
onMounted(() => {
  loadCategories()
  loadMarket()
  loadLocalInstalled()
})
</script>

<style scoped>
.store-view { padding: 28px 0 56px; }

.glass {
  background: var(--grad-card);
  backdrop-filter: var(--glass-blur);
  -webkit-backdrop-filter: var(--glass-blur);
  border: 1px solid var(--glass-border);
  box-shadow: var(--shadow), var(--glass-hi);
  border-radius: var(--radius-lg);
}

/* ===== 市场主区域 ===== */
.market-main { display: flex; flex-direction: column; gap: 16px; }

/* ===== 搜索工具栏 ===== */
.market-toolbar {
  display: flex; gap: 12px; align-items: center; padding: 14px 18px;
}
.search-box {
  flex: 1; display: flex; align-items: center; gap: 10px;
  padding: 0 14px; height: 42px; border-radius: var(--radius-sm);
  background: rgba(255, 255, 255, 0.55);
  border: 1px solid var(--glass-border);
  transition: all 0.25s var(--ease);
}
.search-box:focus-within { border-color: var(--mint-border); background: rgba(255, 255, 255, 0.85); box-shadow: 0 0 0 3px var(--mint-soft); }
.search-box svg { color: var(--text-dim); flex-shrink: 0; }
.search-input { 
  flex: 1; border: none; background: transparent; outline: none;
  font-size: 14px; color: var(--text-main);
}
.search-input::placeholder { color: var(--text-dim); }
.filter-group { display: flex; gap: 8px; }
.sort-select, .cat-select {
  padding: 8px 12px; border-radius: var(--radius-sm); font-size: 13px;
  border: 1px solid var(--glass-border);
  background: var(--glass-bg-strong);
  backdrop-filter: var(--glass-blur-sm);
  color: var(--text-main);
  cursor: pointer; transition: all 0.2s var(--ease);
}
.sort-select:hover, .cat-select:hover { border-color: var(--mint-border); }

/* ===== 加载和空状态 ===== */
.loading-state, .empty-state {
  display: flex; flex-direction: column; align-items: center; 
  justify-content: center; padding: 60px 20px; gap: 12px;
}
.spinner { 
  width: 32px; height: 32px; border: 3px solid rgba(16,185,129,0.15); 
  border-top-color: var(--mint); border-radius: 50%; 
  animation: spin 0.8s linear infinite; 
}
@keyframes spin { to { transform: rotate(360deg); } }
.empty-icon { 
  width: 80px; height: 80px; border-radius: 50%; 
  background: var(--mint-soft); border: 1px solid var(--mint-border);
  display: flex; align-items: center; justify-content: center;
  color: var(--text-dim); margin-bottom: 8px;
}

/* ===== 市场插件网格 ===== */
.market-grid { 
  display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); 
  gap: 14px; 
}
.market-card {
  display: flex; flex-direction: column; padding: 20px;
  cursor: pointer; transition: all 0.3s var(--ease);
}
.market-card:hover { 
  box-shadow: var(--shadow-hover), var(--glass-hi);
  transform: translateY(-4px);
  border-color: var(--mint-border);
}
.market-card.installed { border-color: var(--mint-border); }
.market-card-header { display: flex; gap: 12px; margin-bottom: 12px; }
.market-icon { 
  width: 48px; height: 48px; border-radius: var(--radius-md); 
  display: flex; align-items: center; justify-content: center;
  font-size: 20px; font-weight: 700; color: var(--mint);
  background: var(--mint-soft);
  border: 1px solid var(--mint-border);
  flex-shrink: 0;
  transition: all 0.3s var(--ease);
}
.market-card:hover .market-icon { 
  background: var(--grad-mint); color: #fff; border-color: transparent; 
  transform: scale(1.06);
}
.market-card.installed .market-icon { background: var(--grad-mint); color: #fff; border-color: transparent; }
.market-info { flex: 1; min-width: 0; }
.market-title-row { display: flex; align-items: center; gap: 8px; }
.market-name { font-size: 16px; font-weight: 700; margin: 0; }
.installed-badge { 
  font-size: 10px; padding: 2px 8px; border-radius: 999px;
  background: var(--mint-soft); color: var(--mint); font-weight: 600;
}
.market-desc { 
  font-size: 13px; color: var(--text-sub); margin: 4px 0 0 0;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; 
  overflow: hidden; line-height: 1.5;
}
.market-meta-row { 
  display: flex; align-items: center; gap: 6px; 
  font-size: 12px; color: var(--text-dim); margin-bottom: 8px; 
}
.meta-item { display: flex; align-items: center; gap: 4px; }
.meta-item svg { width: 12px; height: 12px; }
.meta-sep { color: var(--glass-border-soft); }
.market-rating-row { display: flex; align-items: center; gap: 6px; margin-bottom: 12px; }
.rating-stars { display: flex; gap: 1px; }
.rating-stars .star { font-size: 12px; color: var(--glass-border); }
.rating-stars .star.filled { color: var(--amber); }
.rating-score { font-size: 13px; font-weight: 600; color: var(--amber); }
.rating-count { font-size: 12px; color: var(--text-dim); }
.market-actions { margin-top: auto; }
.install-btn {
  width: 100%; padding: 10px; border-radius: var(--radius-sm);
  background: var(--grad-mint); color: #fff; font-weight: 600; font-size: 13px;
  border: none; cursor: pointer; transition: all 0.25s var(--ease);
  box-shadow: 0 6px 16px rgba(16,185,129,0.2);
}
.install-btn:hover { filter: brightness(1.08); box-shadow: var(--shadow-mint); transform: translateY(-1px); }
.install-btn:disabled { opacity: 0.6; cursor: not-allowed; }
.installed-text { 
  display: block; width: 100%; text-align: center;
  padding: 10px; border-radius: var(--radius-sm);
  background: var(--mint-soft); color: var(--mint); font-weight: 600; font-size: 13px;
  border: 1px solid var(--mint-border);
}

/* ===== 分页 ===== */
.pagination { 
  display: flex; align-items: center; justify-content: center; gap: 16px; 
  padding: 16px 0; 
}
.page-info { font-size: 13px; color: var(--text-sub); }

/* ===== 弹窗样式 ===== */
.detail-mask {
  position: fixed; inset: 0; z-index: 220;
  display: flex; align-items: center; justify-content: center;
  background: rgba(15, 23, 42, 0.45); backdrop-filter: blur(12px) saturate(140%);
  -webkit-backdrop-filter: blur(12px) saturate(140%);
}
.detail-panel { 
  width: min(480px, 90vw); max-height: 90vh; overflow-y: auto;
  padding: 32px; border-radius: var(--radius-xl); box-shadow: var(--shadow-hover), var(--glass-hi); 
  position: relative; 
}

/* ===== 详情弹窗 ===== */
.detail-panel { width: min(560px, 94vw); }
.detail-close {
  position: absolute; top: 16px; right: 16px;
  width: 32px; height: 32px; border-radius: 50%; border: none;
  background: var(--glass-bg-strong); color: var(--text-sub); cursor: pointer;
  display: flex; align-items: center; justify-content: center;
  backdrop-filter: var(--glass-blur-sm);
  transition: all 0.2s var(--ease);
}
.detail-close:hover { background: var(--danger-soft); color: var(--danger); }
.detail-header { display: flex; gap: 16px; margin-bottom: 20px; }
.detail-icon { 
  width: 64px; height: 64px; border-radius: var(--radius-md);
  display: flex; align-items: center; justify-content: center;
  font-size: 28px; font-weight: 700; color: var(--mint);
  background: var(--mint-soft); border: 1px solid var(--mint-border); flex-shrink: 0;
}
.detail-title-area { flex: 1; }
.detail-name { font-size: 22px; font-weight: 700; margin: 0; }
.detail-author { font-size: 13px; color: var(--text-sub); margin: 4px 0 0 0; }
.detail-stats { 
  display: flex; gap: 20px; padding: 14px 16px; margin-bottom: 20px;
  border-radius: var(--radius-md);
  background: var(--glass-bg-strong);
  border: 1px solid var(--glass-border);
}
.stat-item { display: flex; align-items: center; gap: 8px; }
.stat-item svg { color: var(--mint); }
.stat-text { font-size: 13px; color: var(--text-sub); }
.rating-stars-lg { display: flex; gap: 2px; }
.rating-stars-lg .star { font-size: 16px; color: var(--glass-border); }
.rating-stars-lg .star.filled { color: var(--amber); }
.detail-section { margin-bottom: 20px; }
.detail-desc { font-size: 14px; line-height: 1.7; color: var(--text-main); margin: 0; }
.detail-sub { font-size: 14px; font-weight: 700; margin: 0 0 12px 0; }
.version-list { display: flex; flex-direction: column; gap: 8px; }
.version-row { 
  display: flex; align-items: center; gap: 12px; padding: 10px 12px;
  border-radius: var(--radius-sm);
  background: var(--glass-bg-strong);
  border: 1px solid var(--glass-border);
  font-size: 13px;
}
.ver-num { font-weight: 600; color: var(--mint); }
.ver-date { color: var(--text-dim); }
.ver-changelog { flex: 1; color: var(--text-sub); }
.detail-empty { padding: 24px; text-align: center; color: var(--text-dim); font-size: 13px; }
.review-list { display: flex; flex-direction: column; gap: 12px; }
.review-row { padding: 12px 14px; border-radius: var(--radius-sm); background: var(--glass-bg-strong); border: 1px solid var(--glass-border); }
.review-head { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
.review-user { font-size: 13px; font-weight: 600; }
.review-stars { color: var(--amber); font-size: 12px; }
.review-date { font-size: 11px; color: var(--text-dim); }
.review-comment { font-size: 13px; color: var(--text-sub); margin: 0; line-height: 1.5; }
.detail-rate-form { margin-bottom: 20px; }
.rate-stars { display: flex; gap: 4px; margin-bottom: 12px; }
.star-btn { 
  width: 32px; height: 32px; border: none; border-radius: var(--radius-sm);
  background: var(--glass-bg-strong); color: var(--text-dim); font-size: 18px;
  cursor: pointer; transition: all 0.2s var(--ease);
}
.star-btn:hover { background: rgba(245, 158, 11, 0.14); color: var(--amber); }
.star-btn.active { background: rgba(245, 158, 11, 0.16); color: var(--amber); }
.rate-comment { margin-bottom: 12px; min-height: 60px; resize: vertical; }
.detail-footer { display: flex; justify-content: center; padding-top: 16px; border-top: 1px solid var(--glass-border-soft); }
.detail-install { padding: 12px 40px; font-size: 14px; }
.detail-installed { 
  display: flex; align-items: center; gap: 6px;
  padding: 12px 24px; border-radius: var(--radius-md);
  background: var(--mint-soft); color: var(--mint); font-weight: 600; font-size: 14px;
  border: 1px solid var(--mint-border);
}

.pop-enter-active, .pop-leave-active { transition: all 0.3s var(--ease); }
.pop-enter-from, .pop-leave-to { opacity: 0; transform: scale(0.95) translateY(10px); }

.uninstall-btn {
  padding: 6px 16px; border-radius: var(--radius-sm); border: 1px solid var(--danger-border);
  background: var(--danger-soft); color: var(--danger); font-size: 13px; font-weight: 600;
  cursor: pointer; transition: all 0.2s var(--ease);
}
.uninstall-btn:hover { background: var(--danger); color: #fff; }
.uninstall-btn:disabled { opacity: 0.5; cursor: not-allowed; }

/* ===== 卸载确认弹窗 ===== */
.confirm-panel {
  position: fixed; top: 50%; left: 50%; transform: translate(-50%, -50%);
  width: 360px; max-width: 88vw; padding: 32px 28px 24px; border-radius: 16px;
  z-index: 2000; text-align: center;
  background: var(--grad-panel);
  backdrop-filter: var(--glass-blur);
  -webkit-backdrop-filter: var(--glass-blur);
  border: 1px solid var(--glass-border);
  box-shadow: var(--shadow-hover), var(--glass-hi);
}
.confirm-icon { margin-bottom: 16px; }
.confirm-title { font-size: 16px; font-weight: 600; margin: 0 0 8px; }
.confirm-desc { font-size: 13px; color: var(--text-secondary); margin: 0 0 24px; line-height: 1.5; }
.confirm-actions { display: flex; gap: 12px; justify-content: center; }
.confirm-actions .btn {
  min-width: 100px; padding: 8px 20px; border-radius: 8px; border: none;
  font-size: 14px; cursor: pointer; transition: all .2s;
}
.btn-cancel { background: rgba(255,255,255,0.6); color: var(--text-sub); border: 1px solid var(--glass-border); }
.btn-cancel:hover { border-color: var(--mint-border); background: var(--mint-softer); color: var(--mint-deep); }
.btn-danger { background: var(--danger); color: #fff; }
.btn-danger:hover { opacity: .85; }

/* ===== 响应式 ===== */
@media (max-width: 640px) {
  .market-toolbar { flex-direction: column; }
  .filter-group { width: 100%; }
  .sort-select, .cat-select { flex: 1; }
  .market-grid { grid-template-columns: 1fr; }
}
</style>