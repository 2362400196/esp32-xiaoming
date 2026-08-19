<template>
  <div class="tool-view">
    <!-- WebSerial 支持检测 -->
    <div v-if="!serialSupported" class="warn-card card card-in">
      <div class="warn-inner">
        <span class="warn-orb"><svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg></span>
        <div class="warn-text">
          <p class="warn-title">当前浏览器不支持 WebSerial</p>
          <p class="warn-sub">固件烧录与串口日志需要 <b>Chrome / Edge 等 Chromium 内核浏览器</b>，且页面需通过 <b>HTTPS</b> 或 <b>localhost</b> 访问（浏览器安全策略）。</p>
        </div>
      </div>
    </div>

    <template v-if="serialSupported">
      <!-- 分段切换 -->
      <div class="seg glass card-in">
        <button class="seg-item" :class="{ active: section === 'flash' }" @click="switchSection('flash')">
          <span class="seg-ico"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg></span> 固件烧录
        </button>
        <button class="seg-item" :class="{ active: section === 'serial' }" @click="switchSection('serial')">
          <span class="seg-ico"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><polyline points="4 17 10 11 4 5"/><line x1="12" y1="19" x2="20" y2="19"/></svg></span> 串口日志
        </button>
      </div>

      <!-- ============ 固件烧录 ============ -->
      <div v-if="section === 'flash'" class="tool-body">
        <!-- 烧录配置 -->
        <div class="panel panel-compact glass card-in">
          <div class="panel-head">
            <span class="panel-title">烧录配置</span>
            <span class="status-pill" :class="flashConnected ? 'on' : ''">
              <span class="pill-dot"></span>{{ flashConnected ? '已连接' : '未连接' }}
            </span>
          </div>
          <div class="config-grid">
            <div class="field">
              <span class="field-label">波特率</span>
              <select v-model="flashConfig.baudrate" class="input input-sm select-sm" :disabled="flashConnected || isFlashing || isErasing">
                <option value="9600">9600</option>
                <option value="115200">115200</option>
                <option value="230400">230400</option>
                <option value="460800">460800</option>
                <option value="921600">921600</option>
              </select>
            </div>
            <div class="field">
              <span class="field-label">烧录地址</span>
              <input v-model="flashConfig.flashAddress" placeholder="0x00" class="input input-sm select-sm" spellcheck="false" />
            </div>
            <div class="field">
              <span class="field-label">偏移 flash</span>
              <input v-model="flashConfig.flashOffset" placeholder="0x000" class="input input-sm select-sm" spellcheck="false" />
            </div>
          </div>
          <div class="btns-row">
            <button class="btn-mint" @click="connectFlashDevice" :disabled="flashConnected || isFlashing || isErasing" :class="{ loading: flashConnecting }">
              {{ flashConnecting ? '连接中...' : '连接设备' }}
            </button>
            <button v-if="flashConnected" class="btn-ghost btn-danger" @click="disconnectFlashDevice" :disabled="isFlashing || isErasing">断开</button>
            <button class="btn-ghost btn-file" @click="selectFirmware" :disabled="!flashConnected || isFlashing || isErasing">
              <span class="btn-file-label">{{ firmwareFileName || '选择固件 (.bin)' }}</span>
            </button>
            <button class="btn-ghost btn-danger" @click="eraseFlash" :disabled="!flashConnected || isFlashing" :class="{ loading: isErasing }">
              {{ isErasing ? '擦除中...' : '擦除 Flash' }}
            </button>
            <button class="btn-mint btn-flash" @click="startFlash" :disabled="!canFlash || !flashConnected || isFlashing || isErasing" :class="{ loading: isFlashing }">
              {{ isFlashing ? '烧录中...' : '开始烧录' }}
            </button>
          </div>
          <input ref="fileInput" type="file" accept=".bin" style="display: none" @change="handleFileSelect" />
        </div>

        <!-- 烧录进度环 -->
        <div class="panel glass card-in progress-panel">
          <div class="panel-head">
            <span class="panel-title">烧录进度</span>
            <div class="head-right">
              <button class="btn-ghost btn-sm" @click="clearFlashLogs">清除日志</button>
            </div>
          </div>
          <div class="progress-body">
            <div class="ring-wrap" :class="{ indeterminate: isIndeterminate }">
              <svg class="ring" viewBox="0 0 120 120">
                <circle class="ring-bg" cx="60" cy="60" r="52" />
                <circle class="ring-fg" :class="{ done: flashStage === 'done' }" cx="60" cy="60" r="52" :style="ringStyle" />
              </svg>
              <div class="ring-center">
                <span class="ring-pct">{{ ringCenter }}</span>
                <span class="ring-sub">{{ ringSub }}</span>
              </div>
            </div>
            <div class="stage-text">
              <span class="stage-dot" :class="flashStage"></span>
              {{ stageLabel }}
            </div>
            <div class="last-log" v-if="flashLogs.length">
              <span class="last-log-label">状态</span>
              {{ lastFlashLogMsg }}
            </div>
          </div>
        </div>

        <!-- 烧录步骤提示 -->
        <div class="tips-card card-in">
          <p class="tips-title">使用步骤</p>
          <ol class="tips-list">
            <li>用 USB 线连接 ESP32 开发板（首次需安装 CH340 驱动）</li>
            <li>按住 <b>Boot</b> 键，再按一下 <b>Reset</b> 键进入下载模式（部分模组无需）</li>
            <li>点击"连接设备"选择串口</li>
            <li>选择 .bin 固件 → 点击"开始烧录"</li>
          </ol>
        </div>
      </div>

      <!-- ============ 串口日志 ============ -->
      <div v-if="section === 'serial'" class="tool-body">
        <!-- 串口控制 -->
        <div class="panel panel-compact glass card-in">
          <div class="panel-head">
            <span class="panel-title">串口控制</span>
            <span class="status-pill" :class="serialConnected ? 'on' : ''">
              <span class="pill-dot"></span>{{ serialConnected ? '已连接' : '未连接' }}
            </span>
          </div>
          <div class="config-grid">
            <div class="field">
              <span class="field-label">波特率</span>
              <select v-model="serialBaud" class="input input-sm select-sm" :disabled="serialConnected">
                <option value="9600">9600</option>
                <option value="19200">19200</option>
                <option value="38400">38400</option>
                <option value="57600">57600</option>
                <option value="115200">115200</option>
                <option value="230400">230400</option>
                <option value="921600">921600</option>
              </select>
            </div>
            <div class="field field-grow">
              <span class="field-label">发送命令</span>
              <div class="send-box">
                <input v-model="sendData" class="input input-sm send-input" placeholder="输入命令后回车发送..." :disabled="!serialConnected" spellcheck="false" @keyup.enter="sendSerialData" />
                <button class="btn-mint btn-sm" :disabled="!serialConnected || !sendData" @click="sendSerialData">发送</button>
              </div>
            </div>
          </div>
          <div class="btns-row">
            <button class="btn-mint" @click="connectSerial" :disabled="serialConnected">连接设备</button>
            <button v-if="serialConnected" class="btn-ghost btn-danger" @click="disconnectSerial">断开</button>
          </div>
        </div>

        <!-- 日志终端 -->
        <div class="panel glass card-in">
          <div class="panel-head">
            <span class="panel-title">日志输出</span>
            <div class="head-right">
              <span class="log-count" v-if="serialLogs.length">{{ serialLogs.length }} 条</span>
              <button class="btn-ghost btn-sm" @click="togglePause">{{ serialPaused ? '恢复' : '暂停' }}</button>
              <button class="btn-ghost btn-sm" @click="copyLogs">复制</button>
              <button class="btn-ghost btn-sm btn-danger" @click="clearSerialLogs">清除</button>
            </div>
          </div>
          <div class="terminal">
            <div ref="serialTerminalRef" class="terminal-content">
              <div v-for="(log, i) in serialLogs" :key="i" class="log-line" :class="getSerialLogClass(log)">
                <span class="log-time">{{ logTime() }}</span>
                <span class="log-content">{{ log }}</span>
              </div>
            </div>
          </div>
        </div>

        <div class="tips-card card-in">
          <p class="tips-title">使用说明</p>
          <ol class="tips-list">
            <li>选择波特率（本固件默认 <b>115200</b>）后点击"连接设备"</li>
            <li>连接成功后会自动重启设备并开始抓取串口日志</li>
            <li>可在下方输入框向设备发送命令（自动追加 \r\n）</li>
            <li>Ctrl+L 可快速清空日志</li>
          </ol>
        </div>
      </div>
    </template>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { ESPLoader, Transport } from 'esptool-js'

