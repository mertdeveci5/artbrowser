// QA only. This library is never installed in the daily ArtBrowser app.
#import <Foundation/Foundation.h>
#import <Security/Security.h>
#import <objc/runtime.h>
#import <objc/message.h>
#import <dlfcn.h>
#import <fcntl.h>
#import <unistd.h>
#import <errno.h>
#import <sys/socket.h>
#import <arpa/inet.h>

static void Record(NSString *event, NSDictionary *details) {
    const char *path = getenv("ARTBROWSER_QA_REPORT");
    if (!path) return;
    NSMutableDictionary *row = [details mutableCopy] ?: [NSMutableDictionary new];
    row[@"event"] = event; row[@"pid"] = @(getpid());
    row[@"process_time"] = @([NSDate date].timeIntervalSince1970);
    NSData *json = [NSJSONSerialization dataWithJSONObject:row options:0 error:NULL];
    NSMutableData *line = [json mutableCopy]; [line appendBytes:"\n" length:1];
    int fd = open(path, O_WRONLY | O_CREAT | O_APPEND, 0600);
    if (fd >= 0 && line) { write(fd, line.bytes, line.length); close(fd); }
}

static OSStatus NoCredentials(CFDictionaryRef query, CFTypeRef *result) {
    // Public certificates remain available for genuine HTTPS validation.
    if (query && CFEqual(CFDictionaryGetValue(query, kSecClass) ?: kCFNull, kSecClassCertificate))
        return SecItemCopyMatching(query, result);
    if (result) *result = NULL;
    Record(@"keychain_credential_read_denied", nil);
    return errSecItemNotFound;
}
static OSStatus NoAdd(CFDictionaryRef query, CFTypeRef *result) {
    (void)query; if (result) *result = NULL; return errSecInteractionNotAllowed;
}
static OSStatus NoUpdate(CFDictionaryRef query, CFDictionaryRef update) {
    (void)query; (void)update; return errSecInteractionNotAllowed;
}
static OSStatus NoDelete(CFDictionaryRef query) {
    (void)query; Record(@"keychain_delete_simulated",nil); return errSecSuccess;
}
static OSStatus NoLegacyRead(void *ignored, ...) {
    (void)ignored; Record(@"legacy_keychain_read_denied",nil); return errSecItemNotFound;
}
#define INTERPOSE(replacement, original) \
    __attribute__((used)) static struct { const void *replacement; const void *original; } \
    item_##original __attribute__((section("__DATA,__interpose"))) = { (const void *)&replacement, (const void *)&original }
INTERPOSE(NoCredentials, SecItemCopyMatching);
INTERPOSE(NoAdd, SecItemAdd);
INTERPOSE(NoUpdate, SecItemUpdate);
INTERPOSE(NoDelete, SecItemDelete);
INTERPOSE(NoLegacyRead, SecKeychainFindGenericPassword);
INTERPOSE(NoLegacyRead, SecKeychainFindInternetPassword);
INTERPOSE(NoLegacyRead, SecKeychainItemCopyContent);

@interface QARequestObserver : NSURLProtocol
@end
@implementation QARequestObserver
+ (BOOL)canInitWithRequest:(NSURLRequest *)request {
    if (request.URL.host) Record(@"native_http_host", @{@"host":request.URL.host});
    return NO;
}
+ (NSURLRequest *)canonicalRequestForRequest:(NSURLRequest *)request { return request; }
@end

static IMP DefaultConfiguration;
static IMP EphemeralConfiguration;
static id ProxyConfiguration(id receiver, SEL selector) {
    IMP original = selector == @selector(defaultSessionConfiguration) ? DefaultConfiguration : EphemeralConfiguration;
    NSURLSessionConfiguration *config = ((id (*)(id,SEL))original)(receiver,selector);
    NSMutableArray *protocols = [config.protocolClasses mutableCopy] ?: [NSMutableArray new];
    [protocols insertObject:QARequestObserver.class atIndex:0]; config.protocolClasses = protocols;
    NSInteger port = strtol(getenv("ARTBROWSER_QA_PROXY_PORT") ?: "0", NULL, 10);
    if (port) config.connectionProxyDictionary = @{@"HTTPEnable":@YES,@"HTTPProxy":@"127.0.0.1",@"HTTPPort":@(port),@"HTTPSEnable":@YES,@"HTTPSProxy":@"127.0.0.1",@"HTTPSPort":@(port)};
    return config;
}

