#include "config.h"
#include "board_compat.h"
#include "provisioning.h"
#include "driver/gpio.h"
#include "driver/i2s_std.h"
#include <math.h>  /* sqrtf（回声延迟互相关归一化） */
#include <string.h> /* memset（参考未对齐时补零） */
#include <stdlib.h>  /* atof（NVS 唤醒灵敏度解析） */
// 纯 WakeNet 接口（对齐 xiaozhi-esp32 C3 方案）：
// 不经过完整 AFE（NS/VAD/AEC/ringbuffer），I2S 数据累积到 chunksize 后直接 detect()。
// 相比 AFE 方案：内存更小、无 "Ringbuffer of AFE is empty" 刷屏问题。
#include "esp_wn_iface.h"
#include "esp_wn_models.h"
#include "model_path.h"
#include "esp_heap_caps.h"  /* heap_caps_get_free_size（内存诊断） */
#include "gif_downloader.h" /* gif_download_is_busy：表情下载期间禁用唤醒 */
#include "ota_update.h"     /* ota_is_updating：OTA 升级期间禁用唤醒/按键 */
#include "nvs_flash.h"      /* 唤醒灵敏度 NVS 持久化 */
#include "esp_timer.h"      /* esp_timer_get_time：AFE 循环耗时段（诊断「算」） */
#include "freertos/idf_additions.h"  /* xTaskCreatePinnedToCoreWithCaps */
#include "freertos/semphr.h"
#if defined(AUDIO_SCHEME_ES8311)
#include "audio_codec/es8311.h"
#endif

// S3 + ES8311 全双工方案：AFE 管线（AEC+VAD）+ 外挂纯 WakeNet 检测
// 【架构】wn9 唤醒模型在 AFE 内不检出（本项目 srmodels 只打包 wn9，
// "VadNet is not initialized"），故 AFE 只跑 AEC+VAD（wakenet_init=false），
// 唤醒词用纯接口实例 detect()：
// - 空闲态喂原始麦克风数据（已验证可靠）
// - TTS 播放中喂 AEC 输出（回声已消，喊唤醒词也能打断；AEC 未对齐/发散时跳过，
//   见 afe_task 唤醒词检测处的门）
// AEC 对齐三件套（详见下方"AEC 参考对齐"一节）：
// 1. audio.c 起播灌满 TX DMA 队列 → 发出延迟恒为队列深度（180ms），不再是随机相位；
// 2. 发出账本 E 按样本数推进，欠载时停账喂零参考；
// 3. 每条流开始互相关标定一次抽头（两窗投票），锁定后不再动。
// VAD 用 AFE 能量 VAD（VadNet 模型缺失自动回退）。
// C3 无 PSRAM 跑不动 AFE，保持纯 WakeNet 方案。
#if defined(CONFIG_IDF_TARGET_ESP32S3) && defined(AUDIO_SCHEME_ES8311)
#define WAKEUP_USE_AFE 1
#endif

#if defined(WAKEUP_USE_AFE)
#include "esp_afe_sr_iface.h"
#include "esp_afe_sr_models.h"
#include "esp_vad.h"        /* VAD_SPEECH 枚举 */
#endif

static const char *TAG = "wakeup";

// 唤醒状态
static bool s_wakeup_running = false;
static TaskHandle_t s_wakeup_task_handle = NULL;
static TaskHandle_t s_wakenet_task_handle = NULL;

// 事件组
EventGroupHandle_t s_wakeup_event_group;

// BOOT 按钮引脚 (ESP32-S3) - 运行时获取
// 在需要获取按钮引脚的地方使用 board_get_config()->wake_button_gpio

// keepalive 检查计数器
static int s_keepalive_check_counter = 0;
static TickType_t s_last_wakeup_trigger_tick = 0;

#define WAKEUP_TRIGGER_COOLDOWN_MS 3000

// WakeNet 状态（纯 wakenet 接口，无 AFE）
static const esp_wn_iface_t *s_wakenet = NULL;      // WakeNet 接口
static model_iface_data_t *s_wakenet_data = NULL;   // WakeNet 实例（激活缓冲，~80KB）
static srmodel_list_t *s_models = NULL;
static const char *s_model_name = NULL;             // 模型名（指向 s_models 内部）
static volatile bool s_wakenet_paused = false;
static volatile bool s_wakenet_reading = false;  // 标记是否正在读取 I2S
static i2s_chan_handle_t s_wakenet_mic_handle = NULL;
static i2s_chan_handle_t s_spk_tx_handle = NULL;  // ES8311 全双工方案的 TX 句柄
static SemaphoreHandle_t s_i2s_mutex = NULL;
// I2S 互斥锁代持标志：wakeup_pause 拿锁后会话期间一直持有；ASR 结束
// （audio_mic_stop）时经 wakeup_i2s_mutex_release 释放开启"TTS 打断窗口"，
// 下一轮 ASR（audio_mic_start）前 wakeup_i2s_mutex_reacquire 重新拿锁。
static bool s_pause_holding_mutex = false;

// VAD 实时打断待处理标志。打断和唤醒词共用 WAKEUP_TRIGGERED_BIT，但会话语义不同：
// 触发打断时用户的话已经在说了，服务端必须立刻开麦；先播唤醒问候语（实测 1.4~2.1 秒）
// 会把他这半句话吃掉，表现为"打断后只回我在呢、我说话它收不到音"。
// handle_wakeup() 用 wakeup_take_barge_in() 取走并清零。
static volatile bool s_barge_in_pending = false;

// 实时打断开关（服务端管理后台可配 vad_barge_in_enabled，NVS "esp-ai-kv"/"barge_in" 持久化）。
// false = afe_task 的 VAD 打断整链关闭，仅保留唤醒词打断（旧版行为）。默认 true。
// 加载与 setter 见文件尾 wakeup_load_barge_in_enabled / wakeup_set_barge_in_enabled。
static volatile bool s_barge_in_enabled = true;

// 打断→开麦交接窗（见 config.h 声明处）：窗口里 afe_task 继续读麦克风并把 AEC 输出
// 存进预缓冲，audio_mic_start() 收棒时关闭；超过预缓冲长度再读下去也只是覆盖。
static volatile bool s_bargein_handoff = false;
static volatile TickType_t s_bargein_handoff_tick = 0;

#if defined(WAKEUP_USE_AFE)
// ==================== AFE 管线状态（S3：AEC+VAD+WakeNet）====================
static const esp_afe_sr_iface_t *s_afe_handle = NULL;  // AFE 接口
static afe_config_t *s_afe_cfg = NULL;                 // AFE 配置（create_from_config 读取）
static esp_afe_sr_data_t *s_afe_data = NULL;           // AFE 实例

// 扬声器参考信号环形缓冲（AEC 参考通道）
// audio.c 每写一次 I2S 推送实际播放的 16kHz 数据（音量/淡入处理后），
// AFE feed 时与麦克风数据交织成 "MR" 格式喂给 AEC。
// 【用绝对写位置而不是读写指针】消费端要取"多少毫秒之前推入"的那一段参考，
// 绝对序号让任何滞后量都能直接算出下标，不依赖读写指针的相对快慢（见下方
// 回声延迟自估计）。容量 512ms 必须大于搜索范围上限 240ms + 一帧。
// 【容量必须盖住 TX 队列深度】audio.c 的 TX DMA 是 24 描述符 × 480 样本 = 720ms，
// 服务端推流快于播放速度时队列会被填满，"已写入"与"正在发出"之间最多差 720ms。
// 环只有 512ms 时，抽头位置压根落在环外，互相关搜不到也修不回来（实测残余恒 ~100%）。
#define AEC_REF_RING_SAMPLES 16384   // 1024ms @16kHz，> 720ms 队列 + 128ms 窗 + 余量
static int16_t *s_aec_ref_ring = NULL;
static volatile int s_aec_ref_abs_wr = 0;     // 累计推入样本数（每次会话复位归零）
static volatile int s_aec_ref_abs_valid = 0;  // 环内最旧有效样本的绝对序号
static portMUX_TYPE s_aec_ref_mux = portMUX_INITIALIZER_UNLOCKED;

// 推送扬声器参考信号（audio.c spk_task 调用；写入的是实际进扬声器的 16kHz 单声道 PCM）
void wakeup_spk_ref_push(const int16_t *samples, int num)
{
    if (s_aec_ref_ring == NULL || samples == NULL || num <= 0) return;
    portENTER_CRITICAL(&s_aec_ref_mux);
    for (int i = 0; i < num; i++) {
        s_aec_ref_ring[s_aec_ref_abs_wr % AEC_REF_RING_SAMPLES] = samples[i];
        s_aec_ref_abs_wr++;
    }
    // 只保留最近 RING-1 个样本，更早的已被覆盖、视为无效
    int oldest = s_aec_ref_abs_wr - (AEC_REF_RING_SAMPLES - 1);
    if (s_aec_ref_abs_valid < oldest) s_aec_ref_abs_valid = oldest;
    portEXIT_CRITICAL(&s_aec_ref_mux);
}

// ==================== AEC 参考对齐：发出账本 + 每条流一次标定 ====================
// 【参考的绝对基准】audio.c 起播先把 TX DMA 队列灌满静音（SPK_DMA_PRIME_SAMPLES），
// 之后阻塞写维持队列全满——"写入位置 W"与"正在发出位置"之间恒差一个队列深度；
// 中途欠载时 DMA 发静音，发出位置停在 W。这条不变式是本节全部对齐逻辑的地基。
// 【发出账本】E = min(W, E + 本帧消费的麦克风样本数)：DMA 只要队列非空就严格按
// 16k/s 抽干；队列空时 E 停在 W（auto_clear 发静音，喂全零参考正好对应）。
// 按样本数推进、不按墙钟——serial32：循环耗时 18~52ms 抖动时按墙钟推进会制造
// 8~20ms 的"参考比麦克风新"的负延迟，正抽头滤波器物理上消不掉，只会发散
// （实测输出达麦克风 3 倍、600 个窗反超作废、87.9s 假打断一次）。
// 被丢掉的样本（RX 积压、读失败）由调用方补进账本，时间线不断。
// 【抽头标定，每条流一次】互相关粗搜 + 两窗独立复核 + 置信 ≥0.50 才锁
// （锁错一次整轮报废：serial21 以 0.43 把已收敛的 32ms 改锁 6ms、serial23 以 0.45
// 锁 59ms，两次 AEC 都从消 80~90% 掉到只消 40%）。锁完之后抽头不再移动——
// 细跟/台阶跳变/偏置扫描/提前量复用（serial10~32）每一层都在响应上一层的测量噪声，
// 且每挪一次抽头 = 本底作废 + 重收敛盲区 + 闸门关闭，整层删除。窗长 128ms 是因为
// 32ms 单帧的自相关峰太宽没有唯一下标（±25ms 乱跳）；粗搜摊开跑是因为一帧全扫
// 要 34~38ms > 32ms 数据速率，RX 会积压且量到的"滞后"变成自己的开销（serial28）。
// 【测不到回声就喂全零】全零参考 = AEC 直通（待机即此状态），比喂错位参考安全：
// 错位参考会让自适应滤波自己加能量（实测输出达麦克风 2~3 倍）。发散的处置同此——
// 本流第一次发散允许重新标定一次，第二次直接直通并关闭打断（见 aec_resid_feed）。
// 【抽头偏晚才安全——AEC 的因果性】esp-sr 的 AEC（esp_aec3, filter_length=4）只有
// 正抽头：抽头略晚于真实延迟只是消不干净；偏早需要负抽头（用未来的参考消现在的
// 回声），物理上不可能，滤波只会发散。所以置信不足宁可不锁。
// 【削顶帧不参与一切】削顶是非线性失真，波形已不是参考的线性拷贝：相关峰被削平、
// 线性 AEC 消不掉。增益已在 config.h MIC_GAIN_DB 压到回声不削顶，这里保留检测兜底。
#define AEC_LAG_WIN_SAMPLES  2048   // 互相关窗长（128ms @16kHz = 4 个 AFE 帧）
#define AEC_LAG_MIN_MS          0     // 发出账本对齐后，剩余只是 codec+声学延迟
#define AEC_LAG_MAX_MS        192     // 常规定位范围（codec+声学延迟的量程）
#define AEC_LAG_MAX_EXT_MS    704     // 环 1024ms − 窗 128 − 队列 150 之后再留余量
#define AEC_LAG_EXT_STEP        8     // 高段步长（粗扫，命中后再 1ms 精修）
#define AEC_LAG_COARSE_STEP     4     // 第一段步长（ms）
#define AEC_LAG_REFINE_MS       4     // 第二段精修半径（ms），步长 1
#define AEC_LAG_CONF_MIN   0.50f      // 归一化互相关低于此值 = 没测到回声
#define AEC_LAG_COARSE_EVERY    4     // 粗搜摊开跑（见上），平均开销降到 1/4
#define AEC_LAG_VOTE_GAP        2     // 两票间隔 = 两次粗搜 = 8 帧（256ms），窗内容完全换过
#define AEC_LAG_VOTE_TOL_MS     AEC_LAG_REFINE_MS
#define AEC_LAG_MIN_PEAK     1500     // 窗内峰值低于此值不做延迟估计（只剩噪声）
#define AEC_REF_MIN_PEAK     1500     // 参考峰值低于此值 = 这一刻扬声器基本没出声
// 【还要相对判：本帧参考必须够得上本轮播放的响度】词间停顿和播放尾巴上，
// 窗内求和的分母（早先的响帧）还在，分子里的输出却已带着混响尾和 AFE 管线延迟，
// 比值虚高到 14.5 倍（serial14）。绝对值 1500 拦不住这种窗，必须再看一眼
// "本帧参考相对本轮最响的参考还剩多少"。
#define AEC_REF_LIVE_DIV          4   // 本帧参考峰值 < 本轮最响参考的 1/4 → 本读数作废
#define AEC_LAG_CLIP_LEVEL  32700     // 视为削顶的电平
#define AEC_LAG_CLIP_MAX       16     // 窗内削顶样本多于 16 个（0.8%）就放弃本窗

// ==================== 残余度量与发散（打断判据的读数来源）====================
static int s_aec_resid_pct = 100;      // 实时残余比例（AEC 后/麦克风能量，%，仅诊断）
// 512ms 滑动窗能量累加器（见 aec_resid_feed）
#define AEC_RESID_WIN         16    // 滑动窗帧数（512ms）
// 窗读数的沿用上限：一整窗。超出这个年龄，"上一窗的比值"就作废（见 aec_resid_feed）
#define AEC_WIN_HOLD_MS       (AEC_RESID_WIN * 32)
static float s_aec_win_mic[AEC_RESID_WIN];
static float s_aec_win_out[AEC_RESID_WIN];
static bool s_aec_win_ok[AEC_RESID_WIN];
static int s_aec_win_pos = 0;
static int s_aec_resid_frames = 0;     // 窗内有效帧数（诊断）
static float s_aec_win_ref[AEC_RESID_WIN];   // 窗内参考能量（打断判据的分母）
static float s_aec_win_ratio = 0.0f;   // 窗内 AEC 后能量 / 参考能量（回声本底比的实时值）
static volatile TickType_t s_aec_win_ratio_tick = 0;  // 最近一次"窗攒够有效帧"的出数时刻
static float s_aec_floor_ratio = 0.0f; // 回声本底比：<=0 = 还没学到，闸门不放行
static int s_aec_diverge_frames = 0;   // 连续"滤波发散"帧数（32ms/帧）
static bool s_aec_diverged = false;    // 当前窗是否发散（诊断 + 拦打断）
static int s_aec_recal_used = 0;       // 本流已用的"发散重新标定"次数（上限 1 次）
// 抽头刚锁/重锁后的重收敛盲区：滤波器还在追新路径，读数里混着它自己的暂态，
// 既不进窗也不学本底（语义与被删掉的偏置扫描 AEC_BIAS_SKIP 相同）
#define AEC_TAP_SETTLE_FRAMES  6
static volatile int s_aec_settle_frames = 0;
// RX 积压待丢标志（实现在 afe_task 之前）：开播/发散重测前把麦克风拉回最新采样
static bool s_rx_drain_req = false;

// ── 打断判据：AEC 后能量 相对 参考能量 的本底比 ─────────────────────────
// 【为什么废弃残余比例闸门】残余 = AEC后能量/麦克风能量。用户真的开口时，分子分母
// 同时被他的人声主导，比值必然趋近 100%——这个判据专在"他在说话"这一刻关门。
// 实测 serial10：对着 TTS 连续喊 6.7 秒，残余 79~104%，闸门一次都没开。
// 【归一化到参考才是对的】回声是唯一"由参考决定"的成分：TTS 响 10dB，AEC 漏下来的
// 回声残余也跟着响 10dB，两者之比不动；能把这个比值抬上去的，只有参考解释不了的
// 麦克风能量，也就是真人。于是判据变成"窗内比值 ≥ 回声本底比 × AEC_VOICE_MARGIN_PCT"。
// 归一化顺带抵消了 TTS 自身的音量起伏（词间 10~15dB 动态）——绝对能量本底做不到
// 这一点：一个轻声词就把本底拉到极低，下一个重音自己触发打断（"TTS 一开口就打断
// 自己"那个老事故就是这么来的）。
// 本底放开速度：比打断确认（连续 5 帧 = 160ms）慢一个量级（5 帧只涨 1%），
// 又能在一句话的工夫（约 3.5 秒翻倍）从一次误采的过低本底里恢复。
#define AEC_FLOOR_RISE        1.002f
// 【阈值 4 倍→2.5 倍：被 serial13 的实测数字逼出来的，不是放宽标准】
// 那轮 AEC 本身已经是好的（滞后锁 27ms、置信 0.63、残余 3%、无发散无削顶），
// 他对着 1.4 秒的问候语开口，输出/参考只从本底 1.2% 抬到 3.5% = 2.9 倍，正卡在
// 4 倍门下被拦。按 margin = 1 + V/(c·E) 反解：他的人声能量只有回声漏出量的 1.9 倍
// （在麦克风口上比自家回声低约 17dB）。4 倍等于要求他比当时再响 3.5dB。
// 但"再低就会自打断"这件事我没有数据支撑——整轮播放期间从没采过"他不说话时这个
// 比值能漂到几倍"的对照分布。所以这一轮同时把分布记下来（见 s_margin_hist）：
// 下一轮的阈值由两组的重叠程度定，不再靠猜。
#define AEC_VOICE_MARGIN_PCT    250   // 窗内比值 ≥ 本底 ×2.5（+4dB）判为真人语音
#define AEC_DIVERGE_PCT         200   // AEC 后能量超麦克风 2 倍 = 抽头偏早、滤波发散
// 【按帧持续，不按"窗"】旧版写"连续 3 窗"，代码里却是每帧 +1：三帧 ≈96ms 就作废。
// serial26 实测 60ms 锁定后 0.29s 就被判发散、改锁 23ms，随后偏置扫描在没有有效样本的
// 情况下选了个 +96（仅 84% 残余），再次发散，整条流再没锁上——这不是滤波坏了，是
// 滤波器还没收敛（抽头一跳，esp-sr 要几百毫秒才跟上）。闸门仍逐帧判断（发散期间不许
// 打断），但"处置发散"必须等持续 1.5 秒的发散，才值得付那一次的钱。
// 【发散的处置不再是"重扫追赶"】发散 = 输出持续反超麦克风 = 抽头错位/滤波在给自己
// 加能量，此时一切读数（比值、VAD）都是滤波器自己的振荡。处置：本流第一次发散
// 允许重新标定一次（粗搜两票流程原样再走一遍），第二次直接参考置零（直通）并关闭
// 打断。重扫、挪抽头、重学本底的连锁成本在 serial10~32 里反复验证过，不再付。
#define AEC_DIVERGE_HOLD_FRAMES 48

// 窗内帧作废：窗里混着两个抽头状态下的帧时，比值没有物理意义，整窗清空重攒
static void aec_win_epoch_break(void)
{
    s_aec_win_ratio = 0.0f;
    s_aec_resid_frames = 0;
    for (int i = 0; i < AEC_RESID_WIN; i++) s_aec_win_ok[i] = false;
}

