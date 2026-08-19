<template>
  <div class="settings-mask" @click.self="$emit('close')">
    <div class="settings-panel">
      <div class="settings-head">
        <div class="head-titles">
          <h3 class="settings-title">设备设置</h3>
          <span class="settings-device">{{ device?.name || '设备' }}</span>
        </div>
        <button class="settings-close" @click="$emit('close')" aria-label="关闭">✕</button>
      </div>

      <!-- 选项卡 -->
      <div class="tabs-bar">
        <button v-for="t in tabs" :key="t.id" class="tab-item"
          :class="{ active: activeTab === t.id }" @click="activeTab = t.id">
          {{ t.label }}
        </button>
      </div>

      <div v-if="loading" class="settings-loading">加载中…</div>

      <div v-else class="settings-body">
        <transition name="tab-slide" mode="out-in">
        <!-- ============ ASR ============ -->
        <section v-if="activeTab === 'asr'" key="asr" class="tab-pane">
          <div class="block">
            <p class="block-label">引擎</p>
            <div class="engine-row">
              <button v-for="e in asrEngines" :key="e.id" class="engine-chip"
                :class="{ active: asrEngine === e.id }" @click="asrEngine = e.id">{{ e.name }}</button>
            </div>
          </div>
          <div class="block" v-if="asrEngine === 'bytedance'">
            <p class="block-label">API Key</p>
            <div class="input-wrap">
              <input class="input input-inner" :type="showKey.bytedance ? 'text' : 'password'"
                placeholder="请输入字节跳动 API Key" v-model="form.asr_api_key" />
              <button class="eye-btn" @click="showKey.bytedance = !showKey.bytedance">
                <span class="eye-icon" :class="{ off: !showKey.bytedance }">👁</span>
              </button>
            </div>
          </div>
          <div class="block" v-if="asrEngine === 'bytedance'">
            <div class="collapse-head" @click="asrPoolOpen = !asrPoolOpen">
              <span class="collapse-title">超时与连接池</span>
              <span class="collapse-arrow" :class="{ open: asrPoolOpen }">▾</span>
            </div>
            <div v-if="asrPoolOpen" class="collapse-body">
              <div class="block">
                <p class="block-label">无人说话超时（秒）</p>
                <input class="input" type="number" min="1" max="120" placeholder="5（留空用全局默认）" v-model.number="form.asr_no_speech_timeout" />
                <p class="form-tip">ASR 启动后无识别结果时退出，留空则用服务器全局配置</p>
              </div>
              <div class="block">
                <p class="block-label">说话后静默超时（秒）</p>
                <input class="input" type="number" min="1" max="30" placeholder="2（留空用全局默认）" v-model.number="form.asr_silence_timeout" />
                <p class="form-tip">用户说完话后静默多久进入 LLM，留空则用服务器全局配置</p>
              </div>
              <div class="block">
                <p class="block-label">最大并发数</p>
                <input class="input" type="number" min="1" max="500" placeholder="100（留空用全局默认）" v-model.number="form.asr_max_concurrency" />
                <p class="form-tip">ASR 同时处理的最大会话数，留空则用服务器全局配置</p>
              </div>
              <div class="block">
                <div class="toggle-row">
                  <div class="toggle-label">
                    <p class="toggle-title">启用连接池</p>
                    <p class="toggle-sub">复用 ASR WebSocket 连接，降低首字延迟</p>
                  </div>
                  <button class="ios-toggle" :class="{ on: form.asr_enable_pool }" @click="form.asr_enable_pool = !form.asr_enable_pool">
                    <span class="knob"></span>
                  </button>
                </div>
              </div>
              <div class="block">
                <p class="block-label">池最大连接数</p>
                <input class="input" type="number" min="1" max="500" placeholder="100（留空用全局默认）" v-model.number="form.asr_pool_max_size" />
              </div>
              <div class="block">
                <p class="block-label">池最小连接数</p>
                <input class="input" type="number" min="0" max="100" placeholder="2（留空用全局默认）" v-model.number="form.asr_pool_min_size" />
              </div>
              <div class="block">
                <p class="block-label">心跳间隔（秒）</p>
                <input class="input" type="number" min="5" max="300" placeholder="30（留空用全局默认）" v-model.number="form.asr_pool_heartbeat_interval" />
              </div>
              <div class="block">
                <p class="block-label">空闲超时（秒）</p>
                <input class="input" type="number" min="10" max="3600" placeholder="300（留空用全局默认）" v-model.number="form.asr_pool_idle_timeout" />
              </div>
              <div class="block">
                <p class="block-label">连接超时（秒）</p>
                <input class="input" type="number" min="1" max="60" placeholder="15（留空用全局默认）" v-model.number="form.asr_pool_connection_timeout" />
              </div>
              <p class="form-tip">连接池为全局共享，首个连接的设备参数优先生效，留空则用服务器全局配置</p>
            </div>
          </div>
          <template v-if="asrEngine === 'tencent'">
            <div class="block">
              <p class="block-label">App ID</p>
              <input class="input" type="text" placeholder="请输入腾讯云 App ID" v-model="form.tencent_app_id" />
            </div>
            <div class="block">
              <p class="block-label">Secret ID</p>
              <input class="input" type="text" placeholder="请输入腾讯云 Secret ID" v-model="form.tencent_secret_id" />
            </div>
            <div class="block">
              <p class="block-label">Secret Key</p>
              <div class="input-wrap">
                <input class="input input-inner" :type="showKey.tencent ? 'text' : 'password'"
                  placeholder="请输入腾讯云 Secret Key" v-model="form.tencent_secret_key" />
                <button class="eye-btn" @click="showKey.tencent = !showKey.tencent">
                  <span class="eye-icon" :class="{ off: !showKey.tencent }">👁</span>
                </button>
              </div>
            </div>
          </template>
        </section>

        <!-- ============ LLM ============ -->
        <section v-else-if="activeTab === 'llm'" key="llm" class="tab-pane">
          <div class="block">
            <p class="block-label">引擎</p>
            <div class="engine-row"><button class="engine-chip active">DeepSeek</button></div>
          </div>
          <div class="block">
            <p class="block-label">API Key</p>
            <div class="input-wrap">
              <input class="input input-inner" :type="showKey.deepseek ? 'text' : 'password'"
                placeholder="请输入 DeepSeek API Key" v-model="form.llm_api_key" />
              <button class="eye-btn" @click="showKey.deepseek = !showKey.deepseek">
                <span class="eye-icon" :class="{ off: !showKey.deepseek }">👁</span>
              </button>
            </div>
          </div>
          <div class="block">
            <p class="block-label">模型</p>
            <div class="model-list">
              <button v-for="m in llmModels" :key="m.type" class="model-card"
                :class="{ active: form.llm_model === m.type }" @click="form.llm_model = m.type">
                <span class="model-name">{{ m.name }}</span>
                <span class="model-desc">{{ m.desc }}</span>
              </button>
            </div>
          </div>
          <div class="block">
            <div class="toggle-row">
              <div class="toggle-label">
                <p class="toggle-title">自定义提示词</p>
                <p class="toggle-sub">关闭则使用服务器默认人设</p>
              </div>
              <button class="ios-toggle" :class="{ on: customPrompt }" @click="customPrompt = !customPrompt">
                <span class="knob"></span>
              </button>
            </div>
            <div v-if="customPrompt" class="toggle-body">
              <textarea class="input settings-textarea" placeholder="请输入系统提示词" v-model="form.llm_system_prompt" maxlength="500"></textarea>
              <p class="char-count">{{ (form.llm_system_prompt || '').length }} / 500</p>
            </div>
          </div>
          <div class="block">
            <div class="toggle-row">
              <div class="toggle-label">
                <p class="toggle-title">对话记忆</p>
                <p class="toggle-sub">开启后 AI 能记住上下文</p>
              </div>
              <button class="ios-toggle" :class="{ on: memoryOn }" @click="memoryOn = !memoryOn">
                <span class="knob"></span>
              </button>
            </div>
            <div v-if="memoryOn" class="toggle-body">
              <p class="block-label">最大记忆轮数</p>
              <input class="input" type="number" min="1" max="50" placeholder="20" v-model.number="form.llm_memory_max" />
            </div>
          </div>
        </section>

        <!-- ============ TTS ============ -->
        <section v-else-if="activeTab === 'tts'" key="tts" class="tab-pane">
          <div class="block">
            <p class="block-label">引擎</p>
            <div class="engine-row"><button class="engine-chip active">字节跳动</button></div>
          </div>
          <div class="block">
            <p class="block-label">API Key</p>
            <div class="input-wrap">
              <input class="input input-inner" :type="showKey.tts ? 'text' : 'password'"
                placeholder="请输入字节跳动 API Key" v-model="form.tts_api_key" />
              <button class="eye-btn" @click="showKey.tts = !showKey.tts">
                <span class="eye-icon" :class="{ off: !showKey.tts }">👁</span>
              </button>
            </div>
          </div>
          <div class="block">
            <p class="block-label">模型</p>
            <div class="model-list">
              <button v-for="m in ttsModels" :key="m.type" class="model-card"
                :class="{ active: ttsModel === m.type }" @click="selectTtsModel(m.type)">
                <span class="model-name">{{ m.name }}</span>
                <span class="model-desc">{{ m.desc }}</span>
              </button>
            </div>
          </div>
          <div class="block">
            <p class="block-label">音色</p>
            <template v-if="ttsModel === 'seed-icl-2.0'">
              <AppSelect v-model="form.voice_type" :options="cloneVoices" placeholder="选择复刻音色" allow-custom />
              <p class="form-tip">声音复刻：从列表选择或自定义音色 ID</p>
            </template>
            <template v-else>
              <AppSelect v-model="form.voice_type" :options="voiceOptions" placeholder="选择音色" allow-custom />
            </template>
          </div>
          <div class="block">
            <p class="block-label">语速 <span class="value-tag">{{ (form.tts_speed_ratio ?? 1.0).toFixed(2) }}</span></p>
            <input class="input" type="range" min="0.5" max="2.0" step="0.05" v-model.number="form.tts_speed_ratio" />
            <p class="form-tip">0.5 慢速 ~ 2.0 快速，默认 1.0</p>
          </div>
          <div class="block">
            <p class="block-label">音量 <span class="value-tag">{{ (form.tts_volume_ratio ?? 1.0).toFixed(2) }}</span></p>
            <input class="input" type="range" min="0.5" max="2.0" step="0.05" v-model.number="form.tts_volume_ratio" />
            <p class="form-tip">0.5 轻声 ~ 2.0 大声，默认 1.0</p>
          </div>
          <div class="block">
            <p class="block-label">音调 <span class="value-tag">{{ (form.tts_pitch_ratio ?? 1.0).toFixed(2) }}</span></p>
            <input class="input" type="range" min="0.5" max="2.0" step="0.05" v-model.number="form.tts_pitch_ratio" />
            <p class="form-tip">0.5 低沉 ~ 2.0 高亢，默认 1.0</p>
          </div>
          <div class="block">
            <div class="collapse-head" @click="ttsPoolOpen = !ttsPoolOpen">
              <span class="collapse-title">TTS 连接池</span>
              <span class="collapse-arrow" :class="{ open: ttsPoolOpen }">▾</span>
            </div>
            <div v-if="ttsPoolOpen" class="collapse-body">
              <div class="block">
                <div class="toggle-row">
                  <div class="toggle-label">
                    <p class="toggle-title">启用连接池</p>
                    <p class="toggle-sub">复用 TTS WebSocket 连接，降低首字延迟</p>
                  </div>
                  <button class="ios-toggle" :class="{ on: form.tts_enable_pool }" @click="form.tts_enable_pool = !form.tts_enable_pool">
                    <span class="knob"></span>
                  </button>
                </div>
              </div>
              <div class="block">
                <p class="block-label">池最大连接数</p>
                <input class="input" type="number" min="1" max="500" placeholder="100（留空用全局默认）" v-model.number="form.tts_pool_max_size" />
              </div>
              <div class="block">
                <p class="block-label">池最小连接数</p>
                <input class="input" type="number" min="0" max="100" placeholder="2（留空用全局默认）" v-model.number="form.tts_pool_min_size" />
              </div>
              <div class="block">
                <p class="block-label">心跳间隔（秒）</p>
                <input class="input" type="number" min="5" max="300" placeholder="30（留空用全局默认）" v-model.number="form.tts_pool_heartbeat_interval" />
              </div>
              <div class="block">
                <p class="block-label">空闲超时（秒）</p>
                <input class="input" type="number" min="10" max="3600" placeholder="300（留空用全局默认）" v-model.number="form.tts_pool_idle_timeout" />
              </div>
              <div class="block">
                <p class="block-label">连接超时（秒）</p>
                <input class="input" type="number" min="1" max="60" placeholder="15（留空用全局默认）" v-model.number="form.tts_pool_connection_timeout" />
              </div>
              <p class="form-tip">连接池为全局共享，首个连接的设备参数优先生效，留空则用服务器全局配置</p>
            </div>
          </div>
          <div class="block">
            <div class="collapse-head" @click="volcOpen = !volcOpen">
              <span class="collapse-title">火山 OpenAPI 密钥</span>
              <span class="collapse-arrow" :class="{ open: volcOpen }">▾</span>
            </div>
            <div v-if="volcOpen" class="collapse-body">
              <div class="block">
                <p class="block-label">AccessKeyId</p>
                <div class="input-wrap">
                  <input class="input input-inner" :type="showKey.volcAk ? 'text' : 'password'"
                    placeholder="以 AKLT 开头" v-model="form.volc_ak" />
                  <button class="eye-btn" @click="showKey.volcAk = !showKey.volcAk">
                    <span class="eye-icon" :class="{ off: !showKey.volcAk }">👁</span>
                  </button>
                </div>
              </div>
              <div class="block">
                <p class="block-label">SecretAccessKey</p>
                <div class="input-wrap">
                  <input class="input input-inner" :type="showKey.volcSk ? 'text' : 'password'"
                    placeholder="SecretAccessKey" v-model="form.volc_sk" />
                  <button class="eye-btn" @click="showKey.volcSk = !showKey.volcSk">
                    <span class="eye-icon" :class="{ off: !showKey.volcSk }">👁</span>
                  </button>
                </div>
              </div>
              <div class="block">
                <p class="block-label">项目名</p>
                <input class="input" type="text" placeholder="默认 default" v-model="form.volc_project" />
              </div>
              <p class="form-tip">留空则使用服务器 .env 的环境变量配置</p>
            </div>
          </div>
        </section>

        <!-- ============ Wakeup ============ -->
        <section v-else-if="activeTab === 'wakeup'" key="wakeup" class="tab-pane">
          <div class="block">
            <p class="block-label">唤醒回复文本</p>
            <input class="input" type="text" placeholder="我在呢" v-model="form.wakeup_text" maxlength="20" />
            <p class="form-tip">设备唤醒后播报的文本，留空则用服务器全局配置</p>
          </div>
          <div class="block">
            <div class="toggle-row">
              <div class="toggle-label">
                <p class="toggle-title">启用唤醒音频</p>
                <p class="toggle-sub">唤醒后播放提示音</p>
              </div>
              <button class="ios-toggle" :class="{ on: form.wakeup_enable_audio }" @click="form.wakeup_enable_audio = !form.wakeup_enable_audio">
                <span class="knob"></span>
              </button>
            </div>
          </div>
          <div class="block">
            <div class="toggle-row">
              <div class="toggle-label">
                <p class="toggle-title">缓存唤醒音频</p>
                <p class="toggle-sub">预生成音频避免首次延迟</p>
              </div>
              <button class="ios-toggle" :class="{ on: form.wakeup_cache_enabled }" @click="form.wakeup_cache_enabled = !form.wakeup_cache_enabled">
                <span class="knob"></span>
              </button>
            </div>
          </div>
          <div class="block">
            <div class="toggle-row">
              <div class="toggle-label">
                <p class="toggle-title">播放唤醒音频</p>
                <p class="toggle-sub">关闭后唤醒不发声</p>
              </div>
              <button class="ios-toggle" :class="{ on: form.wakeup_play_enabled }" @click="form.wakeup_play_enabled = !form.wakeup_play_enabled">
                <span class="knob"></span>
              </button>
            </div>
          </div>
          <div class="block">
            <p class="block-label">音频来源</p>
            <div class="engine-row">
              <button class="engine-chip" :class="{ active: form.wakeup_audio_source === 'file' }" @click="form.wakeup_audio_source = 'file'">本地文件</button>
              <button class="engine-chip" :class="{ active: form.wakeup_audio_source === 'tts' }" @click="form.wakeup_audio_source = 'tts'">TTS 合成</button>
            </div>
            <p class="form-tip">本地文件优先播放 dou.mp3，TTS 合成则使用唤醒文本实时生成</p>
          </div>
          <div class="block">
            <div class="toggle-row">
              <div class="toggle-label">
                <p class="toggle-title">下一轮播放</p>
                <p class="toggle-sub">唤醒音频推迟到下一轮对话播放</p>
              </div>
              <button class="ios-toggle" :class="{ on: form.wakeup_play_on_next_round }" @click="form.wakeup_play_on_next_round = !form.wakeup_play_on_next_round">
                <span class="knob"></span>
              </button>
            </div>
          </div>
        </section>

        <!-- ============ 插件 ============ -->
        <section v-else-if="activeTab === 'plugins'" key="plugins" class="tab-pane">
          <div class="plugins-head">
            <p class="plugins-hint">管理当前设备启用的插件，可从市场安装后再在此启用</p>
            <button class="btn-ghost btn-sm" :disabled="checkingUpdates" @click="checkUpdates">
              {{ checkingUpdates ? '检查中…' : '检查更新' }}
            </button>
          </div>
          <div v-if="pluginLoading" class="plugins-loading">加载中…</div>
          <div v-else-if="!installedPlugins.length" class="plugins-empty">当前设备还没有插件</div>
          <div v-else class="plugin-list">
            <div v-for="p in installedPlugins" :key="p.name" class="plugin-item"
              :class="{ enabled: p.enabled, 'has-update': hasUpdate(p.name) }">
              <div class="plugin-main">
                <span class="plugin-icon" :class="{ active: p.enabled }">{{ (p.title || p.name).charAt(0).toUpperCase() }}</span>
                <div class="plugin-info">
                  <p class="plugin-name">{{ p.title || p.name }}</p>
                  <div class="plugin-meta">
                    <span v-if="p.source === 'built-in'" class="meta-tag">内置</span>
                    <span v-else-if="p.version" class="meta-tag">v{{ p.version }}</span>
                    <span v-if="hasUpdate(p.name)" class="meta-tag update">新版本</span>
                  </div>
                </div>
              </div>
              <div class="plugin-actions">
                <button v-if="hasUpdate(p.name)" class="action-btn update"
                  :disabled="updating === p.name" @click="updatePlugin(p)">
                  {{ updating === p.name ? '…' : '更新' }}
                </button>
                <button v-if="p.config_fields && p.config_fields.length" class="action-btn"
                  @click="openConfig(p)">配置</button>
                <button class="action-btn toggle" :class="{ on: p.enabled }"
                  :disabled="p.saving" @click="togglePlugin(p)">
                  {{ p.saving ? '…' : (p.enabled ? '禁用' : '启用') }}
                </button>
                <button v-if="p.source !== 'built-in'" class="action-btn danger"
                  :disabled="uninstalling === p.name" @click="uninstallPlugin(p)">
                  {{ uninstalling === p.name ? '…' : '卸载' }}
                </button>
              </div>
            </div>
          </div>
        </section>
        </transition>
      </div>

      <div class="settings-foot">
        <button class="btn-ghost" @click="$emit('close')">取消</button>
        <button class="btn-mint" :disabled="loading || saving" @click="save">
          {{ saving ? '保存中…' : '保存配置' }}
        </button>
      </div>
    </div>

    <!-- 插件配置弹窗 -->
    <transition name="pop">
      <div v-if="configPlugin" class="config-mask" @click.self="configPlugin = null">
        <div class="config-panel glass">
          <h3 class="config-title">配置「{{ configPlugin.title }}」</h3>
          <p class="config-note">配置仅保存在当前设备，不影响其他设备</p>
          <div v-for="f in configFields" :key="f.key" class="config-field">
            <label class="config-label">{{ f.label }}<span v-if="f.required" class="req"> *</span></label>
            <input class="input" v-model="configValues[f.key]" :placeholder="f.placeholder || '请输入'" />
          </div>
          <div class="config-actions">
            <button class="btn-ghost" @click="configPlugin = null">取消</button>
            <button class="btn-mint" :disabled="configSaving" @click="saveConfig">
              {{ configSaving ? '保存中…' : '保存配置' }}
            </button>
          </div>
        </div>
      </div>
    </transition>
  </div>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import AppSelect from './AppSelect.vue'
