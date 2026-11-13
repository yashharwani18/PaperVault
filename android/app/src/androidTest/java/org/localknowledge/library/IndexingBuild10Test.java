package org.localknowledge.library;
import android.content.*;
import android.graphics.*;
import android.graphics.pdf.PdfDocument;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import com.tom_roush.pdfbox.pdmodel.PDDocument;
import com.tom_roush.pdfbox.io.MemoryUsageSetting;
import org.json.*;
import org.junit.*;
import org.junit.runner.RunWith;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import static org.junit.Assert.*;
@RunWith(AndroidJUnit4.class)
public class IndexingBuild10Test {
 Context context(){return InstrumentationRegistry.getInstrumentation().getTargetContext();}
 void report(String name,JSONObject result)throws Exception{try(FileOutputStream out=new FileOutputStream(new File(context().getCacheDir(),name))){out.write(result.toString().getBytes(StandardCharsets.UTF_8));}}
 List<String> read(File file,boolean legacy)throws Exception{
  DocumentReader reader=new DocumentReader(context());List<String> result=new ArrayList<>();
  if(legacy){try(PDDocument doc=PDDocument.load(file,MemoryUsageSetting.setupTempFileOnly().setTempDir(context().getCacheDir()))){for(int i=0;i<doc.getNumberOfPages();i++){DocumentReader.Stripper s=new DocumentReader.Stripper();s.setStartPage(i+1);s.setEndPage(i+1);String text=s.getText(doc);result.add(Json.obj("page",i+1,"text",text,"words",s.words).toString());}}}
  else reader.pdf(file,false,(n,total,text,method,words,warnings,rotation,w,h)->result.add(Json.obj("page",n,"text",text,"words",words).toString()));
  return result;
 }
 @Test public void extractionMatchesLegacyIncludingBlankPagesAndIsTimed()throws Exception{
  File file=new File(context().getCacheDir(),"build10-extraction.pdf");PdfDocument pdf=new PdfDocument();
  try{for(int i=0;i<160;i++){PdfDocument.Page p=pdf.startPage(new PdfDocument.PageInfo.Builder(595,842,i+1).create());if(i!=0&&i!=7&&i!=159){Paint paint=new Paint();paint.setTextSize(12);p.getCanvas().drawText("Page "+i+" digital filters and Fourier transforms",30,60,paint);p.getCanvas().drawText("A second source line with invoice total 230.50",30,90,paint);}pdf.finishPage(p);}try(FileOutputStream out=new FileOutputStream(file)){pdf.writeTo(out);}}finally{pdf.close();}
  try{List<String> old=read(file,true),now=read(file,false);assertEquals(160,now.size());assertEquals("Text, word boxes and blank page numbers changed",old,now);
   double[] before=new double[3],after=new double[3];for(int round=0;round<3;round++)for(int j=0;j<2;j++){boolean legacy=(round+j)%2==0;long start=System.nanoTime();assertEquals(old,read(file,legacy));double ms=(System.nanoTime()-start)/1e6;if(legacy)before[round]=ms;else after[round]=ms;}
   double[] b=before.clone(),a=after.clone();Arrays.sort(b);Arrays.sort(a);report("build10-extraction.json",Json.obj("pages",160,"text_and_word_boxes_identical",true,"before_ms",new JSONArray(before),"after_ms",new JSONArray(after),"before_median_ms",b[1],"after_median_ms",a[1],"speedup",b[1]/a[1]));
  }finally{file.delete();}
 }
 @Test public void tokenCachePreservesVectorAndTimesTokenizerReuse()throws Exception{
  NativeBackend b=((LibraryApplication)context().getApplicationContext()).backend;String model=b.models.embedding(),text="title: Notes | text: "+"Digital signal processing uses Fourier transforms and convolution. ".repeat(10);
  NativeModels.release();int tokens=NativeModels.tokenCount(model,text);float[] cached=NativeModels.embed(model,text);NativeModels.release();float[] fresh=NativeModels.embed(model,text);assertArrayEquals(fresh,cached,0.00001f);assertEquals(768,cached.length);
  double[] hit=new double[3],miss=new double[3];for(int r=0;r<3;r++)for(int j=0;j<2;j++){boolean cachedInput=(r+j)%2==0;long start=System.nanoTime();for(int i=0;i<400;i++){int n=NativeModels.tokenCount(model,cachedInput?text:text+" item "+r+" "+i);assertTrue(n>0);}double ms=(System.nanoTime()-start)/1e6;if(cachedInput)hit[r]=ms;else miss[r]=ms;}
  report("build10-token-cache.json",Json.obj("cached_ms",new JSONArray(hit),"uncached_ms",new JSONArray(miss),"calls_per_round",400,"vector_matches_fresh",true,"tokens",tokens,"scope","Tokenizer microbenchmark; uncached inputs have a short unique suffix, not end-to-end indexing"));
 }
 String power()throws Exception{try(var fd=InstrumentationRegistry.getInstrumentation().getUiAutomation().executeShellCommand("dumpsys power");var in=new FileInputStream(fd.getFileDescriptor())){return new String(in.readAllBytes(),StandardCharsets.UTF_8);}}
 boolean held()throws Exception{return power().lines().anyMatch(l->l.contains("PARTIAL_WAKE_LOCK")&&l.contains("Khoj:Indexing"));}
 void waitHeld(boolean value)throws Exception{long until=System.currentTimeMillis()+7000;while(System.currentTimeMillis()<until){if(held()==value)return;Thread.sleep(200);}assertEquals("Unexpected indexing wake lock state",value,held());}
 @Test public void wakeLockTracksWorkPauseAndServiceStop()throws Exception{
  Context c=context();NativeBackend b=((LibraryApplication)c.getApplicationContext()).backend;boolean paused=b.paused;String task=LibraryStore.id();Intent service=new Intent(c,ImportService.class);
  try{b.paused=false;b.store.exec("INSERT INTO tasks(id,filename,status,created_at) VALUES(?,?,'running',?)",task,"build10-wake-fixture",LibraryStore.now());c.startForegroundService(service);waitHeld(true);b.paused=true;waitHeld(false);b.paused=false;c.startForegroundService(service);waitHeld(true);b.store.exec("DELETE FROM tasks WHERE id=?",task);c.stopService(service);waitHeld(false);report("build10-wake.json",Json.obj("held_during_work",true,"released_when_paused",true,"released_on_stop",true));}
  finally{b.paused=paused;b.store.exec("DELETE FROM tasks WHERE id=?",task);c.stopService(service);}
 }
}
