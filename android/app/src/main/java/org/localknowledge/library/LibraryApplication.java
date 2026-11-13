package org.localknowledge.library;
import android.app.Application;
import java.util.concurrent.*;

public final class LibraryApplication extends Application {
    NativeBackend backend;
    final ExecutorService api=Executors.newFixedThreadPool(2);
    final ExecutorService metadataApi=Executors.newSingleThreadExecutor();
    @Override public void onCreate(){super.onCreate();NativeModels.configure(getApplicationInfo().nativeLibraryDir);backend=new NativeBackend(this);}
    @Override public void onTrimMemory(int level){super.onTrimMemory(level);if(level>=TRIM_MEMORY_RUNNING_LOW)api.submit(NativeModels::release);}
}
