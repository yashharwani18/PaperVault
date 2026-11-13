package org.localknowledge.library;

import android.content.*;
import android.database.Cursor;
import android.database.sqlite.SQLiteDatabase;
import android.database.sqlite.SQLiteStatement;
import android.net.Uri;
import android.os.BatteryManager;
import android.os.Debug;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.FloatBuffer;
import androidx.documentfile.provider.DocumentFile;
import org.json.*;
import java.io.*;
import java.math.BigDecimal;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.regex.*;

final class NativeBackend {
    final Context context;final LibraryStore store;final ModelAssets models;
    final ExecutorService indexing=Executors.newSingleThreadExecutor();
    final AtomicInteger searches=new AtomicInteger();volatile boolean paused=false,chargingOnly=false,closed=false;
    String progressTask="",progressStage="";long progressAt;
    final ThreadLocal<String> activeImport=new ThreadLocal<>();
    static final class IndexSkipped extends RuntimeException {IndexSkipped(){super("Skipped by you; original file retained.");}}
    final String token=LibraryStore.id();
    final AndroidEmbeddingUpgrade embeddingUpgrade;
    final KhojFeatures features;final SmartTopics smartTopics;final PhoneScan phoneScan;final LibraryQoL libraryQoL;
    boolean importsResumed;volatile boolean uiVisible;
    String linkKey="";JSONArray linkCache=null;
    NativeBackend(Context context){this.context=context;store=new LibraryStore(context);models=new ModelAssets(context);embeddingUpgrade=new AndroidEmbeddingUpgrade(this);
        store.exec("UPDATE tasks SET status='skipped',error=NULL WHERE status='skipping'");
        store.exec("UPDATE tasks SET status='interrupted',error='The app stopped before indexing finished. Retry to continue.' WHERE status IN ('queued','running')");
        JSONArray settings=store.query("SELECT value FROM settings WHERE key='charging_only'");chargingOnly=settings.length()>0&&settings.optJSONObject(0).optString("value").equals("true");features=new KhojFeatures(this);smartTopics=new SmartTopics(this);phoneScan=new PhoneScan(this);libraryQoL=new LibraryQoL(this);paused=phoneScan.value("processing.paused").equals("true");phoneScan.resume();}
    void onAppOpen(){synchronized(this){if(!importsResumed){indexing.submit(()->{try{embeddingUpgrade.ensure();}catch(Exception ignored){}});features.resume();importsResumed=true;}}phoneScan.onAppOpen();}
    boolean plugged(){Intent battery=context.registerReceiver(null,new IntentFilter(Intent.ACTION_BATTERY_CHANGED));return battery==null||battery.getIntExtra(BatteryManager.EXTRA_PLUGGED,0)!=0;}
    JSONObject processing(){return Json.obj("embedding_upgrade",embeddingUpgrade.status(),"paused",paused,"charging_only",chargingOnly,"battery_available",true,"power_plugged",plugged(),"waiting_for_power",chargingOnly&&!plugged(),"process_rss_bytes",Debug.getPss()*1024L,"search_priority",true);}
    JSONObject modelStatus(){return Json.obj("available",models.state.equals("ready"),"model","Qwen3 0.6B","download_bytes",484220320,"thinking",false,"local_only",true);}
    JSONObject state()throws Exception{return state("",true);}
    JSONObject state(String knownRevision)throws Exception{return state(knownRevision,true);}
    JSONObject state(String knownRevision,boolean includeDocuments)throws Exception{JSONArray documents=phoneScan.attachModifiedTimes(phoneScan.visibleDocuments(store.documents())),bills=new JSONArray();Set<String> visible=new HashSet<>();int pages=0;for(JSONObject doc:LibraryStore.objects(documents)){decorateTextSource(doc);pages+=doc.optInt("page_count");visible.add(doc.optString("id"));}for(JSONObject bill:LibraryStore.objects(store.bills()))if(visible.contains(bill.optString("document_id")))bills.put(bill);
        JSONArray decorated=includeDocuments?features.decorate(documents):null;String revision=includeDocuments?LibraryStore.hash(decorated.toString().getBytes(StandardCharsets.UTF_8)):"";
        return Json.obj("folders",store.folders(),"documents",!includeDocuments||revision.equals(knownRevision)?JSONObject.NULL:decorated,"documents_revision",revision,"library_page",Json.obj("sorts",Json.arr("added_new","added_old","name","name_desc","size_large","size_small"),"filters",Json.arr("folder","extension","status","added","size","favorites","recent","name"),"candidates",false),"bills",bills,"tasks",store.tasks(),"token",token,"trash",store.query("SELECT id,filename,updated_at deleted_at FROM documents WHERE trashed=1"),
            "aliases",aliases(),"linked_folders",linkedFolders(),"topic_suggestions",smartTopics.status(),"processing",processing(),"ocr_available",true,"powerpoint_available",true,"local_only",true,
            "import_capabilities",Json.obj("upload_extensions",Json.arr("pdf","pptx","docx","xlsx","txt","md","csv","tsv"),"folder_extensions",Json.arr("pdf","pptx","docx","xlsx","txt","md","csv","tsv"),"scan_extensions",Json.arr("pdf"),"share_extensions",Json.arr("pdf")),
            "query_interpreter",modelStatus(),"semantic_status",Json.obj("state",models.state,"error",models.error),"voice_available",AndroidVoiceInput.capabilities(context).optBoolean("available"),"voice",AndroidVoiceInput.capabilities(context),
            "stats",Json.obj("documents",documents.length(),"pages",pages,"database_bytes",context.getDatabasePath("library.sqlite3").length(),"embedding_runtime",Json.obj("model_loads",0)));
    }
    synchronized JSONObject dispatch(String path,String method,JSONObject body)throws Exception {
        Uri uri=Uri.parse(path);String route=uri.getPath();if(route.startsWith("/api"))route=route.substring(4);String[] parts=route.split("/");
        if(parts.length==4&&parts[1].equals("tasks")&&parts[3].equals("skip")&&method.equals("POST"))return skipTask(parts[2]);
        JSONObject reading=libraryQoL.route(route,method,body);if(reading!=null)return reading;
        JSONObject scanning=phoneScan.route(route,method,body);if(scanning!=null)return scanning;
        JSONObject feature=features.route(route,method,body);if(feature!=null)return feature;
        if(route.equals("/phone-scan"))return phoneScan.status();
        if(route.equals("/phone-scan/skip")){phoneScan.set("phone_scan.choice","no");return phoneScan.status();}
        if(route.equals("/phone-scan/pause")){paused=body.optBoolean("paused");phoneScan.set("processing.paused",String.valueOf(paused));if(!paused){phoneScan.processingAllowed=true;phoneScan.service();}return phoneScan.status();}
        if(route.equals("/phone-scan/retry")){store.exec("UPDATE phone_scan_files SET state='waiting',task_id=NULL,error=NULL WHERE state='failed'");phoneScan.service();return phoneScan.status();}
        if(route.equals("/state"))return state(param(uri,"documents_revision",""),!param(uri,"include_documents","true").equals("false"));
        if(route.equals("/library-page")&&method.equals("POST"))return NativeLibraryBrowse.page(this,body);
        if(route.equals("/models/warmup"))return Json.obj("state",models.state,"error",models.error);
        if(route.equals("/filename-matches")&&method.equals("POST"))return filenameMatches(body);
        if(route.equals("/search")){searches.incrementAndGet();try{return search(body);}finally{searches.decrementAndGet();}}
        if(route.equals("/folders")&&method.equals("POST")){String name=name(body.optString("name"));String id=LibraryStore.id(),now=LibraryStore.now();store.exec("INSERT INTO folders VALUES(?,?,?,?,?)",id,name,color(body.optString("color","#A78BFA")),now,now);return store.one("SELECT * FROM folders WHERE id=?",id);}
        if(parts.length==3&&parts[1].equals("folders")){
            if(method.equals("DELETE")){if(store.one("SELECT count(*) n FROM documents WHERE folder_id=?",parts[2]).optInt("n")>0)throw new IllegalArgumentException("Move or remove documents before deleting this folder");store.exec("DELETE FROM folders WHERE id=?",parts[2]);return Json.obj("deleted",true);}
            JSONObject old=store.one("SELECT * FROM folders WHERE id=?",parts[2]);store.exec("UPDATE folders SET name=?,color=?,updated_at=? WHERE id=?",name(body.optString("name",old.optString("name"))),color(body.optString("color",old.optString("color"))),LibraryStore.now(),parts[2]);return store.one("SELECT * FROM folders WHERE id=?",parts[2]);
        }
        if(route.equals("/tasks/status")){Set<String> wanted=strings(body.optJSONArray("ids"));JSONArray out=new JSONArray();for(JSONObject task:LibraryStore.objects(store.tasks()))if(wanted.contains(task.optString("id")))out.put(task);return Json.obj("__array",out);}
        if(parts.length==4&&parts[1].equals("tasks")&&parts[3].equals("retry"))return Json.obj("task_id",features.retry(parts[2]));
        if(parts.length>=3&&parts[1].equals("documents")){
            String id=parts[2];JSONObject doc=store.document(id);
            if(parts.length==3&&method.equals("GET")){JSONArray pages=store.query(isTextFormat(doc.optString("format"))?"SELECT page_number,page_number unit_number,evidence FROM pages WHERE document_id=? ORDER BY page_number":"SELECT page_number,page_number unit_number FROM pages WHERE document_id=? ORDER BY page_number",id);if(isTextFormat(doc.optString("format")))for(JSONObject item:LibraryStore.objects(pages)){JSONObject location=textLocation(Json.parse(item.optString("evidence","{}")),item.optInt("page_number"));item.put("location",location);item.put("location_label",location.optString("label"));item.remove("evidence");}return Json.obj("document",decorateTextSource(doc),"pages",pages,"original",null);}
            if(parts.length==5&&parts[3].equals("units")&&method.equals("GET")){String revision=param(uri,"revision","");if(!revision.isEmpty()&&!revision.equals(doc.optString("sha256")))throw new IllegalArgumentException("This document changed. Open its latest version.");int number=Integer.parseInt(parts[4]);JSONObject unit=page(id,number);unit.put("unit_number",number);JSONObject location=textLocation(unit.optJSONObject("evidence"),number);unit.put("location",location);unit.put("location_label",location.optString("label"));return unit;}
            if(parts.length==3&&method.equals("DELETE")){store.exec("UPDATE documents SET trashed=1,updated_at=? WHERE id=?",LibraryStore.now(),id);return Json.obj("recoverable",true);}
            if(parts.length==4&&parts[3].equals("move")){store.one("SELECT id FROM folders WHERE id=?",body.optString("folder_id"));store.exec("UPDATE documents SET folder_id=?,updated_at=? WHERE id=?",body.optString("folder_id"),LibraryStore.now(),id);return store.document(id);}
            if(parts.length==4&&parts[3].equals("refresh-ocr")&&isTextFormat(doc.optString("format")))throw new IllegalArgumentException("OCR is available for scanned PDFs, not text documents.");
            if(parts.length==4&&(parts[3].equals("refresh")||parts[3].equals("refresh-ocr")))return Json.obj("task_id",enqueue(doc.optString("source_uri"),doc.optString("filename"),doc.optString("folder_id"),id,parts[3].equals("refresh-ocr"),store.bill(id)!=null,doc.optString("source_mode").equals("reference"),parts[3].equals("refresh-ocr")));
            if(parts.length==4&&parts[3].equals("bill")){
                if(method.equals("PUT"))return saveBill(id,body);
                JSONObject saved=store.bill(id);return Json.obj("saved",saved,"suggested",suggest(id));}
            if(parts.length==5&&parts[3].equals("bill")&&parts[4].equals("undo"))return undoBill(id);
            if(parts.length==4&&parts[3].equals("checks"))return checks(id);
            if(parts.length==4&&parts[3].equals("pages"))return Json.obj("__array",store.query("SELECT page_number,page_number page_label,method,length(text) characters,'ok' status FROM pages WHERE document_id=? ORDER BY page_number",id));
            if(parts.length==5&&parts[3].equals("pages"))return page(id,Integer.parseInt(parts[4]));
            if(parts.length==4&&parts[3].equals("highlight"))return highlight(id,Integer.parseInt(param(uri,"page","1")),param(uri,"text",""));
            if(parts.length==4&&parts[3].equals("evidence")){JSONObject p=page(id,Integer.parseInt(param(uri,"page","1")));String value=param(uri,"value","");JSONObject h=highlight(id,p.optInt("page_number"),value);return Json.obj("text",p.optString("text"),"method",p.optString("method"),"value",value,"boxes",h.optJSONArray("boxes"),"found",p.optString("text").contains(value),"page",p.optInt("page_number"));}
            if(parts.length==4&&parts[3].equals("tables"))return Json.obj("tables",new JSONArray(),"note","Check the original table layout; text-only table reconstruction is not verified.");
        }
        if(route.equals("/auditor/skipped-files")){
            int needsOcr=0,corrupt=0,partial=0;JSONArray docs=new JSONArray();
            for(JSONObject doc:LibraryStore.objects(store.documents())){
                String st=doc.optString("status");
                if(st.equals("needs_ocr")||st.equals("partial")||st.equals("empty")||st.equals("extraction_failed")){
                    if(st.equals("needs_ocr"))needsOcr++;
                    else if(st.equals("partial"))partial++;
                    else corrupt++;
                    docs.put(Json.obj("id",doc.optString("id"),"filename",doc.optString("filename"),"title",doc.optString("title"),"folder_name",doc.optString("folder_name"),"status",st,"size_bytes",doc.optLong("size_bytes"),"page_count",doc.optInt("page_count"),"reason",st.equals("needs_ocr")?"Scanned or image-only pages; run OCR to index text":st.equals("partial")?"Only first 5 pages indexed so far":"Empty or unreadable content"));
                }
            }
            int failedTasks=0;JSONArray failedT=new JSONArray();
            for(JSONObject t:LibraryStore.objects(store.tasks())){
                String st=t.optString("status");
                if(st.equals("failed")||st.equals("interrupted")){
                    failedTasks++;
                    failedT.put(Json.obj("id",t.optString("id"),"filename",t.optString("filename"),"status",st,"error",t.optString("error","Task was interrupted or failed")));
                }
            }
            JSONObject summary=Json.obj("total_skipped",docs.length()+failedTasks,"needs_ocr",needsOcr,"unreadable_or_corrupt",corrupt,"partial",partial,"failed_tasks",failedTasks,"locked",0);
            return Json.obj("summary",summary,"documents",docs,"tasks",failedT,"discovered",new JSONArray());
        }
        if(route.equals("/workspace"))return Json.obj("linked_folders",linkedFolders(),"duplicates",duplicates(),"processing",processing(),"voice",Json.obj("note","Voice prefers on-device recognition. Android speech fallback may use internet; document search stays on this phone."),"models",Json.obj("query",modelStatus(),"embedding",Json.obj("model_id","google/embeddinggemma-2 text (LiteRT INT4)")));
        if(route.equals("/linked-folders/rebuild"))return Json.obj("linked_folders",linkedFolders());
        if(route.equals("/processing")){paused=body.optBoolean("paused");phoneScan.set("processing.paused",String.valueOf(paused));chargingOnly=body.optBoolean("charging_only",chargingOnly);store.exec("INSERT OR REPLACE INTO settings VALUES('charging_only',?)",String.valueOf(chargingOnly));phoneScan.updateSchedule();return processing();}
        if(route.equals("/compare"))return compare(body);
        if(route.equals("/party-aliases")){String alias=normalize(body.optString("alias")),party=body.optString("party").trim();if(alias.isEmpty()||party.isEmpty())throw new IllegalArgumentException("Enter an alias and party");store.exec("INSERT OR REPLACE INTO aliases VALUES(?,?)",alias,party);return Json.obj("saved",true);}
        if(parts.length==3&&parts[1].equals("party-aliases")){store.exec("DELETE FROM aliases WHERE alias=?",Uri.decode(parts[2]));return Json.obj("removed",true);}
        if(route.equals("/feedback")){if(method.equals("POST")){store.exec("INSERT INTO feedback VALUES(?,?,?)",LibraryStore.id(),LibraryStore.now(),body.toString());return Json.obj("saved",true);}return Json.obj("__array",store.query("SELECT id,created_at,payload FROM feedback ORDER BY created_at DESC"));}
        if(parts.length>=3&&parts[1].equals("trash")){String id=parts[2];if(method.equals("DELETE")){if(!body.optString("confirmation").equals("DELETE PERMANENTLY"))throw new IllegalArgumentException("Type DELETE PERMANENTLY");store.exec("DELETE FROM documents WHERE id=? AND trashed=1",id);}else{if(body.has("folder_id")&&!body.isNull("folder_id"))store.exec("UPDATE documents SET folder_id=? WHERE id=?",body.optString("folder_id"),id);store.exec("UPDATE documents SET trashed=0,updated_at=? WHERE id=?",LibraryStore.now(),id);}return Json.obj("saved",true);}
        if(route.equals("/maintenance"))return storage();
        if(route.equals("/verify-backup-readiness"))return verify();
        if(route.equals("/cleanup")){if(!body.optString("confirmation").equals("CLEAN UNUSED PDFS"))throw new IllegalArgumentException("Type CLEAN UNUSED PDFS");return cleanup();}
        throw new IllegalArgumentException("This action is unavailable in this Android build: "+route);
    }
    static String name(String value){String s=value.trim();if(s.isEmpty()||s.length()>128||s.matches("(?s).*[\\x00-\\x1f].*"))throw new IllegalArgumentException("Use a name of 1–128 printable characters");return s;}
    static String color(String value){if(!value.matches("#[0-9a-fA-F]{6}"))throw new IllegalArgumentException("Use a six-digit color");return value;}
    static String normalize(String value){return value.toLowerCase(Locale.ROOT).replaceAll("[^\\p{L}\\p{N}]+"," ").trim();}
    static Set<String> strings(JSONArray values){Set<String> result=new HashSet<>();if(values!=null)for(int i=0;i<values.length();i++)result.add(values.optString(i));return result;}
    static String param(Uri uri,String key,String fallback){String value=uri.getQueryParameter(key);return value==null?fallback:value;}