const emit = defineEmits(['toast'])

const serialSupported = typeof navigator !== 'undefined' && !!navigator.serial
const section = ref('flash')

function switchSection(s) {
  if (s === section.value) return
  // 切换前关闭另一侧已占用的串口，避免端口冲突
  if (s === 'flash' && serialConnected.value) disconnectSerial()
  if (s === 'serial' && flashConnected.value) disconnectFlashDevice()
  section.value = s
}

// ==================== 通用 ====================
function formatSize(bytes) {
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(2) + ' KB'
  return (bytes / (1024 * 1024)).toFixed(2) + ' MB'
}

// ==================== 固件烧录 ====================
const flashConnected = ref(false)
const flashConnecting = ref(false)
const isFlashing = ref(false)
const isErasing = ref(false)
const firmwareData = ref(null)
const firmwareFileName = ref('')
const fileInput = ref(null)
const flashPort = ref(null)
const flashLogs = ref([])
const flashConfig = reactive({ baudrate: '921600', flashAddress: '0x00', flashOffset: '0x000' })
const canFlash = computed(() => firmwareData.value !== null)

const flashStage = ref('idle') // idle | busy | flash | done | error
const flashProgress = ref(0)
const flashLabel = ref('')
let flashResetTimer = null

const isIndeterminate = computed(() => flashStage.value === 'busy')
const ringStyle = computed(() => {
  const C = 2 * Math.PI * 52
  const pct = Math.min(100, Math.max(0, flashProgress.value))
  return {
    strokeDasharray: `${C}`,
    strokeDashoffset: `${C * (1 - pct / 100)}`,
  }
})
const stageLabel = computed(() => {
  switch (flashStage.value) {
    case 'busy': return flashLabel.value || '处理中...'
    case 'flash': return `正在烧录固件 ${flashProgress.value}%`
    case 'done': return flashLabel.value || '完成'
    case 'error': return flashLabel.value || '操作失败'
    default: return '等待烧录'
  }
})
const ringCenter = computed(() => {
  if (flashStage.value === 'flash') return `${flashProgress.value}%`
  if (flashStage.value === 'done') return '✓'
  if (flashStage.value === 'error') return '!'
  return ''
})
const ringSub = computed(() => {
  if (flashStage.value === 'flash') return '烧录中'
  if (flashStage.value === 'done') return '完成'
  if (flashStage.value === 'error') return '失败'
  if (flashStage.value === 'busy') return flashLabel.value || '处理中'
  return '就绪'
})
const lastFlashLogMsg = computed(() => {
  const last = flashLogs.value[flashLogs.value.length - 1]
  return last ? last.split(']')[1].trim() : ''
})

