package org.localknowledge.library;
import android.content.Context;
import android.os.*;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import org.junit.Test;
import org.junit.runner.RunWith;
import static org.junit.Assert.*;

@RunWith(AndroidJUnit4.class)
public class AndroidShareFlowTest {
    @Test public void capturesBothExternalGrantsEvenAfterActivityCloses()throws Exception {
        var instrumentation=InstrumentationRegistry.getInstrumentation();Context c=instrumentation.getTargetContext();NativeBackend b=((LibraryApplication)c.getApplicationContext()).backend;boolean paused=b.paused;String run=Long.toUnsignedString(System.nanoTime());
        if(Build.VERSION.SDK_INT>=33)instrumentation.getUiAutomation().grantRuntimePermission(c.getPackageName(),"android.permission.POST_NOTIFICATIONS");b.paused=true;
        try{
            try(ParcelFileDescriptor output=instrumentation.getUiAutomation().executeShellCommand("am start -n org.localknowledge.library.test/org.localknowledge.library.ShareSenderActivity --es run "+run)){try(var in=new ParcelFileDescriptor.AutoCloseInputStream(output)){in.readAllBytes();}}
            long deadline=System.currentTimeMillis()+30000;while(!AndroidSharing.active()&&System.currentTimeMillis()<deadline)Thread.sleep(25);assertTrue("Share was not forwarded to the foreground service",AndroidSharing.active());
            instrumentation.runOnMainSync(()->{MainActivity activity=AndroidSharing.foreground.get();if(activity!=null)activity.finish();});
            while(AndroidSharing.active()&&System.currentTimeMillis()<deadline)Thread.sleep(50);assertFalse("Temporary URI capture timed out",AndroidSharing.active());
            var tasks=b.store.query("SELECT filename,source_path FROM tasks WHERE filename LIKE ?","grant-"+run+"-%");assertEquals("Both grants must outlive the receiver Activity",2,tasks.length());for(int i=0;i<tasks.length();i++)assertTrue(new java.io.File(tasks.optJSONObject(i).optString("source_path")).isFile());
        }finally{b.paused=paused;}
    }
}
