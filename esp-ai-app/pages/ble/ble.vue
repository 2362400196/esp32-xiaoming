<template>
	<view class="page">
		<!-- 顶部栏 -->
		<view class="header">
			<view class="header-left" @click="goBack">
				<view class="back-icon">
					<view class="arrow-left"></view>
				</view>
			</view>
			<view class="header-center">
				<text class="title">蓝牙配网</text>
			</view>
			<view class="header-right">
				<text class="header-action" @click="toggleScan">{{ scanning ? '停止' : '扫描' }}</text>
			</view>
		</view>

		<!-- 扫描动画 -->
		<view class="scan-area">
			<view class="radar">
				<view class="radar-circle c1" :class="{ anim: scanning }"></view>
				<view class="radar-circle c2" :class="{ anim: scanning }"></view>
				<view class="radar-circle c3" :class="{ anim: scanning }"></view>
				<view class="radar-circle c4" :class="{ anim: scanning }"></view>
				<view class="radar-center">
					<view class="bluetooth-icon">
						<view class="ble-path p1"></view>
						<view class="ble-path p2"></view>
					</view>
				</view>
				<view class="radar-scan-line" :class="{ anim: scanning }"></view>
			</view>
			<text class="scan-tip">{{ scanTip }}</text>
		</view>

		<!-- 设备列表 -->
		<view class="device-section" v-if="devices.length > 0">
			<text class="section-title">发现的设备</text>
			<view class="device-list">
				<view v-for="device in devices" :key="device.deviceId"
					class="device-item"
					:class="{ selected: selectedDevice && selectedDevice.deviceId === device.deviceId }"
					hover-class="device-item-pressed" @click="selectDevice(device)">
					<view class="device-info">
						<text class="device-name">{{ device.name }}</text>
						<text class="device-id">{{ device.deviceId }}</text>
						<text class="device-rssi" v-if="device.RSSI">信号 {{ device.RSSI }} dBm</text>
					</view>
					<view class="device-signal">
						<view class="signal-bars" :class="'strength-' + signalLevel(device.RSSI)">
							<view class="signal-bar b1"></view>
							<view class="signal-bar b2"></view>
							<view class="signal-bar b3"></view>
							<view class="signal-bar b4"></view>
						</view>
					</view>
				</view>
			</view>
		</view>

		<!-- ========== 配置表单 ========== -->
		<view v-if="selectedDevice">

			<!-- ① 网络配置 -->
			<view class="cfg-section">
				<text class="section-title">网络配置</text>
				<view class="cfg-card">
					<view class="cfg-row">
						<text class="cfg-label">WiFi 账号 *</text>
						<input class="cfg-input" type="text" placeholder="请输入 WiFi 名称" v-model="wifiSsid" />
					</view>
					<view class="cfg-row">
						<text class="cfg-label">WiFi 密码 *</text>
						<input class="cfg-input" :type="showPwd ? 'text' : 'password'" placeholder="请输入 WiFi 密码" v-model="wifiPassword" />
						<view class="btn-eye" @click="showPwd = !showPwd">
							<view class="eye-icon" :class="{ open: showPwd }"></view>
						</view>
					</view>
				</view>
			</view>

			<!-- ② 唤醒/对话方式 -->
			<view class="cfg-section">
				<text class="section-title">唤醒/对话方式</text>
				<view class="cfg-card">
					<view class="cfg-select-row">
						<text class="cfg-label-sm">唤醒方式 *</text>
						<picker class="cfg-picker" :value="wakeupTypeIndex" :range="wakeupTypeList" @change="onWakeupChange">
							<text class="cfg-picker-text">{{ wakeupTypeList[wakeupTypeIndex] }}</text>
							<view class="picker-arrow"></view>
						</picker>
					</view>
				</view>
			</view>

			<!-- ③ 服务配置 -->
			<view class="cfg-section">
				<text class="section-title">服务配置</text>
				<view class="cfg-card">
					<view class="cfg-radio-row">
						<view class="cfg-radio" :class="{ active: configType === 'official' }" @click="configType = 'official'">
							<view class="radio-dot">
								<view class="radio-inner" v-if="configType === 'official'"></view>
							</view>
							<text class="radio-label">使用开放平台服务</text>
						</view>
						<view class="cfg-radio" :class="{ active: configType === 'custom' }" @click="switchToCustom">
							<view class="radio-dot">
								<view class="radio-inner" v-if="configType === 'custom'"></view>
							</view>
							<text class="radio-label">使用自定义服务</text>
						</view>
					</view>

					<!-- 开放平台 -->
					<template v-if="configType === 'official'">
						<view class="cfg-row">
							<text class="cfg-label">开放平台密钥 *</text>
							<input class="cfg-input" type="text" placeholder="请输入开放平台 API Key" v-model="officialApiKey" />
						</view>
						<view class="cfg-desc">在 ESP-AI 开放平台（dev.espai.fun）创建超体后获取，设备连接官方服务需鉴权</view>
					</template>

					<!-- 自定义服务 -->
					<template v-if="configType === 'custom'">
						<view class="cfg-row">
							<text class="cfg-label">服务协议 *</text>
							<picker class="cfg-picker" :value="customProtocolIndex" :range="['http', 'https']" @change="onProtocolChange">
								<text class="cfg-picker-text">{{ ['http', 'https'][customProtocolIndex] }}</text>
								<view class="picker-arrow"></view>
							</picker>
						</view>
						<view class="cfg-row">
							<text class="cfg-label">服务地址 *</text>
							<input class="cfg-input" type="text" placeholder="IP 或域名" v-model="customHost" />
						</view>
						<view class="cfg-row">
							<text class="cfg-label">服务端口 *</text>
							<input class="cfg-input" type="text" inputmode="numeric" placeholder="如 8088" v-model="customPort" />
						</view>
						<view class="cfg-row">
						<text class="cfg-label">请求参数</text>
						<input class="cfg-input" type="text" placeholder="可选，如 api_key=xxx" v-model="customParams" />
					</view>
					</template>
				</view>
			</view>

			<!-- ④ 电量检测 -->
			<view class="cfg-section">
				<text class="section-title">电量检测配置 <text style="font-size:20rpx;font-weight:400;color:#b0b0b0"> 高级 [选填]</text></text>
				<view class="cfg-card">
					<view class="cfg-switch-row">
						<text class="cfg-label">启用电量检测</text>
						<view class="switch" :class="{ on: kwhEnable }" @click="kwhEnable = !kwhEnable">
							<view class="switch-knob"></view>
						</view>
					</view>
					<view class="cfg-desc">如果开发板没有电压检测模块，请关闭此功能</view>
				</view>
			</view>

			<!-- ⑤ 音量控制 -->
			<view class="cfg-section">
				<text class="section-title">音量控制配置 <text style="font-size:20rpx;font-weight:400;color:#b0b0b0"> 高级 [选填]</text></text>
				<view class="cfg-card">
					<view class="cfg-switch-row">
						<text class="cfg-label">启用音量控制</text>
						<view class="switch" :class="{ on: volumeEnable }" @click="volumeEnable = !volumeEnable">
							<view class="switch-knob"></view>
						</view>
					</view>
					<view class="cfg-row">
						<text class="cfg-label">电位器输入引脚</text>
						<input class="cfg-input pin-input" type="text" inputmode="numeric" placeholder="默认 7" v-model="volumePin" />
					</view>
					<view class="cfg-desc">使用 10K 电位器，没有插电位器不要启用</view>
				</view>
			</view>

			<!-- ⑥ 指示灯 -->
			<view class="cfg-section">
				<text class="section-title">指示灯配置 <text style="font-size:20rpx;font-weight:400;color:#b0b0b0"> 高级 [选填]</text></text>
				<view class="cfg-card">
					<view class="cfg-row">
						<text class="cfg-label">WS2812 引脚</text>
						<input class="cfg-input pin-input" type="text" inputmode="numeric" placeholder="默认 18" v-model="lightsData" />
					</view>
					<view class="cfg-desc">普通 ESP32S3 开发板请设置为 48</view>
				</view>
			</view>

			<!-- ⑦ OLED 屏幕 -->
			<view class="cfg-section">
				<text class="section-title">OLED 屏幕配置 <text style="font-size:20rpx;font-weight:400;color:#b0b0b0"> 高级 [选填]</text></text>
				<view class="cfg-card">
					<view class="cfg-row">
						<text class="cfg-label">屏幕类型</text>
						<picker class="cfg-picker" :value="oledTypeIndex" :range="['0.96寸（方形）', '0.91寸（条形）']" @change="onOledTypeChange">
							<text class="cfg-picker-text">{{ ['0.96寸（方形）', '0.91寸（条形）'][oledTypeIndex] }}</text>
							<view class="picker-arrow"></view>
						</picker>
					</view>
					<view class="cfg-row">
						<text class="cfg-label">SCK/SCL 引脚</text>
						<input class="cfg-input pin-input" type="text" inputmode="numeric" placeholder="默认 38" v-model="oledSck" />
					</view>
					<view class="cfg-row">
						<text class="cfg-label">SDA 引脚</text>
						<input class="cfg-input pin-input" type="text" inputmode="numeric" placeholder="默认 39" v-model="oledSda" />
					</view>
					<view class="cfg-desc">屏幕正极一定要使用 3.3v</view>
				</view>
			</view>

			<!-- ⑧ 麦克风引脚 -->
			<view class="cfg-section">
				<text class="section-title">麦克风引脚配置 <text style="font-size:20rpx;font-weight:400;color:#b0b0b0"> 高级 [选填]</text></text>
				<view class="cfg-card">
					<view class="cfg-row">
						<text class="cfg-label">SCK</text>
						<input class="cfg-input pin-input" type="text" inputmode="numeric" placeholder="默认 4" v-model="micBck" />
					</view>
					<view class="cfg-row">
						<text class="cfg-label">WS</text>
						<input class="cfg-input pin-input" type="text" inputmode="numeric" placeholder="默认 5" v-model="micWs" />
					</view>
					<view class="cfg-row">
						<text class="cfg-label">SD</text>
						<input class="cfg-input pin-input" type="text" inputmode="numeric" placeholder="默认 6" v-model="micData" />
					</view>
					<view class="cfg-desc">除非你知道你在做什么，否则不要动这里的参数</view>
				</view>
			</view>

			<!-- ⑨ 扬声器引脚 -->
			<view class="cfg-section">
				<text class="section-title">扬声器引脚配置 <text style="font-size:20rpx;font-weight:400;color:#b0b0b0"> 高级 [选填]</text></text>
				<view class="cfg-card">
					<view class="cfg-row">
						<text class="cfg-label">DIN</text>
						<input class="cfg-input pin-input" type="text" inputmode="numeric" placeholder="默认 15" v-model="speakerData" />
					</view>
					<view class="cfg-row">
						<text class="cfg-label">BCLK</text>
						<input class="cfg-input pin-input" type="text" inputmode="numeric" placeholder="默认 16" v-model="speakerBck" />
					</view>
					<view class="cfg-row">
						<text class="cfg-label">LRC</text>
						<input class="cfg-input pin-input" type="text" inputmode="numeric" placeholder="默认 17" v-model="speakerWs" />
					</view>
					<view class="cfg-desc">除非你知道你在做什么，否则不要动这里的参数</view>
				</view>
			</view>

			<!-- 提交 -->
			<view class="btn-area">
				<view class="btn-send" hover-class="btn-send-pressed" @click="sendWifiConfig">
					<text class="btn-send-text">{{ connecting ? '配网中...' : '保存' }}</text>
				</view>
			</view>

		</view>

		<!-- 配网状态提示 -->
		<view class="status-toast" :class="{ show: statusMsg }">
			<view class="status-dot" :class="statusType"></view>
			<text class="status-text">{{ statusMsg }}</text>
		</view>
	</view>
