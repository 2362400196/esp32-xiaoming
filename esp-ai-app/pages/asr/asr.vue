<template>
	<view class="page">
		<view class="header">
			<view class="header-left" @click="goBack">
				<view class="back-icon">
					<view class="arrow-left"></view>
				</view>
			</view>
			<view class="header-center">
				<text class="title">ASR 语音识别</text>
			</view>
			<view class="header-right"></view>
		</view>

		<view class="content">
			<view class="section">
				<text class="section-title">引擎选择</text>
				<view class="engine-list">
					<view class="engine-item" :class="{ active: engine === 'whisper' }" @click="engine = 'whisper'">
						<view class="engine-icon whisper"></view>
						<text class="engine-name">Whisper</text>
						<text class="engine-desc">OpenAI 开源语音识别</text>
						<view class="engine-check" v-if="engine === 'whisper'">
							<view class="check-dot"></view>
						</view>
					</view>
					<view class="engine-item" :class="{ active: engine === 'baidu' }" @click="engine = 'baidu'">
						<view class="engine-icon baidu"></view>
						<text class="engine-name">百度语音</text>
						<text class="engine-desc">百度智能云 ASR</text>
						<view class="engine-check" v-if="engine === 'baidu'">
							<view class="check-dot"></view>
						</view>
					</view>
					<view class="engine-item" :class="{ active: engine === 'aliyun' }" @click="engine = 'aliyun'">
						<view class="engine-icon aliyun"></view>
						<text class="engine-name">阿里云</text>
						<text class="engine-desc">阿里云语音识别</text>
						<view class="engine-check" v-if="engine === 'aliyun'">
							<view class="check-dot"></view>
						</view>
					</view>
					<view class="engine-item" :class="{ active: engine === 'tencent' }" @click="engine = 'tencent'">
						<view class="engine-icon tencent"></view>
						<text class="engine-name">腾讯云</text>
						<text class="engine-desc">腾讯云语音识别</text>
						<view class="engine-check" v-if="engine === 'tencent'">
							<view class="check-dot"></view>
						</view>
					</view>
				</view>
			</view>

			<view class="section">
				<text class="section-title">API 配置</text>
				<view class="config-card">
					<view class="config-item">
						<text class="config-label">API Key</text>
						<input class="config-input" type="text" placeholder="请输入 API Key" v-model="apiKey" />
					</view>
					<view class="config-item" v-if="engine === 'baidu' || engine === 'aliyun' || engine === 'tencent'">
						<text class="config-label">Secret Key</text>
						<input class="config-input" type="text" placeholder="请输入 Secret Key" v-model="secretKey" />
					</view>
					<view class="config-item" v-if="engine === 'baidu'">
						<text class="config-label">App ID</text>
						<input class="config-input" type="text" placeholder="请输入 App ID" v-model="appId" />
					</view>
				</view>
			</view>

			<view class="section">
				<text class="section-title">模型选择</text>
				<view class="model-list">
					<view class="model-item" :class="{ active: model === 'whisper-1' }" @click="model = 'whisper-1'" v-if="engine === 'whisper'">
						<text class="model-name">whisper-1</text>
						<text class="model-desc">最新版本，推荐使用</text>
						<view class="model-check" v-if="model === 'whisper-1'"></view>
					</view>
					<view class="model-item" :class="{ active: model === 'deepspeech2' }" @click="model = 'deepspeech2'" v-if="engine === 'baidu'">
						<text class="model-name">DeepSpeech2</text>
						<text class="model-desc">百度深度学习模型</text>
						<view class="model-check" v-if="model === 'deepspeech2'"></view>
					</view>
					<view class="model-item" :class="{ active: model === 'paraformer' }" @click="model = 'paraformer'" v-if="engine === 'aliyun'">
						<text class="model-name">Paraformer</text>
						<text class="model-desc">阿里达摩院语音模型</text>
						<view class="model-check" v-if="model === 'paraformer'"></view>
					</view>
					<view class="model-item" :class="{ active: model === 'fastasr' }" @click="model = 'fastasr'" v-if="engine === 'tencent'">
						<text class="model-name">FastASR</text>
						<text class="model-desc">腾讯流式语音识别</text>
						<view class="model-check" v-if="model === 'fastasr'"></view>
					</view>
				</view>
			</view>

			<view class="actions">
				<view class="btn-save" @click="saveConfig">
					<text class="btn-text">保存配置</text>
				</view>
			</view>
		</view>
	</view>
</template>

<script setup>
	import { ref } from 'vue'
	
	const engine = ref('whisper')
	const apiKey = ref('')
	const secretKey = ref('')
	const appId = ref('')
	const model = ref('whisper-1')
	
	const goBack = () => {
		uni.navigateBack()
	}
	
	const saveConfig = () => {
		uni.showToast({
			title: '保存成功',
			icon: 'success'
		})
	}