static IMP OriginalCloudStart;
static IMP OriginalCurrentUser;
static id ObservedAuth;
static id CaptureCurrentUser(id auth,SEL selector){ObservedAuth=auth;return ((id (*)(id,SEL))OriginalCurrentUser)(auth,selector);}
static void CloudResponse(NSURLProtocol *protocol, SEL selector) {
    NSString *mode = [NSString stringWithUTF8String:getenv("ARTBROWSER_QA_RESPONSE") ?: "offline"];
    Record(@"cloud_request_intercepted", @{@"mode":mode,@"host":protocol.request.URL.host ?: @""});
    if ([mode isEqualToString:@"offline"] || [mode isEqualToString:@"timeout"]) { ((void (*)(id,SEL))OriginalCloudStart)(protocol,selector); return; }
    NSInteger status = [mode isEqualToString:@"disabled"] ? 400 : 410;
    NSString *message = [mode isEqualToString:@"disabled"] ? @"USER_DISABLED" : @"ACCOUNT_DELETED";
    NSData *body = [NSJSONSerialization dataWithJSONObject:@{@"error":@{@"code":@(status),@"message":message}} options:0 error:NULL];
    NSHTTPURLResponse *response = [[NSHTTPURLResponse alloc] initWithURL:protocol.request.URL statusCode:status HTTPVersion:@"HTTP/1.1" headerFields:@{@"Content-Type":@"application/json"}];
    [protocol.client URLProtocol:protocol didReceiveResponse:response cacheStoragePolicy:NSURLCacheStorageNotAllowed];
    [protocol.client URLProtocol:protocol didLoadData:body];
    [protocol.client URLProtocolDidFinishLoading:protocol];
}

static NSString *Constant(const char *name, NSString *fallback) {
    NSString *__unsafe_unretained *value = (NSString *__unsafe_unretained *)dlsym(RTLD_DEFAULT, name);
    return value && *value ? *value : fallback;
}

static void RevokeAuth(void) {
    @try {
        id auth = ObservedAuth;
        if (!auth) { Record(@"revocation_injection_failed",@{@"reason":@"no_auth_instance"}); return; }
        NSError *error = nil;
        BOOL result = ((BOOL (*)(id,SEL,NSError **))objc_msgSend)(auth,NSSelectorFromString(@"signOut:"),&error);
        Record(@"sdk_signout_injected", @{@"returned":@(result),@"error_code":@(error.code)});
        NSString *publicName = Constant("FIRAuthStateDidChangeNotification", @"FIRAuthStateDidChangeNotification");
        NSString *internalName = Constant("FIRAuthStateDidChangeInternalNotification", @"FIRAuthStateDidChangeInternalNotification");
        NSString *appKey = Constant("FIRAuthStateDidChangeInternalNotificationAppKey", @"FIRAuthStateDidChangeInternalNotificationAppKey");
        [NSNotificationCenter.defaultCenter postNotificationName:publicName object:auth userInfo:nil];
        NSString *appName=@"[DEFAULT]";
        @try { id app=[auth valueForKey:@"app"]; NSString *name=[app valueForKey:@"name"];if(name)appName=name; } @catch(NSException *ignored){}
        [NSNotificationCenter.defaultCenter postNotificationName:internalName object:auth userInfo:@{appKey:appName}];
        Record(@"signed_out_notifications_injected", nil);
    } @catch(NSException *exception) {
        Record(@"revocation_injection_failed", @{@"exception":exception.name});
    }
}

