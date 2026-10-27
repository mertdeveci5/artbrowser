// Local-only compatibility shim. Does not access Keychain or send network requests.
// Loaded only when ARTBROWSER_LOCAL_ONLY=1 is set by our test launcher.
#import <Foundation/Foundation.h>
#import <AppKit/AppKit.h>
#import <objc/runtime.h>
#import <stdlib.h>
#import <string.h>

static NSError *OfflineError(void) {
    return [NSError errorWithDomain:@"CKErrorDomain" code:3
                           userInfo:@{NSLocalizedDescriptionKey: @"Cloud services are disabled in this local copy."}];
}

@interface ABDisabledCloudProtocol : NSURLProtocol
@end
@implementation ABDisabledCloudProtocol
+ (BOOL)canInitWithRequest:(NSURLRequest *)request {
    NSString *host = request.URL.host.lowercaseString;
    while ([host hasSuffix:@"."]) host = [host substringToIndex:host.length - 1];
    for (NSString *domain in @[@"arc.net", @"thebrowser.company", @"diabrowser.com",
                               @"diabrowser.engineering", @"browserinternal.com", @"launchdarkly.com",
                               @"identitytoolkit.googleapis.com", @"securetoken.googleapis.com",
                               @"firestore.googleapis.com", @"firebaseinstallations.googleapis.com",
                               @"firebaseremoteconfig.googleapis.com", @"fcmregistrations.googleapis.com",
                               @"sentry.io", @"segment.io", @"segment.com", @"amplitude.com"]) {
        if ([host isEqualToString:domain] || [host hasSuffix:[@"." stringByAppendingString:domain]]) return YES;
    }
    return NO;
}
+ (NSURLRequest *)canonicalRequestForRequest:(NSURLRequest *)request { return request; }
- (void)startLoading {
    NSError *error = [NSError errorWithDomain:@"ArtBrowserLocalServices" code:1
                                     userInfo:@{NSLocalizedDescriptionKey: @"This local browser does not use Arc cloud services."}];
    [self.client URLProtocol:self didFailWithError:error];
}
- (void)stopLoading {}
@end

static IMP OriginalDefaultConfiguration;
static IMP OriginalEphemeralConfiguration;
static id LocalSessionConfiguration(id receiver, SEL selector) {
    IMP original = selector == @selector(defaultSessionConfiguration) ? OriginalDefaultConfiguration : OriginalEphemeralConfiguration;
    NSURLSessionConfiguration *configuration = ((id (*)(id, SEL))original)(receiver, selector);
    NSMutableArray *protocols = [configuration.protocolClasses mutableCopy] ?: [NSMutableArray new];
    [protocols removeObject:[ABDisabledCloudProtocol class]];
    [protocols insertObject:[ABDisabledCloudProtocol class] atIndex:0];
    configuration.protocolClasses = protocols;
    return configuration;
}

@interface ABOfflineCloudDatabase : NSObject
@end
@implementation ABOfflineCloudDatabase
- (NSInteger)databaseScope { return 2; }
- (void)addOperation:(id)operation {
    // No cloud operations are scheduled. The account status is NoAccount;
    // clients should stop their cloud workflows before reaching this point.
    (void)operation;
}
- (void)fetchRecordWithID:(id)record completionHandler:(void (^)(id, NSError *))completion {
    (void)record; if (completion) completion(nil, OfflineError());
}
- (void)saveRecord:(id)record completionHandler:(void (^)(id, NSError *))completion {
    (void)record; if (completion) completion(nil, OfflineError());
}
- (void)fetchAllRecordZonesWithCompletionHandler:(void (^)(id, NSError *))completion {
    if (completion) completion(nil, OfflineError());
}
- (NSMethodSignature *)methodSignatureForSelector:(SEL)selector {
    NSMethodSignature *signature = [super methodSignatureForSelector:selector];
    if (signature) return signature;
    Method method = class_getInstanceMethod(NSClassFromString(@"CKDatabase"), selector);
    return method ? [NSMethodSignature signatureWithObjCTypes:method_getTypeEncoding(method)] : nil;
}
- (void)forwardInvocation:(NSInvocation *)invocation {
    NSUInteger length = invocation.methodSignature.methodReturnLength;
    if (length) {
        void *zero = calloc(1, length);
        [invocation setReturnValue:zero];
        free(zero);
    }
}
@end

