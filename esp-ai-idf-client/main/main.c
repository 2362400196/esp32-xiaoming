#include "config.h"
#include "log_system.h"
#include "nvs_flash.h"
#include "nvs.h"
#include "provisioning.h"
#include "commands/command_registry.h"
#include "boards/board_interface.h"
#include "eeui_port.h"
#if defined(AUDIO_SCHEME_ES8311)
#include "audio_codec/es8311.h"
#endif
#include "esp_heap_caps.h"
#include "esp_system.h"
#include "esp_spiffs.h"

static const char *TAG = "main";

// 前向声明（命令注册函数在 commands/ 目录中，通过显式注册调用）
extern void register_audio_commands(void);
extern void register_lyric_commands(void);
extern void register_lua_commands(void);
extern void register_bind_commands(void);
extern void register_config_commands(void);
extern void register_official_commands(void);
extern void register_ota_commands(void);

// 会话看门狗：记录唤醒时间，防止 wakenet 永久暂停
static TickType_t s_wakeup_trigger_tick = 0;
// 会话看门狗由"心跳 + 业务数据"驱动（websocket.c 收到任意数据帧时刷新）：
// 服务端 keepalive 间隔 TTS 时 1s、其他状态 3s，因此正常会话会持续刷新，永不误杀长对话。
// 60 秒 = 20 个心跳周期无任何动静，说明服务端已无响应（断网/崩溃），此时兜底恢复唤醒。
// 注意：真正的连接存活检测由 websocket_check_keepalive()（45s 无心跳主动断开）负责，
// 此看门狗是会话级最后一道兜底。
#define SESSION_WATCHDOG_TIMEOUT_MS 60000

// ==================== BLE 配网设备绑定回调（与 esp-ai-client 的 onBindDeviceCb 一致） ====================
// 用户可在此处向自己的服务注册设备绑定
// data_json: 包含 wifi_name, wifi_pwd 及所有自定义字段的 JSON
// 返回 JSON 格式: {"success":true} 或 {"success":false,"message":"xxx"}
// 返回的字符串会被自动 free，需用 malloc/strdup 分配
static char *on_bind_device(const char *data_json)
{
    ESP_LOGI(TAG, "on_bind_device called, data: %s", data_json);
    // 默认绑定成功，用户可在此处添加自己的绑定逻辑
    char *result = strdup("{\"success\":true,\"message\":\"\"}");
    return result;
}

// 处理唤醒事件
// 与 Arduino wakeUp("wakeup") 流程一致：
// 1. 停止所有音频播放 (mp3_player_stop)
// 2. 暂停 WakeNet（IDF 特有：I2S 句柄共享需要暂停）
// 3. 发送 start 消息 (sendTXT)
// 4. 清除 tts_task_id
// 注意：与 Arduino 一致，唤醒时不启动麦克风采集任务。
// Arduino 的 open_mic() 只切换 I2S 硬件模式，不立即发送数据。
// 数据发送在 iat_start 时才开始（Arduino: esp_ai_start_send_audio = true）。
// IDF 对应：iat_start 时调用 audio_mic_start()。
// 播放唤醒提示音缓存并等待播完（对齐 Arduino wakeUp.cpp: wait_mp3_player_done）
// 无缓存时直接返回，不影响原有唤醒流程
static void play_wakeup_prompt(const uint8_t *data, size_t len)
{
    if (!data || len == 0) return;
    audio_spk_play();          // 重置播放缓冲 + 启动播放
    audio_spk_write(data, len);
    audio_spk_wait_drain();    // 设置 drain 等待，播完由 spk_task 置 drain_done
    for (int i = 0; i < 100; i++) {   // 最长等 2 秒
        if (audio_spk_check_drain_done()) break;
        vTaskDelay(pdMS_TO_TICKS(20));
    }
    audio_spk_stop();          // 停止提示音播放，准备进入对话
}

