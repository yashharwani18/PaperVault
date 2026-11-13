package org.localknowledge.library;

import android.content.Context;
import android.graphics.Paint;
import android.graphics.pdf.PdfDocument;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import org.json.*;
import org.junit.Test;
import org.junit.runner.RunWith;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import static org.junit.Assert.*;

@RunWith(AndroidJUnit4.class)
public class SearchLatencyTest {
    @Test public void ordinarySearchKeepsEmbeddingModelResident()throws Exception {
        Context context=InstrumentationRegistry.getInstrumentation().getTargetContext();NativeBackend b=((LibraryApplication)context.getApplicationContext()).backend;
        boolean paused=b.paused;b.paused=true;String folder="search-latency-fixture";
        String[] queries={"How does convolution combine two signals?","How do matched cables reduce reflected waves?","Where are operational risk controls explained?"};
        String[] texts={"Convolution combines two signals to determine the output of a linear system. Filters shape the frequency response of a signal.","Impedance matching on transmission lines reduces reflections. Matched cables preserve the transmitted signal.","Operational risk controls identify hazards, assess their impact and document how teams mitigate them."};
        List<String> docs=new ArrayList<>();List<File> files=new ArrayList<>();
        try{
            b.store.exec("INSERT INTO folders VALUES(?,?,'#9b7ec4',?,?)",folder,"Synthetic search latency fixture",LibraryStore.now(),LibraryStore.now());
            String model=b.models.embedding();
            for(int i=0;i<queries.length;i++){
                String id="search-latency-"+i;docs.add(id);File source=new File(b.store.root,"sources/"+id+".pdf");files.add(source);
                PdfDocument pdf=new PdfDocument();try{var page=pdf.startPage(new PdfDocument.PageInfo.Builder(500,500,1).create());Paint paint=new Paint();paint.setTextSize(12);page.getCanvas().drawText(texts[i],20,40,paint);pdf.finishPage(page);try(FileOutputStream out=new FileOutputStream(source)){pdf.writeTo(out);}}finally{pdf.close();}
                String sha=LibraryStore.hash(source),now=LibraryStore.now();float[] vector=NativeModels.embed(model,"task: search result | query: "+queries[i]);
                b.store.exec("INSERT INTO documents(id,folder_id,filename,title,sha256,source_path,preview_path,source_uri,format,page_count,chunk_count,status,version,created_at,updated_at,size_bytes,trashed,source_mode) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",id,folder,id+".pdf",id,sha,"sources/"+source.getName(),"sources/"+source.getName(),android.net.Uri.fromFile(source).toString(),"pdf",1,1,"indexed",1,now,now,source.length(),0,"managed");
                b.store.exec("INSERT INTO pages VALUES(?,?,?,?,?,?)",id,1,texts[i],"native","[]","{}");
                b.store.exec("INSERT INTO chunks(document_id,page_number,chunk_index,text,char_start,char_end,vector,input_hash) VALUES(?,1,0,?,0,?,?,?)",id,texts[i],texts[i].length(),LibraryStore.vector(vector),b.models.embeddingSha+":latency-"+i);
            }
            NativeModels.release();long[] before=NativeModels.performance();JSONArray measured=new JSONArray();
            for(int round=0;round<2;round++)for(int i=0;i<queries.length;i++){
                long[] nativeBefore=NativeModels.performance();long start=System.nanoTime();JSONObject response=b.dispatch("/search","POST",Json.obj("query",queries[i],"folder_id",folder));double ms=(System.nanoTime()-start)/1e6;long[] nativeAfter=NativeModels.performance();
                JSONArray hits=response.getJSONArray("results");assertTrue(hits.length()>0);assertEquals("search-latency-"+i,hits.getJSONObject(0).optString("document_id"));
                measured.put(Json.obj("round",round,"query",queries[i],"elapsed_ms",ms,"embedding_ms",(nativeAfter[1]-nativeBefore[1])/1000.0,"model_loads",nativeAfter[3]-nativeBefore[3],"response_method",response.getJSONObject("response").optString("method"),"ranked_ids",new JSONArray(LibraryStore.objects(hits).stream().map(h->h.optString("document_id")).toArray())));
                if(!InstrumentationRegistry.getArguments().getString("profile_only","false").equals("true"))assertEquals(hits.getJSONObject(0).optString("source_identity"),response.getJSONObject("response").getJSONArray("citations").getJSONObject(0).optString("source_identity"));
            }
            long[] after=NativeModels.performance();JSONObject report=Json.obj("device","Android 15 x86_64 emulator; 3 GiB, 2 vCPUs","fixture","3 small generated PDFs with fixed query vectors; latency/identity control, not a search-quality benchmark","requests",measured,"model_loads",after[3]-before[3],"embedding_calls",after[0]-before[0]);
            String label=InstrumentationRegistry.getArguments().getString("profile_label","current");
            try(FileOutputStream out=new FileOutputStream(new File(context.getFilesDir(),"search-latency-"+label+".json"))){out.write(report.toString().getBytes(StandardCharsets.UTF_8));}
            android.os.Bundle status=new android.os.Bundle();status.putString("search_latency_report",report.toString());InstrumentationRegistry.getInstrumentation().sendStatus(2,status);
            if(!InstrumentationRegistry.getArguments().getString("profile_only","false").equals("true"))assertEquals("Ordinary searches must not evict the embedding model to select a citation",1,after[3]-before[3]);
        }finally{b.paused=paused;for(String id:docs)b.store.exec("DELETE FROM documents WHERE id=?",id);b.store.exec("DELETE FROM folders WHERE id=?",folder);for(File file:files)file.delete();}
    }
}
