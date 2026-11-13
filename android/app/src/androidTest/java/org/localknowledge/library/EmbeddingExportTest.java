package org.localknowledge.library;

import android.content.Context;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import org.json.*;
import org.junit.Test;
import org.junit.runner.RunWith;
import java.io.*;
import java.nio.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.zip.*;
import static org.junit.Assert.*;

@RunWith(AndroidJUnit4.class)
public class EmbeddingExportTest {
    @Test public void exportedVectorsRetainTextSourceAndModelIdentity() throws Exception {
        Context context=InstrumentationRegistry.getInstrumentation().getTargetContext();
        NativeBackend b=((LibraryApplication)context.getApplicationContext()).backend;
        String folder=LibraryStore.id(),id=LibraryStore.id(),trashed=LibraryStore.id(),now=LibraryStore.now();
        b.store.exec("INSERT INTO folders VALUES(?,?,'blue',?,?)",folder,"Export test "+folder,now,now);
        try {
            document(b,folder,id,now,0);document(b,folder,trashed,now,1);
            b.store.exec("INSERT INTO pages VALUES(?,1,?,'native','[]','{}')",id,"Invoice No: 25\nTotal: 6600");
            b.store.exec("INSERT INTO chunks(document_id,page_number,chunk_index,text,char_start,char_end,vector,input_hash) VALUES(?,1,0,?,0,24,?,?)",id,"Invoice No: 25\nTotal: 6600",LibraryStore.vector(new float[]{1.25f,-2f,0.5f}),"fixture-model:input-sha");
            b.store.exec("INSERT INTO chunks(document_id,page_number,chunk_index,text,char_start,char_end,vector,input_hash) VALUES(?,1,1,'Not embedded yet',24,40,NULL,'')",id);
            ByteArrayOutputStream bytes=new ByteArrayOutputStream();
            try {Class.forName("org.localknowledge.library.EmbeddingExport").getDeclaredMethod("write",NativeBackend.class,OutputStream.class).invoke(null,b,bytes);}
            catch(ClassNotFoundException missing){fail("Embedding export is not implemented");}
            Map<String,byte[]> files=new HashMap<>();
            try(ZipInputStream zip=new ZipInputStream(new ByteArrayInputStream(bytes.toByteArray()))){ZipEntry entry;while((entry=zip.getNextEntry())!=null){ByteArrayOutputStream file=new ByteArrayOutputStream();NativeTransfer.copy(zip,file);files.put(entry.getName(),file.toByteArray());}}
            assertEquals(new HashSet<>(Arrays.asList("manifest.json","documents.jsonl","pages.jsonl","chunks.jsonl","vectors.f32")),files.keySet());
            JSONObject manifest=new JSONObject(new String(files.get("manifest.json"),StandardCharsets.UTF_8));
            assertEquals("khoj-embeddings-v1",manifest.getString("format"));
            assertEquals("little",manifest.getString("byte_order"));
            JSONObject hashes=manifest.getJSONObject("sha256");
            for(String name:files.keySet())if(!name.equals("manifest.json"))assertEquals(name,hashes.getString(name),LibraryStore.hash(files.get(name)));
            JSONObject doc=find(files,"documents.jsonl",id,"id");assertEquals("Analysis fixture.pdf",doc.getString("filename"));assertEquals("source-sha",doc.getString("source_sha256"));
            assertFalse(doc.has("source_path"));assertFalse(doc.has("source_uri"));
            assertNull(find(files,"documents.jsonl",trashed,"id"));
            assertEquals("Invoice No: 25\nTotal: 6600",find(files,"pages.jsonl",id,"document_id").getString("text"));
            List<JSONObject> chunks=new ArrayList<>();for(String line:new String(files.get("chunks.jsonl"),StandardCharsets.UTF_8).split("\n")){JSONObject chunk=new JSONObject(line);if(chunk.getString("document_id").equals(id))chunks.add(chunk);}
            assertEquals(2,chunks.size());JSONObject chunk=chunks.get(0);
            assertEquals("fixture-model:input-sha",chunk.getString("input_hash"));assertEquals(3,chunk.getInt("dimensions"));
            ByteBuffer vector=ByteBuffer.wrap(files.get("vectors.f32")).order(ByteOrder.LITTLE_ENDIAN);vector.position(chunk.getInt("vector_offset_bytes"));
            assertEquals(1.25f,vector.getFloat(),0);assertEquals(-2f,vector.getFloat(),0);assertEquals(.5f,vector.getFloat(),0);
            assertTrue(chunks.get(1).isNull("vector_offset_bytes"));assertEquals(0,chunks.get(1).getInt("dimensions"));
        } finally {b.store.exec("DELETE FROM documents WHERE folder_id=?",folder);b.store.exec("DELETE FROM folders WHERE id=?",folder);}
    }
    JSONObject find(Map<String,byte[]> files,String name,String id,String key) throws Exception {for(String line:new String(files.get(name),StandardCharsets.UTF_8).split("\n")){if(line.isEmpty())continue;JSONObject row=new JSONObject(line);if(row.getString(key).equals(id))return row;}return null;}
    void document(NativeBackend b,String folder,String id,String now,int trashed){b.store.exec("INSERT INTO documents(id,folder_id,filename,title,sha256,source_path,preview_path,source_uri,format,page_count,chunk_count,status,version,created_at,updated_at,size_bytes,trashed,source_mode) VALUES(?,?,'Analysis fixture.pdf','Analysis fixture','source-sha','missing','missing','content://private/path','pdf',1,2,'partial',1,?,?,0,?,'managed')",id,folder,now,now,trashed);}
}