import { api } from '../api'
import { ttsVoices1, ttsVoices2 } from '../data/ttsVoices'

const props = defineProps({ device: Object })
const emit = defineEmits(['close', 'toast', 'plugins-changed'])

const loading = ref(false)
const saving = ref(false)
const volcOpen = ref(false)
const asrPoolOpen = ref(false)
const ttsPoolOpen = ref(false)
const customPrompt = ref(false)
const memoryOn = ref(false)
const activeTab = ref('asr')
const showKey = ref({ bytedance: false, tencent: false, deepseek: false, tts: false, volcAk: false, volcSk: false })
const asrEngine = ref('bytedance')
const ttsModel = ref('seed-tts-2.0')
const cloneVoices = ref([])
const form = ref({})

// ===== 插件管理 =====
const pluginLoading = ref(false)
const installedPlugins = ref([])
const updatesMap = ref({})
const checkingUpdates = ref(false)
const updating = ref(null)
const uninstalling = ref(null)
const configPlugin = ref(null)
const configFields = ref([])
const configValues = ref({})
const configSaving = ref(false)

const tabs = [
  { id: 'asr', label: '语音识别' },
  { id: 'llm', label: '大模型' },
  { id: 'tts', label: '语音合成' },
  { id: 'wakeup', label: '唤醒' },
  { id: 'plugins', label: '插件' },
]
const asrEngines = [
  { id: 'bytedance', name: '字节跳动' },
  { id: 'tencent', name: '腾讯云' },
]
const llmModels = [
  { name: 'deepseek-v4-flash', type: 'deepseek-v4-flash', desc: '快速响应' },
  { name: 'deepseek-v4-pro', type: 'deepseek-v4-pro', desc: '深度推理' },
]
const ttsModels = [
  { name: 'Seed TTS 1.0', type: 'seed-tts-1.0', desc: '基础模型，支持标准音色' },
  { name: 'Seed TTS 2.0', type: 'seed-tts-2.0', desc: '高级模型，支持更多音色' },
  { name: '声音复刻', type: 'seed-icl-2.0', desc: '复刻音色，自定义音色 ID' },
]

