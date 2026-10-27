// Prints "pid layer width height" for every on-screen window. Needs no permissions.
#include <CoreGraphics/CoreGraphics.h>
#include <stdio.h>

int main(void) {
    CFArrayRef list = CGWindowListCopyWindowInfo(kCGWindowListOptionOnScreenOnly, kCGNullWindowID);
    if (!list) return 1;
    for (CFIndex i = 0; i < CFArrayGetCount(list); i++) {
        CFDictionaryRef window = CFArrayGetValueAtIndex(list, i);
        int pid = 0, layer = -1;
        CFNumberRef number = CFDictionaryGetValue(window, kCGWindowOwnerPID);
        if (number) CFNumberGetValue(number, kCFNumberIntType, &pid);
        number = CFDictionaryGetValue(window, kCGWindowLayer);
        if (number) CFNumberGetValue(number, kCFNumberIntType, &layer);
        CGRect bounds = CGRectZero;
        CFDictionaryRef box = CFDictionaryGetValue(window, kCGWindowBounds);
        if (box) CGRectMakeWithDictionaryRepresentation(box, &bounds);
        printf("%d %d %.0f %.0f\n", pid, layer, bounds.size.width, bounds.size.height);
    }
    CFRelease(list);
    return 0;
}