// 抽头换位置了：本底比和窗读数一起作废，再给滤波器留重收敛盲区。
// 粗搜锁定、发散重新标定都必须走这里——少走一个，就是 serial16 那种"几处口径不一致"的事故。
static void aec_tap_moved(const char *why)
{
    bool had_reading = s_aec_floor_ratio > 0.0f || s_aec_win_ratio > 0.0f;
    s_aec_floor_ratio = 0.0f;
    aec_win_epoch_break();
    s_aec_settle_frames = AEC_TAP_SETTLE_FRAMES;
    if (had_reading) {   // 首轮还没有任何旧读数可作废，别报这条
        ESP_LOGW(TAG, "抽头变化(%s)：本底作废，%d 帧内读数不进窗",
                 why, AEC_TAP_SETTLE_FRAMES);
    }
}

// ── 打断余量分布（本轮唯一要拿的对照数据）─────────────────────────────
// 整段播放期间，每帧把"超本底倍数"按 AFE 的 vad 状态分成两组累计：
//   静音组 = 纯回声（他自己能漂多高 = 阈值的假阳下界）
//   人声组 = 回声 + 真人（他能到多高 = 阈值的真阳上界）
// 两组不重叠 → 阈值就画在重叠区外面；重叠 → 说明这个判据在这台机器上分不开，
// 得换物理量（降播放音量抬高 V/E、或换抑制档），而不是继续挪阈值。
// 【serial14 的教训：vad 不能当"他没说话"的代理】第二段播放他基本没出声，
// 42 帧里仍有 40 帧 vad=1——回声漏出量自己就能把 AFE 的 VAD 顶成人声态。
// 所以真正的对照只能靠指令分：一段全程闭嘴、一段中途开口，两组分布按"第几轮播放"
// 对齐服务端那边有没有转写出字来判读。
#define MARGIN_BUCKETS            7
static const float s_margin_edges[MARGIN_BUCKETS - 1] = {1.2f, 1.5f, 2.0f, 2.5f, 3.0f, 4.0f};
static int   s_margin_hist[2][MARGIN_BUCKETS];  // [0]=vad 静音 [1]=vad 人声
static int   s_margin_frames[2];
static float s_margin_max[2];
static float s_floor_min = 0.0f, s_floor_max = 0.0f;  // 本底在整段播放里的漂移
static int   s_dup_trigger;      // 上一次打断还挂着又被判出的触发数（本轮拦截了多少次）
static int   s_win_void;         // 输出能量反超麦克风被作废的窗数（仪器故障，不是人声）

static void margin_reset(void)
{
    memset(s_margin_hist, 0, sizeof(s_margin_hist));
    memset(s_margin_frames, 0, sizeof(s_margin_frames));
    memset(s_margin_max, 0, sizeof(s_margin_max));
    s_floor_min = 0.0f;
    s_floor_max = 0.0f;
    s_dup_trigger = 0;
    s_win_void = 0;
}

// 只统计"窗里确实攒够有效帧、本底已学到"的读数，否则采到的是上一窗的余量
static void margin_feed(float margin, float floor_ratio, bool vad_speech)
{
    if (!(margin > 0.0f) || !(floor_ratio > 0.0f)) return;
    int g = vad_speech ? 1 : 0;
    int b = 0;
    while (b < MARGIN_BUCKETS - 1 && margin >= s_margin_edges[b]) b++;
    s_margin_hist[g][b]++;
    s_margin_frames[g]++;
    if (margin > s_margin_max[g]) s_margin_max[g] = margin;
    float floor_pct = floor_ratio * 100.0f;
    if (s_floor_min <= 0.0f || floor_pct < s_floor_min) s_floor_min = floor_pct;
    if (floor_pct > s_floor_max) s_floor_max = floor_pct;
}

static void margin_report(void)
{
    if (s_margin_frames[0] + s_margin_frames[1] == 0) return;
    ESP_LOGI(TAG, "打断余量分布: 本底漂移%.1f~%.1f%% 阈值=%.1f倍",
             s_floor_min, s_floor_max, AEC_VOICE_MARGIN_PCT / 100.0f);
    for (int g = 0; g < 2; g++) {
        ESP_LOGI(TAG, "  %s %d帧 max=%.1f倍: <1.2:%d 1.2:%d 1.5:%d 2:%d 2.5:%d 3:%d >=4:%d",
                 g == 0 ? "无人声" : "人声", s_margin_frames[g], s_margin_max[g],
                 s_margin_hist[g][0], s_margin_hist[g][1], s_margin_hist[g][2],
                 s_margin_hist[g][3], s_margin_hist[g][4], s_margin_hist[g][5],
                 s_margin_hist[g][6]);
    }
    // 重复触发拦截 / 反超作废窗：读日志时分清"拦了假的"和"仪器故障"
    ESP_LOGI(TAG, "  记账: 重复触发拦截=%d 反超作废窗=%d",
             s_dup_trigger, s_win_void);
}

static volatile int s_aec_lag_ms = 180;  // 当前采用的滞后；180ms 是旧固定抽头值
static float s_aec_lag_conf = 0.0f;      // 最近一次置信度
static bool s_aec_lag_valid = false;     // 置信度达标才真正输出参考
static bool s_aec_lag_coarse = true;     // 本轮播放还没粗搜成功
static int s_aec_lag_vote_ms = -1;       // 粗搜第一票的滞后（-1 = 还没投票）
static float s_aec_lag_vote_conf = 0.0f; // 第一票的置信（诊断用）
static int s_aec_lag_vote_age = 0;       // 第一票之后过了几帧（凑够间隔才收第二票）
static int s_aec_coarse_tick = 0;        // 粗搜帧计数（每 AEC_LAG_COARSE_EVERY 帧才真扫一次）
static int s_aec_log_tick = 0;
static int s_aec_search_log_tick = 0;     // 粗搜"没达门"诊断的限流计数
static volatile int s_aec_ref_peak = 0;  // 本帧送给 AEC 的参考峰值
static int s_aec_ref_peak_play = 0;      // 本轮播放里最响的参考峰值（相对活性判据的尺子）
static float s_aec_ref_e_play = 0.0f;    // 本轮播放里最响的参考能量（分母口径的同一把尺子）
// 本帧参考环位置快照：估计与取数共用同一个 w，避免两阶段之间漂移
static int s_aec_ref_w = 0;
static int s_aec_ref_valid = 0;
// 本帧真正喂给 AEC 的参考能量（样本平方和，与麦克风/AEC 后同域）——打断判据的分母
static float s_aec_ref_e = 0.0f;
// 发出账本：此刻麦克风正在听的那段时间里，DAC 送到喇叭的样本在写入流里的绝对序号
// （见本节开头的设计说明）。推进量 = 本帧真正消费掉的麦克风样本数，不用墙钟。
// 诊断行里的「队列」= W − E，现在等于 TX 队列 + RX 积压（E 落后墙钟的量），
// 不再是纯 TX 队列深度。
static int s_aec_emit = 0;
// 本条播放流开始时（或账本被重置时）的发出位置。互相关窗的参考下限不能早于这里：
// serial26 实测新流开头参考环里还留着上一条流的尾巴，第一票投在了一段不属于本条流的
// 参考上（0.63 置信！），锁出来的滞后比真值大，抽头一落就发散。
static int s_aec_stream_emit0 = 0;
static bool s_aec_tx_live = false;   // 本帧 DMA 确实在发出参考（队列非空）
static uint32_t s_aec_tx_epoch = 0;  // audio.c 的 TX 队列代际号，变了说明队列被冲掉
// 互相关用的麦克风滑动窗（最近 128ms），只在 afe_task 里访问
static int16_t s_aec_mic_win[AEC_LAG_WIN_SAMPLES];
static int s_aec_win_fill = 0;
static int s_aec_clip_cnt = 0;     // 最近一窗的削顶样本数（诊断）
// AEC 输出滑动窗（最近 128ms）：回答"这半秒 AEC 后的能量是谁的"。
// 回声漏出的能量是参考波形的延迟拷贝，和参考做互相关会出峰；真人说话则与参考无关。
// serial29 的假打断就是丢掉了这个区分：AEC 后能量抬到 9.3~11.9 倍看似人声，
// 实际是自家 TTS 的漏出（服务端 ASR 转出的正是 TTS 原文"他不摆摊"）。
static int16_t s_aec_out_win[AEC_LAG_WIN_SAMPLES];
static int s_aec_out_fill = 0;

// 麦克风帧读完后调用一次：同步写位置快照，并把发出账本按本帧消费的样本数推进。
// 【必须先查代际号】audio.c 在打断/换采样率时 disable TX 通道，驱动会把已排队
// 未发出的样本整段丢掉——那段账再也对不上，只能重新起账（重新粗搜、重新扫偏置）。
//
// 【为什么按样本数推进，不按墙钟】serial32 实测：同一条流里循环耗时「算」在
// 18~52ms 之间抖，麦克风数据却固定 32ms/帧到——循环慢一帧，麦克风就比墙钟多积压
// 8~20ms。按墙钟推进时账本照走，喂给 AEC 的参考瞬间比麦克风新 8~20ms（负延迟，
// 只有正抽头的滤波器物理上消不掉）：那次锁 48ms 后首帧残余 22%，随即 80%→300%、
// 「AEC后 > 麦克风」刷屏、600 个 512ms 窗因反超作废，87.9s 还靠 AEC 自己加出来的
// 能量尖峰（窗内逐帧 302%/280%）假打断一次，服务端 5s 无有效语音。
// 按样本数推进后，参考与麦克风在样本域严格同速，循环快慢、积压抖动都不再改变两者的
// 相对对齐。被丢掉的样本（丢 RX 积压、读失败丢半帧）在调用方补进账本，时间线不断。
static void aec_ref_reset(void);

static void aec_ref_snapshot(int num)
{
    if (audio_spk_tx_epoch() != s_aec_tx_epoch) {
        aec_ref_reset();
    }
    portENTER_CRITICAL(&s_aec_ref_mux);
    s_aec_ref_w = s_aec_ref_abs_wr;
    s_aec_ref_valid = s_aec_ref_abs_valid;
    portEXIT_CRITICAL(&s_aec_ref_mux);

    int e = s_aec_emit + num;
    if (e > s_aec_ref_w) e = s_aec_ref_w;   // 队列被抽干：DMA 在发静音，发出位置原地不动
    s_aec_emit = e;
    // 队列里还有没放完的样本 = DMA 确实在出声；按队列深度判，不受帧间隔抖动影响
    s_aec_tx_live = num > 0 && (s_aec_ref_w - e) > 0;
}

// 环上 [abs_base, +num) 抄送进 dst（调用方已保证该区间仍在有效历史内）
static void aec_ring_copy(int16_t *dst, int num, int abs_base)
{
    int p = abs_base % AEC_REF_RING_SAMPLES;
    int head = AEC_REF_RING_SAMPLES - p;
    if (head > num) head = num;
    for (int i = 0; i < head; i++) dst[i] = s_aec_ref_ring[p + i];
    for (int i = head; i < num; i++) dst[i] = s_aec_ref_ring[i - head];
}

// mic 与环上 [abs_base, +num) 的相关值；*out_ref_e 带回该窗口参考能量（归一化分母）
static float aec_corr(const int16_t *mic, int num, int abs_base, float *out_ref_e)
{
    int p = abs_base % AEC_REF_RING_SAMPLES;
    int head = AEC_REF_RING_SAMPLES - p;
    if (head > num) head = num;
    float s = 0, e = 0;
    for (int i = 0; i < head; i++) { float r = s_aec_ref_ring[p + i]; s += (float)mic[i] * r; e += r * r; }
    for (int i = head; i < num; i++) { float r = s_aec_ref_ring[i - head]; s += (float)mic[i] * r; e += r * r; }
    *out_ref_e = e;
    return s;
}

// 在 [lo_ms, hi_ms] 内按 step_ms 找与麦克风窗最对齐的参考滞后（窗固定 128ms）
static int aec_lag_search(int lo_ms, int hi_ms, int step_ms, float win_e, float *out_conf)
{
    // 【历史刚攒够时不许贴着边界锁】播放开头参考历史还不够深，高滞后那一段
    // 只能取到很少的样本，窗内相关峰是残缺的。给它留 8ms 余量，不够就不搜，
    // 否则第一条流的头两窗会把"可搜范围内的假峰"投成正式票（票一旦一致就锁死）。
    // 下限取"环有效起点"和"本条流起点"的较大者：暂停期间参考环里留着上一条流的
    // 尾巴，只用 ref_valid 挡不住它。
    int hist_floor = s_aec_ref_valid > s_aec_stream_emit0 ? s_aec_ref_valid : s_aec_stream_emit0;
    int avail_ms = (s_aec_emit - AEC_LAG_WIN_SAMPLES - hist_floor) / 16 - 8;
    if (hi_ms > avail_ms) hi_ms = avail_ms;
    if (hi_ms < lo_ms) { *out_conf = 0.0f; return -1; }
    int best = -1;
    float best_c = 0, best_re = 1.0f;
    for (int ms = lo_ms; ms <= hi_ms; ms += step_ms) {
        int base = s_aec_emit - AEC_LAG_WIN_SAMPLES - ms * 16;
        if (base < s_aec_ref_valid) continue;   // 历史已被覆盖/播放刚开始还没攒够
        float re;
        float c = aec_corr(s_aec_mic_win, AEC_LAG_WIN_SAMPLES, base, &re);
        if (c < 0) c = -c;
        if (c > best_c) { best_c = c; best_re = re; best = ms; }
    }
    if (best < 0) { *out_conf = 0.0f; return -1; }
    float denom = sqrtf(win_e * best_re);
    *out_conf = denom > 1.0f ? best_c / denom : 0.0f;
    return best;
}

// 粗搜：4ms 步长全扫一遍，再在最优点 ±4ms 内以 1ms 精修（一次相关 2048 乘加）
// 最优点顶到常规定位范围上沿时，继续往高扫一段：起播相位可能把回声推到 192ms 之外，
// 那种流在常规范围内只会找到个低相关的假峰（把抽头锁在回声前面 = 直接发散）。
static int aec_lag_coarse(float win_e, float *out_conf)
{
    float c1 = 0;
    int best = aec_lag_search(AEC_LAG_MIN_MS, AEC_LAG_MAX_MS, AEC_LAG_COARSE_STEP, win_e, &c1);
    *out_conf = c1;
    if (best < 0) return -1;
    if (best >= AEC_LAG_MAX_MS - AEC_LAG_COARSE_STEP) {
        float c3 = 0;
        int ext = aec_lag_search(AEC_LAG_MAX_MS + AEC_LAG_EXT_STEP, AEC_LAG_MAX_EXT_MS,
                                 AEC_LAG_EXT_STEP, win_e, &c3);
        if (ext >= 0 && c3 > *out_conf) { best = ext; *out_conf = c3; }
    }
    float coarse_conf = *out_conf;
    int lo = best - AEC_LAG_REFINE_MS;
    int hi = best + AEC_LAG_REFINE_MS;
    if (lo < AEC_LAG_MIN_MS) lo = AEC_LAG_MIN_MS;
    if (hi > AEC_LAG_MAX_EXT_MS) hi = AEC_LAG_MAX_EXT_MS;
    float c2 = 0;
    int fine = aec_lag_search(lo, hi, 1, win_e, &c2);
    if (fine >= 0 && c2 >= coarse_conf) *out_conf = c2;
    else fine = best;
    return fine;
}

// 本帧麦克风进滑动窗：窗内始终保留最近 128ms，右端就是最新一帧
static void aec_win_append(const int16_t *mic, int num)
{
    if (num <= 0) return;
    if (num >= AEC_LAG_WIN_SAMPLES) {   // 帧比窗还长（当前 AFE 不会），只留最新一段
        memcpy(s_aec_mic_win, mic + num - AEC_LAG_WIN_SAMPLES,
               AEC_LAG_WIN_SAMPLES * sizeof(int16_t));
        s_aec_win_fill = AEC_LAG_WIN_SAMPLES;
        return;
    }
    int keep = AEC_LAG_WIN_SAMPLES - num;
    if (s_aec_win_fill > keep) {
        memmove(s_aec_mic_win, s_aec_mic_win + (s_aec_win_fill - keep),
                keep * sizeof(int16_t));
        s_aec_win_fill = keep;
    }
    memcpy(s_aec_mic_win + s_aec_win_fill, mic, num * sizeof(int16_t));
    s_aec_win_fill += num;
}

// 本帧 AEC 输出进滑动窗：窗内始终保留最近 128ms，右端就是最新一帧
static void aec_out_win_append(const int16_t *out, int num)
{
    if (out == NULL || num <= 0) return;
    if (num >= AEC_LAG_WIN_SAMPLES) {   // 帧比窗还长（当前 AFE 不会），只留最新一段
        memcpy(s_aec_out_win, out + num - AEC_LAG_WIN_SAMPLES,
               AEC_LAG_WIN_SAMPLES * sizeof(int16_t));
        s_aec_out_fill = AEC_LAG_WIN_SAMPLES;
        return;
    }
    int keep = AEC_LAG_WIN_SAMPLES - num;
    if (s_aec_out_fill > keep) {
        memmove(s_aec_out_win, s_aec_out_win + (s_aec_out_fill - keep),
                keep * sizeof(int16_t));
        s_aec_out_fill = keep;
    }
    memcpy(s_aec_out_win + s_aec_out_fill, out, num * sizeof(int16_t));
    s_aec_out_fill += num;
}

// AEC 输出与参考的最大归一化互相关：≥ AEC_LAG_CONF_MIN 就是"这窗能量还是自家回声"。
// 人声在 AEC 输出里和参考没有相关峰，只有漏出的回声有；所以这个数不需要另立门限，
// 沿用锁定滞时时已经在用的同一个置信度门（0.50 = 测到回声）。
// 输出帧比麦克风帧晚若干个块，绝对时基对不上，延迟量本身由搜索吸收（0~704ms 同上）。
// 返回 <0 = 没法判断（参考没在出声 / 输出窗没攒满 / 输出是静音）——此时不拦。
static float aec_out_echo_conf(void)
{
    if (s_aec_out_fill < AEC_LAG_WIN_SAMPLES || s_aec_ref_ring == NULL || !s_aec_tx_live)
        return -1.0f;
    float win_e = 0;
    for (int i = 0; i < AEC_LAG_WIN_SAMPLES; i++) {
        float v = (float)s_aec_out_win[i];
        win_e += v * v;
    }
    if (win_e <= 0.0f) return -1.0f;
    int hist_floor = s_aec_ref_valid > s_aec_stream_emit0 ? s_aec_ref_valid : s_aec_stream_emit0;
    int avail_ms = (s_aec_emit - AEC_LAG_WIN_SAMPLES - hist_floor) / 16 - 8;
    int hi = avail_ms < AEC_LAG_MAX_EXT_MS ? avail_ms : AEC_LAG_MAX_EXT_MS;
    float best = 0.0f;
    for (int ms = 0; ms <= hi; ms += AEC_LAG_COARSE_STEP) {
        int base = s_aec_emit - AEC_LAG_WIN_SAMPLES - ms * 16;
        if (base < s_aec_ref_valid) continue;
        float re;
        float c = aec_corr(s_aec_out_win, AEC_LAG_WIN_SAMPLES, base, &re);
        if (c < 0) c = -c;
        float denom = sqrtf(win_e * re);
        if (denom > 1.0f) {
            float conf = c / denom;
            if (conf > best) best = conf;
        }
    }
    return best;
}

