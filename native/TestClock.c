// QA only: process-scoped wall-clock shift. Never included in ArtBrowser.app.
#include <stdlib.h>
#include <stdint.h>
#include <stdio.h>
#include <sys/time.h>
#include <time.h>

static int64_t shift;

static int shifted_gettimeofday(struct timeval *value, void *zone) {
    int result = gettimeofday(value, zone);
    if (!result && value) value->tv_sec += shift;
    return result;
}

static int shifted_clock_gettime(clockid_t clock, struct timespec *value) {
    int result = clock_gettime(clock, value);
    if (!result && value && clock == CLOCK_REALTIME) value->tv_sec += shift;
    return result;
}

static time_t shifted_time(time_t *out) {
    time_t now = time(NULL) + shift;
    if (out) *out = now;
    return now;
}

static uint64_t shifted_clock_gettime_nsec_np(clockid_t clock) {
    uint64_t value = clock_gettime_nsec_np(clock);
    return clock == CLOCK_REALTIME ? value + (uint64_t)shift * 1000000000ull : value;
}

#define INTERPOSE(replacement, original) \
    __attribute__((used)) static struct { const void *new_function; const void *old_function; } \
    pair_##original __attribute__((section("__DATA,__interpose"))) = \
    { (const void *)(uintptr_t)&replacement, (const void *)(uintptr_t)&original }

INTERPOSE(shifted_gettimeofday, gettimeofday);
INTERPOSE(shifted_clock_gettime, clock_gettime);
INTERPOSE(shifted_time, time);
INTERPOSE(shifted_clock_gettime_nsec_np, clock_gettime_nsec_np);

__attribute__((constructor)) static void configure_test_clock(void) {
    const char *value = getenv("ARTBROWSER_QA_DATE_SHIFT");
    if (value) shift = strtoll(value, NULL, 10);
    struct timespec now;
    shifted_clock_gettime(CLOCK_REALTIME, &now);
    struct tm date;
    gmtime_r(&now.tv_sec, &date);
    fprintf(stderr, "[ArtBrowser QA] Process date %04d-%02d-%02d; host clock unchanged\n", date.tm_year + 1900, date.tm_mon + 1, date.tm_mday);
}
