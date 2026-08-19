#pragma once

#include <stdint.h>
#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
    int sample_rate;
    int channels;
    int bitrate;
} mp3_decoder_info_t;

typedef void *mp3_decoder_handle_t;

mp3_decoder_handle_t mp3_decoder_init(void);
int mp3_decoder_find_sync(const uint8_t *buf, int len);
int mp3_decoder_decode_frame(mp3_decoder_handle_t handle,
                              uint8_t **inbuf, int *bytesLeft,
                              short *outbuf, int *outSamps);
int mp3_decoder_get_info(mp3_decoder_handle_t handle, mp3_decoder_info_t *info);
void mp3_decoder_free(mp3_decoder_handle_t handle);

#ifdef __cplusplus
}
#endif
