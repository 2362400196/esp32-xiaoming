#include "mp3_decoder_wrapper.h"
#include "mp3dec.h"
#include <stdlib.h>
#include <string.h>

mp3_decoder_handle_t mp3_decoder_init(void)
{
    return (mp3_decoder_handle_t)MP3InitDecoder();
}

int mp3_decoder_find_sync(const uint8_t *buf, int len)
{
    return MP3FindSyncWord((unsigned char *)buf, len);
}

int mp3_decoder_decode_frame(mp3_decoder_handle_t handle,
                              uint8_t **inbuf, int *bytesLeft,
                              short *outbuf, int *outSamps)
{
    int ret = MP3Decode((HMP3Decoder)handle,
                         (unsigned char **)inbuf, bytesLeft,
                         outbuf, 0);
    if (ret == 0) {
        MP3FrameInfo info;
        MP3GetLastFrameInfo((HMP3Decoder)handle, &info);
        *outSamps = info.outputSamps;
    }
    return ret;
}

int mp3_decoder_get_info(mp3_decoder_handle_t handle, mp3_decoder_info_t *info)
{
    if (!handle || !info) return -1;
    MP3FrameInfo frame_info;
    MP3GetLastFrameInfo((HMP3Decoder)handle, &frame_info);
    info->sample_rate = frame_info.samprate;
    info->channels = frame_info.nChans;
    info->bitrate = frame_info.bitrate;
    return 0;
}

void mp3_decoder_free(mp3_decoder_handle_t handle)
{
    if (handle) {
        MP3FreeDecoder((HMP3Decoder)handle);
    }
}