// 每帧在取参考之前调用（仅播放期间）：每条流开始时标定一次回声延迟（两窗投票），
// 锁定后不再动抽头——细跟/台阶跳变/偏置扫描已整层删除，见本节开头的设计说明。
static void aec_lag_update(const int16_t *mic, int num)
{
    aec_win_append(mic, num);
    if (!s_aec_lag_coarse) return;                      // 已锁定：抽头不再动
    if (s_aec_win_fill < AEC_LAG_WIN_SAMPLES) return;   // 窗还没攒满，相关信息量不够

    int peak = 0, clip = 0;
    float win_e = 0;
    for (int i = 0; i < AEC_LAG_WIN_SAMPLES; i++) {
        int v = s_aec_mic_win[i] < 0 ? -s_aec_mic_win[i] : s_aec_mic_win[i];
        if (v > peak) peak = v;
        if (v >= AEC_LAG_CLIP_LEVEL) clip++;
        win_e += (float)s_aec_mic_win[i] * (float)s_aec_mic_win[i];
    }
    s_aec_clip_cnt = clip;
    if (peak < AEC_LAG_MIN_PEAK) return;   // 太安静：相关结果全是噪声
    if (clip > AEC_LAG_CLIP_MAX) return;   // 削顶太多：非线性，相关峰不可信

    // 摊开跑：见 AEC_LAG_COARSE_EVERY。非搜索帧直接返回，互相关窗照样每帧更新，
    // 所以两次搜索之间窗内容始终是最新的。
    if (++s_aec_coarse_tick < AEC_LAG_COARSE_EVERY) return;
    s_aec_coarse_tick = 0;
    float conf = 0.0f;
    int lag = aec_lag_coarse(win_e, &conf);
    if (lag < 0 || conf < AEC_LAG_CONF_MIN) {
        // 没达门也要出数：光看"被拦截"分不清是没测到（lag<0）、置信不够（conf 多少）、
        // 还是根本没跑（tx 欠载）。每 16 次搜索打一条，够判读又不刷屏。
        if ((s_aec_search_log_tick++ % 16) == 0) {
            ESP_LOGI(TAG, "粗搜未达门: 最佳=%dms 置信=%.2f 流内=%dms 队列=%dms 峰值=%d 削顶=%d",
                     lag, conf, (s_aec_emit - s_aec_stream_emit0) / 16,
                     (s_aec_ref_w - s_aec_emit) / 16, peak, clip);
        }
        return;   // 测不准就保持"未对齐"（参考置零）
    }

    // 粗搜锁定前必须两窗独立复核：单个 128ms 窗的相关峰仍可能落到错误峰上，
    // 而锁错一次就整轮 AEC 报废（serial21/23）
    if (s_aec_lag_vote_ms < 0) {
        s_aec_lag_vote_ms = lag;
        s_aec_lag_vote_conf = conf;
        s_aec_lag_vote_age = 0;
        ESP_LOGI(TAG, "粗搜投票 1: %dms (置信=%.2f 削顶=%d)，等第二窗复核",
                 lag, conf, clip);
        return;
    }
    if (++s_aec_lag_vote_age < AEC_LAG_VOTE_GAP) return;
    int diff = lag - s_aec_lag_vote_ms;
    if (diff < 0) diff = -diff;
    if (diff > AEC_LAG_VOTE_TOL_MS) {
        // 两个独立窗指向不同的峰：谁都不信，以较新的窗重新起票
        ESP_LOGW(TAG, "粗搜投票不一致: 上窗 %dms(置信=%.2f) 本窗 %dms(置信=%.2f)，以本窗重投",
                 s_aec_lag_vote_ms, s_aec_lag_vote_conf, lag, conf);
        s_aec_lag_vote_ms = lag;
        s_aec_lag_vote_conf = conf;
        s_aec_lag_vote_age = 0;
        return;
    }
    ESP_LOGI(TAG, "粗搜投票 2: %dms (置信=%.2f)，与上窗 %dms 一致（间隔 %d 帧）",
             lag, conf, s_aec_lag_vote_ms, s_aec_lag_vote_age);
    s_aec_lag_vote_ms = -1;
    // 粗搜锁定：抽头一次性到位，之后不再动
    s_aec_lag_ms = lag;
    s_aec_lag_coarse = false;
    s_aec_lag_conf = conf;
    s_aec_lag_valid = true;
    // 【每条流锁完都要重学本底】锁定前参考是零、那几帧不进窗，锁定后滤波器才从
    // 零开始收敛；旧本底代表的是上一个抽头状态，沿用只会虚高/虚低。
    // 本底清零 + 留重收敛盲区，代价只是闸门晚开半秒。
    aec_tap_moved("本轮新量");
    ESP_LOGI(TAG, "回声延迟锁定: %dms (置信=%.2f 削顶=%d 队列=%dms)，抽头=%dms",
             lag, conf, clip, (s_aec_ref_w - s_aec_emit) / 16, s_aec_lag_ms);
}

// 取出 num 个参考样本：按"发出位置 + 实测回声延迟"从环上定位；不可信时补零（AEC 直通）
// 【基准是发出账本 E，不再是写入位置 W】E 逐帧严格 +chunksize，所以参考与麦克风
// 同速前进，两者之差只剩 codec+声学这一个常数——这才是 AEC 能消的东西。
// 【队列抽干时喂零】E 停在 W 不动的那些帧，DMA 正在发静音（auto_clear），
// 补零与真实出声一致；上一版拿 audio_spk_is_playing() 当闸门，播放尾巴（队列里
// 还有几百 ms 没放完）被强制清零，等于让设备在自己的尾音里"听见"用户说话。
// 【抽头必须是实测滞后，不能写死 0】serial31 抽头 0 时整轮残余 50~256%＝AEC 没消、
// 输出反复反超麦克风；抽头 0 等于让 AEC 去消一段"未来"的回声（负抽头），线性滤波
// 只能发散。未标定时补零直通：喂位置不对的参考只会让它自己加能量。
static void aec_ref_pop(int16_t *dst, int num)
{
    int tap_ms = s_aec_lag_ms;
    int base = s_aec_emit - num - tap_ms * 16;   // 16kHz：1ms = 16 样本（与本文其余相关窗一致）
    if (!s_aec_lag_valid || !s_aec_tx_live || s_aec_ref_ring == NULL
        || base < s_aec_ref_valid) {
        memset(dst, 0, num * sizeof(int16_t));
        s_aec_ref_peak = 0;
        s_aec_ref_e = 0.0f;
        return;
    }
    aec_ring_copy(dst, num, base);
    int peak = 0;
    float e = 0.0f;
    for (int i = 0; i < num; i++) {
        int v = dst[i] < 0 ? -dst[i] : dst[i];
        if (v > peak) peak = v;
        e += (float)dst[i] * (float)dst[i];
    }
    s_aec_ref_peak = peak;
    s_aec_ref_e = e;
}

// 清空参考环（会话暂停期间积压的旧参考已过期，resume 时丢弃）
// 【滞后每条播放流重测】起播相位已由 audio.c 灌满 DMA 队列固定下来，但账本起点
// 仍跟每条流的开始走；重测只要两窗、约 0.3 秒，代价远小于锁错的代价。
// 两窗投票 + 置信 0.50 的门沿用 serial21/23 的教训。
static void aec_ref_reset(void)
{
    portENTER_CRITICAL(&s_aec_ref_mux);
    s_aec_ref_abs_wr = 0;
    s_aec_ref_abs_valid = 0;
    portEXIT_CRITICAL(&s_aec_ref_mux);
    s_aec_ref_w = 0;
    s_aec_ref_valid = 0;
    s_aec_ref_peak = 0;
    s_aec_ref_e = 0.0f;
    s_aec_ref_e_play = 0.0f;
    // 账本重新起：写入位置归零，发出位置跟着归零，并记下当前 TX 代际号
    s_aec_emit = 0;
    s_aec_stream_emit0 = 0;   // 账本重置 = 参考的同一条基线从这里重新算
    s_aec_tx_live = false;
    s_aec_tx_epoch = audio_spk_tx_epoch();
    s_aec_lag_coarse = !s_aec_lag_valid;   // 已有可用滞后就沿用，只有真凭据才重扫
    s_aec_lag_vote_ms = -1;                // 新一次粗搜从空票箱起
    s_aec_recal_used = 0;                  // 发散重新标定的额度也重新计
    if (!s_aec_lag_coarse) {
        ESP_LOGI(TAG, "沿用上一轮回声滞后 %dms（本轮不重扫）", s_aec_lag_ms);
    }
    s_aec_coarse_tick = 0;
    s_aec_win_fill = 0;
    s_aec_clip_cnt = 0;
    s_aec_resid_pct = 100;
    s_aec_resid_frames = 0;
    s_aec_win_pos = 0;
    s_aec_win_ratio = 0.0f;
    s_aec_diverged = false;
    s_aec_diverge_frames = 0;
    for (int i = 0; i < AEC_RESID_WIN; i++) {
        s_aec_win_ok[i] = false;
        s_aec_win_ref[i] = 0.0f;
    }
    // 兜底：无论 AEC 被什么路径关掉过，重置时都恢复使能
    if (s_afe_handle != NULL && s_afe_data != NULL) {
        s_afe_handle->enable_aec(s_afe_data);
    }
}

// ==================== 残余回声度量 ====================
// 残余比例 = AEC 后能量 / 麦克风能量，只作为"对齐质量"的诊断读数保留。
// 【必须用能量、而且必须跨窗累加】上一版拿"本帧喂进去的麦克风峰值"去比"本帧
// fetch 出来的输出峰值"，但 fetch 出来的帧比 feed 晚若干个块（VAD 还带 128ms
// 缓存），两个峰值根本不是同一时刻的声音；语音电平一帧之内就差 3 倍，于是残余
// 在 90%~150% 之间乱跳，好坏完全读不出来。改成 16 帧（512ms）滑动窗能量比：
// 两路平均速率相同、只差固定块数，长窗内自动抵消。
// 【参考峰值过低的帧两边都不计】扬声器这一刻没出声，计入会把比值推向 100%。
// 【它不能当打断判据】分母是麦克风，用户一开口分母就被他自己撑大，比值恒趋近
// 100%——详见上文 s_aec_floor_ratio（回声本底比）处的说明；判据改用 输出/参考，
// 这里只留读数。
#define AEC_RESID_MIN_FRAMES   8    // 窗内有效帧不足则不出数

// 每帧一次：维护 512ms 滑动窗能量统计，产出残余读数（诊断）、回声本底比（打断判据）
// 与发散标志。
static void aec_resid_feed(float mic_e, float out_e, float ref_e, bool qualified)
{
    // 【重收敛盲区】抽头刚锁定/重锁的那几帧，滤波器还在追新的回声路径，读数里混着
    // 它自己的暂态——既不进窗也不学本底。
    if (s_aec_settle_frames > 0) {
        s_aec_settle_frames--;
        qualified = false;
    }
    int p = s_aec_win_pos;
    s_aec_win_mic[p] = qualified ? mic_e : 0.0f;
    s_aec_win_out[p] = qualified ? out_e : 0.0f;
    s_aec_win_ref[p] = qualified ? ref_e : 0.0f;
    s_aec_win_ok[p] = qualified;
    s_aec_win_pos = (p + 1) % AEC_RESID_WIN;

    float sm = 0.0f, so = 0.0f, sr = 0.0f;
    int n = 0;
    for (int i = 0; i < AEC_RESID_WIN; i++) {
        if (!s_aec_win_ok[i]) continue;
        sm += s_aec_win_mic[i];
        so += s_aec_win_out[i];
        sr += s_aec_win_ref[i];
        n++;
    }
    s_aec_resid_frames = n;
    if (n >= AEC_RESID_MIN_FRAMES && sm > 0.0f) {
        int pct = (int)(so * 100.0f / sm);
        s_aec_resid_pct = pct > 300 ? 300 : pct;   // 窗本身已够平滑，不再叠 EMA
    }

    // 【发散检测】线性 AEC 理想上只会让输出比麦克风更小（它减掉一个成分）。输出反超
    // 麦克风 = 抽头跑到了回声前面，自适应滤波在给自己加能量。这时 VAD 听到的是
    // 滤波器自己的振荡，拿它判打断毫无意义。闸门按帧就关（s_aec_diverged），但
    // 作废重扫要等持续 1.5 秒：锁定后抽头整个搬家，esp-sr 要几百毫秒才收敛，
    // 收敛过程本身就会让输出短暂反超（serial26：60ms 锁后 0.29s 就作废、改锁 23ms，
    // 再跑了遍没有有效样本的偏置扫描，整条流再没锁上）。
    s_aec_diverged = (n >= AEC_RESID_MIN_FRAMES && sm > 0.0f
                      && so * 100.0f > sm * AEC_DIVERGE_PCT);
    if (s_aec_diverged) {
        if (++s_aec_diverge_frames >= AEC_DIVERGE_HOLD_FRAMES) {
            s_aec_diverge_frames = 0;
            aec_win_epoch_break();
            s_aec_settle_frames = AEC_TAP_SETTLE_FRAMES;
            s_aec_lag_valid = false;   // 参考置零 = 直通，闸门随之关闭
            if (s_aec_recal_used < 1) {
                // 本流第一次发散：允许重新标定一次（两票流程原样再走一遍）
                s_aec_recal_used++;
                s_aec_lag_coarse = true;
                s_aec_coarse_tick = 0;
                s_aec_lag_vote_ms = -1;
                // 发散多半是"麦克风的时间基准变了"（RX 积压涨/塌），重测之前先把
                // 积压丢掉，否则下一次量到的还是一个拖着的旧延迟。
                s_rx_drain_req = true;
                ESP_LOGW(TAG, "AEC 后能量持续 %.1f 秒反超麦克风(输出/麦克风=%d%% 队列=%dms 抽头=%dms)：作废滞后，重新标定（本流第 1 次）",
                         AEC_DIVERGE_HOLD_FRAMES * 0.032f, s_aec_resid_pct,
                         (s_aec_ref_w - s_aec_emit) / 16, s_aec_lag_ms);
            } else {
                // 第二次发散：不再追赶。直通状态下 AEC 不加能、闸门全关，安全但打断关闭；
                // 抓住这一条日志 = 该查 RX 积压/削顶/声学环境，而不是继续调参。
                ESP_LOGW(TAG, "AEC 持续发散，本流剩余时间参考直通、实时打断关闭(队列=%dms 抽头=%dms)",
                         (s_aec_ref_w - s_aec_emit) / 16, s_aec_lag_ms);
            }
        }
    } else {
        s_aec_diverge_frames = 0;
    }

    // 【出数只看窗，不看本帧】serial17 实测打断滞后 2.2 秒，根因就在这里：
    // TTS 句子之间有停顿、他的语音节也有间隙，只要"本帧"参考掉到 1500 以下，
    // 旧代码就把整个窗的读数抹成 0，160ms 的连续计数立刻清零；他连续说 2.7 秒，
    // 窗却反复凑不齐 ≥8 帧有效参考（132230/133751/134278 三次"本窗无有效参考"），
    // 直到 134786 撞上一段响一点的 TTS 才出数——那时他整句话早就说完了。
    // 窗里已有 ≥8 帧各自带有效参考，"这一刻参考是否在出声"就不该再否决整窗；
    // 陈旧读数的防护改由窗龄负责（见 AEC_WIN_HOLD_MS），本底仍只从真·有效帧学习。
    if (n >= AEC_RESID_MIN_FRAMES && sr > 0.0f) {
        // 【线性 AEC 减不出负值】输出能量反超麦克风 = 这半秒里滤波器在给自己加能量
        // （抽头没跟上或参考错位）。这时"输出/参考"读数不是"参考解释不了的人声"，
        // 是仪器故障——作废本窗，也不许它污染本底。真人说话时输出 = 人声+残余回声
        // ≤ 麦克风，永远碰不到这条线。
        if (so > sm) {
            s_win_void++;
            s_aec_win_ratio = 0.0f;
        } else {
            s_aec_win_ratio = so / sr;
            s_aec_win_ratio_tick = xTaskGetTickCount();
        }
    } else {
        // 【读数不存在要显式作废】窗里有效帧不足时，留着上一窗的比值会让闸门
        // 拿陈读数放行——serial13 的 1581210（有效 0 帧却挂着 5.7%、算出 4.6 倍）
        // 就是这一类；窗龄到点即作废，见下面的消费侧。
        s_aec_win_ratio = 0.0f;
    }
    // 【本底 = 本轮播放里见过的最小窗比值，不是第一窗的值，也不是快速跟降的值】
    // 物理依据：输出 = 回声漏出量 + 人声，人声只会往上抬、不会往下压，所以时间的
    // 最小值就是回声漏出量本身。serial13/14 原版"第一窗当种子 + 快降慢升"栽了两次：
    //   serial14 第一轮：种子采在播放开头（滤波器还没收敛、漏得最多）= 4.9%，
    //     之后他一直说话只走"慢升"分支，本底再没下来过 → 他人声实测只到 2.1 倍，
    //     被"语音未超回声本底"拦死；
    //   同一轮第二段播放种子采在收敛之后 = 1.4%。同一个判据两轮本底差 3.5 倍，
    //   说明那个量量的不是回声，是"我从哪一刻开始看"。
    // 放开速度 AEC_FLOOR_RISE 要兼顾两头：比打断确认（5 帧 160ms）慢一个量级，
    // 又要能在几秒内从一次误采的低值里恢复回来。
    if (!s_aec_diverged && qualified
        && n >= AEC_RESID_MIN_FRAMES && sr > 0.0f) {
        float wr = so / sr;
        if (s_aec_floor_ratio <= 0.0f || wr < s_aec_floor_ratio) {
            s_aec_floor_ratio = wr;
        } else {
            s_aec_floor_ratio *= AEC_FLOOR_RISE;
        }
    }
}

#endif

#if !defined(WAKEUP_USE_AFE)
// 纯 WakeNet 路径无 AEC：空实现（audio.c ES8311 播放路径统一调用，AFE 启用后切换为真实现）
void wakeup_spk_ref_push(const int16_t *samples, int num)
{
    (void)samples;
    (void)num;
}
#endif

// 前向声明
extern void websocket_check_keepalive(void);
static void wakeup_apply_det_threshold(void);
static void wakeup_load_det_threshold(void);
static void wakeup_load_barge_in_enabled(void);
// ==================== 按钮唤醒任务（保留原有逻辑）====================