    void checkSkipped(){String task=activeImport.get();if(task!=null){String status=store.one("SELECT status FROM tasks WHERE id=?",task).optString("status");if(status.equals("skipping")||status.equals("skipped"))throw new IndexSkipped();}}
    void checkpoint()throws Exception {checkSkipped();while(!closed&&(paused||(chargingOnly&&!plugged())||searches.get()>0)){Thread.sleep(150);checkSkipped();}if(closed)throw new InterruptedException("Indexing stopped; retry after restarting");}
    synchronized JSONObject skipTask(String task){JSONObject job=store.one("SELECT status,progress FROM tasks WHERE id=?",task);String status=job.optString("status");if(!status.equals("queued")&&!status.equals("running"))return Json.obj("status",status);
        if(!job.isNull("progress")&&Json.parse(job.optString("progress")).optString("stage").equals("committing"))return Json.obj("status",status,"message","This file is finishing its saved index.");
        status=status.equals("queued")?"skipped":"skipping";store.exec("UPDATE tasks SET status=?,error=NULL WHERE id=?",status,task);return Json.obj("status",status);}
    String enqueue(String sourceUri,String filename,String folder,String replacement,boolean ocr,boolean bill){return enqueue(sourceUri,filename,folder,replacement,ocr,bill,false);}
    String enqueue(String sourceUri,String filename,String folder,String replacement,boolean ocr,boolean bill,boolean reference){return enqueue(sourceUri,filename,folder,replacement,ocr,bill,reference,false);}
    synchronized String enqueue(String sourceUri,String filename,String folder,String replacement,boolean ocr,boolean bill,boolean reference,boolean forceOcr){store.one("SELECT id FROM folders WHERE id=?",folder);String id=LibraryStore.id();
        JSONArray pending=store.query("SELECT id FROM tasks WHERE status IN ('queued','running','skipping') AND ((replace_id!='' AND replace_id=?) OR (source_uri=? AND folder_id=?)) LIMIT 1",replacement==null?"":replacement,sourceUri,folder);if(pending.length()>0)return pending.optJSONObject(0).optString("id");
        if(reference)store.exec("UPDATE tasks SET status='recovered',error=NULL WHERE is_reference=1 AND source_uri=? AND folder_id=? AND status IN ('failed','interrupted')",sourceUri,folder);
        // Existing integer column: 0=off, 1=automatic, 2=explicit re-read.
        // Keep the database schema compatible with existing Android backups.
        store.exec("INSERT INTO tasks(id,filename,status,progress,error,result,source_uri,folder_id,replace_id,ocr,is_bill,is_reference,created_at) VALUES(?,?,'queued',NULL,NULL,NULL,?,?,?,?,?,?,?)",id,filename,sourceUri,folder,replacement==null?"":replacement,forceOcr?2:ocr?1:0,bill?1:0,reference?1:0,LibraryStore.now());
        indexing.submit(()->importTask(id));
        try{context.startForegroundService(new Intent(context,ImportService.class));}catch(IllegalStateException ignored){/* The persisted task can resume after a system interruption. */}
        return id;
    }
    void progress(String task,int page,int count,String stage,int chunks){checkpointUnchecked();long now=android.os.SystemClock.elapsedRealtime();if(task.equals(progressTask)&&stage.equals(progressStage)&&now-progressAt<1000)return;store.exec("UPDATE tasks SET progress=? WHERE id=?",Json.obj("page",page,"total_pages",count,"stage",stage,"chunks",chunks).toString(),task);progressTask=task;progressStage=stage;progressAt=now;}
    void checkpointUnchecked(){try{checkpoint();}catch(IndexSkipped e){throw e;}catch(Exception e){Thread.currentThread().interrupt();throw new IllegalStateException(e);}}
    void ensureReferenceIncluded(File source,String task)throws IOException {if(phoneScan.isExcluded(source)||store.query("SELECT path FROM phone_scan_files WHERE task_id=? AND state='excluded'",task).length()>0)throw new IOException("This PDF was ignored. Include it and scan again to read it.");}
    long sourceModifiedAt(Uri uri){
        try{
            long value=0;
            if("file".equals(uri.getScheme())){File file=new File(uri.getPath());if(file.isFile())value=file.lastModified();}
            else if("content".equals(uri.getScheme()))try(Cursor c=context.getContentResolver().query(uri,new String[]{android.provider.DocumentsContract.Document.COLUMN_LAST_MODIFIED},null,null,null)){if(c!=null&&c.moveToFirst()&&!c.isNull(0))value=c.getLong(0);}
            if(value<=0)return 0;java.time.Instant.ofEpochMilli(value);return value;
        }catch(Exception ignored){return 0;}
    }
    void importTask(String task){File stageFile=new File(context.getCacheDir(),"index-"+task+".sqlite3");SQLiteDatabase stage=null;
        try{
            if(!store.one("SELECT status FROM tasks WHERE id=?",task).optString("status").equals("queued"))return;
            embeddingUpgrade.ensure();activeImport.set(task);
            try(SQLiteStatement claim=store.getWritableDatabase().compileStatement("UPDATE tasks SET status='running' WHERE id=? AND status='queued'")){claim.bindString(1,task);if(claim.executeUpdateDelete()!=1)return;}
            JSONObject job=store.one("SELECT * FROM tasks WHERE id=?",task);
            checkpoint();
            String filename=job.optString("filename"),extension=filename.substring(filename.lastIndexOf('.')+1).toLowerCase(Locale.ROOT);
            if(!extension.equals("pdf")&&!extension.equals("pptx")&&!isTextFormat(extension))throw new IllegalArgumentException("Unsupported document format. Choose a PDF, PPTX or supported text file.");
            Uri selected=Uri.parse(job.optString("source_uri"));File retained=null;
            if("file".equals(selected.getScheme())){File candidate=new File(selected.getPath()).getCanonicalFile();if(candidate.isFile()&&candidate.getParentFile().equals(new File(store.root,"sources").getCanonicalFile()))retained=candidate;}
            final long observedBefore=retained==null?sourceModifiedAt(selected):0;
            boolean reference=job.optInt("is_reference")!=0;File external=reference?new File(selected.getPath()).getCanonicalFile():null;if(reference&&(!PhoneScan.access(context)||!PhoneScan.allowedPath(context,external)||!external.isFile()))throw new IOException("Original unavailable. Allow file access and scan again.");File source=reference?external:retained==null?new File(store.root,"sources/"+task+"."+extension):retained;progress(task,0,0,"copying",0);
            if(reference)ensureReferenceIncluded(source,task);
            if(!reference&&retained==null)try(InputStream in=context.getContentResolver().openInputStream(selected);FileOutputStream out=new FileOutputStream(source)){
                if(in==null)throw new IOException("Cannot open the selected document");byte[] buffer=new byte[262144];int n;long size=0;while((n=in.read(buffer))>=0){checkpoint();size+=n;if(size>100L*1048576)throw new IOException("Document exceeds 100 MB");out.write(buffer,0,n);}out.getFD().sync();}
            final long observedAfter=retained==null?sourceModifiedAt(selected):0;
            final long[] sourceModified={observedBefore>0&&observedBefore==observedAfter?observedBefore:0};
            store.exec("UPDATE tasks SET source_path=? WHERE id=?",source.getAbsolutePath(),task);String sha=LibraryStore.hash(source),replacement=job.optString("replace_id");if(!replacement.isEmpty())job.put("folder_id",store.document(replacement).optString("folder_id"));
            JSONArray duplicate=store.query("SELECT id FROM documents WHERE folder_id=? AND sha256=? AND trashed=0 AND id!=?",job.optString("folder_id"),sha,replacement);
            if(duplicate.length()>0){JSONObject existing=store.document(duplicate.optJSONObject(0).optString("id"));if(reference&&existing.optString("source_mode").equals("reference")&&!new File(existing.optString("source_path")).isFile()){store.exec("UPDATE documents SET source_path=?,preview_path=?,source_uri=?,version=version+1,updated_at=? WHERE id=?",source.getPath(),source.getPath(),selected.toString(),LibraryStore.now(),existing.optString("id"));existing=store.document(existing.optString("id"));}complete(task,Json.obj("action","duplicate","document",existing));return;}
            JSONObject old=replacement.isEmpty()?null:store.document(replacement);if(old!=null)job.put("folder_id",old.optString("folder_id"));
            String id=old==null?LibraryStore.id():replacement,title=filename.replaceFirst("(?i)\\.(pdf|pptx|docx|xlsx|txt|md|csv|tsv)$","");File preview=extension.equals("pptx")?new File(store.root,"previews/"+task+".pdf"):source;
            stage=SQLiteDatabase.openOrCreateDatabase(stageFile,null);stage.execSQL("CREATE TABLE pages(page_number INTEGER,text TEXT,method TEXT,warnings TEXT,evidence TEXT)");stage.execSQL("CREATE TABLE chunks(page_number INTEGER,chunk_index INTEGER,text TEXT,char_start INTEGER,char_end INTEGER,vector BLOB,input_hash TEXT)");
            final SQLiteDatabase staging=stage;final int[] counts={0,0,0};
            final PageIndexer[] pageIndexer={null};final JSONObject[] sourceLocation={null};
            DocumentReader.Consumer consume=(number,total,text,method,words,warnings,rotation,width,height)->{
                checkpoint();progress(task,number,total,"reading",counts[0]);counts[1]=total;
                JSONObject evidence=Json.obj("version",1,"frame",method.equals("text")?"source_text":method.equals("ocr")?"display_page_points":"unrotated_page_points","rotation",rotation,"bounds",Json.arr(0,0,width,height),"words",words,"ocr_alternatives",null,"source_sha256",sha,"recipe","android-pdfbox-mlkit-v1","chunking_recipe",PageIndexer.RECIPE);
                if(sourceLocation[0]!=null)evidence.put("location",sourceLocation[0]);
                if(text.trim().isEmpty()){counts[2]++;staging.execSQL("INSERT INTO pages VALUES(?,?,?,?,?)",new Object[]{number,text,method,warnings.toString(),evidence.toString()});return;}
                if(pageIndexer[0]==null){final String embeddingPath=models.embedding();pageIndexer[0]=new PageIndexer(store,staging,models.embeddingSha,title,new PageIndexer.Engine(){
                    public int tokens(String input){return NativeModels.tokenCount(embeddingPath,input);}
                    public float[] scalar(String input){return NativeModels.embed(embeddingPath,input);}
                    public float[][] batch(String[] inputs)throws Exception{checkpoint();return NativeModels.embedBatch(embeddingPath,inputs);}
                },()->{checkpoint();if(reference)ensureReferenceIncluded(source,task);},4,true);}
                pageIndexer[0].indexPage(number,text,method,warnings.toString(),evidence.toString(),chunks->progress(task,number,total,"embedding",chunks));counts[0]=pageIndexer[0].chunkCount;
            };
            DocumentReader reader=new DocumentReader(context);if(extension.equals("pdf"))reader.pdf(source,job.optInt("ocr")!=0,job.optInt("ocr")==2,consume);else if(extension.equals("pptx"))reader.pptx(source,preview,consume);else if(OfficeTextDocument.supports(extension)){
                List<OfficeTextDocument.Section> sections=OfficeTextDocument.read(source,extension,android.util.Xml::newPullParser);
                for(int i=0;i<sections.size();i++){OfficeTextDocument.Section part=sections.get(i);int number=i+1;sourceLocation[0]=officeLocation(part,number);JSONArray warnings=extension.equals("xlsx")?Json.arr("Extracted worksheet text and cached values. Formulas are not evaluated; cached values may be missing or stale. Verify the original workbook."):Json.arr("Extracted document text. Verify formatting in the original file.");consume.page(number,sections.size(),part.text,"text",new JSONArray(),warnings,0,0,0);}
            }else reader.plainText(source,consume);
            if(pageIndexer[0]!=null){pageIndexer[0].finish(chunks->progress(task,counts[1],counts[1],"embedding",chunks));counts[0]=pageIndexer[0].chunkCount;}
            stage.close();stage=null;SQLiteDatabase db=store.getWritableDatabase();
            if(reference){ensureReferenceIncluded(source,task);if(!LibraryStore.hash(source).equals(sha))throw new IOException("Original changed during reading. Scan again to retry.");if(sourceModified[0]!=sourceModifiedAt(selected))sourceModified[0]=0;}
            checkpoint();
            db.execSQL("ATTACH DATABASE ? AS staged",new Object[]{stageFile.getAbsolutePath()});
            try{synchronized(this){checkSkipped();if(reference)ensureReferenceIncluded(source,task);store.exec("UPDATE tasks SET progress=? WHERE id=?",Json.obj("page",counts[1],"total_pages",counts[1],"stage","committing","chunks",counts[0]).toString(),task);db.beginTransaction();try{
                JSONObject current=old==null?null:store.document(id);if(old!=null&&(current.optInt("version")!=old.optInt("version")||current.optInt("trashed")!=0))throw new IllegalArgumentException("Document changed during indexing; previous version retained");
                if(old!=null){db.execSQL("DELETE FROM chunks WHERE document_id=?",new Object[]{id});db.execSQL("DELETE FROM pages WHERE document_id=?",new Object[]{id});db.execSQL("DELETE FROM bills WHERE document_id=?",new Object[]{id});}
                ContentValues values=new ContentValues();values.put("id",id);values.put("folder_id",job.optString("folder_id"));values.put("filename",filename);values.put("title",title);values.put("sha256",sha);values.put("source_mode",reference?"reference":"managed");values.put("source_path",reference?source.getCanonicalPath():relative(source));values.put("preview_path",reference?preview.getCanonicalPath():relative(preview));values.put("source_uri",job.optString("source_uri"));values.put("format",extension);values.put("page_count",counts[1]);values.put("chunk_count",counts[0]);values.put("status",counts[0]==0?(isTextFormat(extension)?"empty":"needs_ocr"):counts[2]>0?"partial":"indexed");values.put("version",old==null?1:old.optInt("version")+1);values.put("created_at",old==null?LibraryStore.now():old.optString("created_at"));values.put("updated_at",LibraryStore.now());values.put("size_bytes",source.length());
                if(old==null)db.insertOrThrow("documents",null,values);else db.update("documents",values,"id=?",new String[]{id});
                if(sourceModified[0]>0)db.execSQL("INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)",new Object[]{"khoj.modified:"+id,Json.obj("sha256",sha,"epoch_ms",sourceModified[0]).toString()});
                else if(retained==null||old==null||!sha.equals(old.optString("sha256")))db.execSQL("DELETE FROM settings WHERE key=?",new Object[]{"khoj.modified:"+id});
                db.execSQL("INSERT INTO pages SELECT ?,page_number,text,method,warnings,evidence FROM staged.pages",new Object[]{id});db.execSQL("INSERT INTO chunks(document_id,page_number,chunk_index,text,char_start,char_end,vector,input_hash) SELECT ?,page_number,chunk_index,text,char_start,char_end,vector,input_hash FROM staged.chunks",new Object[]{id});db.setTransactionSuccessful();
            }finally{db.endTransaction();}}}finally{db.execSQL("DETACH DATABASE staged");}
            JSONObject guessed=suggest(id);if(job.optInt("is_bill")!=0||guessed.optBoolean("detected")){guessed.put("reviewed",0);guessed.put("origin","extracted");store.exec("INSERT OR REPLACE INTO bills VALUES(?,?)",id,guessed.toString());}
            complete(task,Json.obj("action",old==null?"added":"updated","document",store.document(id),"indexing_timing",Json.obj("embedding_ms",pageIndexer[0]==null?0:pageIndexer[0].embeddingNs/1e6,"database_ms",pageIndexer[0]==null?0:pageIndexer[0].databaseNs/1e6)));
        }catch(IndexSkipped error){store.exec("UPDATE tasks SET status='skipped',error=NULL WHERE id=?",task);
        }catch(Throwable error){store.exec("UPDATE tasks SET status='failed',error=? WHERE id=?",error.getClass().getSimpleName()+": "+String.valueOf(error.getMessage()),task);
        }finally{activeImport.remove();if(stage!=null)stage.close();stageFile.delete();}
    }
    String relative(File file){try{var root=store.root.getCanonicalFile().toPath();var target=file.getCanonicalFile().toPath();if(!target.startsWith(root))throw new IllegalArgumentException("File is outside PaperVault's private library");return root.relativize(target).toString();}catch(IOException error){throw new IllegalArgumentException("Could not locate PaperVault's saved file",error);}}
    synchronized void complete(String task,JSONObject result){JSONObject job=store.one("SELECT progress FROM tasks WHERE id=?",task);if(job.isNull("progress")||!Json.parse(job.optString("progress")).optString("stage").equals("committing"))checkSkipped();store.exec("UPDATE tasks SET status='completed',result=? WHERE id=?",result.toString(),task);}
    JSONObject page(String id,int number)throws Exception{JSONObject row=store.one("SELECT * FROM pages WHERE document_id=? AND page_number=?",id,String.valueOf(number));row.put("warnings",new JSONArray(row.optString("warnings")));row.put("evidence",Json.parse(row.optString("evidence")));row.put("page_label",String.valueOf(number));return row;}
    JSONArray aliases(){JSONArray result=new JSONArray();for(JSONObject row:LibraryStore.objects(store.query("SELECT * FROM aliases ORDER BY alias")))result.put(Json.obj("alias",row.optString("alias"),"display_alias",row.optString("alias"),"party",row.optString("party")));return result;}

