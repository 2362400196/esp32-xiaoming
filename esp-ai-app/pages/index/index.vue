<template>
	<view class="page">
		<view class="header">
			<view class="header-center">
				<text class="brand">{{ currentTab === 'ble' ? '蓝牙配网' : currentTab === 'skills' ? '技能管理' : currentTab === 'store' ? '插件商店' : currentTab === 'profile' ? '我的' : 'ESP-AI' }}</text>
				<text class="tagline" v-if="currentTab === 'home'">智能语音设备控制中心</text>
				<text class="tagline" v-if="currentTab === 'skills'">管理设备可用的智能技能</text>
				<text class="tagline" v-if="currentTab === 'store'">安装插件到当前设备</text>
			</view>
			<view class="header-right">
				<view class="device-status" @click="showModal('devices')">
					<view class="pulse" :style="{ backgroundColor: currentDevice && currentDevice.online ? '#34d399' : '#ef4444', opacity: currentDevice ? 1 : 0.3 }"></view>
					<text class="device-name">{{ currentDevice ? (currentDevice.mac ? currentDevice.name : currentDevice.name + '(待同步)') : '设备管理' }}</text>
					<view class="device-arrow"></view>
				</view>
			</view>
		</view>

		<view class="home-tab" v-if="currentTab === 'home'">
		<view class="hero">
			<view class="ai-core">
				<view class="core-center">
					<view class="device-hardware" :class="{ 'device-online': currentDevice && currentDevice.online }">
						<view class="device-bezel"></view>
						<view class="device-screen" :class="{ 'screen-off': !currentDevice || !currentDevice.online }">
							<view class="screen-statusbar" v-if="currentDevice && currentDevice.online">
								<view class="status-left">
									<view class="icon-wifi"></view>
									<text class="status-label">{{ currentDevice.name || '设备' }}</text>
								</view>
								<view class="status-right">
									<view class="icon-battery">
										<view class="battery-body"><view class="battery-level" :style="{ width: batteryPct + '%' }"></view></view>
										<view class="battery-cap"></view>
									</view>
								</view>
							</view>
							<view class="screen-content" v-if="currentDevice && currentDevice.online">
								<image v-if="sleepEmoUrl && !sleepEmoError" :src="sleepEmoUrl" mode="scaleToFill" class="screen-gif" @error="sleepEmoError = true"></image>
								<view v-else class="screen-emoji">💤</view>
							</view>
							<view class="screen-off-content" v-else>
								<text class="screen-off-text">OFF</text>
							</view>
							<view class="screen-glare" v-if="currentDevice && currentDevice.online"></view>
						</view>
						<view class="device-led" :class="{ on: currentDevice && currentDevice.online }"></view>
					</view>
				</view>
			</view>
		</view>

		<view class="modules">
			<view class="module" hover-class="module-pressed" @click="showModal('asr')">
				<view class="module-body asr">
					<view class="module-icon asr-icon">
						<text class="iconfont icon-asr">&#xe76c;</text>
					</view>
					<view class="module-text">
						<text class="module-title">ASR</text>
						<text class="module-sub">语音识别</text>
					</view>
					<view class="module-status">
						<view class="dot"></view>
					</view>
				</view>
			</view>

			<view class="module" hover-class="module-pressed" @click="showModal('llm')">
				<view class="module-body llm">
					<view class="module-icon llm-icon">
						<text class="iconfont icon-llm">&#xe709;</text>
					</view>
					<view class="module-text">
						<text class="module-title">LLM</text>
						<text class="module-sub">大语言模型</text>
					</view>
					<view class="module-status">
						<view class="dot"></view>
					</view>
				</view>
			</view>

			<view class="module" hover-class="module-pressed" @click="showModal('tts')">
				<view class="module-body tts">
					<view class="module-icon tts-icon">
						<view class="wave">
							<view class="bar b1"></view>
							<view class="bar b2"></view>
							<view class="bar b3"></view>
							<view class="bar b4"></view>
						</view>
					</view>
					<view class="module-text">
						<text class="module-title">TTS</text>
						<text class="module-sub">语音合成</text>
					</view>
					<view class="module-status">
						<view class="dot"></view>
					</view>
				</view>
			</view>
		</view>

		<view class="settings">
			<view class="setting setting-wake" hover-class="setting-pressed" @click="showModal('wake')">
				<view class="setting-icon-bg bg-blue">
					<view class="icon-wake">
						<view class="wake-bar wb1"></view>
						<view class="wake-bar wb2"></view>
						<view class="wake-bar wb3"></view>
						<view class="wake-bar wb4"></view>
						<view class="wake-bar wb5"></view>
					</view>
				</view>
				<text class="setting-label">唤醒</text>
			</view>
			<view class="setting setting-speak" hover-class="setting-pressed" @click="showModal('speak')">
				<view class="setting-icon-bg bg-green">
					<view class="icon-speak">
						<view class="speak-mic"></view>
						<view class="speak-base"></view>
					</view>
				</view>
				<text class="setting-label">说话</text>
			</view>
			<view class="setting setting-vol" hover-class="setting-pressed" @click="toggleVolumeFloat">
				<view class="setting-icon-bg bg-orange">
					<view class="icon-vol">
						<view class="vol-speaker"></view>
						<view class="vol-wave v1"></view>
						<view class="vol-wave v2"></view>
					</view>
				</view>
				<text class="setting-label">音量</text>
			</view>
			<view class="setting setting-emo" hover-class="setting-pressed" @click="showModal('emo')">
				<view class="setting-icon-bg bg-yellow">
					<view class="icon-emo">
						<view class="emo-face">
							<view class="emo-eye el"></view>
							<view class="emo-eye er"></view>
							<view class="emo-mouth"></view>
						</view>
					</view>
				</view>
				<text class="setting-label">表情</text>
			</view>
			<view class="setting setting-mcp" hover-class="setting-pressed" @click="openMcpModal">
				<view class="setting-icon-bg bg-green">
					<view class="icon-mcp">
						<view class="mcp-node"></view>
						<view class="mcp-line"></view>
						<view class="mcp-node"></view>
						<view class="mcp-line"></view>
						<view class="mcp-node"></view>
					</view>
				</view>
				<text class="setting-label">MCP</text>
			</view>
			<view class="setting setting-about" hover-class="setting-pressed" @click="showModal('tools')">
				<view class="setting-icon-bg bg-gray">
					<view class="icon-about">
						<view class="about-circle"></view>
						<view class="about-dot"></view>
						<view class="about-line"></view>
					</view>
				</view>
				<text class="setting-label">工具</text>
			</view>
		</view>

		</view>

		<!-- ====== 配网 Tab ====== -->
		<view class="ble-tab" v-if="currentTab === 'ble'">
			<view class="ble-scan-area">
				<view class="ble-radar">
					<view class="ble-radar-circle c1" :class="{ anim: bleScanning }"></view>
					<view class="ble-radar-circle c2" :class="{ anim: bleScanning }"></view>
					<view class="ble-radar-circle c3" :class="{ anim: bleScanning }"></view>
					<view class="ble-radar-circle c4" :class="{ anim: bleScanning }"></view>
					<view class="ble-radar-center"><view class="ble-bt-icon"><view class="ble-bt-path p1"></view><view class="ble-bt-path p2"></view></view></view>
					<view class="ble-radar-line" :class="{ anim: bleScanning }"></view>
				</view>
				<text class="ble-scan-tip">{{ bleScanTip }}</text>
				<view class="ble-scan-btn" hover-class="ble-btn-pressed" @click="bleToggleScan"><text class="ble-scan-btn-text">{{ bleScanning ? '停止扫描' : '开始扫描' }}</text></view>
			</view>
			<view class="ble-device-section" v-if="bleDevices.length > 0">
				<view class="ble-device-list">
					<view v-for="d in bleDevices" :key="d.deviceId" class="ble-device-item" :class="{ selected: bleSelectedDevice && bleSelectedDevice.deviceId === d.deviceId }" @click="bleSelectDevice(d)">
						<view class="ble-device-info"><text class="ble-device-name">{{ d.name }}</text><text class="ble-device-id">{{ d.deviceId }}</text><text class="ble-device-rssi" v-if="d.RSSI">信号 {{ d.RSSI }} dBm</text></view>
						<view class="ble-signal-bars" :class="'s' + bleSignalLevel(d.RSSI)"><view class="bar b1"></view><view class="bar b2"></view><view class="bar b3"></view><view class="bar b4"></view></view>
					</view>
				</view>
			</view>
			<view class="ble-form" v-if="bleSelectedDevice">
				<view class="ble-fg-section"><text class="ble-fg-title">网络配置</text>
					<view class="ble-fg-card">
						<view class="ble-fg-row"><view class="ble-fg-label">WiFi 账号 *</view><input class="ble-fg-input" type="text" placeholder="请输入 WiFi 名称" v-model="bleWifiSsid" /></view>
						<view class="ble-fg-row"><view class="ble-fg-label">WiFi 密码 *</view><input class="ble-fg-input" :type="bleShowPwd ? 'text' : 'password'" placeholder="请输入 WiFi 密码" v-model="bleWifiPwd" /><view class="ble-btn-eye" @click="bleShowPwd = !bleShowPwd"><view class="ble-eye" :class="{ on: bleShowPwd }"></view></view></view>
					</view>
				</view>
				<view class="ble-fg-section"><text class="ble-fg-title">服务配置</text>
					<view class="ble-fg-card">
						<view class="ble-radio-row">
							<view class="ble-radio" :class="{ on: bleSvcType === 'official' }" @click="bleSvcType = 'official'"><view class="ble-radio-dot"><view class="ble-radio-in" v-if="bleSvcType === 'official'"></view></view><text class="ble-radio-label">开放平台</text></view>
							<view class="ble-radio" :class="{ on: bleSvcType === 'custom' }" @click="bleSvcType = 'custom'"><view class="ble-radio-dot"><view class="ble-radio-in" v-if="bleSvcType === 'custom'"></view></view><text class="ble-radio-label">自定义服务</text></view>
						</view>
						<template v-if="bleSvcType === 'official'"><view class="ble-fg-row"><view class="ble-fg-label">API Key</view><input class="ble-fg-input" type="text" placeholder="请输入开放平台 API Key" v-model="bleSvcApiKey" /></view><view class="ble-fg-note" style="font-size:24rpx;color:#888;">在 ESP-AI 开放平台创建超体后获取，设备连接官方服务鉴权用</view></template>
						<template v-if="bleSvcType === 'custom'">
							<view class="ble-fg-row"><view class="ble-fg-label">服务协议</view><view class="ble-fg-picker" @click="showBlePicker(['http','https'], (i) => bleSvcProtocolIdx = i)"><text class="ble-fg-pick-text">{{ ['http','https'][bleSvcProtocolIdx] }}</text><view class="ble-pick-arrow"></view></view></view>
							<view class="ble-fg-row"><view class="ble-fg-label">服务地址</view><input class="ble-fg-input" type="text" placeholder="IP 或域名" v-model="bleSvcHost" /></view>
							<view class="ble-fg-row"><view class="ble-fg-label">服务端口</view><input class="ble-fg-input" type="text" inputmode="numeric" placeholder="如 8088" v-model="bleSvcPort" /></view>
						</template>
					</view>
				</view>
				<view class="ble-fg-section"><text class="ble-fg-title">唤醒/对话方式</text>
					<view class="ble-fg-card">
						<view class="ble-fg-row"><view class="ble-fg-label">唤醒方式</view>
							<view class="ble-fg-picker" @click="showBlePicker(['BOOT按钮唤醒','天问唤醒','天问+BOOT','高电平唤醒','低电平唤醒','按住BOOT对话','按住按钮对话'], (i) => bleWakeIdx = i)"><text class="ble-fg-pick-text">{{ ['BOOT按钮唤醒','天问唤醒','天问+BOOT','高电平唤醒','低电平唤醒','按住BOOT对话','按住按钮对话'][bleWakeIdx] }}</text><view class="ble-pick-arrow"></view></view>
						</view>
					</view>
				</view>
				<view class="ble-adv-toggle" @click="bleShowAdv = !bleShowAdv"><text class="ble-adv-toggle-text">{{ bleShowAdv ? '收起高级设置' : '展开高级设置' }}</text><view class="ble-adv-arrow" :class="{ up: bleShowAdv }"></view></view>
				<view v-show="bleShowAdv">
					<view class="ble-fg-section"><text class="ble-fg-title">电量检测配置</text><view class="ble-fg-card"><view class="ble-fg-row"><view class="ble-fg-label">启用电量检测</view><view class="ble-switch" :class="{ on: bleKwhEn }" @click="bleKwhEn = !bleKwhEn"><view class="ble-switch-knob"></view></view></view></view></view>
					<view class="ble-fg-section"><text class="ble-fg-title">音量控制配置</text><view class="ble-fg-card"><view class="ble-fg-row"><view class="ble-fg-label">启用音量控制</view><view class="ble-switch" :class="{ on: bleVolEn }" @click="bleVolEn = !bleVolEn"><view class="ble-switch-knob"></view></view></view><view class="ble-fg-row"><view class="ble-fg-label">电位器引脚</view><input class="ble-fg-input" type="text" inputmode="numeric" placeholder="默认 7" v-model="bleVolPin" /></view></view></view>
					<view class="ble-fg-section"><text class="ble-fg-title">指示灯配置</text><view class="ble-fg-card"><view class="ble-fg-row"><view class="ble-fg-label">WS2812 引脚</view><input class="ble-fg-input" type="text" inputmode="numeric" placeholder="默认 18" v-model="bleLightsData" /></view></view></view>
					<view class="ble-fg-section"><text class="ble-fg-title">OLED 屏幕配置</text><view class="ble-fg-card"><view class="ble-fg-row"><view class="ble-fg-label">SCK/SCL</view><input class="ble-fg-input" type="text" inputmode="numeric" placeholder="默认 38" v-model="bleOledSck" /></view><view class="ble-fg-row"><view class="ble-fg-label">SDA</view><input class="ble-fg-input" type="text" inputmode="numeric" placeholder="默认 39" v-model="bleOledSda" /></view></view></view>
					<view class="ble-fg-section"><text class="ble-fg-title">麦克风引脚配置</text><view class="ble-fg-card"><view class="ble-fg-row"><view class="ble-fg-label">SCK</view><input class="ble-fg-input" type="text" inputmode="numeric" placeholder="默认 4" v-model="bleMicBck" /></view><view class="ble-fg-row"><view class="ble-fg-label">WS</view><input class="ble-fg-input" type="text" inputmode="numeric" placeholder="默认 5" v-model="bleMicWs" /></view><view class="ble-fg-row"><view class="ble-fg-label">SD</view><input class="ble-fg-input" type="text" inputmode="numeric" placeholder="默认 6" v-model="bleMicData" /></view></view></view>
					<view class="ble-fg-section"><text class="ble-fg-title">扬声器引脚配置</text><view class="ble-fg-card"><view class="ble-fg-row"><view class="ble-fg-label">DIN</view><input class="ble-fg-input" type="text" inputmode="numeric" placeholder="默认 15" v-model="bleSpkData" /></view><view class="ble-fg-row"><view class="ble-fg-label">BCLK</view><input class="ble-fg-input" type="text" inputmode="numeric" placeholder="默认 16" v-model="bleSpkBck" /></view><view class="ble-fg-row"><view class="ble-fg-label">LRC</view><input class="ble-fg-input" type="text" inputmode="numeric" placeholder="默认 17" v-model="bleSpkWs" /></view></view></view>
				</view>
				<view class="ble-btn-area"><view class="ble-btn-send" hover-class="ble-btn-send-p" @click="bleSendConfig"><text class="ble-btn-send-text">{{ bleConnecting ? '配网中...' : '保存' }}</text></view></view>
			</view>
		</view>

		<!-- ====== 技能 Tab ====== -->
		<view class="skills-tab" v-if="currentTab === 'skills'">
			<view class="skills-header">
				<view class="skills-count" v-if="skillsList.length > 0">
					<text class="skills-count-text">共 {{ skillsList.length }} 个技能</text>
				</view>
				<view class="skills-add-btn" hover-class="skills-add-pressed" @click="openSkillModal()">
					<text class="skills-add-text">+ 添加技能</text>
				</view>
			</view>

			<view class="skills-empty" v-if="skillsList.length === 0 && !skillsLoading">
				<text class="skills-empty-icon">&#xe71f;</text>
				<text class="skills-empty-text">暂无技能</text>
				<text class="skills-empty-sub">点击上方「添加技能」创建你的第一个技能</text>
			</view>

			<view class="skills-loading" v-if="skillsLoading">
				<text class="skills-loading-text">加载中...</text>
			</view>

			<view class="skills-list" v-if="skillsList.length > 0">
				<view class="skill-card" v-for="s in skillsList" :key="s.id" :class="{ disabled: s.disabled }">
					<view class="skill-card-top">
						<view class="skill-info">
							<text class="skill-name">{{ s.id }}</text>
							<text class="skill-desc">{{ s.description }}</text>
						</view>
						<view class="skill-toggle" @click="toggleSkill(s)">
							<view class="skill-toggle-track" :class="{ on: !s.disabled }">
								<view class="skill-toggle-thumb"></view>
							</view>
						</view>
					</view>
					<view class="skill-tags" v-if="s.category && s.category.length > 0 || s.tags && s.tags.length > 0">
						<text class="skill-tag cat" v-for="c in (s.category || [])" :key="'c'+c">{{ c }}</text>
						<text class="skill-tag" v-for="t in (s.tags || [])" :key="'t'+t">{{ t }}</text>
					</view>
					<view class="skill-actions">
						<view class="skill-btn skill-btn-view" hover-class="skill-btn-pressed" @click="viewSkillDetail(s)">
							<text class="skill-btn-text view">查看</text>
						</view>
						<view class="skill-btn skill-btn-edit" hover-class="skill-btn-pressed" @click="openSkillModal(s)">
							<text class="skill-btn-text">编辑</text>
						</view>
						<view class="skill-btn skill-btn-del" hover-class="skill-btn-pressed" @click="confirmDeleteSkill(s)">
							<text class="skill-btn-text del">删除</text>
						</view>
					</view>
				</view>
			</view>
		</view>

		<!-- ====== 插件商店 Tab ====== -->
		<view class="store-tab" v-if="currentTab === 'store'">
			<view class="store-top">
				<view class="store-top-row">
					<text class="store-top-label">安装到</text>
					<text class="store-top-device">{{ currentDevice ? currentDevice.name : '未选择设备' }}</text>
					<view class="store-refresh" hover-class="store-refresh-pressed" @click="loadPlugins">
						<text class="store-refresh-text">刷新</text>
					</view>
				</view>
				<text class="store-note">为你的设备挑选插件，安装后立即生效，各设备互不影响</text>
			</view>

			<view class="plugin-loading" v-if="pluginForm.loading">
				<text class="plugin-loading-text">加载中...</text>
			</view>

			<view class="store-grid-wrap" v-if="!pluginForm.loading">
				<view class="store-grid">
					<view class="goods-card" v-for="p in pluginForm.list" :key="p.name"
						:class="{ installed: p.enabled }">
						<view class="goods-body">
							<view class="goods-name-row">
								<text class="goods-name">{{ p.title || p.name }}</text>
								<text class="goods-tag builtin" v-if="p.source === 'built-in'">内置</text>
								<text class="goods-tag" v-if="p.requires && p.requires.length">需屏幕</text>
							</view>
							<text class="goods-desc">{{ p.desc }}</text>
							<view class="goods-bottom">
								<view class="goods-config-btn" v-if="p.config_fields && p.config_fields.length"
									:class="{ done: p.configDone }" hover-class="goods-btn-pressed" @click.stop="openPluginConfig(p)">
									<text class="goods-config-text">{{ p.configDone ? '⚙ 已配置' : '⚙ 需配置' }}</text>
								</view>
								<view class="goods-btn" :class="{ installed: p.enabled, disabled: p.saving }"
									hover-class="goods-btn-pressed" @click.stop="installPlugin(p)">
									<text class="goods-btn-text">{{ p.saving ? '处理中...' : pluginBtnText(p) }}</text>
								</view>
							</view>
						</view>
					</view>
				</view>
				<view class="plugin-empty" v-if="pluginForm.list.length === 0">
					<text class="plugin-empty-text">没有可用的插件</text>
				</view>
			</view>
		</view>

		<!-- ====== 技能创建/编辑弹窗 ====== -->
		<view class="skill-page" :class="{ show: currentModal === 'skill' }">
			<view class="skill-page-header">
				<text class="skill-page-title">{{ skillForm.editing ? '编辑技能' : '添加技能' }}</text>
				<view class="skill-page-close" @click="hideModal">
					<view class="close-icon">
						<view class="close-line line1"></view>
						<view class="close-line line2"></view>
					</view>
				</view>
			</view>
			<scroll-view class="skill-page-body" scroll-y>
				<view class="form-section">
					<text class="form-label">技能名称 *</text>
					<input class="form-input" type="text" placeholder="小写字母/数字/下划线，如 my_skill" v-model="skillForm.name" :disabled="skillForm.editing" />
					<text class="form-hint" v-if="skillForm.editing">名称不可修改</text>
				</view>
				<view class="form-section">
					<text class="form-label">激活描述 *</text>
					<input class="form-input" type="text" placeholder="描述哪些用户意图会触发此技能" v-model="skillForm.description" />
				</view>
				<view class="form-section">
					<view class="form-label-row">
						<text class="form-label">执行指令 *</text>
						<view class="tool-insert-btn" hover-class="tool-insert-btn-pressed" @click="openToolPicker">
							<text class="tool-insert-btn-text">插入工具</text>
						</view>
					</view>
					<textarea class="skill-page-textarea" v-model="skillForm.instructions" placeholder="给 AI 的执行步骤..." maxlength="-1" @focus="onInstructionsFocus" @input="onInstructionsInput" @click="onInstructionsInput" />
				</view>
				<view class="form-row">
					<view class="form-section form-section-grow">
						<text class="form-label">分类（可选）</text>
						<input class="form-input" type="text" placeholder="如：utility" v-model="skillForm.categoryStr" />
					</view>
					<view class="form-section form-section-grow">
						<text class="form-label">标签（可选）</text>
						<input class="form-input" type="text" placeholder="如：weather" v-model="skillForm.tagsStr" />
					</view>
				</view>
			</scroll-view>
			<view class="skill-page-footer">
				<view class="btn-cancel" hover-class="btn-cancel-pressed" @click="hideModal">
					<text class="btn-text-cancel">取消</text>
				</view>
				<view class="btn-confirm" hover-class="btn-confirm-pressed" @click="submitSkill">
					<text class="btn-text-confirm">{{ skillForm.editing ? '保存' : '创建' }}</text>
				</view>
			</view>
		</view>

		<!-- ====== 技能详情弹窗 ====== -->
		<view class="modal-mask" :class="{ show: currentModal === 'skillDetail' }" @click="hideModal">
			<view class="modal-container modal-wide" :class="{ show: currentModal === 'skillDetail' }" @click.stop="">
				<view class="modal-header">
					<text class="modal-title">{{ skillDetail.id }}</text>
					<view class="modal-close" @click="hideModal">
						<view class="close-icon">
							<view class="close-line line1"></view>
							<view class="close-line line2"></view>
						</view>
					</view>
				</view>
				<view class="modal-body">
					<view class="detail-section" v-if="skillDetail.description">
						<text class="detail-label">激活描述</text>
						<text class="detail-text">{{ skillDetail.description }}</text>
					</view>
					<view class="detail-section" v-if="skillDetail.category && skillDetail.category.length">
						<text class="detail-label">分类</text>
						<view class="skill-tags">
							<text class="skill-tag cat" v-for="c in skillDetail.category" :key="c">{{ c }}</text>
						</view>
					</view>
					<view class="detail-section" v-if="skillDetail.tags && skillDetail.tags.length">
						<text class="detail-label">标签</text>
						<view class="skill-tags">
							<text class="skill-tag" v-for="t in skillDetail.tags" :key="t">{{ t }}</text>
						</view>
					</view>
					<view class="detail-section">
						<text class="detail-label">完整规则</text>
						<view class="detail-doc-box">
							<text class="detail-doc" v-if="!skillDetailLoading">{{ skillDetail.document || '无内容' }}</text>
							<text class="detail-doc" v-else>加载中...</text>
						</view>
					</view>
				</view>
				<view class="modal-footer">
					<view class="btn-confirm btn-full" hover-class="btn-confirm-pressed" @click="hideModal">
						<text class="btn-text-confirm">关闭</text>
					</view>
				</view>
			</view>
		</view>

		<!-- ====== 插件配置弹窗 ====== -->
		<view class="skill-page" :class="{ show: currentModal === 'pluginConfig' }">
			<view class="skill-page-header">
				<text class="skill-page-title">配置「{{ pluginConfigForm.title }}」</text>
				<view class="skill-page-close" @click="hideModal">
					<view class="close-icon">
						<view class="close-line line1"></view>
						<view class="close-line line2"></view>
					</view>
				</view>
			</view>
			<scroll-view class="plugin-page-body" scroll-y>
				<view class="plugin-note" style="margin-bottom:24rpx;">配置保存在当前设备上，仅本设备生效。</view>
				<view class="form-section" v-for="f in pluginConfigForm.fields" :key="f.key">
					<text class="form-label">{{ f.label }}<text v-if="f.required" style="color:#ff4d4f;"> *</text></text>
					<input class="form-input" type="text" :placeholder="f.placeholder || '请输入'" v-model="f.value" />
				</view>
				<view style="height:40rpx;"></view>
			</scroll-view>
			<view class="skill-page-footer">
				<view class="btn-cancel" hover-class="btn-cancel-pressed" @click="hideModal">
					<text class="btn-text-cancel">取消</text>
				</view>
				<view class="btn-confirm" hover-class="btn-confirm-pressed" @click="savePluginConfig">
					<text class="btn-text-confirm">{{ pluginConfigForm.saving ? '保存中...' : '保存' }}</text>
				</view>
			</view>
		</view>

		<!-- ====== MCP 配置管理抽屉 ====== -->
		<view class="drawer-mask" :class="{ show: currentModal === 'mcp' }" @click="hideModal">
			<view class="drawer-container" :class="{ show: currentModal === 'mcp' }" @click.stop="">
				<view class="drawer-header">
					<text class="drawer-title">MCP 服务器配置</text>
					<view class="drawer-close" @click="hideModal">
						<view class="close-icon">
							<view class="close-line line1"></view>
							<view class="close-line line2"></view>
						</view>
					</view>
				</view>
				<scroll-view class="drawer-body" scroll-y>
					<view class="mcp-loading" v-if="mcpLoading">
						<text class="mcp-loading-text">加载中...</text>
					</view>
					<view class="mcp-empty" v-if="!mcpLoading && mcpList.length === 0">
						<view class="mcp-empty-icon">
							<view class="mcp-empty-icon-inner"></view>
						</view>
						<text class="mcp-empty-text">暂无 MCP 服务器</text>
						<text class="mcp-empty-sub">点击下方按钮添加你的第一个服务器</text>
					</view>
					<view class="mcp-list" v-if="!mcpLoading && mcpList.length > 0">
						<view class="mcp-card" v-for="mcp in mcpList" :key="mcp.name" :class="{ disabled: mcp.disabled }">
							<view class="mcp-card-accent"></view>
							<view class="mcp-card-body">
								<view class="mcp-card-top">
									<text class="mcp-card-name">{{ mcp.name }}</text>
									<view class="mcp-card-right">
										<view class="mcp-card-tag">
											<text class="mcp-card-tag-text">HTTP</text>
										</view>
										<view class="skill-toggle" @click.stop="toggleMcpServer(mcp)">
											<view class="skill-toggle-track" :class="{ on: !mcp.disabled }">
												<view class="skill-toggle-thumb"></view>
											</view>
										</view>
									</view>
								</view>
								<text class="mcp-card-url" :selectable="true">{{ maskUrl(mcp.url) }}</text>
								<view class="mcp-card-actions">
									<view class="mcp-btn mcp-btn-tools" hover-class="mcp-btn-pressed" @click="openMcpTools(mcp)">
										<text class="mcp-btn-text tools">工具</text>
									</view>
									<view class="mcp-btn mcp-btn-edit" hover-class="mcp-btn-pressed" @click="openMcpEdit(mcp)">
										<text class="mcp-btn-text">编辑</text>
									</view>
									<view class="mcp-btn mcp-btn-del" hover-class="mcp-btn-pressed" @click="confirmDeleteMcp(mcp)">
										<text class="mcp-btn-text del">删除</text>
									</view>
								</view>
							</view>
						</view>
					</view>
				</scroll-view>
				<view class="drawer-footer">
					<view class="btn-cancel" hover-class="btn-cancel-pressed" @click="hideModal">
						<text class="btn-text-cancel">关闭</text>
					</view>
					<view class="btn-confirm" hover-class="btn-confirm-pressed" @click="openMcpAdd">
						<text class="btn-text-confirm">添加服务器</text>
					</view>
				</view>
			</view>
		</view>

		<!-- ====== MCP 添加/编辑抽屉 ====== -->
		<view class="drawer-mask" :class="{ show: currentModal === 'mcpForm' }" @click="backToMcpList">
			<view class="drawer-container" :class="{ show: currentModal === 'mcpForm' }" @click.stop="">
				<view class="drawer-header">
					<text class="drawer-title">{{ mcpForm.editing ? '编辑 MCP 服务器' : '添加 MCP 服务器' }}</text>
					<view class="drawer-close" @click="backToMcpList">
						<view class="close-icon">
							<view class="close-line line1"></view>
							<view class="close-line line2"></view>
						</view>
					</view>
				</view>
				<scroll-view class="drawer-body drawer-body-padded" scroll-y>
					<view class="form-section">
						<text class="form-label">服务器名称 *</text>
						<input class="form-input" type="text" placeholder="如：amap-maps" v-model="mcpForm.name" :disabled="mcpForm.editing" />
						<text class="form-hint" v-if="mcpForm.editing">名称不可修改</text>
					</view>
					<view class="form-section">
						<text class="form-label">类型</text>
						<view class="mcp-type-display">
							<text class="mcp-type-value">Streamable HTTP</text>
						</view>
					</view>
					<view class="form-section">
						<text class="form-label">URL *</text>
						<input class="form-input" type="text" placeholder="https://mcp.example.com/mcp" v-model="mcpForm.url" />
					</view>
					<view class="form-section">
						<text class="form-label">Headers（可选，JSON 格式）</text>
						<textarea class="mcp-form-textarea" v-model="mcpForm.headersStr" placeholder='{"Authorization": "Bearer xxx"}' maxlength="-1" />
					</view>
					<view class="form-section">
						<text class="form-label">Auth（可选，JSON 格式）</text>
						<textarea class="mcp-form-textarea" v-model="mcpForm.authStr" placeholder='{"token": "xxx"}' maxlength="-1" />
					</view>
				</scroll-view>
				<view class="drawer-footer">
					<view class="btn-cancel" hover-class="btn-cancel-pressed" @click="backToMcpList">
						<text class="btn-text-cancel">取消</text>
					</view>
					<view class="btn-confirm" hover-class="btn-confirm-pressed" @click="submitMcp">
						<text class="btn-text-confirm">{{ mcpForm.editing ? '保存' : '添加' }}</text>
					</view>
				</view>
			</view>
		</view>

		<!-- ====== MCP 工具列表抽屉 ====== -->
		<view class="drawer-mask" :class="{ show: currentModal === 'mcpTools' }" @click="closeMcpTools">
			<view class="drawer-container" :class="{ show: currentModal === 'mcpTools' }" @click.stop="">
				<view class="drawer-header">
					<text class="drawer-title">{{ mcpToolsServer }} 工具</text>
					<view class="drawer-close" @click="closeMcpTools">
						<view class="close-icon">
							<view class="close-line line1"></view>
							<view class="close-line line2"></view>
						</view>
					</view>
				</view>
				<scroll-view class="drawer-body" scroll-y>
					<view class="mcp-loading" v-if="mcpToolsLoading">
						<text class="mcp-loading-text">加载中...</text>
					</view>
					<view class="mcp-empty" v-if="!mcpToolsLoading && mcpTools.length === 0">
						<view class="mcp-empty-icon">
							<view class="mcp-empty-icon-inner"></view>
						</view>
						<text class="mcp-empty-text">暂无工具</text>
						<text class="mcp-empty-sub">该服务器未提供工具</text>
					</view>
					<view class="tool-list" v-if="!mcpToolsLoading && mcpTools.length > 0">
						<view class="tool-card" v-for="(tool, idx) in mcpTools" :key="idx" :class="{ 'tool-disabled': tool.disabled }">
							<view class="tool-card-row">
								<view class="tool-card-info">
									<text class="tool-name">{{ tool.name }}</text>
									<text class="tool-desc">{{ tool.description || '暂无描述' }}</text>
								</view>
								<view class="skill-toggle" @click="toggleMcpTool(tool)">
									<view class="skill-toggle-track" :class="{ on: !tool.disabled }">
										<view class="skill-toggle-thumb"></view>
									</view>
								</view>
							</view>
						</view>
					</view>
				</scroll-view>
				<view class="drawer-footer">
					<view class="btn-cancel" hover-class="btn-cancel-pressed" @click="closeMcpTools">
						<text class="btn-text-cancel">关闭</text>
					</view>
				</view>
			</view>
		</view>

		<!-- ====== 工具选择器抽屉 ====== -->
		<view class="drawer-mask" :class="{ show: currentModal === 'toolPicker' }" @click="hideModal">
			<view class="drawer-container" :class="{ show: currentModal === 'toolPicker' }" @click.stop="">
				<view class="drawer-header">
					<text class="drawer-title">可用工具</text>
					<view class="drawer-close" @click="hideModal">
						<view class="close-icon">
							<view class="close-line line1"></view>
							<view class="close-line line2"></view>
						</view>
					</view>
				</view>
				<scroll-view class="drawer-body" scroll-y>
					<view class="mcp-loading" v-if="toolPickerLoading">
						<text class="mcp-loading-text">加载中...</text>
					</view>
					<view class="mcp-empty" v-if="!toolPickerLoading && toolPickerList.length === 0">
						<view class="mcp-empty-icon">
							<view class="mcp-empty-icon-inner"></view>
						</view>
						<text class="mcp-empty-text">暂无可用工具</text>
					</view>
					<view class="tool-list" v-if="!toolPickerLoading && toolPickerList.length > 0">
						<view class="tool-card tool-card-clickable" v-for="(tool, idx) in toolPickerList" :key="idx" @click="insertToolName(tool.name)">
							<view class="tool-card-top">
								<text class="tool-name">{{ tool.name }}</text>
								<text class="tool-type-tag" v-if="tool.type">{{ tool.type === 'mcp' ? 'MCP' : '内置' }}</text>
							</view>
							<text class="tool-desc">{{ tool.description || '暂无描述' }}</text>
						</view>
					</view>
				</scroll-view>
				<view class="drawer-footer">
					<view class="btn-cancel" hover-class="btn-cancel-pressed" @click="hideModal">
						<text class="btn-text-cancel">关闭</text>
					</view>
				</view>
			</view>
		</view>

		<!-- ====== 我的 Tab ====== -->
		<view class="profile-tab" v-if="currentTab === 'profile'">

			<!-- 未登录：登录/注册 -->
			<template v-if="!isLoggedInRef">
				<view class="profile-brand">
					<text class="profile-brand-title">ESP-AI</text>
					<text class="profile-brand-sub">智能语音设备控制中心</text>
				</view>

				<view class="profile-switch">
					<view class="profile-switch-item" :class="{ on: profileFormMode === 'login' }" @click="profileFormMode = 'login'">
						<text class="profile-switch-text">登录</text>
					</view>
					<view class="profile-switch-item" :class="{ on: profileFormMode === 'register' }" @click="profileFormMode = 'register'">
						<text class="profile-switch-text">注册</text>
					</view>
					<view class="profile-switch-bar" :style="{ left: profileFormMode === 'login' ? '0%' : '50%' }"></view>
				</view>

				<!-- 登录表单 -->
				<view class="profile-form" v-if="profileFormMode === 'login'">
					<view class="profile-input-row">
						<text class="profile-input-label">邮箱 / 手机号</text>
						<input class="profile-input" type="text" placeholder="请输入邮箱或手机号" v-model="profileEmail" />
					</view>
					<view class="profile-input-row">
						<text class="profile-input-label">密码</text>
						<input class="profile-input" :type="profileShowPwd ? 'text' : 'password'" placeholder="请输入密码" v-model="profilePassword" />
						<view class="profile-eye" @click="profileShowPwd = !profileShowPwd"><text class="profile-eye-text">{{ profileShowPwd ? '隐藏' : '显示' }}</text></view>
					</view>
					<view class="profile-error" v-if="profileErr">{{ profileErr }}</view>
					<view class="profile-btn" hover-class="profile-btn-p" @click="doLogin">
						<text class="profile-btn-text">{{ profileLoading ? '登录中...' : '登录' }}</text>
					</view>

					<!-- 服务器地址（折叠，仅登录页展示） -->
					<view class="profile-server-collapse" @click="profileServerCollapsed = !profileServerCollapsed">
						<text class="profile-server-collapse-text">服务器配置</text>
						<text class="profile-server-collapse-arrow">{{ profileServerCollapsed ? '▸' : '▾' }}</text>
					</view>
					<view class="profile-server-section" v-if="!profileServerCollapsed">
						<view class="profile-input-row">
							<text class="profile-input-label">服务器地址</text>
							<input class="profile-input" type="text" placeholder="http://192.168.31.176:8088" v-model="profileServerUrl" @blur="saveServerUrl" />
						</view>
						<text class="profile-server-note">修改后需在首页顶栏「设备管理」中同步</text>
					</view>
				</view>

				<!-- 注册表单 -->
				<view class="profile-form" v-if="profileFormMode === 'register'">
					<view class="profile-input-row">
						<text class="profile-input-label">邮箱 / 手机号</text>
						<input class="profile-input" type="text" placeholder="请输入邮箱或手机号" v-model="profileEmail" />
					</view>
					<view class="profile-input-row">
						<text class="profile-input-label">昵称</text>
						<input class="profile-input" type="text" placeholder="给自己起个名字" v-model="profileNickname" />
					</view>
					<view class="profile-input-row">
						<text class="profile-input-label">密码</text>
						<input class="profile-input" :type="profileShowPwd ? 'text' : 'password'" placeholder="至少 6 位" v-model="profilePassword" />
					</view>
					<view class="profile-error" v-if="profileErr">{{ profileErr }}</view>
					<view class="profile-btn" hover-class="profile-btn-p" @click="doRegister">
						<text class="profile-btn-text">{{ profileLoading ? '注册中...' : '注册' }}</text>
					</view>
				</view>
			</template>

			<!-- 已登录：用户信息 -->
			<template v-if="isLoggedInRef">
				<view class="profile-user-card">
					<view class="profile-avatar">
						<text class="profile-avatar-text">{{ (getUser()?.nickname || getUser()?.email || '?')[0].toUpperCase() }}</text>
					</view>
					<view class="profile-user-info">
						<text class="profile-user-name">{{ getUser()?.nickname || '用户' }}</text>
						<text class="profile-user-email">{{ getUser()?.email }}</text>
					</view>
				</view>

				<view class="profile-menu">
					<view class="profile-menu-item" @click="showModal('devices')">
						<text class="profile-menu-icon">📱</text>
						<text class="profile-menu-label">设备管理</text>
						<text class="profile-menu-arrow">›</text>
					</view>
					<view class="profile-menu-item" @click="refreshFromServer">
						<text class="profile-menu-icon">🔄</text>
						<text class="profile-menu-label">从服务器同步设备</text>
						<text class="profile-menu-arrow">›</text>
					</view>
					<view class="profile-menu-item" @click="profileWakeCollapsed = !profileWakeCollapsed">
						<text class="profile-menu-icon">🔊</text>
						<text class="profile-menu-label">唤醒配置</text>
						<text class="profile-menu-arrow" style="font-size:20rpx;">{{ profileWakeCollapsed ? '▸' : '▾' }}</text>
					</view>
					<view v-if="!profileWakeCollapsed" style="padding:16rpx 32rpx;background:#f9f9f9;">
						<view class="profile-input-row">
							<text class="profile-input-label">回复文本</text>
							<input class="profile-input" type="text" placeholder="我在呢" v-model="profileWakeText" />
						</view>
						<view class="ble-fg-row" style="margin-top:12rpx;">
							<text class="ble-fg-label">启用唤醒音频</text>
							<view class="ble-switch" :class="{ on: profileWakeAudioEn }" @click="profileWakeAudioEn = !profileWakeAudioEn"><view class="ble-switch-knob"></view></view>
						</view>
						<view class="profile-input-row" style="margin-top:12rpx;">
							<text class="profile-input-label">音频来源</text>
							<view style="display:flex;gap:8rpx;flex:1;">
								<view class="ble-switch" style="flex-direction:row;gap:8rpx;padding:0;" @click="profileWakeSource = 'tts'">
									<text style="font-size:26rpx;color:#666;" :style="{color:profileWakeSource==='tts'?'#007aff':'#666'}">TTS</text>
								</view>
								<text style="color:#ccc;">|</text>
								<view class="ble-switch" style="flex-direction:row;gap:8rpx;padding:0;" @click="profileWakeSource = 'file'">
									<text style="font-size:26rpx;color:#666;" :style="{color:profileWakeSource==='file'?'#007aff':'#666'}">文件</text>
								</view>
							</view>
						</view>
						<view class="ble-fg-row" style="margin-top:12rpx;">
							<text class="ble-fg-label">对话结束后再播</text>
							<view class="ble-switch" :class="{ on: profileWakeNextRound }" @click="profileWakeNextRound = !profileWakeNextRound"><view class="ble-switch-knob"></view></view>
						</view>
						<view style="display:flex;gap:12rpx;margin-top:16rpx;">
							<view class="profile-btn" style="flex:1;" hover-class="profile-btn-p" @click="saveWakeConfig">
								<text class="profile-btn-text">保存</text>
							</view>
							<view class="profile-btn" style="flex:1;background:#e0e0e0;" hover-class="profile-btn-p" @click="loadWakeConfig">
								<text class="profile-btn-text" style="color:#666;">刷新</text>
							</view>
						</view>
					</view>
					<!-- AI 主动聊天 -->
					<view class="profile-menu-item" @click="profileProactiveCollapsed = !profileProactiveCollapsed">
						<text class="profile-menu-icon">🤖</text>
						<text class="profile-menu-label">AI 主动聊天</text>
						<text class="profile-menu-arrow" style="font-size:20rpx;">{{ profileProactiveCollapsed ? '▸' : '▾' }}</text>
					</view>
					<view v-if="!profileProactiveCollapsed" style="padding:16rpx 32rpx;background:#f9f9f9;">
						<view class="profile-input-row">
							<text class="profile-input-label">每日主动推送次数</text>
							<text style="font-size:28rpx;color:#007aff;font-weight:600;">{{ proactiveMaxPushes }}次</text>
						</view>
						<slider min="0" max="50" step="1" :value="proactiveMaxPushes" activeColor="#007aff" backgroundColor="#e5e5ea" blockColor="#007aff" @change="onProactiveMaxChange" style="margin:0;" />
						<text style="font-size:20rpx;color:#999;display:block;margin-top:-8rpx;">设为 0 即关闭 AI 主动找你聊天</text>
						<view style="display:flex;gap:12rpx;margin-top:16rpx;">
							<view class="profile-btn" style="flex:1;" hover-class="profile-btn-p" @click="saveProactiveConfig">
								<text class="profile-btn-text">保存</text>
							</view>
							<view class="profile-btn" style="flex:1;background:#e0e0e0;" hover-class="profile-btn-p" @click="loadProactiveConfig">
								<text class="profile-btn-text" style="color:#666;">刷新</text>
							</view>
						</view>
					</view>
					<!-- 微信绑定 -->
					<view class="profile-menu-item" @click="wechatCollapsed = !wechatCollapsed">
						<text class="profile-menu-icon">💬</text>
						<text class="profile-menu-label">微信绑定</text>
						<text class="profile-menu-arrow" style="font-size:20rpx;">{{ wechatCollapsed ? '▸' : '▾' }}</text>
					</view>
					<view v-if="!wechatCollapsed" style="padding:16rpx 32rpx;background:#f9f9f9;">
						<!-- 已绑定状态 -->
						<template v-if="wechatBoundDeviceKey">
							<view style="display:flex;align-items:center;gap:12rpx;padding:12rpx 0;">
								<text style="font-size:28rpx;">✅</text>
								<text style="font-size:26rpx;color:#333;">微信已绑定</text>
							</view>
							<view style="font-size:24rpx;color:#999;margin-bottom:12rpx;">
								设备: {{ wechatBoundDeviceKey.slice(0,16) }}...
							</view>
							<view v-if="wechatGroupId" style="font-size:24rpx;color:#999;margin-bottom:12rpx;">
								群聊: {{ wechatGroupId.slice(0,20) }}...
							</view>
							<view class="profile-btn" style="background:#ff4d4f;" hover-class="profile-btn-p" @click="unbindWechat">
								<text class="profile-btn-text">解绑微信</text>
							</view>
						</template>
						<!-- 未绑定 + 二维码登录 -->
						<template v-else>
							<view style="display:flex;flex-direction:column;align-items:center;padding:12rpx 0;">
								<view v-if="wechatQrStatus === 'waiting_scan' || wechatQrStatus === 'scanned' || wechatQrStatus === 'redirected'" style="width:100%;">
									<!-- 二维码图片 -->
									<image v-if="wechatQrDataUrl" :src="wechatQrDataUrl" mode="widthFix"
										style="width:300rpx;height:300rpx;display:block;margin:0 auto 16rpx;border-radius:16rpx;border:2rpx solid #e0e0e0;" />
									<view v-else style="width:300rpx;height:300rpx;display:flex;align-items:center;justify-content:center;margin:0 auto 16rpx;background:#f0f0f0;border-radius:16rpx;">
										<text style="font-size:24rpx;color:#999;">二维码加载中...</text>
									</view>
									<text style="display:block;text-align:center;font-size:26rpx;color:#333;margin-bottom:8rpx;">
										{{ wechatQrMessage }}
									</text>
									<text v-if="wechatQrPolling" style="display:block;text-align:center;font-size:22rpx;color:#999;">
										正在等待扫码...
									</text>
									<view style="display:flex;gap:12rpx;margin-top:16rpx;">
										<view class="profile-btn" style="flex:1;background:#e0e0e0;" hover-class="profile-btn-p" @click="stopPollQr">
											<text class="profile-btn-text" style="color:#666;">取消</text>
										</view>
										<view class="profile-btn" style="flex:1;" hover-class="profile-btn-p" @click="startWechatQr">
											<text class="profile-btn-text">刷新二维码</text>
										</view>
									</view>
								</view>
								<view v-else>
									<text style="display:block;text-align:center;font-size:26rpx;color:#666;margin-bottom:16rpx;">
										{{ wechatQrMessage || '绑定微信后，可通过微信聊天控制设备' }}
									</text>
									<view class="profile-btn" hover-class="profile-btn-p" @click="startWechatQr">
										<text class="profile-btn-text">开始微信扫码绑定</text>
									</view>
								</view>
							</view>
						</template>
						<!-- 群聊绑定（始终显示，绑定后也可操作） -->
						<view style="margin-top:20rpx;padding-top:16rpx;border-top:2rpx solid #e0e0e0;">
							<text style="display:block;font-size:24rpx;color:#999;margin-bottom:8rpx;">
								绑定群聊（在群里 @机器人后点刷新）
								<text v-if="wechatGroupId" style="color:#07c160;"> ✓ 已绑定</text>
							</text>
							<view style="display:flex;gap:8rpx;flex-wrap:wrap;">
								<picker v-if="recentGroups.length > 0" @change="onGroupPick" :value="groupPickIndex" :range="recentGroups" range-key="name">
									<view style="flex:1;border:2rpx solid #ddd;border-radius:8rpx;padding:8rpx 12rpx;font-size:24rpx;min-height:60rpx;display:flex;align-items:center;">
										<text v-if="groupPickIndex >= 0" style="color:#333;">{{ recentGroups[groupPickIndex].name }}</text>
										<text v-else style="color:#bbb;">选择群聊...</text>
									</view>
								</picker>
								<view class="profile-btn" style="padding:8rpx 20rpx;" hover-class="profile-btn-p" @click="fetchRecentGroups">
									<text class="profile-btn-text" style="font-size:22rpx;">刷新</text>
								</view>
								<view class="profile-btn" style="padding:8rpx 20rpx;background:#07c160;" hover-class="profile-btn-p" @click="saveGroupBind">
									<text class="profile-btn-text" style="font-size:22rpx;">保存</text>
								</view>
								<view v-if="wechatGroupId" class="profile-btn" style="padding:8rpx 20rpx;background:#ff4d4f;" hover-class="profile-btn-p" @click="unbindGroupChat">
									<text class="profile-btn-text" style="font-size:22rpx;">解绑</text>
								</view>
							</view>
						</view>
					</view>
				<!-- 关于和 OTA -->
					<view class="profile-menu-item" @click="showAbout">
						<text class="profile-menu-icon">ℹ️</text>
						<text class="profile-menu-label">关于</text>
						<text class="profile-menu-arrow">›</text>
					</view>
					<view class="profile-menu-item" @click="checkOtaUpdate">
						<text class="profile-menu-icon">📥</text>
						<text class="profile-menu-label">OTA 升级</text>
						<text class="profile-menu-arrow">›</text>
					</view>
				</view>

				<view class="profile-logout-btn" hover-class="profile-btn-p" @click="showLogoutConfirm">
					<text class="profile-logout-text">退出登录</text>
				</view>
			</template>
		</view>

		<view class="nav">
			<view class="nav-item" :class="{ active: currentTab === 'home' }" hover-class="nav-pressed" @click="switchTab('home')">
				<view class="nav-icon-wrap">
					<view class="nav-icon home"></view>
				</view>
				<text class="nav-label">首页</text>
			</view>
			<view class="nav-item" :class="{ active: currentTab === 'skills' }" hover-class="nav-pressed" @click="switchTab('skills')">
				<view class="nav-icon-wrap">
					<text class="iconfont nav-iconfont">&#xe71f;</text>
				</view>
				<text class="nav-label">技能</text>
			</view>
			<view class="nav-item" :class="{ active: currentTab === 'store' }" hover-class="nav-pressed" @click="switchTab('store')">
				<view class="nav-icon-wrap">
					<text class="nav-iconfont" style="font-size:36rpx;line-height:1;">🧩</text>
				</view>
				<text class="nav-label">商店</text>
			</view>
			<view class="nav-item" :class="{ active: currentTab === 'ble' }" hover-class="nav-pressed" @click="switchTab('ble')">
				<view class="nav-icon-wrap">
					<view class="nav-icon ble"></view>
				</view>
				<text class="nav-label">配网</text>
			</view>
			<view class="nav-item" :class="{ active: currentTab === 'profile' }" hover-class="nav-pressed" @click="switchTab('profile')">
				<view class="nav-icon-wrap">
					<text class="iconfont nav-iconfont">&#xe651;</text>
				</view>
				<text class="nav-label">我的</text>
			</view>
		</view>

		<view class="modal-mask" :class="{ show: currentModal === 'asr' }" @click="hideModal">
			<view class="modal-container" :class="{ show: currentModal === 'asr' }" @click.stop="">
				<view class="modal-header">
					<text class="modal-title">ASR 语音识别配置</text>
					<view class="modal-close" @click="hideModal">
						<view class="close-icon">
							<view class="close-line line1"></view>
							<view class="close-line line2"></view>
						</view>
					</view>
				</view>

				<view class="modal-body">
					<view class="form-section">
						<text class="form-label">引擎选择</text>
						<view class="engine-options">
							<view class="engine-option" :class="{ active: asrEngine === 'bytedance' }" @click="switchAsrEngine('bytedance')">
								<text class="engine-name">字节跳动</text>
								<view class="engine-check" v-if="asrEngine === 'bytedance'">
									<view class="check-dot"></view>
								</view>
							</view>
							<view class="engine-option" :class="{ active: asrEngine === 'tencent' }" @click="switchAsrEngine('tencent')">
								<text class="engine-name">腾讯云</text>
								<view class="engine-check" v-if="asrEngine === 'tencent'">
									<view class="check-dot"></view>
								</view>
							</view>
						</view>
					</view>

					<view class="form-section" v-if="asrEngine === 'bytedance'">
						<text class="form-label">API Key</text>
						<view class="form-input-wrap">
							<input class="form-input form-input-inner" :type="showKey.bytedance ? 'text' : 'password'" placeholder="请输入字节跳动 API Key" v-model="bytedanceApiKey" />
							<view class="eye-btn" @click="showKey.bytedance = !showKey.bytedance">
								<view class="eye-icon" :class="{ off: !showKey.bytedance }"></view>
							</view>
						</view>
					</view>

					<template v-if="asrEngine === 'tencent'">
						<view class="form-section">
							<text class="form-label">App ID</text>
							<input class="form-input" type="text" placeholder="请输入腾讯云 App ID" v-model="tencentAppId" />
						</view>
						<view class="form-section">
							<text class="form-label">Secret ID</text>
							<input class="form-input" type="text" placeholder="请输入腾讯云 Secret ID" v-model="tencentSecretId" />
						</view>
						<view class="form-section">
							<text class="form-label">Secret Key</text>
							<view class="form-input-wrap">
								<input class="form-input form-input-inner" :type="showKey.tencent ? 'text' : 'password'" placeholder="请输入腾讯云 Secret Key" v-model="tencentSecretKey" />
								<view class="eye-btn" @click="showKey.tencent = !showKey.tencent">
									<view class="eye-icon" :class="{ off: !showKey.tencent }"></view>
								</view>
							</view>
						</view>
					</template>
				</view>

				<view class="modal-footer">
					<view class="btn-cancel" hover-class="btn-cancel-pressed" @click="hideModal">
						<text class="btn-text-cancel">取消</text>
					</view>
					<view class="btn-confirm" hover-class="btn-confirm-pressed" @click="saveAsrConfig">
						<text class="btn-text-confirm">保存</text>
					</view>
				</view>
			</view>
		</view>

		<view class="modal-mask" :class="{ show: currentModal === 'llm' }" @click="hideModal">
			<view class="modal-container" :class="{ show: currentModal === 'llm' }" @click.stop="">
				<view class="modal-header">
					<text class="modal-title">LLM 大语言模型配置</text>
					<view class="modal-close" @click="hideModal">
						<view class="close-icon">
							<view class="close-line line1"></view>
							<view class="close-line line2"></view>
						</view>
					</view>
				</view>

				<view class="modal-body">
					<view class="form-section">
						<text class="form-label">引擎选择</text>
						<view class="engine-options-single">
							<view class="engine-option active">
								<text class="engine-name">DeepSeek</text>
								<view class="engine-check">
									<view class="check-dot"></view>
								</view>
							</view>
						</view>
					</view>

					<view class="form-section">
						<text class="form-label">API Key</text>
						<view class="form-input-wrap">
							<input class="form-input form-input-inner" :type="showKey.deepseek ? 'text' : 'password'" placeholder="请输入 DeepSeek API Key" v-model="deepseekApiKey" />
							<view class="eye-btn" @click="showKey.deepseek = !showKey.deepseek">
								<view class="eye-icon" :class="{ off: !showKey.deepseek }"></view>
							</view>
						</view>
					</view>

					<view class="form-section">
						<text class="form-label">模型选择</text>
						<view class="model-options">
							<view class="model-option" :class="{ active: llmModel === 'deepseek-v4-flash' }" @click="llmModel = 'deepseek-v4-flash'">
								<text class="model-name">deepseek-v4-flash</text>
								<view class="model-check" v-if="llmModel === 'deepseek-v4-flash'"></view>
							</view>
							<view class="model-option" :class="{ active: llmModel === 'deepseek-v4-pro' }" @click="llmModel = 'deepseek-v4-pro'">
								<text class="model-name">deepseek-v4-pro</text>
								<view class="model-check" v-if="llmModel === 'deepseek-v4-pro'"></view>
							</view>
						</view>
					</view>

					<view class="form-section">
						<text class="form-label">提示词</text>
						<textarea class="form-textarea" placeholder="请输入系统提示词" v-model="llmPrompt" />
					</view>
				</view>

				<view class="modal-footer">
					<view class="btn-cancel" hover-class="btn-cancel-pressed" @click="hideModal">
						<text class="btn-text-cancel">取消</text>
					</view>
					<view class="btn-confirm" hover-class="btn-confirm-pressed" @click="saveLlmConfig">
						<text class="btn-text-confirm">保存</text>
					</view>
				</view>
			</view>
		</view>

		<view class="modal-mask" :class="{ show: currentModal === 'tts' }" @click="hideModal">
			<view class="modal-container" :class="{ show: currentModal === 'tts' }" @click.stop="">
				<view class="modal-header">
					<text class="modal-title">TTS 语音合成配置</text>
					<view class="modal-close" @click="hideModal">
						<view class="close-icon">
							<view class="close-line line1"></view>
							<view class="close-line line2"></view>
						</view>
					</view>
				</view>

				<view class="modal-body">
					<view class="form-section">
						<text class="form-label">引擎选择</text>
						<view class="engine-options-single">
							<view class="engine-option active">
								<text class="engine-name">字节跳动</text>
								<view class="engine-check">
									<view class="check-dot"></view>
								</view>
							</view>
						</view>
					</view>

					<view class="form-section">
						<text class="form-label">API Key</text>
						<view class="form-input-wrap">
							<input class="form-input form-input-inner" :type="showKey.tts ? 'text' : 'password'" placeholder="请输入字节跳动 API Key" v-model="ttsApiKey" />
							<view class="eye-btn" @click="showKey.tts = !showKey.tts">
								<view class="eye-icon" :class="{ off: !showKey.tts }"></view>
							</view>
						</view>
					</view>

					<!-- 火山 OpenAPI 密钥:查询复刻音色列表用,默认折叠,留空回退服务器 .env -->
					<view class="form-section">
						<view class="collapsible-header" @click="volcCredOpen = !volcCredOpen">
							<text class="collapsible-title">火山 OpenAPI 密钥(查询复刻音色列表)</text>
							<text class="collapsible-arrow" :class="{ open: volcCredOpen }">▼</text>
						</view>
						<view v-if="volcCredOpen" class="collapsible-body">
							<view class="form-input-wrap">
								<input class="form-input form-input-inner" :type="showKey.volcAk ? 'text' : 'password'"
									placeholder="AccessKeyId(以 AKLT 开头)" v-model="volcAkId" />
								<view class="eye-btn" @click="showKey.volcAk = !showKey.volcAk">
									<view class="eye-icon" :class="{ off: !showKey.volcAk }"></view>
								</view>
							</view>
							<view class="form-input-wrap">
								<input class="form-input form-input-inner" :type="showKey.volcSk ? 'text' : 'password'"
									placeholder="SecretAccessKey" v-model="volcSk" />
								<view class="eye-btn" @click="showKey.volcSk = !showKey.volcSk">
									<view class="eye-icon" :class="{ off: !showKey.volcSk }"></view>
								</view>
							</view>
							<input class="form-input" type="text" placeholder="项目名(默认 default)"
								v-model="volcProjectName" />
							<text class="form-tip">留空则使用服务器 .env 的环境变量配置;配置后"声音复刻"模型下拉可自动获取复刻音色</text>
						</view>
					</view>

					<view class="form-section">
						<text class="form-label">模型</text>
						<view class="model-options">
							<view class="model-option" :class="{ active: ttsResourceId === 'seed-tts-1.0' }" @click="selectTtsModel('seed-tts-1.0')">
								<view class="model-info">
									<text class="model-name">Seed TTS 1.0</text>
									<text class="model-desc">基础模型，支持标准音色</text>
								</view>
								<view class="engine-check" v-if="ttsResourceId === 'seed-tts-1.0'">
									<view class="check-dot"></view>
								</view>
							</view>
							<view class="model-option" :class="{ active: ttsResourceId === 'seed-tts-2.0' }" @click="selectTtsModel('seed-tts-2.0')">
								<view class="model-info">
									<text class="model-name">Seed TTS 2.0</text>
									<text class="model-desc">高级模型，支持更多音色</text>
								</view>
								<view class="engine-check" v-if="ttsResourceId === 'seed-tts-2.0'">
									<view class="check-dot"></view>
								</view>
							</view>
							<view class="model-option" :class="{ active: ttsResourceId === 'seed-icl-2.0' }" @click="selectCloneVoiceModel()">
								<view class="model-info">
									<text class="model-name">声音复刻</text>
									<text class="model-desc">复刻音色，自定义音色 ID</text>
								</view>
								<view class="engine-check" v-if="ttsResourceId === 'seed-icl-2.0'">
									<view class="check-dot"></view>
								</view>
							</view>
						</view>
					</view>

					<view class="form-section">
						<text class="form-label">音色</text>
						<template v-if="ttsResourceId === 'seed-icl-2.0'">
							<view class="voice-dropdown">
								<view class="voice-trigger" @click="toggleCloneDropdown()">
									<text class="voice-trigger-text">{{ cloneVoiceDisplayName }}</text>
									<text class="voice-trigger-arrow" :class="{ open: cloneDropdownOpen }">▼</text>
								</view>
								<view class="voice-dropdown-panel" v-if="cloneDropdownOpen">
									<view v-if="cloneVoicesLoading" class="voice-dropdown-item">
										<text class="voice-name">加载中...</text>
									</view>
									<view v-else-if="cloneVoices.length === 0" class="voice-dropdown-item">
										<text class="voice-name">没有查询到可用的复刻音色</text>
									</view>
									<view v-else>
										<view class="voice-dropdown-item" :class="{ active: ttsVoiceCustom === v.speaker_id }"
											v-for="v in cloneVoices" :key="v.speaker_id" @click="selectCloneVoice(v)">
											<view class="voice-info">
												<text class="voice-name">{{ v.alias || v.speaker_id }}</text>
												<text class="voice-type">{{ v.speaker_id }}</text>
											</view>
											<view class="voice-tag" v-if="v.state === 'Active'">已激活</view>
											<view class="voice-tag" v-else>{{ v.state }}</view>
											<view class="voice-preview-btn" v-if="v.demo_audio" @click.stop="previewCloneVoice(v)">
												<text class="voice-preview-text">▶ 试听</text>
											</view>
										</view>
									</view>
								</view>
							</view>
						</template>
						<view v-else class="voice-dropdown">
							<view class="voice-trigger" @click="voiceDropdownOpen = !voiceDropdownOpen">
								<text class="voice-trigger-text">{{ voiceDisplayName || '请选择音色' }}</text>
								<text class="voice-trigger-arrow" :class="{ open: voiceDropdownOpen }">▼</text>
							</view>
							<view class="voice-dropdown-panel" v-if="voiceDropdownOpen">
								<input class="voice-dropdown-search" type="text" placeholder="搜索音色..." v-model="ttsVoiceSearch" />
								<scroll-view class="voice-dropdown-list" scroll-y>
									<view class="voice-dropdown-item" :class="{ active: ttsVoice === v.type }" v-for="v in filteredVoiceList" :key="v.type" @click="selectVoice(v)">
								<view class="voice-info">
									<text class="voice-name">{{ v.name }}</text>
									<text class="voice-type">{{ v.type }}</text>
								</view>
								<view class="voice-tag">{{ v.tag }}</view>
							</view>
								</scroll-view>
							</view>
						</view>
					</view>
				</view>

				<view class="modal-footer">
					<view class="btn-cancel" hover-class="btn-cancel-pressed" @click="hideModal">
						<text class="btn-text-cancel">取消</text>
					</view>
					<view class="btn-confirm" hover-class="btn-confirm-pressed" @click="saveTtsConfig">
						<text class="btn-text-confirm">保存</text>
					</view>
				</view>
			</view>
		</view>

		<view class="modal-mask" :class="{ show: currentModal === 'wake' }" @click="hideModal">
			<view class="modal-container" :class="{ show: currentModal === 'wake' }" @click.stop="">
				<view class="modal-header">
					<text class="modal-title">唤醒设备</text>
					<view class="modal-close" @click="hideModal">
						<view class="close-icon">
							<view class="close-line line1"></view>
							<view class="close-line line2"></view>
						</view>
					</view>
				</view>

				<view class="modal-body">
					<view class="wake-content">
						<text class="wake-text">是否唤醒 ESP32 设备？</text>
						<text class="wake-desc">唤醒后设备将进入工作状态</text>
					</view>
				</view>

				<view class="modal-footer">
					<view class="btn-cancel" hover-class="btn-cancel-pressed" @click="hideModal">
						<text class="btn-text-cancel">取消</text>
					</view>
					<view class="btn-confirm" hover-class="btn-confirm-pressed" @click="wakeDevice">
						<text class="btn-text-confirm">唤醒</text>
					</view>
				</view>
			</view>
		</view>

		<view class="modal-mask" :class="{ show: currentModal === 'speak' }" @click="hideModal">
			<view class="modal-container modal-top" :class="{ show: currentModal === 'speak' }" @click.stop="">
				<view class="modal-header">
					<text class="modal-title">说话</text>
					<view class="modal-close" @click="hideModal">
						<view class="close-icon">
							<view class="close-line line1"></view>
							<view class="close-line line2"></view>
						</view>
					</view>
				</view>

				<view class="modal-body">
					<view class="form-section">
						<text class="form-label">请输入要说的话</text>
						<textarea class="form-textarea" placeholder="输入内容后点击发送" v-model="speakText" cursor-spacing="200" :focus="speakFocus" @confirm="sendSpeak" />
					</view>
				</view>

				<view class="modal-footer">
					<view class="btn-cancel" hover-class="btn-cancel-pressed" @click="hideModal">
						<text class="btn-text-cancel">取消</text>
					</view>
					<view class="btn-confirm" hover-class="btn-confirm-pressed" @click="sendSpeak">
						<text class="btn-text-confirm">发送</text>
					</view>
				</view>
			</view>
		</view>

		<!-- ====== 音量悬浮条（不弹窗）====== -->
		<view class="volume-float" v-if="showVolumeFloat">
			<view class="volume-float-bar">
				<view class="volume-float-header">
					<text class="volume-float-icon">🔊</text>
					<text class="volume-float-val">{{ Math.round(volumeValue) }}%</text>
					<view class="volume-float-close" @click.stop="hideVolumeFloat">✕</view>
				</view>
				<view class="volume-float-slider" @touchstart="onVolumeTouchStart" @touchmove="onVolumeTouchMove">
					<view class="slider-track">
						<view class="slider-fill" :style="{ width: volumeValue + '%' }"></view>
						<view class="slider-thumb" :style="{ left: volumeValue + '%' }"></view>
					</view>
				</view>
			</view>
		</view>


				<!-- ====== 工具列表抽屉 ====== -->
		<view class="drawer-mask" :class="{ show: currentModal === 'tools' }" @click="hideModal">
			<view class="drawer-container" :class="{ show: currentModal === 'tools' }" @click.stop="">
				<view class="drawer-header">
					<text class="drawer-title">内置工具</text>
					<view class="drawer-close" @click="hideModal">
						<view class="close-icon"><view class="close-line line1"></view><view class="close-line line2"></view></view>
					</view>
				</view>
								<scroll-view class="drawer-body drawer-body-padded" scroll-y>
					<view class="mcp-loading" v-if="toolPickerLoading">
						<text class="mcp-loading-text">加载中...</text>
					</view>
					<view class="mcp-empty" v-if="!toolPickerLoading && toolPickerList.length === 0">
						<text class="mcp-empty-text">暂无内置工具</text>
						<text class="mcp-empty-sub">设备未提供可用内置工具</text>
					</view>
					<view class="tool-list" v-if="!toolPickerLoading && toolPickerList.length > 0">
						<view class="tool-card" v-for="(tool, idx) in toolPickerList" :key="idx">
							<view class="tool-card-top">
								<text class="tool-name">{{ tool.name }}</text>
								<text class="tool-type-tag">内置</text>
							</view>
							<text class="tool-desc" :style="{ maxHeight: tool._descCollapsed ? '72rpx' : '600rpx' }">{{ tool.description || '暂无描述' }}</text>
							<text class="tool-expand" @click="tool._descCollapsed = !tool._descCollapsed">{{ tool._descCollapsed ? '展开' : '收起' }}</text>
						</view>
					</view>
				</scroll-view>
			</view>
		</view>

		<!-- ====== 表情抽屉 ====== -->
		<view class="drawer-mask" :class="{ show: currentModal === 'emo' }" @click="hideModal">
			<view class="drawer-container" :class="{ show: currentModal === 'emo' }" @click.stop="">
				<view class="drawer-header">
					<text class="drawer-title">表情包管理</text>
					<view class="drawer-close" @click="hideModal">
						<view class="close-icon">
							<view class="close-line line1"></view>
							<view class="close-line line2"></view>
						</view>
					</view>
				</view>
				<scroll-view class="drawer-body" scroll-y>
					<!-- 表情包选择器 -->
					<view class="emo-pack-bar">
						<scroll-view scroll-x class="emo-pack-scroll">
							<view class="emo-pack-list">
								<view
									class="emo-pack-tab"
									v-for="(pack, idx) in emoPackList"
									:key="pack.name"
									:class="{ active: activePack === pack.name }"
									@click="switchPack(pack.name)"
									@longpress="confirmDeletePack(pack.name)"
								>
									<text class="emo-pack-tab-text">{{ pack.display_name || pack.name }}</text>
									<text class="emo-pack-tab-count">{{ pack.count }}</text>
								</view>
								<view class="emo-pack-tab emo-pack-add" @click="promptCreatePack">
									<text class="emo-pack-tab-text">+</text>
								</view>
							</view>
						</scroll-view>
				</view>

				<!-- 上传尺寸选择器 -->
				<view class="emo-size-bar">
					<text class="emo-size-label">上传尺寸</text>
					<view class="emo-size-options">
						<view
							class="emo-size-opt"
							v-for="opt in emoSizeOptions"
							:key="opt.value"
							:class="{ active: emoResizeSize === opt.value }"
							@click="emoResizeSize = opt.value"
						>
							<text class="emo-size-opt-text">{{ opt.label }}</text>
						</view>
					</view>
				</view>

				<!-- 表情网格：始终显示13个标准表情槽位 -->
					<view class="emo-grid">
						<view class="emo-item" v-for="(emo, idx) in emoList" :key="idx" @click="pickAndUpload(idx)">
							<image class="emo-img" v-if="emo.url" :src="emo.url" mode="scaleToFill"></image>
							<text class="emo-empty" v-else>+</text>
							<text class="emo-name">{{ emo.name || '' }}</text>
						</view>
					</view>
				</scroll-view>
				<view class="drawer-footer">
					<view class="btn-cancel" hover-class="btn-cancel-pressed" @click="hideModal">
						<text class="btn-text-cancel">关闭</text>
					</view>
					<view class="btn-confirm" hover-class="btn-confirm-pressed" @click="applyPack">
						<text class="btn-text-confirm">应用到设备</text>
					</view>
				</view>
			</view>
		</view>

		<!-- 新建表情包弹窗 -->
		<view class="dialog-mask" :class="{ show: emoCreateVisible }" @click="emoCreateVisible = false">
			<view class="dialog-box" :class="{ show: emoCreateVisible }" @click.stop="">
				<text class="dialog-title">新建表情包</text>
				<input
					class="dialog-input"
					v-model="emoCreateName"
					placeholder="输入名称（如：可爱风格）"
					:focus="emoCreateVisible"
					@confirm="doCreatePack"
				/>
				<view class="dialog-actions">
					<view class="dialog-btn dialog-btn-cancel" @click="emoCreateVisible = false">
						<text class="dialog-btn-text cancel">取消</text>
					</view>
					<view class="dialog-btn dialog-btn-confirm" @click="doCreatePack">
						<text class="dialog-btn-text confirm">创建</text>
					</view>
				</view>
			</view>
		</view>

		<!-- 删除确认弹窗 -->
		<view class="dialog-mask" :class="{ show: emoDeleteVisible }" @click="emoDeleteVisible = false">
			<view class="dialog-box" :class="{ show: emoDeleteVisible }" @click.stop="">
				<text class="dialog-title">删除表情包</text>
				<text class="dialog-msg">确定要删除「{{ emoDeleteDisplayName }}」吗？</text>
				<view class="dialog-actions">
					<view class="dialog-btn dialog-btn-cancel" @click="emoDeleteVisible = false">
						<text class="dialog-btn-text cancel">取消</text>
					</view>
					<view class="dialog-btn dialog-btn-danger" @click="doDeletePack">
						<text class="dialog-btn-text danger">删除</text>
					</view>
				</view>
			</view>
		</view>

		<view class="drawer-mask" :class="{ show: currentModal === 'devices' }" @click="hideModal">
			<view class="drawer-container" :class="{ show: currentModal === 'devices' }" @click.stop="">
				<view class="drawer-header">
					<text class="drawer-title">设备管理</text>
					<view class="drawer-close" @click="hideModal">
						<view class="close-icon"><view class="close-line line1"></view><view class="close-line line2"></view></view>
					</view>
				</view>
				<scroll-view class="drawer-body" scroll-y style="padding-top:20rpx;">
					<!-- 设备列表 -->
					<text class="no-device-text" v-if="deviceList.length === 0 && !showBindForm" style="padding:40rpx 0;text-align:center;">暂无已配网设备</text>
					<view class="device-list" v-if="deviceList.length > 0">
						<view class="device-card" v-for="(device, index) in deviceList" :key="device.id || index"
							:class="{ active: currentDevice && currentDevice.id === device.id }"
							@click="selectDevice(device)">
							<view class="device-card-left">
								<view class="device-card-icon"><view class="device-card-dot"></view></view>
								<view class="device-card-info">
									<text class="device-card-name">{{ device.name || device.mac?.substring(0, 8) || '设备' }}</text>
									<text class="device-card-mac">MAC: {{ device.mac ? device.mac.substring(0, 17) : '待同步' }}</text>
								</view>
							</view>
							<view class="device-card-right">
								<view class="device-card-status">
									<view class="status-dot" :class="{ connected: device.online }"></view>
									<text class="status-text">{{ device.online ? '在线' : '离线' }}</text>
								</view>
								<view class="device-del" @click.stop="unbindDevice(device)"><text class="device-del-text">解绑</text></view>
							</view>
						</view>
					</view>
					<!-- 绑定设备 -->
					<view v-if="!showBindForm" style="padding:24rpx 32rpx;">
						<view class="profile-btn" hover-class="profile-btn-p" @click="showBindForm = true">
							<text class="profile-btn-text">+ 绑定设备</text>
						</view>
					</view>
					<view v-if="showBindForm" style="padding:24rpx 32rpx;border-top:1rpx solid #eee;">
						<view class="profile-input-row" style="margin-bottom:16rpx;">
							<text class="profile-input-label" style="width:auto;margin-right:12rpx;">设备名称</text>
							<input class="profile-input" type="text" placeholder="给设备起个名字（可选）" v-model="bindNameInput" style="flex:1;" />
						</view>
						<view class="profile-input-row" style="margin-bottom:16rpx;">
							<text class="profile-input-label" style="width:auto;margin-right:12rpx;">绑定码</text>
							<input class="profile-input" type="text" placeholder="设备屏幕显示的6位码" v-model="bindCodeInput" style="flex:1;" />
						</view>
						<view style="display:flex;gap:12rpx;">
							<view class="profile-btn" style="flex:1;background:#e0e0e0;" hover-class="profile-btn-p" @click="showBindForm = false; bindCodeInput=''; bindNameInput=''">
								<text class="profile-btn-text" style="color:#666;">取消</text>
							</view>
							<view class="profile-btn" style="flex:1;" hover-class="profile-btn-p" @click="doBindDevice">
								<text class="profile-btn-text">绑定</text>
							</view>
						</view>
					</view>
				</scroll-view>
			</view>
		</view>
	</view>