</template>

<script setup>
import { ref, computed, onUnmounted } from 'vue'

// ===== 页面状态 =====
const scanning = ref(false)
const scanTip = ref('点击右上角「扫描」开始搜索蓝牙设备')
const devices = ref([])
const selectedDevice = ref(null)
const connecting = ref(false)
const statusMsg = ref('')
const statusType = ref('success')
const showPwd = ref(false)

let showStatusTimer = null
let discoveredDeviceIds = new Set()

// ===== ① 网络配置 =====
const wifiSsid = ref('')
const wifiPassword = ref('')

// ===== ② 唤醒方式 =====
const wakeupTypeList = [
	'天问唤醒',
	'天问唤醒+BOOT唤醒',
	'按钮高电平唤醒(三角按钮)',
	'按钮低电平唤醒(三角按钮)',
	'BOOT按钮唤醒',
	'按住对话(BOOT按钮)',
	'按住对话(三角按钮)'
]
const wakeupTypeValues = ['asrpro', 'asrpro_boot', 'pin_high', 'pin_low', 'boot', 'boot_listen', 'pin_high_listen']
const wakeupTypeIndex = ref(4) // 默认 boot

const onWakeupChange = (e) => { wakeupTypeIndex.value = e.detail.value }

// ===== ③ 服务配置 =====
const configType = ref('official') // 'official' | 'custom'
const officialApiKey = ref('')     // 开放平台 API Key（设备连接官方服务鉴权用）
const customProtocolIndex = ref(0)
const customHost = ref('')
const customPort = ref('8088')
const customParams = ref('')