const resetFlashStage = () => {
  flashStage.value = 'idle'
  flashProgress.value = 0
  flashLabel.value = ''
}
const scheduleFlashReset = (delay = 4000) => {
  if (flashResetTimer) clearTimeout(flashResetTimer)
  flashResetTimer = setTimeout(resetFlashStage, delay)
}

const addFlashLog = (message) => {
  flashLogs.value.push(`[${new Date().toLocaleTimeString()}] ${message}`)
}

const getFlashLogClass = (log) => {
  if (log.includes('成功') || log.includes('success')) return 'log-success'
  if (log.includes('失败') || log.includes('错误') || log.includes('error')) return 'log-error'
  if (log.includes('警告') || log.includes('warning')) return 'log-warning'
  return ''
}

const clearFlashLogs = () => {
  flashLogs.value = []
  addFlashLog('日志已清除')
}

const connectFlashDevice = async () => {
  flashConnecting.value = true
  try {
    addFlashLog('正在请求串口连接...')
    flashPort.value = await navigator.serial.requestPort()
    try {
      const info = flashPort.value.getInfo()
      const vendor = (info.usbVendorId ?? 0).toString(16).toUpperCase().padStart(4, '0')
      const product = (info.usbProductId ?? 0).toString(16).toUpperCase().padStart(4, '0')
      addFlashLog(`已选择设备: VID=${vendor} PID=${product}`)
    } catch (e) {}
    flashConnected.value = true
    addFlashLog('串口连接成功，请选择固件后点击"开始烧录"')
    emit('toast', '设备连接成功')
  } catch (error) {
    if (/No port selected/i.test(error?.message || '')) {
      addFlashLog('已取消选择端口')
      return
    }
    addFlashLog(`连接失败: ${error.message}`)
    emit('toast', '连接失败')
    if (flashPort.value) {
      try { await flashPort.value.close() } catch (e) {}
      flashPort.value = null
    }
    flashConnected.value = false
  } finally {
    flashConnecting.value = false
  }
}

const disconnectFlashDevice = async () => {
  if (!flashPort.value) return
  try {
    if (flashPort.value.readable || flashPort.value.writable) {
      await flashPort.value.close()
    }
    flashPort.value = null
    flashConnected.value = false
    addFlashLog('设备已断开')
  } catch (error) {
    addFlashLog(`断开失败: ${error.message}`)
  }
}

const selectFirmware = () => fileInput.value?.click()

const handleFileSelect = (event) => {
  const file = event.target.files[0]
  if (!file) return
  if (!file.name.toLowerCase().endsWith('.bin')) {
    emit('toast', '请选择 .bin 格式的固件文件')
    return
  }
  firmwareFileName.value = file.name
  const reader = new FileReader()
  reader.onload = (e) => {
    firmwareData.value = new Uint8Array(e.target.result)
    addFlashLog(`已加载固件: ${file.name} (${formatSize(firmwareData.value.length)})`)
  }
  reader.readAsArrayBuffer(file)
}

