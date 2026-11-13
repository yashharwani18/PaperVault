package org.localknowledge.library;

import android.content.Context;
import android.database.Cursor;
import android.database.sqlite.SQLiteDatabase;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import org.json.*;
import org.junit.Test;
import org.junit.runner.RunWith;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.zip.*;
import static org.junit.Assert.*;

/** Retrieval-only experiment: real current Android models, fixed public source text. */
@RunWith(AndroidJUnit4.class)
public class RetrievalBenchmarkTest {
    @Test public void exportCurrentModelRetrievalSnapshot() throws Exception {
        Context tests=InstrumentationRegistry.getInstrumentation().getContext(),context=InstrumentationRegistry.getInstrumentation().getTargetContext();
        NativeBackend b=((LibraryApplication)context.getApplicationContext()).backend;
        byte[] bytes;try(InputStream in=tests.getAssets().open("retrieval-benchmark/corpus.json")){bytes=ModelAssets.read(in);}
        JSONObject corpus=new JSONObject(new String(bytes,StandardCharsets.UTF_8));String corpusSha=LibraryStore.hash(bytes);
        String model=b.models.embedding();String identity=b.models.embeddingSha;
        File destination=new File(context.getFilesDir(),"retrieval-benchmark.zip"),partial=new File(context.getFilesDir(),"retrieval-benchmark.partial");
        if(destination.isFile())try(ZipFile existing=new ZipFile(destination)){
            JSONObject manifest=new JSONObject(new String(ModelAssets.read(existing.getInputStream(existing.getEntry("manifest.json"))),StandardCharsets.UTF_8));
            if(manifest.optString("corpus_sha256").equals(corpusSha)&&manifest.optString("model_identity").equals(identity)&&manifest.optString("chunk_recipe").equals(PageIndexer.RECIPE)){status("Reusing matching benchmark snapshot");return;}
        }catch(Exception ignored){}
        boolean paused=b.paused;b.paused=true;int chunkId=0,pages=0;long indexStart=System.nanoTime();
        try(ZipOutputStream zip=new ZipOutputStream(new FileOutputStream(partial))) {
            zip.putNextEntry(new ZipEntry("chunks.jsonl"));
            for(JSONObject document:LibraryStore.objects(corpus.getJSONArray("documents"))) {
                try(SQLiteDatabase stage=SQLiteDatabase.create(null)){
                    stage.execSQL("CREATE TABLE pages(page_number INTEGER,text TEXT,method TEXT,warnings TEXT,evidence TEXT)");
                    stage.execSQL("CREATE TABLE chunks(page_number INTEGER,chunk_index INTEGER,text TEXT,char_start INTEGER,char_end INTEGER,vector BLOB,input_hash TEXT)");
                    PageIndexer.Engine engine=new PageIndexer.Engine(){public int tokens(String text){return NativeModels.tokenCount(model,text);}public float[] scalar(String text){return NativeModels.embed(model,text);}public float[][] batch(String[] text){return NativeModels.embedBatch(model,text);}};
                    PageIndexer indexer=new PageIndexer(b.store,stage,identity,document.getString("title"),engine,NativeBackend::searchCheckpoint,4,true);
                    for(JSONObject page:LibraryStore.objects(document.getJSONArray("pages"))){indexer.indexPage(page.getInt("page_number"),page.getString("text"),"fixed-pymupdf","[]","{}",n->{});pages++;}
                    indexer.finish(n->{});
                    try(Cursor cursor=stage.rawQuery("SELECT * FROM chunks ORDER BY chunk_index",null)){while(cursor.moveToNext()){
                        JSONObject row=NativeLibraryBrowse.row(cursor);row.put("id",++chunkId);row.put("document",document.getString("id"));row.put("title",document.getString("title"));
                        row.put("vector",new JSONArray(LibraryStore.vector(cursor.getBlob(cursor.getColumnIndexOrThrow("vector")))));line(zip,row);
                    }}
                }
                status(document.getString("id")+"; "+pages+" pages, "+chunkId+" chunks");
            }
            zip.closeEntry();double indexingMs=(System.nanoTime()-indexStart)/1e6;
            zip.putNextEntry(new ZipEntry("queries.jsonl"));int queries=0;
            for(JSONObject query:LibraryStore.objects(corpus.getJSONArray("queries"))) {
                String original=query.getString("query");long start=System.nanoTime();
                float[] originalVector=NativeModels.embed(model,"task: search result | query: "+original);double originalMs=(System.nanoTime()-start)/1e6;
                start=System.nanoTime();String rewrite=b.interpretSemanticSearch(original);double rewriteMs=(System.nanoTime()-start)/1e6;
                start=System.nanoTime();float[] combined=NativeModels.embed(model,"task: search result | query: "+SemanticQuery.combine(original,rewrite));double combinedMs=(System.nanoTime()-start)/1e6;
                start=System.nanoTime();float[] rewritten=rewrite.trim().equalsIgnoreCase(original.trim())?originalVector:NativeModels.embed(model,"task: search result | query: "+rewrite);double rewrittenMs=(System.nanoTime()-start)/1e6;
                JSONObject row=new JSONObject(query.toString());row.put("rewrite",rewrite);row.put("original_vector",new JSONArray(originalVector));row.put("combined_vector",new JSONArray(combined));row.put("rewrite_vector",new JSONArray(rewritten));
                row.put("timing_ms",Json.obj("original_embedding",originalMs,"rewrite_generation",rewriteMs,"combined_embedding",combinedMs,"rewrite_embedding",rewrittenMs));line(zip,row);
                if(++queries%5==0)status("Queries "+queries+"/"+corpus.getJSONArray("queries").length());
            }
            zip.closeEntry();zip.putNextEntry(new ZipEntry("manifest.json"));line(zip,Json.obj("format","khoj-retrieval-benchmark-v1","baseline_build",21,"corpus_sha256",corpusSha,"model_identity",identity,"chunk_recipe",PageIndexer.RECIPE,"documents",20,"pages",pages,"chunks",chunkId,"queries",queries,"indexing_ms",indexingMs,"device","Android x86_64 emulator; not physical ARM latency","scope",corpus.getString("scope")));zip.closeEntry();
            assertTrue(chunkId>0);assertEquals(1346,pages);assertEquals(62,queries);
        } finally {b.paused=paused;}
        if(destination.exists())assertTrue(destination.delete());assertTrue(partial.renameTo(destination));status("Benchmark snapshot complete");
    }
    static void line(ZipOutputStream zip,JSONObject row) throws Exception {zip.write((row.toString()+"\n").getBytes(StandardCharsets.UTF_8));}
    static void status(String text){android.os.Bundle bundle=new android.os.Bundle();bundle.putString("retrieval_benchmark",text);InstrumentationRegistry.getInstrumentation().sendStatus(2,bundle);}
}