const onProtocolChange = (e) => { customProtocolIndex.value = e.detail.value }
const switchToCustom = () => {
	configType.value = 'custom'
	if (!customHost.value) customHost.value = ''
}

// ===== ④ 电量检测 =====
const kwhEnable = ref(true)

// ===== ⑤ 音量控制 =====
const volumeEnable = ref(false)
const volumePin = ref('7')

// ===== ⑥ 指示灯 =====
const lightsData = ref('18')

// ===== ⑦ OLED =====
const oledTypeIndex = ref(0) // 0: 0.96寸
const oledSck = ref('38')
const oledSda = ref('39')

const onOledTypeChange = (e) => { oledTypeIndex.value = e.detail.value }

// ===== ⑧ 麦克风 =====
const micBck = ref('4')
const micWs = ref('5')
const micData = ref('6')

// ===== ⑨ 扬声器 =====
const speakerData = ref('15')
const speakerBck = ref('16')
const speakerWs = ref('17')

// ===== 工具 =====
const goBack = () => { stopScan(); uni.navigateBack() }

const showStatus = (msg, type = 'success') => {
	clearTimeout(showStatusTimer)
	statusMsg.value = msg; statusType.value = type
	showStatusTimer = setTimeout(() => { statusMsg.value = '' }, 3000)
}

