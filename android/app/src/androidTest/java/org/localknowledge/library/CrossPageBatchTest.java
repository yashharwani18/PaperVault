package org.localknowledge.library;
import android.content.*;
import android.graphics.*;
import android.graphics.pdf.PdfDocument;
import android.net.Uri;
import android.database.sqlite.SQLiteDatabase;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import org.json.*;
import org.junit.Test;
import org.junit.runner.RunWith;
import java.io.*;
import java.util.*;
import java.nio.charset.StandardCharsets;
import static org.junit.Assert.*;
@RunWith(AndroidJUnit4.class)
public class CrossPageBatchTest {
 NativeBackend backend(){return ((LibraryApplication)InstrumentationRegistry.getInstrumentation().getTargetContext().getApplicationContext()).backend;}
 File fixture(int pages)throws Exception{File file=new File(backend().context.getCacheDir(),"batch-proof-"+System.nanoTime()+".pdf");PdfDocument pdf=new PdfDocument();try{for(int i=1;i<=pages;i++){PdfDocument.Page p=pdf.startPage(new PdfDocument.PageInfo.Builder(595,842,i).create());Paint paint=new Paint();paint.setTextSize(12);p.getCanvas().drawText("Unique source page "+i,30,30,paint);for(int line=0;line<13;line++)p.getCanvas().drawText("Digital signal processing uses filters and Fourier transforms.",30,60+line*22,paint);pdf.finishPage(p);}try(FileOutputStream out=new FileOutputStream(file)){pdf.writeTo(out);}}finally{pdf.close();}return file;}
 @Test public void benchmarkSamePdfScalarVersusCrossPageBatches()throws Exception{
  NativeBackend b=backend();File file=fixture(8);String path=b.models.embedding(),sha="batch-proof-"+LibraryStore.id();JSONArray rows=new JSONArray();
  NativeModels.embedBatch(path,new String[]{"title: Warm | text: "+"digital filters ".repeat(80),"title: Warm | text: "+"SQL transactions ".repeat(80)});
  try{for(int round=0;round<3;round++)for(int j=0;j<2;j++){boolean packed=(round+j)%2==1;b.store.exec("DELETE FROM vector_cache WHERE input_hash LIKE ?",sha+":%");
   File stageFile=new File(b.context.getCacheDir(),"batch-stage-"+LibraryStore.id()+".sqlite3");long[] before=NativeModels.performance();long start=System.nanoTime();
   try(SQLiteDatabase stage=SQLiteDatabase.openOrCreateDatabase(stageFile,null)){stage.execSQL("CREATE TABLE pages(page_number INTEGER,text TEXT,method TEXT,warnings TEXT,evidence TEXT)");stage.execSQL("CREATE TABLE chunks(page_number INTEGER,chunk_index INTEGER,text TEXT,char_start INTEGER,char_end INTEGER,vector BLOB,input_hash TEXT)");
    PageIndexer.Engine engine=new PageIndexer.Engine(){public int tokens(String t){return NativeModels.tokenCount(path,t);}public float[] scalar(String t){return NativeModels.embed(path,t);}public float[][] batch(String[] t){if(packed)return NativeModels.embedBatch(path,t);float[][] out=new float[t.length][];for(int k=0;k<t.length;k++)out[k]=NativeModels.embed(path,t[k]);return out;}};
    PageIndexer p=new PageIndexer(b.store,stage,sha,"Proof",engine,()->{},4,packed);new DocumentReader(b.context).pdf(file,false,(n,total,text,method,words,warnings,rot,w,h)->p.indexPage(n,text,method,warnings.toString(),"{}",x->{}));p.finish(x->{});assertEquals(8,p.chunkCount);
    long[] after=NativeModels.performance();rows.put(Json.obj("round",round,"batched",packed,"elapsed_ms",(System.nanoTime()-start)/1e6,"passages",p.chunkCount,"native_batches",after[4]-before[4],"embedded_tokens",after[5]-before[5]));
   }finally{stageFile.delete();new File(stageFile+"-journal").delete();}
  }
  JSONObject report=Json.obj("scope","PDF extraction, embedding, vector-cache writes and staging; excludes scan and final document publication","pages",8,"runs",rows,"device","Android 15 x86_64 emulator, two vCPUs","cpu",NativeModels.cpuInfo());try(FileOutputStream out=new FileOutputStream(new File(b.context.getCacheDir(),"cross-page-benchmark.json"))){out.write(report.toString().getBytes(StandardCharsets.UTF_8));}
  }finally{file.delete();b.store.exec("DELETE FROM vector_cache WHERE input_hash LIKE ?",sha+":%");}
 }
 @Test public void productionImportPublishesFinalPartialBatchAndCorrectCounts()throws Exception{
  NativeBackend b=backend();File file=fixture(5);String folder=LibraryStore.id(),task="",document="",source="";boolean paused=b.paused;
  b.store.exec("INSERT INTO folders VALUES(?,?,?,?,?)",folder,"Batch proof "+folder,"#A78BFA",LibraryStore.now(),LibraryStore.now());
  try{b.paused=false;task=b.enqueue(Uri.fromFile(file).toString(),file.getName(),folder,"",false,false);b.indexing.submit(()->{}).get(45,java.util.concurrent.TimeUnit.SECONDS);JSONObject job=b.store.one("SELECT * FROM tasks WHERE id=?",task);assertEquals(job.optString("error"),"completed",job.optString("status"));JSONObject doc=Json.parse(job.optString("result")).getJSONObject("document");document=doc.getString("id");source=doc.optString("source_path");assertEquals(5,doc.getInt("page_count"));assertEquals(5,doc.getInt("chunk_count"));assertEquals("indexed",doc.getString("status"));assertEquals(5,b.store.one("SELECT count(*) n FROM chunks WHERE document_id=?",document).getInt("n"));}
  finally{b.paused=paused;if(!document.isEmpty()){b.store.exec("DELETE FROM documents WHERE id=?",document);if(!source.isEmpty())new File(b.store.root,source).delete();}if(!task.isEmpty())b.store.exec("DELETE FROM tasks WHERE id=?",task);b.store.exec("DELETE FROM folders WHERE id=?",folder);file.delete();}
 }
}
