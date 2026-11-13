package org.localknowledge.library;

import android.content.Context;
import androidx.test.platform.app.InstrumentationRegistry;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.json.*;
import static org.junit.Assert.*;

@RunWith(AndroidJUnit4.class)
public class KhojFeaturesTest {
    @Test public void retryKeepsCachedSourceAndRotatedHighlightIsHonest()throws Exception {
        Context context=InstrumentationRegistry.getInstrumentation().getTargetContext();NativeBackend backend=((LibraryApplication)context.getApplicationContext()).backend;
        String task=LibraryStore.id(),folder=backend.store.folders().getJSONObject(0).getString("id");
        java.io.File cached=new java.io.File(backend.store.root,"sources/"+task+".pdf");byte[] bytes="Unusable PDF retained for retry safety".getBytes(java.nio.charset.StandardCharsets.UTF_8);try(java.io.OutputStream out=new java.io.FileOutputStream(cached)){out.write(bytes);}String hash=LibraryStore.hash(cached);
        backend.store.exec("INSERT INTO tasks(id,filename,status,source_path,source_uri,folder_id,replace_id,ocr,is_bill,created_at) VALUES(?,?,'failed',?,?,?,'',0,0,?)",task,"Retry fixture.pdf",cached.getAbsolutePath(),"content://missing/original",folder,LibraryStore.now());
        backend.features.retry(task);long deadline=System.currentTimeMillis()+30000;while(!backend.idle()&&System.currentTimeMillis()<deadline)Thread.sleep(100);
        assertTrue(backend.idle());assertEquals(hash,LibraryStore.hash(cached));backend.store.exec("DELETE FROM tasks WHERE id=?",task);cached.delete();
        String id=LibraryStore.id(),now=LibraryStore.now();backend.store.exec("INSERT INTO documents(id,folder_id,filename,title,sha256,source_path,preview_path,source_uri,format,page_count,chunk_count,status,version,created_at,updated_at,size_bytes) VALUES(?,?,'Rotated.pdf','Rotated','fixture','none','none','none','pdf',1,0,'indexed',1,?,?,0)",id,folder,now,now);
        try{backend.store.exec("INSERT INTO pages VALUES(?,1,'word','native','[]',?)",id,Json.obj("rotation",90,"bounds",Json.arr(0,0,595,842),"words",Json.arr(Json.arr(10,10,50,30,"word"))).toString());assertEquals(0,backend.highlight(id,1,"word").getJSONArray("boxes").length());}finally{backend.store.exec("DELETE FROM documents WHERE id=?",id);}
    }
    @Test public void releasePrivacyAndOrganizationWork()throws Exception {
        Context context=InstrumentationRegistry.getInstrumentation().getTargetContext();
        NativeBackend backend=((LibraryApplication)context.getApplicationContext()).backend;
        assertEquals("PaperVault",backend.dispatch("/about","GET",new JSONObject()).getString("name"));
        String privateValue="PRIVATE_KHOJ_DIAGNOSTIC_"+System.nanoTime();
        String first=backend.dispatch("/folders","POST",Json.obj("name",privateValue)).getString("id");
        String second=backend.dispatch("/folders","POST",Json.obj("name",privateValue+" second")).getString("id");
        String id=LibraryStore.id(),now=LibraryStore.now();
        backend.store.exec("INSERT INTO documents(id,folder_id,filename,title,sha256,source_path,preview_path,source_uri,format,page_count,chunk_count,status,version,created_at,updated_at,size_bytes) VALUES(?,?,?,?,?,?,?,?,?,1,0,'empty',1,?,?,0)",id,first,privateValue+".pdf",privateValue,privateValue,"missing.pdf","missing.pdf","content://private/"+privateValue,"pdf",now,now);
        try {
            String topic=backend.dispatch("/organization/topics","POST",Json.obj("name",privateValue)).getString("id");
            backend.dispatch("/organization/topics/assign","POST",Json.obj("document_ids",Json.arr(id),"topic_ids",Json.arr(topic)));
            backend.dispatch("/organization/topics/"+topic,"PATCH",Json.obj("name",privateValue+" renamed"));
            assertEquals(topic,backend.dispatch("/organization/documents/"+id,"GET",new JSONObject()).getJSONArray("topic_ids").getString(0));
            backend.dispatch("/organization/documents/"+id+"/name","PUT",Json.obj("name","Saved personal name"));
            JSONObject moved=backend.dispatch("/organization/move","POST",Json.obj("document_ids",Json.arr(id),"folder_id",second));
            assertEquals(second,backend.store.document(id).getString("folder_id"));
            backend.dispatch("/organization/moves/"+moved.getString("undo_token")+"/undo","POST",new JSONObject());
            assertEquals(first,backend.store.document(id).getString("folder_id"));
            assertEquals("missing",backend.dispatch("/documents/"+id+"/recovery","GET",new JSONObject()).getJSONObject("source").getString("code"));
            String diagnostic=backend.dispatch("/diagnostics","POST",new JSONObject()).toString();
            assertFalse(diagnostic.contains(privateValue));assertFalse(diagnostic.contains("source_path"));assertFalse(diagnostic.contains(context.getFilesDir().toString()));
            assertEquals("PaperVault",new JSONObject(diagnostic).getJSONObject("product").getString("name"));
            boolean found=false;for(JSONObject doc:LibraryStore.objects(backend.state().getJSONArray("documents")))if(doc.getString("id").equals(id)){assertEquals("Saved personal name",doc.getString("display_title"));found=true;}assertTrue(found);
        } finally {backend.store.exec("DELETE FROM documents WHERE id=?",id);backend.store.exec("DELETE FROM folders WHERE id IN (?,?)",first,second);}
    }
}