const signalLevel = (rssi) => {
	if (rssi == null) return 0
	if (rssi > -50) return 4
	if (rssi > -65) return 3
	if (rssi > -75) return 2
	if (rssi > -85) return 1
	return 0
}

// ===== 蓝牙扫描 =====
const toggleScan = () => { scanning.value ? stopScan() : startScan() }

const startScan = () => {
	devices.value = []; selectedDevice.value = null; connecting.value = false
	discoveredDeviceIds = new Set()

	uni.openBluetoothAdapter({
		success: () => {
			uni.startBluetoothDevicesDiscovery({
				allowDuplicatesKey: false,
				success: () => {
					scanning.value = true; scanTip.value = '正在扫描蓝牙设备...'
					showStatus('开始扫描', 'success')
				},
				fail: (err) => { showStatus('扫描启动失败: ' + (err.errMsg || '未知错误'), 'error') }
			})
			uni.onBluetoothDeviceFound((res) => {
				const newDevices = res.devices || []
				for (const dev of newDevices) {
					const name = (dev.name || dev.localName || '').trim()
					if (!name) continue
					if (!name.toUpperCase().includes('ESP') && !name.toUpperCase().includes('AI')) continue
					if (discoveredDeviceIds.has(dev.deviceId)) {
						const idx = devices.value.findIndex(d => d.deviceId === dev.deviceId)
						if (idx >= 0) devices.value[idx] = { ...devices.value[idx], ...dev }
					} else {
						discoveredDeviceIds.add(dev.deviceId)
						devices.value.push(dev)
					}
				}
				if (devices.value.length > 0) scanTip.value = '发现 ' + devices.value.length + ' 个设备'
			})
		},
		fail: (err) => { showStatus('请打开手机蓝牙: ' + (err.errMsg || ''), 'error') }
	})
}

const stopScan = () => {
	scanning.value = false
	uni.stopBluetoothDevicesDiscovery({})
	scanTip.value = devices.value.length > 0 ? '发现 ' + devices.value.length + ' 个设备' : '扫描已停止'
}

const selectDevice = (device) => { selectedDevice.value = device }

// ===== BLE 配网 (ESP-AI 协议) =====
const EOT_MARKER = '--END--'
// 手动实现 str → ArrayBuffer（兼容 uni-app 安卓 WebView，纯 ASCII 用单字节）
const str2ab = (str) => {
	const buf = new ArrayBuffer(str.length)
	const view = new Uint8Array(buf)
	for (let i = 0; i < str.length; i++) view[i] = str.charCodeAt(i) & 0xFF
	return buf
}
const delay = (ms) => new Promise(r => setTimeout(r, ms))

const bleWrite = (deviceId, serviceId, characteristicId, value) =>
	new Promise((resolve, reject) => {
		uni.writeBLECharacteristicValue({ deviceId, serviceId, characteristicId, value, success: resolve, fail: reject })
	})

const toast = (msg) => { uni.showToast({ title: msg, icon: 'none', duration: 2500 }) }

