#import <AppKit/AppKit.h>
#import <Foundation/Foundation.h>
#import <fcntl.h>
#import <sys/stat.h>
#import <unistd.h>
#ifdef ARTBROWSER_QA
#import <sandbox.h>
#endif

#ifndef ARTBROWSER_PROFILE_DIRECTORY
#define ARTBROWSER_PROFILE_DIRECTORY @"ArtBrowser"
#endif

static int Fail(NSString *message) {
    [NSApplication sharedApplication];
    NSAlert *alert = [NSAlert new];
    alert.messageText = @"ArtBrowser could not start";
    alert.informativeText = message;
    [alert addButtonWithTitle:@"Quit"];
    [alert runModal];
    return 1;
}

int main(int argc, const char **argv) {
    @autoreleasepool {
        NSBundle *bundle = NSBundle.mainBundle;
#ifdef ARTBROWSER_QA
        NSData *settingsData=[NSData dataWithContentsOfFile:ARTBROWSER_QA_SETTINGS];
        NSDictionary *settings=settingsData?[NSJSONSerialization JSONObjectWithData:settingsData options:0 error:NULL]:nil;
        if(![settings isKindOfClass:NSDictionary.class])return Fail(@"QA launch settings are missing.");
        for(NSString *key in settings[@"environment"]){
            NSString *value=settings[@"environment"][key];
            if([key hasPrefix:@"ARTBROWSER_"] && [value isKindOfClass:NSString.class])setenv(key.UTF8String,value.UTF8String,1);
        }
#endif
        NSString *root = [NSHomeDirectory() stringByAppendingPathComponent:@"Library/Application Support"];
        NSString *profile = [root stringByAppendingPathComponent:ARTBROWSER_PROFILE_DIRECTORY];
        NSString *resolved = profile.stringByResolvingSymlinksInPath;
        NSString *original = [root stringByAppendingPathComponent:@"Arc"].stringByResolvingSymlinksInPath;
        if ([resolved isEqualToString:original] || [resolved hasPrefix:[original stringByAppendingString:@"/"]])
            return Fail(@"The local copy must use its own data folder. Your original Arc data has not been changed.");
        NSString *authFile = [profile stringByAppendingPathComponent:@"StorableAuthState.json"];
        NSData *authData = [NSData dataWithContentsOfFile:authFile];
        NSDictionary *auth = authData ? [NSJSONSerialization JSONObjectWithData:authData options:0 error:NULL] : nil;
        NSDictionary *session = [auth[@"session"] isKindOfClass:[NSDictionary class]] ? auth[@"session"] : nil;
        NSDictionary *user = [session[@"user"] isKindOfClass:[NSDictionary class]] ? session[@"user"] : nil;
        if (![user[@"id"] isKindOfClass:[NSString class]] || ![user[@"id"] length])
            return Fail(@"The saved local session is missing. Restore the preserved browser data before opening ArtBrowser.");
        if (![[NSFileManager defaultManager] fileExistsAtPath:[profile stringByAppendingPathComponent:@"StorableSidebar.json"]])
            return Fail(@"Your saved sidebar is missing. Restore the preserved browser data before opening ArtBrowser.");

        NSString *identifier = bundle.bundleIdentifier;
        for (NSRunningApplication *app in [NSRunningApplication runningApplicationsWithBundleIdentifier:identifier]) {
            if (app.processIdentifier != getpid() && !app.terminated) {
                [app activateWithOptions:NSApplicationActivateAllWindows];
                return 0;
            }
        }

        NSString *binary = [bundle.bundlePath stringByAppendingPathComponent:@"Contents/MacOS/ArcBinary"];
        NSString *library = [bundle.bundlePath stringByAppendingPathComponent:@"Contents/Frameworks/ArtBrowserLocalServices.dylib"];
        if (access(binary.fileSystemRepresentation, X_OK) || access(library.fileSystemRepresentation, R_OK))
            return Fail(@"The application is incomplete. Rebuild or restore ArtBrowser from the preserved copy.");

        NSString *logs = [root stringByAppendingPathComponent:@"ArtBrowserPreservation.noindex/logs"];
#ifdef ARTBROWSER_QA
        const char *qaLogs=getenv("ARTBROWSER_QA_LOG_DIRECTORY");
        if (!qaLogs) return Fail(@"The isolated QA log directory is missing.");
        logs=[NSString stringWithUTF8String:qaLogs];
#endif
        [[NSFileManager defaultManager] createDirectoryAtPath:logs withIntermediateDirectories:YES attributes:@{NSFilePosixPermissions:@0700} error:NULL];
        NSString *logFile = [logs stringByAppendingPathComponent:@"ArtBrowser.log"];
        int log = open(logFile.fileSystemRepresentation, O_WRONLY | O_CREAT | O_APPEND, 0600);
        if (log >= 0) { dup2(log, STDERR_FILENO); dup2(log, STDOUT_FILENO); close(log); }

        setenv("ARTBROWSER_LOCAL_ONLY", "1", 1);
        setenv("ARTBROWSER_PROFILE", profile.fileSystemRepresentation, 1);
        setenv("ARC_FAKE_AUTH", "1", 1);
        setenv("DYLD_INSERT_LIBRARIES", library.fileSystemRepresentation, 1);
#ifdef ARTBROWSER_QA
        // Compiled into the disposable QA launcher only, never the daily app.
        NSString *qaLibrary = [bundle.bundlePath stringByAppendingPathComponent:@"Contents/Frameworks/ShutdownConditions.dylib"];
        NSString *injected = [library stringByAppendingFormat:@":%@", qaLibrary];
        setenv("DYLD_INSERT_LIBRARIES", injected.fileSystemRepresentation, 1);
#endif
        unsetenv("ARC_UI_TESTS");
        NSMutableArray<NSString *> *arguments = [NSMutableArray arrayWithObject:binary];
        for (int i = 1; i < argc; i++) [arguments addObject:[NSString stringWithUTF8String:argv[i]]];
        [arguments addObjectsFromArray:@[@"--disable-sync", @"-cloudKitSyncEnabled", @"NO", @"-firebaseSyncEnabled", @"NO",
                                        @"-SUEnableAutomaticChecks", @"NO", @"-SUAutomaticallyUpdate", @"NO"]];
        if (getenv("ARTBROWSER_SMOKE_TEST")) {
            [arguments addObjectsFromArray:@[@"--use-mock-keychain", @"--disable-extensions", @"--disable-background-networking", @"--disable-component-update"]];
        }
        char **raw = calloc(arguments.count + 1, sizeof(char *));
        for (NSUInteger i = 0; i < arguments.count; i++) raw[i] = strdup(arguments[i].UTF8String);
#ifdef ARTBROWSER_QA
        NSString *policy=[NSString stringWithContentsOfFile:settings[@"policy"] encoding:NSUTF8StringEncoding error:NULL];
        char *sandboxError=NULL;
        if(!policy || sandbox_init(policy.UTF8String,0,&sandboxError)!=0){
            fprintf(stderr,"QA sandbox could not start: %s\n",sandboxError ?: "missing policy");
            if(sandboxError)sandbox_free_error(sandboxError);
            return 70;
        }
        for(NSString *argument in settings[@"arguments"])[arguments addObject:argument];
        free(raw);raw=calloc(arguments.count+1,sizeof(char *));
        for(NSUInteger i=0;i<arguments.count;i++)raw[i]=strdup(arguments[i].UTF8String);
#endif
        execv(binary.fileSystemRepresentation, raw);
        return Fail(@"The browser process could not be started. Your preserved data is still available.");
    }
}