__attribute__((constructor)) static void ConfigureConditions(void) {
    @autoreleasepool {
        int (*sandboxCheck)(pid_t,const char *,int)=(int (*)(pid_t,const char *,int))dlsym(RTLD_DEFAULT,"sandbox_check");
        if (!sandboxCheck) {
            void *library=dlopen("/usr/lib/libsandbox.1.dylib",RTLD_NOW);
            sandboxCheck=(int (*)(pid_t,const char *,int))dlsym(library,"sandbox_check");
        }
        int sandboxed=sandboxCheck?sandboxCheck(getpid(),NULL,0):-1;
        int fd=open("/Applications/Arc.app/Contents/Info.plist",O_RDONLY);
        BOOL originalDenied=fd<0 && errno==EPERM;
        if(fd>=0)close(fd);
        NSString *live=[NSHomeDirectory() stringByAppendingPathComponent:@"Library/Application Support/ArtBrowser.noindex/Profile/StorableSidebar.json"];
        fd=open(live.fileSystemRepresentation,O_RDONLY);
        BOOL liveDenied=fd<0 && errno==EPERM;
        if(fd>=0)close(fd);
        int port=atoi(getenv("ARTBROWSER_QA_FORBIDDEN_PORT") ?: "0");
        int sock=socket(AF_INET,SOCK_STREAM,0);
        struct sockaddr_in address={0};address.sin_family=AF_INET;address.sin_port=htons(port);inet_pton(AF_INET,"127.0.0.1",&address.sin_addr);
        int connected=connect(sock,(struct sockaddr *)&address,sizeof(address));
        BOOL networkDenied=connected<0 && errno==EPERM;close(sock);
        NSString *role=NSClassFromString(@"FIRAuth")?@"main":@"helper";
        Record(@"runtime_isolation",@{@"role":role,@"sandbox_status":@(sandboxed),@"original_app_read_denied":@(originalDenied),@"live_profile_read_denied":@(liveDenied),@"forbidden_connect_denied":@(networkDenied)});
        if(sandboxed!=1 || !originalDenied || !liveDenied || !networkDenied)_exit(70);
        if (!NSClassFromString(@"FIRAuth")) return; // Main app only.
        Method user=class_getInstanceMethod(NSClassFromString(@"FIRAuth"),@selector(currentUser));
        OriginalCurrentUser=method_setImplementation(user,(IMP)CaptureCurrentUser);
        Method normal = class_getClassMethod(NSURLSessionConfiguration.class,@selector(defaultSessionConfiguration));
        Method ephemeral = class_getClassMethod(NSURLSessionConfiguration.class,@selector(ephemeralSessionConfiguration));
        DefaultConfiguration = method_setImplementation(normal,(IMP)ProxyConfiguration);
        EphemeralConfiguration = method_setImplementation(ephemeral,(IMP)ProxyConfiguration);
        Class blocked = NSClassFromString(@"ABDisabledCloudProtocol");
        Method start = class_getInstanceMethod(blocked,@selector(startLoading));
        if (start) OriginalCloudStart = method_setImplementation(start,(IMP)CloudResponse);
        Record(@"shutdown_conditions_active", @{@"saved_credentials_available":@NO});
        // Explicitly exercise the native interception path; this is a transport
        // probe, recorded separately from requests initiated by Arc itself.
        dispatch_after(dispatch_time(DISPATCH_TIME_NOW,5*NSEC_PER_SEC),dispatch_get_main_queue(),^{
            NSURL *url=[NSURL URLWithString:@"https://clientstream.launchdarkly.com/artbrowser-qa-probe"];
            [[NSURLSession.sharedSession dataTaskWithURL:url completionHandler:^(NSData *data,NSURLResponse *response,NSError *error){
                Record(@"transport_probe_completed",@{@"http_status":@([(NSHTTPURLResponse *)response statusCode]),@"error_code":@(error.code)});
            }] resume];
        });
        NSInteger seconds = strtol(getenv("ARTBROWSER_QA_REVOKE_AFTER") ?: "0",NULL,10);
        if (seconds > 0) dispatch_after(dispatch_time(DISPATCH_TIME_NOW,seconds*NSEC_PER_SEC),dispatch_get_main_queue(),^{RevokeAuth();});
    }
}