const sendWifiConfig = async () => {
	try {
		// === 校验 ===
		if (!selectedDevice.value) { toast('请先选择一个设备'); return }
		if (!wifiSsid.value.trim()) { toast('请输入 WiFi 名称'); return }
		if (!wifiPassword.value.trim()) { toast('请输入 WiFi 密码'); return }

		connecting.value = true
		stopScan()
		const deviceId = selectedDevice.value.deviceId

		// === 先断开已有连接 ===
		try {
			await new Promise((resolve) => {
				uni.closeBLEConnection({ deviceId, success: resolve, fail: resolve })
			})
		} catch(e) {}
		await delay(300)

		// === 1. 连接 ===
		uni.showLoading({ title: '连接设备...', mask: true })
		try {
			await new Promise((resolve, reject) => {
				uni.createBLEConnection({ deviceId, timeout: 10000, success: resolve, fail: reject })
			})
		} catch (e) {
			uni.hideLoading()
			connecting.value = false
			toast('连接失败: ' + (e.errMsg || '超时'))
			return
		}
		await delay(500)

		// === 2. 获取服务 ===
		uni.showLoading({ title: '获取服务...', mask: true })
		let services, targetService
		try {
			const res = await new Promise((resolve, reject) => {
				uni.getBLEDeviceServices({ deviceId, success: resolve, fail: reject })
			})
			services = res.services || []
			if (services.length === 0) throw new Error('无可用服务')
			// 优先查找 UUID 包含 BAAD 的服务
			targetService = services.find(s => s.uuid.toUpperCase().includes('BAAD'))
			if (!targetService) targetService = services[0]
		} catch (e) {
			uni.hideLoading()
			connecting.value = false
			toast('获取服务失败')
			return
		}

		// === 3. 获取特征值 ===
		uni.showLoading({ title: '获取特征值...', mask: true })
		let writeChar
		try {
			const res = await new Promise((resolve, reject) => {
				uni.getBLEDeviceCharacteristics({ deviceId, serviceId: targetService.uuid, success: resolve, fail: reject })
			})
			const chars = res.characteristics || []
			// 优先查找 UUID 包含 F00D 且可写的特征值，否则找可写的，否则找包含 F00D 的，否则取第一个
			writeChar = chars.find(c => c.uuid.toUpperCase().includes('F00D') && (c.properties.write || c.properties.writeNoResponse))
				|| chars.find(c => c.properties.write || c.properties.writeNoResponse)
				|| chars.find(c => c.uuid.toUpperCase().includes('F00D'))
				|| chars[0]
		} catch (e) {
			uni.hideLoading()
			connecting.value = false
			toast('获取特征值失败')
			return
		}

		// === 4. 构建数据 ===
		uni.showLoading({ title: '发送配网数据...', mask: true })
		const payload = {
			wifi_name: wifiSsid.value.trim(),
			wifi_pwd: wifiPassword.value.trim(),
			ext7: wakeupTypeValues[wakeupTypeIndex.value],
			kwh_enable: kwhEnable.value ? '1' : '0',
			volume_enable: volumeEnable.value ? '1' : '0',
			volume_pin: volumePin.value.trim() || '7',
			mic_bck: micBck.value.trim() || '4',
			mic_ws: micWs.value.trim() || '5',
			mic_data: micData.value.trim() || '6',
			speaker_bck: speakerBck.value.trim() || '16',
			speaker_ws: speakerWs.value.trim() || '17',
			speaker_data: speakerData.value.trim() || '15',
			lights_data: lightsData.value.trim() || '18',
			oled_type: oledTypeIndex.value === 0 ? '096' : '091',
			oled_sck: oledSck.value.trim() || '38',
			oled_sda: oledSda.value.trim() || '39'
		}
		if (configType.value === 'official') {
			const key = officialApiKey.value.trim()
			if (!key) { uni.hideLoading(); connecting.value = false; toast('请输入开放平台密钥'); return }
			payload.api_key = key
			payload.ext1 = key // 兼容以 ext1 读取的固件
		} else if (configType.value === 'custom') {
			payload.ext4 = ['http', 'https'][customProtocolIndex.value]
			payload.ext5 = customHost.value.trim()
			payload.ext6 = customPort.value.trim() || '8088'
			payload.diyServerParams = customParams.value.trim() || ''
		}

		const reqData = str2ab(encodeURIComponent(JSON.stringify(payload)))

		// === 5. BLE 分块写入（无前缀，直接发原始 URL 编码数据） ===
		const chunkSize = 20
		const totalLen = reqData.byteLength
		const totalChunks = Math.ceil(totalLen / chunkSize)

		for (let i = 0; i < totalChunks; i++) {
			const start = i * chunkSize
			const end = Math.min(start + chunkSize, totalLen)
			const chunk = reqData.slice(start, end)

			await bleWrite(deviceId, targetService.uuid, writeChar.uuid, chunk)
			await delay(50)
		}

		await delay(100)
		await bleWrite(deviceId, targetService.uuid, writeChar.uuid, str2ab(EOT_MARKER))

		// === 完成 ===
		// 新架构：设备不再需要 api_key，配网只发 WiFi 凭据
		uni.hideLoading()
		connecting.value = false
		uni.showToast({ title: '配网成功！设备连接中...', icon: 'success', duration: 3000 })
		setTimeout(() => { uni.closeBLEConnection({ deviceId }) }, 2000)
	} catch (e) {
		uni.hideLoading()
		connecting.value = false
		toast('配网出错: ' + (e.message || '未知错误'))
	}
}

