#import <CloudKit/CloudKit.h>
#import <Foundation/Foundation.h>

@interface FIRAuth : NSObject
- (id)currentUser;
- (id)addAuthStateDidChangeListener:(void (^)(id, id))listener;
- (void)removeAuthStateDidChangeListener:(id)handle;
@end
@implementation FIRAuth
- (id)currentUser { return nil; }
- (id)addAuthStateDidChangeListener:(void (^)(id, id))listener { listener(self, nil); return [NSObject new]; }
- (void)removeAuthStateDidChangeListener:(id)handle { (void)handle; }
@end

int main(void) {
    @autoreleasepool {
        __block NSInteger status = -1;
        CKContainer *first = [CKContainer defaultContainer];
        CKContainer *second = [CKContainer containerWithIdentifier:@"iCloud.net.arc.sidebar"];
        [first accountStatusWithCompletionHandler:^(CKAccountStatus result, NSError *error) {
            if (error) exit(2);
            status = result;
        }];
        if (!first || !second || !first.privateCloudDatabase || status != CKAccountStatusNoAccount) return 1;
        puts("PASS: default and named containers report NoAccount without CloudKit initialization");
        if (getenv("ARTBROWSER_PROFILE")) {
            FIRAuth *auth = [FIRAuth new];
            id user = auth.currentUser;
            if (![[user valueForKey:@"uid"] isEqualToString:@"local-test-user"]) return 3;
            __block BOOL delivered = NO;
            [auth addAuthStateDidChangeListener:^(id source, id currentUser) {
                delivered = source == auth && currentUser == user;
            }];
            NSDate *deadline = [NSDate dateWithTimeIntervalSinceNow:2];
            while (!delivered && deadline.timeIntervalSinceNow > 0) [[NSRunLoop currentRunLoop] runUntilDate:[NSDate dateWithTimeIntervalSinceNow:0.01]];
            if (!delivered) return 4;
            puts("PASS: copied local metadata supplies a local user and observer notification");
        }
        Class protocol = NSClassFromString(@"ABDisabledCloudProtocol");
        if (![(id)protocol canInitWithRequest:[NSURLRequest requestWithURL:[NSURL URLWithString:@"https://releases.arc.net/updates.xml"]]]) return 5;
        if ([(id)protocol canInitWithRequest:[NSURLRequest requestWithURL:[NSURL URLWithString:@"https://example.com/"]]]) return 6;
        if ([(id)protocol canInitWithRequest:[NSURLRequest requestWithURL:[NSURL URLWithString:@"https://notarc.net/"]]]) return 7;
        __block BOOL blocked = NO;
        NSURLSession *session = [NSURLSession sessionWithConfiguration:NSURLSessionConfiguration.ephemeralSessionConfiguration];
        [[session dataTaskWithURL:[NSURL URLWithString:@"https://securetoken.googleapis.com/v1/token"] completionHandler:^(NSData *data, NSURLResponse *response, NSError *error) {
            blocked = [error.domain isEqualToString:@"ArtBrowserLocalServices"];
        }] resume];
        NSDate *deadline = [NSDate dateWithTimeIntervalSinceNow:3];
        while (!blocked && deadline.timeIntervalSinceNow > 0) [[NSRunLoop currentRunLoop] runUntilDate:[NSDate dateWithTimeIntervalSinceNow:0.01]];
        if (!blocked) return 8;
        puts("PASS: native cloud request rejected by local protocol; ordinary sites allowed");
    }
    return 0;
}