const voiceOptions = computed(() => {
  const list = ttsModel.value === 'seed-tts-2.0' ? ttsVoices2 : ttsVoices1
  return list.map(v => ({ label: v.name, value: v.type, tag: v.tag }))
})

watch(() => props.device, () => { if (props.device) load() }, { immediate: true })

async function load() {
  if (!props.device?.mac) return
  loading.value = true
  const res = await api.getConfig(props.device.mac)
  if (res.status === 200 && res.data?.code === 0) {
    const cfg = res.data.data || {}
    const asrCfg = cfg.asr_config || {}
    const volcAsr = asrCfg.volcengine || {}
    const tencentCfg = asrCfg.tencent || {}
    const vo = cfg.tts_config?.volc_openapi || {}
    form.value = {
      asr_api_key: volcAsr.api_key || asrCfg.api_key || '',
      asr_no_speech_timeout: volcAsr.no_speech_timeout ?? null,
      asr_silence_timeout: volcAsr.silence_timeout ?? null,
      asr_max_concurrency: volcAsr.max_concurrency ?? null,
      asr_enable_pool: volcAsr.enable_pool ?? true,
      asr_pool_max_size: volcAsr.pool_max_size ?? null,
      asr_pool_min_size: volcAsr.pool_min_size ?? null,
      asr_pool_heartbeat_interval: volcAsr.pool_heartbeat_interval ?? null,
      asr_pool_idle_timeout: volcAsr.pool_idle_timeout ?? null,
      asr_pool_connection_timeout: volcAsr.pool_connection_timeout ?? null,
      tencent_app_id: tencentCfg.app_id || asrCfg.app_id || '',
      tencent_secret_id: tencentCfg.secret_id || asrCfg.secret_id || '',
      tencent_secret_key: tencentCfg.secret_key || asrCfg.secret_key || '',
      llm_api_key: cfg.llm?.api_key || '',
      llm_model: cfg.llm?.model || 'deepseek-v4-flash',
      llm_system_prompt: cfg.llm?.system_prompt || '',
      llm_memory_max: cfg.llm?.memory_max_messages || 20,
      tts_api_key: cfg.tts_config?.api_key || '',
      volc_ak: vo.access_key_id || '',
      volc_sk: vo.secret_access_key || '',
      volc_project: vo.project_name || 'default',
      voice_type: cfg.tts_config?.voice_type || '',
      tts_speed_ratio: cfg.tts_config?.speed_ratio ?? 1.0,
      tts_volume_ratio: cfg.tts_config?.volume_ratio ?? 1.0,
      tts_pitch_ratio: cfg.tts_config?.pitch_ratio ?? 1.0,
      tts_enable_pool: cfg.tts_config?.enable_pool ?? true,
      tts_pool_max_size: cfg.tts_config?.pool_max_size ?? null,
      tts_pool_min_size: cfg.tts_config?.pool_min_size ?? null,
      tts_pool_heartbeat_interval: cfg.tts_config?.pool_heartbeat_interval ?? null,
      tts_pool_idle_timeout: cfg.tts_config?.pool_idle_timeout ?? null,
      tts_pool_connection_timeout: cfg.tts_config?.pool_connection_timeout ?? null,
      wakeup_text: cfg.wakeup?.text ?? '我在呢',
      wakeup_enable_audio: cfg.wakeup?.enable_audio ?? true,
      wakeup_cache_enabled: cfg.wakeup?.cache_enabled ?? true,
      wakeup_play_enabled: cfg.wakeup?.play_enabled ?? true,
      wakeup_audio_source: cfg.wakeup?.source ?? 'file',
      wakeup_play_on_next_round: cfg.wakeup?.play_on_next_round ?? false,
    }
    asrEngine.value = cfg.asr_provider === 'tencent' ? 'tencent' : 'bytedance'
    ttsModel.value = cfg.tts_config?.resource_id || 'seed-tts-2.0'
    customPrompt.value = !!form.value.llm_system_prompt
    memoryOn.value = cfg.llm?.memory_enabled === true || cfg.llm?.memory_enabled === undefined
    loadCloneVoices()
  }
  loading.value = false
}