const eraseFlash = async () => {
  let esploader = null
  let transport = null
  try {
    if (!flashPort.value || !flashConnected.value) {
      addFlashLog('请先连接串口设备')
      return
    }
    isErasing.value = true
    flashStage.value = 'busy'
    flashLabel.value = '正在擦除 Flash...'
    flashProgress.value = 0
    addFlashLog('正在准备擦除 Flash...')
    if (flashPort.value.readable || flashPort.value.writable) {
      try { await flashPort.value.close() } catch (e) {}
    }
    transport = new Transport(flashPort.value, true)
    esploader = new ESPLoader({ transport, baudrate: parseInt(flashConfig.baudrate), debugLogging: true })
    addFlashLog('正在连接设备...')
    const chip = await esploader.main('default_reset')
    addFlashLog(`连接成功，检测到芯片: ${chip}`)
    addFlashLog('正在擦除 Flash...')
    await esploader.eraseFlash()
    addFlashLog('Flash 擦除完成!')
    flashStage.value = 'done'
    flashLabel.value = 'Flash 擦除完成'
    flashProgress.value = 100
    scheduleFlashReset()
    emit('toast', 'Flash 擦除成功')
  } catch (error) {
    console.error('擦除失败:', error)
    flashStage.value = 'error'
    flashLabel.value = '擦除失败'
    addFlashLog(`擦除失败: ${error.message}`)
    scheduleFlashReset()
    emit('toast', `擦除失败: ${error?.message || '未知错误'}`)
  } finally {
    if (transport) {
      addFlashLog('正在关闭串口连接...')
      try { await transport.disconnect() } catch (e) { console.error(e) }
      addFlashLog('串口连接已关闭')
    }
    esploader = null
    transport = null
    isErasing.value = false
  }
}

const startFlash = async () => {
  let esploader = null
  let transport = null
  try {
    if (!firmwareData.value) { addFlashLog('请先选择要烧录的固件'); return }
    if (!flashPort.value || !flashConnected.value) { addFlashLog('请先连接串口设备'); return }
    isFlashing.value = true
    flashStage.value = 'busy'
    flashLabel.value = '正在连接设备...'
    flashProgress.value = 0
    addFlashLog('正在准备烧录...')
    if (flashPort.value.readable || flashPort.value.writable) {
      try { await flashPort.value.close() } catch (e) {}
    }
    transport = new Transport(flashPort.value, true)
    esploader = new ESPLoader({ transport, baudrate: parseInt(flashConfig.baudrate), debugLogging: true })
    addFlashLog('正在连接设备...')
    const chip = await esploader.main('default_reset')
    addFlashLog(`连接成功，检测到芯片: ${chip}`)
    addFlashLog('开始烧录固件...')
    flashStage.value = 'flash'
    flashProgress.value = 0
    const flashAddr = parseInt(flashConfig.flashAddress, 16) || 0x00
    const bytes = firmwareData.value
    let binary = ''
    for (let i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i])
    await esploader.writeFlash({
      fileArray: [{ data: binary, address: flashAddr }],
      flashSize: 'keep',
      flashMode: 'keep',
      flashFreq: 'keep',
      compress: true,
      reportProgress: (fileIndex, bytesWritten, totalBytes) => {
        if (totalBytes > 0) {
          flashProgress.value = Math.floor((bytesWritten / totalBytes) * 100)
        }
      },
    })
    flashProgress.value = 100
    addFlashLog('烧录成功! 正在重置设备...')
    await esploader.after('hard_reset')
    addFlashLog('固件烧录完成，设备已自动重启')
    flashStage.value = 'done'
    flashLabel.value = '烧录完成，设备已重启'
    scheduleFlashReset()
    emit('toast', '烧录成功')
  } catch (error) {
    console.error('烧录失败:', error)
    flashStage.value = 'error'
    flashLabel.value = '烧录失败'
    addFlashLog(`烧录失败: ${error.message}`)
    scheduleFlashReset()
    emit('toast', `烧录失败: ${error?.message || '未知错误'}`)
  } finally {
    if (transport) {
      addFlashLog('正在关闭串口连接...')
      try { await transport.disconnect() } catch (e) { console.error(e) }
      addFlashLog('串口连接已关闭')
    }
    esploader = null
    transport = null
    isFlashing.value = false
  }
}

// ==================== 串口日志 ====================
const serialPort = ref(null)
const serialTerminalRef = ref(null)
const reader = ref(null)
const serialConnected = ref(false)
const isNativeUsb = ref(false)
const serialBaud = ref('115200')
const serialLogs = ref([])
const serialPaused = ref(false)
const sendData = ref('')
const partialLog = ref('')
const batchLogs = ref('')


const addSerialLog = (message) => {
  serialLogs.value.push(message)
  if (serialLogs.value.length > 1000) serialLogs.value.shift()
  scrollToBottom(serialTerminalRef)
}

const getSerialLogClass = (log) => {
  if (log.startsWith('>')) return 'log-send'
  if (log.includes('成功') || log.includes('connected')) return 'log-success'
  if (log.includes('失败') || log.includes('错误') || log.includes('error')) return 'log-error'
  if (log.includes('断开') || log.includes('closed')) return 'log-warning'
  if (log.includes('重启')) return 'log-info'
  return ''
}

const logTime = () => new Date().toLocaleTimeString()