static void button_wakeup_task(void *arg)
{
    ESP_LOGI(TAG, "按钮唤醒任务启动");

    gpio_config_t io_conf = {
        .pin_bit_mask = (1ULL << board_get_config()->wake_button_gpio),
        .mode = GPIO_MODE_INPUT,
        .pull_up_en = GPIO_PULLUP_ENABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type = GPIO_INTR_DISABLE,
    };
    gpio_config(&io_conf);

    int last_state = 1;
    int loop_count = 0;

    // 4 次按键进入配网检测
    const int REPROV_PRESS_THRESHOLD = 4;
    int s_press_count = 0;
    TickType_t s_first_press_tick = 0;

    while (s_wakeup_running) {
        int current_state = gpio_get_level(board_get_config()->wake_button_gpio);

        // 每100次循环打印一次状态（约1秒）
        loop_count++;
        if (loop_count >= 100) {
            ESP_LOGD(TAG, "按钮状态: GPIO%d = %d", board_get_config()->wake_button_gpio, current_state);
            loop_count = 0;

            // 每 1 秒检查一次 keepalive 超时
            s_keepalive_check_counter++;
            if (s_keepalive_check_counter >= 1) {
                s_keepalive_check_counter = 0;
                websocket_check_keepalive();
            }
        }

        // 检查 4 次按键超时重置：如果第一下按键超过 2 秒没有后续，清零
        TickType_t now = xTaskGetTickCount();
        if (s_press_count > 0 && s_press_count < REPROV_PRESS_THRESHOLD) {
            TickType_t since_first = (now - s_first_press_tick) * portTICK_PERIOD_MS;
            if (since_first >= 2000) {
                s_press_count = 0;
                s_first_press_tick = 0;
                ESP_LOGI(TAG, "4次按键超时，计数清零");
            }
        }

        // 检测按钮按下（下降沿）
        if (current_state == 0 && last_state == 1) {
            // OTA 升级期间禁用所有按键操作（唤醒/配网）：写 flash 时被按键打断
            // 可能导致异常会话或干扰升级，升级完成后自动恢复
            if (ota_is_updating()) {
                // 等待按钮释放并消抖
                vTaskDelay(pdMS_TO_TICKS(50));
                while (gpio_get_level(board_get_config()->wake_button_gpio) == 0) {
                    vTaskDelay(pdMS_TO_TICKS(10));
                }
                last_state = 1;
                continue;
            }
            // 更新按键计数（滑动窗口：同一 2s 窗口内计数）
            if (s_press_count == 0) {
                s_first_press_tick = xTaskGetTickCount();
            }
            s_press_count++;

            if (s_press_count >= REPROV_PRESS_THRESHOLD) {
                ESP_LOGW(TAG, "=========================================");
                ESP_LOGW(TAG, "%d次按键检测到，清除配置进入配网!", REPROV_PRESS_THRESHOLD);
                ESP_LOGW(TAG, "=========================================");
                s_press_count = 0;
                s_first_press_tick = 0;

                // 等待按钮释放
                vTaskDelay(pdMS_TO_TICKS(50));
                while (gpio_get_level(board_get_config()->wake_button_gpio) == 0) {
                    vTaskDelay(pdMS_TO_TICKS(10));
                }

                // 清除所有配置并重启
                provisioning_clear_all();
                vTaskDelete(NULL);  // 防御兜底：若 provisioning_clear_all 未重启，任务不能以 return 退出
                return;
            }

            // 正常唤醒触发（单次按键），受冷却限制
            if (s_last_wakeup_trigger_tick != 0) {
                TickType_t elapsed_ms = (now - s_last_wakeup_trigger_tick) * portTICK_PERIOD_MS;
                if (elapsed_ms < WAKEUP_TRIGGER_COOLDOWN_MS) {
                    ESP_LOGW(TAG, "Wakeup ignored: trigger cooldown active (%d/%d ms)",
                             (int)elapsed_ms, WAKEUP_TRIGGER_COOLDOWN_MS);
                    vTaskDelay(pdMS_TO_TICKS(50));
                    while (gpio_get_level(board_get_config()->wake_button_gpio) == 0) {
                        vTaskDelay(pdMS_TO_TICKS(10));
                    }
                    last_state = 1;
                    continue;
                }
            }
            // 表情下载期间禁用唤醒（与语音唤醒一致，避免下载占用内存时
            // 唤醒/播放分配失败导致异常会话）。放在冷却计时之前：
            // 忽略的唤醒不启动 8 秒冷却，下载完成后可立即唤醒。
            if (gif_download_is_busy()) {
                static TickType_t s_last_ignored_btn = 0;
                TickType_t now_t2 = xTaskGetTickCount();
                if ((now_t2 - s_last_ignored_btn) * portTICK_PERIOD_MS > 5000) {
                    s_last_ignored_btn = now_t2;
                    ESP_LOGW(TAG, "表情下载中，忽略按钮唤醒（下载完成后自动恢复）");
                }
                // 等待按钮释放并消抖
                vTaskDelay(pdMS_TO_TICKS(50));
                while (gpio_get_level(board_get_config()->wake_button_gpio) == 0) {
                    vTaskDelay(pdMS_TO_TICKS(10));
                }
                last_state = 1;
                continue;
            }

            s_last_wakeup_trigger_tick = now;

            ESP_LOGI(TAG, "=========================================");
            ESP_LOGI(TAG, "检测到按钮唤醒触发! (2秒内再按%d次可进入配网)",
                     REPROV_PRESS_THRESHOLD - s_press_count);
            ESP_LOGI(TAG, "=========================================");

            // 设置唤醒事件
            xEventGroupSetBits(s_wakeup_event_group, WAKEUP_TRIGGERED_BIT);

            // 等待按钮释放并消抖
            vTaskDelay(pdMS_TO_TICKS(50));
            while (gpio_get_level(board_get_config()->wake_button_gpio) == 0) {
                vTaskDelay(pdMS_TO_TICKS(10));
            }
            ESP_LOGI(TAG, "按钮已释放");

            // 释放后继续消抖
            vTaskDelay(pdMS_TO_TICKS(100));
        }

        last_state = current_state;
        vTaskDelay(pdMS_TO_TICKS(10));
    }

    s_wakeup_task_handle = NULL;
    vTaskDelete(NULL);
}

// ==================== 语音唤醒任务（纯 WakeNet，无 AFE）====================

static void wakenet_task(void *arg)
{
    ESP_LOGI(TAG, "语音唤醒任务启动");

    // 为 detect 分配 PCM 缓冲（chunksize × 通道数）
    int chunksize = s_wakenet->get_samp_chunksize(s_wakenet_data);
    int wn_channels = s_wakenet->get_channel_num(s_wakenet_data);
    int16_t *feed_buf = (int16_t *)board_malloc_audio(chunksize * wn_channels * sizeof(int16_t));
    if (feed_buf == NULL) {
        ESP_LOGE(TAG, "分配 WakeNet PCM 缓冲区失败");
        s_wakenet_task_handle = NULL;
        vTaskDelete(NULL);
        return;
    }

    ESP_LOGI(TAG, "WakeNet chunksize=%d, channels=%d", chunksize, wn_channels);

    while (s_wakeup_running) {
        // 会话期间暂停语音唤醒（s_wakenet_data 可能已被 wakeup_pause 销毁释放内存）
        if (s_wakenet_paused || s_wakenet_data == NULL) {
            s_wakenet_reading = false;  // 标记未在读取
            vTaskDelay(pdMS_TO_TICKS(50));
            continue;
        }

        // 【播放中保持检测（用户决策）】本路径没有 AEC，播放中检测听到的是自家
        // 回声，存在假唤醒风险；但用户明确要求播放（TTS/音乐）期间必须能语音
        // 打断，宁可承担假唤醒风险也不接受"播放中设备失聪只能按键"。
        // 要彻底解决假唤醒需要 AEC（参考对齐三件套），当前只有 ES8311 单总线
        // 架构具备；INMP441 双总线移植另立任务。

        // 标记正在读取 I2S
        s_wakenet_reading = true;

        // 尝试获取 I2S 互斥锁（非阻塞，让 mic_task 也有机会获取）
        // 如果 wakeup_pause 已获取锁，这里会快速退出
        if (s_i2s_mutex && xSemaphoreTake(s_i2s_mutex, pdMS_TO_TICKS(5)) != pdTRUE) {
            s_wakenet_reading = false;
            continue;
        }

        // 再次检查暂停（获取锁后检查）
        if (s_wakenet_paused || s_wakenet_data == NULL) {
            if (s_i2s_mutex) xSemaphoreGive(s_i2s_mutex);
            s_wakenet_reading = false;
            continue;
        }

        // 从 I2S 麦克风读取音频数据，累积读满一个 detect 块（chunksize 采样）
        const size_t chunk_bytes = (size_t)chunksize * wn_channels * sizeof(int16_t);
        size_t filled = 0;
        bool read_failed = false;
        int read_empty_count = 0;  // 连续空读保护
        while (filled < chunk_bytes && s_wakeup_running && !s_wakenet_paused && s_wakenet_data != NULL) {
            size_t bytes_read = 0;
            esp_err_t ret = i2s_channel_read(s_wakenet_mic_handle,
                                             (uint8_t *)feed_buf + filled,
                                             chunk_bytes - filled,
                                             &bytes_read, pdMS_TO_TICKS(50));
            if (ret != ESP_OK) { read_failed = true; break; }
            if (bytes_read > 0) {
                filled += bytes_read;
                read_empty_count = 0;
            } else {
                read_empty_count++;
                // 连续 10 次空读（约 500ms 无数据）→ 放弃本轮，避免死循环
                if (read_empty_count >= 10) {
                    ESP_LOGW(TAG, "I2S RX 连续空读 %d 次，放弃本轮检测", read_empty_count);
                    read_failed = true;
                    break;
                }
            }
        }
        // 读取完成后释放互斥锁，让 mic_task 可以使用
        if (s_i2s_mutex) xSemaphoreGive(s_i2s_mutex);

        // 诊断：统计本次读取的音频峰值，判断麦克风是否有有效数据
        // （若峰值一直为 0，说明 ES8311 ADC 未工作/收音静音）
        static uint32_t s_mic_diag_cnt = 0;
        s_mic_diag_cnt++;

        // ── 麦克风健康看门狗 ──
        // 现象：设备运行一段时间后无法语音唤醒，按键唤醒后也无法录音。
        // 本质多为 ES8311 ADC 时钟失锁 / 寄存器被 WiFi 射频干扰写坏（I2C 抗干扰经典坑），
        // 固件无任何自愈逻辑时只能靠重启恢复。
        // 自愈：连续检测到"读取失败/无数据"或"长期全零"时，重跑 es8311_power_up()
        // 重新锁存 CSM 时钟 + 重新上电 ADC/DAC + 解静音，恢复收音。
        static int s_mic_bad_reads = 0;         // 连续"读取失败/无数据"次数
        static uint32_t s_mic_zero_reads = 0;   // 连续"全零数据"次数
        static TickType_t s_last_mic_recover_tick = 0;  // 自愈冷却
        if (read_failed || filled == 0 || (filled < chunk_bytes && !s_wakenet_paused)) {
            s_mic_bad_reads++;
            s_mic_zero_reads = 0;
        } else if (filled == chunk_bytes) {
            bool all_zero = true;
            int zsamples = (int)(filled / sizeof(int16_t));
            for (int i = 0; i < zsamples; i++) {
                if (feed_buf[i] != 0) { all_zero = false; break; }
            }
            if (all_zero) {
                s_mic_zero_reads++;
                s_mic_bad_reads = 0;
            } else {
                s_mic_bad_reads = 0;
                s_mic_zero_reads = 0;
            }
        }
        // 周期性信号强度诊断：每 ~6 秒打印一次输入峰值/RMS（正常说话时应明显高于底噪）
        static uint32_t s_mic_sig_cnt = 0;
        if (filled == chunk_bytes && s_mic_bad_reads == 0 && s_mic_zero_reads == 0) {
            s_mic_sig_cnt++;
            if (s_mic_sig_cnt % 200 == 0) {
                int16_t peak = 0;
                int64_t sum_sq = 0;
                int zsamples = (int)(filled / sizeof(int16_t));
                for (int i = 0; i < zsamples; i++) {
                    int16_t v = feed_buf[i];
                    int16_t a = v < 0 ? (int16_t)-v : v;
                    if (a > peak) peak = a;
                    sum_sq += (int64_t)v * v;
                }
                int rms = (int)sqrt((double)sum_sq / zsamples);
                ESP_LOGI(TAG, "麦克风信号: 峰值=%d (%.0f%%), RMS=%d", peak,
                         peak * 100.0f / 32767.0f, rms);
            }
        }
        // 连续 ~2s 无数据 或 连续 ~30s 全零 → 判定麦克风失效，触发自愈（带 30s 冷却）
        if ((s_mic_bad_reads >= 40 || s_mic_zero_reads >= 600)) {
            TickType_t now_tick = xTaskGetTickCount();
            if ((now_tick - s_last_mic_recover_tick) * portTICK_PERIOD_MS > 30000) {
                s_last_mic_recover_tick = now_tick;
                ESP_LOGW(TAG, "麦克风检测失效 (bad_reads=%d, zero_reads=%u)，尝试 ES8311 重新锁存恢复...",
                         s_mic_bad_reads, (unsigned)s_mic_zero_reads);
                s_mic_bad_reads = 0;
                s_mic_zero_reads = 0;
#if defined(AUDIO_SCHEME_ES8311)
                if (es8311_is_initialized()) {
                    es8311_power_up();
                    es8311_set_mic_gain(MIC_GAIN_DB);
                    es8311_dump_regs();
                    ESP_LOGW(TAG, "麦克风自愈完成，已重新锁存 ES8311 时钟/ADC");
                }
#endif
            }
        }

        if (s_mic_diag_cnt % 50 == 0) {
            // 麦克风峰值诊断：DEBUG 级别，生产模式不显示（排查麦克风问题时
            // 将 wakeup 日志级别调为 DEBUG 即可恢复）
            int16_t peak = 0;
            int samples = (int)(filled / sizeof(int16_t));
            for (int i = 0; i < samples; i++) {
                int16_t v = feed_buf[i];
                if (v < 0) v = -v;
                if (v > peak) peak = v;
            }
            ESP_LOGD(TAG, "[MIC诊断] ret=%s bytes=%d peak=%d",
                     read_failed ? "FAIL" : "OK", (int)filled, peak);
        }

        if (read_failed || filled < chunk_bytes) {
            // 读取失败或暂停退出（未读满一块）：不检测，下一轮继续累积
            s_wakenet_reading = false;
            continue;
        }

        // 唤醒词检测（纯 WakeNet，直接对原始 PCM 检测）
        wakenet_state_t state = s_wakenet->detect(s_wakenet_data, feed_buf);
        s_wakenet_reading = false;

        // 诊断：每 200 次检测（约 6 秒）打印一次 detect 结果，确认 WakeNet 在运行
        static uint32_t s_detect_diag = 0;
        s_detect_diag++;
        if (s_detect_diag % 200 == 0) {
            ESP_LOGD(TAG, "WakeNet 检测状态: %s (迭代 %u)",
                     state == WAKENET_DETECTED ? "DETECTED" :
                     state == WAKENET_NO_DETECT ? "NOT_DETECTED" : "UNKNOWN",
                     (unsigned)s_detect_diag);
        }

        if (state == WAKENET_DETECTED) {
            // 表情下载/OTA 升级期间禁用唤醒（下载/写 flash 占用内存，唤醒后播放/重建
            // 可能分配失败导致异常会话；完成自动恢复）。日志节流 5 秒一次避免刷屏。
            if (gif_download_is_busy() || ota_is_updating()) {
                static TickType_t s_last_ignored_log = 0;
                TickType_t now_t = xTaskGetTickCount();
                if ((now_t - s_last_ignored_log) * portTICK_PERIOD_MS > 5000) {
                    s_last_ignored_log = now_t;
                    ESP_LOGW(TAG, "表情下载/OTA升级中，忽略语音唤醒（完成后自动恢复）");
                }
                continue;
            }
            // 冷却检查（和按钮唤醒共用冷却机制）
            TickType_t now = xTaskGetTickCount();
            if (s_last_wakeup_trigger_tick != 0) {
                TickType_t elapsed_ms = (now - s_last_wakeup_trigger_tick) * portTICK_PERIOD_MS;
                if (elapsed_ms < WAKEUP_TRIGGER_COOLDOWN_MS) {
                    ESP_LOGW(TAG, "语音唤醒忽略: 冷却中 (%d/%d ms)",
                             (int)elapsed_ms, WAKEUP_TRIGGER_COOLDOWN_MS);
                    continue;
                }
            }
            s_last_wakeup_trigger_tick = now;

            ESP_LOGI(TAG, "=========================================");
            // 注意：wn9s 的唤醒词索引从 1 开始（0 会触发 "index is out of range"）
            ESP_LOGI(TAG, "检测到语音唤醒! (词: %s)",
                     s_wakenet->get_word_name(s_wakenet_data, 1));
            ESP_LOGI(TAG, "=========================================");

            // 设置唤醒事件
            xEventGroupSetBits(s_wakeup_event_group, WAKEUP_TRIGGERED_BIT);

            // 暂停语音唤醒，等待会话结束后由 wakeup_resume() 恢复
            s_wakenet_paused = true;
            s_wakenet_reading = false;
            ESP_LOGI(TAG, "语音唤醒已暂停，等待会话结束");
        }
    }

    free(feed_buf);
    s_wakenet_task_handle = NULL;
    vTaskDeleteWithCaps(NULL);  /* 配合 xTaskCreatePinnedToCoreWithCaps */
}

#if defined(WAKEUP_USE_AFE)
// ==================== AFE 语音唤醒任务（S3：AEC+VAD+WakeNet，支持实时打断）====================

// afe_task 工作窗口口径。顶栏、拿锁后复查、逐帧读循环三处必须用同一个判断：
// serial16 实测三处口径不一致（复查还要求"正在播放"）→ 顶栏放行后立刻被否决、
// 中间没有任何延期 → 零延时死循环抽干 CPU0。
static bool afe_window_open(void)
{
    if (!s_wakenet_paused) return true;   // 空闲唤醒检测
    // 打断窗口 / 交接窗：会话中 + ASR 未在采集 + （正在播放 或 打断后等开麦）
    return !audio_mic_is_running()
           && (audio_spk_is_playing() || s_bargein_handoff);
}

// ==================== RX 积压：把麦克风拉回最新采样 ====================
// 【为什么必须丢】RX 和 TX 是全双工同一控制器、DMA 同深 12×240 = 180ms。AFE 循环
// 只要有一段时间跟不上 16kHz（serial28 实测：粗搜那几帧 34~38ms/帧，而数据是
// 32ms/帧 到的），DMA 就会被灌满，此后每次读到的都是 100~180ms 前的旧声音；
// 读和写同速，这个落后量永远不会自己消掉。回声滞后量的是"麦克风比扬声器晚多少"，
// 落后量一变，刚锁定的滞后就作废——那轮的粗搜投票 26→107→112→140→158→166
// 一路往上爬，量的就是这个正在变大的积压，直到积压顶到 DMA 上限才停住（锁 164ms），
// 锁完再没收敛（输出/麦克风 49~300% 来回摆，11 秒一次没压住）。
// 【丢的代价】RX 里那些都是"开播之前"的旧声音，打断判据用不上；通道是同一时钟域，
// 丢完下一次读立即拿到最新采样，滞后从此只剩 codec+声学这个常数。
// 只在 AFE 循环里、拿 I2S 锁之后调用（mic_task 独占 RX 时不在这里）。
static int rx_drop_backlog(int chunk_samples)
{
    if (s_wakenet_mic_handle == NULL) return 0;
    static int16_t scratch[512];
    int cap = (chunk_samples > 0 && chunk_samples <= 512) ? chunk_samples : 512;
    int dropped = 0;
    // 上限 24 块 ≈ 768ms：正常积压不会超过 DMA 深度（180ms），留几倍余量只为兜异常
    for (int i = 0; i < 24; i++) {
        size_t bytes = 0;
        esp_err_t ret = i2s_channel_read(s_wakenet_mic_handle, scratch,
                                         (size_t)cap * sizeof(int16_t), &bytes, 0);
        if (ret != ESP_OK || bytes == 0) break;   // ESP_ERR_TIMEOUT = 已经读空
        dropped += (int)(bytes / sizeof(int16_t));
    }
    // 【账本必须跟着跳】丢掉的是 dropped 个样本对应的时间，麦克风时间线整体前进了
    // dropped。账本不跳，之后每一帧的参考都会晚 dropped 个样本——抽头偏晚还落在
    // 128ms 滤波器里能补，超过就整轮消不掉（小智只有正抽头，偏晚只是变差、偏早才发散）。
    if (dropped > 0) s_aec_emit += dropped;
    return dropped;
}

