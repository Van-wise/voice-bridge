<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed, watch, nextTick } from 'vue'
import QRCode from 'qrcode'
import SimpleRecorder from './components/SimpleRecorder.vue'
import ErrorBoundary from './components/ErrorBoundary.vue'
import { apiGet, apiPost, getApiBase, getClientId } from './utils/api'
import { setToastFunction } from './utils/errorHandler'
import { logger, setDeviceId } from './utils/logger'

// ==================== 错误处理 ====================
function handleComponentError(error: Error, errorInfo: any) {
  logger.error('App', '组件错误', { message: error.message, errorInfo })
}

// 注册全局 Toast 函数（供 errorHandler 使用）
setToastFunction((msg: string, type: string) => {
  showToast(msg, type as 'ok' | 'err' | 'warn' | 'loading')
})

// ==================== 状态 ====================
const text = ref('')
const isOnline = ref(false)
const syncing = ref(false)
const lastEv = ref(-1)
const settingsVersion = ref(0)
const settings = ref({
  mode: 'auto',
  auto_clear: true,
  auto_copy: true,
  persist_history: true,
  port: 7266
})
const history = ref<any[]>([])
const historyTotal = ref(0)
const historyOffset = ref(0)
const historySearch = ref('')
const historyFilterCategory = ref<string>('')  // 新增：内容分类过滤
const showHistory = ref(false)
const showDrawer = ref(false)
const showDropdown = ref(false)
const localIp = ref('')
const currentPort = ref(7266)
const stats = ref({
  total_syncs: 0,
  total_chars: 0,
  active_clients: 0,
  total_history: 0
})
const toast = ref({ show: false, message: '', type: 'ok' as 'ok' | 'err' | 'warn' | 'loading', fading: false })
const toastTimer = ref<number | null>(null)
const clientId = ref(localStorage.getItem('vb_device_id') || ('c' + Math.random().toString(36).substr(2, 9)))
// 持久化设备ID（统一标识）
if (!localStorage.getItem('vb_device_id')) {
  localStorage.setItem('vb_device_id', clientId.value)
}
const isPC = computed(() => location.hostname === '127.0.0.1' || location.hostname === 'localhost')
const charCount = computed(() => text.value.length)
const qrCanvas = ref<HTMLCanvasElement | null>(null)

// 初始化设备 ID 用于日志上报
setDeviceId(clientId.value)

// 睡眠模式
const isSleeping = ref(false)
const lastActivity = ref(Date.now())
const sleepInterval = 5 * 60 * 1000

// 设备列表
const devices = ref<any[]>([])

// 齿轮双击
const gearLastClick = ref(0)

// 轮询（兜底机制：800ms 间隔拉取事件）
let pollTimer: number | null = null
let pollFails = 0
let sleepCheckTimer: number | null = null

// WebSocket 剪贴板连接
let wsClipboard: WebSocket | null = null
let wsReconnectTimer: number | null = null
let wsHeartbeatTimer: number | null = null

// 历史滚动加载
const scrollLoading = ref(false)
const historyScroll = ref<HTMLElement | null>(null)

// 二维码URL
const qrUrl = ref('')

// 端口编辑
const editingPort = ref(false)
const portInput = ref('')