onUnmounted(() => { stopScan(); try { uni.closeBluetoothAdapter({}) } catch(e) {} })
</script>

<style>
.page {
	min-height: 100vh;
	background-color: #f5f5f5;
	padding-bottom: 40rpx;
}

/* 顶部栏 */
.header {
	display: flex;
	flex-direction: row;
	align-items: center;
	justify-content: space-between;
	padding: 60rpx 32rpx 24rpx;
	background-color: #ffffff;
}

.header-left {
	width: 80rpx;
}

.back-icon {
	width: 64rpx;
	height: 64rpx;
	border-radius: 20rpx;
	background-color: #f5f5f5;
	display: flex;
	justify-content: center;
	align-items: center;
}

.arrow-left {
	width: 16rpx;
	height: 16rpx;
	border-left: 4rpx solid #333333;
	border-bottom: 4rpx solid #333333;
	transform: rotate(45deg);
	margin-left: 6rpx;
}

.title {
	font-size: 32rpx;
	font-weight: 700;
	color: #1a1a1a;
}

.header-action {
	font-size: 26rpx;
	font-weight: 500;
	color: #34d399;
	padding: 12rpx 24rpx;
	background-color: rgba(52, 211, 153, 0.08);
	border-radius: 16rpx;
}

/* 扫描动画 */
.scan-area {
	display: flex;
	flex-direction: column;
	align-items: center;
	padding: 60rpx 0 40rpx;
	background-color: #ffffff;
	margin-bottom: 20rpx;
}

.radar {
	position: relative;
	width: 280rpx;
	height: 280rpx;
	display: flex;
	justify-content: center;
	align-items: center;
}

.radar-circle {
	position: absolute;
	border-radius: 50%;
	border: 2rpx solid rgba(52, 211, 153, 0.12);
	background-color: rgba(52, 211, 153, 0.02);
}

.radar-circle.c1 { width: 280rpx; height: 280rpx; }
.radar-circle.c2 { width: 210rpx; height: 210rpx; }
.radar-circle.c3 { width: 140rpx; height: 140rpx; }
.radar-circle.c4 { width: 70rpx; height: 70rpx; }

.radar-circle.anim {
	animation: radarPulse 2s ease-out infinite;
}

.radar-circle.c1.anim { animation-delay: 0s; }
.radar-circle.c2.anim { animation-delay: 0.4s; }
.radar-circle.c3.anim { animation-delay: 0.8s; }
.radar-circle.c4.anim { animation-delay: 1.2s; }

@keyframes radarPulse {
	0% {
		transform: scale(0.3);
		opacity: 1;
		border-color: rgba(52, 211, 153, 0.35);
		background-color: rgba(52, 211, 153, 0.06);
	}
	100% {
		transform: scale(1);
		opacity: 0;
		border-color: rgba(52, 211, 153, 0);
		background-color: rgba(52, 211, 153, 0);
	}
}

.radar-center {
	position: relative;
	z-index: 2;
	width: 80rpx;
	height: 80rpx;
	background-color: #34d399;
	border-radius: 50%;
	display: flex;
	justify-content: center;
	align-items: center;
	box-shadow: 0 0 40rpx rgba(52, 211, 153, 0.4);
}

.bluetooth-icon {
	position: relative;
	width: 28rpx;
	height: 38rpx;
	display: flex;
	justify-content: center;
	align-items: center;
}

