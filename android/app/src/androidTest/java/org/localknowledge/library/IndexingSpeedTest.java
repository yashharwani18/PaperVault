package org.localknowledge.library;
import android.content.Context;
import android.graphics.*;
import android.graphics.pdf.PdfDocument;
import androidx.test.platform.app.InstrumentationRegistry;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import org.json.*;
import org.junit.Test;
import org.junit.runner.RunWith;
import java.io.*;
import static org.junit.Assert.*;

@RunWith(AndroidJUnit4.class)
public class IndexingSpeedTest {
    File logoPdf(Context context)throws Exception {File file=new File(context.getCacheDir(),"native-logo-speed.pdf");PdfDocument pdf=new PdfDocument();Bitmap logo=Bitmap.createBitmap(40,40,Bitmap.Config.ARGB_8888);logo.eraseColor(Color.BLUE);try{for(int i=0;i<8;i++){PdfDocument.Page p=pdf.startPage(new PdfDocument.PageInfo.Builder(595,842,i+1).create());Paint paint=new Paint();paint.setTextSize(16);p.getCanvas().drawText("Digital signal processing uses filters and convolution for discrete signals.",30,70,paint);p.getCanvas().drawBitmap(logo,30,100,paint);pdf.finishPage(p);}try(OutputStream out=new FileOutputStream(file)){pdf.writeTo(out);}}finally{pdf.close();logo.recycle();}return file;}
    @Test public void textPagesWithImagesDoNotNeedAutomaticOcr()throws Exception {
        Context context=InstrumentationRegistry.getInstrumentation().getTargetContext();File pdf=logoPdf(context);int[] ocr={0},pages={0};long start=System.nanoTime();
        new DocumentReader(context).pdf(pdf,true,(number,total,text,method,words,warnings,rotation,width,height)->{pages[0]++;if(method.equals("ocr"))ocr[0]++;assertTrue(text.contains("signal processing"));});
        JSONObject report=Json.obj("pages",pages[0],"ocr_pages",ocr[0],"elapsed_ms",(System.nanoTime()-start)/1e6);
        try(OutputStream out=new FileOutputStream(new File(context.getCacheDir(),"indexing-speed-reader.json"))){out.write(report.toString().getBytes(java.nio.charset.StandardCharsets.UTF_8));}
        assertEquals(8,pages[0]);assertEquals("Selectable text must not be OCRed just because there is a logo",0,ocr[0]);
    }
    @Test public void benchmarkWarmEmbeddings()throws Exception {
        Context context=InstrumentationRegistry.getInstrumentation().getTargetContext();NativeBackend b=((LibraryApplication)context.getApplicationContext()).backend;String model=b.models.embedding();NativeModels.release();String text="Digital signal processing uses convolution and Fourier transforms. ".repeat(12);
        long[] before=NativeModels.performance();long cold=System.nanoTime();float[] first=NativeModels.embed(model,"title: Speed | text: "+text);cold=System.nanoTime()-cold;
        long warm=System.nanoTime();for(int i=0;i<8;i++){float[] v=NativeModels.embed(model,"title: Speed | text: "+i+" "+text);assertEquals(768,v.length);}warm=System.nanoTime()-warm;
        float[] repeated=NativeModels.embed(model,"title: Speed | text: "+text);assertArrayEquals("Previous passages must not contaminate embeddings",first,repeated,0.00001f);
        double norm=0;for(float v:repeated){assertTrue(Float.isFinite(v));norm+=v*v;}assertEquals(1,norm,0.00001);
        long[] after=NativeModels.performance();assertEquals(10,after[0]-before[0]);assertEquals("One context must serve all ten passages",1,after[2]-before[2]);assertEquals(1,after[3]-before[3]);
        NativeModels.release();assertArrayEquals("Reused and fresh contexts must agree",first,NativeModels.embed(model,"title: Speed | text: "+text),0.00001f);
        JSONObject report=Json.obj("cold_ms",cold/1e6,"warm_8_ms",warm/1e6,"contexts_for_10_embeddings",after[2]-before[2],"cpu",NativeModels.cpuInfo());try(OutputStream out=new FileOutputStream(new File(context.getCacheDir(),"indexing-speed-embedding.json"))){out.write(report.toString().getBytes(java.nio.charset.StandardCharsets.UTF_8));}
    }
    @Test public void explicitOcrStillRereadsSelectableText()throws Exception {
        Context context=InstrumentationRegistry.getInstrumentation().getTargetContext();File pdf=logoPdf(context);int[] pages={0};
        new DocumentReader(context).pdf(pdf,true,true,(number,total,text,method,words,warnings,rotation,width,height)->{assertEquals("ocr",method);assertTrue(text.contains("signal processing"));pages[0]++;});assertEquals(8,pages[0]);
    }
}
