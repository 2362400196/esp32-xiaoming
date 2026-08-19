// 全局认证状态
const TOKEN_KEY = 'esp_ai_token'
const USER_KEY = 'esp_ai_user'

// 服务器地址配置
let serverBaseUrl = 'http://192.168.31.176:8088'

// 认证过期回调（由 UI 层注册）
let _authExpiredCallback = null

// base64url 解码（兼容 H5 和 App 环境）
function base64UrlDecode(str) {
    try {
        let payload = str.replace(/-/g, '+').replace(/_/g, '/')
        while (payload.length % 4) payload += '='
        if (typeof atob !== 'undefined') {
            return atob(payload)
        }
        // 手动解码兜底
        const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/'
        let result = ''
        let i = 0
        payload = payload.replace(/[^A-Za-z0-9+/]/g, '')
        while (i < payload.length) {
            const a = chars.indexOf(payload[i++])
            const b = chars.indexOf(payload[i++])
            const c = chars.indexOf(payload[i++])
            const d = chars.indexOf(payload[i++])
            const n = (a << 18) | (b << 12) | (c << 6) | d
            result += String.fromCharCode((n >> 16) & 0xFF)
            if (c !== 64) result += String.fromCharCode((n >> 8) & 0xFF)
            if (d !== 64) result += String.fromCharCode(n & 0xFF)
        }
        return result
    } catch (e) {
        return null
    }
}

// 解析 JWT payload
function decodeJWTPayload(token) {
    try {
        const parts = token.split('.')
        if (parts.length !== 3) return null
        const decoded = base64UrlDecode(parts[1])
        if (!decoded) return null
        return JSON.parse(decoded)
    } catch (e) {
        return null
    }
}

// 检查 token 是否已过期
export function isTokenExpired() {
    const token = getToken()
    if (!token) return true
    const payload = decodeJWTPayload(token)
    if (!payload) return true
    if (!payload.exp) return false
    return Date.now() >= payload.exp * 1000
}

// 注册认证过期回调（UI 层调用）
export function setAuthExpiredCallback(cb) {
    _authExpiredCallback = cb
}

// 触发认证过期：清除登录状态并通知 UI
function triggerAuthExpired() {
    setToken('')
    setUser(null)
    if (typeof _authExpiredCallback === 'function') {
        _authExpiredCallback()
    }
}

export function setServerUrl(url) {
    serverBaseUrl = url
    uni.setStorageSync('esp_ai_server_url', url)
}

export function getServerUrl() {
    const saved = uni.getStorageSync('esp_ai_server_url')
    if (saved) serverBaseUrl = saved
    return serverBaseUrl
}

export function getToken() {
    return uni.getStorageSync(TOKEN_KEY) || ''
}

export function setToken(token) {
    if (token) uni.setStorageSync(TOKEN_KEY, token)
    else uni.removeStorageSync(TOKEN_KEY)
}

export function getUser() {
    try {
        const raw = uni.getStorageSync(USER_KEY)
        return raw ? JSON.parse(raw) : null
    } catch(e) { return null }
}

export function setUser(user) {
    if (user) uni.setStorageSync(USER_KEY, JSON.stringify(user))
    else uni.removeStorageSync(USER_KEY)
}

export function isLoggedIn() {
    const token = getToken()
    if (!token) return false
    // 检查 JWT 是否已过期
    const payload = decodeJWTPayload(token)
    if (!payload) return false
    if (payload.exp && Date.now() >= payload.exp * 1000) return false
    return true
}

export function logout() {
    setToken('')
    setUser(null)
}

// 带 JWT 的 API 调用
export function callApi(path, method = 'GET', data = null) {
    const baseUrl = getServerUrl()
    const headers = {
        'Content-Type': 'application/json'
    }
    const token = getToken()
    if (token) headers['Authorization'] = 'Bearer ' + token
    
    return new Promise((resolve) => {
        uni.request({
            url: baseUrl + path,
            method: method,
            data: data,
            header: headers,
            timeout: 10000,
            success: (res) => {
                // 检测 401：token 过期或无效，自动触发认证过期流程
                // 排除认证接口本身（登录/注册），它们的 401 表示凭据错误而非 token 过期
                if (res.statusCode === 401 && !path.startsWith('/api/v1/auth/')) {
                    triggerAuthExpired()
                }
                resolve(res)
            },
            fail: (err) => resolve({ statusCode: 0, errMsg: err.errMsg, data: null })
        })
    })
}

// 注册
export async function register(email, password, nickname) {
    const res = await callApi('/api/v1/auth/register', 'POST', { email, password, nickname })
    if (res.statusCode === 200 || (res.data && res.data.code === 0)) {
        return { success: true }
    }
    return { success: false, message: res.data?.message || res.data?.detail?.[0]?.msg || res.errMsg || '注册失败' }
}

// 登录
export async function login(email, password) {
    const res = await callApi('/api/v1/auth/login', 'POST', { email, password })
    if (res.data && res.data.code === 0 && res.data.data) {
        setToken(res.data.data.access_token)
        setUser({
            user_id: res.data.data.user_id,
            email: res.data.data.email,
            nickname: res.data.data.nickname,
        })
        return { success: true }
    }
    return { success: false, message: res.data?.message || res.data?.detail?.[0]?.msg || '登录失败' }
}

// 获取设备列表
export async function getDevices() {
    const res = await callApi('/api/v1/devices', 'GET')
    if (res.data && res.data.code === 0) {
        return res.data.data.devices || []
    }
    return []
}