const connectSerial = async () => {
  try {
    addSerialLog('正在请求串口连接...')
    serialPort.value = await navigator.serial.requestPort()
    try {
      const info = serialPort.value.getInfo()
      const vendor = (info.usbVendorId ?? 0).toString(16).toUpperCase().padStart(4, '0')
      const product = (info.usbProductId ?? 0).toString(16).toUpperCase().padStart(4, '0')
      addSerialLog(`已选择设备: VID=${vendor} PID=${product}`)
      isNativeUsb.value = info.usbVendorId === 0x303a
      if (isNativeUsb.value) {
        addSerialLog('检测到原生 USB（USB-JTAG/CDC），使用专用复位方式')
        addSerialLog('提示：本固件控制台走 UART0(GPIO20/21)。若想查看应用日志，请改选外部 USB 转串口桥端口（CH340/CP210x），而非此原生 USB 端口')
      }
    } catch (e) {}

    let portOpened = false
    let openAttempts = 0
    const maxAttempts = 3
    let lastOpenError = null
    while (openAttempts < maxAttempts && !portOpened) {
      openAttempts++
      try {
        addSerialLog(`正在尝试打开串口 (第 ${openAttempts} 次)...`)
        if (serialPort.value.readable) {
          addSerialLog('串口已打开，直接使用')
          portOpened = true
          break
        }
        try { await serialPort.value.close() } catch (e) {}
        await serialPort.value.open({ baudRate: parseInt(serialBaud.value) })
        portOpened = true
        addSerialLog('串口连接成功')
      } catch (openError) {
        lastOpenError = openError
        if (openAttempts >= maxAttempts) break
        if (openError.message.includes('The port is already open')) {
          addSerialLog('串口被占用，2 秒后重试...')
        } else {
          addSerialLog(`打开失败（${openError.name || '未知错误'}），2 秒后重试...`)
        }
        await new Promise(resolve => setTimeout(resolve, 2000))
      }
    }

    if (!portOpened) {
      addSerialLog(`串口打开失败: ${lastOpenError?.message || '未知错误'}`)
      addSerialLog('排查建议：① 关闭其他占用该串口的软件（Arduino IDE / 串口助手）；② 确认选中的串口正确；③ 拔插 USB 线后重试')
      if (serialPort.value) {
        try { await serialPort.value.close() } catch (e) {}
        serialPort.value = null
      }
      return
    }

    serialConnected.value = true
    readSerial()
    await resetSerialDevice()
  } catch (error) {
    if (/No port selected/i.test(error?.message || '')) {
      addSerialLog('已取消选择端口')
      return
    }
    console.error('连接失败:', error)
    addSerialLog(`串口连接失败: ${error.message}`)
    if (serialPort.value) {
      try { await serialPort.value.close() } catch (e) {}
      serialPort.value = null
    }
  }
}

const resetSerialDevice = async () => {
  try {
    if (!serialPort.value) return
    addSerialLog('正在重启设备...')
    if (isNativeUsb.value) {
      // USB-JTAG/CDC 原生 USB：RTS=芯片复位，DTR=IO0
      // 保持 IO0=H，短复位一下让应用正常启动（而不是进下载模式）
      await serialPort.value.setSignals({ dataTerminalReady: false, requestToSend: true })
      await new Promise(r => setTimeout(r, 200))
      await serialPort.value.setSignals({ dataTerminalReady: false, requestToSend: false })
      await new Promise(r => setTimeout(r, 1000))
    } else {
      // 外部串口桥（CH340/CP210x/CH9102）：经典 EN+IO0 复位
      await serialPort.value.setSignals({ dataTerminalReady: false })
      await new Promise(r => setTimeout(r, 200))
      await serialPort.value.setSignals({ dataTerminalReady: true })
      await new Promise(r => setTimeout(r, 500))
      await serialPort.value.setSignals({ requestToSend: false })
      await new Promise(r => setTimeout(r, 200))
      await serialPort.value.setSignals({ requestToSend: true })
      await new Promise(r => setTimeout(r, 500))
      await serialPort.value.setSignals({ dataTerminalReady: false, requestToSend: false })
      await new Promise(r => setTimeout(r, 1000))
    }
    addSerialLog('设备重启成功')
  } catch (error) {
    console.error('重启失败:', error)
    addSerialLog('设备重启失败')
  }
}

const disconnectSerial = async () => {
  serialConnected.value = false
  await new Promise(resolve => {
    let attempts = 0
    const checkInterval = setInterval(() => {
      attempts++
      if (!reader.value || attempts > 10) {
        clearInterval(checkInterval)
        resolve()
      }
    }, 100)
  })
  if (reader.value) {
    try { await reader.value.cancel() } catch (error) {}
    try { reader.value.releaseLock() } catch (error) {}
    reader.value = null
  }
  if (serialPort.value) {
    try { await serialPort.value.close() } catch (error) {}
    serialPort.value = null
  }
  serialConnected.value = false
  isNativeUsb.value = false
  flushBatchLogs()
  addSerialLog('串口已断开')
}

