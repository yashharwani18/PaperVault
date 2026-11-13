package org.localknowledge.library;

import android.content.Context;
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
public class BillSearchQualityTest {
    @Test public void realPdfInvoiceAndAmountQueriesRetainTheirSourcePages() throws Exception {
        Context tests=InstrumentationRegistry.getInstrumentation().getContext(),context=InstrumentationRegistry.getInstrumentation().getTargetContext();
        NativeBackend b=((LibraryApplication)context.getApplicationContext()).backend;
        JSONObject corpus;try(InputStream in=tests.getAssets().open("bill-quality/corpus.json")){corpus=new JSONObject(new String(ModelAssets.read(in),StandardCharsets.UTF_8));}
        String folder=LibraryStore.id(),now=LibraryStore.now();List<File> temporary=new ArrayList<>();JSONArray results=new JSONArray();int passed=0;
        b.store.exec("INSERT INTO folders VALUES(?,?,'blue',?,?)",folder,"Real bill search audit "+folder,now,now);
        try {
            for(JSONObject fixture:LibraryStore.objects(corpus.getJSONArray("documents"))) {
                String id=LibraryStore.id();File source=new File(b.store.root,"sources/quality-"+id+".pdf");temporary.add(source);
                try(InputStream in=tests.getAssets().open("bill-quality/"+fixture.getString("asset"));OutputStream out=new FileOutputStream(source)){NativeTransfer.copy(in,out);}
                assertEquals(fixture.getString("sha256"),LibraryStore.hash(source));
                b.store.exec("INSERT INTO documents(id,folder_id,filename,title,sha256,source_path,preview_path,source_uri,format,page_count,chunk_count,status,version,created_at,updated_at,size_bytes,source_mode) VALUES(?,?,?,?,?,?,?,?, 'pdf',0,0,'indexed',1,?,?,?,'managed')",id,folder,fixture.getString("filename"),fixture.getString("filename"),fixture.getString("sha256"),"sources/"+source.getName(),"sources/"+source.getName(),android.net.Uri.fromFile(source).toString(),now,now,source.length());
                final int[] pages={0};new DocumentReader(context).pdf(source,false,(number,count,text,method,words,warnings,rotation,width,height)->{
                    pages[0]++;String evidence=Json.obj("words",words,"rotation",rotation,"bounds",Json.arr(0,0,width,height)).toString();
                    b.store.exec("INSERT INTO pages VALUES(?,?,?,?,?,?)",id,number,text,method,warnings.toString(),evidence);
                    // Structured lookup does not need inference. One whole-page passage preserves source offsets.
                    b.store.exec("INSERT INTO chunks(document_id,page_number,chunk_index,text,char_start,char_end) VALUES(?,?,0,?,0,?)",id,number,text,text.length());
                });
                b.store.exec("UPDATE documents SET page_count=?,chunk_count=? WHERE id=?",pages[0],pages[0],id);
            }
            for(JSONObject test:LibraryStore.objects(corpus.getJSONArray("cases"))) {
                String query=test.getString("query");long start=System.nanoTime();JSONObject row=Json.obj("query",query,"language",test.getString("language"),"expected",test.getJSONArray("expected"));
                try {
                    JSONObject response=b.search(Json.obj("query",query,"folder_id",folder,"content_only",true,"matching",Json.obj("mode",test.getString("matching"))));
                    assertEquals("Deterministic queries must not depend on a model: "+query,"not_needed",response.getString("query_interpreter"));
                    JSONArray hits=response.getJSONArray("results");Set<String> actual=new TreeSet<>(),expected=new TreeSet<>();
                    for(JSONObject hit:LibraryStore.objects(hits)) {
                        actual.add(hit.getString("filename")+":"+hit.getInt("page_number"));
                        assertTrue(query,hit.getString("source_identity").length()>0);
                        if(!test.getString("field").equals("invoice_number")){JSONObject amount=hit.getJSONObject("amount_match");assertEquals(query,test.getString("field"),amount.getString("field"));assertEquals(query,test.getString("value"),amount.getString("value"));assertFalse(query,amount.getBoolean("approximate"));}
                    }
                    for(JSONObject target:LibraryStore.objects(test.getJSONArray("expected")))expected.add(target.getString("filename")+":"+target.getInt("page_number"));
                    row.put("actual",new JSONArray(actual));assertEquals(query,expected,actual);row.put("passed",true);passed++;
                } catch(Throwable failure){row.put("passed",false);row.put("error",failure.toString());}
                row.put("elapsed_ms",(System.nanoTime()-start)/1e6);results.put(row);
            }
            JSONObject report=Json.obj("real_documents",corpus.getJSONArray("documents").length(),"provenance",corpus.getString("provenance"),"limitations",corpus.getString("limitations"),"passed",passed,"total",results.length(),"cases",results);
            try(OutputStream out=new FileOutputStream(new File(context.getFilesDir(),"bill-search-quality.json"))){out.write(report.toString(2).getBytes(StandardCharsets.UTF_8));}
            android.os.Bundle status=new android.os.Bundle();status.putString("bill_quality_summary",passed+"/"+results.length());InstrumentationRegistry.getInstrumentation().sendStatus(2,status);
            assertEquals("See bill-search-quality.json for each failed query",results.length(),passed);
        } finally {b.store.exec("DELETE FROM documents WHERE folder_id=?",folder);b.store.exec("DELETE FROM folders WHERE id=?",folder);for(File file:temporary)file.delete();}
    }
}
