package org.localknowledge.library;

import android.content.Context;
import android.net.Uri;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import org.json.JSONObject;
import org.junit.Test;
import org.junit.runner.RunWith;
import java.io.File;
import java.io.FileOutputStream;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import static org.junit.Assert.*;

@RunWith(AndroidJUnit4.class)
public class IndexSkipTest {
    NativeBackend backend(){return ((LibraryApplication)InstrumentationRegistry.getInstrumentation().getTargetContext().getApplicationContext()).backend;}
    File source(NativeBackend b)throws Exception{File p=new File(b.context.getCacheDir(),"skip-"+System.nanoTime()+".pdf");try(FileOutputStream out=new FileOutputStream(p)){out.write("No PDF parsing should occur before Skip".getBytes(java.nio.charset.StandardCharsets.UTF_8));}return p;}
    String status(NativeBackend b,String id){return b.store.one("SELECT status FROM tasks WHERE id=?",id).optString("status");}
    void await(NativeBackend b,String id,String expected)throws Exception{long end=System.currentTimeMillis()+8000;while(System.currentTimeMillis()<end&&!status(b,id).equals(expected))Thread.sleep(25);assertEquals(expected,status(b,id));}

    @Test public void queuedSkipNeverReadsSourceAndDoesNotBlockTheNextJob()throws Exception {
        NativeBackend b=backend();File p=source(b);String folder=b.store.folders().optJSONObject(0).optString("id"),task="";
        CountDownLatch entered=new CountDownLatch(1),release=new CountDownLatch(1);
        b.indexing.submit(()->{entered.countDown();try{release.await(10,TimeUnit.SECONDS);}catch(InterruptedException e){Thread.currentThread().interrupt();}});
        assertTrue(entered.await(2,TimeUnit.SECONDS));
        try{
            task=b.enqueue(Uri.fromFile(p).toString(),p.getName(),folder,"",false,false);
            assertEquals("skipped",b.dispatch("/tasks/"+task+"/skip","POST",Json.obj()).optString("status"));
            release.countDown();b.indexing.submit(()->{}).get(5,TimeUnit.SECONDS);
            assertEquals("skipped",status(b,task));assertTrue(p.isFile());
            assertEquals(0,b.store.query("SELECT id FROM documents WHERE filename=?",p.getName()).length());
            assertTrue(b.store.one("SELECT * FROM tasks WHERE id=?",task).isNull("source_path"));
        }finally{release.countDown();if(!task.isEmpty())b.store.exec("DELETE FROM tasks WHERE id=?",task);p.delete();}
    }

    @Test public void activeSkipWorksWhilePausedAndKeepsThePreviousIndex()throws Exception {
        NativeBackend b=backend();File p=source(b);boolean paused=b.paused;String folder=b.store.folders().optJSONObject(0).optString("id"),id=LibraryStore.id(),task="",now=LibraryStore.now();
        b.store.exec("INSERT INTO documents(id,folder_id,filename,title,sha256,source_path,preview_path,source_uri,format,page_count,chunk_count,status,version,created_at,updated_at,size_bytes,trashed,source_mode) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",id,folder,p.getName(),"Previous index","old-hash",p.getPath(),p.getPath(),Uri.fromFile(p).toString(),"pdf",1,0,"indexed",1,now,now,p.length(),0,"reference");
        b.store.exec("INSERT INTO pages VALUES(?,?,?,?,?,?)",id,1,"PREVIOUS COMMITTED TEXT","native","[]","{}");
        try{
            b.paused=true;task=b.enqueue(Uri.fromFile(p).toString(),p.getName(),folder,id,false,false);
            await(b,task,"running");assertEquals("skipping",b.dispatch("/tasks/"+task+"/skip","POST",Json.obj()).optString("status"));
            await(b,task,"skipped");assertEquals("PREVIOUS COMMITTED TEXT",b.store.one("SELECT text FROM pages WHERE document_id=?",id).optString("text"));
            assertEquals(1,b.store.document(id).optInt("version"));assertTrue(p.isFile());
        }finally{b.paused=paused;b.store.exec("DELETE FROM documents WHERE id=?",id);if(!task.isEmpty())b.store.exec("DELETE FROM tasks WHERE id=?",task);p.delete();}
    }

