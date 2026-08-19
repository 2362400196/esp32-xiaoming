/**
 * @file lv_gifenc.c
 *
 */

/*********************
 *      INCLUDES
 *********************/
#include "../../misc/lv_timer_private.h"
#include "../../core/lv_obj_class_private.h"
#include "lv_gif_private.h"
#if LV_USE_GIF

#include "gifdec.h"
#include "esp_log.h"

/*********************
 *      DEFINES
 *********************/
#define MY_CLASS (&lv_gif_class)

/**********************
 *      TYPEDEFS
 **********************/

/**********************
 *  STATIC PROTOTYPES
 **********************/
static void lv_gif_constructor(const lv_obj_class_t * class_p, lv_obj_t * obj);
static void lv_gif_destructor(const lv_obj_class_t * class_p, lv_obj_t * obj);
static void next_frame_task_cb(lv_timer_t * t);

/**********************
 *  STATIC VARIABLES
 **********************/

const lv_obj_class_t lv_gif_class = {
    .constructor_cb = lv_gif_constructor,
    .destructor_cb = lv_gif_destructor,
    .instance_size = sizeof(lv_gif_t),
    .base_class = &lv_image_class,
    .name = "gif",
};

/**********************
 *      MACROS
 **********************/

/**********************
 *   GLOBAL FUNCTIONS
 **********************/

lv_obj_t * lv_gif_create(lv_obj_t * parent)
{

    LV_LOG_INFO("begin");
    lv_obj_t * obj = lv_obj_class_create_obj(MY_CLASS, parent);
    lv_obj_class_init_obj(obj);
    return obj;
}

void lv_gif_set_src(lv_obj_t * obj, const void * src)
{
    lv_gif_t * gifobj = (lv_gif_t *) obj;
    gd_GIF * gif = gifobj->gif;

    /*Close previous gif if any*/
    if(gif != NULL) {
        lv_image_cache_drop(lv_image_get_src(obj));

        gd_close_gif(gif);
        gifobj->gif = NULL;
        gifobj->imgdsc.data = NULL;
    }

    if(lv_image_src_get_type(src) == LV_IMAGE_SRC_VARIABLE) {
        const lv_image_dsc_t * img_dsc = src;
        gif = gd_open_gif_data(img_dsc->data, img_dsc->data_size);
    }
    else if(lv_image_src_get_type(src) == LV_IMAGE_SRC_FILE) {
        gif = gd_open_gif_file(src);
    }
    if(gif == NULL) {
        LV_LOG_WARN("Couldn't load the source");
        /* 修复：gif 加载失败时暂停 timer，避免 next_frame_task_cb 访问 NULL gif */
        lv_timer_pause(gifobj->timer);
        return;
    }

    gifobj->gif = gif;
    gifobj->imgdsc.data = gif->canvas;
    gifobj->imgdsc.header.magic = LV_IMAGE_HEADER_MAGIC;
    gifobj->imgdsc.header.flags = LV_IMAGE_FLAGS_MODIFIABLE;
    gifobj->imgdsc.header.cf = LV_COLOR_FORMAT_RGB565A8;
    gifobj->imgdsc.header.h = gif->height;
    gifobj->imgdsc.header.w = gif->width;
    gifobj->imgdsc.header.stride = gif->width * 2;  /* RGB565 stride (color part only) */
    gifobj->imgdsc.data_size = gif->width * gif->height * 3;  /* RGB565(2) + A8(1) = 3 bytes/pixel */

    gifobj->last_call = lv_tick_get();

    lv_image_set_src(obj, &gifobj->imgdsc);

    lv_timer_resume(gifobj->timer);
    lv_timer_reset(gifobj->timer);

    /* 强制即时解码第一帧：lv_gif_set_src 最后调用的 next_frame_task_cb 中
     * 由于 last_call 刚设为当前时间，帧延迟检查 (elaps < effective_delay)
     * 会直接 return，导致第一帧不解码，canvas 保持全空。
     * 此处将 last_call 置 0 使时间检查通过，确保第一帧立即解码。 */
    gifobj->last_call = 0;
    next_frame_task_cb(gifobj->timer);

}

void lv_gif_restart(lv_obj_t * obj)
{
    lv_gif_t * gifobj = (lv_gif_t *) obj;

    if(gifobj->gif == NULL) {
        LV_LOG_WARN("Gif resource not loaded correctly");
        return;
    }

    gd_rewind(gifobj->gif);
    lv_timer_resume(gifobj->timer);
    lv_timer_reset(gifobj->timer);
}

void lv_gif_pause(lv_obj_t * obj)
{
    lv_gif_t * gifobj = (lv_gif_t *) obj;
    lv_timer_pause(gifobj->timer);
}

void lv_gif_resume(lv_obj_t * obj)
{
    lv_gif_t * gifobj = (lv_gif_t *) obj;

    if(gifobj->gif == NULL) {
        LV_LOG_WARN("Gif resource not loaded correctly");
        return;
    }

    lv_timer_resume(gifobj->timer);
}

bool lv_gif_is_loaded(lv_obj_t * obj)
{
    lv_gif_t * gifobj = (lv_gif_t *) obj;

    return (gifobj->gif != NULL);
}

int32_t lv_gif_get_loop_count(lv_obj_t * obj)
{
    lv_gif_t * gifobj = (lv_gif_t *) obj;

    if(gifobj->gif == NULL) {
        return -1;
    }

    return gifobj->gif->loop_count;
}

