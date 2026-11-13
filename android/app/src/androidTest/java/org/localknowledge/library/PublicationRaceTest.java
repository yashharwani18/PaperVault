package org.localknowledge.library;
import android.content.*;
import android.graphics.Paint;
import android.graphics.pdf.PdfDocument;
import android.net.Uri;
import android.os.Environment;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import org.json.*;
import org.junit.Test;
import org.junit.runner.RunWith;
import java.io.*;
import java.util.*;
import static org.junit.Assert.*;

@RunWith(AndroidJUnit4.class)
public class PublicationRaceTest {
    NativeBackend backend(){return ((LibraryApplication)InstrumentationRegistry.getInstrumentation().getTargetContext().getApplicationContext()).backend;}
    @Test public void ignoreAndPublicationSerializeWithoutReplacingOldIndex()throws Exception {
        NativeBackend b=backend();b.models.embedding();boolean paused=b.paused;String saved=b.phoneScan.value("phone_scan.exclusions"),id=LibraryStore.id(),task="";File root=new File(Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOCUMENTS),"Khoj-publication-"+id);assertTrue(root.mkdirs());File file=new File(root,"Race.pdf");
        PdfDocument pdf=new PdfDocument();try{var page=pdf.startPage(new PdfDocument.PageInfo.Builder(400,500,1).create());Paint p=new Paint();p.setTextSize(16);page.getCanvas().drawText("Signals and Fourier transforms for publication race "+id,20,60,p);pdf.finishPage(page);try(OutputStream out=new FileOutputStream(file)){pdf.writeTo(out);}}finally{pdf.close();}
        String sha=LibraryStore.hash(file),folder=b.store.folders().optJSONObject(0).optString("id"),now=LibraryStore.now();b.store.exec("INSERT INTO documents(id,folder_id,filename,title,sha256,source_path,preview_path,source_uri,format,page_count,chunk_count,status,version,created_at,updated_at,size_bytes,trashed,source_mode) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",id,folder,"Race.pdf","Race",sha,file.getCanonicalPath(),file.getCanonicalPath(),Uri.fromFile(file).toString(),"pdf",1,0,"indexed",1,now,now,file.length(),0,"reference");b.store.exec("INSERT INTO pages VALUES(?,?,?,?,?,?)",id,1,"OLD INDEX","native","[]","{}");b.paused=false;
        try{
            synchronized(b){
                task=b.enqueue(Uri.fromFile(file).toString(),file.getName(),folder,id,false,false,true);b.store.exec("INSERT OR REPLACE INTO phone_scan_files(path,signature,task_id,state,document_id) VALUES(?,?,?,'queued',?)",file.getCanonicalPath(),file.length()+":"+file.lastModified(),task,id);
                long end=System.currentTimeMillis()+15000;boolean blocked=false;while(System.currentTimeMillis()<end){for(var entry:Thread.getAllStackTraces().entrySet())if(entry.getKey().getState()==Thread.State.BLOCKED&&entry.getValue().length>0){StackTraceElement frame=entry.getValue()[0];if(frame.getClassName().equals(NativeBackend.class.getName())&&frame.getMethodName().equals("importTask"))blocked=true;}if(blocked)break;String status=b.store.one("SELECT status FROM tasks WHERE id=?",task).optString("status");if(status.equals("completed")||status.equals("failed"))break;Thread.sleep(30);}
                assertTrue("Publication must wait for the same lock used by Ignore",blocked);
                b.phoneScan.route("/phone-scan/exclusions","POST",Json.obj("path",file.getCanonicalPath(),"kind","file"));
            }
            long end=System.currentTimeMillis()+15000;while(b.store.one("SELECT status FROM tasks WHERE id=?",task).optString("status").equals("running")&&System.currentTimeMillis()<end)Thread.sleep(30);
            assertEquals("failed",b.store.one("SELECT status FROM tasks WHERE id=?",task).optString("status"));assertEquals("OLD INDEX",b.store.one("SELECT text FROM pages WHERE document_id=? AND page_number=1",id).optString("text"));
        }finally{b.phoneScan.set("phone_scan.exclusions",saved);b.store.exec("DELETE FROM phone_scan_files WHERE path=?",file.getCanonicalPath());b.store.exec("DELETE FROM documents WHERE id=?",id);if(!task.isEmpty())b.store.exec("DELETE FROM tasks WHERE id=?",task);b.paused=paused;file.delete();root.delete();}
    }
    @Test public void generatedLibrarySourcesRemainReadable()throws Exception {
        NativeBackend b=backend();JSONArray bad=new JSONArray();for(JSONObject d:LibraryStore.objects(b.store.query("SELECT * FROM documents")))try{b.store.source(d.optString("id"),true);}catch(Exception error){bad.put(Json.obj("id",d.optString("id"),"fixture",d.optString("filename"),"problem",error.getClass().getSimpleName()+": "+error.getMessage()));}
        assertEquals(bad.toString(),0,bad.length());assertTrue(b.verify().toString(),b.verify().optBoolean("passed"));
    }
}
