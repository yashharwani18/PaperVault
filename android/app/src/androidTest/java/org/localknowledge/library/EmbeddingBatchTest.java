package org.localknowledge.library;

import android.content.Context;
import android.os.Debug;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import org.json.*;
import org.junit.Test;
import org.junit.runner.RunWith;
import java.io.*;
import java.lang.reflect.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import static org.junit.Assert.*;

@RunWith(AndroidJUnit4.class)
public class EmbeddingBatchTest {
    Context context(){return InstrumentationRegistry.getInstrumentation().getTargetContext();}
    String model()throws Exception{return ((LibraryApplication)context().getApplicationContext()).backend.models.embedding();}
    float[][] batch(String model,String... inputs)throws Exception {
        try{return (float[][])NativeModels.class.getDeclaredMethod("embedBatch",String.class,String[].class).invoke(null,model,inputs);}
        catch(InvocationTargetException e){if(e.getCause() instanceof Exception)throw (Exception)e.getCause();throw e;}
    }
    void save(String name,JSONObject report)throws Exception {try(OutputStream out=new FileOutputStream(new File(context().getCacheDir(),name))){out.write(report.toString().getBytes(StandardCharsets.UTF_8));}}
    void equivalent(float[] a,float[] b){assertEquals(768,b.length);double dot=0,na=0,nb=0,max=0;for(int i=0;i<a.length;i++){assertTrue(Float.isFinite(b[i]));dot+=a[i]*b[i];na+=a[i]*a[i];nb+=b[i]*b[i];max=Math.max(max,Math.abs(a[i]-b[i]));}assertEquals(1,nb,0.00001);assertTrue("cosine="+dot/Math.sqrt(na*nb),dot/Math.sqrt(na*nb)>=0.99999);assertTrue("max error="+max,max<=0.0001);}
    String[] samples(){return new String[]{"title: DSP | text: "+"Digital signal processing uses filters and Fourier transforms. ".repeat(12),"title: Bank | text: Invoice total INR 29000. Current amount only.","title: Notes | text: Automata recognize regular languages. ".repeat(8),"title: हिन्दी | text: "+"यह डिजिटल संकेत और गणित के अध्ययन के लिए है। ".repeat(3),"title: DSP | text: "+"Digital signal processing uses filters and Fourier transforms. ".repeat(12),"title: Data | text: "+"Relational databases use SQL joins and transactions. ".repeat(14),"title: Small | text: Hello world.","title: Unicode | text: café naïve signals 😀 "+"convolution ".repeat(60)};}
    double cosine(float[] a,float[] b){double d=0,aa=0,bb=0;for(int i=0;i<a.length;i++){d+=a[i]*b[i];aa+=a[i]*a[i];bb+=b[i]*b[i];}return d/Math.sqrt(aa*bb);}
    @Test public void batchUsesOneNativeExecution()throws Exception {
        String path=model();String[] all=samples();String[] input={all[0],all[2],all[4],all[5]};NativeModels.embed(path,input[0]);
        batch(path,input);long[] before=NativeModels.performance();batch(path,input);long[] after=NativeModels.performance();
        assertEquals("Four passages must use one native inference batch",1,after[4]-before[4]);
        assertEquals(4,after[0]-before[0]);
    }
    @Test public void diagnoseBatchNumerics()throws Exception {
        String model=model();String[] input=samples();NativeModels.release();float[] before=NativeModels.embed(model,input[0]);float[][] mixed=batch(model,input[0],input[1]);float[] after=NativeModels.embed(model,input[0]);float[][] duplicate=batch(model,input[0],input[0]);
        save("batch-numerics.json",Json.obj("mixed_vs_reference",cosine(before,mixed[0]),"scalar_after_capacity_growth",cosine(before,after),"duplicate_vs_reference",cosine(before,duplicate[0]),"mixed_vs_duplicate",cosine(mixed[0],duplicate[0])));
        equivalent(before,mixed[0]);
    }
    @Test public void nearLimitMixedLengthsPreserveRankingAndOrder()throws Exception {
        String path=model();String longText="title: Source | text: ";
        while(NativeModels.tokenCount(path,longText+"Digital signal processing and Fourier transforms. ")<480)longText+="Digital signal processing and Fourier transforms. ";
        String[] input={longText,samples()[1],samples()[2],samples()[5]};
        float[][] scalar=new float[4][];for(int i=0;i<4;i++)scalar[i]=NativeModels.embed(path,input[i]);
        for(int shift=0;shift<4;shift++){String[] rotated=new String[4];for(int j=0;j<4;j++)rotated[j]=input[(j+shift)%4];float[][] actual=batch(path,rotated);for(int j=0;j<4;j++)equivalent(scalar[(j+shift)%4],actual[j]);}
        float[][] packed=batch(path,input);
        for(String query:new String[]{"task: search result | query: Fourier transforms","task: search result | query: invoice total","task: search result | query: SQL database joins"}){
            float[] q=NativeModels.embed(path,query);List<Integer> a=new ArrayList<>(Arrays.asList(0,1,2,3)),b=new ArrayList<>(a);
            a.sort(Comparator.comparingDouble((Integer i)->cosine(q,scalar[i])).reversed());b.sort(Comparator.comparingDouble((Integer i)->cosine(q,packed[i])).reversed());assertEquals("Batch changed source ranking",a,b);
        }
        assertTrue("Oversized page token counting must return a count, not fail",NativeModels.tokenCount(path,"漢 ".repeat(10000))>8192);
        save("batch-ranking.json",Json.obj("queries",3,"rankings_identical",true,"rotations",4,"long_passage_tokens",NativeModels.tokenCount(path,longText)));
    }
    @Test public void benchmarkScalarAndBatches()throws Exception {
        String model=model();String[] inputs=samples();NativeModels.release();NativeModels.embed(model,inputs[0]);
        JSONArray scalar=new JSONArray();for(int round=0;round<3;round++){long t=System.nanoTime();for(String s:inputs)NativeModels.embed(model,s);scalar.put((System.nanoTime()-t)/1e6);}
        JSONObject report=Json.obj("device","Android emulator x86_64","cpu",NativeModels.cpuInfo(),"inputs",inputs.length,"scalar_ms",scalar,"pss_scalar_kib",Debug.getPss());save("batch-baseline.json",report);
        JSONObject timings=new JSONObject();for(int size:new int[]{1,2,4}){batch(model,Arrays.copyOfRange(inputs,0,size));JSONArray values=new JSONArray();for(int round=0;round<3;round++){long t=System.nanoTime();for(int i=0;i<inputs.length;i+=size)batch(model,Arrays.copyOfRange(inputs,i,Math.min(inputs.length,i+size)));values.put((System.nanoTime()-t)/1e6);}timings.put(String.valueOf(size),values);report.put("pss_batch_"+size+"_kib",Debug.getPss());}
        report.put("batch_ms",timings);save("batch-benchmark.json",report);
    }
    @Test public void independentSequencesMatchScalarAndRecoverAfterInvalidInput()throws Exception {
        String model=model();String[] input=samples();float[][] expected=new float[input.length][];for(int i=0;i<input.length;i++)expected[i]=NativeModels.embed(model,input[i]);
        JSONArray comparisons=new JSONArray();boolean compatible=true;
        for(int size:new int[]{1,2,4})for(int i=0;i<input.length;i+=size){float[][] actual=batch(model,Arrays.copyOfRange(input,i,i+size));assertEquals(size,actual.length);for(int j=0;j<size;j++){double max=0;for(int k=0;k<768;k++)max=Math.max(max,Math.abs(expected[i+j][k]-actual[j][k]));comparisons.put(Json.obj("size",size,"input",i+j,"cosine",cosine(expected[i+j],actual[j]),"max_error",max));try{equivalent(expected[i+j],actual[j]);}catch(AssertionError error){compatible=false;}}}
        save("batch-compatibility.json",Json.obj("compatible",compatible,"comparisons",comparisons));assertTrue("See batch-compatibility.json for per-input differences",compatible);
        float[][] shuffled=batch(model,input[3],input[0],input[3],input[7]);equivalent(expected[3],shuffled[0]);equivalent(expected[0],shuffled[1]);equivalent(expected[3],shuffled[2]);equivalent(expected[7],shuffled[3]);
        for(String[] bad:new String[][]{new String[0],new String[]{"a","b","c","d","e"},new String[]{"word ".repeat(600)}}){try{batch(model,bad);fail("Invalid batch accepted");}catch(RuntimeException expectedError){}}
        equivalent(expected[0],NativeModels.embed(model,input[0]));NativeModels.release();equivalent(expected[0],batch(model,input[0])[0]);
    }
}