const readSerial = async () => {
  try {
    if (!serialPort.value.readable) return
    const decoder = new TextDecoderStream()
    const readerStream = serialPort.value.readable.pipeThrough(decoder)
    reader.value = readerStream.getReader()
    while (serialConnected.value) {
      try {
        if (!serialConnected.value) break
        const readPromise = reader.value.read()
        const checkPromise = new Promise(resolve => {
          const checkInterval = setInterval(() => {
            if (!serialConnected.value) {
              clearInterval(checkInterval)
              resolve({ done: true })
            }
          }, 100)
        })
        const result = await Promise.race([readPromise, checkPromise])
        if (result.done) break
        if (result.value && !serialPaused.value) {
          processSerialData(result.value)
        }
      } catch (readError) {
        const lost = /device has been lost|Failed to read|disconnected|not open/i.test(readError?.message || '')
        if (lost) {
          serialConnected.value = false
          isNativeUsb.value = false
          flushBatchLogs()
          addSerialLog('设备已断开（USB 拔除/设备重启/串口被其他程序占用）')
          emit('toast', '设备连接已断开')
          if (reader.value) {
            try { await reader.value.cancel() } catch (e) {}
            try { reader.value.releaseLock() } catch (e) {}
            reader.value = null
          }
          if (serialPort.value) {
            try { await serialPort.value.close() } catch (e) {}
            serialPort.value = null
          }
          break
        }
        console.error('读取错误:', readError)
        if (!serialConnected.value) break
        await new Promise(resolve => setTimeout(resolve, 100))
      }
    }
  } catch (error) {
    console.error('读取失败:', error)
    addSerialLog('串口读取失败')
  } finally {
    if (reader.value) {
      try { await reader.value.cancel() } catch (e) {}
      try { reader.value.releaseLock() } catch (e) {}
      reader.value = null
    }
  }
}

const processSerialData = (data) => {
  const cleanedData = data
    .replace(/[\x00-\x08\x0B\x0C\x0E-\x1F\x7F-\x9F]/g, '')
    .replace(/[\uFFFD]/g, '?')
    .replace(/\r/g, '')
  if (!cleanedData) return
  batchLogs.value += cleanedData
  flushBatchLogs()
}

const flushBatchLogs = () => {
  if (!batchLogs.value) return
  partialLog.value += batchLogs.value
  const lines = partialLog.value.split('\n')
  batchLogs.value = ''
  const newLines = []
  for (let i = 0; i < lines.length - 1; i++) {
    const line = lines[i].trim()
    if (line) newLines.push(line)
  }
  partialLog.value = lines[lines.length - 1]
  if (newLines.length > 0) {
    serialLogs.value.push(...newLines)
    if (serialLogs.value.length > 1000) serialLogs.value = serialLogs.value.slice(-1000)
    scrollToBottom(serialTerminalRef)
  }
}

const sendSerialData = async () => {
  if (!sendData.value || !serialPort.value) return
  try {
    const encoder = new TextEncoder()
    const writer = serialPort.value.writable.getWriter()
    await writer.write(encoder.encode(sendData.value + '\r\n'))
    await writer.releaseLock()
    addSerialLog(`> ${sendData.value}`)
    sendData.value = ''
  } catch (error) {
    console.error('发送失败:', error)
    addSerialLog('数据发送失败')
  }
}

const togglePause = () => {
  serialPaused.value = !serialPaused.value
  addSerialLog(serialPaused.value ? '日志已暂停' : '日志已恢复')
}

const clearSerialLogs = () => {
  serialLogs.value = []
  partialLog.value = ''
  addSerialLog('日志已清除')
}

const copyLogs = () => {
  navigator.clipboard.writeText(serialLogs.value.join('\n'))
    .then(() => emit('toast', '日志已复制到剪贴板'))
    .catch(() => emit('toast', '复制失败'))
}

// ==================== 滚动 ====================
function scrollToBottom(refObj) {
  nextTick(() => {
    setTimeout(() => {
      if (refObj.value) refObj.value.scrollTop = refObj.value.scrollHeight
    }, 10)
  })
}

function onKeyDown(e) {
  if (e.ctrlKey && e.key === 'l') {
    e.preventDefault()
    clearSerialLogs()
  }
}

onMounted(() => {
  if (!serialSupported) return
  addFlashLog('欢迎使用 ESP32 固件烧录工具')
  addFlashLog('1. 连接设备 → 2. 选择 .bin 固件 → 3. 开始烧录')
  addSerialLog('欢迎使用 ESP32 串口调试工具')
  addSerialLog('选择波特率后点击"连接设备"即可查看日志')
  window.addEventListener('keydown', onKeyDown)
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKeyDown)
  if (flashResetTimer) clearTimeout(flashResetTimer)
  if (serialConnected.value) disconnectSerial()
  if (flashConnected.value) disconnectFlashDevice()
})
</script>

<style scoped>
.tool-view { padding: 0 0 56px; }

/* 分段切换 */
.seg {
  display: inline-flex;
  gap: 4px;
  padding: 5px;
  border-radius: var(--radius-md);
  background: rgba(255, 255, 255, 0.45);
  border: 1px solid var(--glass-border);
  box-shadow: var(--shadow-xs), var(--glass-hi);
  margin-bottom: 20px;
}
.seg-item {
  display: flex;
  align-items: center;
  gap: 6px;
  border: none;
  background: transparent;
  padding: 8px 18px;
  font-size: 13px;
  font-weight: 600;
  color: var(--text-sub);
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: all 0.3s var(--ease);
}
.seg-ico { font-size: 14px; display: inline-flex; align-items: center; }
.seg-item:hover { color: var(--text-main); }
.seg-item.active {
  color: #fff;
  background: var(--grad-mint);
  box-shadow: 0 6px 16px rgba(16, 185, 129, 0.28);
}