async function loadCloneVoices() {
  if (!props.device?.mac) return
  const res = await api.cloneVoices(props.device.mac)
  if (res.status === 200 && res.data?.code === 0) {
    const voices = res.data.data?.voices || []
    cloneVoices.value = voices
      .filter(v => /^(s_|icl_|saturn_|dit_)/i.test(v.speaker_id || v.speaker || ''))
      .map(v => ({ label: v.speaker_name || v.speaker_id, value: v.speaker_id || v.speaker, tag: '复刻' }))
  }
}

function selectTtsModel(type) {
  ttsModel.value = type
  if (type === 'seed-icl-2.0') loadCloneVoices()
}

// ===== 插件管理 =====
const deviceId = computed(() => props.device?.device_id || props.device?.id || props.device?.mac || '')

async function loadPlugins() {
  if (!deviceId.value) return
  pluginLoading.value = true
  const res = await api.plugins(deviceId.value)
  if (res.status === 200 && res.data?.code === 0) {
    const d = res.data.data
    const rawEnabled = d.enabled_plugins
    const allEnabled = !rawEnabled || rawEnabled.length === 0
    const enabled = new Set(rawEnabled || [])
    const configs = d.plugin_configs || {}
    installedPlugins.value = (d.available_plugins || []).map(p => ({
      ...p,
      config: configs[p.name] || {},
      configDone: Object.keys(configs[p.name] || {}).length > 0,
      enabled: allEnabled || p.source === 'built-in' || enabled.has(p.name),
      saving: false,
    }))
  }
  pluginLoading.value = false
}