</script>

<style>
	.page {
		background-color: #fafafa;
	}

	.header {
		display: flex;
		flex-direction: row;
		justify-content: space-between;
		align-items: center;
		padding: 80rpx 32rpx 24rpx;
		background-color: #fafafa;
	}

	.header-left {
		width: 48rpx;
		height: 48rpx;
		display: flex;
		justify-content: center;
		align-items: center;
	}

	.back-icon {
		width: 32rpx;
		height: 32rpx;
		display: flex;
		justify-content: center;
		align-items: center;
	}

	.arrow-left {
		width: 12rpx;
		height: 12rpx;
		border-left: 3rpx solid #1a1a1a;
		border-bottom: 3rpx solid #1a1a1a;
		transform: rotate(45deg);
	}

	.header-center {
		flex: 1;
		display: flex;
		justify-content: center;
		align-items: center;
	}

	.title {
		font-size: 32rpx;
		font-weight: 600;
		color: #1a1a1a;
	}

	.header-right {
		width: 48rpx;
	}

	.content {
		padding: 0 32rpx 160rpx;
	}

	.section {
		margin-bottom: 48rpx;
	}

	.section-title {
		font-size: 24rpx;
		font-weight: 600;
		color: #1a1a1a;
		margin-bottom: 20rpx;
		display: block;
	}

	.engine-list {
		display: flex;
		flex-direction: column;
		gap: 16rpx;
	}

	.engine-item {
		background-color: rgba(255, 255, 255, 0.9);
		border-radius: 20rpx;
		padding: 24rpx;
		display: flex;
		flex-direction: row;
		align-items: center;
		position: relative;
	}

	.engine-item .engine-name {
		margin-left: 16rpx;
	}

	.engine-item.active {
		border: 2rpx solid #34d399;
	}

	.engine-icon {
		width: 48rpx;
		height: 48rpx;
		border-radius: 12rpx;
		display: flex;
		justify-content: center;
		align-items: center;
	}

	.engine-icon.whisper {
		background-color: rgba(52, 211, 153, 0.1);
	}

	.engine-icon.baidu {
		background-color: rgba(59, 130, 246, 0.1);
	}

	.engine-icon.aliyun {
		background-color: rgba(249, 115, 22, 0.1);
	}

	.engine-icon.tencent {
		background-color: rgba(34, 197, 94, 0.1);
	}

	.engine-name {
		font-size: 26rpx;
		font-weight: 600;
		color: #1a1a1a;
	}

	.engine-desc {
		font-size: 20rpx;
		color: #b0b0b0;
		margin-left: auto;
	}

	.engine-check {
		width: 24rpx;
		height: 24rpx;
		background-color: #34d399;
		border-radius: 12rpx;
		display: flex;
		justify-content: center;
		align-items: center;
	}

	.check-dot {
		width: 8rpx;
		height: 8rpx;
		background-color: #ffffff;
		border-radius: 8rpx;
	}

	.config-card {
		background-color: rgba(255, 255, 255, 0.9);
		border-radius: 20rpx;
		padding: 8rpx 24rpx;
	}

	.config-item {
		padding: 20rpx 0;
		border-bottom: 1px solid #f0f0f0;
	}

	.config-item:last-child {
		border-bottom: none;
	}

	.config-label {
		font-size: 22rpx;
		color: #b0b0b0;
		margin-bottom: 12rpx;
		display: block;
	}

	.config-input {
		font-size: 26rpx;
		color: #1a1a1a;
		background-color: transparent;
		border: none;
		padding: 0;
		height: 40rpx;
	}

	.model-list {
		display: flex;
		flex-direction: column;
		gap: 12rpx;
	}

	.model-item {
		background-color: rgba(255, 255, 255, 0.9);
		border-radius: 16rpx;
		padding: 20rpx 24rpx;
		display: flex;
		flex-direction: row;
		align-items: center;
		position: relative;
	}

	.model-item.active {
		border: 2rpx solid #34d399;
	}

	.model-name {
		font-size: 24rpx;
		font-weight: 600;
		color: #1a1a1a;
	}

	.model-desc {
		font-size: 20rpx;
		color: #b0b0b0;
		margin-left: 16rpx;
	}

	.model-check {
		position: absolute;
		right: 24rpx;
		width: 20rpx;
		height: 20rpx;
		background-color: #34d399;
		border-radius: 10rpx;
	}

	.actions {
		position: fixed;
		bottom: 40rpx;
		left: 32rpx;
		right: 32rpx;
	}

	.btn-save {
		background-color: #34d399;
		border-radius: 20rpx;
		padding: 28rpx;
		display: flex;
		justify-content: center;
		align-items: center;
	}

	.btn-text {
		font-size: 28rpx;
		font-weight: 600;
		color: #ffffff;
	}
</style>
