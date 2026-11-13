package org.localknowledge.library;

import java.io.File;
import java.io.IOException;

/** Android-independent rules for discovery throttling and path boundaries. */
final class ScanPolicy {
    static final class DiscoveryToken {
        private volatile boolean cancelled,complete;
        void cancel(){cancelled=true;}
        void finish(){complete=true;}
        boolean isComplete(){return complete;}
        boolean shouldStop(boolean paused,boolean chargingOnly,boolean plugged){return cancelled||paused||chargingOnly&&!plugged;}
    }
    static boolean mustDeferBackgroundIndexing(boolean uiVisible,boolean serviceRunning){return !uiVisible&&!serviceRunning;}
    static final long OPEN_THROTTLE_MS=15*60*1000L;
    static boolean autoCheckDue(long now,long last){return last<=0||now<last||now-last>=OPEN_THROTTLE_MS;}
    static boolean matches(File candidate,File rule,boolean folder)throws IOException {
        File file=candidate.getCanonicalFile(),canonical=rule.getCanonicalFile();
        return folder?file.toPath().startsWith(canonical.toPath()):file.equals(canonical);
    }
}
