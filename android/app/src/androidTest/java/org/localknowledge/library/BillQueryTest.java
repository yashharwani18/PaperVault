package org.localknowledge.library;

import android.content.Context;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import org.json.*;
import org.junit.Test;
import org.junit.runner.RunWith;
import java.util.*;
import static org.junit.Assert.*;

@RunWith(AndroidJUnit4.class)
public class BillQueryTest {
    @Test public void savedInvoiceNumberDoesNotHijackAnAmount() throws Exception {
        Context context=InstrumentationRegistry.getInstrumentation().getTargetContext();NativeBackend b=((LibraryApplication)context.getApplicationContext()).backend;
        String folder=LibraryStore.id(),first=LibraryStore.id(),second=LibraryStore.id(),now=LibraryStore.now();
        b.store.exec("INSERT INTO folders VALUES(?,?,'blue',?,?)",folder,"Identifier boundary test "+folder,now,now);
        try {
            insert(b,folder,first,"Invoice No: 25\nGrand Total: INR 1000.00",now);insert(b,folder,second,"Invoice No: 26\nGrand Total: INR 2500.00",now);
            b.store.exec("INSERT INTO bills VALUES(?,?)",first,Json.obj("document_id",first,"invoice_number","25","source_page",1,"reviewed",0).toString());
            JSONObject result=b.search(Json.obj("query","total exactly 2500","folder_id",folder,"content_only",true));
            assertEquals(1,result.getJSONArray("results").length());assertEquals(second,result.getJSONArray("results").getJSONObject(0).getString("document_id"));
        } finally {b.store.exec("DELETE FROM documents WHERE folder_id=?",folder);b.store.exec("DELETE FROM folders WHERE id=?",folder);}
    }
    @Test public void nearbyAmountsAndIncompleteReadingRemainExplicit() throws Exception {
        Context context=InstrumentationRegistry.getInstrumentation().getTargetContext();NativeBackend b=((LibraryApplication)context.getApplicationContext()).backend;
        String folder=LibraryStore.id(),first=LibraryStore.id(),second=LibraryStore.id(),pending=LibraryStore.id(),now=LibraryStore.now();
        b.store.exec("INSERT INTO folders VALUES(?,?,'blue',?,?)",folder,"Amount boundary test "+folder,now,now);
        try {
            insert(b,folder,first,"Invoice No: 25\nGrand Total: INR 6600.00",now);
            insert(b,folder,second,"Invoice No: 26\nGrand Total: INR 6630.00",now);
            insert(b,folder,pending,"Unfinished file",now);b.store.exec("DELETE FROM chunks WHERE document_id=?",pending);b.store.exec("UPDATE documents SET chunk_count=0,status='partial' WHERE id=?",pending);
            JSONObject nearby=b.search(Json.obj("query","total 6500","folder_id",folder,"content_only",true));
            assertEquals(2,nearby.getJSONArray("results").length());
            Set<String> actual=new HashSet<>();for(JSONObject hit:LibraryStore.objects(nearby.getJSONArray("results"))){JSONObject amount=hit.getJSONObject("amount_match");actual.add(amount.getString("value"));assertTrue(amount.getBoolean("approximate"));assertEquals("6500.00",amount.getString("requested_value"));}
            assertEquals(new HashSet<>(Arrays.asList("6600.00","6630.00")),actual);
            JSONObject absent=b.search(Json.obj("query","total exactly 6500","folder_id",folder,"content_only",true));
            assertEquals(0,absent.getJSONArray("results").length());assertEquals("no_matching_amount",absent.getString("empty_reason"));
            JSONObject coverage=absent.getJSONObject("diagnostics");assertEquals(3,coverage.getInt("documents"));assertEquals(2,coverage.getInt("searchable"));assertEquals(1,coverage.getInt("needs_attention"));
            JSONObject invoice=b.search(Json.obj("query","show me the invoice 25","folder_id",folder,"content_only",true));
            JSONObject evidence=invoice.getJSONArray("results").getJSONObject(0).getJSONObject("invoice_match");assertEquals("25",evidence.getString("requested_number"));assertEquals("page_text",evidence.getString("source"));
            JSONObject exactHindi=b.search(Json.obj("query","बिल्कुल 6600 वाला बिल","folder_id",folder,"content_only",true));
            assertEquals(1,exactHindi.getJSONArray("results").length());assertEquals(first,exactHindi.getJSONArray("results").getJSONObject(0).getString("document_id"));
        } finally {b.store.exec("DELETE FROM documents WHERE folder_id=?",folder);b.store.exec("DELETE FROM folders WHERE id=?",folder);}
    }
    @Test public void conversationalIdentifierAndHindiAmountFindTheSameInvoice() throws Exception {
        Context context=InstrumentationRegistry.getInstrumentation().getTargetContext();
        NativeBackend b=((LibraryApplication)context.getApplicationContext()).backend;
        String folder=LibraryStore.id(),wanted=LibraryStore.id(),other=LibraryStore.id(),now=LibraryStore.now();
        b.store.exec("INSERT INTO folders VALUES(?,?,'blue',?,?)",folder,"Bill query test "+folder,now,now);
        try {
            insert(b,folder,wanted,"Invoice No: 25\nGrand Total: INR 6600.00",now);
            insert(b,folder,other,"Invoice No: 125\nGrand Total: INR 25.00",now);
            for(String query:new String[]{"show me the invoice 25","invoice no. 25","invoice no. INV-25","find invoice INV-25","मुझे इनवॉइस नंबर २५ दिखाओ","6600 वाला बिल","मुझे ६६०० वाला बिल दिखाओ","6600 रुपये का बिल","total 6600"}) {
                JSONObject result=b.search(Json.obj("query",query,"folder_id",folder,"content_only",true));
                JSONArray hits=result.getJSONArray("results");
                assertEquals(query+": "+result,1,hits.length());
                assertEquals(query,wanted,hits.getJSONObject(0).getString("document_id"));
                if(!query.contains("6600")&&!query.contains("६६००")){
                    assertEquals(query,"bill_fields",hits.getJSONObject(0).getString("score_type"));
                    assertEquals(query,"page_text",hits.getJSONObject(0).getJSONObject("invoice_match").getString("source"));
                }
                if(query.contains("6600")||query.contains("६६००"))assertEquals(query,"6600.00",hits.getJSONObject(0).getJSONObject("amount_match").getString("value"));
            }
        } finally {
            b.store.exec("DELETE FROM documents WHERE folder_id=?",folder);
            b.store.exec("DELETE FROM folders WHERE id=?",folder);
        }
    }

    void insert(NativeBackend b,String folder,String id,String text,String now) {
        b.store.exec("INSERT INTO documents(id,folder_id,filename,title,sha256,source_path,preview_path,source_uri,format,page_count,chunk_count,status,version,created_at,updated_at,size_bytes,source_mode) VALUES(?,?,?,?,?,'missing','missing','','pdf',1,1,'indexed',1,?,?,0,'managed')",id,folder,id+".pdf","Bill fixture","fixture",now,now);
        b.store.exec("INSERT INTO pages VALUES(?,1,?,'native','[]','{}')",id,text);
        b.store.exec("INSERT INTO chunks(document_id,page_number,chunk_index,text,char_start,char_end) VALUES(?,1,0,?,0,?)",id,text,text.length());
    }
}