static void afe_task(void *arg)
{
    ESP_LOGI(TAG, "AFE 语音唤醒任务启动（AEC 实时打断已启用）");

    // feed chunksize：AEC 每帧处理的样本数（单通道）
    int chunksize = s_afe_handle->get_feed_chunksize(s_afe_data);
    int16_t *mic_buf = (int16_t *)board_malloc_audio(chunksize * sizeof(int16_t));      // 麦克风原始
    int16_t *ref_buf = (int16_t *)board_malloc_audio(chunksize * sizeof(int16_t));      // 扬声器参考
    int16_t *afe_in_buf = (int16_t *)board_malloc_audio(chunksize * 2 * sizeof(int16_t)); // MR 交织
    if (mic_buf == NULL || ref_buf == NULL || afe_in_buf == NULL) {
        ESP_LOGE(TAG, "分配 AFE 缓冲区失败");
        free(mic_buf); free(ref_buf); free(afe_in_buf);
        s_wakenet_task_handle = NULL;
        vTaskDeleteWithCaps(NULL);
        return;
    }

    ESP_LOGI(TAG, "AFE chunksize=%d (MR 双通道输入)", chunksize);

    // 麦克风健康看门狗状态（与纯 WakeNet 路径一致：ES8311 ADC 失锁自愈）
    static int s_mic_bad_reads = 0;
    static uint32_t s_mic_zero_reads = 0;
    static TickType_t s_last_mic_recover_tick = 0;
    // VAD 打断防误触发状态：
    // - 播放刚开始的几百 ms 内 AEC 自适应滤波器尚未收敛，回声残余会被 VAD 误判为人声
    //   （表现为 TTS 一开口就自己打断自己，且打断→新会话→又播 TTS→循环打断）
    // - 因此设置播放起始保护期，期内 VAD 计数继续但不开闸；连续帧数也提高阈值
    int vad_consec = 0;
    int vad_protect_hits = 0;
    int vad_echo_leaks = 0;   // 能量够但判定为自家回声漏出、被拦下的帧数（诊断）
    bool prev_playing = false;
    TickType_t spk_play_start_tick = 0;
#define VAD_BARGE_IN_ARM_MS     600   // 播放起始保护期（AEC 收敛窗口）
#define VAD_BARGE_IN_MIN_FRAMES 5     // 开闸后连续人声帧数（每帧约 32ms，5 帧 ≈ 160ms）
#define VAD_BARGE_IN_MIN_DBFS   (-35.0f)  // AEC 后能量门限：真人近讲约 -25~-15dBFS，
                                          // 收敛后残余回声约 -45~-35dBFS，低于门限不打断
    // 循环单帧耗时（不含阻塞读）：>32ms 就意味着麦克风会积压，AEC 的滞后会跟着漂。
    // 只做诊断，打在 16 帧一次的"回声对齐"行里（serial28 判读全靠这个数）。
    int64_t s_work_sum_us = 0;
    int s_work_n = 0;
    int64_t t_after_read = 0;


    while (s_wakeup_running) {
        // 两种工作窗口：
        // - 空闲检测：未暂停（正常待机唤醒）
        // - 打断窗口：会话中 + TTS 播放中 + ASR 未在采集（mic_task 已停）。
        //   TTS 阶段 I2S 互斥锁已被 audio_mic_stop 释放（见 wakeup_i2s_mutex_release），
        //   afe_task 可安全读 RX 做"说话即打断/唤醒词打断"检测。
        if (!afe_window_open() || s_afe_data == NULL) {
            s_wakenet_reading = false;
            vad_consec = 0;
            vTaskDelay(pdMS_TO_TICKS(50));
            continue;
        }
        s_wakenet_reading = true;

        if (s_i2s_mutex && xSemaphoreTake(s_i2s_mutex, pdMS_TO_TICKS(5)) != pdTRUE) {
            s_wakenet_reading = false;
            continue;
        }
        // 复查（可能在拿锁期间被暂停/麦克风启动）
        if (!afe_window_open() || s_afe_data == NULL) {
            if (s_i2s_mutex) xSemaphoreGive(s_i2s_mutex);
            s_wakenet_reading = false;
            vTaskDelay(pdMS_TO_TICKS(5));   // 让出 CPU，绝不允许无延期回到顶栏
            continue;
        }

        // 每条播放流开播时先把 RX 积压丢掉（见 rx_drop_backlog）。放在拿锁之后、
        // 正式读之前：这一刻读到的下一块就是最新采样。
        if (s_rx_drain_req) {
            s_rx_drain_req = false;
            int dropped = rx_drop_backlog(chunksize);
            if (dropped > 0) {
                ESP_LOGW(TAG, "RX 积压 %d 样本(%dms)，已丢旧留新，麦克风与发声账本一起前移",
                         dropped, dropped * 1000 / SPK_SAMPLE_RATE);
            }
        }

        // 读取一帧麦克风数据（chunksize 样本 = chunksize*2 字节）
        const size_t chunk_bytes = (size_t)chunksize * sizeof(int16_t);
        size_t filled = 0;
        bool read_failed = false;
        int read_empty_count = 0;
        while (filled < chunk_bytes && s_wakeup_running
               && afe_window_open()
               && s_afe_data != NULL) {
            size_t bytes_read = 0;
            esp_err_t ret = i2s_channel_read(s_wakenet_mic_handle,
                                             (uint8_t *)mic_buf + filled,
                                             chunk_bytes - filled,
                                             &bytes_read, pdMS_TO_TICKS(50));
            if (ret != ESP_OK) { read_failed = true; break; }
            if (bytes_read > 0) {
                filled += bytes_read;
                read_empty_count = 0;
            } else if (++read_empty_count >= 10) {
                ESP_LOGW(TAG, "I2S RX 连续空读 %d 次，放弃本轮检测", read_empty_count);
                read_failed = true;
                break;
            }
        }
        if (s_i2s_mutex) xSemaphoreGive(s_i2s_mutex);
        t_after_read = esp_timer_get_time();   // 从这里到循环底 = 本帧真正占用的 CPU

        // ── 麦克风健康看门狗（与纯 WakeNet 路径同策略）──
        if (read_failed || filled < chunk_bytes) {
            s_mic_bad_reads++;
            s_mic_zero_reads = 0;
        } else {
            bool all_zero = true;
            for (int i = 0; i < chunksize; i++) {
                if (mic_buf[i] != 0) { all_zero = false; break; }
            }
            if (all_zero) { s_mic_zero_reads++; s_mic_bad_reads = 0; }
            else { s_mic_bad_reads = 0; s_mic_zero_reads = 0; }

            // RX 冻结自愈：RX 通道被并发读打坏后 i2s_channel_read 返回"成功"但
            // 数据冻结（同一段 32ms 样本循环出现），读不报错、非全零，上面两个
            // 看门狗均测不出 → WakeNet 吃冻结数据永远检不出唤醒词。
            // 真实麦克风底噪必有 LSB 抖动，相邻帧前 8 样本完全相同的概率极低；
            // 连续 300 帧（约 10s）签名不变则重启 RX 通道（disable+enable，10ms 无感）。
            static int16_t s_last_frame_sig[8];
            static int s_frozen_frames = 0;
            bool same_sig = !all_zero;
            for (int i = 0; i < 8 && same_sig; i++) {
                if (mic_buf[i] != s_last_frame_sig[i]) same_sig = false;
            }
            memcpy(s_last_frame_sig, mic_buf, sizeof(s_last_frame_sig));
            if (same_sig) {
                if (++s_frozen_frames >= 300) {
                    s_frozen_frames = 0;
                    ESP_LOGW(TAG, "RX 数据冻结 300 帧（并发读打坏 DMA），重启 I2S RX 通道自愈");
                    i2s_channel_disable(s_wakenet_mic_handle);
                    i2s_channel_enable(s_wakenet_mic_handle);
                }
            } else {
                s_frozen_frames = 0;
            }
        }
        if (s_mic_bad_reads >= 40 || s_mic_zero_reads >= 600) {
            TickType_t now_tick = xTaskGetTickCount();
            if ((now_tick - s_last_mic_recover_tick) * portTICK_PERIOD_MS > 30000) {
                s_last_mic_recover_tick = now_tick;
                ESP_LOGW(TAG, "麦克风检测失效 (bad_reads=%d, zero_reads=%u)，尝试 ES8311 重新锁存恢复...",
                         s_mic_bad_reads, (unsigned)s_mic_zero_reads);
                s_mic_bad_reads = 0;
                s_mic_zero_reads = 0;
                if (es8311_is_initialized()) {
                    es8311_power_up();
                    es8311_set_mic_gain(MIC_GAIN_DB);
                    ESP_LOGW(TAG, "麦克风自愈完成，已重新锁存 ES8311 时钟/ADC");
                }
            }
        }

        if (read_failed || filled < chunk_bytes) {
            s_wakenet_reading = false;
            s_aec_win_fill = 0;   // 掉帧：麦克风窗不再连续，绝对序号映射失效，重新攒窗
            s_aec_out_fill = 0;   // 输出窗也断了（与麦克风窗同一条时间线）
            // 已经读上来又丢掉的样本仍推进了麦克风时间线，账本不补就会永久落后这段
            // 时长（参考偏晚）。读失败一个字节都没拿到时 filled=0，账本原地不动。
            s_aec_emit += (int)(filled / sizeof(int16_t));
            continue;
        }

        // 拉取扬声器参考信号，交织成 "MR" 格式 [mic0, ref0, mic1, ref1, ...]
        // 先推进发出账本，再量回声延迟：麦克风帧刚读完，本帧的发出位置就是这段
        // 声音被听到的时间基准。队列抽干（DMA 在发静音）时不测，测了也只是噪声。
        aec_ref_snapshot(chunksize);
        if (s_aec_tx_live) {
            aec_lag_update(mic_buf, chunksize);
        }
        aec_ref_pop(ref_buf, chunksize);
        for (int i = 0; i < chunksize; i++) {
            afe_in_buf[2 * i] = mic_buf[i];
            afe_in_buf[2 * i + 1] = ref_buf[i];
        }

        // 喂给 AFE（AEC 消回声 → NS/AGC → VAD → WakeNet），fetch 在锁外做（CPU 重）
        s_afe_handle->feed(s_afe_data, afe_in_buf);
        s_wakenet_reading = false;

        afe_fetch_result_t *res = s_afe_handle->fetch_with_delay(s_afe_data, pdMS_TO_TICKS(200));
        // wakenet_state_t 只有 CHANNEL_VERIFIED/DETECTED 两个值，无错误枚举；
        // fetch 出错时返回 NULL 或 ret_value=ESP_FAIL，以此判断即可
        if (res == NULL || res->ret_value == ESP_FAIL) {
            continue;
        }

        // ── 播放判定 + 逐帧峰值（对齐日志、残余统计、VAD 打断共用一次遍历）──
        bool playing = audio_spk_is_playing();
        // 交接窗读到预缓冲那么长就够了（再读只会覆盖更早的一段）；iat_start 迟迟
        // 不来（断线/服务端没开麦）时不能一直占着 RX。
        if (s_bargein_handoff &&
            (xTaskGetTickCount() - s_bargein_handoff_tick) * portTICK_PERIOD_MS > WAKEUP_PREROLL_MS) {
            s_bargein_handoff = false;
        }
        if (!playing) {
            vad_consec = 0;
            if (prev_playing) margin_report();   // 本轮播放结束：交出余量分布
        } else if (!prev_playing) {
            // 播放刚开始：记录起始时间并重置计数（进入 AEC 收敛保护期）
            spk_play_start_tick = xTaskGetTickCount();
            vad_consec = 0;
            vad_protect_hits = 0;
            s_aec_resid_pct = 100;  // 本轮残余重新观察，别拿上一轮的结论放行打断
            wakeup_preroll_clear(); // 新一轮 TTS 起算，上一轮的预缓冲不再属于这句话
            s_bargein_handoff = false;  // 又开播了：这次打断已经作废，别再往预缓冲灌
            margin_reset();
            s_aec_win_ratio = 0.0f;  // 新一轮：上一轮播放的窗读数绝不沿用
            s_aec_ref_peak_play = 0;  // 本轮的响度尺子重新起量（音量/内容每轮都不同）
            s_aec_ref_e_play = 0.0f;
            // 【每条播放流都重新标定滞后】发出账本 E 的起点跟着每条流的开始走。
            // 起播相位已由 audio.c 灌满 DMA 队列固定（发出延迟=队列深度），锁出来的
            // 应当只剩 codec+声学这个小常数；标定在有效参考出现之前完成（参考置零 =
            // AEC 直通、闸门关闭），两窗投票一致才锁。
            s_aec_lag_valid = false;
            s_aec_lag_coarse = true;
            s_aec_coarse_tick = 0;
            s_aec_lag_vote_ms = -1;
            s_aec_lag_vote_age = 0;
            s_aec_recal_used = 0;   // 发散重新标定的额度按流重计
            s_aec_win_fill = 0;   // 互相关窗只装这条流的麦克风，别混上一条流的尾音
            s_aec_out_fill = 0;   // AEC 输出窗同理（漏出判据只看本条流）
            // 【开播先把 RX 积压倒空】上一条流（或 ASR 那一段）留下来的积压会让本流
            // 的麦克风整体晚 100ms 以上，而滞后是相对扬声器量的——不先对齐，量出来
            // 的就是"声学延迟 + 积压"，积压一变又作废。见 rx_drop_backlog。
            s_rx_drain_req = true;
            s_aec_stream_emit0 = s_aec_emit;  // 参考下限：不许引用本条流开始之前的样本
            s_aec_diverge_frames = 0;         // 上一条流留下的发散计数不能算到这条流头上
        }
        prev_playing = playing;

        int mic_peak = 0;
        int out_peak = 0;
        int mic_clip = 0;
        bool vad_speech = false;
        float aec_margin = 0.0f;   // 本窗超本底倍数（打断判据与余量分布共用同一个数）
        if (playing) {
            float mic_e = 0, out_e = 0;
            for (int i = 0; i < chunksize; i++) {
                int v = mic_buf[i] < 0 ? -mic_buf[i] : mic_buf[i];
                if (v > mic_peak) mic_peak = v;
                if (v >= AEC_LAG_CLIP_LEVEL) mic_clip++;
                mic_e += (float)mic_buf[i] * (float)mic_buf[i];
            }
            if (res->data != NULL) {
                for (int i = 0; i < chunksize; i++) {
                    int v = res->data[i] < 0 ? -res->data[i] : res->data[i];
                    if (v > out_peak) out_peak = v;
                    out_e += (float)res->data[i] * (float)res->data[i];
                }
                // 滚动存下这段"回声已被压掉的音频"，供打断开麦时回灌（见预缓冲一节）
                wakeup_preroll_push(res->data, chunksize);
                // 同一段"AEC 后"音频进漏出判据的窗口（见 aec_out_echo_conf）
                aec_out_win_append(res->data, chunksize);
            }
            vad_speech = (res->vad_state == VAD_SPEECH);
            if (s_aec_ref_peak > s_aec_ref_peak_play) s_aec_ref_peak_play = s_aec_ref_peak;
            if (s_aec_ref_e > s_aec_ref_e_play) s_aec_ref_e_play = s_aec_ref_e;
            // 计入残余/标定的条件：这一刻参考里确实有声音（既要够响，也要够得上
            // 本轮自己的响度），且麦克风没被推爆。
            // 削顶帧必须排除——回声一旦顶到 ADC 就是非线性失真，线性 AEC 天生消不掉，
            // 把它算进平均值会把"对齐其实是对的"这个结论也一起淹掉。
            // 【峰值的活度线要再来一条能量的】判据的分母是参考"能量"，门槛却只卡在
            // 峰值上。一个尖峰而几乎没能量的参考帧（TTS 词头、参考环打洞）照样过闸，
            // 于是 out/ref 被除以一个极小的分母：serial20 同一窗里其它帧只有 1~2%，
            // 这几帧却是 543%/602%，把 512ms 窗从 2% 抬到 55.5%，超本底 85.6 倍，
            // 服务端随后又是一轮空打（他一句话没说）。能量口径跟着峰值口径一起卡，
            // 系数沿用峰值那条 AEC_REF_LIVE_DIV（4 倍幅度 = 16 倍能量）。
            bool qualified = s_aec_ref_peak >= AEC_REF_MIN_PEAK
                             && s_aec_ref_peak * AEC_REF_LIVE_DIV >= s_aec_ref_peak_play
                             && s_aec_ref_e * (AEC_REF_LIVE_DIV * AEC_REF_LIVE_DIV) >= s_aec_ref_e_play
                             && mic_clip <= 2;
            aec_resid_feed(mic_e, out_e, s_aec_ref_e, qualified);
            // 【窗读数可沿用一整窗】帧间隙（TTS 句间停顿、语音节间隙）不该抹掉
            // 刚出过的读数；超龄才作废。serial17 的 2.2 秒打断滞后就是被逐帧清零拖出来的。
            if (s_aec_win_ratio > 0.0f && !qualified
                && (xTaskGetTickCount() - s_aec_win_ratio_tick) * portTICK_PERIOD_MS > AEC_WIN_HOLD_MS) {
                s_aec_win_ratio = 0.0f;
            }
            aec_margin = (s_aec_floor_ratio > 0.0f && s_aec_win_ratio > 0.0f)
                         ? s_aec_win_ratio / s_aec_floor_ratio : 0.0f;
            // 旧版这里还有 frame_margin（本帧 out/ref 超同一道线）+ gap_ok（参考间隙
            // 凭"上次输出/参考<1"退回窗龄口径）两道帧级门，已删：分子 out_e 来自 fetch
            // 管线延迟后的旧帧、分母 s_aec_ref_e 是本帧参考，时间基准相差 AFE 内部
            // 若干帧（VAD 缓存 128ms+），瞬态上的比值没有物理意义，后来"本帧已回落"
            // 等补丁都是在修它自己的伪影。帧级的"是不是此刻"由 VAD + data_volume +
            // 回波相关 + 连续 5 帧共同承担，这些量的时间基准都对得上。
            margin_feed(aec_margin, s_aec_floor_ratio, vad_speech);
            if (++s_aec_log_tick >= 16) {
                s_aec_log_tick = 0;
                ESP_LOGI(TAG, "回声对齐: 滞后=%dms 置信=%.2f 残余=%d%%(%d帧) "
                             "输出/参考=%.1f%% 本底=%.1f%% 超本底=%.1f倍 队列=%dms "
                             "麦克风=%d 参考=%d AEC后=%d 帧削顶=%d 窗削顶=%d 算=%.1fms vad=%d%s",
                         s_aec_lag_ms, s_aec_lag_conf, s_aec_resid_pct,
                         s_aec_resid_frames,
                         s_aec_win_ratio * 100.0f, s_aec_floor_ratio * 100.0f,
                         aec_margin,
                         (s_aec_ref_w - s_aec_emit) / 16,
                         mic_peak, s_aec_ref_peak, out_peak, mic_clip, s_aec_clip_cnt,
                         s_work_n > 0 ? (double)s_work_sum_us / 1000.0 / s_work_n : -1.0,
                         (int)res->vad_state,
                         s_aec_lag_valid ? "" : " (未对齐，参考置零)");
                s_work_sum_us = 0;
                s_work_n = 0;
            }
        } else if (s_bargein_handoff && res->data != NULL) {
            // 打断已触发、iat_start 还没到：扬声器已硬停（参考归零，AEC 这段近似直通），
            // 继续攒的就是他正在说的这句话。此前采集只在 if (playing) 里做，实测
            // 交接那 0.55 秒没人读麦克风——serial15 第二轮服务端整场 5s 无有效语音。
            wakeup_preroll_push(res->data, chunksize);
        }

        // ── 数据质量诊断：有声音时限流打印三级数据峰值 ──
        // 用于排查"唤不醒"：对比原始麦克风峰值与 AEC 后峰值。
        // 正常：喊话时原始 >1000，AEC 后接近原始（待机参考全零 AEC 应直通）。
        // 若原始好但 AEC 后被压扁 → AFE 管线衰减；若两者都差 → I2S/ES8311 采集问题。
        static int s_diag_frame = 0;
        if (++s_diag_frame >= 15) {
            s_diag_frame = 0;
            if (!playing) {
                for (int i = 0; i < chunksize; i++) {
                    int v = mic_buf[i] < 0 ? -mic_buf[i] : mic_buf[i];
                    if (v > mic_peak) mic_peak = v;
                }
                if (mic_peak > 200 && res->data != NULL) {
                    for (int i = 0; i < chunksize; i++) {
                        int v = res->data[i] < 0 ? -res->data[i] : res->data[i];
                        if (v > out_peak) out_peak = v;
                    }
                }
            }
            if (mic_peak > 200 && !playing) {
                ESP_LOGI(TAG, "音频诊断: 麦克风峰值=%d, AEC后峰值=%d, vol=%.1f dBFS, wn=%d, 滞后=%dms",
                         mic_peak, out_peak, res->data_volume, (int)res->wakeup_state,
                         s_aec_lag_ms);
            }
        }

        // ── VAD 实时打断：TTS 播放中检测到真人说话 ──
        // 判据链（每条的时间基准都站得住，见上文删 frame_margin 的说明）：
        //   1. 播放起始保护期（VAD_BARGE_IN_ARM_MS，AEC 收敛 + 本底学习）
        //   2. AEC 已标定（lag_valid）且未发散（diverged）——否则读数是滤波器自己的振荡
        //   3. 512ms 窗 输出/参考 ≥ 本底 × AEC_VOICE_MARGIN_PCT，且窗读数未超龄
        //   4. 本帧 VAD 人声 + AEC 输出能量 > VAD_BARGE_IN_MIN_DBFS
        //   5. AEC 输出与参考互相关 < AEC_LAG_CONF_MIN（排除自家回声漏出，serial29）
        //   6. 连续 VAD_BARGE_IN_MIN_FRAMES 帧（160ms）
        // 【必须在开闸后才计数】旧实现在保护期内也累加 vad_consec，判定条件却是
        // "计数≥5 且已开闸"——回声连续命中 VAD 时，保护期一到（600ms）必然立刻
        // 触发。实测 7 次"打断"全部落在 606~611ms，触发能量 -8~-21dBFS 就是自家
        // TTS 的残余回声，表现为"TTS 一开口就自己打断自己"。
        // 【判的是"这段输出参考解释不了"】窗内 AEC后能量/参考能量 必须明显高出
        // 只有 TTS 时的本底比。分母绝不能用麦克风：用户一开口分母就被他自己撑大，
        // 比值必然趋近 100%，等于专门在"他真的在说话"时关门（serial10：连喊 6.7
        // 秒残余 79~104%，闸门一次没开）。
        {
            TickType_t now = xTaskGetTickCount();
            int play_ms = (int)((now - spk_play_start_tick) * portTICK_PERIOD_MS);
            bool speech = playing && vad_speech;
            bool over_floor = aec_margin * 100.0f >= AEC_VOICE_MARGIN_PCT;
            bool win_fresh = s_aec_win_ratio > 0.0f
                             && (now - s_aec_win_ratio_tick) * portTICK_PERIOD_MS <= AEC_WIN_HOLD_MS;
            bool echo_ok = s_aec_lag_valid && !s_aec_diverged && over_floor && win_fresh;

            // 【实时打断开关关闭 = 旧行为】VAD 打断整链跳过（只保持计数复位），
            // 唤醒词打断（下方 WakeNet 对 AEC 输出检测）与按键打断不受影响。
            // 开关来自管理后台 vad_barge_in_enabled，NVS 持久化，见 wakeup_load_barge_in_enabled。
            if (!s_barge_in_enabled) {
                vad_consec = 0;
            } else if (!playing || play_ms < VAD_BARGE_IN_ARM_MS) {
                vad_consec = 0;
                if (speech && (++vad_protect_hits % 16 == 0)) {
                    // 保护期内的 VAD 命中只打日志（data_volume 为 AEC 后能量，用于校准阈值）
                    ESP_LOGI(TAG, "VAD 人声(保护期 %dms, vol=%.1f dBFS, 滞后=%dms, 超本底=%.1f倍)",
                             play_ms, res->data_volume, s_aec_lag_ms, aec_margin);
                }
            } else if (!echo_ok) {
                vad_consec = 0;
                if (speech && (++vad_protect_hits % 16 == 0)) {
                    ESP_LOGI(TAG, "VAD 命中被拦截(%s: 输出/参考=%.1f%% 本底=%.1f%% 超本底=%.1f倍 有效%d帧 残余=%d%% 滞后=%dms 置信=%.2f)",
                             !s_aec_lag_valid ? "回声未对齐"
                                 : (s_aec_diverged ? "滤波发散"
                                     : (s_aec_win_ratio <= 0.0f ? "本窗无有效参考"
                                         : (s_aec_floor_ratio <= 0.0f ? "回声本底未学到"
                                                                      : "语音未超回声本底"))),
                             s_aec_win_ratio * 100.0f, s_aec_floor_ratio * 100.0f,
                             aec_margin, s_aec_resid_frames,
                             s_aec_resid_pct, s_aec_lag_ms, s_aec_lag_conf);
                }
            } else if (speech && res->data_volume > VAD_BARGE_IN_MIN_DBFS) {
                // 【能量够了还不够，得先回答"这是谁的声音"】输出/参考超本底只说明
                // "这半秒 AEC 后剩下的能量，参考解释不了"——回声没对齐时它同样成立。
                // 线性 AEC 漏出的回声是参考的延迟拷贝，和参考做互相关照样出峰；
                // 真人说话在 AEC 输出里和参考没有相关峰。serial29 的 9.3~11.9 倍
                // 就是靠这一条区分出来的：窗内两帧 600%/744% 的尖峰是自家 TTS 漏出。
                float echo_conf = aec_out_echo_conf();
                if (echo_conf >= AEC_LAG_CONF_MIN) {
                    vad_consec = 0;
                    if (++vad_echo_leaks % 16 == 1) {
                        ESP_LOGI(TAG, "VAD 命中被拦截(AEC 输出与参考相关 %.2f：能量是自家回声漏出，不是人声；"
                                      "滞后=%dms 置信=%.2f 超本底=%.1f倍)",
                                 echo_conf, s_aec_lag_ms, s_aec_lag_conf, aec_margin);
                    }
                } else {
                vad_consec++;
                if (vad_consec >= VAD_BARGE_IN_MIN_FRAMES) {
                    // 与唤醒词相同的前置检查：表情下载/OTA 期间忽略
                    if (gif_download_is_busy() || ota_is_updating()) {
                        static TickType_t s_last_vad_ignored = 0;
                        TickType_t now_t = xTaskGetTickCount();
                        if ((now_t - s_last_vad_ignored) * portTICK_PERIOD_MS > 5000) {
                            s_last_vad_ignored = now_t;
                            ESP_LOGW(TAG, "表情下载/OTA升级中，忽略实时打断（完成后自动恢复）");
                        }
                    } else if (s_barge_in_pending || s_wakenet_paused) {
                        // 上一次打断还挂着等 handle_wakeup 消费，重复触发没有任何新事实：
                        // 只会把交接窗起点一次次往后挪（挪过头会推迟开麦）、刷 4 遍日志。
                        // serial18 同一段播放 696685/696834/696972/697072 连触 4 次
                        // （间隔 ~140ms），第一次触发到 handle_wakeup 跑起来隔了 545ms。
                        s_dup_trigger++;
                        vad_consec = 0;
                    } else {
                        ESP_LOGI(TAG, "=========================================");
                        ESP_LOGI(TAG, "VAD 实时打断! (播放 %dms 后检测到人声, vol=%.1f dBFS, "
                                     "滞后=%dms 置信=%.2f, 超本底=%.1f倍[窗%.1f%%/本底%.1f%%], "
                                     "有效%d帧 窗龄%dms, 回波相关=%.2f)",
                                 play_ms, res->data_volume, s_aec_lag_ms, s_aec_lag_conf,
                                 aec_margin, s_aec_win_ratio * 100.0f, s_aec_floor_ratio * 100.0f,
                                 s_aec_resid_frames,
                                 (int)((now - s_aec_win_ratio_tick) * portTICK_PERIOD_MS),
                                 echo_conf < 0.0f ? -1.0f : echo_conf);
                        ESP_LOGI(TAG, "=========================================");
                        // 逐帧摊开这一窗：哪几帧在把比值推上去（"-" = 该帧无有效参考）。
                        // 三帧就能把窗从 14% 抬到 77%，不摊开只看汇总分不清是人声还是仪器。
                        char fr[192];
                        int off = 0;
                        for (int i = 0; i < AEC_RESID_WIN; i++) {
                            int k = (s_aec_win_pos + i) % AEC_RESID_WIN;
                            if (!s_aec_win_ok[k]) {
                                off += snprintf(fr + off, sizeof(fr) - off, "- ");
                            } else {
                                int pct = s_aec_win_ref[k] > 0.0f
                                              ? (int)(s_aec_win_out[k] * 100.0f / s_aec_win_ref[k]) : 0;
                                off += snprintf(fr + off, sizeof(fr) - off, "%d ", pct);
                            }
                            if (off >= (int)sizeof(fr) - 6) break;
                        }
                        ESP_LOGI(TAG, "  窗内逐帧 输出/参考%%(旧→新): %s", fr);
                        // 回灌起点：本段连续人声的第一帧（vad_consec 帧之前），
                        // 开麦时从这里再前推 WAKEUP_PREROLL_LEAD_MS 开始回灌。
                        // 必须在触发这一刻记，才能保证它对应"这一次打断"的语音起点。
                        wakeup_preroll_mark_onset(vad_consec);
                        ESP_LOGI(TAG, "  回灌起点: 语音起点前 %dms（连续人声 %d 帧 ≈ %dms）",
                                 WAKEUP_PREROLL_LEAD_MS, vad_consec,
                                 vad_consec * 32);
                        s_last_wakeup_trigger_tick = now;
                        s_barge_in_pending = true;
                        s_bargein_handoff = true;          // 开麦前的采集交接窗（见上文预缓冲回灌）
                        s_bargein_handoff_tick = now;
                        xEventGroupSetBits(s_wakeup_event_group, WAKEUP_TRIGGERED_BIT);
                        // 暂停唤醒检测，等待新会话结束后 wakeup_resume 恢复
                        s_wakenet_paused = true;
                    }
                    vad_consec = 0;
                }
                }
            } else {
                vad_consec = 0;
            }
        }


        // ── 唤醒词检测（外挂纯接口实例，数据源按场景切换）──
        // 空闲态：原始麦克风数据（已验证可靠的路径）；
        // TTS 打断窗口：AEC 输出（回声已消，喊唤醒词也能打断）。
        // 【AEC 未标定/发散时播放中不喂 wn9】直通或错位状态下"输出"里就是回声本身，
        // wn9 听到自家 TTS 会假唤醒——这是旧版漏掉的第二个自打断入口（VAD 之外）。
        // 此代价是每条流标定完成前（约 0.3~0.6s，藏在 600ms 保护期内）喊唤醒词无效。
        // wn9 在 AFE 内不检出（模型缺失），故用纯实例 detect()。
        if (s_wakenet != NULL && s_wakenet_data != NULL) {
            bool spk_now = audio_spk_is_playing();
            if (!spk_now || (s_aec_lag_valid && !s_aec_diverged)) {
                const int16_t *wn_in = (spk_now && res->data != NULL) ? res->data : mic_buf;
                wakenet_state_t wn_state = s_wakenet->detect(s_wakenet_data, (int16_t *)wn_in);
                if (wn_state == WAKENET_DETECTED) {
                    if (gif_download_is_busy() || ota_is_updating()) {
                        static TickType_t s_last_ignored_log = 0;
                        TickType_t now_t = xTaskGetTickCount();
                        if ((now_t - s_last_ignored_log) * portTICK_PERIOD_MS > 5000) {
                            s_last_ignored_log = now_t;
                            ESP_LOGW(TAG, "表情下载/OTA升级中，忽略语音唤醒（完成后自动恢复）");
                        }
                        continue;
                    }
                    TickType_t now = xTaskGetTickCount();
                    if (s_last_wakeup_trigger_tick != 0) {
                        TickType_t elapsed_ms = (now - s_last_wakeup_trigger_tick) * portTICK_PERIOD_MS;
                        if (elapsed_ms < WAKEUP_TRIGGER_COOLDOWN_MS) {
                            ESP_LOGW(TAG, "语音唤醒忽略: 冷却中 (%d/%d ms)",
                                     (int)elapsed_ms, WAKEUP_TRIGGER_COOLDOWN_MS);
                            continue;
                        }
                    }
                    s_last_wakeup_trigger_tick = now;

                    ESP_LOGI(TAG, "=========================================");
                    if (s_wakenet_paused) {
                        ESP_LOGI(TAG, "检测到语音唤醒! (TTS 播放中打断)");
                    } else {
                        ESP_LOGI(TAG, "检测到语音唤醒!");
                    }
                    ESP_LOGI(TAG, "=========================================");
                    xEventGroupSetBits(s_wakeup_event_group, WAKEUP_TRIGGERED_BIT);
                    s_wakenet_paused = true;
                    ESP_LOGI(TAG, "语音唤醒已暂停，等待会话结束");
                }
            }
        }

        // 单帧耗时（不含读）：累计给 16 帧一次的诊断行。>32ms/帧 = 跟不上 16kHz = RX 积压。
        s_work_sum_us += esp_timer_get_time() - t_after_read;
        s_work_n++;
    }

    free(mic_buf);
    free(ref_buf);
    free(afe_in_buf);
    s_wakenet_task_handle = NULL;
    vTaskDeleteWithCaps(NULL);
}
#endif

