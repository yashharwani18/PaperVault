package org.localknowledge.library;

import android.content.Context;
import android.graphics.Paint;
import android.graphics.pdf.PdfDocument;
import android.os.Debug;
import android.os.Environment;
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
public class FirstIndexBenchmarkTest {
    long sourceBytes(File root){long n=0;for(File f:Objects.requireNonNull(root.listFiles()))n+=f.length();return n;}
    @Test public void measureCompleteReferenceIndexing()throws Exception {
        Context context=InstrumentationRegistry.getInstrumentation().getTargetContext();NativeBackend b=((LibraryApplication)context.getApplicationContext()).backend;
        assertTrue(b.phoneScan.hasAccess());assertTrue(b.idle());
        int count=Integer.parseInt(InstrumentationRegistry.getArguments().getString("count","24")),chars=Integer.parseInt(InstrumentationRegistry.getArguments().getString("chars","2800")),pages=Integer.parseInt(InstrumentationRegistry.getArguments().getString("pages","1"));
        File root=new File(Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOCUMENTS),"Khoj-perf-"+System.nanoTime());assertTrue(root.mkdirs());
        String text="Digital signal processing uses convolution filters and Fourier transforms. ".repeat(Math.max(1,chars/73));
        for(int i=0;i<count;i++){PdfDocument pdf=new PdfDocument();try{for(int page=0;page<pages;page++){PdfDocument.Page p=pdf.startPage(new PdfDocument.PageInfo.Builder(595,842,page+1).create());Paint paint=new Paint();paint.setTextSize(10);p.getCanvas().drawText("Unique fixture "+root.getName()+" document "+i+" page "+page,20,15,paint);for(int j=0;j<text.length();j+=85)p.getCanvas().drawText(text.substring(j,Math.min(text.length(),j+85)),20,30+j/85*18,paint);pdf.finishPage(p);}try(OutputStream out=new FileOutputStream(new File(root,"Signal-"+root.getName()+"-"+i+".pdf"))){pdf.writeTo(out);}}finally{pdf.close();}}
        NativeModels.embed(b.models.embedding(),"task: search result | query: digital signal processing");long[] before=NativeModels.performance();long sourceBefore=sourceBytes(new File(b.store.root,"sources"));long dbBefore=context.getDatabasePath("library.sqlite3").length();
        long started=System.nanoTime(),deadline=System.currentTimeMillis()+1200000,peakPss=Debug.getPss();JSONArray searchTimes=new JSONArray();boolean searched=false;
        b.phoneScan.scanRoots(Collections.singletonList(root));
        while((b.phoneScan.finding||b.phoneScan.pending())&&System.currentTimeMillis()<deadline){
            if(!searched&&!b.phoneScan.finding&&b.store.one("SELECT count(*) n FROM phone_scan_files WHERE path LIKE ? AND state='indexed'",root.getCanonicalPath()+"/%").optInt("n")>=Math.min(4,count)){
                long t=System.nanoTime();JSONObject hits=b.dispatch("/search","POST",Json.obj("query","digital filters","folder_id",b.phoneScan.folder()));assertTrue(hits.getJSONArray("results").length()>0);searchTimes.put((System.nanoTime()-t)/1e6);searched=true;
            }
            peakPss=Math.max(peakPss,Debug.getPss());Thread.sleep(250);
        }
        assertFalse("Indexing timed out",b.phoneScan.pending());assertFalse(b.phoneScan.finding);
        int indexed=b.store.one("SELECT count(*) n FROM phone_scan_files WHERE path LIKE ? AND state='indexed'",root.getCanonicalPath()+"/%").optInt("n");assertEquals(count,indexed);assertEquals("Scanned originals must not be copied",sourceBefore,sourceBytes(new File(b.store.root,"sources")));
        long[] after=NativeModels.performance();JSONObject report=Json.obj("device","Android 15 x86_64 task emulator","pdfs",count,"pages_per_pdf",pages,"approx_chars_per_pdf",text.length()*pages,"elapsed_ms",(System.nanoTime()-started)/1e6,"completed_passages",after[0]-before[0],"native_embedding_ms",(after[1]-before[1])/1000.0,"model_loads",after[3]-before[3],"peak_process_pss_kib",peakPss,"database_growth_bytes",context.getDatabasePath("library.sqlite3").length()-dbBefore,"source_copy_growth_bytes",0,"search_during_index_ms",searchTimes);
        try(OutputStream out=new FileOutputStream(new File(context.getCacheDir(),"first-index-benchmark.json"))){out.write(report.toString().getBytes(StandardCharsets.UTF_8));}
    }
}
