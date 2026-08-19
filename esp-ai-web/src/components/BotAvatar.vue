<template>
  <div class="bot-avatar" :class="'state-' + state" :style="{ width: size + 'px', height: size + 'px' }">
    <!-- 柔和光圈 -->
    <div class="halo"></div>

    <!-- 机器人主体（SVG）或动漫人物（mode="anime" 加载图片，以后可换任意角色） -->
    <svg v-if="mode === 'robot'" class="bot-body" viewBox="0 0 200 200" fill="none">
      <!-- 天线 -->
      <line x1="100" y1="20" x2="100" y2="42" stroke="#9ca3af" stroke-width="3" stroke-linecap="round"/>
      <circle cx="100" cy="15" r="5" fill="#10b981" class="antenna-ball"/>
      <!-- 头 -->
      <ellipse cx="100" cy="95" rx="56" ry="50" fill="#ffffff" stroke="#d9e4de" stroke-width="2"/>
      <!-- 耳朵 -->
      <rect x="30" y="78" width="13" height="26" rx="6.5" fill="#f0f5f2" stroke="#d9e4de"/>
      <rect x="157" y="78" width="13" height="26" rx="6.5" fill="#f0f5f2" stroke="#d9e4de"/>
      <circle cx="36.5" cy="86" r="3" fill="#10b981"/>
      <circle cx="163.5" cy="86" r="3" fill="#10b981"/>
      <!-- 眼睛 -->
      <g class="eyes">
        <ellipse v-if="state === 'happy'" cx="80" cy="88" rx="9" ry="10" fill="#374151"/>
        <ellipse v-if="state === 'happy'" cx="120" cy="88" rx="9" ry="10" fill="#374151"/>
        <path v-if="state === 'happy'" d="M72 82 q8 -7 16 0 M112 82 q8 -7 16 0" stroke="#374151" stroke-width="4" stroke-linecap="round" fill="none"/>
        <!-- 待机：微笑眼（下弯弧线） -->
        <path v-if="state === 'idle'" d="M70 88 q10 9 20 0 M110 88 q10 9 20 0" stroke="#374151" stroke-width="4" stroke-linecap="round" fill="none"/>
        <!-- 应答：圆眼 -->
        <ellipse v-if="state === 'speaking'" cx="80" cy="90" rx="10" ry="11" fill="#374151"/>
        <ellipse v-if="state === 'speaking'" cx="120" cy="90" rx="10" ry="11" fill="#374151"/>
        <circle v-if="state === 'speaking'" cx="84" cy="86" r="3.5" fill="#10b981" class="eye-shine"/>
        <circle v-if="state === 'speaking'" cx="124" cy="86" r="3.5" fill="#10b981" class="eye-shine"/>
        <g v-if="state === 'listening'" class="wave-eye">
          <circle cx="80" cy="90" r="3" fill="#10b981"/>
          <circle cx="120" cy="90" r="3" fill="#10b981"/>
        </g>
      </g>
      <!-- 腮红 -->
      <ellipse cx="62" cy="112" rx="9" ry="5" fill="rgba(16,185,129,0.15)"/>
      <ellipse cx="138" cy="112" rx="9" ry="5" fill="rgba(16,185,129,0.15)"/>
      <!-- 嘴 -->
      <g class="mouth">
        <path v-if="state === 'speaking'" d="M88 124 h24" stroke="#374151" stroke-width="3.5" stroke-linecap="round" class="mouth-speak"/>
        <path v-else-if="state === 'happy'" d="M84 120 q16 14 32 0" stroke="#374151" stroke-width="3.5" stroke-linecap="round" fill="none"/>
        <path v-else d="M88 121 q12 9 24 0" stroke="#374151" stroke-width="3" stroke-linecap="round" fill="none"/>
      </g>
      <!-- 身体 -->
      <path d="M62 152 q0 -18 38 -18 q38 0 38 18 v22 q0 10 -38 10 q-38 0 -38 -10 Z" fill="#ffffff" stroke="#d9e4de" stroke-width="2"/>
      <circle cx="100" cy="168" r="5" fill="#10b981" class="chest-core"/>
    </svg>

    <div v-else class="anime-body">
      <img :src="animeSrc" alt="角色" />
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  size: { type: Number, default: 220 },
  state: { type: String, default: 'idle' },   // idle / listening / speaking / happy
  online: { type: Boolean, default: true },
  mode: { type: String, default: 'robot' },   // robot / anime
  animeSrc: { type: String, default: '' },
})

const stateText = computed(() => ({
  idle: '待机中', listening: '聆听中', speaking: '应答中', happy: '待命中',
}[props.state] || '待机中'))
</script>

<style scoped>
.bot-avatar { position: relative; display: flex; align-items: center; justify-content: center; }
.halo {
  position: absolute; inset: 2%;
  border-radius: 50%;
  background: radial-gradient(circle, rgba(16, 185, 129, 0.12) 0%, transparent 62%);
  animation: breath 3.2s ease-in-out infinite;
}
.state-listening .halo { animation-duration: 1.4s; }
.state-speaking .halo { animation-duration: 0.9s; }

.bot-body { width: 100%; height: 100%; animation: botFloat 4.5s ease-in-out infinite; }
@keyframes botFloat { 0%, 100% { transform: translateY(0); } 50% { transform: translateY(-6px); } }
.state-listening .bot-body { animation-duration: 2s; }
.state-speaking .bot-body { animation: botTalk 0.7s ease-in-out infinite; }
@keyframes botTalk { 0%, 100% { transform: translateY(0) scale(1); } 50% { transform: translateY(-2px) scale(1.01); } }

.antenna-ball { animation: blink 2.2s ease-in-out infinite; }
@keyframes blink { 0%, 88%, 100% { opacity: 1; } 92% { opacity: 0.2; } }
.eyes { animation: eyeBlink 4.2s ease-in-out infinite; transform-origin: 100px 90px; }
@keyframes eyeBlink { 0%, 92%, 100% { transform: scaleY(1); } 95% { transform: scaleY(0.08); } }
.eye-shine { animation: shine 2.6s ease-in-out infinite; }
@keyframes shine { 0%, 60%, 100% { opacity: 1; } 80% { opacity: 0.3; } }
.wave-eye circle { animation: wavePulse 0.8s ease-in-out infinite; }
.wave-eye circle:nth-child(2) { animation-delay: 0.4s; }
@keyframes wavePulse { 0%, 100% { r: 3; opacity: 1; } 50% { r: 6; opacity: 0.6; } }
.mouth-speak { animation: speakMouth 0.5s ease-in-out infinite; }
@keyframes speakMouth { 0%, 100% { transform: scaleX(1); } 50% { transform: scaleX(0.35); } }
.chest-core { animation: corePulse 1.8s ease-in-out infinite; }
@keyframes corePulse { 0%, 100% { r: 5; opacity: 1; } 50% { r: 7; opacity: 0.5; } }

.anime-body { width: 88%; height: 88%; border-radius: 50%; overflow: hidden; }
.anime-body img { width: 100%; height: 100%; object-fit: cover; }
</style>