// HTTPS 状态提示
const isHttps = computed(() => window.location.protocol === 'https:')
const isLocalhost = computed(() => window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1')
const showHttpsWarning = computed(() => !isHttps.value && !isLocalhost.value)

// HTTPS 模式下用户用 HTTP 访问的提示
const showHttpInHttpsMode = ref(false)

// 内容分类配置
const contentCategories = [
  { value: '', label: '全部' },
  { value: 'url', label: '🔗 链接' },
  { value: 'code', label: '💻 代码' },
  { value: 'file_path', label: '📁 文件' },
  { value: 'email', label: '📧 邮箱' },
  { value: 'phone', label: '📞 电话' },
]

// ==================== Toast ====================
function showToast(message: string, type: 'ok' | 'err' | 'warn' | 'loading' = 'ok', duration = 2000) {
  if (toastTimer.value) clearTimeout(toastTimer.value)
  toast.value = { show: true, message, type, fading: false }
  if (duration > 0) {
    toastTimer.value = window.setTimeout(() => {
      toast.value.fading = true
      toastTimer.value = window.setTimeout(() => {
        toast.value.show = false
        toastTimer.value = null
      }, 600)
    }, duration)
  }
}

// ==================== 睡眠模式（WebSocket 版本，已简化） ====================
// WebSocket 自动处理连接和重连，不再需要轮询
function onActivity() {
  lastActivity.value = Date.now()
  // WebSocket 会自动维护连接，不需要额外处理
}

function checkSleep() {
  const idle = Date.now() - lastActivity.value
  // 睡眠模式下只是关闭指示灯，不影响 WebSocket
  if (!isSleeping.value && idle >= sleepInterval) {
    isSleeping.value = true
    setDot(false)
  } else if (isSleeping.value && idle < sleepInterval) {
    isSleeping.value = false
    setDot(true)
  }
}

// 不再需要 restartPoll

// ==================== 轮询（已废弃，改用 WebSocket） ====================
// 保留 doPoll 用于初始化，不使用定时轮询
async function doPoll() {
  try {
    // 使用统一的 API 工具，静默处理轮询错误
    const result = await apiGet<any>(`/api/poll?last_ev=${lastEv.value}`, { showError: false })
    
    if (!result.success || !result.data) {
      pollFails++
      if (pollFails >= 3 && isOnline.value) {
        isOnline.value = false
        showToast('连接断开', 'err')
        setDot(false)
        logger.warn('Poll', '连接断开，3次轮询失败')
      }
      return
    }
    
    const resp = result.data

    if (!isOnline.value) {
      isOnline.value = true
      showToast('已连接', 'ok', 1500)
      logger.info('Poll', '后端连接成功')
    }

    if (resp.local_ip) localIp.value = resp.local_ip
    if (resp.current_port) currentPort.value = resp.current_port
    if (resp.ev) lastEv.value = resp.ev

    if (resp.settings_ver && resp.settings_ver !== settingsVersion.value) {
      await loadSettings()
    }

    if (resp.devices) {
      devices.value = resp.devices
    }

    if (resp.events && resp.events.length > 0) {
      for (const ev of resp.events) {
        handleEvent(ev)
      }
    }

    pollFails = 0
  } catch (e) {
    pollFails++
    if (pollFails >= 3 && isOnline.value) {
      isOnline.value = false
      showToast('连接断开', 'err')
      setDot(false)
      logger.error('Poll', '轮询异常', { pollFails })
    }
  }
}

// ==================== WebSocket 剪贴板连接 ====================
function connectClipboardWS() {
  const deviceId = localStorage.getItem('vb_device_id') || 'unknown'
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const host = window.location.host
  
  wsClipboard = new WebSocket(`${protocol}//${host}/ws/${deviceId}`)
  
  wsClipboard.onopen = () => {
    isOnline.value = true
    setDot(true)
    pollFails = 0
    showToast('已连接', 'ok', 1500)
    logger.info('WS', '剪贴板 WebSocket 连接成功')
    
    // 启动心跳
    startWsHeartbeat()
  }
  
  wsClipboard.onmessage = (event) => {
    try {
      const msg = JSON.parse(event.data)
      handleWsMessage(msg)
    } catch (e) {
      logger.error('WS', '解析消息失败', { error: e })
    }
  }
  
  wsClipboard.onclose = () => {
    isOnline.value = false
    setDot(false)
    stopWsHeartbeat()
    logger.warn('WS', '剪贴板 WebSocket 断开，3秒后重连')
    
    // 3秒后重连
    if (!wsReconnectTimer) {
      wsReconnectTimer = window.setTimeout(() => {
        wsReconnectTimer = null
        connectClipboardWS()
      }, 3000)
    }
  }
  
  wsClipboard.onerror = (e) => {
    logger.error('WS', 'WebSocket 错误', { error: e })
  }
}

function handleWsMessage(msg: any) {
  if (!msg || !msg.type) return
  
  switch (msg.type) {
    case 'pong':
      // 心跳响应，不需要处理
      break
      
    case 'clipboard_update':
      // 收到剪贴板更新
      if (msg.data && msg.data.text !== undefined) {
        if (msg.source !== localStorage.getItem('vb_device_id')) {
          text.value = msg.data.text
          const fromTip = msg.data.device_type === 'mobile' ? '📱 收到同步' : '💻 收到同步'
          showToast(fromTip, 'ok', 1500)
          logger.info('WS', '收到剪贴板同步', { source: msg.source })
        }
      }
      break
      
    case 'settings_update':
      // 设置更新
      if (msg.data) {
        settings.value = { ...settings.value, ...msg.data }
        logger.info('WS', '收到设置更新')
      }
      break
      
    case 'device_list':
      // 设备列表更新
      if (msg.data && msg.data.devices) {
        devices.value = msg.data.devices
      }
      break
    
    case 'clipboard_clear':
      text.value = ''
      logger.info('WS', '收到清空事件')
      break
      
    default:
      logger.debug('WS', '未知消息类型', { type: msg.type })
  }
}

function startWsHeartbeat() {
  stopWsHeartbeat()
  wsHeartbeatTimer = window.setInterval(() => {
    if (wsClipboard && wsClipboard.readyState === WebSocket.OPEN) {
      wsClipboard.send(JSON.stringify({ type: 'ping' }))
    }
  }, 30000)
}

function stopWsHeartbeat() {
  if (wsHeartbeatTimer) {
    clearInterval(wsHeartbeatTimer)
    wsHeartbeatTimer = null
  }
}

function disconnectClipboardWS() {
  stopWsHeartbeat()
  if (wsReconnectTimer) {
    clearTimeout(wsReconnectTimer)
    wsReconnectTimer = null
  }
  if (wsClipboard) {
    wsClipboard.close()
    wsClipboard = null
  }
}

function setDot(on: boolean) {
  if (isSleeping.value) {
    isOnline.value = false
  } else {
    isOnline.value = on
  }
}

// ==================== 事件处理 ====================
function handleEvent(ev: any) {
  if (!ev || !ev.type) return

  // 处理同步文本事件
  if (ev.type === 'sync' && ev.data && ev.data.text !== undefined) {
    // 使用统一的 clientId（也是 vb_device_id）排除自己
    if (ev.data.client_id === clientId.value) return
    text.value = ev.data.text
    const fromTip = ev.data.device_type === 'mobile' ? '📱 收到同步' : '💻 收到同步'
    showToast(fromTip, 'ok', 1500)
  }

  // 处理 clear 事件（轮询兜底）
  if (ev.type === 'clear') {
    // 检查是否是本设备发起的清空（通过 source_device 排除）
    if (ev.data && ev.data.source_device === clientId.value) return
    text.value = ''
    showToast('🧹 内容已清空', 'ok', 1200)
  }

  if (ev.type === 'settings' && ev.data) {
    settings.value = { ...settings.value, ...ev.data }
  }
}

// ==================== 设置 ====================
async function loadSettings() {
  try {
    const result = await apiGet<any>('/api/settings', { showError: false })
    if (result.success && result.data) {
      const data = result.data
      if (data._ver !== undefined) {
        settingsVersion.value = data._ver
        delete data._ver
        settings.value = { ...settings.value, ...data }
      }
    }
  } catch (e) {
    logger.error('Settings', '加载设置失败', { error: e })
  }
}

async function saveSettings() {
  try {
    const result = await apiPost<any>('/api/settings', settings.value, { showError: false })
    if (result.success && result.data) {
      if (result.data._ver) settingsVersion.value = result.data._ver
      if (result.data.settings) settings.value = { ...settings.value, ...result.data.settings }
    }
  } catch (e) {
    logger.error('Settings', '保存设置失败', { error: e })
  }
}

// ==================== 齿轮单/双击 ====================
function onGearClick() {
  const now = Date.now()
  if (now - gearLastClick.value < 350) {
    openDrawer()
  } else {
    toggleDropdown()
  }
  gearLastClick.value = now
}

function toggleDropdown() {
  showDropdown.value = !showDropdown.value
}

function closeDropdown(e: MouseEvent) {
  if (!(e.target as HTMLElement).closest('.gear-wrap')) {
    showDropdown.value = false
  }
}

// ==================== 模式切换 ====================
function cycleMode() {
  settings.value.mode = settings.value.mode === 'manual' ? 'auto' : 'manual'
  if (settings.value.mode === 'auto') {
    settings.value.auto_copy = true
  }
  saveSettings()
  showToast(`模式: ${settings.value.mode === 'manual' ? '手动粘贴' : '自动粘贴'}`, 'ok', 1500)
  showDropdown.value = false
}

function toggleOpt(key: 'auto_copy' | 'auto_clear' | 'persist_history') {
  settings.value[key] = !settings.value[key]
  if (key === 'auto_clear') {
    if (settings.value.auto_clear) {
      settings.value.auto_copy = true
      showToast('🧹 已开启自动清空', 'ok', 2000)
    } else {
      showToast('🧹 已关闭自动清空', 'ok', 2000)
    }
  }
  if (key === 'persist_history') {
    showToast(settings.value.persist_history ? '💾 历史记录将永久保存' : '💾 历史记录仅保存本次会话', 'ok', 2000)
  }
  saveSettings()
  showDropdown.value = false
}

// ==================== 计算属性 ====================
const modeName = computed(() => settings.value.mode === 'manual' ? '手动粘贴' : '自动粘贴')
const isLocked = computed(() => settings.value.mode === 'auto' || settings.value.auto_clear)

const filteredHistory = computed(() => {
  let result = history.value
  
  // 按分类过滤
  if (historyFilterCategory.value) {
    result = result.filter(h => h.content_category === historyFilterCategory.value)
  }
  
  // 按关键词搜索
  if (historySearch.value) {
    const keyword = historySearch.value.toLowerCase()
    result = result.filter(h => h.text.toLowerCase().includes(keyword))
  }
  
  return result
})

// ==================== 同步 ====================
async function doSync() {
  if (!text.value.trim()) {
    showToast('请先输入文字', 'err', 1500)
    return
  }
  if (syncing.value) {
    showToast('正在同步中...', 'warn', 1000)
    return
  }

  syncing.value = true
  showToast('正在同步...', 'loading', 0)
  logger.info('Sync', '开始同步文本', { length: text.value.length })
  
  try {
    const result = await apiPost<any>('/api/sync', {
      text: text.value.trim(),
      mode: settings.value.mode,
      auto_clear: settings.value.auto_clear,
      manual: true
    }, { showError: false, timeout: 10000 })  // 10秒超时

    syncing.value = false
    
    if (result.success && result.data) {
      const data = result.data
      let msg = '✅ 已同步'
      if (data.action === 'pasted') msg = '✅ 已同步并粘贴'
      else if (data.action === 'copied') msg = '✅ 已同步 + 复制'
      showToast(msg, 'ok', 2000)
      logger.info('Sync', '同步成功', { action: data.action })

      flashBorder(true)

      if (data.auto_clear) {
        text.value = ''
        showToast('🧹 已清空', 'ok', 1200)
      }

      if (navigator.vibrate) navigator.vibrate(50)
      if (showHistory.value) loadHistory()
    } else {
      const errMsg = result.message || result.error || '同步失败'
      showToast('❌ ' + errMsg, 'err', 3000)
      flashBorder(false)
      logger.warn('Sync', '同步失败', { error: errMsg })
    }
  } catch (e) {
    syncing.value = false
    showToast('❌ 网络错误', 'err', 3000)
    flashBorder(false)
    logger.error('Sync', '同步异常', { error: e })
  }
}

function flashBorder(ok: boolean) {
  const el = document.getElementById('sync-textarea')
  if (el) {
    (el as HTMLElement).style.borderColor = ok ? '#22c55e' : '#ef4444'
    setTimeout(() => { (el as HTMLElement).style.borderColor = '' }, 600)
  }
}

// ==================== HTTPS 提示 ====================
function checkHttps() {
  // 检测是否在 HTTPS 模式下用 HTTP 访问
  const host = window.location.hostname
  const isLocal = host === 'localhost' || host === '127.0.0.1'
  
  // 如果是本地访问，检查服务器是否在 HTTPS 模式
  if (isLocal && !isHttps.value) {
    // 本地访问，检查是否是 HTTPS 模式启动但用户用 HTTP 访问
    fetch(window.location.origin + '/api/status', { method: 'GET' })
      .then(() => { showHttpInHttpsMode.value = false })
      .catch(() => { showHttpInHttpsMode.value = false })
  }
  
  // 非 localhost 且非 HTTPS，提示手机麦克风不可用
  if (!isHttps.value && !isLocalhost.value) {
    showToast('手机麦克风功能需要 HTTPS，请在电脑上运行「启动HTTPS模式.bat」', 'warn', 5000)
  }
}

// 切换到 HTTPS
function switchToHttps() {
  const host = window.location.hostname
  const port = window.location.port || '7266'
  window.open(`https://${host}:${port}`, '_self')
}

// 切换到 HTTP（本地模式）
function switchToHttp() {
  const host = window.location.hostname
  const port = window.location.port || '7266'
  window.open(`http://${host}:${port}`, '_self')
}

// ==================== 复制 ====================
function copyLocal() {
  if (!text.value.trim()) {
    showToast('请先输入文字', 'err', 1500)
    return
  }
  clipboardCopy(text.value.trim(), (ok) => {
    showToast(ok ? '✅ 已复制' : '复制失败', ok ? 'ok' : 'err', 1500)
  })
}

function clipboardCopy(text: string, cb: (ok: boolean) => void) {
  if (navigator.clipboard && window.isSecureContext) {
    navigator.clipboard.writeText(text).then(() => cb(true)).catch(() => clipboardFallback(text, cb))
  } else {
    clipboardFallback(text, cb)
  }
}

function clipboardFallback(text: string, cb: (ok: boolean) => void) {
  const ta = document.createElement('textarea')
  ta.value = text
  ta.style.cssText = 'position:fixed;left:-9999px'
  document.body.appendChild(ta)
  ta.select()
  let ok = false
  try { ok = document.execCommand('copy') } catch (e) {}
  document.body.removeChild(ta)
  cb(ok)
}

// ==================== 清空 ====================
async function doClear() {
  try {
    // 传递设备ID供后端识别源设备（用于广播时排除）
    const headers: Record<string, string> = {
      'X-Device-Id': clientId.value
    }
    const result = await apiPost('/api/clear', {}, { showError: false, timeout: 5000, headers })
    if (result.success) {
      text.value = ''
      showToast('🧹 已清空', 'ok', 1200)
    } else {
      showToast('清空失败', 'err', 2000)
    }
  } catch (e) {
    logger.error('Clear', '清空失败', { error: e })
    showToast('清空失败', 'err', 2000)
  }
}

// ==================== 历史 ====================
async function loadHistory() {
  try {
    const result = await apiGet<any>(`/api/history?offset=0&limit=20`, { showError: false })
    if (result.success && result.data) {
      history.value = result.data.items || []
      historyTotal.value = result.data.total || 0
      historyOffset.value = history.value.length
    }
  } catch (e) {
    logger.error('History', '加载历史失败', { error: e })
  }
}

async function loadMoreHistory() {
  if (scrollLoading.value) return
  scrollLoading.value = true
  try {
    const result = await apiGet<any>(`/api/history?offset=${historyOffset.value}&limit=20`, { showError: false })
    if (result.success && result.data) {
      const newItems = result.data.items || []
      history.value = [...history.value, ...newItems]
      historyOffset.value += newItems.length
      historyTotal.value = result.data.total || 0
    }
  } catch (e) {
    logger.error('History', '加载更多历史失败', { error: e })
  }
  scrollLoading.value = false
}

function onHistoryScroll() {
  if (scrollLoading.value) return
  if (history.value.length >= historyTotal.value) return
  const el = historyScroll.value
  if (!el) return
  const threshold = 80
  if (el.scrollTop + el.clientHeight >= el.scrollHeight - threshold) {
    loadMoreHistory()
  }
}

function toggleHistory() {
  showHistory.value = !showHistory.value
  if (showHistory.value) {
    loadHistory()
  }
}

let lastClickTime = 0
let lastClickIdx = -1

function onHistClick(index: number) {
  const now = Date.now()
  if (lastClickIdx === index && now - lastClickTime < 400) return
  lastClickIdx = index
  lastClickTime = now
}

function onHistDblClick(index: number) {
  if (index >= 0 && index < history.value.length) {
    text.value = history.value[index].text
    showToast('已恢复到输入框', 'ok', 800)
  }
}

function formatTime(timestamp: number) {
  const d = new Date(timestamp * 1000)
  return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
}

// HTML 转义，防止 XSS 攻击
function escapeHtml(text: string): string {
  const div = document.createElement('div')
  div.textContent = text
  return div.innerHTML
}

function highlightSearch(text: string) {
  const escapedText = escapeHtml(text)
  if (!historySearch.value) return escapedText
  const keyword = historySearch.value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  return escapedText.replace(new RegExp(`(${keyword})`, 'gi'), '<mark style="background:#fef08a;padding:0 2px;border-radius:2px;">$1</mark>')
}

// 获取分类标签
function getCategoryLabel(category: string): string {
  const labels: Record<string, string> = {
    url: '🔗',
    code: '💻',
    file_path: '📁',
    email: '📧',
    phone: '📞',
    id_card: '🔐',
    bank_card: '💳',
  }
  return labels[category] || ''
}

// 麦克风设置（与 SimpleRecorder 同步）
const micSettings = ref({
  auto_play: true,
  save_recordings: true,
  notify_on_receive: true,
  max_recordings: 50,
  quality_hint: 'medium',
})

async function loadMicSettings() {
  try {
    const result = await apiGet<any>('/api/audio/settings', { showError: false })
    if (result.success && result.data) {
      micSettings.value = { ...micSettings.value, ...result.data }
    }
  } catch (e) {
    logger.error('MicSettings', '加载麦克风设置失败', { error: e })
  }
}

async function saveMicSettings() {
  try {
    const result = await apiPost<any>('/api/audio/settings', micSettings.value, { showError: false })
    if (result.success) {
      showToast('麦克风设置已更新', 'ok', 1500)
    }
  } catch (e) {
    logger.error('MicSettings', '保存麦克风设置失败', { error: e })
  }
}

function toggleMicSetting(key: string) {
  ;(micSettings.value as any)[key] = !(micSettings.value as any)[key]
  saveMicSettings()
}

// ==================== 抽屉 ====================
async function loadStats() {
  try {
    const result = await apiGet<any>('/api/stats', { showError: false })
    if (result.success && result.data) {
      stats.value = result.data
    }
  } catch (e) {
    logger.error('Drawer', '加载统计失败', { error: e })
  }
}

function openDrawer() {
  showDropdown.value = false
  showDrawer.value = true
  loadStats()
  loadMicSettings()
}

function closeDrawer() {
  showDrawer.value = false
}

function drawerToggle(key: 'auto_copy' | 'auto_clear' | 'persist_history') {
  settings.value[key] = !settings.value[key]
  if (key === 'auto_clear') {
    if (settings.value.auto_clear) {
      settings.value.auto_copy = true
      showToast('🧹 已开启自动清空', 'ok', 2000)
    } else {
      showToast('🧹 已关闭自动清空', 'ok', 2000)
    }
  }
  if (key === 'auto_copy') {
    showToast(settings.value.auto_copy ? '📋 已开启自动复制' : '📋 已关闭自动复制', 'ok', 1500)
  }
  if (key === 'persist_history') {
    showToast(settings.value.persist_history ? '💾 历史永久保存' : '💾 仅保存本次会话', 'ok', 2000)
  }
  saveSettings()
}

// ==================== 端口编辑 ====================
function startPortEdit() {
  editingPort.value = true
  portInput.value = String(currentPort.value)
  nextTick(() => {
    const input = document.getElementById('port-input')
    if (input) {
      input.focus()
      input.select()
    }
  })
}

async function saveNewPort() {
  const newPort = parseInt(portInput.value)
  if (isNaN(newPort) || newPort < 1024 || newPort > 65535) {
    showToast('端口无效（1024-65535）', 'err', 2000)
    portInput.value = String(currentPort.value)
    return
  }
  showToast('正在检查端口冲突...', 'loading', 0)
  try {
    const checkResult = await apiPost<any>('/api/port/check', { port: newPort }, { showError: false })
    if (!checkResult.success || !checkResult.data?.available) {
      showToast('❌ 端口被占用', 'err', 3000)
      portInput.value = String(currentPort.value)
      return
    }
    
    await apiPost<any>('/api/settings', { port: newPort }, { showError: false })
    await apiPost<any>('/api/restart', {}, { showError: false })
    showToast('端口已更新，正在重启...', 'warn', 3000)
    closeDrawer()
    setTimeout(() => {
      const ip = localIp.value || location.hostname
      window.open(`http://${ip}:${newPort}`, '_self')
    }, 4000)
  } catch (e) {
    showToast('保存失败', 'err', 3000)
    logger.error('Port', '端口保存失败', { error: e })
  }
  editingPort.value = false
}

function cancelPortEdit() {
  editingPort.value = false
  portInput.value = String(currentPort.value)
}

// ==================== 重启服务 ====================
async function drawerRestart() {
  closeDrawer()
  showToast('正在重启服务...', 'warn', 0)
  logger.info('Drawer', '请求重启服务')
  try {
    await apiPost('/api/restart', {}, { showError: false })
    setTimeout(() => { location.reload() }, 3000)
  } catch (e) {
    showToast('重启失败', 'err', 3000)
    logger.error('Drawer', '重启服务失败', { error: e })
  }
}

// ==================== 运行日志 ====================
function drawerOpenLogs() {
  showLogs()
}

function showLogs() {
  showDropdown.value = false
  const w = window.open('', '_blank', 'width=700,height=500')
  if (!w) {
    showToast('弹窗被拦截', 'err', 2000)
    return
  }
  w.document.open()
  w.document.write(`
    <!DOCTYPE html><html><head><meta charset="UTF-8"><title>运行日志</title></head>
    <body style="margin:0;font-family:monospace;background:#1e1e1e;color:#d4d4d4;font-size:13px;">
    <div style="position:sticky;top:0;background:#1e1e1e;padding:10px 12px;border-bottom:2px solid #007acc;display:flex;align-items:center;gap:10px;">
    <span style="color:#569cd6;font-size:14px;font-weight:600;">Voice Bridge - 运行日志</span>
    <button id="refBtn" style="background:#007acc;color:white;border:none;padding:3px 12px;border-radius:4px;cursor:pointer;font-size:12px;">手动刷新</button>
    <span id="ts" style="color:#6a9955;font-size:11px;"></span>
    </div>
    <div id="lc" style="padding:8px 12px;line-height:1.8;max-height:100vh;overflow-y:auto;"></div>
    </body></html>
  `)
  w.document.close()

  w.loadLogs = async () => {
    const lc = w.document.getElementById('lc')
    const ts = w.document.getElementById('ts')
    if (!lc || !ts) return
    lc.textContent = '加载中...'
    try {
      const result = await apiGet<any>('/api/logs', { showError: false })
      if (!result.success || !result.data) {
        lc.textContent = '加载失败'
        return
      }
      const logs = result.data.logs || []
      if (!logs.length) {
        lc.textContent = '暂无日志'
        ts.textContent = ''
        return
      }
      const reversed = logs.slice().reverse()
      lc.innerHTML = reversed.map((l: string) => {
        let c = '#9cdcfe'
        if (l.indexOf('[ERROR]') >= 0) c = '#f48771'
        else if (l.indexOf('[WARNING]') >= 0) c = '#cca700'
        else if (l.indexOf('[DEBUG]') >= 0) c = '#6a9955'
        else if (l.indexOf('[+]') >= 0) c = '#4ec9b0'
        return `<div style="padding:2px 0;border-bottom:1px solid #2a2a2a;color:${c}">${l.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')}</div>`
      }).join('')
      ts.textContent = `更新: ${new Date().toLocaleTimeString()} | 共 ${logs.length} 条`
    } catch (e) {
      lc.textContent = '解析失败'
    }
  }

  w.document.getElementById('refBtn')?.addEventListener('click', () => (w as any).loadLogs())
  ;(w as any).loadLogs()
}

// ==================== 二维码 ====================
async function initQR() {
  if (!qrCanvas.value) return
  try {
    const result = await apiGet<any>('/api/info', { showError: false })
    if (!result.success || !result.data) {
      qrUrl.value = window.location.origin
    } else {
      // 使用当前访问地址作为二维码内容
      qrUrl.value = result.data.lan_url || window.location.origin
    }
    await QRCode.toCanvas(qrCanvas.value, qrUrl.value, {
      width: 160,
      margin: 1,
      color: { dark: '#1a1a2e', light: '#ffffff' }
    })
  } catch (e) {
    logger.error('QRCode', '二维码生成失败', { error: e })
  }
}

// ==================== 设备tooltip ====================
const showDeviceTip = ref(false)
const deviceTipStyle = ref({ top: '0px', left: '0px' })

function onStatusHover(e: MouseEvent) {
  if (!devices.value.length) return
  showDeviceTip.value = true
  const rect = (e.target as HTMLElement).getBoundingClientRect()
  deviceTipStyle.value = {
    top: `${rect.bottom + 6}px`,
    left: `${Math.max(0, rect.left - 40)}px`
  }
}

function hideDeviceTip() {
  showDeviceTip.value = false
}

// ==================== 键盘快捷键 ====================
function handleKeydown(e: KeyboardEvent) {
  if (e.ctrlKey && e.key === 'Enter') {
    e.preventDefault()
    doSync()
  }
  if (e.key === 'Escape') {
    e.preventDefault()
    doClear()
  }
}

// ==================== 首次访问引导 ====================
// localStorage key
const ONBOARDING_KEY = 'vb_onboarding_done'

// 检查是否首次访问（电脑端首次使用才引导）
function checkFirstVisit() {
  // 只有电脑端 localhost 访问才进行首次引导
  if (!isLocalhost.value) return false
  
  // 检查是否已完成引导
  if (localStorage.getItem(ONBOARDING_KEY)) return false
  
  return true
}

// 标记引导已完成
function markOnboardingDone() {
  localStorage.setItem(ONBOARDING_KEY, '1')
}

// ==================== 生命周期 ====================
onMounted(() => {
  localStorage.setItem('vb_client_id', clientId.value)
  
  // 首次访问，自动跳转到引导页
  if (checkFirstVisit()) {
    // 延迟一点跳转，让页面先渲染
    setTimeout(() => {
      window.location.href = '/setup'
    }, 500)
    return // 不执行后续初始化
  }
  
  loadSettings()
  loadMicSettings()
  
  // 初始化：先拉一次初始数据，然后建立 WebSocket 连接
  doPoll()
  
  // 启动 WebSocket 剪贴板连接（主通道，保证实时性）
  connectClipboardWS()
  
  // 启动轮询兜底（800ms 间隔，保证可靠性）
  pollTimer = window.setInterval(() => {
    doPoll()
  }, 800)

  sleepCheckTimer = window.setInterval(checkSleep, 10000)
  const events = ['keydown', 'mousedown', 'touchstart', 'scroll', 'input']
  events.forEach(ev => {
    document.addEventListener(ev, onActivity, { passive: true })
  })

  // 检查 HTTPS 状态
  checkHttps()
  
  setTimeout(initQR, 1000)
  document.addEventListener('click', closeDropdown)
})

onUnmounted(() => {
  if (toastTimer.value) clearTimeout(toastTimer.value)
  if (pollTimer) clearInterval(pollTimer)
  if (sleepCheckTimer) clearInterval(sleepCheckTimer)
  disconnectClipboardWS()  // 断开 WebSocket
  document.removeEventListener('click', closeDropdown)
})
</script>

<template>
  <div class="card">
    <!-- 头部 -->
    <div class="header">
      <div class="header-left">
        <h1>Voice Bridge</h1>
        <!-- 状态指示灯 -->
        <span
          id="status-dot"
          :class="['status-dot', isSleeping ? 'sleeping' : (isOnline ? 'online' : 'offline')]"
          @mouseenter="onStatusHover"
          @mouseleave="hideDeviceTip"
        ></span>
        <!-- 设备tooltip -->
        <div v-if="showDeviceTip && devices.length" id="device-tip" class="device-tip" :style="deviceTipStyle">
          <div class="device-tip-title">📡 已连接设备</div>
          <div v-for="d in devices" :key="d.ip" class="device-tip-item">
            <span>{{ d.device_type === 'mobile' ? '📱' : '💻' }}</span>
            <span class="device-ip">{{ d.ip }}</span>
            <span v-if="d.is_local || d.ip === localIp" class="device-local">本机</span>
          </div>
        </div>
        <!-- 二维码 -->
        <div class="qr-wrap">
          <button class="qr-btn" title="手机扫码访问">
            <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.8">
              <rect x="2" y="2" width="8" height="8" rx="1.5"/>
              <rect x="14" y="2" width="8" height="8" rx="1.5"/>
              <rect x="2" y="14" width="8" height="8" rx="1.5"/>
              <rect x="4.5" y="4.5" width="3" height="3" rx="0.5" fill="currentColor" stroke="none"/>
              <rect x="16.5" y="4.5" width="3" height="3" rx="0.5" fill="currentColor" stroke="none"/>
              <rect x="4.5" y="16.5" width="3" height="3" rx="0.5" fill="currentColor" stroke="none"/>
              <rect x="14" y="14" width="2.8" height="2.8" fill="currentColor" stroke="none"/>
              <rect x="18.5" y="18.5" width="2.8" height="2.8" fill="currentColor" stroke="none"/>
              <rect x="18.5" y="14" width="2.8" height="2.8" fill="currentColor" stroke="none"/>
            </svg>
          </button>
          <div class="qr-popup">
            <div class="qr-popup-title">📱 手机扫码访问</div>
            <canvas ref="qrCanvas"></canvas>
            <div class="qr-popup-url">{{ qrUrl }}</div>
            <div class="qr-popup-tip">打开相机 → 扫码</div>
          </div>
        </div>
      </div>

      <div class="gear-wrap">
        <button class="gear-btn" @click="onGearClick">⚙️</button>
        <div :class="['dropdown', { show: showDropdown }]">
          <div class="dd-label">同步模式</div>
          <div class="dd-item" @click="cycleMode">
            <span class="label">🔄 当前模式</span>
            <span style="font-size:12px;color:var(--sub)">{{ modeName }}</span>
          </div>
          <div class="dd-label">同步选项</div>
          <div
            :class="['dd-item', { disabled: isLocked }]"
            @click="!isLocked && toggleOpt('auto_copy')"
          >
            <span class="label">📋 自动复制到剪贴板 <span v-if="isLocked" style="font-size:10px;color:#9ca3af">🔒</span></span>
            <div :class="['toggle', { on: settings.auto_copy, locked: isLocked }]"></div>
          </div>
          <div class="dd-item" @click="toggleOpt('auto_clear')">
            <span class="label">🧹 同步后自动清空</span>
            <div :class="['toggle', { on: settings.auto_clear }]"></div>
          </div>
          <div style="border-top:1px solid #e5e7eb"></div>
          <div class="dd-item" @click="openDrawer">
            <span class="label">⚙️ 更多选项</span>
          </div>
        </div>
      </div>
    </div>

    <div class="sub">
      手机 ↔ 电脑 文字同步
      <span
        id="mode-tag"
        :class="['mode-tag', settings.mode]"
        @click="cycleMode"
        title="点击切换模式"
      >{{ modeName }}</span>
    </div>

    <!-- Toast 提示 -->
    <div :class="['toast', { show: toast.show, 'fade-out': toast.fading }, toast.type]">
      {{ toast.message }}
    </div>

    <!-- 输入框 -->
    <div style="position:relative;">
      <textarea
        id="sync-textarea"
        v-model="text"
        placeholder="在这里输入文字（可用手机语音输入法）..."
        style="min-height:120px;max-height:400px;overflow-y:auto;"
        @keydown="handleKeydown"
      ></textarea>
      <span id="char-count" class="char-count">{{ charCount }} 字</span>
    </div>

    <!-- 按钮 -->
    <div class="btn-row">
      <button class="btn btn-primary" @click="doSync" :disabled="syncing">📤 同步</button>
      <button class="btn btn-green" @click="copyLocal">📋 复制</button>
    </div>
    <div class="btn-row">
      <button class="btn btn-gray" @click="doClear">🗑️ 清空</button>
      <button class="btn btn-orange" @click="toggleHistory">📜 历史</button>
    </div>

    <!-- 麦克风桥接（用 ErrorBoundary 包裹，防止组件错误影响整体） -->
    <ErrorBoundary @error="handleComponentError" fallbackMessage="麦克风组件加载失败">
      <SimpleRecorder :deviceId="clientId" />
    </ErrorBoundary>

    <!-- 历史 -->
    <div v-show="showHistory" class="history">
      <h3>📜 历史记录</h3>
      <div id="h-count" class="h-count">共 {{ historyTotal }} 条，已显示 {{ filteredHistory.length }} 条</div>
      
      <!-- 搜索框 -->
      <div style="padding:0 0 8px 0;">
        <input
          v-model="historySearch"
          type="text"
          placeholder="🔍 搜索历史内容..."
          style="width:100%;padding:8px 10px;border:1.5px solid #e5e7eb;border-radius:6px;font-size:13px;outline:none;"
        >
      </div>
      
      <!-- 分类过滤 -->
      <div class="category-tabs">
        <span
          v-for="cat in contentCategories"
          :key="cat.value"
          :class="['cat-tab', { active: historyFilterCategory === cat.value }]"
          @click="historyFilterCategory = cat.value"
        >
          {{ cat.label }}
        </span>
      </div>
      
      <div ref="historyScroll" class="history-scroll" @scroll="onHistoryScroll">
        <ul class="h-list">
          <li
            v-for="(item, index) in filteredHistory"
            :key="index"
            :class="['h-item', { overwritten: item.overwritten }]"
            @click="onHistClick(index)"
            @dblclick="onHistDblClick(index)"
          >
            <div class="time">
              {{ formatTime(item.time) }}
              <!-- 内容分类标签 -->
              <span v-if="item.content_category && item.content_category !== 'plain'" class="cat-tag" :data-cat="item.content_category">
                {{ getCategoryLabel(item.content_category) }}
              </span>
              <span v-if="item.overwritten" class="tag">被覆盖</span>
              <span class="hint">双击恢复</span>
            </div>
            <div v-html="highlightSearch(item.text)"></div>
          </li>
          <li v-if="!filteredHistory.length" style="color:#999;text-align:center;padding:10px">
            {{ historySearch ? '无匹配结果' : '暂无' }}
          </li>
        </ul>
        <div
          v-if="filteredHistory.length < historyTotal && !historySearch"
          id="load-more"
          class="load-more"
          :class="{ loading: scrollLoading }"
          @click="loadMoreHistory"
        >
          {{ scrollLoading ? '加载中...' : `↓ 继续滚动加载更多 (${historyTotal}条)` }}
        </div>
      </div>
    </div>
  </div>

  <!-- 抽屉遮罩 -->
  <div v-if="showDrawer" id="drawer-overlay" class="drawer-overlay"></div>

  <!-- 设置抽屉 -->
  <div id="settings-drawer" :class="{ open: showDrawer }">
    <div class="drawer-header">
      <h2>⚙️ 设置</h2>
      <button class="drawer-close" @click="closeDrawer">关闭</button>
    </div>
    <div class="drawer-body">
      <!-- 模式 -->
      <div class="drawer-section">
        <div class="drawer-section-title">同步模式</div>
        <div class="drawer-row">
          <span class="label">🔄 当前模式</span>
          <span
            id="dr-mode"
            style="font-size:13px;color:var(--sub);cursor:pointer;"
            @click="cycleMode"
          >{{ modeName }}</span>
        </div>
        <div class="drawer-row" style="border:none;padding-top:4px;">
          <span class="label" style="font-size:12px;color:var(--gray-dark)">点击标签切换</span>
          <span style="font-size:11px;color:var(--primary)">
            {{ settings.mode === 'manual' ? '点击标签切换为自动模式' : '点击标签切换为手动模式' }}
          </span>
        </div>
      </div>

      <!-- 同步选项 -->
      <div class="drawer-section">
        <div class="drawer-section-title">同步选项</div>
        <div class="drawer-row" :style="{ opacity: isLocked ? '0.6' : '1' }">
          <div>
            <div class="label" id="dr-copy-label">📋 自动复制到剪贴板 <span style="font-size:10px;color:#9ca3af">🔒</span></div>
            <div class="desc" id="dr-copy-desc">{{ isLocked ? '自动模式或自动清空时锁定' : '开启后同步自动复制到剪贴板' }}</div>
          </div>
          <div
            :class="['toggle', { on: settings.auto_copy, locked: isLocked }]"
            @click="!isLocked && drawerToggle('auto_copy')"
          ></div>
        </div>
        <div class="drawer-row">
          <div>
            <div class="label">🧹 同步后自动清空</div>
            <div class="desc">同步成功后清空输入框</div>
          </div>
          <div
            :class="['toggle', { on: settings.auto_clear }]"
            @click="drawerToggle('auto_clear')"
          ></div>
        </div>
        <div class="drawer-row">
          <div>
            <div class="label">💾 永久保存历史记录</div>
            <div class="desc">下次启动保留历史记录</div>
          </div>
          <div
            :class="['toggle', { on: settings.persist_history }]"
            @click="drawerToggle('persist_history')"
          ></div>
        </div>
      </div>

      <!-- 统计 -->
      <div class="drawer-section">
        <div class="drawer-section-title">📊 统计</div>
        <div class="drawer-stat">
          <div class="drawer-stat-card">
            <div class="num">{{ stats.total_syncs }}</div>
            <div class="lbl">同步次数</div>
          </div>
          <div class="drawer-stat-card">
            <div class="num" style="font-size:14px;">{{ stats.total_chars }} 字</div>
            <div class="lbl">总字数</div>
          </div>
          <div class="drawer-stat-card">
            <div class="num">{{ stats.active_clients }}</div>
            <div class="lbl">连接设备</div>
          </div>
          <div class="drawer-stat-card">
            <div class="num">{{ stats.total_history }}</div>
            <div class="lbl">历史记录</div>
          </div>
        </div>
      </div>

      <!-- 麦克风桥接 -->
      <div class="drawer-section">
        <div class="drawer-section-title">🎤 麦克风桥接</div>
        <div class="drawer-row">
          <div>
            <div class="label">📻 自动播放录音</div>
            <div class="desc">收到手机录音后自动在电脑播放</div>
          </div>
          <div
            :class="['toggle', { on: micSettings.auto_play }]"
            @click="toggleMicSetting('auto_play')"
          ></div>
        </div>
        <div class="drawer-row">
          <div>
            <div class="label">💾 永久保存录音</div>
            <div class="desc">重启后保留历史录音文件</div>
          </div>
          <div
            :class="['toggle', { on: micSettings.save_recordings }]"
            @click="toggleMicSetting('save_recordings')"
          ></div>
        </div>
        <div class="drawer-row">
          <span class="label">📦 最多保留条数</span>
          <select
            v-model="micSettings.max_recordings"
            @change="saveMicSettings"
            style="border:1.5px solid #d1d5db;border-radius:6px;padding:4px 8px;font-size:12px;color:#374151;background:white;cursor:pointer;outline:none;"
          >
            <option :value="10">10 条</option>
            <option :value="20">20 条</option>
            <option :value="50">50 条</option>
            <option :value="100">100 条</option>
          </select>
        </div>
      </div>

      <!-- 关于 -->
      <div class="drawer-section">
        <div class="drawer-section-title">关于</div>
        <div class="drawer-row">
          <span class="label">🎤 Voice Bridge</span>
          <span style="font-size:12px;color:var(--sub)">v2.0</span>
        </div>
        <div class="drawer-row">
          <span class="label">🔌 端口</span>
          <span
            v-if="!editingPort"
            class="port-edit"
            @dblclick="startPortEdit"
          >
            {{ currentPort }} <small style="color:var(--gray-dark)">(双击修改)</small>
          </span>
          <div v-else style="display:flex;align-items:center;gap:4px;">
            <input
              id="port-input"
              v-model="portInput"
              class="port-edit-input"
              @keydown.enter="saveNewPort"
              @keydown.escape="cancelPortEdit"
              @blur="saveNewPort"
            >
          </div>
        </div>
      </div>

      <!-- 操作 -->
      <div class="drawer-section" style="margin-top:24px;">
        <button class="btn btn-primary" style="width:100%;margin-bottom:8px;" @click="drawerRestart">🔄 重启服务</button>
        <button class="btn btn-gray" style="width:100%;" @click="drawerOpenLogs">📋 运行日志</button>
      </div>
    </div>
  </div>
</template>

<style>
/* ========== 原版CSS样式（1:1复刻） ========== */
:root {
  --bg: #f0f2f5;
  --card: #ffffff;
  --text: #1a1a2e;
  --sub: #6b7280;
  --primary: #3b82f6;
  --primary-dark: #2563eb;
  --green: #22c55e;
  --green-dark: #16a34a;
  --red: #ef4444;
  --gray: #9ca3af;
  --gray-dark: #6b7280;
  --radius: 10px;
  --shadow: 0 2px 12px rgba(0,0,0,0.08);
}

* { box-sizing: border-box; margin: 0; padding: 0; }

body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  background: var(--bg);
  color: var(--text);
  line-height: 1.6;
  padding: 16px;
  max-width: 600px;
  margin: 0 auto;
}