void lv_gif_set_loop_count(lv_obj_t * obj, int32_t count)
{
    lv_gif_t * gifobj = (lv_gif_t *) obj;

    if(gifobj->gif == NULL) {
        LV_LOG_WARN("Gif resource not loaded correctly");
        return;
    }

    gifobj->gif->loop_count = count;
}

/**********************
 *   STATIC FUNCTIONS
 **********************/

static void lv_gif_constructor(const lv_obj_class_t * class_p, lv_obj_t * obj)
{
    LV_UNUSED(class_p);

    lv_gif_t * gifobj = (lv_gif_t *) obj;

    gifobj->gif = NULL;
    gifobj->timer = lv_timer_create(next_frame_task_cb, 10, obj);
    lv_timer_pause(gifobj->timer);
}

static void lv_gif_destructor(const lv_obj_class_t * class_p, lv_obj_t * obj)
{
    LV_UNUSED(class_p);
    lv_gif_t * gifobj = (lv_gif_t *) obj;

    lv_image_cache_drop(lv_image_get_src(obj));

    if(gifobj->gif)
        gd_close_gif(gifobj->gif);
    lv_timer_delete(gifobj->timer);
}

static void next_frame_task_cb(lv_timer_t * t)
{
    static int s_error_count = 0;  /* GIF 解码连续错误计数，超过阈值重新打开 GIF */

    lv_obj_t * obj = t->user_data;
    if(obj == NULL) return;
    if(!lv_obj_is_valid(obj)) return;  /* 对象已被删除，避免 use-after-free */
    lv_gif_t * gifobj = (lv_gif_t *) obj;
    /* 修复：gif 可能为 NULL（加载失败或正在切换），避免空指针崩溃 */
    if(gifobj->gif == NULL) return;
    if(gifobj->imgdsc.data == NULL) return;  /* 画布未就绪 */
    uint32_t elaps = lv_tick_elaps(gifobj->last_call);
    /* 使用 GIF 原始帧延迟，LZW bug 已修复无需加速 */
    uint32_t effective_delay = gifobj->gif->gce.delay * 10;
    if(effective_delay < 10) effective_delay = 10;  /* 防止 delay=0 导致死循环 */
    if(elaps < effective_delay) return;

    uint32_t t0 = lv_tick_get();
    gifobj->last_call = t0;

    int has_next = gd_get_frame(gifobj->gif);
    if(has_next == 0) {
        /*It was the last repeat*/
        s_error_count = 0;
        lv_obj_send_event(obj, LV_EVENT_READY, NULL);
        lv_timer_pause(t);
        return;  /* 修复：最后一帧后不再渲染，避免 gif->palette 为 NULL 导致崩溃 */
    }
    if(has_next < 0) {
        /* 解码错误：gd_GIF 结构体已在内部 RAM，错误应来自数据解析。
         * 连续错误超过 5 次时，完全重新打开 GIF 以重置所有状态 */
        s_error_count++;
        if(s_error_count > 5) {
            ESP_LOGW("lv_gif", "gd_get_frame failed %d times, reopening GIF", s_error_count);
            const void *saved_data = gifobj->gif->data;
            uint32_t saved_data_size = gifobj->gif->data_size;
            gd_close_gif(gifobj->gif);
            gifobj->gif = gd_open_gif_data(saved_data, saved_data_size);
            s_error_count = 0;
            if(gifobj->gif == NULL) {
                ESP_LOGE("lv_gif", "Failed to reopen GIF, pausing timer");
                lv_timer_pause(t);
                return;
            }
            gifobj->imgdsc.data = gifobj->gif->canvas;
        } else {
            ESP_LOGW("lv_gif", "gd_get_frame error %d, rewinding (f_rw_p=%u)",
                     s_error_count, (unsigned)gifobj->gif->f_rw_p);
            gd_rewind(gifobj->gif);
        }
        gifobj->last_call = lv_tick_get();
        return;
    }

    /* 成功解码，重置错误计数 */
    s_error_count = 0;

    uint32_t t1 = lv_tick_get();
    /* gd_GIF 结构体在内部 RAM，gif->canvas 指针安全可靠。
     * 同步 imgdsc.data 以防 lv_gif_t 对象中的该字段被 PSRAM 篡改 */
    if((uint8_t *)gifobj->imgdsc.data != gifobj->gif->canvas) {
        gifobj->imgdsc.data = gifobj->gif->canvas;
    }
    gd_render_frame(gifobj->gif, gifobj->gif->canvas);
    uint32_t t2 = lv_tick_get();

    /* 关键优化：移除 lv_image_cache_drop（每帧 drop+re-cache 是 GIF 卡顿的主因）
     * canvas 数据直接被修改，lv_obj_invalidate 足以触发重绘 */
    lv_obj_invalidate(obj);

    /* 性能日志：每 30 帧输出一次 */
    static int frame_count = 0;
    if(++frame_count % 30 == 0) {
        ESP_LOGI("lv_gif", "perf: get_frame=%lums render=%lums delay=%lu eff_delay=%lu elaps=%lu",
                 t1 - t0, t2 - t1, (unsigned long)gifobj->gif->gce.delay,
                 (unsigned long)effective_delay, elaps);
    }
}

#endif /*LV_USE_GIF*/