    @Test public void skippedScanItemDoesNotAutomaticallyRequeue()throws Exception {
        NativeBackend b=backend();File p=source(b);boolean allowed=b.phoneScan.processingAllowed;b.phoneScan.processingAllowed=false;String folder=b.store.folders().optJSONObject(0).optString("id"),task=LibraryStore.id();
        b.store.exec("INSERT INTO tasks(id,filename,status,source_uri,folder_id,replace_id,ocr,is_bill,is_reference,created_at) VALUES(?,?,'skipped',?,?,'',0,0,1,?)",task,p.getName(),Uri.fromFile(p).toString(),folder,LibraryStore.now());
        b.store.exec("INSERT INTO phone_scan_files(path,signature,task_id,state) VALUES(?,?,?,'queued')",p.getCanonicalPath(),p.length()+":"+p.lastModified(),task);
        try{
            b.phoneScan.pump();assertEquals("skipped",b.store.one("SELECT state FROM phone_scan_files WHERE path=?",p.getCanonicalPath()).optString("state"));
            b.phoneScan.pump();assertEquals("skipped",status(b,task));
            assertTrue(b.store.one("SELECT * FROM phone_scan_files WHERE path=?",p.getCanonicalPath()).isNull("task_id"));
        }finally{b.phoneScan.processingAllowed=allowed;b.store.exec("DELETE FROM phone_scan_files WHERE path=?",p.getCanonicalPath());b.store.exec("DELETE FROM tasks WHERE id=?",task);p.delete();}
    }

    @Test public void finalCommitCannotBeSkipped()throws Exception {
        NativeBackend b=backend();String folder=b.store.folders().optJSONObject(0).optString("id"),task=LibraryStore.id();
        b.store.exec("INSERT INTO tasks(id,filename,status,progress,source_uri,folder_id,replace_id,ocr,is_bill,is_reference,created_at) VALUES(?,?,'running',?,?,?,'',0,0,0,?)",task,"finishing.pdf",Json.obj("stage","committing").toString(),"file:///unused.pdf",folder,LibraryStore.now());
        try{assertEquals("running",b.dispatch("/tasks/"+task+"/skip","POST",Json.obj()).optString("status"));assertEquals("running",status(b,task));}
        finally{b.store.exec("DELETE FROM tasks WHERE id=?",task);}
    }

    @Test public void explicitRetryOfSkippedFileCanFinish()throws Exception {
        NativeBackend b=backend();File p=source(b);android.graphics.pdf.PdfDocument pdf=new android.graphics.pdf.PdfDocument();
        try{var page=pdf.startPage(new android.graphics.pdf.PdfDocument.PageInfo.Builder(200,200,1).create());pdf.finishPage(page);try(FileOutputStream out=new FileOutputStream(p)){pdf.writeTo(out);}}finally{pdf.close();}
        String folder=b.store.folders().optJSONObject(0).optString("id"),task=LibraryStore.id();boolean paused=b.paused;b.paused=false;
        b.store.exec("INSERT INTO tasks(id,filename,status,source_uri,folder_id,replace_id,ocr,is_bill,is_reference,created_at) VALUES(?,?,'skipped',?,?,'',0,0,0,?)",task,p.getName(),Uri.fromFile(p).toString(),folder,LibraryStore.now());
        String doc="";
        try{assertEquals(task,b.features.retry(task));await(b,task,"completed");JSONObject result=Json.parse(b.store.one("SELECT result FROM tasks WHERE id=?",task).optString("result"));doc=result.getJSONObject("document").getString("id");assertTrue(p.isFile());assertEquals("added",result.optString("action"));}
        finally{b.paused=paused;if(!doc.isEmpty())b.store.exec("DELETE FROM documents WHERE id=?",doc);b.store.exec("DELETE FROM tasks WHERE id=?",task);p.delete();}
    }
}