// ==================== 初始化和控制 API ====================

esp_err_t wakeup_init(void)
{
    ESP_LOGI(TAG, "初始化唤醒模块...");

    // 加载用户设置的唤醒灵敏度（NVS，服务端远程调整后持久化的值）
    wakeup_load_det_threshold();
    // 加载实时打断开关（NVS，管理后台可配；关闭 = 仅唤醒词打断）
    wakeup_load_barge_in_enabled();

    // 创建事件组
    s_wakeup_event_group = xEventGroupCreate();
    if (s_wakeup_event_group == NULL) {
        ESP_LOGE(TAG, "创建事件组失败（内存不足）");
        return ESP_ERR_NO_MEM;
    }

    // 初始化 WakeNet（纯 wakenet 接口，对齐 xiaozhi-esp32 C3 方案）
    ESP_LOGI(TAG, "初始化 WakeNet (纯 wakenet 接口)...");

    // 1. 从分区加载模型列表
    s_models = esp_srmodel_init("model");
    if (s_models == NULL) {
        ESP_LOGE(TAG, "加载 SR 模型失败!");
        goto fail;
    }
    ESP_LOGI(TAG, "SR 模型加载成功，共 %d 个模型", s_models->num);

    // 2. 过滤出 WakeNet 模型
    s_model_name = esp_srmodel_filter(s_models, ESP_WN_PREFIX, NULL);
    if (s_model_name == NULL) {
        ESP_LOGE(TAG, "未找到 WakeNet 模型!");
        goto fail;
    }

    // 3. 获取 WakeNet 接口
    s_wakenet = esp_wn_handle_from_name(s_model_name);
    if (s_wakenet == NULL) {
        ESP_LOGE(TAG, "获取 WakeNet 接口失败!");
        goto fail;
    }
    ESP_LOGI(TAG, "WakeNet 模型: %s (灵敏度 DET_MODE_95)", s_model_name);

    // 4. 创建唤醒检测实例
#if defined(WAKEUP_USE_AFE)
    // S3 + ES8311：完整 AFE 管线（AEC 回声消除 + VAD + WakeNet）
    // AEC 用扬声器播放数据做参考信号消除自身声音 → TTS 播放中 VAD 实时打断
    // input_format "MR" = 单麦 + 扬声器参考；S3 加载 wn9 标准模型 → HIGH_PERF 模式
    s_afe_cfg = afe_config_init("MR", s_models, AFE_TYPE_SR, AFE_MODE_HIGH_PERF);
    if (s_afe_cfg == NULL) {
        ESP_LOGE(TAG, "创建 AFE 配置失败!");
        goto fail;
    }
    // 基于默认配置微调：只开 AEC+VAD，省 CPU/内存。
    // wakenet_init=false：wn9 在 AFE 内不检出（模型缺失），唤醒词由下方
    // 外挂纯接口实例负责，AFE 的 wakeup_state 不再使用。
    s_afe_cfg->memory_alloc_mode = AFE_MEMORY_ALLOC_MORE_PSRAM;  // 8MB PSRAM，算法缓冲尽量放 PSRAM
    s_afe_cfg->aec_init = true;       // 回声消除（核心：参考信号来自扬声器播放数据）
    s_afe_cfg->vad_init = true;       // VAD 人声检测（实时打断）
    s_afe_cfg->wakenet_init = false;  // 唤醒词不走 AFE（见文件头架构说明）
    s_afe_cfg->se_init = false;       // 声音分离需要双麦，单麦关闭
    s_afe_cfg->ns_init = false;       // AEC 后剩余噪声少，NS 收益小
    s_afe_cfg->agc_init = false;      // 近讲场景不需要 AGC
    s_afe_handle = esp_afe_handle_from_config(s_afe_cfg);
    if (s_afe_handle == NULL) {
        ESP_LOGE(TAG, "获取 AFE 接口失败!");
        goto fail;
    }
    s_afe_data = s_afe_handle->create_from_config(s_afe_cfg);
    if (s_afe_data == NULL) {
        ESP_LOGE(TAG, "AFE 创建失败!");
        goto fail;
    }
    ESP_LOGI(TAG, "AFE 创建成功（AEC+VAD+WakeNet HIGH_PERF，实时打断已启用）");
    // 【运行时确认 AEC 到底有没有被实例化、抽头多长、是否 enable】
    // aec_filter_length / aec_mode 这些配置项在预编译库里是否被真的采用，源码看不到，
    // 只能让 AFE 自己把管线打出来。print_pipeline 只在初始化时调一次（输出较多）。
    s_afe_handle->enable_aec(s_afe_data);
    s_afe_handle->print_pipeline(s_afe_data);
    // VAD 模型阈值调高（默认 0.5 偏灵敏，AEC 残余回声易误触发打断）：0.5~0.9999
    int vad_ret = s_afe_handle->set_vadnet_threshold(s_afe_data, 0.7f);
    ESP_LOGI(TAG, "VAD 模型阈值已设为 0.7 (ret=%d)", vad_ret);
    // AEC 参考信号环形缓冲（PSRAM，512ms 容量）
    s_aec_ref_ring = (int16_t *)heap_caps_malloc(AEC_REF_RING_SAMPLES * sizeof(int16_t),
                                                 MALLOC_CAP_SPIRAM);
    if (s_aec_ref_ring == NULL) {
        ESP_LOGE(TAG, "分配 AEC 参考环形缓冲失败!");
        goto fail;
    }
    aec_ref_reset();   // 环与滞后估计状态归零
    // 外挂纯 WakeNet 实例（唤醒词检测用；wn9 激活缓冲 ~80KB 在 PSRAM，
    // 与 AFE 缓冲共存无压力）。空闲态 detect 原始麦克风，TTS 中 detect AEC 输出。
    s_wakenet_data = s_wakenet->create(s_model_name, DET_MODE_95);
    if (s_wakenet_data == NULL) {
        ESP_LOGE(TAG, "外挂 WakeNet 实例创建失败!");
        goto fail;
    }
    ESP_LOGI(TAG, "外挂 WakeNet 实例创建成功（唤醒词检测用）");
    wakeup_apply_det_threshold();
#else
    // C3 / I2S 直连：纯 WakeNet 实例（激活缓冲 ~80KB）
    // 内存优化：会话期间 wakeup_pause 会 destroy 释放该内存给音频播放，
    // wakeup_resume 时重建（见 wakeup_pause/wakeup_resume）
    s_wakenet_data = s_wakenet->create(s_model_name, DET_MODE_95);
    if (s_wakenet_data == NULL) {
        ESP_LOGE(TAG, "WakeNet 创建失败!");
        goto fail;
    }
    ESP_LOGI(TAG, "WakeNet 创建成功");
    wakeup_apply_det_threshold();
#endif

    // 为唤醒检测创建 I2S 通道
    ESP_LOGI(TAG, "初始化 WakeNet I2S 通道...");
    esp_err_t i2s_err = ESP_OK;
    i2s_chan_config_t chan_cfg = I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_0, I2S_ROLE_MASTER);
    chan_cfg.auto_clear = true;
    // 【必须合并创建】ESP-IDF 同一 I2S 控制器的全双工 TX/RX 必须在同一次
    // i2s_new_channel 中成对创建并共享时钟——分开两次创建会导致 RX 数据流
    // 损坏（实测满量程削波、波形全坏、WakeNet 永远检不出唤醒）。
    // 代价：TX/RX 管道同深 12×240=180ms，AEC 参考信号无法精确对齐（滤波窗
    // 仅 32ms），回声消除效果受限；由 VAD 打断的三重防误触发兜底（保护期+
    // 连续帧+能量门限）。唤醒可靠性 > AEC 完美对齐，先保证能用。
    // DMA 缓冲区：12×240 = 180ms 吸收调度抖动（I2S 直连方案为 480ms）。
    chan_cfg.dma_desc_num = 12;
    chan_cfg.dma_frame_num = 240;
#if defined(AUDIO_SCHEME_ES8311)
    // ES8311 全双工：一次创建 TX+RX（共享 BCLK/WS/MCLK 时钟域）
    ESP_LOGI(TAG, "ES8311 全双工：合并创建 TX+RX 通道 (I2S_NUM_0)");
    i2s_err = i2s_new_channel(&chan_cfg, &s_spk_tx_handle, &s_wakenet_mic_handle);
#else
    // I2S 直连方案：仅创建 RX 通道（扬声器使用独立的 I2S_NUM_1）
    i2s_err = i2s_new_channel(&chan_cfg, NULL, &s_wakenet_mic_handle);
#endif
    if (i2s_err != ESP_OK) {
        ESP_LOGE(TAG, "创建 I2S 通道失败: %s", esp_err_to_name(i2s_err));
        goto fail;
    }