.ble-path {
	position: absolute;
	width: 0;
	height: 0;
}

.ble-path.p1 {
	border-top: 19rpx solid #ffffff;
	border-left: 8rpx solid transparent;
	border-right: 8rpx solid transparent;
	top: 0;
	left: 50%;
	transform: translateX(-50%);
}

.ble-path.p2 {
	border-bottom: 19rpx solid #ffffff;
	border-left: 8rpx solid transparent;
	border-right: 8rpx solid transparent;
	bottom: 0;
	left: 50%;
	transform: translateX(-50%);
}

.radar-scan-line {
	position: absolute;
	top: 50%;
	left: 50%;
	width: 2rpx;
	height: 90rpx;
	background: linear-gradient(to top, rgba(52, 211, 153, 0.8), rgba(52, 211, 153, 0));
	transform-origin: bottom center;
	transform: translateX(-50%) rotate(0deg);
	opacity: 0;
}

.radar-scan-line.anim {
	opacity: 1;
	animation: scanRotate 2s linear infinite;
}

@keyframes scanRotate {
	from { transform: translateX(-50%) rotate(0deg); }
	to { transform: translateX(-50%) rotate(360deg); }
}

.scan-tip {
	margin-top: 32rpx;
	font-size: 26rpx;
	color: #999999;
}

/* 设备列表 */
.device-section {
	margin: 0 24rpx 24rpx;
}

.section-title {
	font-size: 26rpx;
	font-weight: 600;
	color: #666666;
	margin-bottom: 16rpx;
	padding: 0 8rpx;
}

.device-list {
	display: flex;
	flex-direction: column;
	gap: 12rpx;
}

.device-item {
	background-color: #ffffff;
	border-radius: 20rpx;
	padding: 24rpx 28rpx;
	display: flex;
	flex-direction: row;
	justify-content: space-between;
	align-items: center;
	border: 2rpx solid transparent;
}

.device-item.selected {
	border-color: #34d399;
	background-color: rgba(52, 211, 153, 0.04);
}

.device-item-pressed {
	transform: scale(0.98);
	background-color: #f8f8f8;
}

.device-info {
	display: flex;
	flex-direction: column;
	flex: 1;
}

.device-name {
	font-size: 28rpx;
	font-weight: 600;
	color: #1a1a1a;
}

.device-id {
	font-size: 20rpx;
	color: #b0b0b0;
	margin-top: 4rpx;
}

.device-rssi {
	font-size: 20rpx;
	color: #34d399;
	margin-top: 4rpx;
}

.device-signal {
	margin-left: 16rpx;
}

.signal-bars {
	display: flex;
	flex-direction: row;
	align-items: flex-end;
	gap: 4rpx;
	height: 32rpx;
}

.signal-bar {
	width: 8rpx;
	border-radius: 2rpx;
	background-color: #e0e0e0;
}

.signal-bar.b1 { height: 10rpx; }
.signal-bar.b2 { height: 18rpx; }
.signal-bar.b3 { height: 25rpx; }
.signal-bar.b4 { height: 32rpx; }