</template>

<script setup>
	import { ref, reactive, onMounted, computed } from 'vue'
	import { isLoggedIn, getUser, logout, getServerUrl, setServerUrl, callApi, getDevices, login, register, isTokenExpired, setAuthExpiredCallback, getToken } from '../../store/auth.js'

	const currentModal = ref('')
	const modalAnim = ref(1)
	const currentTab = ref('home')

	// ===== 我的 Tab 状态 =====
	const profileFormMode = ref('login')
	const profileEmail = ref('')
	const profilePassword = ref('')
	const profileNickname = ref('')
	const profileShowPwd = ref(false)
	const profileLoading = ref(false)
	const profileErr = ref('')
	const profileServerUrl = ref(getServerUrl())
	// 响应式登录状态（避免直接调用 isLoggedIn() 导致模板不更新）
	const isLoggedInRef = ref(isLoggedIn())
	// 服务器地址折叠状态（默认折叠）
	const profileServerCollapsed = ref(true)
	const profileWakeCollapsed = ref(true)
	const profileProactiveCollapsed = ref(true)
	const profileWakeText = ref('我在呢')
	const profileWakeAudioEn = ref(true)
	const profileWakeSource = ref('tts')
	const profileWakeNextRound = ref(false)
	const bindCodeInput = ref('')
	const bindNameInput = ref('')
	const showBindForm = ref(false)

	// ===== 微信绑定状态 =====
	const wechatCollapsed = ref(true)
	const wechatQrDataUrl = ref('')
	const wechatQrStatus = ref('idle')
	const wechatQrMessage = ref('')
	const wechatSessionKey = ref('')
	const wechatQrPolling = ref(false)
	const wechatBotToken = ref('')
	const wechatBoundDeviceKey = ref('')
	const wechatBoundWechatId = ref('')
	const wechatGroupId = ref('')             // 群聊 chat_id
	const recentGroups = ref([])              // 可选群聊列表
	const groupPickIndex = ref(-1)            // 群聊选择器索引
	const wechatQrTimer = ref(null)

	// 加载已保存的微信绑定信息
	onMounted(() => {
		const saved = uni.getStorageSync('wechat_bind_info')
		if (saved) {
			try {
				const info = JSON.parse(saved)
				wechatBoundDeviceKey.value = info.device_key || ''
				wechatBoundWechatId.value = info.wechat_chat_id || ''
				wechatGroupId.value = info.wechat_group_id || ''
			} catch(e) {}
		}
	})

	const switchTab = (t) => {
		currentTab.value = t
		if (t === 'home' && currentDevice.value && currentDevice.value.deviceIp) {
			autoSyncDevice()
		}
		if (t === 'skills') {
			loadSkills()
		}
		if (t === 'store') {
			loadPlugins()
		}
	}
	const bleScanning = ref(false)
	const bleScanTip = ref('点击「开始扫描」搜索设备')
	const bleDevices = ref([])
	const bleSelectedDevice = ref(null)
	const bleConnecting = ref(false)
	const bleShowPwd = ref(false)
	const bleWifiSsid = ref('')
	const bleWifiPwd = ref('')
	const bleWakeIdx = ref(0)
	const bleSvcType = ref('official')
	const bleSvcProtocolIdx = ref(0)
	const bleSvcHost = ref('')
	const bleSvcPort = ref('8088')
	const bleSvcApiKey = ref('') // 开放平台 API Key（设备连接官方服务鉴权用）
	const bleKwhEn = ref(true)
	const bleVolEn = ref(false)
	const bleVolPin = ref('7')
	const bleLightsData = ref('18')
	const bleOledSck = ref('38')
	const bleOledSda = ref('39')
	const bleMicBck = ref('4')
	const bleMicWs = ref('5')
	const bleMicData = ref('6')
	const bleSpkData = ref('15')
	const bleSpkBck = ref('16')
	const bleSpkWs = ref('17')
	const bleShowAdv = ref(false)
	let bleDeviceIds = new Set()

	const bleSignalLevel = (rssi) => {
		if (rssi == null) return 0
		if (rssi > -50) return 4
		if (rssi > -65) return 3
		if (rssi > -75) return 2
		if (rssi > -85) return 1
		return 0
	}

	const showBlePicker = (items, cb) => {
		uni.showActionSheet({ itemList: items, success: (e) => cb(e.tapIndex) })
	}

	const bleToggleScan = () => {
		if (bleScanning.value) { bleStopScan(); return }
		bleDevices.value = []; bleSelectedDevice.value = null; bleDeviceIds = new Set()
		uni.openBluetoothAdapter({
			success: () => {
				uni.startBluetoothDevicesDiscovery({
					allowDuplicatesKey: false,
					success: () => { bleScanning.value = true; bleScanTip.value = '正在扫描...' },
					fail: () => { uni.showToast({ title: '扫描启动失败', icon: 'none' }) }
				})
				uni.onBluetoothDeviceFound((res) => {
					for (const dev of (res.devices || [])) {
						const name = (dev.name || dev.localName || '').trim().toUpperCase()
						if (!name || !name.startsWith('ESP')) continue
						if (bleDeviceIds.has(dev.deviceId)) {
							const idx = bleDevices.value.findIndex(d => d.deviceId === dev.deviceId)
							if (idx >= 0) bleDevices.value[idx] = { ...bleDevices.value[idx], ...dev }
						} else {
							bleDeviceIds.add(dev.deviceId)
							bleDevices.value.push(dev)
						}
					}
					if (bleDevices.value.length > 0) bleScanTip.value = '发现 ' + bleDevices.value.length + ' 个设备'
				})
			},
			fail: () => { uni.showToast({ title: '请打开手机蓝牙', icon: 'none' }) }
		})
	}

	const bleStopScan = () => {
		bleScanning.value = false
		try { uni.stopBluetoothDevicesDiscovery({}) } catch(e) {}
		bleScanTip.value = bleDevices.value.length > 0 ? '发现 ' + bleDevices.value.length + ' 个设备' : '扫描已停止'
	}

	const bleSelectDevice = (device) => { bleSelectedDevice.value = device; bleStopScan() }

	const bleStr2ab = (str) => {
		const buf = new ArrayBuffer(str.length)
		const v = new Uint8Array(buf)
		for (let i = 0; i < str.length; i++) v[i] = str.charCodeAt(i) & 0xFF
		return buf
	}
	const bleDelay = (ms) => new Promise(r => setTimeout(r, ms))
	const bleWrite = (did, sid, cid, val) => new Promise((res, rej) => { uni.writeBLECharacteristicValue({ deviceId: did, serviceId: sid, characteristicId: cid, value: val, success: res, fail: rej }) })

	const bleSendConfig = async () => {
		try {
			const ssid = bleWifiSsid.value.trim()
			if (!ssid) { uni.showToast({ title: '请输入 WiFi 名称', icon: 'none' }); return }
			if (!bleWifiPwd.value.trim()) { uni.showToast({ title: '请输入 WiFi 密码', icon: 'none' }); return }
			bleConnecting.value = true
			if (bleScanning.value) bleStopScan()
			const did = bleSelectedDevice.value.deviceId
			// 先查一下当前连接状态
			try {
				const r = await new Promise((res) => { uni.getBLEDeviceServices({ deviceId: did, success: res, fail: () => res(null) }) })
				if (r && r.services) { // 已经连接，先断开
					await new Promise(r2 => { uni.closeBLEConnection({ deviceId: did, success: r2, fail: r2 }) })
					await bleDelay(500)
				}
			} catch(e) {}
			await bleDelay(300)
			uni.showLoading({ title: '连接设备...', mask: true })
			try { await new Promise((res, rej) => { uni.createBLEConnection({ deviceId: did, timeout: 10000, success: res, fail: rej }) }) }
			catch(e) { uni.hideLoading(); bleConnecting.value = false; uni.showToast({ title: '连接失败: ' + (e.errMsg || e.message || ''), icon: 'none', duration: 2000 }); return }
			await bleDelay(500)
			uni.showLoading({ title: '获取服务...', mask: true })
			let svc
			try {
				const r = await new Promise((res, rej) => { uni.getBLEDeviceServices({ deviceId: did, success: res, fail: rej }) })
				const svcs = r.services || []
				if (svcs.length === 0) { uni.hideLoading(); bleConnecting.value = false; uni.showToast({ title: '设备无BLE服务', icon: 'none' }); return }
				svc = svcs.find(s => s.uuid.toUpperCase().includes('BAAD')) || svcs[0]
			} catch(e) { uni.hideLoading(); bleConnecting.value = false; uni.showToast({ title: '获取服务失败: ' + (e.errMsg || e.message || ''), icon: 'none', duration: 2000 }); return }
			uni.showLoading({ title: '获取特征值...', mask: true })
			let ch
			try {
				const r = await new Promise((res, rej) => { uni.getBLEDeviceCharacteristics({ deviceId: did, serviceId: svc.uuid, success: res, fail: rej }) })
				const chs = r.characteristics || []
				ch = chs.find(c => c.uuid.toUpperCase().includes('F00D') && (c.properties.write || c.properties.writeNoResponse))
					|| chs.find(c => c.properties.write || c.properties.writeNoResponse)
					|| chs.find(c => c.uuid.toUpperCase().includes('F00D'))
					|| chs[0]
				if (!ch) { uni.hideLoading(); bleConnecting.value = false; uni.showToast({ title: '设备无可写特征值', icon: 'none' }); return }
			} catch(e) { uni.hideLoading(); bleConnecting.value = false; uni.showToast({ title: '获取特征值失败: ' + (e.errMsg || e.message || ''), icon: 'none', duration: 2000 }); return }
			uni.showLoading({ title: '发送配网数据...', mask: true })
			const wt = ['boot','asrpro','asrpro_boot','pin_high','pin_low','boot_listen','pin_high_listen']
			const payload = {
				wifi_name: ssid, wifi_pwd: bleWifiPwd.value.trim(),
				ext7: wt[bleWakeIdx.value],
				kwh_enable: bleKwhEn.value ? '1' : '0', volume_enable: bleVolEn.value ? '1' : '0', volume_pin: bleVolPin.value || '7',
				mic_bck: bleMicBck.value || '4', mic_ws: bleMicWs.value || '5', mic_data: bleMicData.value || '6',
				speaker_bck: bleSpkBck.value || '16', speaker_ws: bleSpkWs.value || '17', speaker_data: bleSpkData.value || '15',
				lights_data: bleLightsData.value || '18', oled_sck: bleOledSck.value || '38', oled_sda: bleOledSda.value || '39'
			}
			if (bleSvcType.value === 'official') {
				const key = bleSvcApiKey.value.trim()
				if (!key) { uni.hideLoading(); bleConnecting.value = false; uni.showToast({ title: '请输入开放平台密钥', icon: 'none' }); return }
				payload.api_key = key
				payload.ext1 = key // 兼容以 ext1 读取的固件
			} else if (bleSvcType.value === 'custom') {
				payload.ext4 = ['http','https'][bleSvcProtocolIdx.value]
				payload.ext5 = bleSvcHost.value.trim()
				payload.ext6 = bleSvcPort.value.trim() || '8088'
			}
			const data = bleStr2ab(encodeURIComponent(JSON.stringify(payload)))
			const cs = 20, tc = Math.ceil(data.byteLength / cs)
			for (let i = 0; i < tc; i++) {
				const s = i * cs, e = Math.min(s + cs, data.byteLength)
				await bleWrite(did, svc.uuid, ch.uuid, data.slice(s, e))
				await bleDelay(50)
			}
			await bleDelay(100)
			await bleWrite(did, svc.uuid, ch.uuid, bleStr2ab('--END--'))
			uni.hideLoading(); bleConnecting.value = false
			const deviceIp = bleSvcType.value === 'custom' ? bleSvcHost.value.trim() : ''
			// 配网后不自动添加设备到列表，设备连上服务器后会生成绑定码
			// 用户输入绑定码绑定成功后设备才会出现
			uni.showToast({ title: '配网成功！请查看设备屏幕上的绑定码，在「设备管理」中输入完成绑定', icon: 'success', duration: 3000 })
			// 等设备连上WiFi再自动同步状态
			setTimeout(() => { autoSyncDevice() }, 8000)
			setTimeout(() => { autoSyncDevice() }, 15000)
			setTimeout(() => { autoSyncDevice() }, 30000)
			setTimeout(() => { try { uni.closeBLEConnection({ deviceId: did }) } catch(e) {} }, 2000)
		} catch(e) {
			uni.hideLoading(); bleConnecting.value = false
			const msg = e.message || e.errMsg || '未知错误'
			uni.showToast({ title: '配网失败: ' + msg, icon: 'none', duration: 3000 })
			console.log('BLE配网错误:', msg, e)
		}
	}

	const asrEngine = ref('bytedance')
	const showKey = ref({ bytedance: false, tencent: false, deepseek: false, tts: false, volcAk: false, volcSk: false })
	const bytedanceApiKey = ref('')
	const tencentAppId = ref('')
	const tencentSecretId = ref('')
	const tencentSecretKey = ref('')

	const deepseekApiKey = ref('')
	const llmModel = ref('deepseek-v4-flash')
	const llmPrompt = ref('')

	const ttsResourceId = ref('seed-tts-2.0')
	const ttsApiKey = ref('')
	const ttsVoice = ref('')
	// 自定义音色 ID(复刻音色等,不在预设列表里的音色)
	const ttsVoiceCustom = ref('')
	// 设备级火山 OpenAPI 密钥(存 tts_config.volc_openapi,查询复刻音色列表用;留空回退环境变量)
	const volcAkId = ref('')
	const volcSk = ref('')
	const volcProjectName = ref('default')
	const volcCredOpen = ref(false)  // 折叠区开关(默认收起)
	const ttsVoiceList2 = [
		{ name: 'Vivi 2.0', type: 'zh_female_vv_uranus_bigtts', tag: '通用' },
		{ name: '小何 2.0', type: 'zh_female_xiaohe_uranus_bigtts', tag: '通用' },
		{ name: '云舟 2.0', type: 'zh_male_m191_uranus_bigtts', tag: '通用' },
		{ name: '小天 2.0', type: 'zh_male_taocheng_uranus_bigtts', tag: '通用' },
		{ name: '刘飞 2.0', type: 'zh_male_liufei_uranus_bigtts', tag: '通用' },
		{ name: '魅力苏菲 2.0', type: 'zh_female_sophie_uranus_bigtts', tag: '通用' },
		{ name: '清新女声 2.0', type: 'zh_female_qingxinnvsheng_uranus_bigtts', tag: '角色' },
		{ name: '知性灿灿 2.0', type: 'zh_female_cancan_uranus_bigtts', tag: '角色' },
		{ name: '撒娇学妹 2.0', type: 'zh_female_sajiaoxuemei_uranus_bigtts', tag: '通用' },
		{ name: '甜美小源 2.0', type: 'zh_female_tianmeixiaoyuan_uranus_bigtts', tag: '通用' },
		{ name: '甜美桃子 2.0', type: 'zh_female_tianmeitaozi_uranus_bigtts', tag: '通用' },
		{ name: '爽快思思 2.0', type: 'zh_female_shuangkuaisisi_uranus_bigtts', tag: '配音' },
		{ name: '佩奇猪 2.0', type: 'zh_female_peiqi_uranus_bigtts', tag: '抖音' },
		{ name: '邻家女孩 2.0', type: 'zh_female_linjianvhai_uranus_bigtts', tag: '通用' },
		{ name: '少年梓辛 2.0', type: 'zh_male_shaonianzixin_uranus_bigtts', tag: '配音' },
		{ name: '猴哥 2.0', type: 'zh_male_sunwukong_uranus_bigtts', tag: '教育' },
		{ name: 'Tina老师 2.0', type: 'zh_female_yingyujiaoxue_uranus_bigtts', tag: '客服' },
		{ name: '暖阳女声 2.0', type: 'zh_female_kefunvsheng_uranus_bigtts', tag: '阅读' },
		{ name: '儿童绘本 2.0', type: 'zh_female_xiaoxue_uranus_bigtts', tag: '阅读' },
		{ name: '大壹 2.0', type: 'zh_male_dayi_uranus_bigtts', tag: '配音' },
		{ name: '黑猫侦探 2.0', type: 'zh_female_mizai_uranus_bigtts', tag: '配音' },
		{ name: '鸡汤女 2.0', type: 'zh_female_jitangnv_uranus_bigtts', tag: '通用' },
		{ name: '魅力女友 2.0', type: 'zh_female_meilinvyou_uranus_bigtts', tag: '配音' },
		{ name: '流畅女声 2.0', type: 'zh_female_liuchangnv_uranus_bigtts', tag: '配音' },
		{ name: '儒雅逸辰 2.0', type: 'zh_male_ruyayichen_uranus_bigtts', tag: '配音' },
		{ name: 'Tim', type: 'en_male_tim_uranus_bigtts', tag: '英文' },
		{ name: 'Dacey', type: 'en_female_dacey_uranus_bigtts', tag: '英文' },
		{ name: 'Stokie', type: 'en_female_stokie_uranus_bigtts', tag: '英文' },
		{ name: '温柔妈妈 2.0', type: 'zh_female_wenroumama_uranus_bigtts', tag: '通用' },
		{ name: '解说小明 2.0', type: 'zh_male_jieshuoxiaoming_uranus_bigtts', tag: '通用' },
		{ name: 'TVB女声 2.0', type: 'zh_female_tvbnv_uranus_bigtts', tag: '通用' },
		{ name: '译制片男 2.0', type: 'zh_male_yizhipiannan_uranus_bigtts', tag: '通用' },
		{ name: '俏皮女声 2.0', type: 'zh_female_qiaopinv_uranus_bigtts', tag: '角色' },
		{ name: '直率英子 2.0', type: 'zh_female_zhishuaiyingzi_uranus_bigtts', tag: '抖音' },
		{ name: '邻家男孩 2.0', type: 'zh_male_linjiananhai_uranus_bigtts', tag: '角色' },
		{ name: '四郎 2.0', type: 'zh_male_silang_uranus_bigtts', tag: '抖音' },
		{ name: '儒雅青年 2.0', type: 'zh_male_ruyaqingnian_uranus_bigtts', tag: '番茄' },
		{ name: '擎苍 2.0', type: 'zh_male_qingcang_uranus_bigtts', tag: '角色' },
		{ name: '熊二 2.0', type: 'zh_male_xionger_uranus_bigtts', tag: '抖音' },
		{ name: '樱桃丸子 2.0', type: 'zh_female_yingtaowanzi_uranus_bigtts', tag: '抖音' },
		{ name: '温暖阿虎 2.0', type: 'zh_male_wennuanahu_uranus_bigtts', tag: '通用' },
		{ name: '奶气萌娃 2.0', type: 'zh_male_naiqimengwa_uranus_bigtts', tag: '抖音' },
		{ name: '婆婆 2.0', type: 'zh_female_popo_uranus_bigtts', tag: '抖音' },
		{ name: '高冷御姐 2.0', type: 'zh_female_gaolengyujie_uranus_bigtts', tag: '通用' },
		{ name: '傲娇霸总 2.0', type: 'zh_male_aojiaobazong_uranus_bigtts', tag: '通用' },
		{ name: '懒音绵宝 2.0', type: 'zh_male_lanyinmianbao_uranus_bigtts', tag: '角色' },
		{ name: '反卷青年 2.0', type: 'zh_male_fanjuanqingnian_uranus_bigtts', tag: '通用' },
		{ name: '温柔淑女 2.0', type: 'zh_female_wenroushunv_uranus_bigtts', tag: '番茄' },
		{ name: '古风少御 2.0', type: 'zh_female_gufengshaoyu_uranus_bigtts', tag: '角色' },
		{ name: '活力小哥 2.0', type: 'zh_male_huolixiaoge_uranus_bigtts', tag: '通用' },
		{ name: '霸气青叔 2.0', type: 'zh_male_baqiqingshu_uranus_bigtts', tag: '阅读' },
		{ name: '悬疑解说 2.0', type: 'zh_male_xuanyijieshuo_uranus_bigtts', tag: '抖音' },
		{ name: '萌丫头 2.0', type: 'zh_female_mengyatou_uranus_bigtts', tag: '通用' },
		{ name: '贴心女声 2.0', type: 'zh_female_tiexinnvsheng_uranus_bigtts', tag: '通用' },
		{ name: '鸡汤妹妹 2.0', type: 'zh_female_jitangmei_uranus_bigtts', tag: '抖音' },
		{ name: '磁性解说 2.0', type: 'zh_male_cixingjieshuonan_uranus_bigtts', tag: '抖音' },
		{ name: '亮嗓萌仔 2.0', type: 'zh_male_liangsangmengzai_uranus_bigtts', tag: '通用' },
		{ name: '开朗姐姐 2.0', type: 'zh_female_kailangjiejie_uranus_bigtts', tag: '通用' },
		{ name: '高冷沉稳 2.0', type: 'zh_male_gaolengchenwen_uranus_bigtts', tag: '通用' },
		{ name: '深夜播客 2.0', type: 'zh_male_shenyeboke_uranus_bigtts', tag: '角色' },
		{ name: '鲁班七号 2.0', type: 'zh_male_lubanqihao_uranus_bigtts', tag: '抖音' },
		{ name: '林潇 2.0', type: 'zh_female_linxiao_uranus_bigtts', tag: '抖音' },
		{ name: '玲玲姐姐 2.0', type: 'zh_female_lingling_uranus_bigtts', tag: '抖音' },
		{ name: '春日部姐姐 2.0', type: 'zh_female_chunribu_uranus_bigtts', tag: '抖音' },
		{ name: '唐僧 2.0', type: 'zh_male_tangseng_uranus_bigtts', tag: '抖音' },
		{ name: '庄周 2.0', type: 'zh_male_zhuangzhou_uranus_bigtts', tag: '抖音' },
		{ name: '开朗弟弟 2.0', type: 'zh_male_kailangdidi_uranus_bigtts', tag: '抖音' },
		{ name: '猪八戒 2.0', type: 'zh_male_zhubajie_uranus_bigtts', tag: '抖音' },
		{ name: '感冒电音 2.0', type: 'zh_female_ganmaodianyin_uranus_bigtts', tag: '抖音' },
		{ name: '谄媚女声 2.0', type: 'zh_female_chanmeinv_uranus_bigtts', tag: '抖音' },
		{ name: '女雷神 2.0', type: 'zh_female_nvleishen_uranus_bigtts', tag: '抖音' },
		{ name: '亲切女声 2.0', type: 'zh_female_qinqienv_uranus_bigtts', tag: '豆包' },
		{ name: '快乐小东 2.0', type: 'zh_male_kuailexiaodong_uranus_bigtts', tag: '豆包' },
		{ name: '开朗学长 2.0', type: 'zh_male_kailangxuezhang_uranus_bigtts', tag: '豆包' },
		{ name: '悠悠君子 2.0', type: 'zh_male_youyoujunzi_uranus_bigtts', tag: '豆包' },
		{ name: '文静毛毛 2.0', type: 'zh_female_wenjingmaomao_uranus_bigtts', tag: '豆包' },
		{ name: '知性女声 2.0', type: 'zh_female_zhixingnv_uranus_bigtts', tag: '通用' },
		{ name: '清爽男大 2.0', type: 'zh_male_qingshuangnanda_uranus_bigtts', tag: '豆包' },
		{ name: '渊博小叔 2.0', type: 'zh_male_yuanboxiaoshu_uranus_bigtts', tag: '通用' },
		{ name: '阳光青年 2.0', type: 'zh_male_yangguangqingnian_uranus_bigtts', tag: '通用' },
		{ name: '清澈梓梓 2.0', type: 'zh_female_qingchezizi_uranus_bigtts', tag: '通用' },
		{ name: '甜美悦悦 2.0', type: 'zh_female_tianmeiyueyue_uranus_bigtts', tag: '通用' },
		{ name: '心灵鸡汤 2.0', type: 'zh_female_xinlingjitang_uranus_bigtts', tag: '通用' },
		{ name: '温柔小哥 2.0', type: 'zh_male_wenrouxiaoge_uranus_bigtts', tag: '通用' },
		{ name: '柔美女友 2.0', type: 'zh_female_roumeinvyou_uranus_bigtts', tag: '通用' },
		{ name: '东方浩然 2.0', type: 'zh_male_dongfanghaoran_uranus_bigtts', tag: '通用' },
		{ name: '温柔小雅 2.0', type: 'zh_female_wenrouxiaoya_uranus_bigtts', tag: '通用' },
		{ name: '天才童声 2.0', type: 'zh_male_tiancaitongsheng_uranus_bigtts', tag: '角色' },
		{ name: '武则天 2.0', type: 'zh_female_wuzetian_uranus_bigtts', tag: '角色' },
		{ name: '顾姐 2.0', type: 'zh_female_gujie_uranus_bigtts', tag: '抖音' },
		{ name: '广告解说 2.0', type: 'zh_male_guanggaojieshuo_uranus_bigtts', tag: '剪映' },
		{ name: '少儿故事 2.0', type: 'zh_female_shaoergushi_uranus_bigtts', tag: '阅读' },
		{ name: '调皮公主', type: 'saturn_zh_female_tiaopigongzhu_tob', tag: '角色' },
		{ name: '爽朗少年', type: 'saturn_zh_male_shuanglangshaonian_tob', tag: '角色' },
		{ name: '天才同桌', type: 'saturn_zh_male_tiancaitongzhuo_tob', tag: '角色' },
		{ name: '知性灿灿', type: 'saturn_zh_female_cancan_tob', tag: '角色' },
		{ name: '傲娇女友 2.0', type: 'saturn_zh_female_aojiaonvyou_tob', tag: '角色' },
		{ name: '病娇姐姐 2.0', type: 'saturn_zh_female_bingjiaojiejie_tob', tag: '角色' },
		{ name: '成熟姐姐 2.0', type: 'saturn_zh_female_chengshujiejie_tob', tag: '角色' },
		{ name: '可爱女生 2.0', type: 'saturn_zh_female_keainvsheng_tob', tag: '角色' },
		{ name: '暖心学姐 2.0', type: 'saturn_zh_female_nuanxinxuejie_tob', tag: '角色' },
		{ name: '贴心女友 2.0', type: 'saturn_zh_female_tiexinnvyou_tob', tag: '角色' },
		{ name: '温柔文雅 2.0', type: 'saturn_zh_female_wenrouwenya_tob', tag: '通用' },
		{ name: '妩媚御姐 2.0', type: 'saturn_zh_female_wumeiyujie_tob', tag: '角色' },
		{ name: '性感御姐 2.0', type: 'saturn_zh_female_xingganyujie_tob', tag: '角色' },
		{ name: '傲气凌人 2.0', type: 'saturn_zh_male_aiqilingren_tob', tag: '角色' },
		{ name: '傲娇公子 2.0', type: 'saturn_zh_male_aojiaogongzi_tob', tag: '角色' },
		{ name: '傲娇精英 2.0', type: 'saturn_zh_male_aojiaojingying_tob', tag: '角色' },
		{ name: '傲慢少爷 2.0', type: 'saturn_zh_male_aomanshaoye_tob', tag: '角色' },
		{ name: '霸道少爷 2.0', type: 'saturn_zh_male_badaoshaoye_tob', tag: '角色' },
		{ name: '病娇白莲 2.0', type: 'saturn_zh_male_bingjiaobailian_tob', tag: '角色' },
		{ name: '不羁青年 2.0', type: 'saturn_zh_male_bujiqingnian_tob', tag: '角色' },
		{ name: '成熟总裁 2.0', type: 'saturn_zh_male_chengshuzongcai_tob', tag: '角色' },
		{ name: '磁性男嗓 2.0', type: 'saturn_zh_male_cixingnansang_tob', tag: '角色' },
		{ name: '醋精男友 2.0', type: 'saturn_zh_male_cujingnanyou_tob', tag: '角色' },
		{ name: '风发少年 2.0', type: 'saturn_zh_male_fengfashaonian_tob', tag: '角色' },
		{ name: '腹黑公子 2.0', type: 'saturn_zh_male_fuheigongzi_tob', tag: '角色' },
		{ name: '轻盈朵朵 2.0', type: 'saturn_zh_female_qingyingduoduo_cs_tob', tag: '客服' },
		{ name: '温婉珊珊 2.0', type: 'saturn_zh_female_wenwanshanshan_cs_tob', tag: '客服' },
		{ name: '热情艾娜 2.0', type: 'saturn_zh_female_reqingaina_cs_tob', tag: '客服' },
		{ name: '清新沐沐 2.0', type: 'saturn_zh_male_qingxinmumu_cs_tob', tag: '客服' },
	]
	const ttsVoiceList1 = [
		{ name: '冷酷哥哥（多情感）', type: 'zh_male_lengkugege_emo_v2_mars_bigtts', tag: '多情感' },
		{ name: '甜心小美（多情感）', type: 'zh_female_tianxinxiaomei_emo_v2_mars_bigtts', tag: '多情感' },
		{ name: '高冷御姐（多情感）', type: 'zh_female_gaolengyujie_emo_v2_mars_bigtts', tag: '多情感' },
		{ name: '傲娇霸总（多情感）', type: 'zh_male_aojiaobazong_emo_v2_mars_bigtts', tag: '多情感' },
		{ name: '广州德哥（多情感）', type: 'zh_male_guangzhoudege_emo_mars_bigtts', tag: '多情感' },
		{ name: '京腔侃爷（多情感）', type: 'zh_male_jingqiangkanye_emo_mars_bigtts', tag: '多情感' },
		{ name: '邻居阿姨（多情感）', type: 'zh_female_linjuayi_emo_v2_mars_bigtts', tag: '多情感' },
		{ name: '优柔公子（多情感）', type: 'zh_male_yourougongzi_emo_v2_mars_bigtts', tag: '多情感' },
		{ name: '儒雅男友（多情感）', type: 'zh_male_ruyayichen_emo_v2_mars_bigtts', tag: '多情感' },
		{ name: '俊朗男友（多情感）', type: 'zh_male_junlangnanyou_emo_v2_mars_bigtts', tag: '多情感' },
		{ name: '北京小爷（多情感）', type: 'zh_male_beijingxiaoye_emo_v2_mars_bigtts', tag: '多情感' },
		{ name: '柔美女友（多情感）', type: 'zh_female_roumeinvyou_emo_v2_mars_bigtts', tag: '多情感' },
		{ name: '阳光青年（多情感）', type: 'zh_male_yangguangqingnian_emo_v2_mars_bigtts', tag: '多情感' },
		{ name: '魅力女友（多情感）', type: 'zh_female_meilinvyou_emo_v2_mars_bigtts', tag: '多情感' },
		{ name: '爽快思思（多情感）', type: 'zh_female_shuangkuaisisi_emo_v2_mars_bigtts', tag: '多情感' },
		{ name: 'Candice', type: 'en_female_candice_emo_v2_mars_bigtts', tag: '英文' },
		{ name: 'Serena', type: 'en_female_skye_emo_v2_mars_bigtts', tag: '英文' },
		{ name: 'Glen', type: 'en_male_glen_emo_v2_mars_bigtts', tag: '英文' },
		{ name: 'Sylus', type: 'en_male_sylus_emo_v2_mars_bigtts', tag: '英文' },
		{ name: 'Corey', type: 'en_male_corey_emo_v2_mars_bigtts', tag: '英文' },
		{ name: 'Nadia', type: 'en_female_nadia_tips_emo_v2_mars_bigtts', tag: '英文' },
		{ name: '深夜播客', type: 'zh_male_shenyeboke_emo_v2_mars_bigtts', tag: '多情感' },
		{ name: 'Tina老师', type: 'zh_female_yingyujiaoyu_mars_bigtts', tag: '教育' },
		{ name: '温柔女神', type: 'ICL_zh_female_wenrounvshen_239eff5e8ffa_tob', tag: '豆包' },
		{ name: 'Vivi', type: 'zh_female_vv_mars_bigtts', tag: '通用' },
		{ name: '亲切女声', type: 'zh_female_qinqienvsheng_moon_bigtts', tag: '豆包' },
		{ name: '机灵小伙', type: 'ICL_zh_male_shenmi_v1_tob', tag: '通用' },
		{ name: '元气甜妹', type: 'ICL_zh_female_wuxi_tob', tag: '通用' },
		{ name: '知心姐姐', type: 'ICL_zh_female_wenyinvsheng_v1_tob', tag: '通用' },
		{ name: '阳光阿辰', type: 'zh_male_qingyiyuxuan_mars_bigtts', tag: '通用' },
		{ name: '快乐小东', type: 'zh_male_xudong_conversation_wvae_bigtts', tag: '豆包' },
		{ name: '冷酷哥哥', type: 'ICL_zh_male_lengkugege_v1_tob', tag: '豆包' },
		{ name: '纯澈女生', type: 'ICL_zh_female_feicui_v1_tob', tag: '通用' },
		{ name: '初恋女友', type: 'ICL_zh_female_yuxin_v1_tob', tag: '通用' },
		{ name: '贴心闺蜜', type: 'ICL_zh_female_xnx_tob', tag: '通用' },
		{ name: '温柔白月光', type: 'ICL_zh_female_yry_tob', tag: '通用' },
		{ name: '炀炀', type: 'ICL_zh_male_BV705_streaming_cs_tob', tag: '通用' },
		{ name: '开朗学长', type: 'en_male_jason_conversation_wvae_bigtts', tag: '豆包' },
		{ name: '魅力苏菲', type: 'zh_female_sophie_conversation_wvae_bigtts', tag: '通用' },
		{ name: '贴心妹妹', type: 'ICL_zh_female_yilin_tob', tag: '通用' },
		{ name: '甜美桃子', type: 'zh_female_tianmeitaozi_mars_bigtts', tag: '通用' },
		{ name: '清新女声', type: 'zh_female_qingxinnvsheng_mars_bigtts', tag: '通用' },
		{ name: '知性女声', type: 'zh_female_zhixingnvsheng_mars_bigtts', tag: '通用' },
		{ name: '清爽男大', type: 'zh_male_qingshuangnanda_mars_bigtts', tag: '豆包' },
		{ name: '邻家女孩', type: 'zh_female_linjianvhai_moon_bigtts', tag: '豆包' },
		{ name: '渊博小叔', type: 'zh_male_yuanboxiaoshu_moon_bigtts', tag: '豆包' },
		{ name: '阳光青年', type: 'zh_male_yangguangqingnian_moon_bigtts', tag: '豆包' },
		{ name: '甜美小源', type: 'zh_female_tianmeixiaoyuan_moon_bigtts', tag: '豆包' },
		{ name: '清澈梓梓', type: 'zh_female_qingchezizi_moon_bigtts', tag: '豆包' },
		{ name: '解说小明', type: 'zh_male_jieshuoxiaoming_moon_bigtts', tag: '豆包' },
		{ name: '开朗姐姐', type: 'zh_female_kailangjiejie_moon_bigtts', tag: '豆包' },
		{ name: '邻家男孩', type: 'zh_male_linjiananhai_moon_bigtts', tag: '豆包' },
		{ name: '甜美悦悦', type: 'zh_female_tianmeiyueyue_moon_bigtts', tag: '豆包' },
		{ name: '心灵鸡汤', type: 'zh_female_xinlingjitang_moon_bigtts', tag: '豆包' },
		{ name: '知性温婉', type: 'ICL_zh_female_zhixingwenwan_tob', tag: '猫箱' },
		{ name: '暖心体贴', type: 'ICL_zh_male_nuanxintitie_tob', tag: '猫箱' },
		{ name: '开朗轻快', type: 'ICL_zh_male_kailangqingkuai_tob', tag: '猫箱' },
		{ name: '活泼爽朗', type: 'ICL_zh_male_huoposhuanglang_tob', tag: '猫箱' },
		{ name: '率真小伙', type: 'ICL_zh_male_shuaizhenxiaohuo_tob', tag: '猫箱' },
		{ name: '温柔小哥', type: 'zh_male_wenrouxiaoge_mars_bigtts', tag: '通用' },
		{ name: '灿灿/Shiny', type: 'zh_female_cancan_mars_bigtts', tag: '通用' },
		{ name: '爽快思思/Skye', type: 'zh_female_shuangkuaisisi_moon_bigtts', tag: '豆包' },
		{ name: '温暖阿虎/Alvin', type: 'zh_male_wennuanahu_moon_bigtts', tag: '豆包' },
		{ name: '少年梓辛/Brayan', type: 'zh_male_shaonianzixin_moon_bigtts', tag: '豆包' },
	]
	const ttsVoiceSearch = ref('')
	const voiceDropdownOpen = ref(false)
	const voiceDisplayName = computed(() => {
		if (ttsResourceId.value === 'seed-icl-2.0') return ttsVoiceCustom.value || '输入复刻音色 ID'
		if (!ttsVoice.value) return ''
		const list = ttsResourceId.value === 'seed-tts-2.0' ? ttsVoiceList2 : ttsVoiceList1
		const found = list.find(v => v.type === ttsVoice.value)
		return found ? found.name : ttsVoice.value
	})
	const filteredVoiceList = computed(() => {
		const list = ttsResourceId.value === 'seed-tts-2.0' ? ttsVoiceList2 : ttsVoiceList1
		const q = ttsVoiceSearch.value.trim().toLowerCase()
		if (!q) return list
		return list.filter(v => v.name.toLowerCase().includes(q) || v.type.toLowerCase().includes(q) || v.tag.includes(q))
	})
	const selectVoice = (v) => {
		ttsVoice.value = v.type
		voiceDropdownOpen.value = false
		ttsVoiceSearch.value = ''
	}
	// 选择"声音复刻"模型:音色区切换为自定义输入框,填入复刻音色 ID
	const selectCloneVoiceModel = () => {
		ttsResourceId.value = 'seed-icl-2.0'
		ttsVoice.value = '__custom__'
		voiceDropdownOpen.value = false
		ttsVoiceSearch.value = ''
		loadCloneVoices()  // 拉取账号下已有的复刻音色列表
	}
	// 选择预设模型(Seed TTS 1.0/2.0):清理复刻模式的 __custom__ 残留
	const selectTtsModel = (rid) => {
		ttsResourceId.value = rid
		if (ttsVoice.value === '__custom__') ttsVoice.value = ''
		voiceDropdownOpen.value = false
	}

	// ===== 已有复刻音色列表(火山 OpenAPI 查询) =====
	const cloneVoices = ref([])
	const cloneVoicesLoading = ref(false)
	const cloneDropdownOpen = ref(false)

	const loadCloneVoices = async () => {
		if (cloneVoicesLoading.value) return
		cloneVoicesLoading.value = true
		try {
			const dev = currentDevice.value
			const deviceKey = (dev && dev.mac) || (dev && dev.id) || ''
			// mac 用于服务端按设备配置读取火山 OpenAPI 凭据(数据库优先,回退环境变量)
			const url = '/api/v1/tts/clone-voices?mac=' + encodeURIComponent(deviceKey)
			const res = await callDeviceApi(url, 'GET')
			if (res && res.data && res.data.code === 0 && res.data.data && Array.isArray(res.data.data.voices)) {
				cloneVoices.value = res.data.data.voices
			} else {
				cloneVoices.value = []
				uni.showToast({ title: res?.data?.message || '获取复刻音色失败', icon: 'none' })
			}
		} catch (e) {
			cloneVoices.value = []
			uni.showToast({ title: '获取复刻音色失败', icon: 'none' })
		} finally {
			cloneVoicesLoading.value = false
		}
	}
	const toggleCloneDropdown = () => {
		cloneDropdownOpen.value = !cloneDropdownOpen.value
		if (cloneDropdownOpen.value && cloneVoices.value.length === 0 && !cloneVoicesLoading.value) {
			loadCloneVoices()
		}
	}
	const selectCloneVoice = (v) => {
		ttsVoiceCustom.value = v.speaker_id
		cloneDropdownOpen.value = false
	}
	// 试听复刻音色:经服务端代理拉取(audio/wav),下载到本地临时文件后播放,
	// 避免直接播放火山签名 URL(无扩展名 + audio/wave)导致播放器识别失败
	let cloneAudioCtx = null
	const previewCloneVoice = (v) => {
		if (!v || !v.speaker_id) { uni.showToast({ title: '无试听音频', icon: 'none' }); return }
		const baseUrl = getBaseUrl()
		if (!baseUrl) { uni.showToast({ title: '请先配置服务器地址', icon: 'none' }); return }
		uni.showLoading({ title: '加载试听...', mask: true })
		const token = uni.getStorageSync('esp_ai_token') || ''
		const headers = {}
		if (token) headers['Authorization'] = 'Bearer ' + token
		uni.downloadFile({
			url: baseUrl + '/api/v1/tts/clone-voices/preview?speaker_id=' + encodeURIComponent(v.speaker_id) +
				'&mac=' + encodeURIComponent((currentDevice.value && (currentDevice.value.mac || currentDevice.value.id)) || ''),
			header: headers,
			success: (res) => {
				uni.hideLoading()
				console.log('试听下载', res.statusCode, res.tempFilePath)
				if (res.statusCode !== 200) {
					uni.showToast({ title: '试听加载失败(' + res.statusCode + ')', icon: 'none' })
					return
				}
				if (cloneAudioCtx) {
					cloneAudioCtx.stop()
					cloneAudioCtx.destroy()
					cloneAudioCtx = null
				}
				const ctx = uni.createInnerAudioContext()
				ctx.src = res.tempFilePath
				ctx.onError((e) => {
					console.log('试听播放错误', JSON.stringify(e))
					if (cloneAudioCtx === ctx) { cloneAudioCtx = null }
					ctx.destroy()
					uni.showToast({ title: '试听失败', icon: 'none' })
				})
				ctx.onEnded(() => {
					if (cloneAudioCtx === ctx) { cloneAudioCtx = null }
					ctx.destroy()
				})
				ctx.play()
				cloneAudioCtx = ctx
			},
			fail: (e) => {
				uni.hideLoading()
				uni.showToast({ title: '试听下载失败', icon: 'none' })
			}
		})
	}
	// 复刻模型下触发框显示:已选音色名(alias)或 ID
	const cloneVoiceDisplayName = computed(() => {
		if (!ttsVoiceCustom.value) return '选择已有复刻音色'
		const found = cloneVoices.value.find(v => v.speaker_id === ttsVoiceCustom.value)
		return found ? (found.alias || found.speaker_id) : (ttsVoiceCustom.value + '(不在可用列表)')
	})

	const speakText = ref('')
	const speakFocus = ref(false)
	const volumeValue = ref(50)
	const showVolumeFloat = ref(false)
	let volumeTimer = null

	const toggleVolumeFloat = async () => {
		// 设备离线时禁止操作
		if (!currentDevice.value || !currentDevice.value.online) {
			uni.showToast({ title: '设备已离线，无法调节音量', icon: 'none' })
			return
		}
		
		showVolumeFloat.value = !showVolumeFloat.value
		if (showVolumeFloat.value) {
			// 获取当前设备音量来重置进度条
			const mac = currentDevice.value && currentDevice.value.mac
			if (mac) {
				try {
					const res = await callDeviceApi('/api/v1/devices/' + mac + '/volume', 'GET')
					if (res && res.statusCode === 200 && res.data) {
						let body = res.data
						if (typeof body === 'string') {
							try { body = JSON.parse(body) } catch(e) {}
						}
						const vol = body.data?.volume ?? body.volume ?? 0.5
						volumeValue.value = Math.round(vol * 100)
						console.log('[Volume] 获取当前音量:', volumeValue.value)
					}
				} catch (e) {
					console.error('[Volume] 获取音量失败:', e)
				}
			}
			if (volumeTimer) clearTimeout(volumeTimer)
			volumeTimer = setTimeout(() => { showVolumeFloat.value = false }, 5000)
		}
	}
	const hideVolumeFloat = () => { showVolumeFloat.value = false }

	// 复制开源地址
	const copyOpenSourceUrl = () => {
		uni.setClipboardData({
			data: 'https://gitee.com/zhuxiaohuaqn/esp-ai-server',
			success: () => {
				uni.showToast({ title: '已复制到剪贴板', icon: 'success' })
			}
		})
	}

	const showAbout = () => {
		uni.showModal({
			title: '关于',
			content: '应用名称：ESP-AI 语音助手\n版本号：v1.0.0\n设备型号：ESP32-S3\n固件版本：v2.1.0\n作者：青柠博客\n\n开源地址：gitee.com/zhuxiaohuaqn/esp-ai-server\n\nESP-AI 是一款基于 ESP32 的智能语音助手控制中心，支持 ASR 语音识别、LLM 大语言模型对话、TTS 语音合成等功能。',
			confirmText: '复制开源地址',
			success: (r) => {
				if (r.confirm) copyOpenSourceUrl()
			}
		})
	}

	const asrFormOpacity = ref(1)

	// 从本地存储加载已配网设备
	const STORAGE_KEY = 'esp_ai_devices'
	// 记住用户当前选中的设备（页面重启/服务器同步后恢复，避免总是自动切到列表第一个设备）
	const CURRENT_DEVICE_KEY = 'esp_ai_current_device_id'

	const loadDevices = () => {
		try {
			const saved = uni.getStorageSync(STORAGE_KEY)
			return saved ? JSON.parse(saved) : []
		} catch(e) { return [] }
	}
	const saveDevices = (list) => {
		try { uni.setStorageSync(STORAGE_KEY, JSON.stringify(list)) } catch(e) {}
	}
	const loadCurrentDeviceId = () => {
		try { return uni.getStorageSync(CURRENT_DEVICE_KEY) || '' } catch(e) { return '' }
	}
	const saveCurrentDeviceId = (id) => {
		try { uni.setStorageSync(CURRENT_DEVICE_KEY, id || '') } catch(e) {}
	}
	// 从设备列表恢复当前设备：优先恢复上次选择的设备，不存在（被删除/已同步移除）则选第一个
	const resolveCurrentDevice = (list) => {
		if (!list || list.length === 0) return null
		const savedId = loadCurrentDeviceId()
		if (savedId) {
			const found = list.find(d => d.id === savedId)
			if (found) return found
		}
		return list[0]
	}

	const deviceList = ref(loadDevices())
	const currentDevice = ref(resolveCurrentDevice(deviceList.value))

	const selectDevice = (device) => {
		currentDevice.value = device
		saveCurrentDeviceId(device.id)
		hideModal()
		fetchEmos()
		uni.showToast({
			title: '已切换至 ' + device.name,
			icon: 'success'
		})
	}

	// 配网成功后保存设备
	const saveProvisionedDevice = (deviceId, deviceName, authKey, deviceIp, realMac, isOnline, managementApiKey) => {
		const list = loadDevices()
		const idx = list.findIndex(d => d.id === deviceId)
		const entry = { id: deviceId, name: deviceName || deviceId, mac: realMac || '', authKey: authKey || '', management_api_key: managementApiKey || '', deviceIp: deviceIp || '', online: isOnline === true, addedAt: Date.now() }
		if (idx >= 0) { list[idx] = { ...list[idx], ...entry } }
		else { list.unshift(entry) }
		saveDevices(list)
		deviceList.value = list
		currentDevice.value = entry
		saveCurrentDeviceId(entry.id)
	}

	const unbindDevice = (device) => {
		// 第一次确认
		uni.showModal({
			title: '⚠️ 解绑设备',
			content: '此操作将清空设备所有配置，相当于恢复出厂设置。\n\n请再三考虑！确定要解绑 ' + device.name + ' 吗？',
			confirmText: '我确定要解绑',
			confirmColor: '#ef4444',
			cancelText: '取消',
			success: (res) => {
				if (res.confirm) {
					// 第二次确认
					uni.showModal({
						title: '⚠️ 最后警告',
						content: '这是最后警告！\n\n解绑后设备所有配置将被永久清空，\n相当于恢复出厂设置。\n\n真的要解绑 ' + device.name + ' 吗？',
						confirmText: '确认解绑',
						confirmColor: '#ef4444',
						cancelText: '取消',
						success: (r) => {
							if (r.confirm) {
								doUnbind(device)
							}
						}
					})
				}
			}
		})
	}

	const doBindDevice = async () => {
		const code = bindCodeInput.value.trim()
		if (!code) { uni.showToast({ title: '请输入绑定码', icon: 'none' }); return }
		// 检查是否已登录
		if (!isLoggedInRef) {
			uni.showModal({
				title: '需要登录',
				content: '绑定设备需要先登录账号，是否前往登录？',
				success: (r) => { if (r.confirm) switchTab('profile') }
			})
			return
		}
		try {
			const body = { bind_code: code }
			const name = bindNameInput.value.trim()
			if (name) body.name = name
			const res = await callDeviceApi('/api/v1/bind', 'POST', body)
			if (res && res.data && (res.data.code === 0 || res.data.success)) {
				uni.showToast({ title: '绑定成功', icon: 'success' })
				bindCodeInput.value = ''
				bindNameInput.value = ''
				// 刷新设备列表
				if (isLoggedInRef) refreshFromServer()
			} else {
				const msg = res?.data?.message || ''
				// 将英文错误提示转为中文
				const friendly = msg === 'Bind code expired' ? '绑定码已过期，请刷新设备屏幕获取新码' :
					msg === 'Device not found or bind code invalid' ? '绑定码无效，请检查输入的码是否正确' :
					msg === 'Device already bound to another user' ? '该设备已被其他用户绑定' :
					msg || '绑定失败'
				uni.showToast({ title: friendly, icon: 'none', duration: 3000 })
			}
		} catch (e) {
			console.error('绑定失败:', e)
			uni.showToast({ title: '绑定失败: ' + (e.message || '未知错误'), icon: 'none' })
		}
	}

	const doUnbind = async (device) => {
		uni.showLoading({ title: '解绑中...', mask: true })
		try {
			const mac = device.mac || device.authKey || ''
			if (!mac) {
				uni.hideLoading()
				uni.showToast({ title: '设备标识无效', icon: 'none' })
				return
			}
			const res = await callDeviceApi('/api/v1/devices/' + mac + '/unbind', 'POST')
			uni.hideLoading()
			if (res && res.data && (res.data.code === 0 || res.data.success)) {
				// 从本地列表移除
				const list = loadDevices().filter(d => d.id !== device.id)
				saveDevices(list)
				deviceList.value = list
				if (currentDevice.value && currentDevice.value.id === device.id) {
					// 解绑的是当前设备：恢复上次选择（不存在则选第一个）
					currentDevice.value = resolveCurrentDevice(list)
					saveCurrentDeviceId(currentDevice.value?.id || '')
				}
				uni.showToast({ title: '设备已解绑', icon: 'success' })
			} else {
				uni.showToast({ title: res?.data?.message || '解绑失败', icon: 'none' })
			}
		} catch (e) {
			uni.hideLoading()
			console.error('解绑失败:', e)
			uni.showToast({ title: '解绑失败: ' + (e.message || '未知错误'), icon: 'none' })
		}
	}

	// ===== 微信绑定 API =====
	const startWechatQr = async () => {
		try {
			uni.showLoading({ title: '获取二维码...', mask: true })
			const res = await callApi('/api/v1/wechat/qr-start', 'POST')
			uni.hideLoading()
			if (res.data && res.data.code === 0 && res.data.data) {
				const d = res.data.data
				wechatQrDataUrl.value = d.qr_data_url || ''
				wechatQrStatus.value = d.status || 'waiting_scan'
				wechatQrMessage.value = d.message || '请用微信扫描二维码'
				wechatSessionKey.value = d.session_key || ''
				wechatCollapsed.value = false
				startPollQrStatus()
			} else {
				uni.showToast({ title: res.data?.message || '获取二维码失败', icon: 'none' })
			}
		} catch (e) {
			uni.hideLoading()
			uni.showToast({ title: '获取二维码失败: ' + (e.message || '未知错误'), icon: 'none' })
		}
	}

	const startPollQrStatus = () => {
		wechatQrPolling.value = true
		if (wechatQrTimer.value) clearInterval(wechatQrTimer.value)
		wechatQrTimer.value = setInterval(async () => {
			try {
				const res = await callApi('/api/v1/wechat/qr-status', 'GET')
				if (res.data && res.data.code === 0 && res.data.data) {
					const d = res.data.data
					wechatQrStatus.value = d.status
					wechatQrMessage.value = d.message

					if (d.completed) {
						clearInterval(wechatQrTimer.value)
						wechatQrTimer.value = null
						wechatQrPolling.value = false
						wechatBotToken.value = d.bot_token || ''
						uni.showToast({ title: '微信登录成功！', icon: 'success' })
						// 调用 apply-token 激活轮询
						try {
							const applyRes = await callApi('/api/v1/wechat/apply-token', 'POST')
							if (applyRes.data && applyRes.data.code === 0) {
								console.log('微信 token 已应用，轮询已启动')
							} else {
								console.warn('apply-token 失败:', applyRes.data?.message)
							}
						} catch (applyErr) {
							console.error('apply-token 请求失败:', applyErr)
						}
						// 绑定到当前设备
						if (currentDevice.value) {
							await bindCurrentDeviceToWechat(d.ilink_user_id)
						}
					} else if (d.status === 'expired' || d.status === 'error' || d.status === 'cancelled') {
						clearInterval(wechatQrTimer.value)
						wechatQrTimer.value = null
						wechatQrPolling.value = false
					}
				}
			} catch (e) {
				console.error('轮询二维码状态失败:', e)
			}
		}, 1500)
	}

	const stopPollQr = () => {
		if (wechatQrTimer.value) {
			clearInterval(wechatQrTimer.value)
			wechatQrTimer.value = null
		}
		wechatQrPolling.value = false
		callApi('/api/v1/wechat/qr-cancel', 'POST').catch(() => {})
	}

	const bindCurrentDeviceToWechat = async (wechatUserId) => {
		if (!currentDevice.value || !wechatUserId) return
		// 优先使用从服务器获取的 device_key，确保与 WebSocket 认证 key 一致
		const deviceKey = currentDevice.value.device_key || currentDevice.value.authKey || currentDevice.value.mac || ''
		if (!deviceKey) return
		try {
			const res = await callApi('/api/v1/wechat/bind', 'POST', {
				wechat_chat_id: wechatUserId,
				wechat_user_id: wechatUserId,
				device_key: deviceKey,
				device_mac: currentDevice.value.mac || '',
				alias: currentDevice.value.name || '',
			})
			if (res.data && res.data.code === 0) {
				wechatBoundDeviceKey.value = deviceKey
				wechatBoundWechatId.value = wechatUserId
				const bindInfo = {
					device_key: deviceKey,
					wechat_chat_id: wechatUserId,
					wechat_group_id: wechatGroupId.value || '',
				}
				uni.setStorageSync('wechat_bind_info', JSON.stringify(bindInfo))
				uni.showToast({ title: '微信已绑定到当前设备', icon: 'success' })
			}
		} catch (e) {
			console.error('微信绑定设备失败:', e)
		}
	}

	let _unbinding = false

	const unbindWechat = async () => {
		if (!wechatBoundDeviceKey.value || _unbinding) return
		_unbinding = true
		try {
			const res = await callApi('/api/v1/wechat/unbind', 'POST', {
				device_key: wechatBoundDeviceKey.value,
			})
			// 无论 API 返回什么，都清除本地状态
			wechatBoundDeviceKey.value = ''
			wechatBoundWechatId.value = ''
			uni.removeStorageSync('wechat_bind_info')
			if (res.data && res.data.code === 0) {
				uni.showToast({ title: '微信已解绑', icon: 'success' })
			}
		} catch (e) {
			// 即使报错也清除本地状态
			wechatBoundDeviceKey.value = ''
			wechatBoundWechatId.value = ''
			uni.removeStorageSync('wechat_bind_info')
			uni.showToast({ title: '解绑失败: ' + (e.message || '未知错误'), icon: 'none' })
		}
		_unbinding = false
	}

	const saveGroupBind = async () => {
		const groupId = wechatGroupId.value || (groupPickIndex.value >= 0 ? recentGroups.value[groupPickIndex.value]?.group_id : '')
		if (!groupId || !wechatBoundDeviceKey.value) {
			uni.showToast({ title: '请先扫码绑定个人微信，再刷新选择群聊', icon: 'none' })
			return
		}
		try {
			const res = await callApi('/api/v1/wechat/bind', 'POST', {
				wechat_chat_id: wechatBoundWechatId.value,
				wechat_user_id: wechatBoundWechatId.value,
				wechat_group_id: groupId,
				device_key: wechatBoundDeviceKey.value,
			})
			if (res.data && res.data.code === 0) {
				wechatGroupId.value = groupId
				// 持久化群聊 ID
				const saved = uni.getStorageSync('wechat_bind_info')
				if (saved) {
					try {
						const info = JSON.parse(saved)
						info.wechat_group_id = groupId
						uni.setStorageSync('wechat_bind_info', JSON.stringify(info))
					} catch(e) {}
				}
				uni.showToast({ title: '群聊已绑定', icon: 'success' })
			}
		} catch (e) {
			uni.showToast({ title: '绑定群聊失败: ' + (e.message || ''), icon: 'none' })
		}
	}

	const fetchRecentGroups = async () => {
		try {
			const res = await callApi('/api/v1/wechat/recent-groups', 'GET')
			if (res.data && res.data.code === 0 && res.data.data) {
				recentGroups.value = res.data.data
				if (recentGroups.value.length > 0) {
					uni.showToast({ title: `找到 ${recentGroups.value.length} 个群聊`, icon: 'success' })
				} else {
					uni.showToast({ title: '暂无群聊，请在群里 @机器人', icon: 'none' })
				}
			}
		} catch (e) {
			uni.showToast({ title: '获取群聊列表失败', icon: 'none' })
		}
	}

	const onGroupPick = (e) => {
		groupPickIndex.value = e.detail.value
	}

	const unbindGroupChat = async () => {
		if (_unbinding) return
		_unbinding = true
		try {
			const res = await callApi('/api/v1/wechat/bind', 'POST', {
				wechat_chat_id: wechatBoundWechatId.value,
				wechat_user_id: wechatBoundWechatId.value,
				wechat_group_id: '',
				device_key: wechatBoundDeviceKey.value,
			})
			if (res.data && res.data.code === 0) {
				wechatGroupId.value = ''
				groupPickIndex.value = -1
				const saved = uni.getStorageSync('wechat_bind_info')
				if (saved) {
					try {
						const info = JSON.parse(saved)
						info.wechat_group_id = ''
						uni.setStorageSync('wechat_bind_info', JSON.stringify(info))
					} catch(e) {}
				}
				uni.showToast({ title: '群聊已解绑', icon: 'success' })
			}
		} catch (e) {
			uni.showToast({ title: '解绑群聊失败', icon: 'none' })
		}
		_unbinding = false
	}

	// ===== 认证相关 =====
	let _authExpiredShowing = false

	// 处理登录过期：提示用户并跳转登录页
	// 如果用户本来就未登录，静默处理，不弹窗
	const handleAuthExpired = () => {
		if (_authExpiredShowing) return
		// 未登录状态不弹窗，直接切换到登录页
		if (!isLoggedInRef.value) {
			// 未登录状态收到 401 属正常，静默忽略，不跳转
			return
		}
		_authExpiredShowing = true
		uni.showModal({
			title: '登录已过期',
			content: '您的登录状态已过期，请重新登录',
			showCancel: false,
			confirmText: '重新登录',
			success: () => {
				_authExpiredShowing = false
				profileEmail.value = ''
				profilePassword.value = ''
				profileNickname.value = ''
				profileErr.value = ''
				isLoggedInRef.value = false  // 更新响应式状态，触发模板重新渲染
				profileFormMode.value = 'login'
				currentTab.value = 'profile'
			},
			fail: () => { _authExpiredShowing = false }
		})
	}

	const showLogoutConfirm = () => {
		const user = getUser()
		uni.showModal({
			title: '当前用户',
			content: user?.nickname || user?.email || '',
			confirmText: '退出登录',
			confirmColor: '#ef4444',
			cancelText: '取消',
			success: (res) => {
				if (res.confirm) {
					logout()
					profileEmail.value = ''
					profilePassword.value = ''
					profileNickname.value = ''
					profileErr.value = ''
					isLoggedInRef.value = false  // 更新响应式状态，触发模板重新渲染
					uni.showToast({ title: '已退出', icon: 'success' })
					// 立即跳转到登录页面
					profileFormMode.value = 'login'
					currentTab.value = 'profile'
				}
			}
		})
	}

	const saveServerUrl = () => {
		const url = profileServerUrl.value.trim()
		if (url) setServerUrl(url)
	}

	const saveWakeConfig = async () => {
		try {
			const device = currentDevice.value
			if (!device || !device.mac) { uni.showToast({ title: '请先在首页选择设备', icon: 'none' }); return }
			const body = {
				wakeup: {
					text: profileWakeText.value.trim() || '我在呢',
					enabled: profileWakeAudioEn.value,
					source: profileWakeSource.value,
					play_on_next_round: profileWakeNextRound.value,
					cache_enabled: true,
					play_enabled: profileWakeAudioEn.value,
				}
			}
			const res = await callDeviceApi('/api/v1/devices/' + device.mac + '/config', 'POST', body)
			if (res && res.data && (res.data.code === 0 || res.data.success)) {
				uni.showToast({ title: '唤醒配置已保存', icon: 'success' })
			} else {
				uni.showToast({ title: res?.data?.message || '保存失败', icon: 'none' })
			}
		} catch (e) {
			console.error('保存唤醒配置失败:', e)
			uni.showToast({ title: '保存失败: ' + (e.message || '未知错误'), icon: 'none' })
		}
	}

	const loadWakeConfig = async () => {
		try {
			const device = currentDevice.value
			if (!device || !device.mac) { uni.showToast({ title: '请先在首页选择设备', icon: 'none' }); return }
			const res = await callDeviceApi('/api/v1/devices/' + device.mac + '/config', 'GET')
			const w = res?.data?.data?.wakeup
			if (w) {
				if (w.text) profileWakeText.value = w.text
				if (w.enabled !== undefined) profileWakeAudioEn.value = !!w.enabled
				if (w.source) profileWakeSource.value = w.source
				if (w.play_on_next_round !== undefined) profileWakeNextRound.value = !!w.play_on_next_round
				uni.showToast({ title: '唤醒配置已加载', icon: 'success' })
			} else {
				// 使用默认值
				profileWakeText.value = '我在呢'
				profileWakeAudioEn.value = true
				profileWakeSource.value = 'tts'
				profileWakeNextRound.value = false
				uni.showToast({ title: '当前设备未配置唤醒', icon: 'none' })
			}
		} catch (e) {
			console.error('加载唤醒配置失败:', e)
			uni.showToast({ title: '加载失败: ' + (e.message || '未知错误'), icon: 'none' })
		}
	}

	const doLogin = async () => {
		if (!profileEmail.value.trim() || !profilePassword.value.trim()) {
			profileErr.value = '请输入邮箱和密码'
			return
		}
		profileLoading.value = true
		profileErr.value = ''
		const result = await login(profileEmail.value.trim(), profilePassword.value)
		profileLoading.value = false
		if (result.success) {
			isLoggedInRef.value = true  // 更新响应式状态，触发模板重新渲染
			uni.showToast({ title: '登录成功', icon: 'success' })
		} else {
			profileErr.value = result.message || '登录失败'
		}
	}

	const doRegister = async () => {
		if (!profileEmail.value.trim()) { profileErr.value = '请输入邮箱'; return }
		if (!profileNickname.value.trim()) { profileErr.value = '请输入昵称'; return }
		if (!profilePassword.value || profilePassword.value.length < 6) { profileErr.value = '密码至少 6 位'; return }
		profileLoading.value = true
		profileErr.value = ''
		const result = await register(profileEmail.value.trim(), profilePassword.value, profileNickname.value.trim())
		profileLoading.value = false
		if (result.success) {
			uni.showToast({ title: '注册成功，请登录', icon: 'success' })
			profileFormMode.value = 'login'
		} else {
			profileErr.value = result.message || '注册失败'
		}
	}



	const refreshFromServer = async () => {
		if (!isLoggedIn()) {
			uni.showToast({ title: '请先登录', icon: 'none' })
			return
		}
		try {
			const devices = await getDevices()
			if (devices.length > 0) {
				deviceList.value = devices.map(d => ({
					id: d.device_id || d.mac || d.id,
					name: d.name || '',
					mac: d.mac || d.device_id || '',
					online: d.connected === true || d.online === true,
					deviceIp: currentDevice.value?.deviceIp || '',
					authKey: '',
					management_api_key: '',
					addedAt: Date.now(),
				}))
				// 保持用户当前选择的设备（修复原逻辑：原条件写反，导致每次同步都强制切到列表第一个设备）
				currentDevice.value = resolveCurrentDevice(deviceList.value)
				saveCurrentDeviceId(currentDevice.value?.id || '')
				saveDevices(deviceList.value)
				uni.showToast({ title: '已从服务器同步 ' + devices.length + ' 台设备', icon: 'success' })
			}
		} catch (e) {
			uni.showToast({ title: '同步失败', icon: 'none' })
		}
	}

	const switchAsrEngine = (engine) => {
		if (engine === asrEngine.value) return
		asrFormOpacity.value = 0
		setTimeout(() => {
			asrEngine.value = engine
			setTimeout(() => {
				asrFormOpacity.value = 1
			}, 50)
		}, 300)
	}

	// ── 表情包系统 ──
	const emoPackList = ref([])
	const activePack = ref('default')
	const emoList = ref([])
	// 首页设备屏幕：休息中表情 + 模拟电量
	const sleepEmoUrl = ref('')
	const sleepEmoError = ref(false)
	const batteryPct = computed(() => {
		const dev = currentDevice.value
		const key = (dev && (dev.mac || dev.id)) || ''
		if (!key) return 90
		let hash = 0
		for (let i = 0; i < key.length; i++) hash = ((hash << 5) - hash + key.charCodeAt(i)) | 0
		return 55 + (Math.abs(hash) % 45)
	})
	const loadDeviceSleepEmo = () => {
		sleepEmoError.value = false
		const emo = emoList.value.find(e => e.en === 'sleep')
		sleepEmoUrl.value = (emo && emo.url) || ''
	}
	const emoCreateVisible = ref(false)
	const emoCreateName = ref('')
	const emoDeleteVisible = ref(false)
	const emoDeletePackName = ref('')
	const emoDeleteDisplayName = ref('')
	// 表情上传尺寸选择：0=原图 120/160/180/240
	const emoResizeSize = ref(180)
	const emoSizeOptions = [
		{ value: 0, label: '原图' },
		{ value: 120, label: '120' },
		{ value: 160, label: '160' },
		{ value: 180, label: '180' },
		{ value: 240, label: '240' },
	]
	const emoDefs = [
		{ en: 'listen', cn: '聆听中' },
		{ en: 'sleep', cn: '休息中' },
		{ en: 'tts_ing', cn: '说话中' },
		{ en: 'music', cn: '唱歌中' },
		{ en: 'happy', cn: '快乐' },
		{ en: 'sad', cn: '伤心' },
		{ en: 'angry', cn: '愤怒' },
		{ en: 'accident', cn: '意外' },
		{ en: 'error', cn: '发生错误' },
		{ en: 'no', cn: '否定' },
		{ en: 'wifi', cn: 'WiFi' },
		{ en: 'wx_qrcode', cn: '二维码' },
		{ en: 'ap_qrcode', cn: '配网码' }
	]

	function getEmoBase() {
		// 使用服务器地址（与 callDeviceApi 一致），而非设备 IP
		return getServerUrl() || ''
	}

	// 获取带 JWT 认证的请求头
	function getAuthHeaders() {
		var token = uni.getStorageSync('esp_ai_token') || ''
		var headers = { 'Content-Type': 'application/json' }
		if (token) headers['Authorization'] = 'Bearer ' + token
		return headers
	}

	// 加载表情包列表
	const fetchEmoPacks = async () => {
		var base = getEmoBase()
		if (!base) return
		try {
			var res = await new Promise(function(resolve) {
				uni.request({ url: base + '/api/v1/emos/packs/list', method: 'GET', timeout: 5000,
					header: getAuthHeaders(),
					success: function(r) { resolve(r) }, fail: function() { resolve(null) }
				})
			})
			if (res && res.data && res.data.code === 0 && res.data.data) {
				emoPackList.value = res.data.data
				// 如果当前 activePack 不在列表中，选第一个
				var found = false
				for (var i = 0; i < res.data.data.length; i++) {
					if (res.data.data[i].name === activePack.value) { found = true; break }
				}
				if (!found && res.data.data.length > 0) {
					activePack.value = res.data.data[0].name
				}
			}
		} catch(e) {}
	}

	// 加载指定表情包的表情列表（始终显示13个标准槽位）
	const fetchPackEmos = async (packName) => {
		var base = getEmoBase()
		if (!base) return
		// 先创建13个空槽位
		var items = []
		for (var i = 0; i < emoDefs.length; i++) {
			items.push({ url: '', name: emoDefs[i].cn, en: emoDefs[i].en })
		}
		emoList.value = items
		// 从服务器获取该包已有的表情，匹配填充
		try {
			var res = await new Promise(function(resolve) {
				uni.request({ url: base + '/api/v1/emos/packs/' + packName, method: 'GET', timeout: 5000,
					header: getAuthHeaders(),
					success: function(r) { resolve(r) }, fail: function() { resolve(null) }
				})
			})
			if (res && res.data && res.data.code === 0 && res.data.data) {
				var raw = res.data.data
				var arr = items.slice()
				for (var i = 0; i < raw.length; i++) {
					var item = raw[i]
					var enName = item.name || ''
					var url = item.url || ''
					if (url && enName) {
						for (var j = 0; j < arr.length; j++) {
							if (arr[j].en === enName) {
								arr[j] = Object.assign({}, arr[j], { url: url })
								break
							}
						}
					}
				}
				emoList.value = arr
			}
		} catch(e) {}
		loadDeviceSleepEmo()
	}

	// 获取设备当前激活的表情包
	const fetchActivePack = async () => {
		var base = getEmoBase()
		var key = currentDevice.value && (currentDevice.value.mac || currentDevice.value.authKey || '')
		if (!base || !key) return
		try {
			var res = await new Promise(function(resolve) {
				uni.request({ url: base + '/api/v1/emos/active/' + key, method: 'GET', timeout: 5000,
					success: function(r) { resolve(r) }, fail: function() { resolve(null) }
				})
			})
			if (res && res.data && res.data.code === 0 && res.data.data) {
				activePack.value = res.data.data.active_pack || 'default'
			}
		} catch(e) {}
	}

	// 切换表情包（本地选择）
	function switchPack(packName) {
		if (activePack.value === packName) return
		activePack.value = packName
		fetchPackEmos(packName)
	}

	// 应用表情包到设备
	const applyPack = async () => {
		var base = getEmoBase()
		var key = currentDevice.value && (currentDevice.value.mac || currentDevice.value.authKey || '')
		if (!base || !key) { uni.showToast({ title: '请先同步设备', icon: 'none' }); return }
		uni.showLoading({ title: '切换中...', mask: true })
		try {
			var res = await new Promise(function(resolve) {
				uni.request({
					url: base + '/api/v1/emos/active/' + key + '?pack=' + encodeURIComponent(activePack.value),
					method: 'POST',
					timeout: 10000,
					header: getAuthHeaders(),
					success: function(r) { resolve(r) }, fail: function(e) { resolve(null) }
				})
			})
			uni.hideLoading()
			if (res && res.data && res.data.code === 0) {
				uni.showToast({ title: '已切换，设备正在刷新表情', icon: 'none', duration: 2500 })
			} else {
				uni.showToast({ title: (res && res.data && res.data.message) || '切换失败', icon: 'none' })
			}
		} catch(e) {
			uni.hideLoading()
			uni.showToast({ title: '切换出错', icon: 'none' })
		}
	}

	// 创建新表情包（支持中文名称）
	function promptCreatePack() {
		emoCreateName.value = ''
		emoCreateVisible.value = true
	}

	async function doCreatePack() {
		var name = emoCreateName.value.trim()
		if (!name) { uni.showToast({ title: '请输入名称', icon: 'none' }); return }
		emoCreateVisible.value = false
		var base = getEmoBase()
		if (!base) { uni.showToast({ title: '请先同步设备', icon: 'none' }); return }
		try {
			var r = await new Promise(function(resolve) {
				uni.request({
					url: base + '/api/v1/emos/packs/create?name=' + encodeURIComponent(name),
					method: 'POST',
					timeout: 5000,
					header: getAuthHeaders(),
					success: function(r) { resolve(r) }, fail: function() { resolve(null) }
				})
			})
			if (r && r.data && r.data.code === 0) {
				uni.showToast({ title: '创建成功', icon: 'success' })
				fetchEmoPacks()
			} else {
				uni.showToast({ title: (r && r.data && r.data.message) || '创建失败', icon: 'none' })
			}
		} catch(e) {}
	}

	// 删除表情包
	function confirmDeletePack(packName) {
		if (packName === 'default') { uni.showToast({ title: '不能删除默认表情包', icon: 'none' }); return }
		var displayName = packName
		for (var i = 0; i < emoPackList.value.length; i++) {
			if (emoPackList.value[i].name === packName) { displayName = emoPackList.value[i].display_name || packName; break }
		}
		emoDeletePackName.value = packName
		emoDeleteDisplayName.value = displayName
		emoDeleteVisible.value = true
	}

	async function doDeletePack() {
		var packName = emoDeletePackName.value
		emoDeleteVisible.value = false
		var base = getEmoBase()
		if (!base) return
		try {
			var r = await new Promise(function(resolve) {
				uni.request({
					url: base + '/api/v1/emos/packs/' + packName,
					method: 'DELETE',
					timeout: 5000,
					header: getAuthHeaders(),
					success: function(r) { resolve(r) }, fail: function() { resolve(null) }
				})
			})
			if (r && r.data && r.data.code === 0) {
				uni.showToast({ title: '已删除', icon: 'success' })
				if (activePack.value === packName) activePack.value = 'default'
				fetchEmoPacks()
				fetchPackEmos(activePack.value)
			} else {
				uni.showToast({ title: (r && r.data && r.data.message) || '删除失败', icon: 'none' })
			}
		} catch(e) {}
	}

	// 上传表情到当前表情包
	function pickAndUpload(idx) {
		var emo = emoList.value[idx]
		var base = getEmoBase()
		if (!base) { uni.showToast({ title: '请先同步设备', icon: 'none' }); return }
		uni.chooseImage({
			count: 1,
			sizeType: ['original'],
			sourceType: ['album', 'camera'],
			success: function(choose) {
				if (!choose.tempFilePaths || !choose.tempFilePaths[0]) return
				var srcPath = choose.tempFilePaths[0]
				var fileName = (emo && emo.en ? emo.en : 'new') + '.gif'
				uni.showLoading({ title: '上传中...', mask: true })
				// 上传时只带 Authorization 头，不设 Content-Type（uni.uploadFile 自动设为 multipart/form-data）
				var uploadHeader = {}
				var token = uni.getStorageSync('esp_ai_token') || ''
				if (token) uploadHeader['Authorization'] = 'Bearer ' + token
				uni.uploadFile({
				url: base + '/api/v1/emos/packs/' + activePack.value + '/upload?name=' + encodeURIComponent(fileName) + '&size=' + emoResizeSize.value,
				filePath: srcPath,
				name: 'file',
				header: uploadHeader,
				success: function(res) {
					uni.hideLoading()
					if (res.statusCode === 200) {
						uni.showToast({ title: '上传成功', icon: 'success' })
						setTimeout(function() {
							fetchPackEmos(activePack.value)
							fetchEmoPacks()
						}, 1000)
					} else {
						uni.showToast({ title: '上传失败', icon: 'none' })
					}
				},
				fail: function() {
					uni.hideLoading()
					uni.showToast({ title: '上传失败', icon: 'none' })
				}
			})
			}
		})
	}

	// 兼容旧入口
	const fetchEmos = async () => {
		await fetchEmoPacks()
		await fetchActivePack()
		await fetchPackEmos(activePack.value)
	}

	const showModal = (name) => {
		// 设备离线时禁止操作（配置类弹窗允许离线查看/编辑）
		const offlineAllowed = ['devices', 'about', 'asr', 'llm', 'tts']
		if (currentDevice.value && !currentDevice.value.online && !offlineAllowed.includes(name)) {
			uni.showToast({ title: '设备已离线，请先连接设备', icon: 'none' })
			return
		}
		
		currentModal.value = name
		if (name === 'speak') {
			speakFocus.value = false
			setTimeout(() => { speakFocus.value = true }, 300)
		}
		if (name === 'emo') {
			fetchEmos()
		}
		if (name === 'tools') {
			toolPickerList.value = []
			toolPickerLoading.value = true
			loadToolList()
			loadProactiveConfig()
		}
		if (name === 'mcp') {
			loadMcpList()
		}
		if (name === 'devices' && currentDevice.value && currentDevice.value.deviceIp) {
			autoSyncDevice()
		}
		if (name === 'asr' || name === 'llm' || name === 'tts') {
			loadModuleConfig(name)
		}
	}

	const hideModal = () => {
		currentModal.value = ''
	}

	const loadModuleConfig = async (module) => {
		const dev = currentDevice.value
		if (!dev) return
		// 使用设备 MAC 作为标识（服务器同步后自动获取）
		const deviceKey = dev.mac || dev.id
		if (!deviceKey) return
		try {
			const res = await callDeviceApi('/api/v1/devices/' + deviceKey + '/config', 'GET')
			if (!res || !res.data || res.data.code !== 0) return
			const cfg = res.data.data || {}
			if (module === 'asr') {
				const provider = cfg.asr_provider || 'volcengine'
				asrEngine.value = provider === 'volcengine' ? 'bytedance' : provider
				const asrCfg = cfg.asr_config || {}
				// 兼容多层路径：asr_config.volcengine.api_key（服务器实际结构）
				// 或 asr_config.api_key / 顶层 asr_api_key（其他存储格式）
				const volcCfg = asrCfg.volcengine || {}
				bytedanceApiKey.value = volcCfg.api_key || asrCfg.api_key || cfg.asr_api_key || ''
				tencentAppId.value = (asrCfg.tencent && asrCfg.tencent.app_id) || asrCfg.tencent_app_id || asrCfg.app_id || ''
				tencentSecretId.value = (asrCfg.tencent && asrCfg.tencent.secret_id) || asrCfg.tencent_secret_id || asrCfg.secret_id || ''
				tencentSecretKey.value = (asrCfg.tencent && asrCfg.tencent.secret_key) || asrCfg.tencent_secret_key || asrCfg.secret_key || ''
			}
			if (module === 'llm') {
				deepseekApiKey.value = cfg.llm?.api_key || ''
				llmModel.value = cfg.llm?.model || 'deepseek-v4-flash'
				llmPrompt.value = cfg.llm?.system_prompt || ''
			}
			if (module === 'tts') {
				ttsApiKey.value = cfg.tts_config?.api_key || ''
				ttsResourceId.value = cfg.tts_config?.resource_id || 'seed-tts-2.0'
				// 设备级火山 OpenAPI 密钥回显
				const vo = cfg.tts_config?.volc_openapi || {}
				volcAkId.value = vo.access_key_id || ''
				volcSk.value = vo.secret_access_key || ''
				volcProjectName.value = vo.project_name || 'default'
				const savedVoice = cfg.tts_config?.voice_type || ''
				// 复刻音色前缀(S_/icl_/saturn_/DiT_)→ 声音复刻模型,从已有列表回显
				const isCloneVoice = /^(s_|icl_|saturn_|dit_)/i.test(savedVoice)
				if (isCloneVoice) {
					ttsResourceId.value = 'seed-icl-2.0'
					ttsVoice.value = '__custom__'
					ttsVoiceCustom.value = savedVoice
					return
				}
				// 预设模型:音色从下拉列表选择
				const voiceList = ttsResourceId.value === 'seed-tts-2.0' ? ttsVoiceList2 : ttsVoiceList1
				ttsVoice.value = voiceList.some(v => v.type === savedVoice) ? savedVoice : ''
				ttsVoiceCustom.value = ''
			}
		} catch (e) {
			console.log('加载配置失败:', e)
		}
	}

	const saveAsrConfig = async () => {
		const dev = currentDevice.value
		const deviceKey = (dev && dev.mac) || (dev && dev.id) || ''
		if (!dev || !deviceKey) { uni.showToast({ title: '请先添加设备', icon: 'none' }); return }
		const engine = asrEngine.value
		const body = { asr_provider: engine === 'bytedance' ? 'volcengine' : engine }
		if (engine === 'bytedance') {
			body.asr_api_key = bytedanceApiKey.value.trim()
		}
		if (engine === 'tencent') {
			body.asr_config = {
				tencent: {
					tencent_app_id: tencentAppId.value.trim(),
					tencent_secret_id: tencentSecretId.value.trim(),
					tencent_secret_key: tencentSecretKey.value.trim()
				}
			}
		}
		try {
			const res = await callDeviceApi('/api/v1/devices/' + deviceKey + '/config', 'POST', body)
			if (res && res.data && res.data.code === 0) {
				uni.showToast({ title: '保存成功', icon: 'success' })
				hideModal()
			} else {
				uni.showToast({ title: res?.data?.message || '保存失败', icon: 'none' })
			}
		} catch (e) {
			uni.showToast({ title: '网络错误', icon: 'none' })
		}
	}

	const saveLlmConfig = async () => {
		const dev = currentDevice.value
		const deviceKey = (dev && dev.mac) || (dev && dev.id) || ''
		if (!dev || !deviceKey) { uni.showToast({ title: '请先添加设备', icon: 'none' }); return }
		const apiKey = deepseekApiKey.value.trim()
		if (!apiKey) { uni.showToast({ title: '请输入 API Key', icon: 'none' }); return }
		const body = {
			llm_api_key: apiKey,
			// 补传 base_url 与 llm_type:App 的 LLM 配置页是 DeepSeek 简化表单,
			// 不传会导致数据库这两个字段为空,服务端只能回退到全局 .env 配置
			llm_base_url: 'https://api.deepseek.com/v1',
			llm_type: 'openai',
			llm_model: llmModel.value,
			llm_system_prompt: llmPrompt.value.trim()
		}
		try {
			const res = await callDeviceApi('/api/v1/devices/' + deviceKey + '/config', 'POST', body)
			if (res && res.data && res.data.code === 0) {
				uni.showToast({ title: '保存成功', icon: 'success' })
				hideModal()
			} else {
				uni.showToast({ title: res?.data?.message || '保存失败', icon: 'none' })
			}
		} catch (e) {
			uni.showToast({ title: '网络错误', icon: 'none' })
		}
	}

	const saveTtsConfig = async () => {
		const dev = currentDevice.value
		const deviceKey = (dev && dev.mac) || (dev && dev.id) || ''
		if (!dev || !deviceKey) { uni.showToast({ title: '请先添加设备', icon: 'none' }); return }
		const apiKey = ttsApiKey.value.trim()
		if (!apiKey) { uni.showToast({ title: '请输入 API Key', icon: 'none' }); return }
		// 声音复刻模型:取自定义输入框值;预设模型:取下拉选择的音色
		const voiceType = ttsResourceId.value === 'seed-icl-2.0' ? ttsVoiceCustom.value.trim() : ttsVoice.value.trim()
		if (!voiceType) {
			uni.showToast({ title: ttsResourceId.value === 'seed-icl-2.0' ? '请输入复刻音色 ID' : '请选择音色', icon: 'none' })
			return
		}
		const body = {
			tts_api_key: apiKey,
			// resource_id 是火山 V3 单向流式接口 X-Api-Resource-Id 的合法取值：
			// 豆包语音合成大模型 -> seed-tts-2.0(模型2.0) / seed-tts-1.0(模型1.0)，
			// 声音复刻大模型 -> seed-icl-2.0 / seed-icl-1.0。
			// 留空让服务端按 voice_type 自动推导（复刻音色 S_/icl_/saturn_/DiT_ 推导为 seed-icl-2.0）。
			tts_resource_id: '',
			voice_type: voiceType,
			// 设备级火山 OpenAPI 密钥(查询复刻音色列表用;任一为空则清空设备级配置,回退环境变量)
			tts_volc_openapi: {
				access_key_id: volcAkId.value.trim(),
				secret_access_key: volcSk.value.trim(),
				project_name: volcProjectName.value.trim() || 'default'
			}
		}
		try {
			const res = await callDeviceApi('/api/v1/devices/' + deviceKey + '/config', 'POST', body)
			if (res && res.data && res.data.code === 0) {
				uni.showToast({ title: '保存成功', icon: 'success' })
				hideModal()
			} else {
				uni.showToast({ title: res?.data?.message || '保存失败', icon: 'none' })
			}
		} catch (e) {
			uni.showToast({ title: '网络错误', icon: 'none' })
		}
	}

	// ===== 技能管理 =====
	const skillsList = ref([])
	const skillsLoading = ref(false)
	const skillForm = ref({ name: '', description: '', instructions: '', categoryStr: '', tagsStr: '', editing: false })
	const skillDetail = ref({})
	const skillDetailLoading = ref(false)

	// ====== 设备插件管理 ======
	const pluginForm = reactive({ loading: false, saving: false, list: [], deviceId: '' })
	// 插件配置表单：{ plugin, title, fields: [{key,label,value,placeholder,required}], saving }
	const pluginConfigForm = reactive({ plugin: '', title: '', fields: [], saving: false })

	// 加载当前设备的插件商店列表（store Tab 与弹窗共用）
	const loadPlugins = async () => {
		if (!isLoggedInRef.value) { uni.showToast({ title: '请先登录', icon: 'none' }); return }
		if (!currentDevice.value) { uni.showToast({ title: '请先在首页选择设备', icon: 'none' }); return }
		const deviceId = currentDevice.value.id || currentDevice.value.mac
		if (!deviceId) { uni.showToast({ title: '设备信息不完整', icon: 'none' }); return }
		pluginForm.deviceId = deviceId
		pluginForm.loading = true
		try {
			const res = await callApi('/api/v1/devices/' + encodeURIComponent(deviceId) + '/plugins', 'GET')
			const d = res && res.data && res.data.data
			if (res.statusCode === 200 && d) {
				// 插件商店语义：enabled_plugins = 已安装插件；null/空 = 全部启用
				const allEnabled = !d.enabled_plugins || d.enabled_plugins.length === 0
				const installed = new Set(d.enabled_plugins || [])
				const configs = d.plugin_configs || {}
				pluginForm.list = (d.available_plugins || []).map(p => {
					const config = configs[p.name] || {}
					return {
						name: p.name,
						title: p.title || p.name,
						source: p.source || 'installed',
						description: p.description || '',
						desc: (p.description || '').slice(0, 24),
						tools: p.tools || [],
						requires: p.requires || [],
						config_fields: p.config_fields || [],
						config: config,
						configDone: Object.keys(config).length > 0,
						enabled: allEnabled || p.source === 'built-in' || installed.has(p.name),
					}
				})
			} else {
				const msg = (res.data && (res.data.message || res.data.detail)) || '加载插件列表失败'
				uni.showToast({ title: msg, icon: 'none' })
			}
		} catch (e) {
			uni.showToast({ title: '加载失败: ' + (e.message || e), icon: 'none' })
		}
		pluginForm.loading = false
	}

	// 按钮文案：内置插件只有启用/禁用，自己安装的插件才有安装/卸载
	const pluginBtnText = (p) => {
		if (p.source === 'built-in') return p.enabled ? '禁用' : '启用'
		return p.enabled ? '卸载' : '安装'
	}

	// 即时安装/卸载/启用/禁用：点击立即调 API 生效，无需保存
	const installPlugin = async (p) => {
		if (!pluginForm.deviceId || p.saving) return
		p.saving = true
		const targetEnabled = !p.enabled
		// 计算目标列表（基于当前勾选状态翻转该插件）
		const enabled = pluginForm.list
			.filter(x => x.name === p.name ? targetEnabled : x.enabled)
			.map(x => x.name)
		try {
			const res = await callApi('/api/v1/devices/' + encodeURIComponent(pluginForm.deviceId) + '/plugins', 'PUT', { enabled_plugins: enabled })
			if (res.statusCode === 200 && res.data && res.data.code === 0) {
				p.enabled = targetEnabled
				const toast = p.source === 'built-in'
					? (targetEnabled ? '已启用' : '已禁用')
					: (targetEnabled ? '已安装' : '已卸载')
				uni.showToast({ title: toast, icon: 'success' })
			} else {
				const msg = (res.data && (res.data.message || res.data.detail)) || '操作失败'
				uni.showToast({ title: msg, icon: 'none' })
			}
		} catch (e) {
			uni.showToast({ title: '操作失败: ' + (e.message || e), icon: 'none' })
		}
		p.saving = false
	}

	// 打开插件配置弹窗（填入当前值）
	const openPluginConfig = (p) => {
		pluginConfigForm.plugin = p.name
		pluginConfigForm.title = p.title || p.name
		pluginConfigForm.fields = (p.config_fields || []).map(f => ({
			key: f.key,
			label: f.label || f.key,
			placeholder: f.placeholder || '',
			required: !!f.required,
			value: (p.config && p.config[f.key]) || '',
		}))
		currentModal.value = 'pluginConfig'
	}

	// 保存插件配置
	const savePluginConfig = async () => {
		if (!pluginForm.deviceId || !pluginConfigForm.plugin || pluginConfigForm.saving) return
		const config = {}
		for (const f of pluginConfigForm.fields) {
			if (f.value) config[f.key] = f.value
		}
		pluginConfigForm.saving = true
		try {
			const res = await callApi('/api/v1/devices/' + encodeURIComponent(pluginForm.deviceId)
				+ '/plugins/' + encodeURIComponent(pluginConfigForm.plugin) + '/config', 'PUT', { config })
			if (res.statusCode === 200 && res.data && res.data.code === 0) {
				uni.showToast({ title: '配置已保存', icon: 'success' })
				hideModal()
				loadPlugins()  // 刷新商店状态（配置标记）
			} else {
				const msg = (res.data && (res.data.message || res.data.detail)) || '保存失败'
				uni.showToast({ title: msg, icon: 'none' })
			}
		} catch (e) {
			uni.showToast({ title: '保存失败: ' + (e.message || e), icon: 'none' })
		}
		pluginConfigForm.saving = false
	}

	// 插件工具列表展示：优先中文描述（docstring 首行），缺失时回退工具名
	const toolsText = (p) => (p.tools || []).map(t => (typeof t === 'string' ? t : (t.description || t.name))).join('、')

	const loadSkills = async () => {
		skillsLoading.value = true
		try {
			const mac = currentDevice.value ? currentDevice.value.mac : ''
			const path = mac ? '/api/v1/skills?device_id=' + encodeURIComponent(mac) : '/api/v1/skills'
			const res = await callDeviceApi(path, 'GET')
			if (res && res.data && res.data.code === 0) {
				skillsList.value = res.data.data.skills || []
			} else {
				skillsList.value = []
			}
		} catch (e) {
			skillsList.value = []
		} finally {
			skillsLoading.value = false
		}
	}

	const openSkillModal = async (skill) => {
		if (skill) {
			skillForm.value = {
				name: skill.id,
				description: skill.description || '',
				instructions: '',
				categoryStr: (skill.category || []).join(','),
				tagsStr: (skill.tags || []).join(','),
				editing: true,
			}
			showModal('skill')
			try {
				const res = await callDeviceApi('/api/v1/skills/' + skill.id, 'GET')
				if (res && res.data && res.data.code === 0) {
					skillForm.value.instructions = res.data.data.instructions || ''
				}
			} catch (e) {}
		} else {
			skillForm.value = { name: '', description: '', instructions: '', categoryStr: '', tagsStr: '', editing: false }
			showModal('skill')
		}
	}

	const submitSkill = async () => {
		const f = skillForm.value
		if (!f.name.trim()) { uni.showToast({ title: '请输入技能名称', icon: 'none' }); return }
		if (!f.description.trim()) { uni.showToast({ title: '请输入激活描述', icon: 'none' }); return }
		if (!f.instructions.trim()) { uni.showToast({ title: '请输入执行指令', icon: 'none' }); return }

		const parseList = (s) => s.split(',').map(x => x.trim()).filter(Boolean)
		const mac = currentDevice.value ? currentDevice.value.mac : ''

		uni.showLoading({ title: f.editing ? '保存中...' : '创建中...', mask: true })
		try {
			const url = f.editing ? '/api/v1/skills/' + f.name.trim() : '/api/v1/skills'
			const method = f.editing ? 'PUT' : 'POST'
			const res = await callDeviceApi(url, method, {
				name: f.name.trim(),
				description: f.description.trim(),
				instructions: f.instructions.trim(),
				category: parseList(f.categoryStr),
				tags: parseList(f.tagsStr),
				device_id: mac,
			})
			uni.hideLoading()
			if (res && res.data && res.data.code === 0) {
				uni.showToast({ title: f.editing ? '保存成功' : '创建成功', icon: 'success' })
				loadSkills()
				hideModal()
			} else {
				const msg = (res && res.data && res.data.message) || '操作失败'
				uni.showToast({ title: msg, icon: 'none', duration: 3000 })
			}
		} catch (e) {
			uni.hideLoading()
			uni.showToast({ title: '操作出错', icon: 'none' })
		}
	}

	const toggleSkill = async (skill) => {
		const dev = currentDevice.value
		const mac = dev && (dev.mac || dev.authKey || '')
		if (!mac) { uni.showToast({ title: '请先添加设备', icon: 'none' }); return }
		const newState = !skill.disabled
		try {
			const res = await callDeviceApi('/api/v1/skills/' + encodeURIComponent(skill.id) + '/toggle?device_id=' + encodeURIComponent(mac) + '&disabled=' + newState, 'POST')
			if (res && res.data && res.data.code === 0) {
				skill.disabled = newState
				uni.showToast({ title: newState ? '已禁用' : '已启用', icon: 'success' })
			} else {
				uni.showToast({ title: res?.data?.message || '操作失败', icon: 'none' })
			}
		} catch (e) {
			uni.showToast({ title: '网络错误', icon: 'none' })
		}
	}

	const confirmDeleteSkill = (skill) => {
		uni.showModal({
			title: '删除技能',
			content: '确定删除技能「' + skill.id + '」吗？此操作不可恢复。',
			confirmColor: '#ef4444',
			success: async (res) => {
				if (!res.confirm) return
				uni.showLoading({ title: '删除中...', mask: true })
				try {
					const r = await callDeviceApi('/api/v1/skills/' + skill.id, 'DELETE')
					uni.hideLoading()
					if (r && r.data && r.data.code === 0) {
						uni.showToast({ title: '已删除', icon: 'success' })
						loadSkills()
					} else {
						uni.showToast({ title: (r && r.data && r.data.message) || '删除失败', icon: 'none' })
					}
				} catch (e) {
					uni.hideLoading()
					uni.showToast({ title: '删除出错', icon: 'none' })
				}
			}
		})
	}

	const viewSkillDetail = async (skill) => {
		skillDetail.value = { id: skill.id, description: skill.description, category: skill.category, tags: skill.tags, document: '' }
		skillDetailLoading.value = true
		showModal('skillDetail')
		try {
			const res = await callDeviceApi('/api/v1/skills/' + skill.id, 'GET')
			if (res && res.data && res.data.code === 0) {
				skillDetail.value = res.data.data
			}
		} catch (e) {
			uni.showToast({ title: '加载失败', icon: 'none' })
		} finally {
			skillDetailLoading.value = false
		}
	}

	// ===== MCP 管理 =====
	const mcpList = ref([])
	const mcpLoading = ref(false)
	const mcpForm = ref({ name: '', type: 'streamable_http', url: '', headersStr: '', authStr: '', editing: false })

	const maskUrl = (url) => {
		if (!url) return ''
		const half = Math.ceil(url.length / 2)
		return url.substring(0, half) + '***'
	}

	// ===== MCP 工具列表 =====
	const mcpTools = ref([])
	const mcpToolsLoading = ref(false)
	const mcpToolsServer = ref('')

	const openMcpTools = async (mcp) => {
		const dev = currentDevice.value
		const mac = dev && (dev.mac || dev.authKey || '')
		if (!mac) return
		mcpToolsServer.value = mcp.name
		mcpTools.value = []
		mcpToolsLoading.value = true
		hideModal()
		setTimeout(() => { showModal('mcpTools') }, 100)
		try {
			const [toolsRes, disRes] = await Promise.all([
				callDeviceApi('/api/v1/devices/' + mac + '/mcp/' + encodeURIComponent(mcp.name) + '/tools', 'GET', null, 30000),
				callDeviceApi('/api/v1/devices/' + mac + '/mcp/disabled', 'GET')
			])
			const disabledTools = (disRes && disRes.data && disRes.data.code === 0) ? (disRes.data.data.disabled_tools || {})[mcp.name] || [] : []
			if (toolsRes && toolsRes.data && toolsRes.data.code === 0) {
				mcpTools.value = (toolsRes.data.data || []).map(t => ({
					...t,
					disabled: disabledTools.includes(t.name),
				}))
			}
		} catch (e) {
			console.log('MCP 工具加载错误:', e)
		} finally {
			mcpToolsLoading.value = false
		}
	}

	const closeMcpTools = () => {
		hideModal()
		setTimeout(() => { showModal('mcp') }, 100)
	}

	const toggleMcpServer = async (mcp) => {
		const dev = currentDevice.value
		const mac = dev && (dev.mac || dev.authKey || '')
		if (!mac) return
		const newState = !mcp.disabled
		try {
			const res = await callDeviceApi('/api/v1/devices/' + mac + '/mcp/' + encodeURIComponent(mcp.name) + '/toggle?disabled=' + newState, 'POST')
			if (res && res.data && res.data.code === 0) {
				mcp.disabled = newState
				uni.showToast({ title: newState ? '已禁用' : '已启用', icon: 'success' })
			}
		} catch (e) {
			uni.showToast({ title: '操作失败', icon: 'none' })
		}
	}

	const toggleMcpTool = async (tool) => {
		const dev = currentDevice.value
		const mac = dev && (dev.mac || dev.authKey || '')
		if (!mac || !mcpToolsServer.value) return
		const newState = !tool.disabled
		try {
			const res = await callDeviceApi('/api/v1/devices/' + mac + '/mcp/' + encodeURIComponent(mcpToolsServer.value) + '/tools/' + encodeURIComponent(tool.name) + '/toggle?disabled=' + newState, 'POST')
			if (res && res.data && res.data.code === 0) {
				tool.disabled = newState
				uni.showToast({ title: newState ? '已禁用' : '已启用', icon: 'success' })
			}
		} catch (e) {
			uni.showToast({ title: '操作失败', icon: 'none' })
		}
	}

	// ===== 工具选择器（技能编辑页） =====
	const toolPickerList = ref([])
	const toolPickerLoading = ref(false)
	const proactiveMaxPushes = ref(20)

	const onProactiveMaxChange = (e) => {
		proactiveMaxPushes.value = e.detail.value
		saveProactiveConfig()
	}

	const loadProactiveConfig = async () => {
		const dev = currentDevice.value
		if (!dev || !dev.mac) return
		try {
			const res = await callDeviceApi('/api/v1/devices/' + encodeURIComponent(dev.mac) + '/config', 'GET')
			const cfg = res?.data?.data || {}
			proactiveMaxPushes.value = cfg.wakeup?.proactive_max_pushes ?? 20
		} catch (e) {
			console.error('加载主动推送配置失败:', e)
		}
	}

	const saveProactiveConfig = async () => {
		const dev = currentDevice.value
		if (!dev || !dev.mac) return
		try {
			await callDeviceApi('/api/v1/devices/' + encodeURIComponent(dev.mac) + '/config', 'POST', {
				proactive_max_pushes: proactiveMaxPushes.value
			})
			console.log('主动推送配置已保存:', proactiveMaxPushes.value)
		} catch (e) {
			console.error('保存主动推送配置失败:', e)
		}
	}
	let instructionsCursorPos = 0

	const onInstructionsFocus = (e) => {
		if (e && e.detail) {
			instructionsCursorPos = e.detail.cursor || skillForm.value.instructions.length
		}
	}

	const onInstructionsInput = (e) => {
		if (e && e.detail) {
			instructionsCursorPos = e.detail.cursor || skillForm.value.instructions.length
		}
	}

	const openToolPicker = async () => {
		toolPickerList.value = []
		toolPickerLoading.value = true
		showModal('toolPicker')
		await loadToolList()
	}

	const loadToolList = async () => {
		try {
			const dev = currentDevice.value
			const mac = dev && (dev.mac || dev.authKey || '')
			if (!mac) {
				uni.showToast({ title: '请先选择设备', icon: 'none' })
				toolPickerLoading.value = false
				return
			}
			const url = '/api/v1/devices/' + mac + '/tools'
			const res = await callDeviceApi(url, 'GET', null, 30000)
			if (res && res.data && res.data.code === 0) {
				const allTools = res.data.data || []
				toolPickerList.value = allTools.filter(t => t.type !== 'mcp').map(t => ({ ...t, _descCollapsed: true }))
			} else {
				console.log('工具列表返回异常:', res)
			}
		} catch (e) {
			console.log('工具列表加载错误:', e)
		} finally {
			toolPickerLoading.value = false
		}
	}

	const insertToolName = (name) => {
		const cur = skillForm.value.instructions
		const before = cur.substring(0, instructionsCursorPos)
		const after = cur.substring(instructionsCursorPos)
		skillForm.value.instructions = before + name + after
		instructionsCursorPos += name.length
		hideModal()
		setTimeout(() => { showModal('skill') }, 100)
	}

	const loadMcpList = async () => {
		mcpLoading.value = true
		try {
			const dev = currentDevice.value
			// 使用 MAC 或 authKey 作为设备标识
			const mac = dev && (dev.mac || dev.authKey || '')
			if (!mac) {
				mcpList.value = []
				return
			}
			console.log('加载 MCP 列表, 设备标识:', mac)
			const [mcpRes, disRes] = await Promise.all([
				callDeviceApi('/api/v1/devices/' + mac + '/mcp', 'GET'),
				callDeviceApi('/api/v1/devices/' + mac + '/mcp/disabled', 'GET')
			])
			const disabledServers = (disRes && disRes.data && disRes.data.code === 0) ? (disRes.data.data.disabled_servers || []) : []
			if (mcpRes && mcpRes.data && mcpRes.data.code === 0) {
				const servers = mcpRes.data.data || {}
				mcpList.value = Object.keys(servers).map(name => ({
					name,
					type: servers[name].type || 'streamable_http',
					url: servers[name].url || '',
					headers: servers[name].headers || {},
					auth: servers[name].auth || {},
					disabled: disabledServers.includes(name),
				}))
			} else {
				mcpList.value = []
			}
		} catch (e) {
			console.log('MCP 加载错误:', e)
			mcpList.value = []
		} finally {
			mcpLoading.value = false
		}
	}

	const openMcpModal = async () => {
		const dev = currentDevice.value
		if (!dev) {
			uni.showToast({ title: '请先添加设备', icon: 'none' })
			return
		}
		// 如果没有 MAC 地址，尝试同步
		if (!dev.mac && dev.deviceIp) {
			await refreshDeviceMac()
		}
		if (!dev.mac && !dev.authKey) {
			uni.showToast({ title: '请先同步设备获取 MAC', icon: 'none' })
			return
		}
		showModal('mcp')
	}

	const openMcpAdd = () => {
		mcpForm.value = { name: '', type: 'streamable_http', url: '', headersStr: '', authStr: '', editing: false }
		hideModal()
		setTimeout(() => { showModal('mcpForm') }, 100)
	}

	const openMcpEdit = (mcp) => {
		mcpForm.value = {
			name: mcp.name,
			type: mcp.type || 'streamable_http',
			url: mcp.url || '',
			headersStr: mcp.headers && Object.keys(mcp.headers).length > 0 ? JSON.stringify(mcp.headers, null, 2) : '',
			authStr: mcp.auth && Object.keys(mcp.auth).length > 0 ? JSON.stringify(mcp.auth, null, 2) : '',
			editing: true,
		}
		hideModal()
		setTimeout(() => { showModal('mcpForm') }, 100)
	}

	const backToMcpList = () => {
		hideModal()
		setTimeout(() => { showModal('mcp') }, 100)
	}

	const submitMcp = async () => {
		const f = mcpForm.value
		if (!f.name.trim()) { uni.showToast({ title: '请输入服务器名称', icon: 'none' }); return }
		if (!f.url.trim()) { uni.showToast({ title: '请输入服务器 URL', icon: 'none' }); return }

		let headers = {}
		let auth = {}
		if (f.headersStr.trim()) {
			try { headers = JSON.parse(f.headersStr) } catch (e) { uni.showToast({ title: 'Headers JSON 格式错误', icon: 'none' }); return }
		}
		if (f.authStr.trim()) {
			try { auth = JSON.parse(f.authStr) } catch (e) { uni.showToast({ title: 'Auth JSON 格式错误', icon: 'none' }); return }
		}

		const dev = currentDevice.value
		const mac = dev && (dev.mac || dev.authKey || '')
		if (!mac) { uni.showToast({ title: '请先选择设备', icon: 'none' }); return }

		uni.showLoading({ title: f.editing ? '保存中...' : '添加中...', mask: true })
		try {
			const res = await callDeviceApi('/api/v1/devices/' + mac + '/mcp/' + f.name.trim(), 'PUT', {
				type: f.type,
				url: f.url.trim(),
				headers,
				auth,
			})
			uni.hideLoading()
			if (res && res.data && res.data.code === 0) {
				uni.showToast({ title: f.editing ? '保存成功' : '添加成功', icon: 'success' })
				hideModal()
				setTimeout(() => { showModal('mcp') }, 100)
				loadMcpList()
			} else {
				const msg = (res && res.data && res.data.message) || '操作失败'
				uni.showToast({ title: msg, icon: 'none', duration: 3000 })
			}
		} catch (e) {
			uni.hideLoading()
			uni.showToast({ title: '操作出错', icon: 'none' })
		}
	}

	const confirmDeleteMcp = (mcp) => {
		uni.showModal({
			title: '删除 MCP 服务器',
			content: '确定删除「' + mcp.name + '」吗？此操作不可恢复。',
			confirmColor: '#ef4444',
			success: async (res) => {
				if (!res.confirm) return
				const dev = currentDevice.value
				const mac = dev && (dev.mac || dev.authKey || '')
				if (!mac) { uni.showToast({ title: '请先选择设备', icon: 'none' }); return }
				uni.showLoading({ title: '删除中...', mask: true })
				try {
					const r = await callDeviceApi('/api/v1/devices/' + mac + '/mcp/' + mcp.name, 'DELETE')
					uni.hideLoading()
					if (r && r.data && r.data.code === 0) {
						uni.showToast({ title: '已删除', icon: 'success' })
						loadMcpList()
					} else {
						uni.showToast({ title: (r && r.data && r.data.message) || '删除失败', icon: 'none' })
					}
				} catch (e) {
					uni.hideLoading()
					uni.showToast({ title: '删除出错', icon: 'none' })
				}
			}
		})
	}

	const getBaseUrl = () => {
		return getServerUrl() || ('http://' + (currentDevice.value?.deviceIp || '192.168.31.176') + ':8088')
	}

	const callDeviceApi = (path, method = 'POST', data = null, timeout = 15000) => {
		const baseUrl = getBaseUrl()
		if (!baseUrl) {
			uni.showToast({ title: '请先配置服务器地址', icon: 'none' })
			return null
		}
		const headers = { 'Content-Type': 'application/json' }
		const token = uni.getStorageSync('esp_ai_token') || ''
		if (token) headers['Authorization'] = 'Bearer ' + token
		if (data && typeof data === 'object') {
			data = JSON.stringify(data)
		}
		return new Promise((resolve) => {
			uni.request({
				url: baseUrl + path,
				method: method,
				data: data,
				header: headers,
				timeout: timeout,
				success: (res) => {
					// 检测 401：token 过期，触发认证过期流程
					if (res.statusCode === 401) {
						handleAuthExpired()
					}
					console.log('API响应', path, res.statusCode, typeof res.data === 'string' ? res.data.substring(0,100) : JSON.stringify(res.data))
					resolve(res)
				},
				fail: (err) => { uni.showToast({ title: '网络错误', icon: 'none' }); resolve({ statusCode: 0, errMsg: err.errMsg }) }
			})
		})
	}

	const wakeDevice = () => {
		if (!currentDevice.value || !currentDevice.value.mac) {
			uni.showToast({ title: '请先选择设备', icon: 'none' })
			return
		}
		doWakeDevice()
	}

	const doWakeDevice = async () => {
		const mac = currentDevice.value.mac
		uni.showLoading({ title: '唤醒中...', mask: true })
		const res = await callDeviceApi('/api/v1/devices/' + mac + '/wakeup', 'POST')
		uni.hideLoading()
		if (res) {
			uni.showToast({ title: '唤醒成功', icon: 'success' })
			hideModal()
		}
	}

	const autoSyncDevice = () => {
		if (currentDevice.value && currentDevice.value.deviceIp) {
			refreshDeviceMac()
		}
	}

	// ===== 设备状态轮询 =====
	let deviceStatusPollTimer = null
	const DEVICE_STATUS_POLL_INTERVAL = 10000 // 10秒轮询一次

	const startDeviceStatusPolling = () => {
		stopDeviceStatusPolling()
		deviceStatusPollTimer = setInterval(() => {
			pollDeviceStatus()
		}, DEVICE_STATUS_POLL_INTERVAL)
	}

	const stopDeviceStatusPolling = () => {
		if (deviceStatusPollTimer) {
			clearInterval(deviceStatusPollTimer)
			deviceStatusPollTimer = null
		}
	}

	// 静默轮询设备状态（不显示 loading 和 toast）
	const pollDeviceStatus = async () => {
		if (!currentDevice.value) return
		if (!isLoggedIn()) return  // 未登录时跳过轮询
		const baseUrl = getBaseUrl()
		if (!baseUrl) return

		const headers = { 'Content-Type': 'application/json' }
		const token = uni.getStorageSync('esp_ai_token') || ''
		if (token) headers['Authorization'] = 'Bearer ' + token

		try {
			const res = await new Promise((resolve) => {
				uni.request({
					url: baseUrl + '/api/v1/devices',
					method: 'GET',
					header: headers,
					timeout: 5000,
					success: (r) => resolve(r),
					fail: () => resolve(null)
				})
			})

			if (!res) return
			// 检测 401：token 过期，触发认证过期流程
			if (res.statusCode === 401) {
				handleAuthExpired()
				return
			}
			if (!res.data) return

			let body = res.data
			if (typeof body === 'string') {
				try { body = JSON.parse(body) } catch (e) { return }
			}

			const inner = body.data || body
			const devices = inner.devices || []

			applyServerDevices(devices)
		} catch (e) {
			// 忽略错误
		}
	}

	// 按服务器返回更新本地设备（按 mac/device_id 精确匹配，只更新匹配项）。
	// 修复：原实现 devices.forEach 遍历服务器所有设备却全部写入 currentDevice，
	// 导致当前设备的名字/在线状态被服务器其他设备覆盖（"乱改名字"+"在线显示离线"）。
	const applyServerDevices = (devices) => {
		if (!devices || devices.length === 0) return false
		let updated = false
		const list = loadDevices()
		console.log('[设备轮询] 服务器返回:', JSON.stringify(devices))
		console.log('[设备轮询] 本地列表:', JSON.stringify(list))
		devices.forEach(d => {
			const serverId = d.device_id || ''
			const serverMac = d.mac || ''
			if (!serverId && !serverMac) return
			const isOnline = d.online === true || d.connected === true
			const serverName = d.name || ''
			// 在本地列表中按 mac 或 id 匹配同一台设备
			const idx = list.findIndex(local =>
				(serverMac && local.mac && local.mac === serverMac) ||
				(serverId && local.id && local.id === serverId)
			)
			console.log('[设备轮询] 服务器设备', serverId, serverName, '→ 匹配本地 idx=', idx)
			if (idx < 0) return
			const entry = { ...list[idx] }
			if (serverName && serverName !== entry.name) entry.name = serverName
			if (serverMac && serverMac !== entry.mac) entry.mac = serverMac
			if (entry.online !== isOnline) entry.online = isOnline
			if (JSON.stringify(entry) !== JSON.stringify(list[idx])) {
				list[idx] = entry
				updated = true
			}
		})
		if (updated) {
			saveDevices(list)
			deviceList.value = list
			// 同步 currentDevice 引用，保证界面立即反映最新状态
			if (currentDevice.value) {
				const cur = list.find(x => x.id === currentDevice.value.id)
				if (cur) currentDevice.value = cur
			}
		}
		return updated
	}

	const refreshDeviceMac = async () => {
		uni.showLoading({ title: '获取设备列表...', mask: true })
		const res = await callDeviceApi('/api/v1/devices', 'GET')
		uni.hideLoading()
		if (res && res.data) {
			let body = res.data
			if (typeof body === 'string') try { body = JSON.parse(body) } catch(e) {}
			const inner = body.data || body
			const devices = inner.devices || []
			// 与 pollDeviceStatus 共用按 mac/id 匹配的更新逻辑（不再跨设备串写）
			const updated = applyServerDevices(devices)
			if (updated) uni.showToast({ title: '同步成功', icon: 'success' })
			else uni.showToast({ title: '未找到匹配设备', icon: 'none' })
		}
	}

	const sendSpeak = () => {
		if (speakText.value.trim() === '') {
			uni.showToast({ title: '请输入内容', icon: 'none' })
			return
		}
		if (!currentDevice.value || !currentDevice.value.mac) {
			uni.showToast({ title: '请先选择设备', icon: 'none' })
			return
		}
		doSendSpeak()
	}

	const doSendSpeak = async () => {
		try {
			const mac = currentDevice.value.mac
			const text = speakText.value.trim()
			uni.showLoading({ title: '发送中...', mask: true })
			const res = await callDeviceApi('/api/v1/devices/' + mac + '/speak', 'POST', { text })
			uni.hideLoading()
			if (res) {
				if (res.statusCode && res.statusCode >= 400) {
					uni.showToast({ title: '发送失败: HTTP ' + res.statusCode, icon: 'none', duration: 3000 })
					return
				}
				uni.showToast({ title: '已发送', icon: 'success' })
				speakText.value = ''
				speakFocus.value = false
				setTimeout(() => { speakFocus.value = true }, 100)
			}
		} catch(e) {
			uni.hideLoading()
			uni.showToast({ title: '发送出错: ' + (e.message || e.errMsg || ''), icon: 'none', duration: 3000 })
		}
	}

	let volTimer = null
	const onVolumeTouchStart = (e) => {
		updateVolumeFromTouch(e)
	}

	const onVolumeTouchMove = (e) => {
		updateVolumeFromTouch(e)
	}

	const updateVolumeFromTouch = (e) => {
		const touch = e.touches[0]
		if (!touch) return
		uni.createSelectorQuery().select('.volume-float-slider').boundingClientRect((rect) => {
			if (rect) {
				const x = touch.clientX - rect.left
				const pct = Math.max(0, Math.min(100, (x / rect.width) * 100))
				volumeValue.value = Math.round(pct)
				if (volumeTimer) clearTimeout(volumeTimer)
				volumeTimer = setTimeout(() => { showVolumeFloat.value = false }, 4000)
				if (volTimer) clearTimeout(volTimer)
				volTimer = setTimeout(() => { saveVolume(true) }, 800)
			}
		}).exec()
	}

	const saveVolume = async (silent) => {
		if (!currentDevice.value || !currentDevice.value.mac) { return }
		doSaveVolume(silent)
	}

	const doSaveVolume = async (silent) => {
		try {
			const mac = currentDevice.value.mac
			const vol = Math.round((volumeValue.value / 100) * 10) / 10
			const res = await callDeviceApi('/api/v1/devices/' + mac + '/volume', 'POST', { volume: vol })
			if (!silent) {
				if (res) {
					if (res.statusCode && res.statusCode >= 400) {
						uni.showToast({ title: '音量设置失败: HTTP ' + res.statusCode, icon: 'none', duration: 3000 })
						return
					}
					uni.showToast({ title: '音量已设置', icon: 'success' })
					hideModal()
				}
			}
		} catch(e) {
			if (!silent) uni.showToast({ title: '音量出错: ' + (e.message || ''), icon: 'none' })
		}
	}

	const checkOtaUpdate = () => {
		if (!currentDevice.value || !currentDevice.value.mac) {
			uni.showToast({ title: '请先选择设备', icon: 'none' })
			return
		}
		// 第一次确认
		uni.showModal({
			title: '⚠️ OTA 升级',
			content: '此操作将强制推送最新固件到设备，升级过程中设备会重启，请确保设备已连接电源。\n\n确定要触发 OTA 升级吗？',
			confirmText: '我确定要升级',
			confirmColor: '#ef4444',
			cancelText: '取消',
			success: (res) => {
				if (res.confirm) {
					// 第二次确认
					uni.showModal({
						title: '⚠️ 最后警告',
						content: '这是最后警告！\n\nOTA 升级期间设备将重启，\n请勿断开设备电源。\n\n真的要触发 OTA 升级吗？',
						confirmText: '确认升级',
						confirmColor: '#ef4444',
						cancelText: '取消',
						success: (r) => {
							if (r.confirm) doOtaUpdate()
						}
					})
				}
			}
		})
	}

	const doOtaUpdate = async () => {
		const mac = currentDevice.value.mac
		uni.showLoading({ title: 'OTA升级中...', mask: true })
		const res = await callDeviceApi('/api/v1/devices/' + mac + '/ota/force', 'POST')
		uni.hideLoading()
		if (res) {
			uni.showToast({ title: 'OTA已触发', icon: 'success' })
			hideModal()
		}
	}

	onMounted(() => {
		// 注册认证过期回调（当 API 返回 401 或本地检测到 token 过期时触发）
		setAuthExpiredCallback(handleAuthExpired)

		// 启动时检查 token 是否已过期，同步响应式登录状态
		if (getToken() && isTokenExpired()) {
			isLoggedInRef.value = false
			handleAuthExpired()
		} else {
			isLoggedInRef.value = isLoggedIn()
		}

		// 定时检查 token 过期（每 30 秒）
		setInterval(() => {
			if (getToken() && isTokenExpired()) {
				handleAuthExpired()
			}
		}, 30000)

		setTimeout(() => {
			if (currentDevice.value && currentDevice.value.deviceIp) {
				autoSyncDevice()
			}
			// 加载当前设备表情包，用于首页屏幕显示「休息中」表情
			fetchEmos()
		}, 1000)
		
		// 定时轮询设备状态（每 10 秒）
		startDeviceStatusPolling()
	})
