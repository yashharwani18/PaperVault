package org.localknowledge.library;

import android.Manifest;
import android.content.*;
import android.content.pm.PackageManager;
import android.os.*;
import org.json.*;
import java.io.*;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicBoolean;

/** Opt-in shared-storage discovery; originals are read in place. */
final class PhoneScan {
    final NativeBackend b;final LibraryStore s;
    final ExecutorService discovery=Executors.newSingleThreadExecutor();
    final ScheduledExecutorService scheduler=Executors.newSingleThreadScheduledExecutor();
    static final long OPEN_THROTTLE_MS=ScanPolicy.OPEN_THROTTLE_MS;
    volatile boolean processingAllowed=false;
    final AtomicBoolean discoveryRunning=new AtomicBoolean();
    final Object exclusionLock=new Object();volatile ExclusionRules cachedExclusions;
    static final class ExclusionRule {
        final java.nio.file.Path path;final boolean folder;
        ExclusionRule(JSONObject rule)throws IOException {path=new File(rule.optString("path")).getCanonicalFile().toPath();folder=rule.optString("kind").equals("folder");}
    }
    static final class ExclusionRules {
        final String json;final List<ExclusionRule> rules;final boolean invalid;
        ExclusionRules(String source){JSONArray parsed;try{parsed=new JSONArray(source);}catch(JSONException ignored){parsed=new JSONArray();}json=parsed.toString();List<ExclusionRule> result=new ArrayList<>();boolean bad=false;for(JSONObject rule:LibraryStore.objects(parsed))try{result.add(new ExclusionRule(rule));}catch(IOException ignored){bad=true;}rules=Collections.unmodifiableList(result);invalid=bad;}
    }
    final Object timing=new Object();volatile long activeMillis=0,lastTick=0;volatile int initialReady=0;
    volatile boolean finding=false;volatile int directories=0,skipped=0;volatile long started=0,finished=0,indexFinished=0;volatile String error="";
    PhoneScan(NativeBackend backend){b=backend;s=b.store;s.exec("CREATE TABLE IF NOT EXISTS phone_scan_files(path TEXT PRIMARY KEY,signature TEXT,document_id TEXT,task_id TEXT,state TEXT,error TEXT)");scheduler.scheduleWithFixedDelay(()->{try{pump();}catch(Exception e){error="Some files could not be checked. Scan again or retry them in File progress.";}},1,1,TimeUnit.SECONDS);}
    static boolean access(Context c){return Build.VERSION.SDK_INT>=30?Environment.isExternalStorageManager():c.checkSelfPermission(Manifest.permission.READ_EXTERNAL_STORAGE)==PackageManager.PERMISSION_GRANTED;}
    boolean hasAccess(){return access(b.context);}
    static List<File> roots(Context c){LinkedHashSet<File> result=new LinkedHashSet<>();try{result.add(Environment.getExternalStorageDirectory().getCanonicalFile());for(File own:c.getExternalFilesDirs(null))if(own!=null){String path=own.getCanonicalPath();int mark=path.indexOf("/Android/");if(mark>0)result.add(new File(path.substring(0,mark)));}}catch(IOException ignored){}return new ArrayList<>(result);}
    static boolean allowedPath(Context c,File input){try{File file=input.getCanonicalFile();for(File root:roots(c)){if(file.toPath().startsWith(root.toPath())){String rel=root.toPath().relativize(file.toPath()).toString().replace('\\','/');if(rel.equals("Android/data")||rel.startsWith("Android/data/")||rel.equals("Android/obb")||rel.startsWith("Android/obb/"))return false;return true;}}}catch(IOException ignored){}return false;}
    String value(String key){JSONArray rows=s.query("SELECT value FROM settings WHERE key=?",key);return rows.length()==0?"":rows.optJSONObject(0).optString("value");}
    void set(String key,String value){if(key.equals("phone_scan.exclusions")){synchronized(exclusionLock){s.exec("INSERT OR REPLACE INTO settings VALUES(?,?)",key,value);cachedExclusions=null;}}else s.exec("INSERT OR REPLACE INTO settings VALUES(?,?)",key,value);}
    void start(){synchronized(b){processingAllowed=true;if(!hasAccess())throw new IllegalArgumentException("Allow file access in Android settings, then return to Khoj.");set("phone_scan.choice","yes");set("phone_scan.enabled","true");scanRoots(roots(b.context));service();}}
    void service(){try{b.context.startForegroundService(new Intent(b.context,ImportService.class));}catch(IllegalStateException ignored){}}
    void scanRoots(List<File> roots){processingAllowed=true;scanRoots(roots,null);}
    boolean scanRoots(List<File> roots,ScanPolicy.DiscoveryToken background){if(!hasAccess())throw new IllegalArgumentException("File access is required to scan this phone");if(!discoveryRunning.compareAndSet(false,true))return false;if(background!=null&&ScanPolicy.mustDeferBackgroundIndexing(b.uiVisible,ImportService.running))processingAllowed=false;finding=true;started=System.currentTimeMillis();activeMillis=0;lastTick=android.os.SystemClock.elapsedRealtime();initialReady=readyCount();finished=0;indexFinished=0;directories=0;skipped=0;error="";set("phone_scan.incomplete","true");discovery.submit(()->{
        Set<String> seen=new HashSet<>(),visited=new HashSet<>();ArrayDeque<File> pending=new ArrayDeque<>(roots);
        try{while(!pending.isEmpty()){
            if(stopBackground(background))return;
            if(!hasAccess())throw new IOException("File access was turned off. Allow access and scan again.");
            File dir=pending.removeFirst().getCanonicalFile();if(!allowedPath(b.context,dir)||isExcluded(dir)||!visited.add(dir.getPath()))continue;directories++;
            File[] children=dir.listFiles();if(children==null){skipped++;continue;}
            int childIndex=0;for(File child:children){if((childIndex++&31)==0&&stopBackground(background))return;try{File canonical=child.getCanonicalFile();if(!allowedPath(b.context,canonical)||isExcluded(canonical))continue;if(canonical.isDirectory()){pending.addLast(canonical);continue;}if(!canonical.getName().toLowerCase(Locale.ROOT).endsWith(".pdf")||!canonical.isFile())continue;String path=canonical.getPath();seen.add(path);String signature=canonical.length()+":"+canonical.lastModified();
                synchronized(b){if(isExcluded(canonical))continue;JSONArray prior=s.query("SELECT * FROM phone_scan_files WHERE path=?",path);
                if(prior.length()==0)s.exec("INSERT INTO phone_scan_files(path,signature,state) VALUES(?,?,'waiting')",path,signature);
                else{JSONObject old=prior.optJSONObject(0);if(old.optString("state").equals("excluded"))continue;if(!signature.equals(old.optString("signature"))&&!old.optString("state").equals("queued"))s.exec("UPDATE phone_scan_files SET signature=?,state='waiting',task_id=NULL,error=NULL WHERE path=?",signature,path);else if(old.optString("state").equals("missing"))s.exec("UPDATE phone_scan_files SET state='waiting',error=NULL WHERE path=?",path);}
            }}catch(SecurityException|IOException denied){skipped++;}}
        }
        // Only mark missing paths inside this scan's roots, preserving other volumes.
        for(JSONObject row:LibraryStore.objects(s.query("SELECT path FROM phone_scan_files"))){if(stopBackground(background))return;File f=new File(row.optString("path"));boolean scope=false;for(File root:roots)if(f.toPath().startsWith(root.getCanonicalFile().toPath()))scope=true;if(scope&&!isExcluded(f)&&!seen.contains(f.getPath()))s.exec("UPDATE phone_scan_files SET state='missing',error='Original unavailable' WHERE path=?",f.getPath());}
        if(stopBackground(background))return;set("phone_scan.incomplete","false");
        }catch(Exception e){error="The scan could not finish. Check file access and scan again.";}finally{finished=System.currentTimeMillis();set("phone_scan.last_elapsed",String.valueOf((finished-started)/1000));finding=false;discoveryRunning.set(false);if(background!=null)background.finish();}
    });return true;}
    boolean stopBackground(ScanPolicy.DiscoveryToken token){return token!=null&&token.shouldStop(b.paused,b.chargingOnly,!b.chargingOnly||b.plugged());}
    boolean pending(){return s.one("SELECT count(*) n FROM phone_scan_files WHERE state IN ('waiting','queued')").optInt("n")>0;}
    void pump()throws Exception {
        tick();
        for(JSONObject row:LibraryStore.objects(s.query("SELECT f.path FROM phone_scan_files f JOIN tasks t ON t.id=f.task_id WHERE f.state='excluded' AND t.status NOT IN ('queued','running','skipping')")))if(!isExcluded(new File(row.optString("path"))))s.exec("UPDATE phone_scan_files SET state='missing',task_id=NULL WHERE path=?",row.optString("path"));
        for(JSONObject row:LibraryStore.objects(s.query("SELECT f.path,f.signature,t.status,t.result,t.error FROM phone_scan_files f JOIN tasks t ON t.id=f.task_id WHERE f.state='queued'"))){if(isExcluded(new File(row.optString("path")))){s.exec("UPDATE phone_scan_files SET state='excluded' WHERE path=?",row.optString("path"));continue;}String status=row.optString("status");if(status.equals("skipped")){File file=new File(row.optString("path"));String state=file.isFile()&&!(file.length()+":"+file.lastModified()).equals(row.optString("signature"))?"waiting":"skipped";s.exec("UPDATE phone_scan_files SET state=?,task_id=NULL,error=NULL WHERE path=? AND state='queued'",state,row.optString("path"));}else if(status.equals("completed")){JSONObject result=Json.parse(row.optString("result"));s.exec("UPDATE phone_scan_files SET state='indexed',document_id=?,task_id=NULL,error=NULL WHERE path=? AND state='queued'",result.optJSONObject("document").optString("id"),row.optString("path"));}else if(status.equals("failed"))s.exec("UPDATE phone_scan_files SET state='failed',task_id=NULL,error=? WHERE path=? AND state='queued'",row.optString("error"),row.optString("path"));}
        if(!processingAllowed||!hasAccess()||b.paused||b.chargingOnly&&!b.plugged())return;
        int capacity=12-s.one("SELECT count(*) n FROM tasks WHERE status IN ('queued','running','skipping')").optInt("n");if(capacity<=0)return;
        for(JSONObject file:LibraryStore.objects(s.query("SELECT * FROM phone_scan_files WHERE state='waiting' LIMIT "+Math.min(12,capacity)))){
            synchronized(b){if(!processingAllowed||b.paused||b.chargingOnly&&!b.plugged())return;File source=new File(file.optString("path"));if(isExcluded(source)){s.exec("UPDATE phone_scan_files SET state='excluded' WHERE path=?",source.getPath());continue;}if(!allowedPath(b.context,source)||!source.isFile()){s.exec("UPDATE phone_scan_files SET state='missing' WHERE path=?",source.getPath());continue;}
            String docId=file.optString("document_id",""),folder=folder();if(!docId.isEmpty()&&!docId.equals("null")){JSONArray docs=s.query("SELECT id,folder_id,trashed FROM documents WHERE id=?",docId);if(docs.length()==0)docId="";else if(docs.optJSONObject(0).optInt("trashed")!=0){s.exec("UPDATE phone_scan_files SET state='excluded' WHERE path=?",source.getPath());continue;}else{folder=docs.optJSONObject(0).optString("folder_id");JSONObject document=s.document(docId);
                if(!document.optString("source_mode").equals("reference")||!document.optString("source_path").equals(source.getPath()))docId="";
                else for(JSONObject other:LibraryStore.objects(s.query("SELECT path FROM phone_scan_files WHERE document_id=? AND path!=? AND state='indexed'",docId,source.getPath()))){File alternative=new File(other.optString("path"));if(!isExcluded(alternative)&&alternative.isFile()&&LibraryStore.hash(alternative).equals(document.optString("sha256"))){s.exec("UPDATE documents SET source_path=?,preview_path=?,source_uri=?,version=version+1,updated_at=? WHERE id=?",alternative.getPath(),alternative.getPath(),android.net.Uri.fromFile(alternative).toString(),LibraryStore.now(),docId);docId="";break;}}
            }}else docId="";
            String task=b.enqueue(android.net.Uri.fromFile(source).toString(),source.getName(),folder,docId,true,false,true);s.exec("UPDATE phone_scan_files SET state='queued',task_id=?,error=NULL WHERE path=?",task,source.getPath());}
        }
    }
    String folder(){String id=value("phone_scan.folder");if(!id.isEmpty()&&s.query("SELECT id FROM folders WHERE id=?",id).length()>0)return id;id=LibraryStore.id();String now=LibraryStore.now(),name="From this phone";if(s.query("SELECT id FROM folders WHERE name=?",name).length()>0)name+=" · "+id.substring(0,4);s.exec("INSERT INTO folders VALUES(?,?,?,?,?)",id,name,"#A78BFA",now,now);set("phone_scan.folder",id);return id;}
    JSONObject status(){JSONObject counts=new JSONObject();int found=0;for(JSONObject row:LibraryStore.objects(s.query("SELECT state,count(*) n FROM phone_scan_files GROUP BY state")))try{counts.put(row.optString("state"),row.optInt("n"));if(!row.optString("state").equals("excluded"))found+=row.optInt("n");}catch(JSONException ignored){}if(started>0&&!finding&&!pending()&&indexFinished==0){indexFinished=System.currentTimeMillis();set("phone_scan.last_elapsed",String.valueOf((indexFinished-started)/1000));}long elapsed=started==0?0:((finding||pending()?System.currentTimeMillis():indexFinished)-started)/1000;if(started==0)try{elapsed=Long.parseLong(value("phone_scan.last_elapsed"));}catch(NumberFormatException ignored){}tick();int remaining=counts.optInt("waiting")+counts.optInt("queued"),completed=Math.max(0,counts.optInt("indexed")-initialReady);Object eta=started>0&&activeMillis>0&&!finding&&remaining>0&&completed>=3?Math.round((activeMillis/1000.0)*remaining/completed):JSONObject.NULL;
        String stage=b.paused?"paused":!hasAccess()?"permission_required":b.chargingOnly&&!b.plugged()?"waiting_for_power":finding?"discovering":remaining>0?(!processingAllowed?"waiting_for_open":"indexing"):"complete";
        return Json.obj("remaining",remaining,"eta_s",eta,"stage",stage,"active_elapsed_s",activeMillis/1000,"choice",value("phone_scan.choice"),"permission",hasAccess(),"finding",finding,"pending",pending(),"paused",b.paused,"found",found,"counts",counts,"directories",directories,"skipped",skipped,"elapsed_s",Math.max(0,elapsed),"error",error);}
    void resume(){updateSchedule();}
    void onAppOpen(){processingAllowed=true;updateSchedule();if(!value("phone_scan.choice").equals("yes")||!value("phone_scan.enabled").equals("true")||!hasAccess())return;
        long now=System.currentTimeMillis(),last=0;if(started==0&&pending()){started=now;initialReady=readyCount();activeMillis=0;lastTick=android.os.SystemClock.elapsedRealtime();indexFinished=0;}try{last=Long.parseLong(value("phone_scan.last_auto"));}catch(NumberFormatException ignored){}
        if(!b.paused&&(!b.chargingOnly||b.plugged())&&(value("phone_scan.incomplete").equals("true")||value("phone_scan.auto_scan_on_open").equals("true")&&autoCheckDue(now,last))){set("phone_scan.last_auto",String.valueOf(now));scanRoots(roots(b.context));}
        if(finding||pending())service();
    }
    static boolean autoCheckDue(long now,long last){return ScanPolicy.autoCheckDue(now,last);}
    boolean scheduledDiscovery(){return scheduledDiscovery(new ScanPolicy.DiscoveryToken());}
    boolean scheduledDiscovery(ScanPolicy.DiscoveryToken token){if(!value("phone_scan.choice").equals("yes")||!value("phone_scan.enabled").equals("true")||!value("phone_scan.scheduled_scan").equals("true")||!hasAccess()||b.paused||b.chargingOnly&&!b.plugged())return false;if(stopBackground(token))return false;return scanRoots(roots(b.context),token);}
    void updateSchedule(){ScanWorker.configure(b.context,value("phone_scan.scheduled_scan").equals("true")&&value("phone_scan.choice").equals("yes"),b.chargingOnly);}
    ExclusionRules exclusionRules(){ExclusionRules result=cachedExclusions;if(result==null)synchronized(exclusionLock){result=cachedExclusions;if(result==null){result=new ExclusionRules(value("phone_scan.exclusions"));cachedExclusions=result;}}return result;}
    JSONArray exclusions(){try{return new JSONArray(exclusionRules().json);}catch(JSONException ignored){return new JSONArray();}}
    static boolean matches(File candidate,File rule,boolean folder)throws IOException {return ScanPolicy.matches(candidate,rule,folder);}
    boolean isExcluded(File file){ExclusionRules rules=exclusionRules();if(rules.invalid)return true;if(rules.rules.isEmpty())return false;try{java.nio.file.Path candidate=file.getCanonicalFile().toPath();for(ExclusionRule rule:rules.rules)if(rule.folder?candidate.startsWith(rule.path):candidate.equals(rule.path))return true;}catch(IOException ignored){return true;}return false;}
    JSONArray visibleDocuments(JSONArray docs){JSONArray visible=new JSONArray();for(JSONObject doc:LibraryStore.objects(docs))if(!doc.optString("source_mode").equals("reference")||!isExcluded(new File(doc.optString("source_path"))))visible.put(doc);return visible;}
    static String observedModifiedAt(String signature){
        try{String[] parts=signature.split(":",2);if(parts.length!=2||Long.parseLong(parts[0])<0)return null;long time=Long.parseLong(parts[1]);return time>0?java.time.Instant.ofEpochMilli(time).toString():null;}
        catch(RuntimeException error){return null;}
    }
    JSONArray attachModifiedTimes(JSONArray documents)throws JSONException {
        Map<String,String> times=new HashMap<>();for(JSONObject row:LibraryStore.objects(s.query("SELECT document_id,path,signature FROM phone_scan_files WHERE document_id IS NOT NULL"))){
            String time=observedModifiedAt(row.optString("signature"));if(time!=null)times.put(row.optString("document_id")+"\n"+row.optString("path"),time);
        }
        Map<String,JSONObject> recorded=new HashMap<>();for(JSONObject row:LibraryStore.objects(s.query("SELECT key,value FROM settings WHERE key LIKE 'khoj.modified:%'")))try{recorded.put(row.optString("key").substring("khoj.modified:".length()),Json.parse(row.optString("value")));}catch(Exception ignored){}
        for(JSONObject doc:LibraryStore.objects(documents)){String time=doc.optString("source_mode").equals("reference")?times.get(doc.optString("id")+"\n"+doc.optString("source_path")):null;
            JSONObject observed=recorded.get(doc.optString("id"));if(time==null&&observed!=null&&observed.optString("sha256").equals(doc.optString("sha256")))try{long ms=observed.optLong("epoch_ms");if(ms>0)time=java.time.Instant.ofEpochMilli(ms).toString();}catch(RuntimeException ignored){}
            doc.put("modified_at",time==null?JSONObject.NULL:time);}
        return documents;
    }
    JSONObject options(){return Json.obj("auto_scan_on_open",value("phone_scan.auto_scan_on_open").equals("true"),"scheduled_scan",value("phone_scan.scheduled_scan").equals("true"),"exclusions",exclusions());}
    JSONObject route(String route,String method,JSONObject body)throws Exception {
        if(route.equals("/phone-scan/options")){if(method.equals("PATCH")){for(String key:new String[]{"auto_scan_on_open","scheduled_scan"})if(body.has(key)){if(!(body.get(key) instanceof Boolean))throw new IllegalArgumentException("Choose true or false for scan options");set("phone_scan."+key,String.valueOf(body.getBoolean(key)));}updateSchedule();}else if(!method.equals("GET"))throw new IllegalArgumentException("Unsupported scan options action");return options();}
        if(route.equals("/phone-scan/exclude-document")){if(!method.equals("POST"))throw new IllegalArgumentException("Unsupported exclusion action");JSONObject doc=s.document(body.optString("document_id"));if(!doc.optString("source_mode").equals("reference"))throw new IllegalArgumentException("Only scanned originals can be ignored");body=Json.obj("path",doc.optString("source_path"),"kind","file");route="/phone-scan/exclusions";}
        if(!route.equals("/phone-scan/exclusions"))return null;
        if(!method.equals("POST")&&!method.equals("DELETE"))throw new IllegalArgumentException("Unsupported exclusion action");
        String kind=body.optString("kind"),path=body.optString("path");if(!kind.equals("file")&&!kind.equals("folder"))throw new IllegalArgumentException("Choose a file or folder");if(path.isEmpty()||!new File(path).isAbsolute())throw new IllegalArgumentException("Choose a shared-storage file or folder");File file=new File(path).getCanonicalFile();if(!allowedPath(b.context,file))throw new IllegalArgumentException("Choose a supported shared-storage location");
        synchronized(b){JSONArray rules=new JSONArray();for(JSONObject rule:LibraryStore.objects(exclusions()))if(!rule.optString("path").equals(file.getPath())||!rule.optString("kind").equals(kind))rules.put(rule);if(method.equals("POST"))rules.put(Json.obj("path",file.getPath(),"kind",kind));set("phone_scan.exclusions",rules.toString());
            for(JSONObject row:LibraryStore.objects(s.query("SELECT path,state,task_id FROM phone_scan_files"))){String source=row.optString("path");if(isExcluded(new File(source)))s.exec("UPDATE phone_scan_files SET state='excluded' WHERE path=?",source);else if(method.equals("DELETE")&&row.optString("state").equals("excluded")){// Do not re-enqueue an old in-flight job when removing a rule.
                String task=row.optString("task_id");JSONArray tasks=s.query("SELECT status FROM tasks WHERE id=?",task);if(tasks.length()>0&&(tasks.optJSONObject(0).optString("status").equals("running")||tasks.optJSONObject(0).optString("status").equals("queued")))continue;
                s.exec("UPDATE phone_scan_files SET state='missing',task_id=NULL WHERE path=?",source);
            }}
        }return options();
    }
    int readyCount(){return s.one("SELECT count(*) n FROM phone_scan_files WHERE state='indexed'").optInt("n");}
    void tick(){synchronized(timing){long now=android.os.SystemClock.elapsedRealtime();if(lastTick>0&&started>0&&(finding||pending())&&processingAllowed&&!b.paused&&(!b.chargingOnly||b.plugged()))activeMillis+=Math.max(0,now-lastTick);lastTick=now;}}

}
