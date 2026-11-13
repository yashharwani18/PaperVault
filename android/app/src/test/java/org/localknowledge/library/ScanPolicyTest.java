package org.localknowledge.library;
import java.io.File;
import org.junit.Test;
import static org.junit.Assert.*;
public class ScanPolicyTest {
    @Test public void folderBoundariesAndCanonicalPaths()throws Exception {
        File root=new File(System.getProperty("java.io.tmpdir"),"scan-ignore");
        assertTrue(ScanPolicy.matches(new File(root,"nested/a.pdf"),root,true));
        assertTrue(ScanPolicy.matches(new File(root,"../scan-ignore/a.pdf"),root,true));
        assertFalse(ScanPolicy.matches(new File(root.getPath()+"-other/a.pdf"),root,true));
        assertFalse(ScanPolicy.matches(new File(root,"a.pdf"),root,false));
        assertTrue(ScanPolicy.matches(new File(root,"a.pdf"),new File(root,"a.pdf"),false));
    }
    @Test public void opensAreThrottledAndClockRollbackRecovers(){
        assertTrue(ScanPolicy.autoCheckDue(100,0));assertFalse(ScanPolicy.autoCheckDue(101,100));
        assertFalse(ScanPolicy.autoCheckDue(100+ScanPolicy.OPEN_THROTTLE_MS-1,100));
        assertTrue(ScanPolicy.autoCheckDue(100+ScanPolicy.OPEN_THROTTLE_MS,100));assertTrue(ScanPolicy.autoCheckDue(90,100));
    }
    @Test public void backgroundRunsDeferOnlyWithoutAnAllowedForegroundContext(){
        assertFalse(ScanPolicy.mustDeferBackgroundIndexing(true,false));
        assertFalse(ScanPolicy.mustDeferBackgroundIndexing(false,true));
        assertFalse(ScanPolicy.mustDeferBackgroundIndexing(true,true));
        assertTrue(ScanPolicy.mustDeferBackgroundIndexing(false,false));
    }
    @Test public void cancellationIsOwnedByOneDiscoveryAndPowerPauseStopIt(){
        ScanPolicy.DiscoveryToken first=new ScanPolicy.DiscoveryToken(),second=new ScanPolicy.DiscoveryToken();
        assertFalse(first.shouldStop(false,false,false));
        assertTrue(first.shouldStop(true,false,true));
        assertTrue(first.shouldStop(false,true,false));
        assertFalse(first.shouldStop(false,true,true));
        first.cancel();assertTrue(first.shouldStop(false,false,true));
        assertFalse(second.shouldStop(false,false,true));
        first.finish();assertTrue(first.isComplete());assertFalse(second.isComplete());
    }
}