static void handle_wakeup(void)
{
    ESP_LOGI(TAG, "唤醒触发，开始对话...");

    // 通知板级扩展组件（extras）唤醒事件：组件收到后做自己的联动
    // （如状态 LED 双闪提示）。组件回调应快速返回，不得阻塞。
    board_extra_broadcast_event(BOARD_EVENT_WAKEUP, NULL);

    // vv=== Arduino wakeUp: mp3_player_stop() ===vv
    // 1. 记录是否正在播放（打断场景不播唤醒提示，响应更快，与 Arduino is_playing 判断一致）
    bool was_playing = audio_spk_is_playing();
    // 2. 停止网络音频音乐
    network_audio_stop();
    // 3. 硬停止扬声器播放（清空缓冲区 + 重置解码器，相当于 Arduino mp3_player_stop）
    audio_spk_hard_stop();
    // 给 spk_task 时间处理 s_spk_need_reset（清空 I2S DMA、释放解码器）
    // 打断场景下 spk_task 可能正在阻塞写 I2S，最多等 100ms 让 DMA 写完成
    vTaskDelay(pdMS_TO_TICKS(30));

    // vv=== IDF 特有：确保 WakeNet 已暂停，避免 I2S 句柄竞争 ===vv
    // 按钮唤醒和语音唤醒均可能触发，语音唤醒任务自身会暂停，
    // 但按钮唤醒不会暂停 WakeNet，必须在这里强制暂停
    wakeup_pause();

    // vv=== Arduino wakeUp: esp_ai_session_id = "" ===vv
    // 清除上一轮对话状态（session_id、tts_task_id、drain action 等）
    // 语音打断时旧会话可能还在 drain 等待中，必须清理
    // 先停止可能残留的麦克风采集（iat_start 后可能未收到 iat_end 就被打断）
    audio_mic_stop();
    websocket_reset_conversation_state();

    // vv=== Arduino wakeUp: 播放唤醒提示音（服务端缓存的叮声/问候语）===
    // 打断场景（was_playing）不播提示音，响应更快；无缓存则跳过。
    // get/release 成对调用：持有期间服务端不会释放/覆盖缓存缓冲（防 use-after-free）
    if (!was_playing) {
        const uint8_t *prompt = NULL;
        size_t prompt_len = 0;
        if (websocket_cache_get_greeting(&prompt, &prompt_len)) {
            play_wakeup_prompt(prompt, prompt_len);
            websocket_cache_release(prompt);
        }
        if (websocket_cache_get_tone(&prompt, &prompt_len)) {
            play_wakeup_prompt(prompt, prompt_len);
            websocket_cache_release(prompt);
        }
    }

    // 发送 start 消息到服务器，触发会话开始
    // 不在此处启动麦克风！与 Arduino 一致：
    // Arduino wakeUp 只 open_mic()（硬件切换），不设 esp_ai_start_send_audio
    // 麦克风采集在 iat_start 时启动
    esp_err_t ret = websocket_send_text("{\"type\":\"start\"}");
    if (ret == ESP_OK) {
        ESP_LOGI(TAG, "已发送唤醒消息到服务器");
        s_wakeup_trigger_tick = xTaskGetTickCount();
        // 启动唤醒响应超时检测：若 10 秒未收到服务端任何数据(半开连接)，自动重连
        websocket_mark_wakeup_sent();
        // 会话活跃：WiFi 切回 NONE 保证 ASR/TTS 低延迟（省电待机结束）
        power_manager_set_active(true);
    } else {
        ESP_LOGW(TAG, "发送唤醒消息失败，主动触发重连");
        // 发送失败时必须恢复 wakenet，否则唤醒词检测永久卡死
        // 场景：WebSocket 未连接/发送缓冲区满/网络异常
        wakeup_resume();
        // 清除唤醒冷却：失败的唤醒不惩罚用户，网络恢复后立即可再次唤醒
        // （否则断线期间每次唤醒失败+8 秒冷却，感知为"永远唤不醒"）
        wakeup_clear_cooldown();
        // 静默断线（TCP 半开）时自动重连可能不及时，主动触发一次重连
        websocket_force_reconnect();
        power_manager_set_active(false);  // 回待机省电
        display_show_status("等待唤醒...");
        display_show_emotion("休息中");
    }

    // 通知显示模块
    display_show_status("聆听中");
    display_show_emotion("聆听中");
}

// 会话看门狗刷新：收到任意服务端数据（websocket.c 的 WEBSOCKET_EVENT_DATA）时调用。
// 把"死计时"改为"活动刷新"——只要对话有动静（ASR/LLM/TTS/音频块），看门狗就重置，
// 不会把一次正常的多轮长对话误判为超时。
// 当 WakeNet 已恢复（会话正常结束），重置看门狗计时，避免上一轮唤醒的 tick 残留
// 导致下一轮 iat_start 暂停 WakeNet 时误判超时。
void session_watchdog_refresh(void)
{
    if (s_wakeup_trigger_tick != 0) {
        if (wakeup_is_paused()) {
            s_wakeup_trigger_tick = xTaskGetTickCount();
        } else {
            // WakeNet 已恢复（会话正常结束），清除看门狗计时
            s_wakeup_trigger_tick = 0;
        }
    }
}