#if defined(AUDIO_SCHEME_ES8311)
    // ---- ES8311 全双工：先初始化 TX（设置 MCLK/BCLK/WS 引脚），再初始化 RX（共享时钟） ----
    // TX：扬声器通道（DAC），设置主时钟和 BCLK/WS 引脚
    // 引脚从板级配置获取（es8311_cfg + spk_i2s_*）
    const board_config_t *bcfg = board_get_config();
    i2s_std_config_t tx_cfg = {
        .clk_cfg = {
            .sample_rate_hz = SPK_SAMPLE_RATE,
            .clk_src = I2S_CLK_SRC_DEFAULT,
            .mclk_multiple = I2S_MCLK_MULTIPLE_256,  /* 对齐 xiaozhi: 256× (16k→4.096MHz) */
        },
        .slot_cfg = {
            .data_bit_width = I2S_DATA_BIT_WIDTH_16BIT,
            .slot_bit_width = I2S_SLOT_BIT_WIDTH_AUTO,
            .slot_mode = I2S_SLOT_MODE_MONO,
            .slot_mask = I2S_STD_SLOT_BOTH,
            .ws_width = I2S_DATA_BIT_WIDTH_16BIT,
            .ws_pol = false,
            .bit_shift = true,
            .left_align = true,   // 标准 I2S 左对齐（与 xiaozhi/es8311 一致，right_align 会致 ES8311 DAC 收错数据）
            .big_endian = false,
            .bit_order_lsb = false,
        },
        .gpio_cfg = {
            .mclk = bcfg->es8311_cfg->mclk_pin,
            .bclk = bcfg->spk_i2s_bck,
            .ws = bcfg->spk_i2s_ws,
            .dout = bcfg->spk_i2s_data,
            .din = I2S_GPIO_UNUSED,
            .invert_flags = {
                .mclk_inv = false,
                .bclk_inv = false,
                .ws_inv = false,
            },
        },
    };
    i2s_err = i2s_channel_init_std_mode(s_spk_tx_handle, &tx_cfg);
    if (i2s_err != ESP_OK) {
        ESP_LOGE(TAG, "TX I2S 标准模式初始化失败: %s", esp_err_to_name(i2s_err));
        goto fail;
    }

    // RX：麦克风通道（ADC），共享 BCLK/WS，仅配置 DIN 引脚
    // 关键：RX 的 mclk_multiple 必须与 TX 一致！
    // slot 配置也必须与 TX 完全一致（left_align 等），否则 ADC 数据对齐错误
    i2s_std_config_t rx_cfg = {
        .clk_cfg = {
            .sample_rate_hz = 16000,  // WakeNet 要求 16kHz
            .clk_src = I2S_CLK_SRC_DEFAULT,
            .mclk_multiple = I2S_MCLK_MULTIPLE_256,  /* 必须与 TX 一致！ */
        },
        .slot_cfg = {
            .data_bit_width = I2S_DATA_BIT_WIDTH_16BIT,
            .slot_bit_width = I2S_SLOT_BIT_WIDTH_AUTO,
            .slot_mode = I2S_SLOT_MODE_MONO,
            .slot_mask = I2S_STD_SLOT_LEFT,
            .ws_width = I2S_DATA_BIT_WIDTH_16BIT,
            .ws_pol = false,
            .bit_shift = true,
            .left_align = true,    // 与 TX 一致，ES8311 ADC 输出左对齐数据
            .big_endian = false,
            .bit_order_lsb = false,
        },
        .gpio_cfg = {
            .mclk = I2S_GPIO_UNUSED,
            .bclk = I2S_GPIO_UNUSED,   // 共享 TX 的 BCLK
            .ws = I2S_GPIO_UNUSED,     // 共享 TX 的 WS
            .dout = I2S_GPIO_UNUSED,
            .din = bcfg->mic_i2s_data,
            .invert_flags = {
                .mclk_inv = false,
                .bclk_inv = false,
                .ws_inv = false,
            },
        },
    };
    i2s_err = i2s_channel_init_std_mode(s_wakenet_mic_handle, &rx_cfg);
    if (i2s_err != ESP_OK) {
        ESP_LOGE(TAG, "RX I2S 标准模式初始化失败: %s", esp_err_to_name(i2s_err));
        goto fail;
    }

    // 使能 TX 和 RX（全双工同时工作）
    i2s_err = i2s_channel_enable(s_spk_tx_handle);
    if (i2s_err != ESP_OK) {
        ESP_LOGE(TAG, "TX I2S 通道使能失败: %s", esp_err_to_name(i2s_err));
        goto fail;
    }
    i2s_err = i2s_channel_enable(s_wakenet_mic_handle);
    if (i2s_err != ESP_OK) {
        ESP_LOGE(TAG, "RX I2S 通道使能失败: %s", esp_err_to_name(i2s_err));
        goto fail;
    }

    // MCLK 已由 I2S TX 通道稳定输出，让 ES8311 锁存时钟并恢复 ADC/DAC。
    // ES8311 的寄存器配置（含 CSM 使能）已在 main.c 的 es8311_init() 中完成，
    // 但当时 MCLK 未运行，CSM 无法锁定。现在 MCLK 稳定输出，调用 es8311_power_up()
    // 重新锁存时钟，否则 DAC 时钟错乱 → 巨大电流声 + 无收音。
    // 注意：此顺序（先 es8311_init 配寄存器，再启动 MCLK 后 power_up）用户实测验证可用，
    // 不要改成 MCLK 运行后再完整 init（会导致无法唤醒/收音/播放）。
    if (es8311_is_initialized()) {
        vTaskDelay(pdMS_TO_TICKS(50));  // 等 MCLK 稳定
        es8311_power_up();
        es8311_set_format_16bit_i2s();  // MCLK 稳定后重新确认 REG09/0A 格式（MCLK 未运行时可能读回 0xFF）
        es8311_set_mic_gain(MIC_GAIN_DB);   // 重新设置麦克风增益（见 config.h，削顶/AEC 取舍）
        ESP_LOGI(TAG, "ES8311 时钟已锁存（MCLK 稳定后 power_up）");
    } else {
        // main.c 中初始化失败（软重启后 I2C 不响应等），MCLK 运行后再重试一次完整初始化
        ESP_LOGW(TAG, "ES8311 未初始化(MCLK 已运行)，尝试重新初始化...");
        const es8311_config_t *ecfg = bcfg->es8311_cfg;
        esp_err_t es_err = es8311_init(ecfg->i2c_port,
                                       ecfg->i2c_sda,
                                       ecfg->i2c_scl,
                                       ecfg->i2c_addr,
                                       ecfg->mclk_freq,
                                       SPK_SAMPLE_RATE);
        if (es_err == ESP_OK) {
            es8311_set_mic_gain(MIC_GAIN_DB);
            ESP_LOGI(TAG, "ES8311 重新初始化成功（MCLK 运行后恢复）");
        } else {
            ESP_LOGE(TAG, "ES8311 重新初始化仍失败: %s（音频不可用，建议断电重启）",
                     esp_err_to_name(es_err));
        }
    }

    ESP_LOGI(TAG, "ES8311 全双工 I2S 初始化完成 (TX+RX, 16kHz, MCLK=4.096MHz)");
#else
    // ---- I2S 直连方案：仅 RX（麦克风），扬声器在 audio.c 中用 I2S_NUM_1 ----
    i2s_std_config_t std_cfg = {
        .clk_cfg = I2S_STD_CLK_DEFAULT_CONFIG(16000),  // WakeNet 要求 16kHz
        .slot_cfg = {
            .data_bit_width = I2S_DATA_BIT_WIDTH_16BIT,
            .slot_mode = I2S_SLOT_MODE_MONO,
            .slot_mask = I2S_STD_SLOT_LEFT,
            .ws_width = I2S_DATA_BIT_WIDTH_16BIT,
            .ws_pol = false,
            .bit_shift = true,},
        .gpio_cfg = {
            .mclk = I2S_GPIO_UNUSED,
            .bclk = board_get_config()->mic_i2s_bck,
            .ws = board_get_config()->mic_i2s_ws,
            .dout = I2S_GPIO_UNUSED,
            .din = board_get_config()->mic_i2s_data,
            .invert_flags = {
                .mclk_inv = false,
                .bclk_inv = false,
                .ws_inv = false,
            },
        },
    };

    i2s_err = i2s_channel_init_std_mode(s_wakenet_mic_handle, &std_cfg);
    if (i2s_err != ESP_OK) {
        ESP_LOGE(TAG, "I2S 标准模式初始化失败: %s", esp_err_to_name(i2s_err));
        goto fail;
    }
    i2s_err = i2s_channel_enable(s_wakenet_mic_handle);
    if (i2s_err != ESP_OK) {
        ESP_LOGE(TAG, "I2S 通道使能失败: %s", esp_err_to_name(i2s_err));
        goto fail;
    }
    ESP_LOGI(TAG, "WakeNet 专用 I2S 麦克风初始化完成 (16kHz)");
#endif

    // 创建 I2S 互斥锁（用 Binary 而非 Mutex，避免跨任务 Give 触发优先级继承断言）
    s_i2s_mutex = xSemaphoreCreateBinary();
    if (s_i2s_mutex == NULL) {
        ESP_LOGE(TAG, "创建 I2S 互斥锁失败");
        goto fail;
    }
    xSemaphoreGive(s_i2s_mutex);  // 初始化为"已释放"状态

    ESP_LOGI(TAG, "唤醒模块初始化完成");
    // 打印实际加载的唤醒词模型（从 esp-sr 模型列表读取，避免硬编码与实际模型不符）
    if (s_models && s_models->num > 0) {
        char *wake_words = esp_srmodel_get_wake_words(s_models, s_models->model_name[0]);
        ESP_LOGI(TAG, "唤醒词模型: %s (唤醒词: %s)",
                 s_models->model_name[0], wake_words ? wake_words : "未知");
    }
    return ESP_OK;

fail:
    // 初始化失败，按逆序清理已分配资源，避免泄漏
    if (s_i2s_mutex) { vSemaphoreDelete(s_i2s_mutex); s_i2s_mutex = NULL; }
#if defined(AUDIO_SCHEME_ES8311)
    // ES8311 全双工：TX 和 RX 是一对，都需要清理
    if (s_spk_tx_handle) { i2s_channel_disable(s_spk_tx_handle); i2s_del_channel(s_spk_tx_handle); s_spk_tx_handle = NULL; }
#endif
    if (s_wakenet_mic_handle) { i2s_channel_disable(s_wakenet_mic_handle); i2s_del_channel(s_wakenet_mic_handle); s_wakenet_mic_handle = NULL; }
#if defined(WAKEUP_USE_AFE)
    if (s_afe_data && s_afe_handle) { s_afe_handle->destroy(s_afe_data); s_afe_data = NULL; }
    if (s_aec_ref_ring) { free(s_aec_ref_ring); s_aec_ref_ring = NULL; }
    if (s_afe_cfg) { free(s_afe_cfg); s_afe_cfg = NULL; }
    s_afe_handle = NULL;
#endif
    if (s_wakenet_data && s_wakenet) { s_wakenet->destroy(s_wakenet_data); s_wakenet_data = NULL; }
    if (s_models) { esp_srmodel_deinit(s_models); s_models = NULL; }
    return ESP_FAIL;
}

esp_err_t wakeup_start(void)
{
    if (s_wakeup_running) {
        ESP_LOGW(TAG, "唤醒检测已在运行");
        return ESP_OK;
    }

    ESP_LOGI(TAG, "启动唤醒检测...");
    s_wakeup_running = true;

    // 启动按钮唤醒任务
    BaseType_t task_ret = xTaskCreatePinnedToCore(
        button_wakeup_task,
        "btn_wakeup",
        4096,
        NULL,
        TASK_PRIO_WAKEUP,
        &s_wakeup_task_handle,
        BOARD_TASK_CORE_1  // 双核：核心1；单核：核心0
    );

    if (task_ret != pdPASS) {
        ESP_LOGE(TAG, "创建按钮唤醒任务失败");
        s_wakeup_running = false;
        return ESP_FAIL;
    }

    // 启动语音唤醒任务（有 PSRAM 时栈放 PSRAM，无 PSRAM 回退内部 RAM）
    task_ret = xTaskCreatePinnedToCoreWithCaps(
#if defined(WAKEUP_USE_AFE)
        afe_task,
#else
        wakenet_task,
#endif
        "wakenet",
#ifdef CONFIG_IDF_TARGET_ESP32C3
        6144,   // C3 无 PSRAM，栈走内部 RAM，收紧以省堆
#elif defined(WAKEUP_USE_AFE)
        12288,  // AFE 任务内串行调用 feed+fetch（AEC/VAD/WakeNet 库内部栈较深），栈在 PSRAM 放宽
#else
        8192,   // 恢复 8192（有 PSRAM 时栈不受内部 RAM 限制）
#endif
        NULL,
        TASK_PRIO_WAKEUP,
        &s_wakenet_task_handle,
        BOARD_TASK_CORE_0,  // 双核：核心0（与按钮任务分核运行）；单核：核心0
        BOARD_STACK_CAPS_AUDIO
    );

    if (task_ret != pdPASS) {
        ESP_LOGE(TAG, "创建语音唤醒任务失败");
        // 按钮唤醒仍然可用，不返回错误
    } else {
        ESP_LOGI(TAG, "语音唤醒任务创建成功（PSRAM 栈）");
    }

    ESP_LOGI(TAG, "唤醒检测已启动（按钮 + 语音）");
    return ESP_OK;
}

esp_err_t wakeup_stop(void)
{
    if (!s_wakeup_running) {
        return ESP_OK;
    }

    ESP_LOGI(TAG, "停止唤醒检测...");
    s_wakeup_running = false;

    // 等待任务结束（最多等待 5 秒，超时后记录警告并继续，避免无限阻塞）
    const int WAKEUP_STOP_TIMEOUT_MS = 5000;
    int waited_ms = 0;
    while (s_wakeup_task_handle != NULL || s_wakenet_task_handle != NULL) {
        if (waited_ms >= WAKEUP_STOP_TIMEOUT_MS) {
            ESP_LOGW(TAG, "等待唤醒任务退出超时(%dms)，强制继续停止流程 (btn=%p, wakenet=%p)",
                     WAKEUP_STOP_TIMEOUT_MS, s_wakeup_task_handle, s_wakenet_task_handle);
            break;
        }
        vTaskDelay(pdMS_TO_TICKS(10));
        waited_ms += 10;
    }

    // 销毁 WakeNet 实例
    if (s_wakenet_data && s_wakenet) {
        s_wakenet->destroy(s_wakenet_data);
        s_wakenet_data = NULL;
    }

#if defined(WAKEUP_USE_AFE)
    // 销毁 AFE 实例与参考环（AFE destroy 会一并释放内部 WakeNet/VAD/AEC）
    if (s_afe_data && s_afe_handle) {
        s_afe_handle->destroy(s_afe_data);
        s_afe_data = NULL;
    }
    if (s_aec_ref_ring) { free(s_aec_ref_ring); s_aec_ref_ring = NULL; }
#endif

    // 释放模型列表
    if (s_models) {
        esp_srmodel_deinit(s_models);
        s_models = NULL;
    }

    // 关闭 WakeNet 专用 I2S 麦克风
    if (s_wakenet_mic_handle) {
        i2s_channel_disable(s_wakenet_mic_handle);
        i2s_del_channel(s_wakenet_mic_handle);
        s_wakenet_mic_handle = NULL;
    }
#if defined(AUDIO_SCHEME_ES8311)
    // ES8311 全双工：关闭 TX 通道（扬声器）
    if (s_spk_tx_handle) {
        i2s_channel_disable(s_spk_tx_handle);
        i2s_del_channel(s_spk_tx_handle);
        s_spk_tx_handle = NULL;
    }
#endif

    ESP_LOGI(TAG, "唤醒检测已停止");
    return ESP_OK;
}

void wakeup_pause(void)
{
    // 置暂停标志（幂等：语音唤醒路径 wakenet_task 已自行置位，此处可能非首次）
    bool already_paused = s_wakenet_paused;
    s_wakenet_paused = true;

    // 等待 WakeNet 真正停止读取 I2S，避免与 mic_task 竞争
#if defined(WAKEUP_USE_AFE)
    // 【AFE 模式不等】暂停后 afe_task 仍要在打断窗口/交接窗里继续读 RX，
    // s_wakenet_reading 会一直是 true：这里等满 200ms 既等不到结果、又会误报
    // "暂停失败"（serial17 135423），把开麦整条链路拖慢。通道独占由 s_i2s_mutex
    // 负责（下面 !already_paused 分支照样拿锁；mic_task 启动前先 reacquire）。
    (void)already_paused;
#else
    if (!already_paused) {
        int wait = 0;
        while (s_wakenet_reading && wait < 20) {  // 最多等 200ms
            vTaskDelay(pdMS_TO_TICKS(10));
            wait++;
        }
        // 超时后再次检查：若仍正在读取，记录警告并额外等待更长时间
        if (s_wakenet_reading) {
            ESP_LOGW(TAG, "语音唤醒暂停超时(200ms)，s_wakenet_reading 仍为 true，额外等待 500ms");
            int wait2 = 0;
            while (s_wakenet_reading && wait2 < 50) {  // 额外等待 500ms
                vTaskDelay(pdMS_TO_TICKS(10));
                wait2++;
            }
        }
    } else {
        // wakenet_task 自行暂停（语音唤醒打断路径）：读取可能仍在进行，同样等它停
        int wait = 0;
        while (s_wakenet_reading && wait < 20) {
            vTaskDelay(pdMS_TO_TICKS(10));
            wait++;
        }
    }
#endif
    // 获取 I2S 互斥锁，阻止 WakeNet 读 I2S（仅首次暂停时拿，锁一直持有到
    // wakeup_resume() 释放）。重复调用 pause（如"02"连续对话流程的 iat_start
    // 前再次 pause）时锁已被本模块持有，FreeRTOS 互斥锁不可重入，
    // 再 take 会 1 秒超时刷 E 日志——已暂停状态下无需再拿。
    // 使用有限超时（1秒）而非 portMAX_DELAY，避免在 WakeNet 卡死时永久阻塞导致死锁
    if (s_i2s_mutex && !already_paused) {
        if (xSemaphoreTake(s_i2s_mutex, pdMS_TO_TICKS(1000)) == pdTRUE) {
            s_pause_holding_mutex = true;  // 标记锁由本模块代持（TTS 窗口可释放）
        } else {
            s_pause_holding_mutex = false;
            ESP_LOGE(TAG, "wakeup_pause 获取 I2S 互斥锁超时(1s)，可能 WakeNet 任务卡死");
        }
    }
#if defined(WAKEUP_USE_AFE)
    ESP_LOGI(TAG, "语音唤醒已暂停");
#else
    if (s_wakenet_reading) {
        ESP_LOGE(TAG, "语音唤醒暂停失败：s_wakenet_reading 仍为 true，I2S 可能存在竞争");
    } else {
        ESP_LOGI(TAG, "语音唤醒已暂停");
    }
#endif

    // 内存优化：销毁 WakeNet 实例，把激活缓冲还给堆，供音频播放使用。
    // C3（无 PSRAM）：WakeNet 激活缓冲 ~80KB + MP3 解码器 45KB 都在内部 RAM，
    // 无法共存，必须销毁以释放内存给 MP3 解码器（否则播放无声）。
    // 非 C3（有 PSRAM）：WakeNet 激活缓冲在 PSRAM，MP3 解码器用内部 RAM，
    // 无内存冲突，保留实例可避免"02"连续对话中 iat_end 未到达时 WakeNet 永久失效。
    // 注意：即使条件跳过销毁，I2S 互斥锁仍被持有，wakenet_task 不会读取 I2S。
#if defined(CONFIG_IDF_TARGET_ESP32C3)
    if (s_wakenet && s_wakenet_data) {
        s_wakenet->destroy(s_wakenet_data);
        s_wakenet_data = NULL;
        ESP_LOGI(TAG, "WakeNet 实例已销毁，释放堆给播放使用 (剩余堆: %d bytes)",
                 (int)heap_caps_get_free_size(MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT));
    }
#elif defined(WAKEUP_USE_AFE)
    // AFE 实例常驻（PSRAM 充足无需销毁换内存），I2S 互斥锁已持有，
    // afe_task 循环首行检查 s_wakenet_paused 不会再 feed/fetch
    aec_ref_reset();  // 暂停期间积压的旧参考已过期，恢复时从零开始
    ESP_LOGI(TAG, "语音唤醒已暂停（AFE 实例保留，剩余堆: %d bytes, PSRAM: %d bytes)",
             (int)heap_caps_get_free_size(MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT),
             (int)heap_caps_get_free_size(MALLOC_CAP_SPIRAM));
#else
    ESP_LOGI(TAG, "WakeNet 实例保留（PSRAM 模式，无需释放内存，剩余堆: %d bytes, PSRAM: %d bytes)",
             (int)heap_caps_get_free_size(MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT),
             (int)heap_caps_get_free_size(MALLOC_CAP_SPIRAM));
#endif
}