    JSONObject suggest(String id)throws Exception {
        JSONObject doc=store.document(id);JSONArray pages=store.query("SELECT * FROM pages WHERE document_id=? ORDER BY page_number",id);
        String party="",date="",number="",direction="unspecified",amount="",currency="";int sourcePage=1;boolean detected=false;
        for(JSONObject page:LibraryStore.objects(pages)){
            String text=page.optString("text");detected|=Pattern.compile("(?i)\\b(invoice|bill of supply|sales bill|purchase bill|cash memo)\\b").matcher(text).find();
            if(party.isEmpty()){Matcher m=Pattern.compile("(?im)^\\s*(?:bill(?:ed)?\\s*to|sold\\s*to|customer|buyer|supplier|vendor)\\s*[:：]?\\s*\\n?([^\\n]{2,160})").matcher(text);if(m.find())party=m.group(1).trim();}
            if(date.isEmpty()){Matcher m=Pattern.compile("(?im)^\\s*(?:(?:invoice|bill)\\s+)?date\\s*[:：]?\\s*\\n?([^\\n]+)").matcher(text);if(m.find())date=parseDate(m.group(1));}
            if(number.isEmpty()){Matcher m=Pattern.compile("(?im)^\\s*(?:invoice\\s*(?:number|no\\.?|#)|bill\\s*(?:number|no\\.?))\\s*[:：]?\\s*\\n?([^\\n]{1,80})").matcher(text);if(m.find())number=m.group(1).trim();}
            if(text.matches("(?is).*\\b(sales invoice|tax invoice|sold to)\\b.*"))direction="sale";
            if(text.matches("(?is).*\\b(purchase invoice|supplier invoice)\\b.*"))direction="purchase";
            JSONArray observations=Money.amounts(text,Json.parse(page.optString("evidence")));List<JSONObject> totals=new ArrayList<>();for(JSONObject a:LibraryStore.objects(observations))if(a.optString("field").equals("total"))totals.add(a);
            if(amount.isEmpty()&&totals.size()==1&&!totals.get(0).optString("association").equals("unresolved")){amount=totals.get(0).optString("value");currency=totals.get(0).isNull("currency")?"":totals.get(0).optString("currency","");sourcePage=page.optInt("page_number");}
        }
        return Json.obj("document_id",id,"party",party,"party_normalized",normalize(party),"bill_date",date.isEmpty()?null:date,"invoice_number",number,"direction",direction,"amount",amount.isEmpty()?null:amount,"currency",currency,"source_page",sourcePage,"reviewed",0,"origin","extracted","source_sha256",doc.optString("sha256"),"evidence",new JSONObject(),"detected",detected,"warnings",Json.arr("Automatic fields need review against the original document."));
    }
    static String parseDate(String text){
        Matcher iso=Pattern.compile("\\b(20\\d{2})-(\\d{2})-(\\d{2})\\b").matcher(text);if(iso.find())try{return java.time.LocalDate.of(Integer.parseInt(iso.group(1)),Integer.parseInt(iso.group(2)),Integer.parseInt(iso.group(3))).toString();}catch(Exception ignored){}
        Matcher numeric=Pattern.compile("\\b(\\d{1,2})[/.](\\d{1,2})[/.](\\d{2}|20\\d{2})\\b").matcher(text);if(numeric.find())try{int year=Integer.parseInt(numeric.group(3));return java.time.LocalDate.of(year<100?2000+year:year,Integer.parseInt(numeric.group(2)),Integer.parseInt(numeric.group(1))).toString();}catch(Exception ignored){}
        String months="jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?";
        Matcher named=Pattern.compile("(?i)\\b(?:(\\d{1,2})(?:st|nd|rd|th)?\\s+("+months+")|("+months+")\\s+(\\d{1,2})(?:st|nd|rd|th)?),?\\s+(20\\d{2})\\b").matcher(text);
        if(named.find())try{String month=(named.group(2)!=null?named.group(2):named.group(3)).substring(0,3).toLowerCase(Locale.ROOT);int m=Arrays.asList("jan","feb","mar","apr","may","jun","jul","aug","sep","oct","nov","dec").indexOf(month)+1;return java.time.LocalDate.of(Integer.parseInt(named.group(5)),m,Integer.parseInt(named.group(1)!=null?named.group(1):named.group(4))).toString();}catch(Exception ignored){}
        return "";
    }
    JSONObject saveBill(String id,JSONObject fields)throws Exception {
        JSONObject doc=store.document(id),before=store.bill(id);String party=fields.optString("party").trim(),date=fields.optString("bill_date","");if(date.equals("null"))date="";
        if(party.length()>160)throw new IllegalArgumentException("Party name is too long");if(!date.isEmpty()&&!parseDate(date).equals(date))throw new IllegalArgumentException("Use a valid date in YYYY-MM-DD format");
        boolean reviewed=fields.optBoolean("reviewed");if(reviewed&&(party.isEmpty()||date.isEmpty()))throw new IllegalArgumentException("Confirm party and date before marking the bill reviewed");
        String direction=fields.optString("direction","unspecified");if(!Arrays.asList("sale","purchase","unspecified").contains(direction))throw new IllegalArgumentException("Choose sale, purchase or unspecified");
        String amount=fields.isNull("amount")?"":fields.optString("amount","");if(!amount.isEmpty())amount=Money.decimal(amount).toPlainString();int page=fields.optInt("source_page",1);if(page<1||page>doc.optInt("page_count"))throw new IllegalArgumentException("Source page is outside the document");
        JSONObject evidence=new JSONObject();
        if(fields.optBoolean("amount_reviewed")){
            if(!reviewed||amount.isEmpty())throw new IllegalArgumentException("Check the invoice details before confirming its total field");JSONObject p=page(id,page);List<JSONObject> matches=new ArrayList<>();for(JSONObject observation:LibraryStore.objects(Money.amounts(p.optString("text"),p.optJSONObject("evidence"))))if(observation.optString("field").equals("total")&&observation.optString("value").equals(amount))matches.add(observation);
            if(matches.size()!=1||matches.get(0).optString("association").equals("unresolved"))throw new IllegalArgumentException("This amount has no unique indexed total field. Leave the amount confirmation unchecked.");
            JSONObject review=new JSONObject(matches.get(0).toString());review.put("source_sha256",doc.optString("sha256"));review.put("page_number",page);evidence.put("amount_review",review);
        }
        JSONObject bill=Json.obj("document_id",id,"party",party,"party_normalized",normalize(party),"bill_date",date.isEmpty()?null:date,"invoice_number",fields.optString("invoice_number",""),"direction",direction,"amount",amount.isEmpty()?null:amount,"currency",fields.optString("currency","").toUpperCase(Locale.ROOT),"source_page",page,"source_sha256",doc.optString("sha256"),"reviewed",reviewed?1:0,"origin","manual","evidence",evidence);
        SQLiteDatabase db=store.getWritableDatabase();db.beginTransaction();try{store.exec("INSERT OR REPLACE INTO bills VALUES(?,?)",id,bill.toString());store.exec("INSERT INTO history VALUES(?,?,?,?,?,?)",LibraryStore.id(),id,doc.optString("sha256"),LibraryStore.now(),before==null?null:before.toString(),bill.toString());db.setTransactionSuccessful();}finally{db.endTransaction();}return bill;
    }
    JSONObject undoBill(String id)throws Exception {
        JSONObject latest=store.one("SELECT * FROM history WHERE document_id=? ORDER BY created_at DESC LIMIT 1",id),doc=store.document(id);
        if(!latest.optString("source_sha256").equals(doc.optString("sha256")))throw new IllegalArgumentException("The source changed; review the new invoice first");
        JSONObject current=store.bill(id);if(current==null||!current.toString().equals(latest.optString("after_json")))throw new IllegalArgumentException("The bill changed since this correction");
        SQLiteDatabase db=store.getWritableDatabase();db.beginTransaction();try{if(latest.isNull("before_json"))store.exec("DELETE FROM bills WHERE document_id=?",id);else store.exec("INSERT OR REPLACE INTO bills VALUES(?,?)",id,latest.optString("before_json"));store.exec("DELETE FROM history WHERE id=?",latest.optString("id"));db.setTransactionSuccessful();}finally{db.endTransaction();}return Json.obj("undone",true,"saved",store.bill(id));
    }
    JSONObject checks(String id)throws Exception {
        JSONArray checked=new JSONArray();for(JSONObject p:LibraryStore.objects(store.query("SELECT * FROM pages WHERE document_id=?",id))){String text=p.optString("text");JSONArray values=Money.amounts(text,Json.parse(p.optString("evidence")));Set<BigDecimal> sub=new HashSet<>(),total=new HashSet<>();for(JSONObject a:LibraryStore.objects(values))if(!a.optString("association").equals("unresolved"))(a.optString("field").equals("subtotal")?sub:total).add(Money.decimal(a.optString("value")));
            Matcher tax=Pattern.compile("(?im)^\\s*(?:CGST|SGST|IGST|GST|tax)\\b[^\\n\\d]*(?:\\([^\\n)]*\\))?\\s*[:=]?\\s*\\n?\\s*(?:INR|Rs\\.?|₹)?\\s*("+Money.NUMBER+")").matcher(text);BigDecimal taxes=BigDecimal.ZERO;int count=0;while(tax.find())try{taxes=taxes.add(Money.decimal(tax.group(1)));count++;}catch(Exception ignored){}
            if(sub.size()==1&&total.size()==1&&count>0&&!text.matches("(?is).*\\b(discount|round off|shipping|freight|cess|adjustment)\\b.*")){BigDecimal expected=sub.iterator().next().add(taxes),actual=total.iterator().next(),difference=actual.subtract(expected);checked.put(Json.obj("page",p.optInt("page_number"),"expected",expected.toPlainString(),"actual",actual.toPlainString(),"difference",difference.toPlainString(),"status",difference.abs().compareTo(new BigDecimal("0.01"))<=0?"consistent":"review"));}}
        return Json.obj("arithmetic",Json.obj("checks",checked,"note","Arithmetic compares unambiguous indexed fields; it does not correct OCR or prove field meaning."),"history",store.query("SELECT created_at FROM history WHERE document_id=? ORDER BY created_at DESC",id));
    }
    JSONObject highlight(String id,int number,String literal)throws Exception {JSONObject p=page(id,number);if(p.optString("method").equals("native")&&p.optJSONObject("evidence").optInt("rotation")%360!=0)return Json.obj("boxes",new JSONArray(),"note","Rotated native page: open the original to verify; exact highlights unavailable.");JSONArray words=p.optJSONObject("evidence").optJSONArray("words"),bounds=p.optJSONObject("evidence").optJSONArray("bounds"),boxes=new JSONArray();if(literal.length()>1000)literal=literal.substring(0,1000);
        Set<String> terms=new HashSet<>(Arrays.asList(normalize(literal).split("\\s+")));if(words!=null&&bounds!=null)for(int i=0;i<words.length();i++){JSONArray w=words.optJSONArray(i);if(terms.contains(normalize(w.optString(4))))boxes.put(Json.arr(w.optDouble(0)/bounds.optDouble(2),w.optDouble(1)/bounds.optDouble(3),(w.optDouble(2)-w.optDouble(0))/bounds.optDouble(2),(w.optDouble(3)-w.optDouble(1))/bounds.optDouble(3)));if(boxes.length()>=30)break;}
        return Json.obj("boxes",boxes,"note","Literal text positions; highlighting does not verify meaning.");
    }