// 启动会话看门狗计时：在 iat_start 暂停 WakeNet 后调用，确保服务端
// 若未及时发送唤醒音频能在 10 秒内触发超时重连，避免设备卡死。
void session_watchdog_start(void)
{
    s_wakeup_trigger_tick = xTaskGetTickCount();
}

// OTA 检查 + 表情下载兜底任务：WebSocket 连接事件回调中创建 ota_check_task
// 若因内存不足失败（s_ota_checked 未置位），此处延迟 20 秒后再次触发。
// websocket_trigger_ota_check() 幂等，事件回调已触发时直接返回。
static void ota_check_fallback_task(void *arg)
{
    vTaskDelay(pdMS_TO_TICKS(20000));
    websocket_trigger_ota_check();
    vTaskDelete(NULL);
}

void app_main(void)
{
    // 设置全局日志级别（生产模式仅 Warning+Error，调试模式全部输出）
#ifndef CONFIG_LOG_LEVEL_DEBUG
    esp_log_level_set("*", ESP_LOG_WARN);
#endif

    ESP_LOGI(TAG, "========================================");
    ESP_LOGI(TAG, "ESP-AI IDF Client v%s", FIRMWARE_VERSION);
    ESP_LOGI(TAG, "唤醒词: 由 esp-sr 模型分区决定（见 wakeup 日志）");
    ESP_LOGI(TAG, "========================================");

#ifdef CONFIG_LOG_LEVEL_DEBUG
    ESP_LOGI(TAG, "日志级别: DEBUG (全部输出)");
#else
    ESP_LOGI(TAG, "日志级别: PRODUCTION (仅 Warning + Error)");
#endif

    // 设置关键模块为调试日志级别
    // 调试覆盖仅限 INFO 级别的启动诊断；websocket/network_audio 等会输出
    // 服务端消息内容（含用户语音识别文本）的模块只在显式 DEBUG 构建中放开，
    // 生产模式保持 esp_log_level_set("*", ESP_LOG_WARN) 的全局设置
    esp_log_level_set("wifi", ESP_LOG_INFO);     // WiFi 连接过程（重试、断开原因）
    // 初始化阶段的内存诊断（各阶段剩余堆），生产模式也保持 INFO 可见
    esp_log_level_set("main", ESP_LOG_INFO);
    esp_log_level_set("audio", ESP_LOG_INFO);
    esp_log_level_set("wakeup", ESP_LOG_INFO);
    esp_log_level_set("display", ESP_LOG_INFO);
    esp_log_level_set("eeui_port", ESP_LOG_INFO);  // show_card 渲染明细（排查卡片问题）
#ifdef CONFIG_LOG_LEVEL_DEBUG
    esp_log_level_set("cmd_lyric", ESP_LOG_DEBUG);
    esp_log_level_set("websocket", ESP_LOG_DEBUG);
    esp_log_level_set("network_audio", ESP_LOG_DEBUG);
    esp_log_level_set("cmd_lua", ESP_LOG_DEBUG);
    esp_log_level_set("lua_rt", ESP_LOG_DEBUG);
#endif

    // 初始化NVS
    esp_err_t ret = nvs_flash_init();
    if (ret == ESP_ERR_NVS_NO_FREE_PAGES || ret == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        ret = nvs_flash_init();
    }
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "NVS初始化失败");
        return;
    }

    // 生成并保存设备ID（基于WiFi MAC地址）
    {
        char device_id[32] = {0};
        device_id_get(device_id, sizeof(device_id));
        ESP_LOGI(TAG, "设备ID: %s", device_id);

        nvs_handle_t h;
        if (nvs_open("esp-ai-kv", NVS_READWRITE, &h) == ESP_OK) {
            esp_err_t nvs_ret = nvs_set_str(h, "device_id", device_id);
            if (nvs_ret == ESP_OK) {
                nvs_ret = nvs_commit(h);
            }
            if (nvs_ret != ESP_OK) {
                ESP_LOGW(TAG, "设备ID写入NVS失败: %s", esp_err_to_name(nvs_ret));
            }
            nvs_close(h);
        }
    }

    // 挂载 SPIFFS 文件系统（storage 分区，与 SR 模型分区分离）
    // model 分区只放唤醒词模型，storage 分区专供 Lua storage 模块
    {
        esp_vfs_spiffs_conf_t spiffs_conf = {
            .base_path = "/spiffs",
            .partition_label = "storage",
            .max_files = 5,
            .format_if_mount_failed = true,
        };
        esp_err_t spiffs_ret = esp_vfs_spiffs_register(&spiffs_conf);
        if (spiffs_ret != ESP_OK) {
            ESP_LOGW(TAG, "SPIFFS 挂载失败（不影响启动）: %s", esp_err_to_name(spiffs_ret));
        } else {
            size_t total = 0, used = 0;
            esp_spiffs_info("storage", &total, &used);
            ESP_LOGI(TAG, "SPIFFS 已挂载: %s, 总大小=%lu KB, 已用=%lu KB",
                     "/spiffs", (unsigned long)(total / 1024), (unsigned long)(used / 1024));
        }
    }

    // 注册回调指令（替代 __attribute__((constructor))，后者在 ESP-IDF 静态库中无效）
    register_callback_commands();
    register_audio_commands();
    register_lyric_commands();
    register_lua_commands();
    register_bind_commands();
    register_display_commands();
    register_config_commands();

    // 注册 BLE 配网设备绑定回调（与 esp-ai-client 的 onBindDevice 一致）
    provisioning_set_on_bind_cb(on_bind_device);

    // 初始化板级包（board_select.h 自动选择板型，board_init() 直接使用 ACTIVE_BOARD_CONFIG）
    ret = board_init();
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "板级包初始化失败");
        return;
    }

    // 官方服务版专用指令（依赖 board_get_config，须在 board_init 之后注册；
    // 后注册头插覆盖同名 play_music，普通板内部跳过、行为不受影响）
    register_official_commands();
    // OTA 升级指令（服务端 ota_update 强制升级下发，所有板型通用）
    register_ota_commands();
    commands_list();  // 打印已注册指令列表，确认所有指令已加载

    // 初始化显示
    ret = display_init();
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "显示初始化失败");
        return;
    }
    display_show_status("系统启动中...");

    // 从 NVS 恢复屏幕亮度（set_brightness 指令保存的 bl_level；未保存过则保持默认 100%）
    // 放在 display_init 之后、界面渲染之前，避免开机先亮 100% 再跳变
    {
        nvs_handle_t h;
        int32_t bl_level = -1;
        if (nvs_open("esp-ai-kv", NVS_READONLY, &h) == ESP_OK) {
            if (nvs_get_i32(h, "bl_level", &bl_level) != ESP_OK) {
                bl_level = -1;
            }
            nvs_close(h);
        }
        if (bl_level >= 0 && bl_level <= 100) {
            display_set_brightness((int)bl_level);
            ESP_LOGI(TAG, "从 NVS 恢复屏幕亮度: %d%%", (int)bl_level);
        }
    }

    // 推迟初始表情显示，确保 LVGL 完全就绪
    display_show_emotion("休息中");
    display_show_status("初始化完成");

    // ES8311 I2C 总线初始化（在 WiFi 之前，对齐 xiaozhi-esp32 的 InitializeI2c）
    // xiaozhi 在板级构造函数中创建 I2C 总线（WiFi 之前），永不删除/重建。
    // 此处仅创建 I2C 总线和设备，不写寄存器（寄存器在 es8311_init 中配置）。
    // WiFi 之前创建 I2C 总线可避免 WiFi 射频对 I2C 外设初始化的干扰。
