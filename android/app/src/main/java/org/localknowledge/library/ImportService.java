package org.localknowledge.library;

import android.app.*;

import android.content.Intent;

import android.os.*;



public final class ImportService extends Service {
    static volatile boolean running;

    static final String ACTION_PAUSE="org.localknowledge.library.PAUSE_IMPORTS",ACTION_RESUME="org.localknowledge.library.RESUME_IMPORTS";

    final Handler handler=new Handler(Looper.getMainLooper());

    NativeBackend backend;
    PowerManager.WakeLock indexingWakeLock;long wakeRenewAt;

    void releaseWakeLock(){if(indexingWakeLock!=null&&indexingWakeLock.isHeld())indexingWakeLock.release();wakeRenewAt=0;}
    void updateWakeLock(){
        if(backend.paused||backend.closed||(backend.chargingOnly&&!backend.plugged())){releaseWakeLock();return;}
        boolean work=AndroidSharing.active()||backend.phoneScan.finding||backend.store.one("SELECT count(*) n FROM tasks WHERE status IN ('queued','running','skipping')").optInt("n")>0;
        if(!work){releaseWakeLock();return;}
        if(indexingWakeLock==null){indexingWakeLock=getSystemService(PowerManager.class).newWakeLock(PowerManager.PARTIAL_WAKE_LOCK,"PaperVault:Indexing");indexingWakeLock.setReferenceCounted(false);}
        long now=SystemClock.elapsedRealtime();
        if(!indexingWakeLock.isHeld()||now>=wakeRenewAt){indexingWakeLock.acquire(10*60*1000L);wakeRenewAt=now+5*60*1000L;}
    }

    final Runnable refresh=new Runnable(){public void run(){if(backend.idle()){releaseWakeLock();stopForeground(STOP_FOREGROUND_REMOVE);stopSelf();return;}updateWakeLock();getSystemService(NotificationManager.class).notify(41,notification());handler.postDelayed(this,3000);}};

    @Override public void onCreate(){super.onCreate();running=true;backend=((LibraryApplication)getApplication()).backend;NotificationManager manager=getSystemService(NotificationManager.class);manager.createNotificationChannel(new NotificationChannel("imports","Document imports",NotificationManager.IMPORTANCE_LOW));startForeground(41,notification());updateWakeLock();handler.postDelayed(refresh,1500);}

    Notification notification(){

        PendingIntent open=PendingIntent.getActivity(this,0,new Intent(this,MainActivity.class),PendingIntent.FLAG_IMMUTABLE|PendingIntent.FLAG_UPDATE_CURRENT);

        org.json.JSONObject scan=backend.phoneScan.status();int found=scan.optInt("found"),remaining=scan.optInt("remaining");

        String text=AndroidSharing.active()?"Adding shared PDFs":backend.paused?"Indexing paused":backend.chargingOnly&&!backend.plugged()?"Waiting for external power":scan.optBoolean("finding")?"Finding PDFs on this phone":remaining>0?remaining+" files left to index":"Reading and indexing on this phone";

        if(!scan.isNull("eta_s")&&!backend.paused)text+=" · about "+Math.max(1,(scan.optLong("eta_s")+59)/60)+" min left";

        PendingIntent control=PendingIntent.getService(this,backend.paused?2:1,new Intent(this,ImportService.class).setAction(backend.paused?ACTION_RESUME:ACTION_PAUSE),PendingIntent.FLAG_IMMUTABLE|PendingIntent.FLAG_UPDATE_CURRENT);

        Notification.Builder builder=new Notification.Builder(this,"imports").setSmallIcon(org.localknowledge.library.R.drawable.ic_library).setContentTitle("PaperVault").setContentText(text).setContentIntent(open).setOngoing(true)

            .addAction(new Notification.Action.Builder(null,backend.paused?"Resume":"Pause",control).build());

        if(found>0)builder.setProgress(found,Math.max(0,found-remaining),scan.optBoolean("finding"));

        return builder.build();

    }

    @Override public int onStartCommand(Intent intent,int flags,int startId){if(intent!=null){if(AndroidSharing.ACTION_CAPTURE.equals(intent.getAction()))AndroidSharing.capture(this,backend,intent);if(ACTION_PAUSE.equals(intent.getAction()))backend.paused=true;else if(ACTION_RESUME.equals(intent.getAction())){backend.paused=false;backend.phoneScan.processingAllowed=true;}if(ACTION_PAUSE.equals(intent.getAction())||ACTION_RESUME.equals(intent.getAction()))backend.phoneScan.set("processing.paused",String.valueOf(backend.paused));}updateWakeLock();getSystemService(NotificationManager.class).notify(41,notification());return START_NOT_STICKY;}

    @Override public void onTimeout(int startId,int type){backend.paused=true;releaseWakeLock();backend.phoneScan.set("processing.paused","true");stopForeground(STOP_FOREGROUND_REMOVE);stopSelf();}

    @Override public void onDestroy(){running=false;releaseWakeLock();handler.removeCallbacks(refresh);super.onDestroy();}

    @Override public IBinder onBind(Intent intent){return null;}

}

