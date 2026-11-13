package org.localknowledge.library;

import android.content.*;
import android.net.Uri;
import java.lang.ref.WeakReference;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicInteger;

/** Forward URI grants to the service so closing the Activity does not revoke capture access. */
final class AndroidSharing {
    static final String ACTION_CAPTURE="org.localknowledge.library.CAPTURE_PDFS";
    static final AtomicInteger pending=new AtomicInteger();
    static final ExecutorService copies=Executors.newSingleThreadExecutor();
    static volatile WeakReference<MainActivity> foreground=new WeakReference<>(null);
    static volatile String message="";
    static boolean active(){return pending.get()>0;}
    static void attach(MainActivity activity){foreground=new WeakReference<>(activity);deliver();}
    static void detach(MainActivity activity){if(foreground.get()==activity)foreground.clear();}
    static void deliver(){MainActivity activity=foreground.get();if(activity!=null&&!message.isEmpty()&&activity.pageReady){String text=message;message="";activity.libraryChanged(text);}}
    static void forward(MainActivity activity,Intent original){
        List<Uri> uris=SharedImports.uris(original);if(uris.isEmpty()){activity.libraryChanged("Choose a PDF in the sharing app, then share it with Khoj.");return;}
        ClipData clip=new ClipData("Shared PDFs",new String[]{"application/pdf"},new ClipData.Item(uris.get(0)));for(int i=1;i<uris.size();i++)clip.addItem(new ClipData.Item(uris.get(i)));
        Intent service=new Intent(activity,ImportService.class).setAction(ACTION_CAPTURE).addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION).putParcelableArrayListExtra(Intent.EXTRA_STREAM,new ArrayList<>(uris));service.setClipData(clip);
        pending.incrementAndGet();try{activity.startForegroundService(service);activity.libraryChanged("Adding shared PDFs…");}catch(RuntimeException error){pending.decrementAndGet();activity.libraryChanged("Keep Khoj open and share those PDFs again.");}
    }
    static void capture(Context context,NativeBackend backend,Intent intent){
        ArrayList<Uri> uris=intent.getParcelableArrayListExtra(Intent.EXTRA_STREAM);copies.submit(()->{
            try{message=SharedImports.capture(context,backend,uris).optString("message","PDFs added to Khoj.");}
            catch(Exception error){message="Could not add those PDFs. Check the files in the sharing app and try again.";}
            finally{pending.updateAndGet(n->Math.max(0,n-1));MainActivity activity=foreground.get();if(activity!=null)activity.runOnUiThread(AndroidSharing::deliver);}
        });
    }
}