</script>

<style>
	.page {
		min-height: 100vh;
		background: linear-gradient(160deg, #e8f0fe 0%, #f0e6ff 30%, #fafafa 70%, #e6f7ec 100%);
		padding-bottom: 200rpx;
	}

	.home-tab, .ble-tab {
		animation: tabFadeIn 0.3s ease;
	}

	@keyframes tabFadeIn {
		from { opacity: 0; transform: translateY(16rpx); }
		to { opacity: 1; transform: translateY(0); }
	}

	.header {
		display: flex;
		flex-direction: row;
		justify-content: space-between;
		align-items: center;
		padding: 80rpx 48rpx 0;
	}

	.header-center {
		display: flex;
		flex-direction: column;
		align-items: flex-start;
	}

	.brand {
		font-size: 28rpx;
		font-weight: 600;
		color: #1a1a1a;
		letter-spacing: -0.5rpx;
	}

	.tagline {
		font-size: 16rpx;
		color: #b0b0b0;
		margin-top: 4rpx;
		font-weight: 400;
	}

	.device-status {
		display: flex;
		flex-direction: row;
		align-items: center;
		background-color: rgba(255, 255, 255, 0.9);
		padding: 14rpx 20rpx;
		border-radius: 20rpx;
		box-shadow: 0 2rpx 16rpx rgba(0, 0, 0, 0.04);
		margin-left: 12rpx;
	}

	.device-arrow {
		width: 0;
		height: 0;
		border-left: 6rpx solid transparent;
		border-right: 6rpx solid transparent;
		border-top: 6rpx solid #b0b0b0;
		margin-left: 10rpx;
		margin-top: 2rpx;
	}

	.pulse {
		width: 8rpx;
		height: 8rpx;
		background-color: #34d399;
		border-radius: 8rpx;
		margin-right: 10rpx;
		box-shadow: 0 0 12rpx rgba(52, 211, 153, 0.6);
		animation: pulseAnim 2s ease-in-out infinite;
	}

	@keyframes pulseAnim {
		0%, 100% { opacity: 0.7; transform: scale(1); }
		50% { opacity: 1; transform: scale(1.3); }
	}

	.device-name {
		font-size: 18rpx;
		color: #666666;
		font-weight: 500;
	}

	.device-list {
		display: flex;
		flex-direction: column;
		gap: 16rpx;
		padding: 0 24rpx;
	}

	.device-actions {
		margin-top: 24rpx;
		display: flex;
		justify-content: center;
	}

	.device-sync-btn {
		padding: 16rpx 40rpx;
		border-radius: 16rpx;
		background: linear-gradient(135deg, #34d399, #10b981);
	}

	.device-sync-text {
		font-size: 26rpx;
		color: #fff;
		font-weight: 600;
	}

	.device-card {
		background-color: #f8f8f8;
		border-radius: 20rpx;
		padding: 24rpx;
		display: flex;
		flex-direction: row;
		justify-content: space-between;
		align-items: center;
		border: 2rpx solid transparent;
	}

	.device-card.active {
		background-color: rgba(52, 211, 153, 0.08);
		border-color: #34d399;
	}

	.device-card-left {
		display: flex;
		flex-direction: row;
		align-items: center;
		flex: 1;
	}

	.device-card-icon {
		width: 48rpx;
		height: 48rpx;
		background-color: rgba(52, 211, 153, 0.1);
		border-radius: 14rpx;
		display: flex;
		justify-content: center;
		align-items: center;
		margin-right: 16rpx;
	}

	.device-card-dot {
		width: 18rpx;
		height: 18rpx;
		background-color: #34d399;
		border-radius: 6rpx;
	}

	.device-card-info {
		display: flex;
		flex-direction: column;
	}

	.device-card-name {
		font-size: 26rpx;
		font-weight: 600;
		color: #1a1a1a;
	}

	.device-card-mac {
		font-size: 20rpx;
		color: #b0b0b0;
		margin-top: 2rpx;
	}

	.device-card-auth {
		font-size: 20rpx;
		color: #34d399;
		margin-top: 2rpx;
	}
	.device-card-ip {
		font-size: 20rpx;
		color: #888;
		margin-top: 2rpx;
	}

	.no-device-text {
		font-size: 26rpx;
		color: #b0b0b0;
		text-align: center;
		padding: 40rpx 0;
	}

	.device-del {
		padding: 8rpx 16rpx;
		background: #fee2e2;
		border-radius: 10rpx;
		margin-left: 12rpx;
		flex-shrink: 0;
	}
	.device-del-text {
		font-size: 22rpx;
		color: #ef4444;
		font-weight: 500;
	}

	.device-card-desc {
		font-size: 20rpx;
		color: #b0b0b0;
		margin-top: 4rpx;
	}

	.device-card-right {
		display: flex;
		flex-direction: row;
		align-items: center;
		gap: 16rpx;
	}

	.device-card-status {
		display: flex;
		flex-direction: row;
		align-items: center;
		gap: 8rpx;
	}

	.status-dot {
		width: 10rpx;
		height: 10rpx;
		border-radius: 10rpx;
		background-color: #d0d0d0;
	}

	.status-dot.connected {
		background-color: #34d399;
		box-shadow: 0 0 8rpx rgba(52, 211, 153, 0.5);
	}

	.status-text {
		font-size: 20rpx;
		color: #b0b0b0;
	}

	.device-card-status.online .status-text {
		color: #34d399;
	}

	.device-check {
		width: 24rpx;
		height: 24rpx;
		background-color: #34d399;
		border-radius: 12rpx;
		display: flex;
		justify-content: center;
		align-items: center;
	}

	.hero {
		display: flex;
		justify-content: center;
		align-items: center;
		padding: 60rpx 0 48rpx;
	}

	.ai-core {
		position: relative;
		display: flex;
		justify-content: center;
		align-items: center;
	}

	.core-center {
		display: flex;
		justify-content: center;
		align-items: center;
	}

	/* ===== 设备硬件（仿 Web 端 DevicesView） ===== */
	.device-hardware {
		position: relative;
		width: 260rpx;
		height: 260rpx;
		border-radius: 36rpx;
		padding: 16rpx;
		background: linear-gradient(160deg, #ffd6e0, #f9a8d4);
		box-shadow: 0 12rpx 34rpx rgba(244, 114, 182, 0.28), inset 0 2rpx 0 rgba(255, 255, 255, 0.6);
		transition: all 0.6s ease;
	}

	.device-online {
		background: linear-gradient(160deg, #ffc9d6, #f590c6);
		box-shadow: 0 12rpx 40rpx rgba(244, 114, 182, 0.4), inset 0 2rpx 0 rgba(255, 255, 255, 0.6);
	}

	/* 设备边框装饰 */
	.device-bezel {
		position: absolute;
		top: 8rpx;
		left: 50%;
		transform: translateX(-50%);
		width: 44rpx;
		height: 3rpx;
		border-radius: 999rpx;
		background: rgba(255, 255, 255, 0.15);
	}

	/* ===== 屏幕 ===== */
	.device-screen {
		position: relative;
		width: 100%;
		height: 100%;
		border-radius: 14rpx;
		overflow: hidden;
		background: #0a0e14;
	}

	.device-screen.screen-off {
		background: #000;
	}

	/* 屏幕顶部状态栏 */
	.screen-statusbar {
		position: absolute;
		top: 0;
		left: 0;
		right: 0;
		height: 34rpx;
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 0 12rpx;
		background: rgba(0, 0, 0, 0.5);
		z-index: 3;
	}

	.status-left {
		display: flex;
		align-items: center;
		gap: 6rpx;
	}

	.icon-wifi {
		width: 14rpx;
		height: 14rpx;
		border-radius: 50%;
		background: #34d399;
		box-shadow: 0 0 6rpx rgba(52, 211, 153, 0.6);
	}

	.status-label {
		font-size: 14rpx;
		font-weight: 600;
		color: rgba(255, 255, 255, 0.7);
		max-width: 120rpx;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.status-right {
		display: flex;
		align-items: center;
	}

	/* 电池图标 */
	.icon-battery {
		display: flex;
		align-items: center;
	}

	.battery-body {
		width: 26rpx;
		height: 13rpx;
		border: 1px solid rgba(255, 255, 255, 0.5);
		border-radius: 3rpx;
		padding: 1rpx;
		display: flex;
		align-items: center;
	}

	.battery-level {
		height: 100%;
		background: #34d399;
		border-radius: 1rpx;
	}

	.battery-cap {
		width: 2rpx;
		height: 6rpx;
		background: rgba(255, 255, 255, 0.5);
		border-radius: 0 2rpx 2rpx 0;
		margin-left: 2rpx;
	}

	/* 屏幕内容：休息中表情 */
	.screen-content {
		width: 100%;
		height: 100%;
		display: flex;
		align-items: center;
		justify-content: center;
	}

	.screen-gif {
		width: 100%;
		height: 100%;
		display: block;
	}

	.screen-emoji {
		font-size: 64rpx;
		animation: breatheSoft 2.5s ease-in-out infinite;
	}

	@keyframes breatheSoft {
		0%, 100% { transform: scale(1); opacity: 0.9; }
		50% { transform: scale(1.06); opacity: 1; }
	}

	/* 离线黑屏 */
	.screen-off-content {
		width: 100%;
		height: 100%;
		display: flex;
		align-items: center;
		justify-content: center;
		background: #000;
	}

	.screen-off-text {
		font-size: 14rpx;
		font-weight: 700;
		color: rgba(255, 255, 255, 0.08);
		letter-spacing: 2rpx;
	}

	/* 屏幕反光 */
	.screen-glare {
		position: absolute;
		top: 0;
		left: 0;
		right: 0;
		bottom: 0;
		background: linear-gradient(135deg, rgba(255, 255, 255, 0.06) 0%, transparent 40%);
		pointer-events: none;
		border-radius: 14rpx;
	}

	/* 底部呼吸灯 */
	.device-led {
		position: absolute;
		bottom: 6rpx;
		left: 50%;
		transform: translateX(-50%);
		width: 8rpx;
		height: 8rpx;
		border-radius: 50%;
		background: rgba(255, 255, 255, 0.4);
		opacity: 0.3;
		transition: all 0.5s ease;
	}

	.device-led.on {
		background: #34d399;
		opacity: 1;
		box-shadow: 0 0 10rpx rgba(52, 211, 153, 0.8);
		animation: deviceLedBreathe 2s ease-in-out infinite;
	}

	@keyframes deviceLedBreathe {
		0%, 100% { opacity: 1; box-shadow: 0 0 10rpx rgba(52, 211, 153, 0.6); }
		50% { opacity: 0.5; box-shadow: 0 0 4rpx rgba(52, 211, 153, 0.2); }
	}

	.modules {
		padding: 0 28rpx;
		display: flex;
		flex-direction: column;
		gap: 20rpx;
	}

	.module {
		position: relative;
		border-radius: 24rpx;
		overflow: hidden;
		background: rgba(255, 255, 255, 0.6);
		backdrop-filter: blur(20px);
		-webkit-backdrop-filter: blur(20px);
		border: 1rpx solid rgba(255, 255, 255, 0.25);
		box-shadow: 0 4rpx 20rpx rgba(0, 0, 0, 0.04);
		transition: all 0.3s;
	}

	.module-pressed {
		transform: scale(0.97);
		opacity: 0.8;
	}

	.module-glass {
		display: none;
	}

	.module-body {
		position: relative;
		display: flex;
		flex-direction: row;
		align-items: center;
		padding: 24rpx 28rpx;
		gap: 20rpx;
	}

	.module-body::before {
		content: '';
		position: absolute;
		left: 0;
		top: 12rpx;
		bottom: 12rpx;
		width: 6rpx;
		border-radius: 3rpx;
	}

	.module-body.asr::before { background: linear-gradient(to bottom, #34d399, #22c55e); }
	.module-body.llm::before { background: linear-gradient(to bottom, #6ee7b7, #34d399); }
	.module-body.tts::before { background: linear-gradient(to bottom, #f472b6, #ec4899); }

	.module-icon {
		width: 80rpx;
		height: 80rpx;
		display: flex;
		justify-content: center;
		align-items: center;
		border-radius: 18rpx;
		flex-shrink: 0;
	}

	.module-icon.asr-icon { background: rgba(52, 211, 153, 0.15); }
	.module-icon.llm-icon { background: rgba(129, 140, 248, 0.15); }
	.module-icon.tts-icon { background: rgba(244, 114, 182, 0.15); }

	.module-icon .iconfont {
		font-size: 44rpx;
	}

	.icon-asr { color: #22c55e; }
	.icon-llm { color: #34d399; }
	.icon-tts { color: #ec4899; }
	.icon-tts { color: #ec4899; }

	.wave {
		display: flex;
		flex-direction: row;
		align-items: center;
	}

	.bar {
		width: 6rpx;
		background-color: #ec4899;
		border-radius: 3rpx;
		opacity: 0.9;
		margin-left: 6rpx;
	}

	.bar:first-child {
		margin-left: 0;
	}

	.bar.b1 { height: 22rpx; }
	.bar.b2 { height: 36rpx; }
	.bar.b3 { height: 48rpx; }
	.bar.b4 { height: 28rpx; }

	.module-text {
		flex: 1;
		display: flex;
		flex-direction: column;
	}

	.module-title {
		font-size: 26rpx;
		font-weight: 600;
		color: #1a1a1a;
		letter-spacing: -0.3rpx;
	}

	.module-sub {
		font-size: 18rpx;
		color: #b0b0b0;
		font-weight: 400;
		margin-top: 2rpx;
	}

	.module-status {
		display: flex;
		align-items: center;
	}

	.dot {
		width: 8rpx;
		height: 8rpx;
		background-color: #34d399;
		border-radius: 8rpx;
		opacity: 0.8;
	}

	.settings {
		display: flex;
		flex-direction: row;
		flex-wrap: wrap;
		padding: 32rpx 24rpx;
		gap: 24rpx 0;
	}

	.setting {
		width: 33.333%;
		display: flex;
		flex-direction: column;
		align-items: center;
		padding: 20rpx 0;
	}

	.setting-pressed {
		transform: scale(0.93);
		opacity: 0.7;
	}

	.setting-icon-bg {
		width: 96rpx;
		height: 96rpx;
		border-radius: 28rpx;
		display: flex;
		justify-content: center;
		align-items: center;
	}
	.bg-blue { background: rgba(59,130,246,0.12); }
	.bg-green { background: rgba(52,211,153,0.12); }
	.bg-orange { background: rgba(251,146,60,0.12); }
	.bg-yellow { background: rgba(250,204,21,0.12); }
	.bg-green { background: rgba(52,211,153,0.12); }
	.bg-gray { background: rgba(148,163,184,0.12); }

	.setting-label {
		font-size: 24rpx;
		color: #666;
		margin-top: 14rpx;
		font-weight: 500;
	}

	/* 唤醒图标 - 声波 */
	.icon-wake {
		position: relative;
		width: 44rpx;
		height: 44rpx;
		display: flex;
		align-items: flex-end;
		justify-content: center;
		gap: 4rpx;
	}
	.wake-bar {
		width: 5rpx;
		background: #3b82f6;
		border-radius: 3rpx;
	}
	.wake-bar.wb1 { height: 12rpx; }
	.wake-bar.wb2 { height: 24rpx; }
	.wake-bar.wb3 { height: 36rpx; }
	.wake-bar.wb4 { height: 24rpx; }
	.wake-bar.wb5 { height: 12rpx; }

	/* 说话图标 - 麦克风 */
	.icon-speak { position: relative; width: 32rpx; height: 44rpx; display: flex; flex-direction: column; align-items: center; }
	.speak-mic {
		width: 24rpx; height: 32rpx;
		background: #34d399; border-radius: 12rpx 12rpx 16rpx 16rpx;
	}
	.speak-base {
		margin-top: 4rpx;
		width: 32rpx; height: 3rpx;
		background: #34d399; border-radius: 2rpx;
	}

	/* 音量图标 */
	.icon-vol { position: relative; width: 40rpx; height: 36rpx; display: flex; align-items: center; }
	.vol-speaker {
		width: 14rpx; height: 18rpx;
		background: #fb923c; border-radius: 4rpx;
		position: relative;
	}
	.vol-speaker::after {
		content: ''; position: absolute; right: -8rpx; top: -2rpx;
		width: 0; height: 0;
		border-left: 10rpx solid #fb923c;
		border-top: 11rpx solid transparent;
		border-bottom: 11rpx solid transparent;
	}
	.vol-wave {
		position: absolute; right: 0;
		border: 3rpx solid #fb923c;
		border-radius: 50%;
		border-left-color: transparent;
		border-top-color: transparent;
		border-bottom-color: transparent;
	}
	.vol-wave.v1 { width: 12rpx; height: 20rpx; top: 8rpx; }
	.vol-wave.v2 { width: 20rpx; height: 30rpx; top: 3rpx; right: -4rpx; }

	/* 表情图标 */
	.icon-emo { width: 40rpx; height: 40rpx; }
	.emo-face {
		width: 40rpx; height: 40rpx;
		border: 3rpx solid #eab308; border-radius: 50%;
		position: relative;
	}
	.emo-eye {
		position: absolute; width: 5rpx; height: 5rpx;
		background: #eab308; border-radius: 50%; top: 12rpx;
	}
	.emo-eye.el { left: 10rpx; }
	.emo-eye.er { right: 10rpx; }
	.emo-mouth {
		position: absolute; bottom: 8rpx; left: 50%; margin-left: -8rpx;
		width: 16rpx; height: 8rpx;
		border-bottom: 3rpx solid #eab308;
		border-radius: 0 0 10rpx 10rpx;
	}

	/* MCP 图标 - 三点连线 */
	.icon-mcp { display: flex; flex-direction: row; align-items: center; gap: 4rpx; }
	.mcp-node { width: 10rpx; height: 10rpx; background: #34d399; border-radius: 50%; }
	.mcp-line { width: 10rpx; height: 3rpx; background: #34d399; border-radius: 2rpx; }

	/* 关于图标 */
	.icon-about { display: flex; flex-direction: column; align-items: center; }
	.about-circle {
		width: 24rpx; height: 24rpx;
		border: 3rpx solid #94a3b8; border-radius: 50%;
		display: flex; justify-content: center; align-items: center;
	}
	.about-dot {
		width: 4rpx; height: 4rpx; background: #94a3b8; border-radius: 50%;
		margin-top: 8rpx;
	}
	.about-line {
		width: 3rpx; height: 12rpx; background: #94a3b8; border-radius: 2rpx;
		margin-top: 4rpx;
	}

	.nav {
		position: fixed;
		bottom: 40rpx;
		left: 48rpx;
		right: 48rpx;
		background: rgba(255, 255, 255, 0.55);
		backdrop-filter: blur(40px);
		-webkit-backdrop-filter: blur(40px);
		border: 1rpx solid rgba(255, 255, 255, 0.25);
		border-radius: 28rpx;
		padding: 12rpx 16rpx;
		display: flex;
		flex-direction: row;
		justify-content: space-around;
		align-items: center;
		box-shadow: 0 8rpx 40rpx rgba(0, 0, 0, 0.08);
	}

	.nav-item {
		display: flex;
		flex-direction: column;
		justify-content: center;
		align-items: center;
		padding: 8rpx 24rpx;
	}

	.nav-pressed {
		transform: scale(0.95);
	}

	.nav-label {
		font-size: 20rpx;
		color: #999999;
		margin-top: 4rpx;
	}

	.nav-item.active .nav-label {
		color: #34d399;
	}

	.nav-icon-wrap {
		width: 56rpx;
		height: 56rpx;
		display: flex;
		justify-content: center;
		align-items: center;
	}

	.nav-item.active .nav-icon-wrap {
		background-color: #34d399;
		border-radius: 16rpx;
	}

	.nav-icon {
		width: 28rpx;
		height: 28rpx;
	}

	.nav-icon.home {
		background-color: #d0d0d0;
		border-radius: 6rpx;
	}

	.nav-item.active .nav-icon.home {
		background-color: #ffffff;
	}

	.nav-iconfont {
		font-size: 32rpx !important;
		color: #d0d0d0;
	}

	.nav-item.active .nav-iconfont {
		color: #ffffff;
	}

	.nav-icon.ble {
		position: relative;
		display: flex;
		justify-content: center;
		align-items: center;
	}

	.nav-icon.ble::before {
		content: '';
		width: 0;
		height: 0;
		border-top: 12rpx solid transparent;
		border-bottom: 12rpx solid transparent;
		border-right: 14rpx solid transparent;
		border-left: 14rpx solid transparent;
		border-left-color: #d0d0d0;
		border-right-color: transparent;
		transform: rotate(-45deg);
	}

	.nav-icon.ble::after {
		content: '';
		position: absolute;
		width: 6rpx;
		height: 26rpx;
		background-color: #d0d0d0;
		border-radius: 3rpx;
	}

	.nav-item.active .nav-icon.ble::before {
		border-left-color: #ffffff;
	}

	.nav-item.active .nav-icon.ble::after {
		background-color: #ffffff;
	}

	/* ===== 我的 Tab ===== */
	.profile-tab {
		flex: 1;
		padding: 20rpx 32rpx;
		padding-bottom: 140rpx;
		overflow-y: auto;
	}

	.profile-brand {
		display: flex;
		flex-direction: column;
		align-items: center;
		margin: 40rpx 0 36rpx;
	}

	.profile-brand-title {
		font-size: 48rpx;
		font-weight: 800;
		background: linear-gradient(135deg, #6ee7b7, #34d399);
		-webkit-background-clip: text;
		-webkit-text-fill-color: transparent;
	}

	.profile-brand-sub {
		font-size: 24rpx;
		color: #999;
		margin-top: 8rpx;
	}

	.profile-switch {
		position: relative;
		display: flex;
		flex-direction: row;
		background: #f0f0f0;
		border-radius: 16rpx;
		margin-bottom: 32rpx;
		overflow: hidden;
	}

	.profile-switch-item {
		flex: 1;
		padding: 20rpx 0;
		text-align: center;
		z-index: 2;
		position: relative;
	}

	.profile-switch-text {
		font-size: 28rpx;
		color: #888;
		font-weight: 500;
	}

	.profile-switch-item.on .profile-switch-text {
		color: #fff;
	}

	.profile-switch-bar {
		position: absolute;
		left: 0;
		top: 0;
		width: 50%;
		height: 100%;
		background: linear-gradient(135deg, #6ee7b7, #34d399);
		border-radius: 16rpx;
		z-index: 1;
		transition: left 0.3s;
	}

	.profile-form {
		background: #fff;
		border-radius: 20rpx;
		padding: 32rpx 28rpx;
		box-shadow: 0 8rpx 24rpx rgba(0,0,0,0.06);
		display: flex;
		flex-direction: column;
		gap: 24rpx;
	}

	.profile-input-row {
		position: relative;
	}

	.profile-input-label {
		font-size: 24rpx;
		color: #666;
		margin-bottom: 8rpx;
		display: block;
	}

	.profile-input {
		width: 100%;
		height: 80rpx;
		background: #f5f5f5;
		border-radius: 16rpx;
		padding: 0 24rpx;
		font-size: 28rpx;
		box-sizing: border-box;
	}

	.profile-eye {
		position: absolute;
		right: 16rpx;
		bottom: 16rpx;
		padding: 8rpx;
	}

	.profile-eye-text {
		font-size: 22rpx;
		color: #34d399;
	}

	.profile-error {
		font-size: 24rpx;
		color: #ef4444;
		padding: 8rpx 0;
	}

	.profile-btn {
		width: 100%;
		height: 88rpx;
		border-radius: 20rpx;
		background: linear-gradient(135deg, #6ee7b7, #34d399);
		display: flex;
		align-items: center;
		justify-content: center;
		margin-top: 16rpx;
		box-shadow: 0 8rpx 24rpx rgba(52,211,153,0.3);
	}

	.profile-btn-p {
		opacity: 0.8;
	}

	.profile-btn-text {
		font-size: 30rpx;
		color: #fff;
		font-weight: 600;
	}

	.profile-user-card {
		display: flex;
		flex-direction: row;
		align-items: center;
		padding: 32rpx;
		background: linear-gradient(135deg, #6ee7b7, #34d399);
		border-radius: 24rpx;
		margin: 20rpx 0 32rpx;
		box-shadow: 0 8rpx 24rpx rgba(52,211,153,0.25);
	}

	.profile-avatar {
		width: 80rpx;
		height: 80rpx;
		border-radius: 50%;
		background: rgba(255,255,255,0.25);
		display: flex;
		align-items: center;
		justify-content: center;
		margin-right: 24rpx;
	}

	.profile-avatar-text {
		font-size: 32rpx;
		font-weight: 700;
		color: #fff;
	}

	.profile-user-info {
		display: flex;
		flex-direction: column;
	}

	.profile-user-name {
		font-size: 32rpx;
		font-weight: 700;
		color: #fff;
	}

	.profile-user-email {
		font-size: 24rpx;
		color: rgba(255,255,255,0.8);
		margin-top: 4rpx;
	}

	.profile-menu {
		background: #fff;
		border-radius: 20rpx;
		margin-bottom: 40rpx;
		overflow: hidden;
	}

	.profile-menu-item {
		display: flex;
		flex-direction: row;
		align-items: center;
		padding: 28rpx 24rpx;
		border-bottom: 1rpx solid #f0f0f0;
	}

	.profile-menu-icon {
		font-size: 32rpx;
		margin-right: 20rpx;
	}

	.profile-menu-label {
		flex: 1;
		font-size: 28rpx;
		color: #333;
	}

	.profile-menu-arrow {
		font-size: 36rpx;
		color: #ccc;
	}

	.profile-logout-btn {
		width: 100%;
		height: 88rpx;
		border-radius: 20rpx;
		border: 2rpx solid #ef4444;
		display: flex;
		align-items: center;
		justify-content: center;
		margin-bottom: 40rpx;
	}

	.profile-logout-text {
		font-size: 30rpx;
		color: #ef4444;
		font-weight: 600;
	}

	.profile-server-collapse {
		margin-top: 24rpx;
		padding: 16rpx 24rpx;
		background: #f5f5f7;
		border-radius: 16rpx;
		display: flex;
		flex-direction: row;
		justify-content: space-between;
		align-items: center;
	}

	.profile-server-collapse-text {
		font-size: 24rpx;
		color: #888;
	}

	.profile-server-collapse-arrow {
		font-size: 24rpx;
		color: #aaa;
	}

	.profile-server-section {
		margin-top: 12rpx;
		padding: 0 8rpx;
	}

	.profile-server-note {
		font-size: 20rpx;
		color: #bbb;
		margin-top: 8rpx;
		display: block;
	}

	.icon-skill,
	.icon-friend,
	.icon-setting {
		width: 32rpx;
		height: 32rpx;
	}

	.modal-mask {
		position: fixed;
		top: 0;
		left: 0;
		right: 0;
		bottom: 0;
		background-color: rgba(0, 0, 0, 0.4);
		display: flex;
		justify-content: center;
		align-items: center;
		z-index: 1000;
		opacity: 0;
		pointer-events: none;
		transition: opacity 0.3s ease;
	}

	.modal-mask.show {
		opacity: 1;
		pointer-events: auto;
	}

	.modal-container {
		width: 640rpx;
		background: rgba(255, 255, 255, 0.88);
		border-radius: 32rpx;
		overflow: hidden;
		transform: scale(0.85);
		transition: transform 0.3s ease;
	}

	.modal-container.show {
		transform: scale(1);
	}

	.modal-container.modal-top {
		position: fixed;
		top: 10%;
	}

	.modal-header {
		display: flex;
		flex-direction: row;
		justify-content: space-between;
		align-items: center;
		padding: 32rpx;
		border-bottom: 1px solid #f0f0f0;
	}

	.modal-title {
		font-size: 32rpx;
		font-weight: 600;
		color: #1a1a1a;
	}

	.modal-close {
		width: 48rpx;
		height: 48rpx;
		display: flex;
		justify-content: center;
		align-items: center;
	}

	.close-icon {
		width: 20rpx;
		height: 20rpx;
		position: relative;
	}

	.close-line {
		position: absolute;
		width: 24rpx;
		height: 3rpx;
		background-color: #999999;
		border-radius: 2rpx;
		top: 50%;
		left: 50%;
	}

	.close-line.line1 {
		transform: translate(-50%, -50%) rotate(45deg);
	}

	.close-line.line2 {
		transform: translate(-50%, -50%) rotate(-45deg);
	}

	.modal-body {
		padding: 32rpx;
		max-height: 70vh;
		overflow-y: auto;
	}

	.form-section {
		margin-bottom: 32rpx;
		overflow: hidden;
		animation: fadeInUp 0.3s ease;
	}
	@keyframes fadeInUp {
		from { opacity: 0; transform: translateY(16rpx); }
		to { opacity: 1; transform: translateY(0); }
	}

	.form-section:last-child {
		margin-bottom: 0;
	}

	.form-label {
		font-size: 24rpx;
		font-weight: 500;
		color: #666666;
		margin-bottom: 16rpx;
		display: block;
	}

	.engine-options {
		display: flex;
		flex-direction: row;
		gap: 20rpx;
	}

	.engine-options-single {
		display: flex;
		flex-direction: row;
	}

	.engine-option {
		flex: 1;
		background-color: #f8f8f8;
		border-radius: 16rpx;
		padding: 24rpx;
		display: flex;
		flex-direction: row;
		justify-content: space-between;
		align-items: center;
		border: 2rpx solid transparent;
	}

	.engine-option.active {
		background-color: rgba(52, 211, 153, 0.1);
		border-color: #34d399;
	}

	.engine-name {
		font-size: 26rpx;
		font-weight: 500;
		color: #1a1a1a;
	}

	.engine-check {
		width: 32rpx;
		height: 32rpx;
		background-color: #34d399;
		border-radius: 16rpx;
		display: flex;
		justify-content: center;
		align-items: center;
	}

	.check-dot {
		width: 12rpx;
		height: 12rpx;
		background-color: #ffffff;
		border-radius: 6rpx;
	}

	.model-options {
		display: flex;
		flex-direction: column;
		gap: 12rpx;
	}

	.model-option {
		background-color: #f8f8f8;
		border-radius: 16rpx;
		padding: 20rpx 24rpx;
		display: flex;
		flex-direction: row;
		justify-content: space-between;
		align-items: center;
		border: 2rpx solid transparent;
	}

	.model-option.active {
		background-color: rgba(52, 211, 153, 0.1);
		border-color: #34d399;
	}

	.model-name {
		font-size: 24rpx;
		font-weight: 500;
		color: #1a1a1a;
	}

	.model-check {
		width: 20rpx;
		height: 20rpx;
		background-color: #34d399;
		border-radius: 10rpx;
	}

	.form-input {
		width: 100%;
		height: 80rpx;
		background-color: #f8f8f8;
		border-radius: 16rpx;
		padding: 0 24rpx;
		font-size: 26rpx;
		color: #1a1a1a;
		box-sizing: border-box;
	}
	.form-input-wrap {
		position: relative;
		display: flex;
		align-items: center;
	}
	.form-input-inner {
		padding-right: 80rpx;
	}
	.eye-btn {
		position: absolute;
		right: 16rpx;
		width: 56rpx;
		height: 56rpx;
		display: flex;
		justify-content: center;
		align-items: center;
	}
	.eye-icon {
		width: 36rpx;
		height: 22rpx;
		border: 3rpx solid #bbb;
		border-radius: 18rpx;
		position: relative;
	}
	.eye-icon::after {
		content: '';
		position: absolute;
		top: 50%;
		left: 50%;
		transform: translate(-50%, -50%);
		width: 10rpx;
		height: 10rpx;
		background: #bbb;
		border-radius: 50%;
	}
	.eye-icon.off {
		border-color: #ddd;
	}
	.eye-icon.off::after {
		background: transparent;
		border: 3rpx solid #ddd;
		width: 12rpx;
		height: 12rpx;
	}
	.eye-icon.off::before {
		content: '';
		position: absolute;
		top: -4rpx;
		left: 50%;
		transform: translateX(-50%) rotate(45deg);
		width: 3rpx;
		height: 30rpx;
		background: #ddd;
	}

	.form-textarea {
		width: 100%;
		height: 160rpx;
		background-color: #f8f8f8;
		border-radius: 16rpx;
		padding: 20rpx 24rpx;
		font-size: 26rpx;
		color: #1a1a1a;
	}
	.voice-dropdown { position: relative; }
	.voice-trigger {
		display: flex; flex-direction: row; align-items: center; justify-content: space-between;
		height: 80rpx; background: #f8f8f8; border-radius: 16rpx; padding: 0 24rpx;
	}
	.voice-trigger-text { font-size: 26rpx; color: #1a1a1a; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
	.voice-trigger-arrow { font-size: 20rpx; color: #999; margin-left: 12rpx; transition: transform 0.2s; }
	.voice-trigger-arrow.open { transform: rotate(180deg); }
	.voice-dropdown-panel {
		margin-top: 12rpx; background: #fff; border-radius: 16rpx;
		border: 1rpx solid #eee; box-shadow: 0 8rpx 24rpx rgba(0,0,0,0.08);
		overflow: hidden;
	}
	.voice-dropdown-search {
		height: 72rpx; padding: 0 24rpx; font-size: 26rpx; color: #1a1a1a;
		border-bottom: 1rpx solid #f0f0f0; box-sizing: border-box; width: 100%;
	}
	.voice-dropdown-list { max-height: 480rpx; }
	.voice-dropdown-item {
		display: flex; flex-direction: row; align-items: center; justify-content: space-between;
		padding: 20rpx 24rpx; border-bottom: 1rpx solid #f5f5f5;
	}
	.voice-dropdown-item:last-child { border-bottom: none; }
	.voice-dropdown-item.active { background: rgba(52,211,153,0.1); }
	.voice-info { display: flex; flex-direction: column; flex: 1; min-width: 0; }
	.voice-name { font-size: 26rpx; font-weight: 500; color: #1a1a1a; }
	.voice-type { font-size: 20rpx; color: #999; margin-top: 4rpx; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
	.voice-tag { font-size: 20rpx; color: #34d399; background: rgba(52,211,153,0.1); padding: 4rpx 12rpx; border-radius: 6rpx; margin-left: 12rpx; flex-shrink: 0; }
	.voice-preview-btn { font-size: 20rpx; color: #7c3aed; background: rgba(124,58,237,0.1); padding: 4rpx 12rpx; border-radius: 6rpx; margin-left: 12rpx; flex-shrink: 0; }
	.voice-preview-text { line-height: 1; }
	.form-tip { font-size: 22rpx; color: #999; margin-top: 8rpx; }
	.collapsible-header { display: flex; flex-direction: row; justify-content: space-between; align-items: center; padding: 8rpx 0; }
	.collapsible-title { font-size: 24rpx; font-weight: 500; color: #666666; }
	.collapsible-arrow { font-size: 20rpx; color: #999; transition: transform 0.2s ease; }
	.collapsible-arrow.open { transform: rotate(180deg); }
	.collapsible-body { margin-top: 12rpx; display: flex; flex-direction: column; gap: 16rpx; }

	.modal-footer {
		display: flex;
		flex-direction: row;
		padding: 24rpx 32rpx 32rpx;
		gap: 20rpx;
	}

	.btn-cancel {
		flex: 1;
		height: 80rpx;
		background-color: #f8f8f8;
		border-radius: 16rpx;
		display: flex;
		justify-content: center;
		align-items: center;
	}

	.btn-cancel-pressed {
		transform: scale(0.98);
		background-color: #f0f0f0;
	}

	.btn-text-cancel {
		font-size: 28rpx;
		font-weight: 500;
		color: #666666;
	}

	.btn-confirm {
		flex: 1;
		height: 80rpx;
		background-color: #34d399;
		border-radius: 16rpx;
		display: flex;
		justify-content: center;
		align-items: center;
	}

	.btn-confirm-pressed {
		transform: scale(0.98);
		background-color: #2bc48a;
	}

	.btn-text-confirm {
		font-size: 28rpx;
		font-weight: 500;
		color: #ffffff;
	}

	.wake-content {
		display: flex;
		flex-direction: column;
		align-items: center;
		padding: 40rpx 0;
	}

	.wake-text {
		font-size: 32rpx;
		font-weight: 600;
		color: #1a1a1a;
		margin-bottom: 16rpx;
	}

	.wake-desc {
		font-size: 24rpx;
		color: #999999;
	}

	/* 音量悬浮条 */
	.volume-float {
		position: fixed;
		top: 50%;
		left: 50%;
		transform: translate(-50%, -50%);
		z-index: 2000;
		width: 520rpx;
		animation: volFadeIn 0.2s ease;
	}
	@keyframes volFadeIn {
		from { opacity: 0; transform: translate(-50%, -50%) scale(0.9); }
		to { opacity: 1; transform: translate(-50%, -50%) scale(1); }
	}
	.volume-float-bar {
		background: #ffffff;
		border-radius: 24rpx;
		padding: 28rpx 32rpx;
		box-shadow: 0 8rpx 40rpx rgba(0,0,0,0.12);
	}
	.volume-float-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		margin-bottom: 24rpx;
	}
	.volume-float-icon {
		font-size: 40rpx;
	}
	.volume-float-val {
		font-size: 44rpx;
		font-weight: 800;
		color: #1a1a2e;
		letter-spacing: 1rpx;
	}
	.volume-float-close {
		width: 44rpx;
		height: 44rpx;
		display: flex;
		align-items: center;
		justify-content: center;
		border-radius: 50%;
		background: #f0f0f0;
		font-size: 24rpx;
		color: #999;
	}
	.volume-float-slider {
		padding: 8rpx 0;
	}
	.slider-track {
		position: relative;
		width: 100%;
		height: 8rpx;
		background: #e8e8e8;
		border-radius: 4rpx;
		overflow: visible;
	}
	.slider-fill {
		position: absolute;
		left: 0;
		top: 0;
		height: 8rpx;
		background: linear-gradient(90deg, #10b981, #34d399);
		border-radius: 4rpx;
	}
	.slider-thumb {
		position: absolute;
		top: 50%;
		margin-top: -16rpx;
		margin-left: -16rpx;
		width: 32rpx;
		height: 32rpx;
		background: #ffffff;
		border-radius: 50%;
		box-shadow: 0 2rpx 8rpx rgba(0,0,0,0.2);
		border: 3rpx solid #10b981;
		z-index: 2;
	}

	.volume-buttons {
		display: flex;
		flex-direction: row;
		justify-content: center;
		margin-top: 40rpx;
		gap: 40rpx;
	}

	.volume-btn {
		width: 80rpx;
		height: 80rpx;
		background-color: #f8f8f8;
		border-radius: 40rpx;
		display: flex;
		justify-content: center;
		align-items: center;
	}

	.volume-btn-pressed {
		transform: scale(0.95);
		background-color: #f0f0f0;
	}

	.volume-btn-text {
		font-size: 40rpx;
		font-weight: 600;
		color: #34d399;
	}

	.btn-confirm-full {
		flex: 1;
		height: 80rpx;
		background-color: #34d399;
		border-radius: 16rpx;
		display: flex;
		justify-content: center;
		align-items: center;
	}

	.btn-confirm-full-pressed {
		transform: scale(0.98);
		background-color: #2bc48a;
	}

	.about-content {
		padding: 0 0 20rpx;
	}

	.about-item {
		display: flex;
		flex-direction: row;
		justify-content: space-between;
		align-items: center;
		padding: 20rpx 0;
		border-bottom: 1px solid #f0f0f0;
	}

	.about-label {
		font-size: 26rpx;
		color: #999999;
	}

	.about-value {
		font-size: 26rpx;
		font-weight: 500;
		color: #1a1a1a;
	}

	.about-desc {
		margin-top: 32rpx;
		padding: 24rpx;
		background-color: #f8f8f8;
		border-radius: 16rpx;
		font-size: 24rpx;
		color: #666666;
		line-height: 40rpx;
	}

	/* 表情包选择器 */
	.emo-pack-bar {
		margin-bottom: 24rpx;
		padding: 0 24rpx;
	}
	.emo-pack-scroll {
		white-space: nowrap;
	}
	.emo-pack-list {
		display: inline-flex;
		gap: 16rpx;
		padding: 4rpx 0;
	}
	.emo-pack-tab {
		display: inline-flex;
		align-items: center;
		gap: 8rpx;
		padding: 12rpx 24rpx;
		background: #f5f5f5;
		border-radius: 32rpx;
		border: 2rpx solid transparent;
		transition: all 0.2s;
	}
	.emo-pack-tab.active {
		background: rgba(59, 130, 246, 0.1);
		border-color: #3b82f6;
	}
	.emo-pack-tab-text {
		font-size: 26rpx;
		color: #333;
	}
	.emo-pack-tab.active .emo-pack-tab-text {
		color: #3b82f6;
		font-weight: 600;
	}
	.emo-pack-tab-count {
		font-size: 22rpx;
		color: #999;
		background: #e8e8e8;
		border-radius: 16rpx;
		padding: 2rpx 10rpx;
		min-width: 32rpx;
		text-align: center;
	}
	.emo-pack-tab.active .emo-pack-tab-count {
		background: rgba(59, 130, 246, 0.15);
		color: #3b82f6;
	}
	.emo-pack-add {
		border: 2rpx dashed #ccc;
		background: transparent;
		padding: 12rpx 20rpx;
	}
	.emo-pack-add .emo-pack-tab-text {
		font-size: 32rpx;
		color: #999;
	}

	/* 上传尺寸选择器 */
	.emo-size-bar {
		display: flex;
		align-items: center;
		gap: 16rpx;
		padding: 0 24rpx;
		margin-bottom: 20rpx;
	}
	.emo-size-label {
		font-size: 24rpx;
		color: #666;
		flex-shrink: 0;
	}
	.emo-size-options {
		display: flex;
		gap: 12rpx;
		flex-wrap: wrap;
	}
	.emo-size-opt {
		padding: 8rpx 20rpx;
		background: #f5f5f5;
		border-radius: 24rpx;
		border: 2rpx solid transparent;
		transition: all 0.2s;
	}
	.emo-size-opt.active {
		background: rgba(59, 130, 246, 0.1);
		border-color: #3b82f6;
	}
	.emo-size-opt-text {
		font-size: 24rpx;
		color: #333;
	}
	.emo-size-opt.active .emo-size-opt-text {
		color: #3b82f6;
		font-weight: 600;
	}

	/* 表情网格 */
	.emo-grid {
		display: grid;
		grid-template-columns: repeat(2, 1fr);
		gap: 20rpx;
		padding: 8rpx 24rpx;
	}
	.emo-item {
		background: #f8f8f8;
		border-radius: 20rpx;
		display: flex;
		flex-direction: column;
		align-items: center;
		padding: 20rpx 16rpx 12rpx;
		border: 2rpx solid transparent;
	}
	.emo-item:active { background: #e8e8e8; }
	.emo-img { width: 140rpx; height: 140rpx; border-radius: 12rpx; }
	.emo-empty { font-size: 40rpx; color: #ccc; line-height: 140rpx; }
	.emo-name { font-size: 24rpx; color: #666; text-align: center; margin-top: 8rpx; display: block; }

	.about-desc-text {
		font-size: 24rpx;
		color: #666666;
		line-height: 40rpx;
	}

	.about-link {
		display: flex;
		align-items: center;
		gap: 12rpx;
	}

	.about-link-text {
		font-size: 24rpx;
		color: #3498db;
		word-break: break-all;
	}

	.about-link-copy {
		font-size: 20rpx;
		color: #ffffff;
		background-color: #34d399;
		padding: 4rpx 12rpx;
		border-radius: 8rpx;
	}

	.btn-ota {
		flex: 1;
		height: 80rpx;
		background-color: #34d399;
		border-radius: 16rpx;
		display: flex;
		justify-content: center;
		align-items: center;
	}

	.btn-ota-pressed {
		transform: scale(0.98);
		background-color: #2bc48a;
	}

	.btn-ota-text {
		font-size: 28rpx;
		font-weight: 500;
		color: #ffffff;
	}

/* ====== BLE 配网 ====== */
.ble-tab { min-height: 100vh; padding-bottom: 180rpx; }
.ble-scan-area { display: flex; flex-direction: column; align-items: center; padding: 60rpx 0 30rpx; }
.ble-radar { position: relative; width: 280rpx; height: 280rpx; display: flex; justify-content: center; align-items: center; }
.ble-radar-circle { position: absolute; border-radius: 50%; border: 2rpx solid rgba(52,211,153,.12); background: rgba(52,211,153,.02); }
.ble-radar-circle.c1 { width: 280rpx; height: 280rpx; }
.ble-radar-circle.c2 { width: 210rpx; height: 210rpx; }
.ble-radar-circle.c3 { width: 140rpx; height: 140rpx; }
.ble-radar-circle.c4 { width: 70rpx; height: 70rpx; }
.ble-radar-circle.anim { animation: blePulse 2s ease-out infinite; }
.ble-radar-circle.c1.anim { animation-delay: 0s; } .ble-radar-circle.c2.anim { animation-delay: .4s; }
.ble-radar-circle.c3.anim { animation-delay: .8s; } .ble-radar-circle.c4.anim { animation-delay: 1.2s; }
@keyframes blePulse { 0% { transform: scale(.3); opacity: 1; border-color: rgba(52,211,153,.35); background: rgba(52,211,153,.06); } to { transform: scale(1); opacity: 0; border-color: transparent; background: transparent; } }
.ble-radar-center { position: relative; z-index: 2; width: 80rpx; height: 80rpx; background: #34d399; border-radius: 50%; display: flex; justify-content: center; align-items: center; box-shadow: 0 0 40rpx rgba(52,211,153,.4); }
.ble-bt-icon { position: relative; width: 28rpx; height: 38rpx; }
.ble-bt-path { position: absolute; width: 0; height: 0; }
.ble-bt-path.p1 { border-top: 19rpx solid #fff; border-left: 8rpx solid transparent; border-right: 8rpx solid transparent; top: 0; left: 50%; transform: translate(-50%); }
.ble-bt-path.p2 { border-bottom: 19rpx solid #fff; border-left: 8rpx solid transparent; border-right: 8rpx solid transparent; bottom: 0; left: 50%; transform: translate(-50%); }
.ble-radar-line { position: absolute; top: 50%; left: 50%; width: 2rpx; height: 90rpx; background: linear-gradient(to top,rgba(52,211,153,.9),transparent); transform-origin: top center; transform: translate(-50%) rotate(0); opacity: 0; }
.ble-radar-line.anim { opacity: 1; animation: bleScanRotate 2s linear infinite; }
@keyframes bleScanRotate { 0% { transform: translate(-50%) rotate(0); } to { transform: translate(-50%) rotate(360deg); } }
.ble-scan-tip { margin-top: 24rpx; font-size: 26rpx; color: #999; }
.ble-scan-btn { margin-top: 28rpx; padding: 16rpx 60rpx; background: #34d399; border-radius: 16rpx; }
.ble-btn-pressed { transform: scale(.96); background: #2bc48a; }
.ble-scan-btn-text { font-size: 28rpx; font-weight: 500; color: #fff; }
.ble-device-section { margin: 0 24rpx 20rpx; }
.ble-device-list { display: flex; flex-direction: column; gap: 12rpx; }
.ble-device-item { background: #fff; border-radius: 20rpx; padding: 24rpx 28rpx; display: flex; flex-direction: row; justify-content: space-between; align-items: center; border: 2rpx solid transparent; }
.ble-device-item.selected { border-color: #34d399; background: rgba(52,211,153,.04); }
.ble-device-info { display: flex; flex-direction: column; flex: 1; }
.ble-device-name { font-size: 28rpx; font-weight: 600; color: #1a1a1a; }
.ble-device-id { font-size: 20rpx; color: #b0b0b0; margin-top: 4rpx; }
.ble-device-rssi { font-size: 20rpx; color: #34d399; margin-top: 4rpx; }
.ble-signal-bars { display: flex; flex-direction: row; align-items: flex-end; gap: 4rpx; height: 32rpx; }
.ble-signal-bars .bar { width: 8rpx; border-radius: 2rpx; background: #e0e0e0; }
.ble-signal-bars .b1 { height: 10rpx; } .ble-signal-bars .b2 { height: 18rpx; }
.ble-signal-bars .b3 { height: 25rpx; } .ble-signal-bars .b4 { height: 32rpx; }
.ble-signal-bars.s1 .b1,.ble-signal-bars.s2 .b1,.ble-signal-bars.s2 .b2,.ble-signal-bars.s3 .b1,.ble-signal-bars.s3 .b2,.ble-signal-bars.s3 .b3,.ble-signal-bars.s4 .bar { background: #34d399; }
.ble-form { margin: 0 24rpx; }
.ble-fg-section { margin-bottom: 20rpx; }
.ble-fg-title { font-size: 26rpx; font-weight: 600; color: #666; margin-bottom: 12rpx; padding: 0 8rpx; }
.ble-fg-card { background: #fff; border-radius: 20rpx; padding: 8rpx 28rpx; }
.ble-fg-row { display: flex; flex-direction: row; align-items: center; padding: 20rpx 0; border-bottom: 1rpx solid #f0f0f0; }
.ble-fg-row:last-child { border-bottom: none; }
.ble-fg-label { font-size: 26rpx; font-weight: 500; color: #666; width: 160rpx; flex-shrink: 0; }
.ble-fg-input { font-size: 26rpx; color: #1a1a1a; flex: 1; height: 48rpx; }
.ble-fg-picker { flex: 1; display: flex; flex-direction: row; align-items: center; justify-content: space-between; padding: 14rpx 18rpx; background: #f8f8f8; border-radius: 12rpx; }
.ble-fg-pick-text { font-size: 24rpx; color: #1a1a1a; flex: 1; }
.ble-pick-arrow { width: 0; height: 0; border-left: 8rpx solid transparent; border-right: 8rpx solid transparent; border-top: 8rpx solid #b0b0b0; margin-left: 12rpx; }
.ble-btn-eye { width: 48rpx; height: 48rpx; display: flex; justify-content: center; align-items: center; }
.ble-eye { width: 32rpx; height: 20rpx; border: 2rpx solid #b0b0b0; border-radius: 50%; position: relative; display: flex; justify-content: center; align-items: center; }
.ble-eye.on { border-color: #34d399; }
.ble-eye:after { content: ""; width: 8rpx; height: 8rpx; background: #b0b0b0; border-radius: 50%; }
.ble-eye.on:after { background: #34d399; }
.ble-switch { width: 72rpx; height: 40rpx; background: #e0e0e0; border-radius: 20rpx; position: relative; transition: .2s; margin-left: auto; flex-shrink: 0; }
.ble-switch.on { background: #34d399; }
.ble-switch-knob { width: 32rpx; height: 32rpx; background: #fff; border-radius: 16rpx; position: absolute; top: 4rpx; left: 4rpx; box-shadow: 0 2rpx 6rpx rgba(0,0,0,.15); transition: .2s; }
.ble-switch.on .ble-switch-knob { left: 36rpx; }
.ble-radio-row { display: flex; flex-direction: row; gap: 30rpx; padding: 16rpx 0; }
.ble-radio { display: flex; flex-direction: row; align-items: center; gap: 8rpx; }
.ble-radio-dot { width: 28rpx; height: 28rpx; border-radius: 50%; border: 3rpx solid #d0d0d0; display: flex; justify-content: center; align-items: center; }
.ble-radio.on .ble-radio-dot { border-color: #34d399; }
.ble-radio-in { width: 14rpx; height: 14rpx; border-radius: 50%; background: #34d399; }
.ble-radio-label { font-size: 26rpx; color: #333; }
.ble-radio.on .ble-radio-label { color: #34d399; font-weight: 600; }
.ble-adv-toggle { display: flex; flex-direction: row; align-items: center; justify-content: center; padding: 24rpx 0; gap: 12rpx; }
.ble-adv-toggle-text { font-size: 26rpx; color: #34d399; font-weight: 500; }
.ble-adv-arrow { width: 0; height: 0; border-left: 10rpx solid transparent; border-right: 10rpx solid transparent; border-top: 12rpx solid #34d399; transition: transform .3s; }
.ble-adv-arrow.up { transform: rotate(180deg); }
.ble-btn-area { margin: 40rpx 0; }
.ble-btn-send { background: #34d399; border-radius: 20rpx; padding: 28rpx; display: flex; justify-content: center; align-items: center; }
.ble-btn-send-p { transform: scale(.98); background: #2bc48a; }
.ble-btn-send-text { font-size: 28rpx; font-weight: 700; color: #fff; }

/* ====== 技能管理 ====== */
.skills-tab { min-height: 100vh; padding: 0 24rpx 200rpx; animation: tabFadeIn 0.3s ease; }
.skills-header { display: flex; flex-direction: row; justify-content: space-between; align-items: center; padding: 24rpx 0; }
.skills-count-text { font-size: 24rpx; color: #999; }
.skills-add-btn { background: #34d399; border-radius: 16rpx; padding: 14rpx 32rpx; }
.skills-add-pressed { transform: scale(0.96); background: #2bc48a; }
.skills-add-text { font-size: 26rpx; font-weight: 600; color: #fff; }

.skills-empty { display: flex; flex-direction: column; align-items: center; padding: 120rpx 48rpx; }
.skills-empty-icon { font-family: 'iconfont'; font-size: 80rpx; color: #d0d0d0; margin-bottom: 24rpx; }
.skills-empty-text { font-size: 30rpx; font-weight: 600; color: #999; margin-bottom: 12rpx; }
.skills-empty-sub { font-size: 24rpx; color: #b0b0b0; text-align: center; }

.skills-loading { display: flex; justify-content: center; padding: 80rpx 0; }
.skills-loading-text { font-size: 26rpx; color: #999; }

.skills-list { display: flex; flex-direction: column; gap: 16rpx; }
.skill-card { background: #fff; border-radius: 20rpx; padding: 28rpx; box-shadow: 0 2rpx 16rpx rgba(0,0,0,0.04); }
.skill-card.disabled { opacity: 0.5; }
.skill-card-top { display: flex; flex-direction: row; justify-content: space-between; align-items: flex-start; }
.skill-toggle { margin-left: 16rpx; flex-shrink: 0; padding: 4rpx 0; }
.skill-toggle-track {
	width: 80rpx; height: 44rpx; border-radius: 22rpx;
	background: #ddd; position: relative;
	transition: background 0.2s;
}
.skill-toggle-track.on { background: #34d399; }
.skill-toggle-thumb {
	width: 36rpx; height: 36rpx; border-radius: 18rpx;
	background: #fff; position: absolute; top: 4rpx; left: 4rpx;
	box-shadow: 0 2rpx 4rpx rgba(0,0,0,0.15);
	transition: transform 0.2s;
}
.skill-toggle-track.on .skill-toggle-thumb { transform: translateX(36rpx); }
.skill-info { display: flex; flex-direction: column; flex: 1; margin-right: 16rpx; }
.skill-name { font-size: 28rpx; font-weight: 600; color: #1a1a1a; }
.skill-desc { font-size: 24rpx; color: #666; margin-top: 8rpx; line-height: 36rpx; }

.skill-tags { display: flex; flex-direction: row; flex-wrap: wrap; gap: 8rpx; margin-top: 16rpx; }
.skill-tag { font-size: 20rpx; color: #34d399; background: rgba(52,211,153,0.1); padding: 4rpx 14rpx; border-radius: 8rpx; }
.skill-tag.cat { color: #34d399; background: rgba(52,211,153,0.1); }

.skill-actions { display: flex; flex-direction: row; gap: 16rpx; margin-top: 20rpx; }
.skill-btn { flex: 1; height: 40rpx; border-radius: 12rpx; display: flex; justify-content: center; align-items: center; }
.skill-btn-edit { background: rgba(52,211,153,0.1); }
.skill-btn-del { background: rgba(239,68,68,0.08); }
.skill-btn-pressed { transform: scale(0.97); }
.skill-btn-text { font-size: 24rpx; font-weight: 500; color: #34d399; }
.skill-btn-text.del { color: #ef4444; }

.form-hint { font-size: 20rpx; color: #b0b0b0; margin-top: 8rpx; }
.form-textarea.tall { height: 280rpx; }

.skill-page { position: fixed; top: 0; left: 0; right: 0; bottom: 0; z-index: 2000; background: #fff; transform: translateY(100%); transition: transform 0.3s ease; pointer-events: none; }
.skill-page.show { transform: translateY(0); pointer-events: auto; }
.skill-page-header { position: absolute; top: 0; left: 0; right: 0; height: 100rpx; display: flex; flex-direction: row; justify-content: space-between; align-items: center; padding: 0 32rpx; border-bottom: 1px solid #f0f0f0; background: #fff; z-index: 1; }
.skill-page-title { font-size: 32rpx; font-weight: 600; color: #1a1a1a; }
.skill-page-close { padding: 8rpx; }
.skill-page-body { position: absolute; top: 100rpx; left: 0; right: 0; bottom: 130rpx; padding: 32rpx; box-sizing: border-box; overflow: hidden; }
.skill-page-textarea { width: 100%; height: 600rpx; background: #f8f8f8; border-radius: 16rpx; padding: 20rpx 24rpx; font-size: 26rpx; color: #1a1a1a; box-sizing: border-box; }
.skill-page-footer { position: absolute; left: 0; right: 0; bottom: 0; height: 130rpx; display: flex; flex-direction: row; padding: 24rpx 32rpx; gap: 20rpx; border-top: 1px solid #f0f0f0; background: #fff; }
.form-row { display: flex; flex-direction: row; gap: 16rpx; }
.form-row .form-section-grow { flex: 1; min-width: 0; }

/* ====== 设备插件管理 ====== */
.plugin-page-body { position: absolute; top: 100rpx; left: 0; right: 0; bottom: 130rpx; padding: 24rpx 32rpx; box-sizing: border-box; overflow: hidden; }
.plugin-device-row { display: flex; flex-direction: row; align-items: center; gap: 16rpx; padding: 16rpx 20rpx; background: #f5f7fa; border-radius: 12rpx; margin-bottom: 16rpx; }
.plugin-device-label { font-size: 24rpx; color: #999; }
.plugin-device-name { font-size: 26rpx; color: #1a1a1a; font-weight: 600; flex: 1; }
.plugin-note { font-size: 22rpx; color: #888; line-height: 1.6; margin-bottom: 20rpx; }
.plugin-loading { display: flex; justify-content: center; padding: 60rpx 0; }
.plugin-loading-text { font-size: 26rpx; color: #999; }
.plugin-card { background: #f8f8f8; border-radius: 16rpx; padding: 20rpx 24rpx; margin-bottom: 16rpx; border: 1px solid transparent; }
.plugin-card.on { border-color: rgba(52,211,153,0.5); background: rgba(52,211,153,0.06); }
.plugin-card-top { display: flex; flex-direction: row; justify-content: space-between; align-items: center; }
.plugin-info { flex: 1; min-width: 0; margin-right: 16rpx; }
.plugin-name-row { display: flex; flex-direction: row; align-items: center; gap: 12rpx; margin-bottom: 8rpx; }
.plugin-name { font-size: 30rpx; font-weight: 600; color: #1a1a1a; }
.plugin-installed { font-size: 18rpx; color: #34d399; background: rgba(52,211,153,0.12); padding: 2rpx 12rpx; border-radius: 8rpx; }
.plugin-requires { font-size: 18rpx; color: #007aff; background: rgba(0,122,255,0.1); padding: 2rpx 12rpx; border-radius: 8rpx; }
.plugin-desc { font-size: 24rpx; color: #555; display: block; margin-bottom: 6rpx; }
.plugin-tools { font-size: 22rpx; color: #999; display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.plugin-empty { display: flex; justify-content: center; padding: 60rpx 0; }
.plugin-empty-text { font-size: 26rpx; color: #999; }

/* ====== 插件商店 Tab（商品网格） ====== */
.store-tab { min-height: 100vh; padding: 0 28rpx 200rpx; animation: tabFadeIn 0.3s ease; }
.store-top { padding: 24rpx 4rpx 20rpx; }
.store-top-row { display: flex; flex-direction: row; align-items: center; gap: 16rpx; }
.store-top-label { font-size: 24rpx; color: #999; }
.store-top-device { font-size: 28rpx; color: #1a1a1a; font-weight: 600; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.store-refresh { background: #f0f0f0; border-radius: 24rpx; padding: 8rpx 26rpx; }
.store-refresh-pressed { transform: scale(0.95); }
.store-refresh-text { font-size: 24rpx; color: #666; }
.store-note { display: block; font-size: 22rpx; color: #999; margin-top: 10rpx; }
.store-grid-wrap { padding-bottom: 20rpx; }
.store-grid { display: flex; flex-direction: row; flex-wrap: wrap; justify-content: space-between; }
.goods-card { width: calc(50% - 10rpx); background: #fff; border-radius: 24rpx; padding: 28rpx 24rpx 24rpx; margin-bottom: 20rpx; box-shadow: 0 4rpx 20rpx rgba(0,0,0,0.05); border: 2rpx solid transparent; box-sizing: border-box; }
.goods-card.installed { border-color: rgba(52,211,153,0.6); }
.goods-card-pressed { transform: scale(0.97); }
.goods-body { display: flex; flex-direction: column; }
.goods-name-row { display: flex; flex-direction: row; align-items: center; gap: 10rpx; margin-bottom: 8rpx; }
.goods-name { font-size: 28rpx; font-weight: 600; color: #1a1a1a; }
.goods-tag { font-size: 18rpx; color: #007aff; background: rgba(0,122,255,0.08); padding: 2rpx 10rpx; border-radius: 8rpx; }
.goods-tag.builtin { color: #999; background: rgba(0,0,0,0.05); }
.goods-desc { font-size: 22rpx; color: #888; line-height: 1.5; min-height: 66rpx; margin-bottom: 16rpx; display: -webkit-box; -webkit-box-orient: vertical; -webkit-line-clamp: 2; overflow: hidden; }
.goods-bottom { display: flex; flex-direction: row; justify-content: flex-end; align-items: center; gap: 12rpx; }
.goods-config-btn { background: #f0f0f0; border-radius: 28rpx; padding: 10rpx 24rpx; }
.goods-config-btn.done { background: rgba(0,122,255,0.08); }
.goods-config-text { font-size: 22rpx; color: #666; }
.goods-config-btn.done .goods-config-text { color: #007aff; }
.goods-btn { background: linear-gradient(135deg, #34d399, #2bbd8a); border-radius: 28rpx; padding: 10rpx 34rpx; }
.goods-btn.installed { background: #fff0f0; border: 1px solid #ff6b6b; }
.goods-btn.disabled { opacity: 0.6; }
.goods-btn-pressed { transform: scale(0.95); }
.goods-btn-text { font-size: 24rpx; font-weight: 600; color: #fff; }
.goods-btn.installed .goods-btn-text { color: #ff6b6b; }

.skill-btn-view { background: rgba(52,211,153,0.1); }
.skill-btn-text.view { color: #34d399; }

.modal-wide { width: 88vw !important; max-height: 75vh; }
.detail-section { margin-bottom: 24rpx; }
.detail-label { font-size: 24rpx; color: #999; margin-bottom: 8rpx; }
.detail-text { font-size: 28rpx; color: #333; line-height: 42rpx; }
.detail-doc-box { background: #f8f8f8; border-radius: 12rpx; padding: 20rpx; max-height: 600rpx; overflow-y: auto; }
.detail-doc { font-size: 24rpx; color: #444; line-height: 40rpx; white-space: pre-wrap; word-break: break-all; }
.btn-full { width: 100%; }

/* ====== 自定义弹窗 ====== */
.dialog-mask {
	position: fixed;
	top: 0;
	left: 0;
	right: 0;
	bottom: 0;
	background-color: rgba(0, 0, 0, 0.45);
	z-index: 4000;
	opacity: 0;
	pointer-events: none;
	transition: opacity 0.25s ease;
	display: flex;
	justify-content: center;
	align-items: center;
}
.dialog-mask.show {
	opacity: 1;
	pointer-events: auto;
}
.dialog-box {
	width: 580rpx;
	background: #fff;
	border-radius: 28rpx;
	padding: 48rpx 40rpx 36rpx;
	transform: scale(0.9);
	opacity: 0;
	transition: all 0.25s cubic-bezier(0.32, 0.72, 0, 1);
}
.dialog-box.show {
	transform: scale(1);
	opacity: 1;
}
.dialog-title {
	font-size: 32rpx;
	font-weight: 600;
	color: #1a1a1a;
	text-align: center;
	display: block;
	margin-bottom: 28rpx;
}
.dialog-input {
	height: 80rpx;
	background: #f5f5f5;
	border-radius: 16rpx;
	padding: 0 24rpx;
	font-size: 28rpx;
	color: #333;
	margin: 0 8rpx 32rpx;
}
.dialog-msg {
	font-size: 28rpx;
	color: #666;
	text-align: center;
	display: block;
	margin-bottom: 32rpx;
	line-height: 1.5;
}
.dialog-actions {
	display: flex;
	gap: 20rpx;
}
.dialog-btn {
	flex: 1;
	height: 80rpx;
	border-radius: 16rpx;
	display: flex;
	justify-content: center;
	align-items: center;
}
.dialog-btn-cancel {
	background: #f5f5f5;
}
.dialog-btn-confirm {
	background: linear-gradient(135deg, #3b82f6, #2563eb);
}
.dialog-btn-danger {
	background: linear-gradient(135deg, #ef4444, #dc2626);
}
.dialog-btn-text {
	font-size: 28rpx;
	font-weight: 500;
}
.dialog-btn-text.cancel { color: #666; }
.dialog-btn-text.confirm { color: #fff; }
.dialog-btn-text.danger { color: #fff; }

/* ====== 统一抽屉组件 ====== */
.drawer-mask {
	position: fixed;
	top: 0;
	left: 0;
	right: 0;
	bottom: 0;
	background-color: rgba(0, 0, 0, 0.4);
	z-index: 3000;
	opacity: 0;
	pointer-events: none;
	transition: opacity 0.3s ease;
}
.drawer-mask.show {
	opacity: 1;
	pointer-events: auto;
}
.drawer-container {
	position: fixed;
	top: 0;
	left: 0;
	right: 0;
	bottom: 0;
	background: #fff;
	transform: translateY(100%);
	transition: transform 0.3s cubic-bezier(0.32, 0.72, 0, 1);
	display: flex;
	flex-direction: column;
}
.drawer-container.show {
	transform: translateY(0);
}
.drawer-header {
	display: flex;
	flex-direction: row;
	justify-content: space-between;
	align-items: center;
	padding: 80rpx 40rpx 20rpx;
	flex-shrink: 0;
}
.drawer-title {
	font-size: 32rpx;
	font-weight: 600;
	color: #1a1a1a;
}
.drawer-close { padding: 8rpx; }
.drawer-body {
	flex: 1;
	height: 0;
	overflow-y: auto;
}
.drawer-body-padded .form-section {
	margin-left: 32rpx;
	margin-right: 32rpx;
}
.drawer-footer {
	display: flex;
	flex-direction: row;
	padding: 24rpx 40rpx;
	padding-bottom: calc(24rpx + env(safe-area-inset-bottom));
	gap: 20rpx;
	border-top: 1px solid #f0f0f0;
	background: #fff;
	flex-shrink: 0;
}

/* ====== MCP 管理 ====== */
.mcp-icon {
	display: flex;
	flex-direction: column;
	align-items: center;
	gap: 4rpx;
}
.mcp-link {
	width: 24rpx;
	height: 8rpx;
	background: #b0b0b0;
	border-radius: 4rpx;
}
.mcp-loading { display: flex; justify-content: center; align-items: center; padding: 200rpx 40rpx; }
.mcp-loading-text { font-size: 28rpx; color: #bbb; }
.mcp-empty { display: flex; flex-direction: column; align-items: center; justify-content: center; padding: 240rpx 40rpx; }
.mcp-empty-icon { width: 120rpx; height: 120rpx; border-radius: 60rpx; background: #f5f5f5; margin-bottom: 32rpx; display: flex; justify-content: center; align-items: center; }
.mcp-empty-icon-inner { width: 48rpx; height: 16rpx; background: #ddd; border-radius: 8rpx; }
.mcp-empty-text { font-size: 30rpx; font-weight: 500; color: #999; margin-bottom: 12rpx; }
.mcp-empty-sub { font-size: 24rpx; color: #ccc; }
.mcp-list { display: flex; flex-direction: column; gap: 24rpx; margin: 24rpx 40rpx 0; box-sizing: border-box; }
.mcp-card { display: flex; flex-direction: row; background: #fff; border-radius: 20rpx; overflow: hidden; box-shadow: 0 2rpx 16rpx rgba(0,0,0,0.06); }
.mcp-card-accent { width: 8rpx; background: linear-gradient(180deg, #34d399, #6ee7b7); flex-shrink: 0; }
.mcp-card-body { flex: 1; min-width: 0; padding: 24rpx 20rpx; display: flex; flex-direction: column; }
.mcp-card-top { display: flex; flex-direction: row; align-items: center; justify-content: space-between; margin-bottom: 10rpx; }
.mcp-card-name { font-size: 28rpx; font-weight: 600; color: #1a1a1a; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.mcp-card-tag { background: rgba(52,211,153,0.1); border-radius: 8rpx; padding: 4rpx 12rpx; margin-left: 12rpx; flex-shrink: 0; }
.mcp-card-tag-text { font-size: 20rpx; font-weight: 600; color: #34d399; }
.mcp-card-right { display: flex; flex-direction: row; align-items: center; gap: 12rpx; }
.mcp-card.disabled { opacity: 0.5; }
.tool-card-row { display: flex; flex-direction: row; align-items: center; justify-content: space-between; }
.tool-card-info { flex: 1; min-width: 0; }
.tool-disabled { opacity: 0.5; }
.mcp-card-url { font-size: 22rpx; color: #999; margin-bottom: 16rpx; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.mcp-card-actions { display: flex; flex-direction: row; gap: 12rpx; justify-content: flex-end; flex-shrink: 0; }
.mcp-btn { padding: 10rpx 24rpx; border-radius: 16rpx; flex-shrink: 0; }
.mcp-btn-edit { background: #1a1a1a; }
.mcp-btn-del { background: transparent; border: 1rpx solid #e5e5e5; }
.mcp-btn-tools { background: rgba(52,211,153,0.1); }
.mcp-btn-text.tools { color: #34d399; }

/* ====== MCP 工具列表 ====== */
.tool-list { display: flex; flex-direction: column; gap: 16rpx; margin-top: 24rpx; }
.tool-card { background: #f8f8f8; border-radius: 16rpx; padding: 24rpx 20rpx; display: flex; flex-direction: column; gap: 8rpx; }
.tool-name { font-size: 28rpx; font-weight: 600; color: #1a1a1a; }
.tool-desc { font-size: 24rpx; color: #888; line-height: 36rpx; overflow: hidden; transition: max-height 0.25s ease; }
.tool-expand { font-size: 22rpx; color: #34d399; margin-top: 6rpx; display: inline-block; }
.tools-section-title { font-size: 26rpx; font-weight: 600; color: #333; margin-top: 30rpx; margin-bottom: 16rpx; }
.tools-item { margin-bottom: 20rpx; }
.tools-item-row { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8rpx; }
.tools-item-value { font-size: 28rpx; color: #007aff; font-weight: 600; }
.tools-item-desc { font-size: 20rpx; color: #999; margin-top: 4rpx; display: block; }
.icon-proactive { width: 32rpx; height: 32rpx; position: relative; display: flex; align-items: center; justify-content: center; }
.proactive-dot { width: 12rpx; height: 12rpx; background: #fff; border-radius: 50%; position: absolute; }
.proactive-ring { width: 24rpx; height: 24rpx; border: 3rpx solid rgba(255,255,255,0.5); border-radius: 50%; position: absolute; animation: pulse-ring 2s ease-out infinite; }
@keyframes pulse-ring { 0% { transform: scale(0.8); opacity: 0.5; } 50% { transform: scale(1.2); opacity: 0.2; } 100% { transform: scale(0.8); opacity: 0.5; } }
.bg-purple { background: linear-gradient(135deg, #a855f7, #7c3aed); }

/* ====== 工具选择器 ====== */
.form-label-row { display: flex; flex-direction: row; align-items: center; justify-content: space-between; }
.tool-insert-btn { background: rgba(52,211,153,0.1); border-radius: 12rpx; padding: 8rpx 20rpx; }
.tool-insert-btn-pressed { transform: scale(0.95); opacity: 0.7; }
.tool-insert-btn-text { font-size: 24rpx; font-weight: 500; color: #34d399; }
.tool-card-clickable { cursor: pointer; }
.tool-card-top { display: flex; flex-direction: row; align-items: center; justify-content: space-between; margin-bottom: 8rpx; }
.tool-type-tag { font-size: 20rpx; color: #34d399; background: rgba(52,211,153,0.1); padding: 2rpx 10rpx; border-radius: 6rpx; }
.mcp-btn-pressed { transform: scale(0.95); opacity: 0.7; }
.mcp-btn-text { font-size: 24rpx; font-weight: 500; color: #fff; }
.mcp-btn-text.del { color: #999; }

.mcp-form-textarea { width: 100%; height: 160rpx; background: #f8f8f8; border-radius: 16rpx; padding: 20rpx 24rpx; font-size: 26rpx; color: #1a1a1a; box-sizing: border-box; }
.mcp-type-display { background: #f8f8f8; border-radius: 16rpx; padding: 20rpx 24rpx; }
.mcp-type-value { font-size: 26rpx; color: #1a1a1a; }

.mcp-type-options { display: flex; flex-direction: row; gap: 16rpx; }
.mcp-type-option { flex: 1; background: #f8f8f8; border-radius: 16rpx; padding: 20rpx; display: flex; flex-direction: row; justify-content: space-between; align-items: center; border: 2rpx solid transparent; }
.mcp-type-option.active { background: rgba(52,211,153,0.1); border-color: #34d399; }
.mcp-type-name { font-size: 24rpx; font-weight: 500; color: #1a1a1a; }
.mcp-type-check { width: 28rpx; height: 28rpx; background: #34d399; border-radius: 14rpx; display: flex; justify-content: center; align-items: center; }
</style>