    JSONObject filters(String query,JSONObject supplied,boolean force,boolean inferInvoiceNumber){JSONObject result=new JSONObject();for(String key:new String[]{"party","date_from","date_to","direction","invoice_number","item"})try{result.put(key,supplied.optString(key,""));}catch(JSONException ignored){}
        try{
            if(result.optString("party").isEmpty()){
                for(JSONObject bill:LibraryStore.objects(store.bills()))if(!bill.optString("party").isEmpty()&&(" "+normalize(query)+" ").contains(" "+normalize(bill.optString("party"))+" ")){result.put("party",bill.optString("party"));break;}
                for(JSONObject alias:LibraryStore.objects(aliases()))if((" "+normalize(query)+" ").contains(" "+normalize(alias.optString("alias"))+" "))result.put("party",alias.optString("party"));
                Matcher party=Pattern.compile("(?i)\\b(?:sold to|sales to|bought from|purchased from|invoices? (?:for|from)|sales? (?:to))\\s+(.+?)(?=\\s+(?:on|in|total|subtotal|dated|invoice|bill)\\b|$)").matcher(query);if(party.find()&&!party.group(1).trim().matches("[\\d, .]+"))result.put("party",party.group(1).trim());
            }
            boolean billContext=BillSearchIntent.context(query,force,result.optString("party"));
            String date=billContext?parseDate(query):"";if(!date.isEmpty()){if(result.optString("date_from").isEmpty())result.put("date_from",date);if(result.optString("date_to").isEmpty())result.put("date_to",date);}
            if(billContext&&date.isEmpty()){
                java.time.LocalDate today=java.time.LocalDate.now(),from=null,to=null;
                Matcher month=Pattern.compile("(?i)\\b(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\\s+(20\\d{2})\\b").matcher(query);
                if(month.find()){int m=Arrays.asList("jan","feb","mar","apr","may","jun","jul","aug","sep","oct","nov","dec").indexOf(month.group(1).substring(0,3).toLowerCase(Locale.ROOT))+1;from=java.time.LocalDate.of(Integer.parseInt(month.group(2)),m,1);to=from.withDayOfMonth(from.lengthOfMonth());}
                else if(query.matches("(?is).*\\blast month\\b.*")){from=today.minusMonths(1).withDayOfMonth(1);to=from.withDayOfMonth(from.lengthOfMonth());}
                else if(query.matches("(?is).*\\bthis month\\b.*")){from=today.withDayOfMonth(1);to=today.withDayOfMonth(today.lengthOfMonth());}
                else if(query.matches("(?is).*\\byesterday\\b.*")){from=today.minusDays(1);to=from;}
                if(from!=null){if(result.optString("date_from").isEmpty())result.put("date_from",from.toString());if(result.optString("date_to").isEmpty())result.put("date_to",to.toString());}
            }
            if(result.optString("direction").isEmpty()&&billContext){if(query.matches("(?is).*\\b(sold|sale|sales|becha|bechi)\\b.*"))result.put("direction","sale");else if(query.matches("(?is).*\\b(bought|purchased|purchase|kharida)\\b.*"))result.put("direction","purchase");}
            if(inferInvoiceNumber&&result.optString("invoice_number").isEmpty())for(JSONObject bill:LibraryStore.objects(store.bills())){String number=bill.optString("invoice_number");if(!number.isEmpty()&&query.toLowerCase(Locale.ROOT).contains(number.toLowerCase(Locale.ROOT)))result.put("invoice_number",number);}
        }catch(JSONException e){throw new IllegalArgumentException(e);}return result;
    }
    boolean eligible(JSONObject doc,JSONObject filter){JSONObject bill=store.bill(doc.optString("id"));
        for(String key:new String[]{"party","direction","invoice_number"}){String value=filter.optString(key);if(!value.isEmpty()&&(bill==null||!normalize(value).equals(normalize(bill.optString(key)))))return false;}
        String from=filter.optString("date_from"),to=filter.optString("date_to");if(!from.isEmpty()&&(bill==null||bill.isNull("bill_date")||bill.optString("bill_date").compareTo(from)<0))return false;if(!to.isEmpty()&&(bill==null||bill.isNull("bill_date")||bill.optString("bill_date").compareTo(to)>0))return false;
        String item=filter.optString("item");if(!item.isEmpty()){boolean found=false;for(JSONObject p:LibraryStore.objects(store.query("SELECT text FROM pages WHERE document_id=?",doc.optString("id"))))if(normalize(p.optString("text")).contains(normalize(item)))found=true;if(!found)return false;}
        return true;
    }
    String interpretSearch(String query)throws Exception {
        String grammar="root ::= \"general\" | \"invoice_number\" | \"amount\"";
        String prompt=ModelAssets.prompt("Classify this document search. Return only one label: invoice_number for a request for a specific invoice identifier, amount for an invoice total or monetary value, general for anything else. Never treat invoice identifiers as amounts.",query);
        return NativeModels.generate(models.qwen(),prompt,grammar,12).trim();
    }
    String interpretSemanticSearch(String query)throws Exception {
        String grammar="root ::= [^\\n\\r]+";
        String prompt=ModelAssets.prompt("Rewrite the user's document search as one concise search phrase. Preserve the topic, names, identifiers, dates, numbers and constraints. Do not answer, invent details, or add explanations. Support any subject and language. Return only the phrase.",query);
        return NativeModels.generate(models.qwen(),prompt,grammar,72).trim();
    }
    JSONObject interpretAmount(String query)throws Exception {
        String grammar="root ::= \"{\\\"field\\\":\" field \",\\\"amount\\\":\\\"\" amount \"\\\"}\"\nfield ::= \"\\\"total\\\"\" | \"\\\"subtotal\\\"\"\namount ::= [0-9]+ (\".\" [0-9] [0-9]?)?";
        String prompt=ModelAssets.prompt("Extract one invoice search amount from English, Hindi or Hinglish. Return JSON field and amount only. Copy digits exactly; never adjust or round. field is subtotal only for explicit subtotal or before-tax wording, otherwise total. Greetings are not party names.",query);
        JSONObject data=Json.parse(NativeModels.generate(models.qwen(),prompt,grammar,64));BigDecimal value=Money.decimal(data.optString("amount"));
        Matcher literals=Pattern.compile(Money.NUMBER).matcher(query);boolean supported=false;while(literals.find())try{if(Money.decimal(literals.group()).compareTo(value)==0)supported=true;}catch(Exception ignored){}
        if(!supported)throw new IllegalArgumentException("Could not interpret the amount safely. Try total 13800.");
        if(query.matches("(?is).*\\b(under|over|below|above|between|zyada|kam)\\b.*"))throw new IllegalArgumentException("Use one amount; range comparisons are not supported");
        return Json.obj("field",query.matches("(?is).*\\b(sub[ -]?total|before tax|tax se pehle)\\b.*")?"subtotal":"total","value",value.toPlainString(),"currency",null);
    }
    static boolean isTextFormat(String format){return PlainTextDocument.supports(format)||OfficeTextDocument.supports(format);}
    static JSONObject officeLocation(OfficeTextDocument.Section part,int number)throws JSONException {
        if(part.sheet==null)return Json.obj("kind","text","label","Section "+number);
        String label=part.sheet+(part.rowStart>0?(part.rowStart==part.rowEnd?" · row "+part.rowStart:" · rows "+part.rowStart+"–"+part.rowEnd):"");
        JSONObject location=Json.obj("kind","spreadsheet","label",label,"sheet",part.sheet);if(part.rowStart>0){location.put("row_start",part.rowStart);location.put("row_end",part.rowEnd);}return location;
    }
    static JSONObject textLocation(JSONObject evidence,int number)throws JSONException {JSONObject location=evidence==null?null:evidence.optJSONObject("location");return location==null?Json.obj("kind","text","label","Section "+number):location;}
    static JSONObject decorateTextSource(JSONObject doc){
        if(isTextFormat(doc.optString("format")))try{doc.put("source_kind",doc.optString("format").equals("xlsx")?"spreadsheet":"text");doc.put("source_format",doc.optString("format"));doc.put("preview_kind","text");doc.put("unit_count",doc.optInt("page_count"));}catch(JSONException error){throw new IllegalStateException(error);}return doc;
    }
    JSONObject hit(JSONObject doc,JSONObject p,JSONObject chunk,double score)throws Exception {String id=doc.optString("id");int page=p.optInt("page_number");
        JSONObject result=Json.obj("chunk_id",chunk.optLong("id"),"chunk_index",chunk.optInt("chunk_index"),"document_id",id,"filename",doc.optString("filename"),"folder",doc.optString("folder_name"),"folder_id",doc.optString("folder_id"),"page_number",page,"page_label",String.valueOf(page),"passage",chunk.optString("text"),"char_start",chunk.optInt("char_start"),"char_end",chunk.optInt("char_end"),"score",score,"score_type","cosine","extraction_method",p.optString("method"),"warnings",new JSONArray(p.optString("warnings","[]")),"source_sha256",doc.optString("sha256"),"source_revision",doc.optInt("version"),"source_available",new File(store.root,doc.optString("source_path")).isFile(),"source_identity",id+":"+doc.optString("sha256")+":"+doc.optInt("version")+":"+chunk.optInt("chunk_index")+":"+page);
        if(isTextFormat(doc.optString("format"))){result.put("source_kind",doc.optString("format").equals("xlsx")?"spreadsheet":"text");result.put("source_format",doc.optString("format"));result.put("preview_kind","text");result.put("unit_number",page);JSONObject location=textLocation(Json.parse(p.optString("evidence","{}")),page);result.put("location",location);result.put("location_label",location.optString("label"));}
        JSONObject bill=store.bill(id);if(bill!=null)result.put("bill",bill);return result;
    }
    List<JSONObject> literalHits(List<JSONObject> documents,String query)throws Exception {
        Pattern pattern=LiteralSearch.pattern(query);List<JSONObject> hits=new ArrayList<>();if(pattern==null)return hits;
        Set<String> pages=new HashSet<>();
        for(JSONObject doc:documents)try(Cursor c=store.getReadableDatabase().rawQuery("SELECT id,page_number,chunk_index,text,char_start,char_end FROM chunks WHERE document_id=? ORDER BY page_number,chunk_index",new String[]{doc.optString("id")})){
            while(c.moveToNext()){
                searchCheckpoint();int pageNumber=c.getInt(1);String key=doc.optString("id")+":"+pageNumber;
                if(pages.contains(key)||!pattern.matcher(c.getString(3)).find())continue;
                JSONObject chunk=Json.obj("id",c.getLong(0),"page_number",pageNumber,"chunk_index",c.getInt(2),"text",c.getString(3),"char_start",c.getInt(4),"char_end",c.getInt(5));
                JSONObject page=store.one("SELECT * FROM pages WHERE document_id=? AND page_number=?",doc.optString("id"),String.valueOf(pageNumber));
                JSONObject h=hit(doc,page,chunk,1);h.put("score_type","exact_text");h.put("match_reasons",Json.arr("Exact text match in indexed passage"));hits.add(h);pages.add(key);
                if(hits.size()>=20)return hits;
            }
        }return hits;
    }
    void mergeLiteral(List<JSONObject> hits,List<JSONObject> exact){
        Set<String> seen=new HashSet<>();List<JSONObject> merged=new ArrayList<>();
        for(JSONObject h:exact)if(seen.add(h.optString("document_id")+":"+h.optInt("page_number")))merged.add(h);
        for(JSONObject h:hits)if(seen.add(h.optString("document_id")+":"+h.optInt("page_number")))merged.add(h);
        hits.clear();hits.addAll(merged);
    }
    boolean verified(JSONObject bill,JSONObject match,JSONObject doc){if(bill==null||bill.optInt("reviewed")==0||!bill.optString("source_sha256").equals(doc.optString("sha256")))return false;JSONObject review=bill.optJSONObject("evidence")==null?null:bill.optJSONObject("evidence").optJSONObject("amount_review");if(review==null)return false;
        if(!review.optString("source_sha256").equals(doc.optString("sha256"))||review.optInt("page_number")!=match.optInt("page_number"))return false;
        for(String key:new String[]{"field","value","currency","evidence","bbox"})if(!String.valueOf(review.opt(key)).equals(String.valueOf(match.opt(key))))return false;return true;
    }
    static void searchCheckpoint(){if(Thread.currentThread().isInterrupted())throw new CancellationException("Search superseded");}
    JSONObject filenameMatches(JSONObject body)throws Exception {
        String query=body.optString("query").trim();if(query.isEmpty()||query.length()>500)throw new IllegalArgumentException("Enter a search of up to 500 characters");
        Set<String> linked=null;if(!body.optString("linked_folder_id").isEmpty())for(JSONObject group:LibraryStore.objects(features.groups()))if(group.optString("id").equals(body.optString("linked_folder_id")))linked=strings(group.optJSONArray("document_ids"));
        if(!body.optString("linked_folder_id").isEmpty()&&linked==null)throw new IllegalArgumentException("Folder changed. Refresh the library.");
        JSONArray scopedIds=body.optJSONArray("document_ids");if(scopedIds!=null&&scopedIds.length()>10000)throw new IllegalArgumentException("Search collection is too large.");Set<String> allowed=scopedIds==null?null:strings(scopedIds);
        if(body.has("library_filters")&&!body.isNull("library_filters")){JSONObject filters=body.optJSONObject("library_filters");if(filters==null)throw new IllegalArgumentException("Unsupported library search filter.");Set<String> filtered=NativeLibraryBrowse.scopeIds(this,filters);if(allowed==null)allowed=filtered;else allowed.retainAll(filtered);}
        JSONArray matches=new JSONArray();String wanted=FilenameMatch.normalized(query);
        String sql="SELECT d.id,d.filename,d.folder_id,d.source_path,d.source_mode,f.name FROM documents d JOIN folders f ON f.id=d.folder_id WHERE d.trashed=0";
        String folder=body.optString("folder_id");String[] args=folder.isEmpty()?null:new String[]{folder};if(!folder.isEmpty())sql+=" AND d.folder_id=?";
        try(Cursor cursor=store.getReadableDatabase().rawQuery(sql,args)){
            while(cursor.moveToNext()){
                searchCheckpoint();String id=cursor.getString(0),filename=cursor.getString(1);
                if(allowed!=null&&!allowed.contains(id))continue;if(!body.optString("document_id").isEmpty()&&!body.optString("document_id").equals(id))continue;if(linked!=null&&!linked.contains(id))continue;
                if(!FilenameMatch.exactNormalized(wanted,filename))continue;
                boolean reference="reference".equals(cursor.getString(4));File source=reference?new File(cursor.getString(3)):new File(store.root,cursor.getString(3));
                if(reference&&phoneScan.isExcluded(source))continue;
                boolean available=source.isFile()&&source.canRead()&&(!reference||(phoneScan.hasAccess()&&PhoneScan.allowedPath(context,source)));
                matches.put(Json.obj("document_id",id,"filename",filename,"folder_id",cursor.getString(2),"folder",cursor.getString(5),"available",available));
            }
        }return Json.obj("matches",matches);
    }
    static boolean activeBillFilters(JSONObject filters){if(filters==null)return false;Iterator<String> keys=filters.keys();while(keys.hasNext())if(!filters.optString(keys.next(),"").isEmpty())return true;return false;}
    JSONObject search(JSONObject body)throws Exception {
        searchCheckpoint();long started=System.nanoTime();String originalQuery=body.optString("query").trim(),query=Money.expand(originalQuery);if(query.isEmpty()||query.length()>500)throw new IllegalArgumentException("Enter a search of up to 500 characters");
        if(!body.optBoolean("content_only")&&body.optString("document_id").isEmpty()&&!body.optBoolean("bills_only")&&!activeBillFilters(body.optJSONObject("bill_filters"))){
            JSONArray matches=filenameMatches(body).getJSONArray("matches");
            if(matches.length()>0){List<JSONObject> ordered=LibraryStore.objects(matches);ordered.sort(Comparator.comparing((JSONObject m)->m.optString("folder").toLowerCase(Locale.ROOT)).thenComparing(m->m.optString("filename").toLowerCase(Locale.ROOT)).thenComparing(m->m.optString("document_id")));JSONArray found=new JSONArray(),exact=new JSONArray();
                for(JSONObject match:ordered){exact.put(match);String id=match.optString("document_id");found.put(Json.obj("document_id",id,"filename",match.optString("filename"),"folder_id",match.optString("folder_id"),"folder",match.optString("folder"),"page_number",null,"chunk_id",null,"passage","","score",1.0,"score_type","exact_filename","source_available",match.optBoolean("available"),"match_reasons",Json.arr("Exact filename"),"open_uri","/api/documents/"+id+"/file","rank",found.length()+1));}
                return Json.obj("query",originalQuery,"mode","filename","results",found,"exact_filename_matches",exact,"elapsed_s",(System.nanoTime()-started)/1e9,"reliability","filename_match","empty_reason",null,"closest_available",false,"below_cutoff",false,"query_interpreter","not_needed","response",null);
            }
        }
        String queryIntent="general";boolean interpreterAvailable=true;
        boolean usedInterpreter=false;
        JSONArray appliedPrefixes=new JSONArray();
        String filterExt="";
        if(query.matches("(?i).*\\b(bill|invoice|type:bill|is:bill):.*")){
            body.put("bills_only",true);
            query=query.replaceAll("(?i)\\b(bill|invoice|type:bill|is:bill):\\s*(yes|true)?\\s*"," ").trim();
            appliedPrefixes.put("Bills only");
        }
        Matcher extM=Pattern.compile("(?i)\\b(?:ext|type|format):([a-zA-Z0-9]+)").matcher(query);
        if(extM.find()){
            filterExt=extM.group(1).toLowerCase(Locale.ROOT);
            query=extM.replaceAll(" ").trim();
            appliedPrefixes.put("Extension: ."+filterExt);
        }
        Matcher folderM=Pattern.compile("(?i)\\bfolder:(?:\"([^\"]+)\"|(\\S+))").matcher(query);
        if(folderM.find()){
            String folderName=folderM.group(1)!=null?folderM.group(1):folderM.group(2);if(folderM.find())throw new IllegalArgumentException("Use one folder per search.");List<JSONObject> exact=new ArrayList<>(),partial=new ArrayList<>();
            for(JSONObject folder:LibraryStore.objects(store.folders())){String name=folder.optString("name");if(name.equalsIgnoreCase(folderName))exact.add(folder);else if(name.toLowerCase(Locale.ROOT).contains(folderName.toLowerCase(Locale.ROOT)))partial.add(folder);}
            List<JSONObject> matches=exact.isEmpty()?partial:exact;if(matches.size()!=1)throw new IllegalArgumentException("Folder name is missing or ambiguous. Use the full folder name.");
            JSONObject selected=matches.get(0);if(!body.optString("folder_id").isEmpty()&&!body.optString("folder_id").equals(selected.optString("id")))throw new IllegalArgumentException("The folder in the search differs from the selected folder.");
            body.put("folder_id",selected.optString("id"));appliedPrefixes.put("Folder: "+selected.optString("name"));query=folderM.replaceFirst(" ").trim();
        }
        String invoiceNumber=InvoiceNumbers.query(originalQuery);
        JSONObject requested=invoiceNumber==null?Money.request(query):null;
        if(invoiceNumber!=null)queryIntent="invoice_number";else if(requested!=null)queryIntent="amount";else{usedInterpreter=true;try{queryIntent=interpretSearch(originalQuery);}catch(Exception failure){if(failure instanceof InterruptedException)Thread.currentThread().interrupt();searchCheckpoint();interpreterAvailable=false;}searchCheckpoint();}
        if(invoiceNumber==null&&requested==null&&(Money.candidate(query)||(queryIntent.equals("amount")&&query.matches("(?is).*(?:\\b(invoice|bill)\\b|बिल|इनवॉइस).*")&&Pattern.compile(Money.NUMBER).matcher(query).find())))requested=interpretAmount(query);
        if(requested!=null&&!body.optString("amount_field").isEmpty())requested.put("field",body.optString("amount_field"));
        JSONObject supplied=body.optJSONObject("bill_filters");JSONObject filter=filters(invoiceNumber==null?query:"",supplied==null?new JSONObject():supplied,requested!=null||body.optBoolean("bills_only"),requested==null);List<JSONObject> documents=new ArrayList<>();
        Set<String> linked=null;if(!body.optString("linked_folder_id").isEmpty())for(JSONObject group:LibraryStore.objects(features.groups()))if(group.optString("id").equals(body.optString("linked_folder_id")))linked=strings(group.optJSONArray("document_ids"));
        if(!body.optString("linked_folder_id").isEmpty()&&linked==null)throw new IllegalArgumentException("Folder changed. Refresh the library.");
        JSONArray scopedIds=body.optJSONArray("document_ids");if(scopedIds!=null&&scopedIds.length()>10000)throw new IllegalArgumentException("Search collection is too large.");Set<String> allowed=scopedIds==null?null:strings(scopedIds);
        if(body.has("library_filters")&&!body.isNull("library_filters")){JSONObject filters=body.optJSONObject("library_filters");if(filters==null)throw new IllegalArgumentException("Unsupported library search filter.");Set<String> filtered=NativeLibraryBrowse.scopeIds(this,filters);if(allowed==null)allowed=filtered;else allowed.retainAll(filtered);}
        for(JSONObject doc:LibraryStore.objects(phoneScan.visibleDocuments(store.documents()))){
            searchCheckpoint();if(allowed!=null&&!allowed.contains(doc.optString("id")))continue;
            if(!body.optString("folder_id").isEmpty()&&!body.optString("folder_id").equals(doc.optString("folder_id")))continue;
            if(!body.optString("document_id").isEmpty()&&!body.optString("document_id").equals(doc.optString("id")))continue;
            if(!filterExt.isEmpty()&&!doc.optString("format","").equalsIgnoreCase(filterExt)&&!doc.optString("filename","").toLowerCase(Locale.ROOT).endsWith("."+filterExt))continue;
            if(linked!=null&&!linked.contains(doc.optString("id")))continue;
            if(eligible(doc,filter))documents.add(doc);
        }
        List<JSONObject> hits=new ArrayList<>();String semanticInterpretation="",reliability="uncalibrated_candidates",note="Ranked source passages; similarity is not an answer or probability.";
        BigDecimal tolerance=BigDecimal.ZERO;
        if(invoiceNumber!=null){
            for(JSONObject doc:documents){searchCheckpoint();String id=doc.optString("id");JSONObject bill=store.bill(id);String saved=bill==null?"":bill.optString("invoice_number");
                JSONArray pages=store.query("SELECT * FROM pages WHERE document_id=? ORDER BY page_number",id);JSONObject chosen=null;boolean textMatch=false;
                // Prefer the page where the identifier is actually present. A saved
                // field may refer to a different page and is only a fallback.
                for(JSONObject p:LibraryStore.objects(pages))if(InvoiceNumbers.matches(invoiceNumber,"",p.optString("text"))){chosen=p;textMatch=true;break;}
                if(chosen==null&&bill!=null&&InvoiceNumbers.matches(invoiceNumber,saved,"")){int sourcePage=bill.optInt("source_page",1);for(JSONObject p:LibraryStore.objects(pages))if(p.optInt("page_number")==sourcePage){chosen=p;break;}}
                if(chosen==null)continue;
                JSONArray chunks=store.query("SELECT * FROM chunks WHERE document_id=? AND page_number=? ORDER BY chunk_index",id,chosen.optString("page_number"));if(chunks.length()==0)continue;
                JSONObject chunk=null;for(JSONObject candidate:LibraryStore.objects(chunks))if(InvoiceNumbers.matches(invoiceNumber,"",candidate.optString("text"))){chunk=candidate;break;}
                boolean passageMatch=chunk!=null;if(chunk==null)chunk=chunks.optJSONObject(0);
                JSONObject h=hit(doc,chosen,chunk,1);h.put("score_type","bill_fields");h.put("invoice_match",Json.obj("requested_number",invoiceNumber,"source",textMatch?"page_text":"saved_field","page_number",chosen.optInt("page_number")));
                h.put("match_reasons",Json.arr(passageMatch?"Invoice number matched in this indexed passage; verify the source.":textMatch?"Invoice number matched elsewhere on this page; open the source to inspect it.":"Saved invoice number matched; the identifier was not confirmed in indexed page text."));
                if(!passageMatch)h.optJSONArray("warnings").put(textMatch?"The matching identifier is elsewhere on this page.":"Saved invoice number could not be confirmed in indexed page text.");hits.add(h);
            }
            // Prefer enriched invoice evidence over a literal hit on the same source page.
            List<JSONObject> literalFallbacks=literalHits(documents,originalQuery);mergeLiteral(literalFallbacks,hits);hits.clear();hits.addAll(literalFallbacks);
            reliability="unreviewed_bill_fields";note="Invoice number found in saved fields or indexed text; check the original.";
        }else if(requested!=null){JSONObject matching=body.optJSONObject("matching");tolerance=Money.tolerance(query,requested,matching==null?new JSONObject():matching);BigDecimal desired=Money.decimal(requested.optString("value"));
            for(JSONObject doc:documents){searchCheckpoint();String id=doc.optString("id");JSONArray pages=store.query("SELECT * FROM pages WHERE document_id=? ORDER BY page_number",id);boolean invoice=store.bill(id)!=null;for(JSONObject p:LibraryStore.objects(pages))invoice|=p.optString("text").matches("(?is).*\\b(invoice|bill of supply|sales bill|purchase bill|cash memo)\\b.*");if(!invoice)continue;
                for(JSONObject p:LibraryStore.objects(pages))for(JSONObject observation:LibraryStore.objects(Money.amounts(p.optString("text"),Json.parse(p.optString("evidence"))))){BigDecimal delta=Money.decimal(observation.optString("value")).subtract(desired);
                    if(!observation.optString("field").equals(requested.optString("field"))||delta.abs().compareTo(tolerance)>0)continue;
                    if(!requested.isNull("currency")&&!requested.optString("currency").isEmpty()&&!requested.optString("currency").equals(observation.optString("currency")))continue;
                    JSONArray chunks=store.query("SELECT * FROM chunks WHERE document_id=? AND page_number=? AND char_start<=? AND char_end>=? ORDER BY char_start DESC LIMIT 1",id,p.optString("page_number"),observation.optString("start"),observation.optString("end"));if(chunks.length()==0)continue;
                    JSONObject h=hit(doc,p,chunks.optJSONObject(0),1),match=new JSONObject(observation.toString());match.put("page_number",p.optInt("page_number"));match.put("requested_value",requested.optString("value"));match.put("difference",delta.toPlainString());match.put("approximate",delta.signum()!=0);match.put("verified",h.optBoolean("source_available")&&verified(store.bill(id),match,doc));h.put("amount_match",match);h.put("score_type","bill_fields");
                    if(match.optBoolean("label_variant_used"))h.optJSONArray("warnings").put("OCR header 'lnvoice' was used as an Invoice label cue; the original text is retained and needs review.");
                    JSONArray bbox=match.optJSONArray("bbox"),bounds=Json.parse(p.optString("evidence")).optJSONArray("bounds");if(bbox!=null&&bounds!=null&&bounds.optDouble(2)>0&&bounds.optDouble(3)>0)match.put("highlight_box",Json.arr(bbox.optDouble(0)/bounds.optDouble(2),bbox.optDouble(1)/bounds.optDouble(3),(bbox.optDouble(2)-bbox.optDouble(0))/bounds.optDouble(2),(bbox.optDouble(3)-bbox.optDouble(1))/bounds.optDouble(3)));
                    h.put("match_reasons",Json.arr((delta.signum()==0?"Exact text match: ":"Nearby source amount: ")+observation.optString("value")+(match.optBoolean("verified")?" · field reviewed":" · field needs review")));hits.add(h);
                }
            }
            hits.sort(Comparator.comparing(h->Money.decimal(h.optJSONObject("amount_match").optString("difference").replace("-",""))));
            boolean confirmed=false;for(JSONObject h:hits)if(!h.optJSONObject("amount_match").optBoolean("approximate")&&h.optJSONObject("amount_match").optBoolean("verified"))confirmed=true;
            if(confirmed)hits.removeIf(h->h.optJSONObject("amount_match").optBoolean("approximate"));
            Set<String> seen=new HashSet<>();hits.removeIf(h->!seen.add(h.optString("document_id")));boolean exact=false,near=false;for(JSONObject h:hits){near|=h.optJSONObject("amount_match").optBoolean("approximate");exact|=!h.optJSONObject("amount_match").optBoolean("approximate");}
            reliability=near&&exact?"mixed_source_amounts":near?"nearby_source_amount":"exact_source_amount";
            note=near&&exact?"Unreviewed exact text matches and nearby alternatives are shown. Actual totals are unchanged.":near?"No exact amount found. Nearby indexed values are shown; check the original.":"Exact amount in indexed text; check its field and source.";
            if(hits.size()>100){List<JSONObject> visible=new ArrayList<>(),nearby=new ArrayList<>();for(JSONObject h:hits)if(h.optJSONObject("amount_match").optBoolean("approximate"))nearby.add(h);else visible.add(h);int quota=Math.min(5,nearby.size());visible=new ArrayList<>(visible.subList(0,Math.min(100-quota,visible.size())));visible.addAll(nearby.subList(0,Math.min(100-visible.size(),nearby.size())));hits=visible;}
        }else if(body.optBoolean("bills_only")||!filter.optString("party").isEmpty()||!filter.optString("date_from").isEmpty()||!filter.optString("invoice_number").isEmpty()){
            for(JSONObject doc:documents){searchCheckpoint();if(store.bill(doc.optString("id"))==null)continue;JSONArray chunks=store.query("SELECT * FROM chunks WHERE document_id=? ORDER BY page_number,chunk_index LIMIT 1",doc.optString("id"));if(chunks.length()==0)continue;JSONObject c=chunks.optJSONObject(0),p=store.one("SELECT * FROM pages WHERE document_id=? AND page_number=?",doc.optString("id"),c.optString("page_number"));JSONObject h=hit(doc,p,c,1);h.put("score_type","bill_fields");h.put("match_reasons",Json.arr("Matched saved bill fields; verify automatic extraction."));hits.add(h);}reliability="unreviewed_bill_fields";
        }else {
            List<JSONObject> exact=literalHits(documents,query);
            try {
            try{semanticInterpretation=interpretSemanticSearch(query);}catch(Exception failure){if(failure instanceof InterruptedException)Thread.currentThread().interrupt();searchCheckpoint();interpreterAvailable=false;}searchCheckpoint();
            float[] vector=NativeModels.embed(models.embedding(),"task: search result | query: "+SemanticQuery.combine(query,semanticInterpretation));PageCandidates<JSONObject> top=new PageCandidates<>(20);searchCheckpoint();
            // Scan only the ranking columns. Passage text, the page row and the
            // chunk hit are fetched for surviving top-20 pages; scores keep
            // the same little-endian decode order and double accumulation.
            for(JSONObject doc:documents)try(Cursor c=store.getReadableDatabase().rawQuery("SELECT id,page_number,chunk_index,input_hash,vector,char_start,char_end FROM chunks WHERE document_id=?",new String[]{doc.optString("id")})){
                int idIndex=c.getColumnIndexOrThrow("id"),pageNumberIndex=c.getColumnIndexOrThrow("page_number"),chunkIndexIndex=c.getColumnIndexOrThrow("chunk_index"),hashIndex=c.getColumnIndexOrThrow("input_hash"),vectorIndex=c.getColumnIndexOrThrow("vector"),startIndex=c.getColumnIndexOrThrow("char_start"),endIndex=c.getColumnIndexOrThrow("char_end");
                while(c.moveToNext()){
                    searchCheckpoint();if(!c.getString(hashIndex).startsWith(models.embeddingSha+":"))continue;
                    byte[] blob=c.getBlob(vectorIndex);if(blob==null||blob.length!=vector.length*4)continue;FloatBuffer saved=ByteBuffer.wrap(blob).order(ByteOrder.LITTLE_ENDIAN).asFloatBuffer();double score=0;for(int i=0;i<vector.length;i++)score+=vector[i]*saved.get(i);
                    int number=c.getInt(pageNumberIndex);String pageKey=doc.optString("id")+":"+number;if(!top.accepts(pageKey,score))continue;
                    String text=store.one("SELECT text FROM chunks WHERE id=?",String.valueOf(c.getLong(idIndex))).optString("text");JSONObject chunk=Json.obj("id",c.getLong(idIndex),"chunk_index",c.getInt(chunkIndexIndex),"text",text,"char_start",c.getInt(startIndex),"char_end",c.getInt(endIndex));
                    JSONObject p=store.one("SELECT * FROM pages WHERE document_id=? AND page_number=?",doc.optString("id"),String.valueOf(number));top.add(pageKey,score,hit(doc,p,chunk,score));}}
            hits.addAll(top.values());
            }catch(Exception failure){searchCheckpoint();if(exact.isEmpty())throw failure;hits.clear();note="Exact indexed text matches; semantic search was unavailable.";}
            mergeLiteral(hits,exact);
            if(body.optBoolean("diversify")){List<JSONObject> ordered=new ArrayList<>();Set<String> seen=new HashSet<>();for(JSONObject h:hits)if(seen.add(h.optString("document_id")))ordered.add(h);for(JSONObject h:hits)if(!ordered.contains(h))ordered.add(h);hits=ordered;}
            hits=new ArrayList<>(hits.subList(0,Math.min(5,hits.size())));
        }
        JSONArray results=new JSONArray();for(int i=0;i<hits.size();i++){hits.get(i).put("rank",i+1);results.put(hits.get(i));}
        boolean bills=requested!=null||body.optBoolean("bills_only")||reliability.equals("unreviewed_bill_fields");
        JSONObject result=Json.obj("query",query,"mode",bills?"bill_fields":"semantic","results",results,"folder_id",body.opt("folder_id"),"document_id",body.opt("document_id"),"elapsed_s",(System.nanoTime()-started)/1e9,"reliability",reliability,"note",note,"below_cutoff",false,"closest_available",false,"empty_reason",results.length()>0?null:documents.isEmpty()?"empty_scope":requested!=null?"no_matching_amount":invoiceNumber!=null?"no_matching_invoice_number":"no_candidates","bill_matches",results.length(),"bill_intent",filter,"amount_tolerance",tolerance.toPlainString());
        int searchable=0,attention=0;for(JSONObject doc:documents){if(doc.optInt("chunk_count")>0)searchable++;if(!doc.optString("status").equals("indexed"))attention++;}result.put("diagnostics",Json.obj("documents",documents.size(),"searchable",searchable,"needs_attention",attention));
        result.put("query_interpreter",usedInterpreter?(interpreterAvailable?"qwen":"unavailable"):"not_needed");result.put("query_intent",queryIntent);if(!semanticInterpretation.isEmpty())result.put("semantic_interpretation",semanticInterpretation);
        result.put("query",originalQuery);if(requested!=null&&!originalQuery.equals(query))result.put("normalized_query",query);
        result.put("applied_prefixes",appliedPrefixes);
        result.put("response",response(query,results));result.put("elapsed_s",(System.nanoTime()-started)/1e9);return result;
    }