@interface ABOfflineCloudContainer : NSObject
@property(nonatomic, strong) ABOfflineCloudDatabase *database;
@end
@implementation ABOfflineCloudContainer
- (instancetype)init {
    if ((self = [super init])) _database = [ABOfflineCloudDatabase new];
    return self;
}
- (id)privateCloudDatabase { return self.database; }
- (id)publicCloudDatabase { return self.database; }
- (id)sharedCloudDatabase { return self.database; }
- (NSString *)containerIdentifier { return @"local.artbrowser.offline"; }
- (void)accountStatusWithCompletionHandler:(void (^)(NSInteger, NSError *))completion {
    if (completion) completion(3, nil); // CKAccountStatusNoAccount
}
- (void)fetchUserRecordIDWithCompletionHandler:(void (^)(id, NSError *))completion {
    if (completion) completion(nil, OfflineError());
}
- (void)addOperation:(id)operation { (void)operation; }
- (NSMethodSignature *)methodSignatureForSelector:(SEL)selector {
    NSMethodSignature *signature = [super methodSignatureForSelector:selector];
    if (signature) return signature;
    Method method = class_getInstanceMethod(NSClassFromString(@"CKContainer"), selector);
    return method ? [NSMethodSignature signatureWithObjCTypes:method_getTypeEncoding(method)] : nil;
}
- (void)forwardInvocation:(NSInvocation *)invocation {
    NSUInteger length = invocation.methodSignature.methodReturnLength;
    if (length) {
        void *zero = calloc(1, length);
        [invocation setReturnValue:zero];
        free(zero);
    }
}
@end

static id LocalContainer(id receiver, SEL selector, ...) {
    (void)receiver; (void)selector;
    static ABOfflineCloudContainer *container;
    static dispatch_once_t once;
    dispatch_once(&once, ^{ container = [ABOfflineCloudContainer new]; });
    return container;
}

static IMP OriginalAlertRunModal;
static NSModalResponse DiagnosticRunModal(NSAlert *alert, SEL selector) {
    fprintf(stderr, "[ArtBrowser startup alert] %s | %s\n",
            alert.messageText.UTF8String, alert.informativeText.UTF8String);
    return ((NSModalResponse (*)(id, SEL))OriginalAlertRunModal)(alert, selector);
}

@interface ABLocalUser : NSObject
@property(nonatomic, copy) NSDictionary *saved;
@end
@implementation ABLocalUser
- (NSString *)uid { return self.saved[@"id"]; }
- (NSString *)email { return self.saved[@"email"]; }
- (NSString *)displayName { return self.saved[@"name"]; }
- (NSURL *)photoURL { return nil; }
- (NSString *)providerID { return @"local"; }
- (NSArray *)providerData { return @[]; }
- (BOOL)isAnonymous { return NO; }
- (BOOL)isEmailVerified { return NO; }
- (id)metadata { return self; }
- (NSDate *)creationDate { return [NSDate dateWithTimeIntervalSinceReferenceDate:[self.saved[@"createdAt"] doubleValue]]; }
- (NSDate *)lastSignInDate { return self.creationDate; }
- (void)reloadWithCompletion:(void (^)(NSError *))completion { if (completion) completion(nil); }
- (void)getIDTokenWithCompletion:(void (^)(NSString *, NSError *))completion {
    if (completion) completion(nil, OfflineError());
}
- (void)getIDTokenForcingRefresh:(BOOL)refresh completion:(void (^)(NSString *, NSError *))completion {
    (void)refresh; [self getIDTokenWithCompletion:completion];
}
@end

static ABLocalUser *PreservedUser;

static id CurrentLocalUser(id receiver, SEL selector) {
    (void)receiver; (void)selector;
    return PreservedUser;
}