.tool-body { display: flex; flex-direction: column; gap: 20px; }

/* 面板卡片 */
.panel {
  padding: 20px 22px;
  border-radius: var(--radius-lg);
  border: 1px solid var(--glass-border);
  background: var(--grad-panel);
  backdrop-filter: var(--glass-blur);
  -webkit-backdrop-filter: var(--glass-blur);
  box-shadow: var(--shadow), var(--glass-hi);
}
.panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 16px;
}
.panel-compact {
  display: flex;
  flex-wrap: nowrap;
  align-items: center;
  gap: 8px;
  min-height: 80px;
  padding: 0 16px;
}
.panel-compact .panel-head {
  margin-bottom: 0;
  flex-shrink: 0;
  gap: 8px;
}
.panel-compact .panel-title {
  font-size: 13px;
  white-space: nowrap;
}
.panel-compact .config-grid {
  flex: 1;
  min-width: 0;
  flex-wrap: nowrap;
  align-items: center;
  gap: 8px;
  margin-bottom: 0;
}
.panel-compact .field { flex-direction: row; align-items: center; gap: 6px; min-width: 0; flex-shrink: 1; }
.panel-compact .field-grow { flex: 1; min-width: 0; }
.panel-compact .field-label {
  font-size: 12px;
  line-height: 1.2;
  white-space: nowrap;
}
.panel-compact .select-sm { width: 88px; min-width: 0; }
.panel-compact .input-sm {
  padding: 4px 10px;
  font-size: 12px;
}
.panel-compact .send-box { min-width: 0; }
.panel-compact .btns-row {
  gap: 8px;
  flex-shrink: 0;
  margin-left: auto;
}
.panel-compact .btns-row .btn-mint,
.panel-compact .btns-row .btn-ghost {
  padding: 5px 12px;
  font-size: 12px;
}
.panel-compact .btn-flash { padding: 5px 16px; font-size: 12px; }
.panel-compact .btn-sm {
  padding: 4px 10px;
  font-size: 11px;
}
.panel-compact .status-pill {
  padding: 2px 8px;
  font-size: 11px;
}
.panel-compact .firmware-hint {
  margin-top: 0;
  font-size: 11px;
}
.panel-title { font-size: 15px; font-weight: 700; }
.head-right { display: flex; align-items: center; gap: 8px; }
.log-count { font-size: 12px; color: var(--text-dim); }

/* 圆形进度环 */
.progress-panel { min-height: 320px; }
.progress-body {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 14px;
  padding: 6px 0 10px;
}
.ring-wrap {
  position: relative;
  width: 168px;
  height: 168px;
}
.ring {
  width: 100%;
  height: 100%;
  transform: rotate(-90deg);
}
.ring-bg {
  fill: none;
  stroke: rgba(15, 23, 42, 0.08);
  stroke-width: 10;
}
.ring-fg {
  fill: none;
  stroke: var(--mint);
  stroke-width: 10;
  stroke-linecap: round;
  transition: stroke-dashoffset 0.35s var(--ease);
  filter: drop-shadow(0 0 6px rgba(16, 185, 129, 0.45));
}
.ring-fg.done {
  stroke: var(--mint);
}
.ring-fg.error {
  stroke: var(--danger);
  filter: drop-shadow(0 0 6px rgba(239, 68, 68, 0.45));
}
.ring-wrap.indeterminate .ring-fg {
  stroke-dasharray: 100 227;
  animation: ringSpin 1.2s linear infinite;
  transform-origin: center;
  transform-box: fill-box;
}
@keyframes ringSpin {
  to { transform: rotate(360deg); }
}
.ring-center {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 2px;
}
.ring-pct {
  font-size: 34px;
  font-weight: 800;
  color: var(--text-main);
  line-height: 1;
}
.ring-sub {
  font-size: 12px;
  color: var(--text-sub);
}
.stage-text {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  font-weight: 600;
  color: var(--text-main);
}
.stage-dot {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  background: #9ca3af;
}
.stage-dot.busy {
  background: #f59e0b;
  animation: dotBreathe 1.2s ease-in-out infinite;
}
.stage-dot.flash {
  background: var(--mint);
  animation: dotBreathe 1.2s ease-in-out infinite;
}
.stage-dot.done {
  background: var(--mint);
}
.stage-dot.error {
  background: var(--danger);
}
.last-log {
  display: flex;
  align-items: center;
  gap: 8px;
  max-width: 100%;
  font-size: 12px;
  color: var(--text-sub);
  background: rgba(15, 23, 42, 0.04);
  border: 1px solid var(--glass-border);
  border-radius: var(--radius-sm);
  padding: 6px 12px;
}
.last-log-label {
  flex-shrink: 0;
  font-weight: 700;
  color: var(--mint-deep);
}
.last-log span:last-child {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 状态胶囊 */
.status-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-dim);
  padding: 5px 12px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.5);
  border: 1px solid var(--glass-border);
}
.status-pill .pill-dot {
  width: 8px; height: 8px;
  border-radius: 50%;
  background: #9ca3af;
}
.status-pill.on { color: var(--mint-deep); }
.status-pill.on .pill-dot {
  background: var(--mint);
  box-shadow: 0 0 0 0 rgba(16, 185, 129, 0);
  animation: dotBreathe 2s ease-in-out infinite;
}

