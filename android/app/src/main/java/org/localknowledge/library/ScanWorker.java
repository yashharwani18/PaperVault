package org.localknowledge.library;

import android.content.Context;
import androidx.annotation.NonNull;
import androidx.work.*;
import java.util.concurrent.TimeUnit;

/** WorkManager only discovers files. Indexing resumes when the user opens Khoj. */
public final class ScanWorker extends Worker {
    final ScanPolicy.DiscoveryToken discoveryToken=new ScanPolicy.DiscoveryToken();
    static final String NAME="phone-pdf-discovery";
    public ScanWorker(@NonNull Context context,@NonNull WorkerParameters params){super(context,params);}
    static void configure(Context context,boolean enabled,boolean chargingOnly){
        WorkManager manager=WorkManager.getInstance(context);
        if(!enabled){manager.cancelUniqueWork(NAME);return;}
        Constraints constraints=new Constraints.Builder().setRequiresCharging(chargingOnly).build();
        PeriodicWorkRequest request=new PeriodicWorkRequest.Builder(ScanWorker.class,12,TimeUnit.HOURS).setConstraints(constraints).build();
        manager.enqueueUniquePeriodicWork(NAME,ExistingPeriodicWorkPolicy.UPDATE,request);
    }
    @Override public void onStopped(){discoveryToken.cancel();super.onStopped();}
    @NonNull @Override public Result doWork(){
        NativeBackend backend=((LibraryApplication)getApplicationContext()).backend;
        if(backend==null)return Result.retry();
        PhoneScan scan=backend.phoneScan;
        if(!scan.scheduledDiscovery(discoveryToken))return Result.success();
        try{while(!discoveryToken.isComplete()&&!isStopped())Thread.sleep(200);if(isStopped()){discoveryToken.cancel();return Result.retry();}return Result.success();}
        catch(InterruptedException e){discoveryToken.cancel();Thread.currentThread().interrupt();return Result.retry();}
    }
}
