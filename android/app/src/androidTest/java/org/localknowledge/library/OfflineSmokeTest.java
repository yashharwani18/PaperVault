package org.localknowledge.library;

import android.content.Context;
import androidx.test.platform.app.InstrumentationRegistry;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import org.junit.*;
import org.junit.runner.RunWith;
import org.json.*;
import java.util.concurrent.TimeUnit;
import java.io.*;
import android.net.Uri;
import static org.junit.Assert.*;

@RunWith(AndroidJUnit4.class)
public class OfflineSmokeTest {
    @Test public void bundledModelsRunWithoutInternetPermission()throws Exception {
        Context context=InstrumentationRegistry.getInstrumentation().getTargetContext();
        assertEquals(android.content.pm.PackageManager.PERMISSION_DENIED,context.checkSelfPermission("android.permission.INTERNET"));
        LibraryApplication app=(LibraryApplication)context.getApplicationContext();app.backend.models.ready.get(5,TimeUnit.MINUTES);
        float[] first=NativeModels.embed(app.backend.models.embedding(),"title: Automata | text: A deterministic finite automaton recognizes regular languages.");
        assertEquals(768,first.length);double norm=0;for(float value:first){assertFalse(Float.isNaN(value));assertFalse(Float.isInfinite(value));norm+=value*value;}assertEquals(1,norm,.001);
        float[] unrelated=NativeModels.embed(app.backend.models.embedding(),"title: Invoice | text: Sold ten shirts for INR 29000 to Sample Trading."),query=NativeModels.embed(app.backend.models.embedding(),"task: search result | query: Which machines recognize regular languages?");double relevant=0,other=0;for(int i=0;i<first.length;i++){relevant+=query[i]*first[i];other+=query[i]*unrelated[i];}assertTrue("Embedding topic ordering failed",relevant>other);
        String output=NativeModels.generate(app.backend.models.qwen(),ModelAssets.prompt("Return the supplied JSON choice only.","{\"choice\":1}"),"root ::= \"{\\\"choice\\\":1}\"",16);
        assertEquals(1,new JSONObject(output).getInt("choice"));
        JSONObject amount=app.backend.interpretAmount("hello mere bhai kaisa hai, muje wo wala invoice dikha na jaha pe 13800 ka invoice ban raha tha");assertEquals("13800.00",amount.getString("value"));
        assertEquals("ready",app.backend.state().getJSONObject("semantic_status").getString("state"));
    }
    File fixture(String name)throws Exception {Context tests=InstrumentationRegistry.getInstrumentation().getContext(),target=InstrumentationRegistry.getInstrumentation().getTargetContext();File file=new File(target.getCacheDir(),name);try(InputStream in=tests.getAssets().open(name);OutputStream out=new FileOutputStream(file)){NativeTransfer.copy(in,out);}return file;}
    @Test public void localPdfPptxAndBundledOcrWork()throws Exception {
        Context target=InstrumentationRegistry.getInstrumentation().getTargetContext();DocumentReader reader=new DocumentReader(target);final int[] pages={0};
        reader.pdf(fixture("synthetic-native-bill.pdf"),false,(number,total,text,method,words,warnings,rotation,width,height)->{assertTrue(text.contains("Bhagwanti"));assertTrue(words.length()>0);pages[0]++;});assertEquals(1,pages[0]);
        assertFalse(reader.slideTexts(fixture("synthetic-college.pptx")).isEmpty());
        reader.pdf(fixture("synthetic-scan-columns.pdf"),true,(number,total,text,method,words,warnings,rotation,width,height)->{
            try(OutputStream out=new FileOutputStream(new File(target.getCacheDir(),"ocr-observation.json"))){out.write(Json.obj("text",text,"words",words).toString().getBytes(java.nio.charset.StandardCharsets.UTF_8));}
            assertEquals("ocr",method);JSONArray amounts=Money.amounts(text,Json.obj("words",words,"rotation",rotation));assertEquals(amounts.toString(),1,amounts.length());assertEquals("29074.00",amounts.getJSONObject(0).getString("value"));assertEquals("current_column",amounts.getJSONObject(0).getString("association"));
        });
    }
    @Test public void nativeImportSearchReviewAndBackupWork()throws Exception {
        Context target=InstrumentationRegistry.getInstrumentation().getTargetContext();NativeBackend backend=((LibraryApplication)target.getApplicationContext()).backend;
        String folder=backend.dispatch("/folders","POST",Json.obj("name","Synthetic Android test "+System.nanoTime())).getString("id");
        File scan=fixture("synthetic-scan-columns.pdf"),exact=new File(target.getCacheDir(),"synthetic-exact.pdf");
        android.graphics.pdf.PdfDocument pdf=new android.graphics.pdf.PdfDocument();try{android.graphics.pdf.PdfDocument.Page page=pdf.startPage(new android.graphics.pdf.PdfDocument.PageInfo.Builder(595,842,1).create());android.graphics.Paint paint=new android.graphics.Paint();paint.setTextSize(16);page.getCanvas().drawText("SYNTHETIC INVOICE - TEST ONLY",30,40,paint);page.getCanvas().drawText("Grand Total: INR 29000.00",30,100,paint);pdf.finishPage(page);try(OutputStream out=new FileOutputStream(exact)){pdf.writeTo(out);}}finally{pdf.close();}
        File deck=fixture("synthetic-college.pptx");String[] jobs={backend.enqueue(Uri.fromFile(scan).toString(),scan.getName(),folder,"",true,true),backend.enqueue(Uri.fromFile(exact).toString(),exact.getName(),folder,"",false,true),backend.enqueue(Uri.fromFile(deck).toString(),deck.getName(),folder,"",false,false)};
        long deadline=System.currentTimeMillis()+240000;while(!backend.idle()&&System.currentTimeMillis()<deadline)Thread.sleep(300);assertTrue("Import timeout",backend.idle());for(String job:jobs){JSONObject task=backend.store.one("SELECT * FROM tasks WHERE id=?",job);assertEquals(task.toString(),"completed",task.getString("status"));}
        JSONObject mixed=backend.dispatch("/search","POST",Json.obj("query","total about 29000","folder_id",folder));assertEquals(mixed.toString(),2,mixed.getJSONArray("results").length());assertEquals("mixed_source_amounts",mixed.getString("reliability"));
        JSONObject only=backend.dispatch("/search","POST",Json.obj("query","total exactly 29000","folder_id",folder));assertEquals(1,only.getJSONArray("results").length());String id=only.getJSONArray("results").getJSONObject(0).getString("document_id");
        backend.saveBill(id,Json.obj("party","Synthetic Trading","bill_date","2026-09-25","amount","29000","currency","INR","reviewed",true,"amount_reviewed",true));
        JSONObject reviewed=backend.dispatch("/search","POST",Json.obj("query","total 29000","folder_id",folder));assertEquals(1,reviewed.getJSONArray("results").length());assertTrue(reviewed.getJSONArray("results").getJSONObject(0).getJSONObject("amount_match").getBoolean("verified"));
        JSONObject semantic=backend.dispatch("/search","POST",Json.obj("query","How can I prove a language is not regular?","folder_id",folder));assertEquals(semantic.toString(),"synthetic-college.pptx",semantic.getJSONArray("results").getJSONObject(0).getString("filename"));
        File backup=new File(target.getCacheDir(),"android-test-backup.zip");NativeTransfer transfer=new NativeTransfer(backend);try(OutputStream out=new FileOutputStream(backup)){transfer.backup(out,"");}int before=backend.store.documents().length();try(InputStream in=new FileInputStream(backup)){transfer.restore(in,"");}assertEquals(before*2,backend.store.documents().length());assertTrue(backend.verify().getBoolean("passed"));
        File encrypted=new File(target.getCacheDir(),"android-test-encrypted.llandroid");try(OutputStream out=new FileOutputStream(encrypted)){transfer.backup(out,"synthetic-test-password");}
        int existing=backend.store.documents().length();
        try(InputStream in=new FileInputStream(encrypted)){transfer.restore(in,"wrong-password");fail("Wrong password accepted");}catch(java.io.IOException expected){}assertEquals(existing,backend.store.documents().length());
        byte[] damaged;try(InputStream in=new FileInputStream(encrypted)){damaged=ModelAssets.read(in);}damaged[damaged.length-1]^=1;
        try(InputStream in=new ByteArrayInputStream(damaged)){transfer.restore(in,"synthetic-test-password");fail("Tampered authentication tag accepted");}catch(java.io.IOException expected){}assertEquals(existing,backend.store.documents().length());
        try(InputStream in=new FileInputStream(encrypted)){transfer.restore(in,"synthetic-test-password");}assertEquals(existing*2,backend.store.documents().length());assertTrue(backend.verify().getBoolean("passed"));
    }
}