// WakeNet 重建失败重试任务：
// 会话异常结束时（如服务器"Wake audio failed"后不发 session_end），设备端只能靠
// 看门狗/超时检测恢复唤醒。若此刻内存不足（如 GIF 表情下载占用中），create 失败，
// 语音唤醒会永久失效（实测必须重启）。本任务每 10 秒重试重建，直到成功或系统停止。
// 唤醒灵敏度：WakeNet 模型默认阈值 ~0.63，对部分环境/扬声器偏严（需大声喊才能唤醒）。
// 通过 set_det_threshold 调低阈值提升灵敏度（合法范围 0.4~0.9999，越低越灵敏、误唤醒率越高）。
// 默认 0.55：上一版 0.60 在 TTS 播放中（扬声器回声干扰）打断不灵敏。0.55 在降噪环境下
// 误唤醒率仍可接受，但显著提升打断成功率。可由服务端下发 wake_sensitivity 远程调整并持久化。
#define WAKENET_DET_THRESHOLD_DEFAULT 0.55f
#define WAKENET_DET_THRESHOLD_MIN     0.40f
#define WAKENET_DET_THRESHOLD_MAX     0.90f
static float s_wakenet_det_threshold = WAKENET_DET_THRESHOLD_DEFAULT;

// 从 NVS 读取用户设置的唤醒灵敏度（config_commands 保存的 "wake_sens" 键）
static void wakeup_load_det_threshold(void)
{
    nvs_handle_t h;
    if (nvs_open("esp-ai-kv", NVS_READONLY, &h) == ESP_OK) {
        char val[16] = {0};
        size_t len = sizeof(val);
        if (nvs_get_str(h, "wake_sens", val, &len) == ESP_OK) {
            float t = atof(val);
            if (t >= WAKENET_DET_THRESHOLD_MIN && t <= WAKENET_DET_THRESHOLD_MAX) {
                s_wakenet_det_threshold = t;
                ESP_LOGI(TAG, "唤醒灵敏度从 NVS 加载: %.2f", t);
            } else {
                ESP_LOGW(TAG, "NVS 唤醒灵敏度 %s 超出范围，使用默认 %.2f", val, WAKENET_DET_THRESHOLD_DEFAULT);
            }
        }
        nvs_close(h);
    }
}

// 远程设置唤醒灵敏度（config_commands 即时生效调用）：调整当前已创建实例的阈值
void wakeup_set_sensitivity(float threshold)
{
    if (threshold < WAKENET_DET_THRESHOLD_MIN) threshold = WAKENET_DET_THRESHOLD_MIN;
    if (threshold > WAKENET_DET_THRESHOLD_MAX) threshold = WAKENET_DET_THRESHOLD_MAX;
    float old = s_wakenet_det_threshold;
    s_wakenet_det_threshold = threshold;
    ESP_LOGI(TAG, "唤醒灵敏度设置: %.2f → %.2f", old, threshold);
    // 已创建的实例立即应用（重建/resume 后由 wakeup_apply_det_threshold 使用新值）
    if (!s_wakenet_paused) {
        wakeup_apply_det_threshold();
    }
}

// ==================== 实时打断开关 ====================
// 状态变量 s_barge_in_enabled 在文件头（s_barge_in_pending 旁）声明。
// 从 NVS 读取实时打断开关（config_commands 保存的 "barge_in" 键；缺省 = 开启）
static void wakeup_load_barge_in_enabled(void)
{
    nvs_handle_t h;
    if (nvs_open("esp-ai-kv", NVS_READONLY, &h) == ESP_OK) {
        char val[8] = {0};
        size_t len = sizeof(val);
        if (nvs_get_str(h, "barge_in", val, &len) == ESP_OK) {
            s_barge_in_enabled = (strcmp(val, "true") == 0 || strcmp(val, "1") == 0);
        }
        nvs_close(h);
    }
    ESP_LOGI(TAG, "实时打断开关从 NVS 加载: %s", s_barge_in_enabled ? "开启" : "关闭");
}

// 远程设置实时打断开关（config_commands 即时生效调用）
void wakeup_set_barge_in_enabled(bool enabled)
{
    bool old = s_barge_in_enabled;
    s_barge_in_enabled = enabled;
    ESP_LOGI(TAG, "实时打断开关设置: %s → %s", old ? "开启" : "关闭", enabled ? "开启" : "关闭");
}

// 调低 WakeNet 触发阈值（须在 create 之后调用；wakeup_resume/延迟重试重建后阈值会重置，需重新设置）
static void wakeup_apply_det_threshold(void)
{
    // 统一走外挂纯 WakeNet 实例（AFE 内 wakenet 已关闭，AFE 接口的
    // set_wakenet_threshold 对 wakenet_init=false 的实例无效）
    if (!s_wakenet || !s_wakenet_data) return;
    int wn = s_wakenet->get_word_num(s_wakenet_data);
    if (wn <= 0) return;
    for (int i = 0; i < wn; i++) {
        int idx = i + 1;  // 唤醒词索引从 1 开始
        float old_t = s_wakenet->get_det_threshold(s_wakenet_data, idx);
        s_wakenet->set_det_threshold(s_wakenet_data, s_wakenet_det_threshold, idx);
        float new_t = s_wakenet->get_det_threshold(s_wakenet_data, idx);
        const char *wname = s_wakenet->get_word_name(s_wakenet_data, idx);
        ESP_LOGI(TAG, "唤醒阈值[%s]: %.3f → %.3f", wname ? wname : "?", old_t, new_t);
    }
}

static void wakenet_rebuild_task(void *arg)
{
    // 快速重试：前 5 次每秒重试（快速恢复打断能力），之后每 10 秒重试
    int retry_count = 0;
    const int FAST_RETRY_LIMIT = 5;
    const TickType_t FAST_RETRY_DELAY = pdMS_TO_TICKS(1000);
    const TickType_t SLOW_RETRY_DELAY = pdMS_TO_TICKS(10000);
    while (s_wakeup_running) {
        TickType_t delay = (retry_count < FAST_RETRY_LIMIT) ? FAST_RETRY_DELAY : SLOW_RETRY_DELAY;
        vTaskDelay(delay);
        retry_count++;
        if (!s_wakeup_running) break;
        if (s_wakenet_data != NULL) break;          // 已重建成功（可能由其他路径重建）
        if (s_wakenet_paused) continue;             // 会话中，等 resume
        if (s_wakenet == NULL || s_model_name == NULL) break;  // 模块已停
        s_wakenet_data = s_wakenet->create(s_model_name, DET_MODE_95);
        if (s_wakenet_data != NULL) {
            wakeup_apply_det_threshold();
            ESP_LOGI(TAG, "WakeNet 重建成功（延迟重试恢复，重试次数=%d）", retry_count);
            break;
        }
        if (retry_count <= FAST_RETRY_LIMIT) {
            ESP_LOGW(TAG, "WakeNet 重建重试 #%d 失败（堆不足），1 秒后再试, 剩余堆: %d bytes",
                     retry_count, (int)heap_caps_get_free_size(MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT));
        } else {
            ESP_LOGW(TAG, "WakeNet 重建重试 #%d 失败（堆不足），10 秒后再试", retry_count);
        }
    }
    vTaskDelete(NULL);
}

void wakeup_resume(void)
{
    if (s_wakenet_paused) {
        s_wakenet_paused = false;
        // 仅当代持标志有效时释放（TTS 窗口可能已提前释放，避免重复 give）
        if (s_i2s_mutex && s_pause_holding_mutex) {
            xSemaphoreGive(s_i2s_mutex);
            s_pause_holding_mutex = false;
        }
#if defined(WAKEUP_USE_AFE)
        // AFE 模式：实例常驻，无需重建；清掉过期参考数据
        aec_ref_reset();
        ESP_LOGI(TAG, "语音唤醒已恢复（AFE 模式，剩余堆: %d bytes, PSRAM: %d bytes)",
                 (int)heap_caps_get_free_size(MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT),
                 (int)heap_caps_get_free_size(MALLOC_CAP_SPIRAM));
#else
        // 内存优化：重建被 wakeup_pause 销毁的 WakeNet 实例，恢复语音唤醒
        // 播放结束后 MP3 解码器已释放（spk_task drain 时释放），堆充足
        if (s_wakenet_data == NULL && s_wakenet != NULL && s_model_name != NULL) {
            ESP_LOGI(TAG, "WakeNet 创建中... 剩余堆: %d bytes",
                     (int)heap_caps_get_free_size(MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT));
            s_wakenet_data = s_wakenet->create(s_model_name, DET_MODE_95);
            if (s_wakenet_data == NULL) {
                ESP_LOGE(TAG, "WakeNet 重建失败（堆不足），启动延迟重试... 剩余堆: %d bytes",
                         (int)heap_caps_get_free_size(MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT));
                // 不放弃：启动后台重试任务（GIF 下载等内存占用结束后即可恢复），
                // 否则异常会话结束后语音唤醒永久失效，必须重启
                xTaskCreate(wakenet_rebuild_task, "wn_rebuild", 4096, NULL, 2, NULL);
            } else {
                wakeup_apply_det_threshold();
                ESP_LOGI(TAG, "WakeNet 重建成功，语音唤醒已恢复 (剩余堆: %d bytes)",
                         (int)heap_caps_get_free_size(MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT));
            }
        } else if (s_wakenet_data != NULL) {
            ESP_LOGI(TAG, "语音唤醒已恢复（WakeNet 实例已存在，未重建）");
        } else {
            ESP_LOGI(TAG, "语音唤醒标记已恢复（WakeNet 接口未就绪，等待重建任务）");
        }
#endif
    }
}

// 清除唤醒冷却：唤醒触发后发送失败（WS 未连接等）时调用，
// 让用户在网络恢复后能立即再次唤醒，不被 8 秒冷却惩罚
// （否则断线期间每次唤醒都失败+冷却，感知为"永远唤不醒"）
void wakeup_clear_cooldown(void)
{
    s_last_wakeup_trigger_tick = 0;
    ESP_LOGI(TAG, "唤醒冷却已清除（上次唤醒发送失败）");
}

void *wakeup_get_mic_handle(void)
{
    return (void *)s_wakenet_mic_handle;
}

// ==================== TTS 打断窗口锁管理 ====================
// 会话时序：wake → wakeup_pause 拿锁代持 → ASR（mic_task 独占 RX）
//   → ASR 结束 audio_mic_stop → release 放锁 → TTS 播放（afe_task 读 RX 做打断检测）
//   → 下一轮 ASR audio_mic_start → reacquire 拿锁（等待 afe_task 当前帧读完，≤35ms）
//   → 会话结束 wakeup_resume → 放锁归位

void wakeup_i2s_mutex_release(void)
{
    if (s_pause_holding_mutex && s_i2s_mutex) {
        xSemaphoreGive(s_i2s_mutex);
        s_pause_holding_mutex = false;
        ESP_LOGI(TAG, "I2S 互斥锁已释放（TTS 打断窗口开启）");
    }
}

void wakeup_i2s_mutex_reacquire(void)
{
    // 唯一调用点是 audio_mic_start：麦克风要独占 RX 了，交接窗到此为止
    // （再读就和 mic_task 抢同一个通道，两边都拿到半句）
    s_bargein_handoff = false;
    if (!s_pause_holding_mutex && s_i2s_mutex) {
        // afe_task 每帧持锁 ≤35ms（读取 512 样本），2 秒超时非常充裕
        if (xSemaphoreTake(s_i2s_mutex, pdMS_TO_TICKS(2000)) == pdTRUE) {
            s_pause_holding_mutex = true;
        } else {
            ESP_LOGE(TAG, "重新获取 I2S 互斥锁超时（afe_task 可能卡死）");
        }
    }
}

void *wakeup_get_spk_handle(void)
{
    return (void *)s_spk_tx_handle;
}

bool wakeup_is_paused(void)
{
#if defined(WAKEUP_USE_AFE)
    // AFE 模式下"WakeNet 不再检唤醒词"和"有没有人在读 RX"是两件事：会话期间
    // afe_task 必须在打断窗口/交接窗里继续读 RX（这是实时打断的前提），
    // s_wakenet_reading 本来就会长期为真。把它算进"已暂停"，mic_task 会白等到
    // 超时、iat_start 会重复 pause（serial17：135423 误报"暂停失败"、135689 又
    // 暂停一次，开麦整整拖后约 300ms）。RX 的独占从来不靠这个标志，
    // 靠的是 audio_mic_start 先 wakeup_i2s_mutex_reacquire() 才建 mic_task。
    return s_wakenet_paused;
#else
    return s_wakenet_paused && !s_wakenet_reading;
#endif
}

// ==================== 打断预缓冲（barge-in preroll）====================
// 【为什么必须有】打断判据要攒满一个能量窗才敢确认"这段不是自家回声"，从开口到
// 开闸实测要 0.8~3.7 秒，而用户的话在开闸之前就已经说出去了。serial11 实测：
// 229125 触发打断 → 服务端 07:21:03 回 iat_start、229617 开麦（协议这段已经完全
// 正确），但他那句从 225900 就在说；开麦后 4.9 秒采到的全是静音（采集统计
// "人声帧 0、峰值 791"），服务端只能报"5s 无有效语音"——这就是"打断后我说话它
// 收不到音"。所以播放期间把 AEC 输出（回声已被压掉，可直接喂 ASR）滚动存下
// 1.5 秒，开麦时先回灌这一段，再开始采新数据。
// 【只有 VAD 实时打断允许回灌】正常唤醒时这段里全是自家 TTS，喂进识别等于让它
// "听见自己"，所以 armed 标志由 wakeup_take_barge_in() 决定。
static int16_t *s_preroll = NULL;
static int s_preroll_len = 0;                    // 缓冲区里尚未被取走的样本数
static int s_preroll_pos = 0;                    // 下一个写入位置（环形）
static volatile bool s_preroll_armed = false;    // 本轮是否是打断会话（可回灌）
static portMUX_TYPE s_preroll_mux = portMUX_INITIALIZER_UNLOCKED;
// 【回灌起点】旧实现固定回灌"最后 1.5 秒"，起点落在整段语音之前：既把自家 TTS
// 的尾音一起喂进 ASR（实测识别出"嗯那还可以…"），又让真正的话头被挤到缓冲末尾。
// 现在按"本段连续人声的第一帧"定起点，再往前推 WAKEUP_PREROLL_LEAD_MS：
// 保得住用户第一个字，也不会把更早的回声带进来。
// 绝对序号（不是环形下标）由 push 累计，这样"起点→下标"的换算与环形回绕无关。
static uint64_t s_preroll_total = 0;             // 累计写入样本数（绝对序号基准）
static int s_preroll_frame_num = 0;              // 每帧样本数（AFE chunksize）
static uint64_t s_preroll_onset_abs = 0;         // 本段语音起点（绝对序号）
static bool s_preroll_onset_valid = false;       // 是否已定位到语音起点
static uint64_t s_preroll_read_abs = 0;          // take 的读游标（绝对序号）
static bool s_preroll_read_started = false;      // 读游标是否已定位

void wakeup_preroll_push(const int16_t *samples, int num)
{
    if (samples == NULL || num <= 0) return;
    if (s_preroll == NULL) {
        s_preroll = (int16_t *)heap_caps_malloc(WAKEUP_PREROLL_MAX_SAMPLES * sizeof(int16_t),
                                                MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
        if (s_preroll == NULL) {
            ESP_LOGE(TAG, "打断预缓冲分配失败(%d 字节)，实时打断将丢掉开头 %.1f 秒",
                     (int)(WAKEUP_PREROLL_MAX_SAMPLES * sizeof(int16_t)),
                     WAKEUP_PREROLL_MAX_SAMPLES / 16000.0f);
            return;
        }
    }
    portENTER_CRITICAL(&s_preroll_mux);
    s_preroll_frame_num = num;
    for (int i = 0; i < num; i++) {
        s_preroll[s_preroll_pos] = samples[i];
        if (++s_preroll_pos >= WAKEUP_PREROLL_MAX_SAMPLES) s_preroll_pos = 0;
    }
    s_preroll_total += (uint64_t)num;
    if (s_preroll_len + num > WAKEUP_PREROLL_MAX_SAMPLES) {
        s_preroll_len = WAKEUP_PREROLL_MAX_SAMPLES;   // 满了：最旧的一段被覆盖
    } else {
        s_preroll_len += num;
    }
    portEXIT_CRITICAL(&s_preroll_mux);
}

void wakeup_preroll_mark_onset(int frames)
{
    if (frames <= 0) return;
    portENTER_CRITICAL(&s_preroll_mux);
    // 当前帧的样本已经 push 过：本段连续人声的第一帧 = 总数 - frames × 每帧样本数
    uint64_t back = (uint64_t)frames * (uint64_t)(s_preroll_frame_num > 0
                                                      ? s_preroll_frame_num : 1);
    s_preroll_onset_abs = (s_preroll_total > back) ? s_preroll_total - back : 0;
    s_preroll_onset_valid = true;
    portEXIT_CRITICAL(&s_preroll_mux);
}

void wakeup_preroll_clear(void)
{
    portENTER_CRITICAL(&s_preroll_mux);
    s_preroll_len = 0;
    s_preroll_pos = 0;
    s_preroll_total = 0;          // 绝对序号与 pos 必须一起归零，否则换算错位
    s_preroll_onset_abs = 0;
    s_preroll_onset_valid = false;
    s_preroll_read_abs = 0;
    s_preroll_read_started = false;
    s_preroll_armed = false;
    portEXIT_CRITICAL(&s_preroll_mux);
}

int wakeup_preroll_take(int16_t *dst, int max_samples)
{
    if (!s_preroll_armed || s_preroll == NULL || dst == NULL || max_samples <= 0) return 0;
    portENTER_CRITICAL(&s_preroll_mux);

    // 缓冲里最旧的样本（绝对序号）
    uint64_t oldest = (s_preroll_total > (uint64_t)s_preroll_len)
                          ? s_preroll_total - (uint64_t)s_preroll_len : 0;

    if (!s_preroll_read_started) {
        uint64_t start = oldest;
        if (s_preroll_onset_valid) {
            uint64_t lead = (uint64_t)(16 * WAKEUP_PREROLL_LEAD_MS);
            uint64_t want = (s_preroll_onset_abs > lead) ? s_preroll_onset_abs - lead : 0;
            if (want > start) start = want;          // 起点前推 lead，但不越过缓冲最旧处
        }
        s_preroll_read_abs = start;
        s_preroll_read_started = true;
    }

    uint64_t avail = (s_preroll_total > s_preroll_read_abs)
                         ? s_preroll_total - s_preroll_read_abs : 0;
    if (avail == 0) {
        s_preroll_len = 0;
        s_preroll_armed = false;
        s_preroll_onset_valid = false;
        s_preroll_read_started = false;
        portEXIT_CRITICAL(&s_preroll_mux);
        return 0;
    }
    int n = (avail < (uint64_t)max_samples) ? (int)avail : max_samples;
    int idx = (int)(s_preroll_read_abs % WAKEUP_PREROLL_MAX_SAMPLES);
    for (int i = 0; i < n; i++) {
        dst[i] = s_preroll[idx];
        if (++idx >= WAKEUP_PREROLL_MAX_SAMPLES) idx = 0;
    }
    s_preroll_read_abs += (uint64_t)n;
    uint64_t remain = s_preroll_total - s_preroll_read_abs;
    s_preroll_len = (remain > (uint64_t)WAKEUP_PREROLL_MAX_SAMPLES)
                        ? WAKEUP_PREROLL_MAX_SAMPLES : (int)remain;
    if (s_preroll_read_abs >= s_preroll_total) {
        s_preroll_len = 0;
        s_preroll_armed = false;
        s_preroll_onset_valid = false;
        s_preroll_read_started = false;
    }
    portEXIT_CRITICAL(&s_preroll_mux);
    return n;
}

bool wakeup_take_barge_in(void)
{
    bool v = s_barge_in_pending;
    s_barge_in_pending = false;
    // 打断会话才放行预缓冲回灌；正常唤醒顺手清掉，免得把上一段 TTS 喂进 ASR
    if (v) {
        s_preroll_armed = true;
    } else {
        wakeup_preroll_clear();
    }
    return v;
}