#if defined(AUDIO_SCHEME_ES8311)
    {
        const es8311_config_t *ecfg = board_get_config()->es8311_cfg;
        es8311_i2c_init(ecfg->i2c_port, ecfg->i2c_sda, ecfg->i2c_scl, ecfg->i2c_addr);
    }
#endif

    // 初始化WiFi（在 I2C 总线之后，语音唤醒和音频之前）
    // 注意：WiFi 需要在 display_init 之后（wifi.c 会调用 display_show_status）
    display_show_status("连接WiFi...");
    ret = wifi_init();
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "WiFi初始化失败");
        display_show_status("WiFi连接失败");
        return;
    }
    display_show_status("WiFi已连接");

    // 初始化语音唤醒（在音频之前，创建共享的 I2S 麦克风通道）
    // ES8311 方案：先初始化编解码器（I2C 配 ADC/DAC/时钟），再启动 I2S
    // 注意：实测调整为先启动 I2S(MCLK) 再初始化 ES8311 会导致无法唤醒/收音/播放，
    // 保持本顺序（用户验证可用），不要改动。
    // ES8311 作为 slave 从机，CSM 需在寄存器配置完成后、MCLK 稳定运行时锁定；
    // MCLK 尚未运行时就使能 CSM 会导致时钟失锁 → 巨大电流声 + 无收音。
