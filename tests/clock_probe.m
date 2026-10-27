#import <Foundation/Foundation.h>
#import <sys/time.h>
#import <time.h>

int main(void) {
    @autoreleasepool {
        NSDate *date = NSDate.date;
        NSISO8601DateFormatter *formatter = [NSISO8601DateFormatter new];
        puts([[formatter stringFromDate:date] UTF8String]);
        struct timeval wall;
        struct timespec clock;
        gettimeofday(&wall, NULL);
        clock_gettime(CLOCK_REALTIME, &clock);
        if (date.timeIntervalSince1970 < 1797984000 || time(NULL) < 1797984000 || clock_gettime_nsec_np(CLOCK_REALTIME) < 1797984000ull * 1000000000ull || wall.tv_sec < 1797984000 || clock.tv_sec < 1797984000) return 1;
        puts("PASS: Foundation Date and C, time() and nsec wall clocks are after December 22, 2026");
    }
    return 0;
}