/* 配置项 */
.config-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
  align-items: flex-end;
  margin-bottom: 16px;
}
.field { display: flex; flex-direction: column; gap: 6px; }
.field-grow { flex: 1; min-width: 220px; }
.field-label { font-size: 12px; color: var(--text-sub); }
.select-sm { width: 110px; }
.input-sm { padding: 8px 12px; font-size: 13px; }

.btns-row { display: flex; flex-wrap: wrap; gap: 10px; }
.btn-flash { padding: 9px 24px; font-size: 14px; }
.btn-file {
  max-width: 220px;
  padding: 8px 14px;
  overflow: hidden;
}
.btn-file-label {
  display: inline-block;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  vertical-align: bottom;
}
.btn-danger {
  color: var(--danger);
  border-color: rgba(239, 68, 68, 0.3);
}
.btn-danger:hover {
  border-color: rgba(239, 68, 68, 0.5);
  color: var(--danger);
  background: var(--danger-soft);
  box-shadow: 0 4px 14px rgba(239, 68, 68, 0.12);
}
.btn-sm { padding: 5px 12px; font-size: 12px; }
.btn-mint.loading, .btn-ghost.loading { opacity: 0.6; pointer-events: none; }

.firmware-hint { margin-top: 12px; font-size: 12px; color: var(--text-sub); }

.send-box { display: flex; gap: 8px; }
.send-input { flex: 1; }

/* 终端 */
.terminal {
  height: calc(100vh - 300px);
  min-height: 420px;
  max-height: 800px;
  background: #0d1117;
  border-radius: var(--radius-md);
  overflow: hidden;
  font-family: 'Courier New', Courier, monospace;
  font-size: 13px;
  line-height: 1.6;
  border: 1px solid rgba(255, 255, 255, 0.06);
}
.terminal-content {
  height: 100%;
  padding: 14px 16px;
  overflow-y: auto;
}
.log-line { display: flex; margin-bottom: 4px; word-break: break-word; }
.log-time { color: #8b949e; margin-right: 10px; min-width: 80px; font-size: 12px; flex-shrink: 0; }
.log-content { flex: 1; min-width: 0; color: #7ee787; }
.log-success { color: #7ee787; font-weight: 500; }
.log-error { color: #f85149; font-weight: 500; }
.log-warning { color: #f2cc60; font-weight: 500; }
.log-info { color: #79c0ff; font-weight: 500; }
.log-send { color: #d2a8ff; font-weight: 500; }

/* 使用步骤 */
.tips-card {
  padding: 16px 20px;
  border-radius: var(--radius-md);
  background: var(--mint-softer);
  border: 1px dashed var(--mint-border);
}
.tips-title { font-size: 13px; font-weight: 700; color: var(--mint-deep); margin-bottom: 8px; }
.tips-list { margin-left: 18px; display: flex; flex-direction: column; gap: 6px; font-size: 13px; color: var(--text-sub); }

/* WebSerial 不支持提示 */
.warn-card {
  padding: 22px 24px;
  border-radius: var(--radius-lg);
  border: 1px solid rgba(245, 158, 11, 0.35);
  background: linear-gradient(155deg, rgba(255, 255, 255, 0.85), rgba(255, 255, 255, 0.55));
}
.warn-inner { display: flex; align-items: flex-start; gap: 14px; }
.warn-orb { font-size: 26px; }
.warn-title { font-size: 15px; font-weight: 700; color: #b45309; }
.warn-sub { margin-top: 6px; font-size: 13px; color: var(--text-sub); line-height: 1.7; }
.warn-sub b { color: var(--text-main); }

@media (max-width: 640px) {
  .tool-view { padding: 16px 0 40px; }
  .btns-row .btn-mint, .btns-row .btn-ghost { flex: 1; }
  .select-sm { width: 100%; }
  .panel-compact { min-height: 0; flex-wrap: wrap; padding: 10px 16px; }
  .panel-compact .panel-head { width: 100%; }
  .panel-compact .config-grid { flex-wrap: wrap; flex: none; width: 100%; }
  .panel-compact .field { width: 100%; }
  .panel-compact .field-grow { min-width: 0; }
  .panel-compact .select-sm { width: 110px; }
  .panel-compact .btns-row { margin-left: 0; width: 100%; }
}
</style>