#if defined(AUDIO_SCHEME_ES8311)
    {
        const es8311_config_t *ecfg = board_get_config()->es8311_cfg;
        esp_err_t es_err = es8311_init(ecfg->i2c_port,
                                       ecfg->i2c_sda,
                                       ecfg->i2c_scl,
                                       ecfg->i2c_addr,   // 0 = 默认 0x18
                                       ecfg->mclk_freq,  // MCLK 频率
                                       SPK_SAMPLE_RATE);
        if (es_err != ESP_OK) {
            // 不 return：ES8311 异常（常见于软重启后芯片未断电、I2C 不响应）
            // wakeup_init 中 MCLK 运行后还会重试一次，此处继续启动 WiFi/WebSocket
            ESP_LOGE(TAG, "ES8311 初始化失败: %s（将在 MCLK 就绪后重试）",
                     esp_err_to_name(es_err));
            display_show_status("音频初始化中...");
        } else {
            es8311_set_mic_gain(36);   // 麦克风增益 36dB（从 24dB 提升，进一步改善唤醒灵敏度；最高 42dB）
        }
    }
#endif

    ret = wakeup_init();
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "语音唤醒初始化失败");
        display_show_status("唤醒初始化失败");
        return;
    }
    ESP_LOGI(TAG, "wakeup_init 后剩余堆: %d bytes (内部)",
             (int)heap_caps_get_free_size(MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT));

    // 初始化WebSocket（提前到 audio_init 之前！）
    // 原因：C3 无 PSRAM，wakeup_init（AFE+唤醒模型）会吃掉约 100KB 堆，
    // 若等 audio_init（MP3 解码器 45KB + 播放任务缓冲）之后再初始化 WebSocket，
    // 堆只剩几 KB，esp_websocket_client 连自己的任务栈都创建不出来。
    // WebSocket 与音频无依赖（音频只需 wakeup 创建的共享 I2S 句柄），提前初始化
    // 可在堆余量最大时完成连接；服务端音频帧只在会话开始后下发，不会先于 audio_init
    // 到达（唤醒提示音缓存走 websocket.c 内部缓存，不经过音频系统）。
    display_show_status("连接服务...");
    ret = websocket_init();
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "WebSocket初始化失败，剩余堆: %d bytes",
                 (int)heap_caps_get_free_size(MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT));
        display_show_status("服务连接失败");
        return;
    }
    ESP_LOGI(TAG, "websocket_init 后剩余堆: %d bytes (内部)",
             (int)heap_caps_get_free_size(MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT));

    // OTA 检查 + 表情下载兜底：若 WebSocket 连接事件回调创建 ota_check_task 失败
    //（上电初期内存紧张），20 秒后由本任务再次触发（幂等，不会重复执行）
    xTaskCreate(ota_check_fallback_task, "ota_fb", 1024, NULL, 1, NULL);

    // 初始化音频（使用 wakeup 创建的共享麦克风句柄）
    ESP_LOGI(TAG, "audio_init 前剩余堆: %d bytes (内部)",
             (int)heap_caps_get_free_size(MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT));
    ret = audio_init();
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "音频初始化失败");
        return;
    }
    ESP_LOGI(TAG, "audio_init 后剩余堆: %d bytes (内部)",
             (int)heap_caps_get_free_size(MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT));

    // 初始化功耗管理（在音频初始化之后，PA 引脚已配置）
    power_manager_init();

    // 从 NVS 恢复屏保配置（重启后保持之前设置的屏保开关和超时）
    {
        nvs_handle_t h;
        if (nvs_open("esp-ai-kv", NVS_READONLY, &h) == ESP_OK) {
            char buf[16] = {0};
            size_t sz = sizeof(buf);

            // 屏保开关（先在当前作用域声明，下面恢复超时需复用）
            bool ss_enabled = false;
            bool ss_enabled_found = false;

            // 恢复屏保开关（ss_enabled = screensaver_enabled 短键名）
            if (nvs_get_str(h, "ss_enabled", buf, &sz) == ESP_OK) {
                ss_enabled = (strcmp(buf, "true") == 0 || strcmp(buf, "1") == 0);
                ss_enabled_found = true;
                power_manager_set_screensaver_config(ss_enabled ? 1 : 0, -1);
                ESP_LOGI(TAG, "从 NVS 恢复屏保开关: %s", ss_enabled ? "开启" : "关闭");
            }

            // 恢复屏保超时（ss_timeout = screensaver_timeout 短键名）
            sz = sizeof(buf);
            memset(buf, 0, sizeof(buf));
            if (nvs_get_str(h, "ss_timeout", buf, &sz) == ESP_OK) {
                int sec = atoi(buf);
                if (sec >= 5 && sec <= 600) {
                    // 使用已恢复的开关值，不硬编码为 true！
                    // 若 ss_enabled 未找到（NVS 无记录），则默认启用屏保
                    power_manager_set_screensaver_config(ss_enabled_found ? (ss_enabled ? 1 : 0) : 1, sec);
                    ESP_LOGI(TAG, "从 NVS 恢复屏保超时: %d秒（开关=%s）", sec, ss_enabled ? "开" : "关");
                }
            }

            nvs_close(h);
        }
    }

    // 从 NVS 恢复音量（与 Arduino ext2 键一致，移植自 Arduino volume 持久化）
    {
        nvs_handle_t h;
        bool vol_restored = false;
        if (nvs_open("esp-ai-kv", NVS_READONLY, &h) == ESP_OK) {
            char vol_str[16] = {0};
            size_t required_size = sizeof(vol_str);
            if (nvs_get_str(h, "ext2", vol_str, &required_size) == ESP_OK) {
                float vol = atof(vol_str);
                audio_set_volume(vol);
                vol_restored = true;
                ESP_LOGI(TAG, "从 NVS 恢复音量: %.2f", vol);
            }
            nvs_close(h);
        }
        // 无 NVS 存储值时，显式渲染默认音量图标
        if (!vol_restored) {
            audio_set_volume(1.0f);
        }
    }

    // 从 NVS 恢复机器人模式（重启后保持之前设置的机器人模式状态）
    {
        nvs_handle_t h;
        bool robot_mode = false;
        if (nvs_open("esp-ai-kv", NVS_READONLY, &h) == ESP_OK) {
            char buf[8] = {0};
            size_t sz = sizeof(buf);
            if (nvs_get_str(h, "robot_mode", buf, &sz) == ESP_OK) {
                robot_mode = (strcmp(buf, "true") == 0 || strcmp(buf, "1") == 0);
            }
            nvs_close(h);
        }
        if (robot_mode) {
            eeui_port_set_robot_mode(true);
            ESP_LOGI(TAG, "从 NVS 恢复机器人模式: 开启");
        }
    }

    // 表情下载改为 OTA 检查之后触发（先版本后表情），见 websocket.c ota_check_task。
    // 表情不再编译进固件（emos/*.h 已移除），所有图形板型都必须下载：
    // 首次联网后存入 SPIFFS 缓存，之后开机优先读本地缓存

    // 启动唤醒检测（按钮 + 语音）
    ret = wakeup_start();
    if (ret != ESP_OK) {
        ESP_LOGW(TAG, "唤醒检测启动失败");
    }

    // 启动功耗管理定时器（在唤醒检测之后，系统已进入待机状态）
    power_manager_start();

    display_show_status("等待唤醒...");
    display_show_emotion("休息中");

    ESP_LOGI(TAG, "系统初始化完成");

    // 打印内存使用情况
    ESP_LOGI(TAG, "======== 内存统计 ========");
    ESP_LOGI(TAG, "内部 RAM 可用: %ld bytes (%.1f KB)",
             (long)heap_caps_get_free_size(MALLOC_CAP_INTERNAL),
             (float)heap_caps_get_free_size(MALLOC_CAP_INTERNAL) / 1024.0f);
    ESP_LOGI(TAG, "内部 RAM 最大块: %ld bytes (%.1f KB)",
             (long)heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL),
             (float)heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL) / 1024.0f);
    ESP_LOGI(TAG, "PSRAM 可用: %ld bytes (%.1f KB)",
             (long)heap_caps_get_free_size(MALLOC_CAP_SPIRAM),
             (float)heap_caps_get_free_size(MALLOC_CAP_SPIRAM) / 1024.0f);
    ESP_LOGI(TAG, "PSRAM 最大块: %ld bytes (%.1f KB)",
             (long)heap_caps_get_largest_free_block(MALLOC_CAP_SPIRAM),
             (float)heap_caps_get_largest_free_block(MALLOC_CAP_SPIRAM) / 1024.0f);
    ESP_LOGI(TAG, "总可用堆: %ld bytes (%.1f KB)",
             (long)esp_get_free_heap_size(),
             (float)esp_get_free_heap_size() / 1024.0f);
    ESP_LOGI(TAG, "最小空闲堆(水位): %ld bytes (%.1f KB)",
             (long)esp_get_minimum_free_heap_size(),
             (float)esp_get_minimum_free_heap_size() / 1024.0f);
    ESP_LOGI(TAG, "==========================");

    // 主循环 - 处理唤醒事件 + 定期上报 IO 读取值
    uint32_t io_report_tick = 0;
    while (1) {
        EventBits_t bits = xEventGroupWaitBits(
            s_wakeup_event_group,
            WAKEUP_TRIGGERED_BIT,
            pdTRUE,  // 清除位
            pdFALSE,
            pdMS_TO_TICKS(500)  // 500ms 超时，用于定期上报 IO
        );

        if (bits & WAKEUP_TRIGGERED_BIT) {
            handle_wakeup();
        }

        // 会话看门狗：如果 wakenet 已暂停（唤醒已发送但服务端无响应），
        // 分两级处理：
        //   1. 唤醒超时（10秒）：唤醒消息发出后未收到任何服务端数据，
        //      判定连接异常（半开/断线），主动重连后恢复唤醒。
        //      与 websocket_check_keepalive() 中的 s_wakeup_pending 检测互补：
        //      此处不依赖 volatile 标志位，直接检查 WakeNet 暂停状态 + 唤醒时间，
        //      即使 s_wakeup_pending 因意外事件被清除也能兜底恢复。
        //   2. 会话超时（60秒）：服务端应答后整个对话无任何进展，
        //      自动恢复唤醒检测，避免唤醒词永久失效。
        if (s_wakeup_trigger_tick != 0 && wakeup_is_paused()) {
            TickType_t elapsed_ms = (xTaskGetTickCount() - s_wakeup_trigger_tick) * portTICK_PERIOD_MS;
            if (elapsed_ms > 10000 && elapsed_ms < SESSION_WATCHDOG_TIMEOUT_MS) {
                // 唤醒超时：10秒内无任何服务端数据 → 半开连接/断线
                ESP_LOGW(TAG, "唤醒超时: %dms 无服务端响应，强制重连恢复", (int)elapsed_ms);
                wakeup_resume();
                s_wakeup_trigger_tick = 0;
                audio_spk_stop();
                audio_mic_stop();
                websocket_reset_conversation_state();
                // 强制重连 WebSocket，修复半开连接
                websocket_force_reconnect();
                power_manager_set_active(false);
                display_show_status("连接异常，重连中...");
                display_show_emotion("休息中");
            } else if (elapsed_ms > SESSION_WATCHDOG_TIMEOUT_MS) {
                // 会话超时：60秒无任何数据 → 服务端已无响应，兜底恢复
                ESP_LOGW(TAG, "会话看门狗: %dms 无 session_end，自动恢复唤醒", (int)elapsed_ms);
                wakeup_resume();
                s_wakeup_trigger_tick = 0;
                audio_spk_stop();
                audio_mic_stop();
                websocket_reset_conversation_state();
                power_manager_set_active(false);
                display_show_status("等待唤醒...");
                display_show_emotion("休息中");
            }
        }

        // 定期上报硬件 IO 读取值（每 1 秒，移植自 Arduino reporting_sensor_data）
        io_report_tick++;
        if (io_report_tick >= 2) {
            io_report_tick = 0;
            hardware_io_report_readings();
        }
    }
}