.strength-1 .b1 { background-color: #34d399; }
.strength-2 .b1, .strength-2 .b2 { background-color: #34d399; }
.strength-3 .b1, .strength-3 .b2, .strength-3 .b3 { background-color: #34d399; }
.strength-4 .signal-bar { background-color: #34d399; }

/* ====== 配置卡片 (cfg-*) ====== */
.cfg-section {
	margin: 0 24rpx 24rpx;
}

.cfg-card {
	background-color: #ffffff;
	border-radius: 20rpx;
	padding: 8rpx 28rpx;
}

.cfg-row {
	display: flex;
	flex-direction: row;
	align-items: center;
	padding: 22rpx 0;
	border-bottom: 1rpx solid #f0f0f0;
}

.cfg-row:last-child {
	border-bottom: none;
}

.cfg-label {
	font-size: 26rpx;
	font-weight: 500;
	color: #666666;
	width: 200rpx;
	flex-shrink: 0;
}

.cfg-label-sm {
	font-size: 26rpx;
	font-weight: 500;
	color: #666666;
	width: 140rpx;
	flex-shrink: 0;
}

.cfg-input {
	font-size: 26rpx;
	color: #1a1a1a;
	flex: 1;
	height: 48rpx;
}

.pin-input {
	width: 140rpx;
	flex: none;
}

.cfg-desc {
	font-size: 20rpx;
	color: #b0b0b0;
	padding: 8rpx 0 16rpx;
	line-height: 32rpx;
}

/* 密码眼 */
.btn-eye {
	width: 48rpx;
	height: 48rpx;
	display: flex;
	justify-content: center;
	align-items: center;
}

.eye-icon {
	width: 32rpx;
	height: 20rpx;
	border: 2rpx solid #b0b0b0;
	border-radius: 50%;
	position: relative;
	display: flex;
	justify-content: center;
	align-items: center;
}

.eye-icon.open { border-color: #34d399; }

.eye-icon::after {
	content: '';
	width: 8rpx;
	height: 8rpx;
	background-color: #b0b0b0;
	border-radius: 50%;
}

.eye-icon.open::after { background-color: #34d399; }

/* 选择器 (picker) */
.cfg-select-row {
	display: flex;
	flex-direction: row;
	align-items: center;
	padding: 18rpx 0;
}

.cfg-picker {
	flex: 1;
	display: flex;
	flex-direction: row;
	align-items: center;
	justify-content: space-between;
	padding: 14rpx 18rpx;
	background-color: #f8f8f8;
	border-radius: 12rpx;
}

.cfg-picker-text {
	font-size: 26rpx;
	color: #1a1a1a;
}

.picker-arrow {
	width: 0;
	height: 0;
	border-left: 8rpx solid transparent;
	border-right: 8rpx solid transparent;
	border-top: 8rpx solid #b0b0b0;
	margin-left: 12rpx;
}

/* Radio 按钮 */
.cfg-radio-row {
	padding: 16rpx 0;
	display: flex;
	flex-direction: column;
	gap: 20rpx;
}

.cfg-radio {
	display: flex;
	flex-direction: row;
	align-items: center;
	gap: 12rpx;
}

.radio-dot {
	width: 28rpx;
	height: 28rpx;
	border-radius: 50%;
	border: 3rpx solid #d0d0d0;
	display: flex;
	justify-content: center;
	align-items: center;
}

.cfg-radio.active .radio-dot {
	border-color: #34d399;
}

.radio-inner {
	width: 14rpx;
	height: 14rpx;
	border-radius: 50%;
	background-color: #34d399;
}

.radio-label {
	font-size: 26rpx;
	color: #333333;
}

.cfg-radio.active .radio-label {
	color: #34d399;
	font-weight: 600;
}

/* 开关 (Switch) */
.cfg-switch-row {
	display: flex;
	flex-direction: row;
	align-items: center;
	justify-content: space-between;
	padding: 18rpx 0;
}

.switch {
	width: 80rpx;
	height: 44rpx;
	background-color: #e0e0e0;
	border-radius: 22rpx;
	position: relative;
	transition: background-color 0.2s;
}

.switch.on {
	background-color: #34d399;
}

.switch-knob {
	width: 36rpx;
	height: 36rpx;
	background-color: #ffffff;
	border-radius: 18rpx;
	position: absolute;
	top: 4rpx;
	left: 4rpx;
	box-shadow: 0 2rpx 6rpx rgba(0,0,0,0.15);
	transition: left 0.2s;
}

.switch.on .switch-knob {
	left: 40rpx;
}

/* 发送按钮 */
.btn-area {
	margin: 0 24rpx 40rpx;
}

.btn-send {
	background-color: #34d399;
	border-radius: 20rpx;
	padding: 28rpx;
	display: flex;
	justify-content: center;
	align-items: center;
}

.btn-send-pressed {
	transform: scale(0.98);
	background-color: #2bc48a;
}

.btn-send-text {
	font-size: 28rpx;
	font-weight: 700;
	color: #ffffff;
}

/* 状态提示 */
.status-toast {
	position: fixed;
	bottom: 120rpx;
	left: 50%;
	transform: translateX(-50%);
	background-color: #ffffff;
	border-radius: 20rpx;
	padding: 20rpx 32rpx;
	display: flex;
	flex-direction: row;
	align-items: center;
	box-shadow: 0 8rpx 40rpx rgba(0, 0, 0, 0.12);
	opacity: 0;
	pointer-events: none;
	transition: opacity 0.3s;
}

.status-toast.show { opacity: 1; }

.status-dot {
	width: 12rpx;
	height: 12rpx;
	border-radius: 6rpx;
	margin-right: 12rpx;
}

.status-dot.success { background-color: #34d399; }
.status-dot.error { background-color: #f87171; }

.status-text {
	font-size: 26rpx;
	color: #333333;
	font-weight: 500;
	white-space: nowrap;
}
</style>