function hasUpdate(name) {
  return !!updatesMap.value[name]
}

async function checkUpdates() {
  checkingUpdates.value = true
  const res = await api.checkPluginUpdates()
  checkingUpdates.value = false
  if (res.status === 200 && res.data?.code === 0) {
    const list = res.data.data || []
    const map = {}
    for (const u of list) {
      if (u.has_update) map[u.name] = u
    }
    updatesMap.value = map
    const count = Object.keys(map).length
    emit('toast', count ? `${count} 个插件有新版本` : '所有插件已是最新')
  } else {
    emit('toast', res.data?.message || '检查更新失败')
  }
}

async function updatePlugin(p) {
  updating.value = p.name
  emit('toast', `正在更新「${p.title || p.name}」…`)
  const res = await api.updatePlugin(p.name)
  updating.value = null
  if (res.status === 200 && res.data?.code === 0) {
    emit('toast', '更新成功')
    delete updatesMap.value[p.name]
    await loadPlugins()
  } else {
    emit('toast', res.data?.message || '更新失败')
  }
}

async function uninstallPlugin(p) {
  if (!window.confirm(`确定卸载「${p.title || p.name}」？卸载后所有设备将无法使用此插件。`)) return
  uninstalling.value = p.name
  const res = await api.uninstallPlugin(p.name)
  uninstalling.value = null
  if (res.status === 200 && res.data?.code === 0) {
    emit('toast', '插件已卸载')
    await loadPlugins()
    emit('plugins-changed')
  } else {
    emit('toast', res.data?.message || '卸载失败')
  }
}

async function togglePlugin(p) {
  p.saving = true
  const target = !p.enabled
  const list = installedPlugins.value.filter(x => x.name === p.name ? target : x.enabled).map(x => x.name)
  const res = await api.installPlugin(deviceId.value, list)
  p.saving = false
  if (res.status === 200 && res.data?.code === 0) {
    p.enabled = target
    emit('toast', target ? '已启用' : '已禁用')
    emit('plugins-changed')
  } else {
    emit('toast', res.data?.message || '操作失败')
  }
}

function openConfig(p) {
  configPlugin.value = p
  configFields.value = p.config_fields || []
  configValues.value = {}
  for (const f of configFields.value) configValues.value[f.key] = (p.config && p.config[f.key]) || ''
}

async function saveConfig() {
  if (!configPlugin.value) return
  configSaving.value = true
  const config = {}
  for (const f of configFields.value) if (configValues.value[f.key]) config[f.key] = configValues.value[f.key]
  const res = await api.savePluginConfig(deviceId.value, configPlugin.value.name, config)
  configSaving.value = false
  if (res.status === 200 && res.data?.code === 0) {
    emit('toast', '配置已保存')
    configPlugin.value = null
    await loadPlugins()
    emit('plugins-changed')
  } else {
    emit('toast', res.data?.message || '保存失败')
  }
}

watch(activeTab, (val) => {
  if (val === 'plugins') loadPlugins()
})