    JSONObject response(String query,JSONArray hits)throws Exception {
        boolean hindi=query.matches("(?is).*\\b(bhai|mujhe|muje|dikha|dikhao|wala|wali|lagbhag|samjha|batao|hai)\\b.*")||query.matches("(?s).*[\\u0900-\\u097f].*");
        if(hits.length()==0)return Json.obj("text",hindi?"Koi matching source nahi mila. Amount ya wording check karke dobara try karo.":"No matching source found. Try another phrase, field or amount.","citations",new JSONArray(),"method","empty_scope","limitation",null,"language",hindi?"hinglish":"en");
        JSONArray candidates=new JSONArray();
        for(int i=0;i<Math.min(1,hits.length());i++){
            JSONObject h=hits.optJSONObject(i),doc=store.document(h.optString("document_id")),p=page(h.optString("document_id"),h.optInt("page_number"));JSONObject amount=h.optJSONObject("amount_match");
            String quote=amount==null?h.optString("passage").substring(0,Math.min(220,h.optString("passage").length())):amount.optString("evidence");
            JSONArray notes=new JSONArray();for(int j=0;j<h.optJSONArray("warnings").length();j++)notes.put(h.optJSONArray("warnings").optString(j));if(!h.optBoolean("source_available"))notes.put("Original source unavailable.");if(amount!=null&&!amount.optBoolean("verified"))notes.put("Amount matches indexed text; field association has not been reviewed.");if(amount!=null&&amount.optString("association").equals("unresolved"))notes.put("Multiple amount columns; field association unresolved.");
            String[] raw=p.optString("text").split("\\n");Set<Integer> selected=new TreeSet<>();for(int n=0;n<raw.length;n++)if(raw[n].matches("(?is).*(cancel|void|supersed|revis|correct|replac|currency|total|current|previous|\\bINR\\b|\\bUSD\\b|\\bEUR\\b|₹|\\$|€|£).*"))for(int k=Math.max(0,n-1);k<Math.min(raw.length,n+3);k++)selected.add(k);
            JSONArray contextLines=new JSONArray();int chars=0;for(int n:selected){chars+=raw[n].length();contextLines.put(Json.obj("line",n+1,"text",raw[n]));}boolean overflow=chars>1200||selected.size()>24;if(overflow){contextLines=new JSONArray();notes.put("More source context is needed; open the original before drawing a conclusion.");}
            String location=(isTextFormat(doc.optString("format"))?"Section ":doc.optString("format").equals("pptx")?"Slide ":"Page ")+h.optInt("page_number");
            JSONObject citation=Json.obj("document_id",h.optString("document_id"),"chunk_id",h.optLong("chunk_id"),"source_identity",h.optString("source_identity"),"filename",h.optString("filename"),"page_number",h.optInt("page_number"),"location",location,"excerpt",quote,"qualifications",notes,"extraction_method",h.optString("extraction_method"),"source_available",h.optBoolean("source_available"),"source_sha256",h.optString("source_sha256"),"source_revision",h.optInt("source_revision"),"context",Json.obj("lines",contextLines,"budget_exceeded",overflow,"complete",false,"scope","Indexed page only; other pages or revisions may change meaning."));
            candidates.put(citation);
        }
        // This is source navigation, not a generated answer. Keep the retrieval
        // model resident instead of loading Qwen merely to choose a citation.
        int choice=1;String method="ranked_source",limitation=null;
        JSONObject h=hits.optJSONObject(choice-1),citation=candidates.optJSONObject(choice-1),amount=h.optJSONObject("amount_match");String text;
        if(amount!=null){String value=amount.optString("value"),field=amount.optString("field");
            if(amount.optBoolean("approximate"))text=hindi?"Paas ka invoice mila: indexed "+field+" "+value+", tumhare "+amount.optString("requested_value")+" se difference "+amount.optString("difference")+". Original check kar lo.":"Nearby invoice: indexed "+field+" "+value+"; requested "+amount.optString("requested_value")+", difference "+amount.optString("difference")+". Check the original.";
            else text=hindi?"Invoice ke indexed text mein amount mila. Field aur original source check kar lo.":"I found the amount in indexed invoice text. Check the field and original source below.";
        }else text=hindi?"Is "+citation.optString("location")+" par yeh passage mila. Apne sawaal ke context mein check kar lo:":"Here is a passage to check in "+citation.optString("filename")+", "+citation.optString("location").toLowerCase(Locale.ROOT)+":";
        return Json.obj("text",text,"citations",Json.arr(citation),"method",method,"limitation",limitation,"language",hindi?"hinglish":"en","answer_scope","source_navigation");
    }
    JSONArray linkedFolders(){Set<String> visible=new HashSet<>();for(JSONObject d:LibraryStore.objects(phoneScan.visibleDocuments(store.documents())))visible.add(d.optString("id"));JSONArray result=new JSONArray();for(JSONObject source:LibraryStore.objects(features.groups())){JSONObject group=Json.parse(source.toString());JSONArray ids=new JSONArray();for(String id:strings(group.optJSONArray("document_ids")))if(visible.contains(id))ids.put(id);try{group.put("document_ids",ids);group.put("document_count",ids.length());}catch(JSONException error){throw new IllegalStateException(error);}if(ids.length()>0)result.put(group);}return result;}
    JSONArray legacyLinkedFolders(){
        String key=store.query("SELECT id,sha256,title,updated_at,trashed FROM documents ORDER BY id").toString()+store.bills().toString();
        if(linkCache!=null&&key.equals(linkKey))return linkCache;
        Map<String,List<String>> groups=new TreeMap<>();for(JSONObject bill:LibraryStore.objects(store.bills())){String party=bill.optString("party").trim();if(!party.isEmpty())groups.computeIfAbsent("Customer · "+party,k->new ArrayList<>()).add(bill.optString("document_id"));}
        Set<String> stop=new HashSet<>(Arrays.asList("this","that","with","from","your","have","will","which","into","more","than","page","slide","invoice","total","synthetic","test","only","text","theory","document"));
        for(JSONObject doc:LibraryStore.objects(phoneScan.visibleDocuments(store.documents()))){Map<String,Integer> frequency=new HashMap<>();for(JSONObject p:LibraryStore.objects(store.query("SELECT substr(text,1,10000) text FROM pages WHERE document_id=? LIMIT 30",doc.optString("id"))))for(String word:normalize(p.optString("text")).split("\\s+"))if(word.length()>=5&&!stop.contains(word)&&!word.matches("\\d+"))frequency.put(word,frequency.getOrDefault(word,0)+1);
            List<String> ordered=new ArrayList<>(frequency.keySet());ordered.sort((a,b)->Integer.compare(frequency.get(b),frequency.get(a)));for(String word:ordered.subList(0,Math.min(5,ordered.size())))if(frequency.get(word)>=2)groups.computeIfAbsent("Topic · "+word,k->new ArrayList<>()).add(doc.optString("id"));}
        JSONArray result=new JSONArray();for(Map.Entry<String,List<String>> entry:groups.entrySet())if(new HashSet<>(entry.getValue()).size()>=2){JSONArray ids=new JSONArray();for(String id:new LinkedHashSet<>(entry.getValue()))ids.put(id);result.put(Json.obj("id","linked-"+Integer.toHexString(entry.getKey().hashCode()),"name",entry.getKey(),"basis",entry.getKey().startsWith("Customer")?"Shared saved customer field; automatic extraction may need review.":"Shared repeated source words; this is a suggested link, not a verified category.","document_ids",ids,"document_count",ids.length()));if(result.length()>=30)break;}linkKey=key;linkCache=result;return result;
    }
    JSONObject duplicates(){Map<String,JSONArray> exact=new HashMap<>(),names=new HashMap<>();for(JSONObject doc:LibraryStore.objects(phoneScan.visibleDocuments(store.documents()))){exact.computeIfAbsent(doc.optString("sha256"),k->new JSONArray()).put(doc);names.computeIfAbsent(normalize(doc.optString("title").replaceAll("(?i)\\b(copy|final|revised|updated|v\\d+)\\b","")),k->new JSONArray()).put(doc);}JSONArray e=new JSONArray(),n=new JSONArray();for(JSONArray group:exact.values())if(group.length()>1)e.put(group);for(JSONArray group:names.values())if(group.length()>1)n.put(group);return Json.obj("exact",e,"possible_revisions",n,"repeated_invoice_numbers",new JSONArray());}
    JSONObject compare(JSONObject body)throws Exception {JSONArray ids=body.optJSONArray("document_ids");if(ids==null||ids.length()<2||ids.length()>5)throw new IllegalArgumentException("Choose two to five documents");JSONArray result=new JSONArray();String query=body.optString("query");for(int i=0;i<ids.length();i++){String id=ids.optString(i);JSONObject doc=store.document(id);JSONArray amounts=new JSONArray();for(JSONObject p:LibraryStore.objects(store.query("SELECT * FROM pages WHERE document_id=?",id)))for(JSONObject amount:LibraryStore.objects(Money.amounts(p.optString("text"),Json.parse(p.optString("evidence"))))){amount.put("page_number",p.optInt("page_number"));amounts.put(amount);}JSONArray passages=new JSONArray();if(!query.isEmpty())for(JSONObject h:LibraryStore.objects(search(Json.obj("query",query,"document_id",id)).optJSONArray("results")))passages.put(Json.obj("page_number",h.optInt("page_number"),"passage",h.optString("passage")));result.put(Json.obj("document",doc,"bill",store.bill(id),"source_amounts",amounts,"passages",passages));}return Json.obj("documents",result,"note","Compared indexed fields and source passages; no inferred corrections or generated facts.");}
    JSONObject storage(){long managed=0;for(JSONObject d:LibraryStore.objects(store.query("SELECT source_path,preview_path FROM documents WHERE source_mode!='reference'"))){File f=new File(store.root,d.optString("source_path"));managed+=f.length();if(!d.optString("preview_path").equals(d.optString("source_path")))managed+=new File(store.root,d.optString("preview_path")).length();}return Json.obj("database_bytes",context.getDatabasePath("library.sqlite3").length(),"managed_pdf_bytes",managed,"reclaimable_bytes",0,"free_bytes",store.root.getUsableSpace(),"trash_documents",store.one("SELECT count(*) n FROM documents WHERE trashed=1").optInt("n"));}
    JSONObject cleanup(){if(AndroidSharing.active())throw new IllegalArgumentException("Wait for shared PDFs to finish adding.");Set<String> referenced=new HashSet<>();for(JSONObject doc:LibraryStore.objects(store.query("SELECT source_path,preview_path FROM documents"))){referenced.add(doc.optString("source_path"));referenced.add(doc.optString("preview_path"));}for(JSONObject task:LibraryStore.objects(store.query("SELECT source_path FROM tasks WHERE is_reference=0 AND status IN ('queued','running','skipping','skipped','failed','interrupted')")))if(!task.isNull("source_path"))referenced.add(relative(new File(task.optString("source_path"))));long bytes=0;int count=0;for(String dir:new String[]{"sources","previews"}){File[] files=new File(store.root,dir).listFiles();if(files==null)continue;for(File file:files)if(!referenced.contains(relative(file))){long size=file.length();if(file.delete()){bytes+=size;count++;}}}return Json.obj("removed_files",count,"reclaimed_bytes",bytes);}
    JSONObject verify()throws Exception {JSONArray issues=new JSONArray();try(Cursor c=store.getReadableDatabase().rawQuery("PRAGMA integrity_check",null)){if(!c.moveToFirst()||!c.getString(0).equals("ok"))issues.put("Database integrity check failed");}for(JSONObject doc:LibraryStore.objects(store.query("SELECT * FROM documents"))){try{File file=store.source(doc.optString("id"),true);if(!LibraryStore.hash(file).equals(doc.optString("sha256")))issues.put("Changed source");}catch(Exception error){issues.put("Missing or changed source");}}return Json.obj("passed",issues.length()==0,"issues",issues);}
    boolean idle(){return !embeddingUpgrade.running&&!AndroidSharing.active()&&!(phoneScan!=null&&(phoneScan.finding||phoneScan.pending()))&&store.one("SELECT count(*) n FROM tasks WHERE status IN ('queued','running','skipping')").optInt("n")==0;}
    void close(){closed=true;indexing.shutdownNow();store.close();}
}