static id LocalAuthListener(id receiver, SEL selector, id listener) {
    // Report only preserved LOCAL metadata. No Firebase credentials, tokens,
    // authentication, or access to a remote account are fabricated.
    if (selector == NSSelectorFromString(@"addAuthStateDidChangeListener:") && PreservedUser && listener) {
        void (^callback)(id, id) = [listener copy];
        dispatch_async(dispatch_get_main_queue(), ^{ callback(receiver, PreservedUser); });
    }
    return [NSObject new];
}

static void RemoveLocalAuthListener(id receiver, SEL selector, id handle) {
    (void)receiver; (void)selector; (void)handle;
}

__attribute__((constructor)) static void InstallLocalServices(void) {
    const char *enabled = getenv("ARTBROWSER_LOCAL_ONLY");
    if (!enabled || strcmp(enabled, "1") != 0) return;
    @autoreleasepool {
        Class container = NSClassFromString(@"CKContainer");
        if (!container) return; // Chromium helpers do not use CloudKit.
        [NSURLProtocol registerClass:[ABDisabledCloudProtocol class]];
        Method defaultConfig = class_getClassMethod([NSURLSessionConfiguration class], @selector(defaultSessionConfiguration));
        Method ephemeralConfig = class_getClassMethod([NSURLSessionConfiguration class], @selector(ephemeralSessionConfiguration));
        OriginalDefaultConfiguration = method_setImplementation(defaultConfig, (IMP)LocalSessionConfiguration);
        OriginalEphemeralConfiguration = method_setImplementation(ephemeralConfig, (IMP)LocalSessionConfiguration);
        if (getenv("ARTBROWSER_DIAGNOSTICS")) {
            Method alert = class_getInstanceMethod(NSClassFromString(@"NSAlert"), @selector(runModal));
            if (alert) OriginalAlertRunModal = method_setImplementation(alert, (IMP)DiagnosticRunModal);
        }
        for (NSString *name in @[@"defaultContainer", @"containerWithIdentifier:"]) {
            Method method = class_getClassMethod(container, NSSelectorFromString(name));
            if (method) method_setImplementation(method, (IMP)LocalContainer);
        }
        Class auth = NSClassFromString(@"FIRAuth");
        const char *profile = getenv("ARTBROWSER_PROFILE");
        if (profile) {
            NSString *file = [[NSString stringWithUTF8String:profile] stringByAppendingPathComponent:@"StorableAuthState.json"];
            NSData *data = [NSData dataWithContentsOfFile:file];
            NSDictionary *state = data ? [NSJSONSerialization JSONObjectWithData:data options:0 error:NULL] : nil;
            NSDictionary *user = [state[@"session"] isKindOfClass:[NSDictionary class]] ? state[@"session"][@"user"] : nil;
            if ([user isKindOfClass:[NSDictionary class]] && [user[@"id"] isKindOfClass:[NSString class]] && [user[@"id"] length]) {
                PreservedUser = [ABLocalUser new]; PreservedUser.saved = user;
            }
        }
        NSUInteger authMethods = 0;
        Method currentUser = class_getInstanceMethod(auth, NSSelectorFromString(@"currentUser"));
        if (currentUser && PreservedUser) {
            method_setImplementation(currentUser, (IMP)CurrentLocalUser);
            authMethods++;
        }
        for (NSString *name in @[@"addAuthStateDidChangeListener:", @"addIDTokenDidChangeListener:"]) {
            Method method = class_getInstanceMethod(auth, NSSelectorFromString(name));
            if (method) { method_setImplementation(method, (IMP)LocalAuthListener); authMethods++; }
        }
        for (NSString *name in @[@"removeAuthStateDidChangeListener:", @"removeIDTokenDidChangeListener:"]) {
            Method method = class_getInstanceMethod(auth, NSSelectorFromString(name));
            if (method) { method_setImplementation(method, (IMP)RemoveLocalAuthListener); authMethods++; }
        }
        fprintf(stderr, "[ArtBrowser] Local services layer active; %lu auth observer methods isolated\n", (unsigned long)authMethods);
    }
}