async function save() {
  if (!props.device?.mac || saving.value) return
  saving.value = true
  const body = {
    asr_provider: asrEngine.value === 'tencent' ? 'tencent' : 'volcengine',
    asr_config: asrEngine.value === 'tencent'
      ? { tencent: { app_id: form.value.tencent_app_id, secret_id: form.value.tencent_secret_id, secret_key: form.value.tencent_secret_key } }
      : { volcengine: {
          api_key: form.value.asr_api_key,
          no_speech_timeout: form.value.asr_no_speech_timeout || null,
          silence_timeout: form.value.asr_silence_timeout || null,
          max_concurrency: form.value.asr_max_concurrency || null,
          enable_pool: form.value.asr_enable_pool,
          pool_max_size: form.value.asr_pool_max_size || null,
          pool_min_size: form.value.asr_pool_min_size || null,
          pool_heartbeat_interval: form.value.asr_pool_heartbeat_interval || null,
          pool_idle_timeout: form.value.asr_pool_idle_timeout || null,
          pool_connection_timeout: form.value.asr_pool_connection_timeout || null,
        } },
    llm_api_key: form.value.llm_api_key,
    llm_base_url: 'https://api.deepseek.com/v1',
    llm_type: 'openai',
    llm_model: form.value.llm_model,
    llm_system_prompt: customPrompt.value ? form.value.llm_system_prompt : '',
    memory_enabled: memoryOn.value,
    memory_max_messages: form.value.llm_memory_max || 20,
    tts_api_key: form.value.tts_api_key,
    tts_resource_id: ttsModel.value,
    voice_type: form.value.voice_type,
    speed_ratio: form.value.tts_speed_ratio,
    volume_ratio: form.value.tts_volume_ratio,
    pitch_ratio: form.value.tts_pitch_ratio,
    tts_enable_pool: form.value.tts_enable_pool,
    tts_pool_max_size: form.value.tts_pool_max_size || null,
    tts_pool_min_size: form.value.tts_pool_min_size || null,
    tts_pool_heartbeat_interval: form.value.tts_pool_heartbeat_interval || null,
    tts_pool_idle_timeout: form.value.tts_pool_idle_timeout || null,
    tts_pool_connection_timeout: form.value.tts_pool_connection_timeout || null,
    tts_volc_openapi: {
      access_key_id: form.value.volc_ak,
      secret_access_key: form.value.volc_sk,
      project_name: form.value.volc_project,
    },
    wakeup_text: form.value.wakeup_text || '我在呢',
    wakeup_enable_audio: form.value.wakeup_enable_audio,
    wakeup_cache_enabled: form.value.wakeup_cache_enabled,
    wakeup_play_enabled: form.value.wakeup_play_enabled,
    wakeup_audio_source: form.value.wakeup_audio_source || 'file',
    wakeup_play_on_next_round: form.value.wakeup_play_on_next_round,
  }
  const res = await api.saveConfig(props.device.mac, body)
  saving.value = false
  if (res.status === 200 && res.data?.code === 0) {
    emit('toast', '设备配置已保存')
    emit('close')
  } else {
    emit('toast', res.data?.message || res.data?.detail || '保存失败')
  }
}
</script>

<style scoped>
/* 玻璃卡片 */
.glass {
  background: var(--grad-card);
  backdrop-filter: var(--glass-blur);
  -webkit-backdrop-filter: var(--glass-blur);
  border: 1px solid var(--glass-border);
  box-shadow: var(--shadow), var(--glass-hi);
  border-radius: var(--radius-lg);
}

/* 遮罩 */
.settings-mask {
  position: fixed; inset: 0; z-index: 200;
  display: flex; align-items: center; justify-content: center;
  background: rgba(17, 24, 39, 0.45);
  backdrop-filter: blur(8px) saturate(1.2);
  -webkit-backdrop-filter: blur(8px) saturate(1.2);
  animation: maskIn 0.25s var(--ease);
}
@keyframes maskIn { from { opacity: 0; } to { opacity: 1; } }

/* 弹窗 */
.settings-panel {
  width: min(560px, 92vw); max-height: 88vh;
  display: flex; flex-direction: column;
  background: var(--grad-panel);
  backdrop-filter: var(--glass-blur);
  -webkit-backdrop-filter: var(--glass-blur);
  border: 1px solid var(--glass-border);
  border-radius: 20px; overflow: hidden;
  box-shadow: 0 24px 60px rgba(16, 24, 40, 0.22), 0 4px 16px rgba(16, 24, 40, 0.08), var(--glass-hi);
  animation: panelIn 0.3s var(--ease);
}
@keyframes panelIn { from { opacity: 0; transform: translateY(16px) scale(0.97); } to { opacity: 1; transform: none; } }

/* 头部 */
.settings-head { display: flex; align-items: center; justify-content: space-between; padding: 18px 24px; border-bottom: 1px solid var(--glass-border-soft); }
.head-titles { display: flex; align-items: center; gap: 12px; min-width: 0; }
.settings-title { font-size: 17px; font-weight: 800; letter-spacing: -0.2px; }
.settings-device { font-size: 12px; font-weight: 600; color: var(--mint-deep); background: var(--mint-soft); border: 1px solid var(--mint-border); padding: 4px 12px; border-radius: 999px; white-space: nowrap; }
.settings-close { border: none; background: transparent; font-size: 15px; color: var(--text-dim); cursor: pointer; width: 32px; height: 32px; border-radius: 8px; display: flex; align-items: center; justify-content: center; transition: all 0.2s var(--ease); flex-shrink: 0; }
.settings-close:hover { color: var(--text-main); background: var(--glass-bg-strong); }

/* 选项卡 */
.tabs-bar {
  display: flex; gap: 6px; padding: 12px 24px 0;
}
.tab-item {
  border: 1px solid transparent; background: transparent; cursor: pointer;
  padding: 6px 14px; font-size: 12px; font-weight: 600; color: var(--text-sub);
  border-radius: 999px; transition: all 0.25s var(--ease);
}
.tab-item:hover { color: var(--text-main); background: var(--glass-bg-strong); }
.tab-item.active {
  background: var(--mint-soft); color: var(--mint-deep);
  border-color: var(--mint-border);
  animation: tabBreathe 2.8s ease-in-out infinite;
}
@keyframes tabBreathe {
  0%, 100% { box-shadow: 0 0 0 0 rgba(16, 185, 129, 0); }
  50% { box-shadow: 0 0 0 3px rgba(16, 185, 129, 0.1); }
}