.card {
  background: var(--card);
  border-radius: var(--radius);
  box-shadow: var(--shadow);
  padding: 20px;
}

.header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 4px;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 8px;
}

h1 { font-size: 1.5rem; color: var(--primary); }

.sub {
  font-size: 0.85rem;
  color: var(--sub);
  margin-bottom: 16px;
}

/* 模式标签 */
.mode-tag {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 0.75rem;
  font-weight: 600;
  margin-left: 4px;
  vertical-align: middle;
  cursor: pointer;
  transition: all 0.2s ease;
  user-select: none;
}

.mode-tag.manual { background: #e5e7eb; color: #374151; }
.mode-tag.auto { background: #dbeafe; color: #1d4ed8; }

.mode-tag:hover {
  opacity: 0.85;
  transform: scale(1.08);
  box-shadow: 0 2px 8px rgba(0,0,0,0.12);
}

.mode-tag:active { transform: scale(0.94); }


/* HTTPS 提示 */
.https-tip {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  background: linear-gradient(135deg, #fef3c7 0%, #fde68a 100%);
  border: 1.5px solid #fcd34d;
  border-radius: 10px;
  margin-bottom: 14px;
  font-size: 13px;
  color: #92400e;
}

.https-icon {
  font-size: 20px;
  flex-shrink: 0;
}

.https-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.https-title {
  font-weight: 600;
  color: #b45309;
}

.https-desc {
  font-size: 11px;
  color: #d97706;
}

.https-hint {
  font-size: 11px;
  color: #b45309;
  font-weight: 600;
  background: #fff;
  padding: 4px 10px;
  border-radius: 6px;
  white-space: nowrap;
  box-shadow: 0 1px 3px rgba(0,0,0,0.1);
}

/* 状态灯 */
.status-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  display: inline-block;
  flex-shrink: 0;
  transition: background 0.5s;
  cursor: pointer;
}

.status-dot.online {
  background: var(--green);
  box-shadow: 0 0 6px rgba(34,197,94,0.5);
}

.status-dot.sleeping {
  background: #fbbf24;
  box-shadow: 0 0 6px rgba(251,191,36,0.5);
}

.status-dot.offline {
  background: var(--red);
  box-shadow: 0 0 6px rgba(239,68,68,0.5);
}

/* 设备tooltip */
.device-tip {
  position: fixed;
  z-index: 9999;
  background: #1a1a2e;
  color: #fff;
  border-radius: 8px;
  padding: 10px 14px;
  font-size: 12px;
  min-width: 160px;
  box-shadow: 0 4px 16px rgba(0,0,0,0.25);
  pointer-events: none;
}

.device-tip-title {
  font-weight: 600;
  margin-bottom: 6px;
  color: #9cdcfe;
}

.device-tip-item {
  padding: 3px 0;
  display: flex;
  align-items: center;
  gap: 6px;
}

.device-ip {
  font-family: monospace;
}

.device-local {
  background: #3b82f6;
  padding: 1px 4px;
  border-radius: 3px;
  font-size: 10px;
  color: #fff;
}

/* 齿轮按钮 */
.gear-wrap { position: relative; }

.gear-btn {
  background: none;
  border: none;
  font-size: 22px;
  cursor: pointer;
  padding: 4px 8px;
  border-radius: 6px;
  transition: background 0.2s;
}

.gear-btn:hover { background: #f3f4f6; }

/* 下拉菜单 */
.dropdown {
  position: absolute;
  top: 100%;
  right: 0;
  background: var(--card);
  border-radius: var(--radius);
  box-shadow: 0 8px 24px rgba(0,0,0,0.15);
  min-width: 270px;
  z-index: 100;
  display: none;
  overflow: hidden;
}

.dropdown.show { display: block; }

.dd-label {
  padding: 10px 16px 6px;
  font-size: 11px;
  color: var(--gray-dark);
  text-transform: uppercase;
  font-weight: 600;
  letter-spacing: 0.5px;
}

.dd-item {
  padding: 12px 16px;
  cursor: pointer;
  font-size: 14px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  transition: background 0.15s;
  border-bottom: 1px solid #f3f4f6;
}

.dd-item:last-child { border-bottom: none; }
.dd-item:hover { background: #f9fafb; }
.dd-item.disabled { opacity: 0.5; cursor: not-allowed; }

.dd-item .label {
  display: flex;
  align-items: center;
  gap: 8px;
}

/* 开关 */
.toggle {
  width: 44px;
  height: 24px;
  border-radius: 12px;
  position: relative;
  cursor: pointer;
  transition: background 0.3s;
  flex-shrink: 0;
}

.toggle.on { background: var(--green); }
.toggle.off { background: #d1d5db; }
.toggle.locked { cursor: not-allowed; }

.toggle::after {
  content: '';
  position: absolute;
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background: white;
  top: 2px;
  left: 2px;
  transition: left 0.3s;
  box-shadow: 0 1px 3px rgba(0,0,0,0.2);
}

.toggle.on::after {
  left: 22px;
}

.toggle.on::after { left: 22px; }
.toggle.off::after { left: 2px; }

/* Toast */
.toast {
  padding: 10px 14px;
  border-radius: var(--radius);
  margin-bottom: 14px;
  display: none;
  font-size: 14px;
  font-weight: 500;
  animation: fadeIn 0.2s ease;
}

.toast.show { display: block; }
.toast.ok { background: #dcfce7; color: #166534; }
.toast.err { background: #fee2e2; color: #991b1b; }
.toast.loading { background: #e5e7eb; color: #374151; }
.toast.warn { background: #fef3c7; color: #92400e; }

@keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }
@keyframes fadeOut { from { opacity: 1; } to { opacity: 0; } }
.toast.fade-out { animation: fadeOut 0.6s ease forwards; }

/* 输入框 */
textarea {
  width: 100%;
  min-height: 120px;
  max-height: 400px;
  padding: 14px;
  border: 2px solid #e5e7eb;
  border-radius: var(--radius);
  font-size: 16px;
  font-family: inherit;
  resize: vertical;
  transition: border-color 0.3s;
  outline: none;
  position: relative;
}

textarea:focus { border-color: var(--primary); }

#char-count {
  position: absolute;
  bottom: 8px;
  right: 10px;
  font-size: 11px;
  color: var(--gray-dark);
  pointer-events: none;
}

/* 按钮 */
.btn-row { display: flex; gap: 10px; margin-top: 12px; }

.btn {
  flex: 1;
  padding: 14px 12px;
  border: none;
  border-radius: var(--radius);
  font-size: 15px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
  color: white;
}

.btn:active { transform: scale(0.97); }
.btn:disabled { opacity: 0.7; cursor: not-allowed; }

.btn-primary { background: var(--primary); }
.btn-primary:hover { background: var(--primary-dark); }

.btn-green { background: var(--green); }
.btn-green:hover { background: var(--green-dark); }

.btn-gray { background: var(--gray-dark); }
.btn-gray:hover { background: #4b5563; }

.btn-orange { background: #f97316; }
.btn-orange:hover { background: #ea580c; }

/* 历史 */
.history {
  margin-top: 20px;
  border-top: 1px solid #e5e7eb;
  padding-top: 16px;
}

.history h3 { font-size: 1rem; margin-bottom: 10px; }

.h-list { list-style: none; }

.h-item {
  background: #f9fafb;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  padding: 10px;
  margin-bottom: 6px;
  font-size: 0.85rem;
  cursor: pointer;
  transition: background 0.15s;
}

.h-item:hover { background: #f3f4f6; }
.h-item.overwritten { opacity: 0.55; border-color: #d1d5db; background: #f3f4f6; }

.h-item .time { color: var(--gray-dark); font-size: 0.75rem; }
.h-item .tag {
  font-size: 0.7rem;
  color: #9ca3af;
  background: #f3f4f6;
  padding: 1px 6px;
  border-radius: 4px;
  margin-left: 6px;
}

.h-item .hint {
  font-size: 0.7rem;
  color: #b0b0b0;
  float: right;
  margin-top: -18px;
}

/* 分类标签 */
.cat-tag {
  font-size: 0.7rem;
  padding: 1px 5px;
  border-radius: 4px;
  margin-left: 6px;
  background: #e0e7ff;
  color: #4338ca;
}

.cat-tag[data-cat="url"] { background: #dbeafe; color: #1d4ed8; }
.cat-tag[data-cat="code"] { background: #dcfce7; color: #166534; }
.cat-tag[data-cat="file_path"] { background: #fef3c7; color: #92400e; }
.cat-tag[data-cat="email"] { background: #fce7f3; color: #9d174d; }
.cat-tag[data-cat="phone"] { background: #f3e8ff; color: #7c3aed; }
.cat-tag[data-cat="id_card"] { background: #fee2e2; color: #991b1b; }
.cat-tag[data-cat="bank_card"] { background: #ffedd5; color: #9a3412; }

/* 分类过滤标签页 */
.category-tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  padding: 0 0 10px 0;
}

.cat-tab {
  font-size: 12px;
  padding: 4px 10px;
  border-radius: 16px;
  background: #f3f4f6;
  color: #6b7280;
  cursor: pointer;
  transition: all 0.2s;
}

.cat-tab:hover {
  background: #e5e7eb;
}

.cat-tab.active {
  background: var(--primary);
  color: white;
}

.h-count {
  font-size: 0.75rem;
  color: var(--gray-dark);
  margin-bottom: 8px;
}

.history-scroll {
  max-height: 400px;
  overflow-y: auto;
  -webkit-overflow-scrolling: touch;
}

.load-more {
  text-align: center;
  padding: 10px;
  color: var(--primary);
  cursor: pointer;
  font-size: 14px;
  display: none;
}

.load-more.loading { color: var(--gray); }

/* 二维码 */
.qr-wrap { position: relative; margin-left: 1px; }

.qr-btn {
  background: none;
  border: none;
  cursor: pointer;
  padding: 2px 4px;
  border-radius: 5px;
  transition: background 0.2s;
  color: var(--sub);
  display: flex;
  align-items: center;
  opacity: 0.7;
}

.qr-btn:hover {
  background: #e0edff;
  color: var(--primary);
  opacity: 1;
}

.qr-popup {
  position: absolute;
  top: calc(100% + 10px);
  left: 50%;
  transform: translateX(-50%);
  background: var(--card);
  border-radius: 14px;
  box-shadow: 0 12px 40px rgba(0,0,0,0.18);
  padding: 16px 14px 12px;
  z-index: 100;
  display: none;
  width: 200px;
  text-align: center;
}

.qr-popup::before {
  content: '';
  position: absolute;
  top: -7px;
  left: 50%;
  transform: translateX(-50%);
  border: 7px solid transparent;
  border-top: none;
  border-bottom-color: var(--card);
  filter: drop-shadow(0 -2px 2px rgba(0,0,0,0.06));
}

.qr-wrap:hover .qr-popup {
  display: block;
  animation: qrFadeIn 0.25s cubic-bezier(.4,0,.2,1);
}

@keyframes qrFadeIn {
  from { opacity: 0; transform: translateX(-50%) translateY(-8px) scale(0.94); }
  to { opacity: 1; transform: translateX(-50%) translateY(0) scale(1); }
}

.qr-popup-title {
  font-size: 12px;
  color: var(--sub);
  margin-bottom: 10px;
  font-weight: 600;
}

.qr-popup canvas {
  border-radius: 8px;
  display: block;
  margin: 0 auto;
}

.qr-popup-url {
  font-size: 10px;
  color: var(--gray-dark);
  margin-top: 8px;
  word-break: break-all;
  font-family: 'SF Mono', Consolas, monospace;
  line-height: 1.4;
}

.qr-popup-tip {
  font-size: 10px;
  color: var(--primary);
  margin-top: 5px;
  font-weight: 500;
}

/* 抽屉 */
#settings-drawer {
  position: fixed;
  top: 0;
  right: 0;
  bottom: 0;
  width: 380px;
  max-width: 95vw;
  background: var(--card);
  z-index: 200;
  transform: translateX(100%);
  transition: transform 0.3s cubic-bezier(.4,0,.2,1);
  box-shadow: -8px 0 32px rgba(0,0,0,0.18);
  display: flex;
  flex-direction: column;
  border-left: 1px solid #e5e7eb;
}

#settings-drawer.open { transform: translateX(0); }

.drawer-header {
  padding: 16px 20px;
  border-bottom: 1px solid #e5e7eb;
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: var(--bg);
}

.drawer-header h2 { font-size: 1.1rem; color: var(--text); }

.drawer-close {
  background: #f3f4f6;
  border: none;
  border-radius: 6px;
  padding: 6px 12px;
  cursor: pointer;
  font-size: 13px;
  transition: background 0.2s;
}

.drawer-close:hover { background: #e5e7eb; }

.drawer-body {
  flex: 1;
  overflow-y: auto;
  padding: 16px 20px;
}

.drawer-section { margin-bottom: 20px; }

.drawer-section-title {
  font-size: 11px;
  color: var(--gray-dark);
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-bottom: 8px;
  padding-left: 2px;
}

.drawer-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 0;
  border-bottom: 1px solid #f3f4f6;
}

.drawer-row:last-child { border-bottom: none; }
.drawer-row .label { font-size: 14px; display: flex; align-items: center; gap: 6px; }
.drawer-row .desc { font-size: 11px; color: var(--gray-dark); }

.drawer-stat {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
}

.drawer-stat-card {
  background: #f3f4f6;
  border-radius: 8px;
  padding: 12px;
  text-align: center;
}

.drawer-stat-card .num {
  font-size: 20px;
  font-weight: 700;
  color: var(--primary);
}

.drawer-stat-card .lbl {
  font-size: 11px;
  color: var(--gray-dark);
  margin-top: 2px;
}

.port-edit {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  cursor: pointer;
  font-family: monospace;
  font-size: 14px;
  padding: 2px 6px;
  border-radius: 4px;
  transition: background 0.2s;
}

.port-edit:hover { background: #f3f4f6; }

.port-edit-input {
  width: 60px;
  padding: 1px 6px;
  border: 1.5px solid var(--primary);
  border-radius: 4px;
  font-size: 14px;
  font-family: monospace;
  text-align: center;
  outline: none;
}

/* 抽屉遮罩 */
.drawer-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0,0,0,0.3);
  z-index: 199;
}
</style>
