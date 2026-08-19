#pragma once

#include <stdlib.h>

#ifdef __cplusplus
extern "C" {
#endif

static inline void* helix_malloc(int size) { return malloc(size); }
static inline void  helix_free(void *ptr)  { free(ptr); }

#ifdef __cplusplus
}
#endif