/* 主体 */
.settings-body { padding: 18px 24px 20px; overflow-y: auto; flex: 1; }
.settings-body::-webkit-scrollbar { width: 6px; }
.settings-body::-webkit-scrollbar-thumb { background: var(--glass-border); border-radius: 999px; }
.settings-loading { padding: 80px; text-align: center; color: var(--text-sub); }

.tab-pane { display: flex; flex-direction: column; gap: 18px; }

/* 选项卡切换动画：旧页上移淡出，新页下移淡入 */
.tab-slide-enter-active, .tab-slide-leave-active { transition: all 0.28s var(--ease); }
.tab-slide-enter-from { opacity: 0; transform: translateY(12px); }
.tab-slide-leave-to { opacity: 0; transform: translateY(-8px); }
.block { display: flex; flex-direction: column; }
.block-label { font-size: 12px; font-weight: 600; color: var(--text-sub); margin-bottom: 8px; }
.form-tip { margin-top: 6px; font-size: 11px; color: var(--text-dim); }
.value-tag { float: right; font-size: 12px; font-weight: 700; color: var(--mint-deep); }
:deep(.input[type="range"]) { -webkit-appearance: none; appearance: none; height: 6px; border-radius: 3px; background: var(--border); outline: none; cursor: pointer; }
:deep(.input[type="range"]::-webkit-slider-thumb) { -webkit-appearance: none; appearance: none; width: 18px; height: 18px; border-radius: 50%; background: var(--mint); border: 2px solid #fff; box-shadow: 0 1px 4px rgba(0,0,0,0.2); cursor: pointer; }
:deep(.input[type="range"]::-moz-range-thumb) { width: 18px; height: 18px; border-radius: 50%; background: var(--mint); border: 2px solid #fff; box-shadow: 0 1px 4px rgba(0,0,0,0.2); cursor: pointer; }

/* 输入框聚焦光环 */
:deep(.input) { transition: border-color 0.2s var(--ease), box-shadow 0.2s var(--ease); background: rgba(255,255,255,0.55); border-color: var(--glass-border); }
:deep(.input:focus) { border-color: var(--mint); box-shadow: 0 0 0 3px rgba(16, 185, 129, 0.12); outline: none; background: rgba(255,255,255,0.75); }
:deep(textarea.input) { background: rgba(255,255,255,0.55); }
:deep(.input[type="range"]) { -webkit-appearance: none; appearance: none; height: 6px; border-radius: 3px; background: var(--border); outline: none; cursor: pointer; box-shadow: none; }

/* 引擎芯片 */
.engine-row { display: flex; gap: 8px; }
.engine-chip { border: 1px solid var(--glass-border); background: rgba(255,255,255,0.6); color: var(--text-sub); border-radius: 999px; padding: 6px 12px; font-size: 12px; font-weight: 600; cursor: pointer; transition: all 0.2s var(--ease); }
.engine-chip:hover { border-color: var(--mint); }
.engine-chip.active { border-color: var(--mint); background: var(--mint-soft); color: var(--mint-deep); animation: chipBreathe 2.5s ease-in-out infinite; }
@keyframes chipBreathe {
  0%, 100% { box-shadow: 0 0 0 0 rgba(16, 185, 129, 0); }
  50% { box-shadow: 0 0 0 3px rgba(16, 185, 129, 0.1); }
}

/* 模型卡片 */
.model-list { display: flex; flex-direction: row; gap: 8px; flex-wrap: wrap; }
.model-card { display: flex; flex-direction: column; gap: 3px; text-align: left; border: 1px solid var(--glass-border); background: rgba(255,255,255,0.55); border-radius: 12px; padding: 10px 14px; cursor: pointer; transition: all 0.25s var(--ease); flex: 1; min-width: 120px; }
.model-card:hover { border-color: var(--mint); transform: translateY(-1px); box-shadow: 0 4px 12px rgba(16,24,40,0.05); }
.model-card.active { border-color: var(--mint); background: var(--mint-soft); box-shadow: 0 4px 14px rgba(16,185,129,0.12); animation: modelBreathe 2.5s ease-in-out infinite; }
@keyframes modelBreathe {
  0%, 100% { box-shadow: 0 4px 14px rgba(16,185,129,0.12); }
  50% { box-shadow: 0 6px 20px rgba(16,185,129,0.2); }
}
.model-name { font-size: 13px; font-weight: 600; }
.model-desc { font-size: 11px; color: var(--text-dim); }

/* 输入框 + 小眼睛 */
.input-wrap { position: relative; }
.input-inner { padding-right: 44px; }
.eye-btn { position: absolute; right: 6px; top: 50%; transform: translateY(-50%); border: none; background: transparent; cursor: pointer; padding: 6px; font-size: 14px; opacity: 0.45; transition: opacity 0.2s; }
.eye-btn:hover { opacity: 0.9; }
.eye-icon.off { opacity: 0.25; }

/* iOS 开关 */
.toggle-row { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.toggle-label { flex: 1; min-width: 0; }
.toggle-title { font-size: 13px; font-weight: 600; color: var(--text-main); }
.toggle-sub { margin-top: 2px; font-size: 11px; color: var(--text-dim); }
.ios-toggle { width: 44px; height: 26px; border-radius: 999px; border: none; cursor: pointer; background: #d1d5db; position: relative; transition: background 0.25s var(--ease); flex-shrink: 0; padding: 0; }
.ios-toggle .knob { position: absolute; top: 2px; left: 2px; width: 22px; height: 22px; border-radius: 50%; background: #fff; box-shadow: 0 2px 5px rgba(0,0,0,0.18); transition: transform 0.25s var(--ease); }
.ios-toggle.on { background: var(--mint); }
.ios-toggle.on .knob { transform: translateX(18px); }
.toggle-body { margin-top: 12px; }

/* 字符计数 */
.char-count { margin-top: 6px; font-size: 11px; color: var(--text-dim); text-align: right; }

/* 折叠 */
.collapse-head { display: flex; align-items: center; justify-content: space-between; cursor: pointer; padding: 6px 0; border-radius: 8px; }
.collapse-head:hover .collapse-title { color: var(--mint-deep); }
.collapse-title { font-size: 13px; font-weight: 600; color: var(--text-sub); transition: color 0.2s var(--ease); }
.collapse-arrow { font-size: 12px; color: var(--text-dim); transition: transform 0.25s var(--ease); }
.collapse-arrow.open { transform: rotate(180deg); }
.collapse-body { margin-top: 8px; display: flex; flex-direction: column; gap: 14px; }

.settings-textarea { min-height: 80px; resize: vertical; }

/* ===== 插件管理 ===== */
.plugins-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.plugins-hint { font-size: 12px; color: var(--text-sub); }
.plugins-loading { padding: 40px; text-align: center; color: var(--text-sub); font-size: 13px; }
.plugins-empty {
  padding: 36px 16px; text-align: center;
  color: var(--text-dim); font-size: 13px;
  border: 1px dashed var(--glass-border);
  border-radius: 12px;
}
.plugin-list { display: flex; flex-direction: column; gap: 8px; }
.plugin-item {
  display: flex; flex-direction: column; gap: 10px;
  padding: 14px;
  background: rgba(255, 255, 255, 0.35);
  border: 1px solid var(--glass-border);
  border-radius: 12px;
  transition: all 0.2s var(--ease);
}
.plugin-item:hover { background: var(--mint-softer); border-color: var(--mint-border); }
.plugin-item.enabled { border-color: var(--mint-border); }
.plugin-item.has-update { border-color: var(--amber); }
.plugin-main { display: flex; align-items: center; gap: 10px; }
.plugin-icon {
  width: 36px; height: 36px; border-radius: 10px; flex-shrink: 0;
  display: flex; align-items: center; justify-content: center;
  font-size: 14px; font-weight: 700; color: var(--text-sub);
  background: var(--glass-bg-strong);
  border: 1px solid var(--glass-border);
  transition: all 0.25s var(--ease);
}
.plugin-icon.active { background: var(--grad-mint); color: #fff; border-color: transparent; box-shadow: var(--shadow-mint); }
.plugin-info { flex: 1; min-width: 0; }
.plugin-name { font-size: 13px; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.plugin-meta { display: flex; gap: 4px; margin-top: 4px; }
.plugin-meta .meta-tag {
  font-size: 10px; padding: 1px 6px; border-radius: 4px;
  background: var(--glass-bg-strong); color: var(--text-sub);
}
.plugin-meta .meta-tag.update { background: rgba(245, 158, 11, 0.14); color: #b45309; }
.plugin-actions { display: flex; gap: 4px; }
.plugin-actions .action-btn {
  flex: 1; padding: 5px 8px; font-size: 11px; font-weight: 600;
  border-radius: 8px; border: 1px solid var(--glass-border);
  background: var(--glass-bg-strong); color: var(--text-sub);
  cursor: pointer; transition: all 0.2s var(--ease);
}
.plugin-actions .action-btn:hover { border-color: var(--mint); color: var(--mint-deep); }
.plugin-actions .action-btn.toggle.on { background: var(--mint-soft); color: var(--mint); border-color: var(--mint-border); }
.plugin-actions .action-btn.update { background: rgba(245, 158, 11, 0.12); color: #b45309; border-color: transparent; }
.plugin-actions .action-btn.danger:hover { border-color: var(--danger); background: var(--danger-soft); color: var(--danger); }
.plugin-actions .action-btn:disabled { opacity: 0.5; cursor: not-allowed; }

/* ===== 插件配置弹窗 ===== */
.config-mask {
  position: fixed; inset: 0; z-index: 240;
  display: flex; align-items: center; justify-content: center;
  background: rgba(15, 23, 42, 0.4);
  backdrop-filter: blur(10px) saturate(140%);
  -webkit-backdrop-filter: blur(10px) saturate(140%);
  padding: 20px;
}
.config-panel {
  width: min(420px, 90vw);
  padding: 26px 24px;
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-hover), var(--glass-hi);
}
.config-title { font-size: 16px; font-weight: 700; margin: 0 0 6px; }
.config-note { font-size: 12px; color: var(--text-sub); margin: 0 0 18px; }
.config-field { margin-bottom: 14px; }
.config-label { display: block; font-size: 12px; font-weight: 600; color: var(--text-sub); margin-bottom: 6px; }
.config-label .req { color: var(--danger); }
.config-actions { display: flex; justify-content: flex-end; gap: 10px; margin-top: 20px; }
.config-actions .btn-ghost { background: rgba(255,255,255,0.6); color: var(--text-sub); border: 1px solid var(--glass-border); }
.config-actions .btn-ghost:hover { border-color: var(--mint-border); color: var(--mint-deep); background: var(--mint-softer); }
.config-actions .btn-mint { background: var(--grad-mint); color: #fff; border: none; box-shadow: var(--shadow-mint); }

/* 弹窗过渡 */
.pop-enter-active, .pop-leave-active { transition: all 0.3s var(--ease); }
.pop-enter-from, .pop-leave-to { opacity: 0; transform: scale(0.95) translateY(10px); }

/* 底部按钮区 */
.settings-foot {
  display: flex; justify-content: flex-end; gap: 12px; padding: 16px 24px;
  border-top: 1px solid rgba(255, 255, 255, 0.6);
  background: var(--grad-card);
  backdrop-filter: var(--glass-blur);
  -webkit-backdrop-filter: var(--glass-blur);
  box-shadow: var(--glass-hi), 0 -4px 20px rgba(16, 24, 40, 0.06);
}
.btn-ghost {
  border: 1px solid var(--glass-border);
  background: var(--grad-card);
  backdrop-filter: var(--glass-blur);
  -webkit-backdrop-filter: var(--glass-blur);
  box-shadow: var(--glass-hi);
  color: var(--text-sub); border-radius: 10px; padding: 7px 16px; font-size: 13px; font-weight: 600; cursor: pointer; transition: all 0.25s var(--ease);
}
.btn-ghost:hover { border-color: var(--mint-border); color: var(--mint-deep); background: var(--mint-softer); }
.btn-mint {
  border: 1px solid var(--mint-border);
  cursor: pointer; border-radius: 10px; padding: 7px 16px; font-size: 13px; font-weight: 700; color: #fff;
  background: linear-gradient(135deg, rgba(52,211,153,0.9), rgba(5,150,105,0.9));
  backdrop-filter: var(--glass-blur);
  -webkit-backdrop-filter: var(--glass-blur);
  box-shadow: var(--shadow-mint), var(--glass-hi);
  transition: all 0.25s var(--ease);
}
.btn-mint:hover:not(:disabled) { transform: translateY(-2px); box-shadow: 0 8px 22px rgba(16,185,129,0.3); }
.btn-mint:disabled { opacity: 0.6; cursor: not-allowed; }
</style>
