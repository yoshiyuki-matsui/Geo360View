/* Ubuntu FFmpeg 6 diagnostic only: change decoder threads in this process.
 * No FFmpeg struct layout is assumed: use public AVOption accessors.
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

int avcodec_open2(void *context, const void *codec, void **options)
{
    void *handle = dlopen("libavcodec.so.60", RTLD_LAZY | RTLD_NOLOAD);
    if (!handle) {
        fprintf(stderr, "geo360 probe: FFmpeg 6 library is not loaded\n");
        return -1;
    }
    int (*original)(void *, const void *, void **) = dlsym(handle, "avcodec_open2");
    int (*set_option)(void *, const char *, int64_t, int) = dlsym(handle, "av_opt_set_int");
    int (*get_option)(void *, const char *, int, int64_t *) = dlsym(handle, "av_opt_get_int");
    if (!original || !set_option || !get_option || original == avcodec_open2) {
        fprintf(stderr, "geo360 probe: could not resolve FFmpeg functions\n");
        return -1;
    }
    const char *value = getenv("GEO360_PROBE_THREADS");
    char *end = NULL;
    long requested = value ? strtol(value, &end, 10) : 0;
    if (!value || end == value || *end || requested < 1 || requested > 64) {
        fprintf(stderr, "geo360 probe: invalid thread count\n");
        return -1;
    }
    int64_t before = -1, after = -1;
    get_option(context, "threads", 0, &before);
    int result = set_option(context, "threads", requested, 0);
    if (result < 0) {
        fprintf(stderr, "geo360 probe: thread option rejected: %d\n", result);
        return result;
    }
    result = original(context, codec, options);
    get_option(context, "threads", 0, &after);
    fprintf(stderr, "geo360 probe: threads before=%lld requested=%ld actual=%lld open_result=%d\n",
            (long long)before, requested, (long long)after, result);
    return result;
}
