package org.localknowledge.library;

import android.content.Context;
import android.database.sqlite.SQLiteDatabase;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import org.json.*;
import org.junit.Test;
import org.junit.runner.RunWith;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import static org.junit.Assert.*;

/** External private test inputs are never bundled in the application or test APK. */
@RunWith(AndroidJUnit4.class)
public class PhoneMultilingualTest {
 static final File INPUT=new File("/sdcard/Download/khoj-phone-multilingual");
 static List<JSONObject> rows(String name)throws Exception{
  List<JSONObject> result=new ArrayList<>();try(BufferedReader r=new BufferedReader(new InputStreamReader(new FileInputStream(new File(INPUT,name)),StandardCharsets.UTF_8))){String line;while((line=r.readLine())!=null)if(!line.isBlank())result.add(new JSONObject(line));}return result;
 }
 static void save(String name,JSONObject report)throws Exception{try(FileOutputStream out=new FileOutputStream(new File(INPUT,name))){out.write(report.toString(2).getBytes(StandardCharsets.UTF_8));}}
 static void status(String text){android.os.Bundle bundle=new android.os.Bundle();bundle.putString("phone_multilingual",text);InstrumentationRegistry.getInstrumentation().sendStatus(2,bundle);}
 @Test public void fullCorpusSearchAndRealModelLanguageQueries()throws Exception{
  Context context=InstrumentationRegistry.getInstrumentation().getTargetContext();
  NativeBackend b=((LibraryApplication)context.getApplicationContext()).backend;
  String folder=LibraryStore.id(),now=LibraryStore.now();boolean paused=b.paused;b.paused=true;
  Map<String,String> sourceIds=new HashMap<>(),localIds=new HashMap<>();JSONArray results=new JSONArray(),embeddings=new JSONArray();
  List<JSONObject> documents=rows("documents.jsonl"),pages=rows("pages.jsonl"),chunks=rows("chunks.jsonl");
  byte[] vectors;try(InputStream in=new FileInputStream(new File(INPUT,"vectors.f32"))){vectors=ModelAssets.read(in);}
  SQLiteDatabase db=b.store.getWritableDatabase();
  b.store.exec("INSERT INTO folders VALUES(?,?,'blue',?,?)",folder,"Phone language audit "+folder,now,now);
  try{
   db.beginTransaction();try{
    for(JSONObject d:documents){String id=LibraryStore.id();localIds.put(d.getString("id"),id);sourceIds.put(id,d.getString("id"));
     b.store.exec("INSERT INTO documents(id,folder_id,filename,title,sha256,source_path,preview_path,source_uri,format,page_count,chunk_count,status,version,created_at,updated_at,size_bytes,source_mode) VALUES(?,?,?,?,?,?,?,'','pdf',?,?,?,?,?,?,0,'managed')",id,folder,d.getString("filename"),d.optString("title"),d.getString("source_sha256"),"audit-missing/"+id,"audit-missing/"+id,d.getInt("page_count"),d.getInt("chunk_count"),d.getString("status"),d.getInt("version"),now,now);
    }
    for(JSONObject p:pages)b.store.exec("INSERT INTO pages VALUES(?,?,?,?,?,?)",localIds.get(p.getString("document_id")),p.getInt("page_number"),p.getString("text"),p.getString("method"),p.getString("warnings"),p.getString("evidence"));
    for(JSONObject c:chunks){int at=c.getInt("vector_offset_bytes"),length=c.getInt("dimensions")*4;
     b.store.exec("INSERT INTO chunks(document_id,page_number,chunk_index,text,char_start,char_end,vector,input_hash) VALUES(?,?,?,?,?,?,?,?)",localIds.get(c.getString("document_id")),c.getInt("page_number"),c.getInt("chunk_index"),c.getString("text"),c.getInt("char_start"),c.getInt("char_end"),Arrays.copyOfRange(vectors,at,at+length),c.getString("input_hash"));
    }db.setTransactionSuccessful();
   }finally{db.endTransaction();}
   vectors=null;status("Loaded "+documents.size()+" documents, "+pages.size()+" pages, "+chunks.size()+" chunks");
   List<JSONObject> cases=rows("device-cases.jsonl");for(JSONObject c:rows("semantic-cases.jsonl"))if(c.optBoolean("full_backend"))cases.add(c);
   int done=0;
   for(JSONObject c:cases){long started=System.nanoTime();JSONObject row=Json.obj("id",c.getString("id"),"query",c.getString("query"),"language",c.getString("language"),"kind",c.optString("kind","semantic"));
    try{
     JSONObject response=b.search(Json.obj("query",c.getString("query"),"folder_id",folder,"content_only",true,"matching",Json.obj("mode","exact")));
     Set<String> expected=new HashSet<>(),expectedDocs=new HashSet<>(),actual=new TreeSet<>(),actualDocs=new HashSet<>();JSONArray targets=c.getJSONArray("expected");for(int i=0;i<targets.length();i++){String key=targets.getString(i);expected.add(key);expectedDocs.add(key.split(":")[0]);}
     boolean provenance=true;for(JSONObject h:LibraryStore.objects(response.getJSONArray("results"))){String original=sourceIds.get(h.getString("document_id"));assertNotNull("Result escaped the temporary folder",original);String key=original+":"+h.getInt("page_number");actual.add(key);actualDocs.add(original);provenance&=!h.optString("source_identity").isEmpty();}
     boolean semantic=!c.has("kind"),passed=semantic?!Collections.disjoint(expected,actual):c.getString("kind").equals("invoice")?actualDocs.equals(expectedDocs)&&expected.containsAll(actual):actual.containsAll(expected);
     if(!semantic)passed&=response.optString("query_interpreter").equals("not_needed");
     row.put("passed",passed&&provenance).put("actual",new JSONArray(actual)).put("interpreter",response.optString("query_interpreter")).put("elapsed_s",response.optDouble("elapsed_s")).put("semantic_interpretation",response.optString("semantic_interpretation"));
    }catch(Throwable failure){row.put("passed",false).put("error",failure.toString());}
    row.put("wall_ms",(System.nanoTime()-started)/1e6);results.put(row);save("device-results.json",Json.obj("cases",results,"complete",false));status("Full search "+(++done)+"/"+cases.size()+": "+row.optBoolean("passed"));
   }
   // Actual Android LiteRT query vectors, not source vectors or desktop-model substitutes.
   String model=b.models.embedding();int count=0;
   for(JSONObject c:rows("semantic-cases.jsonl")){long started=System.nanoTime();float[] vector=NativeModels.embed(model,"task: search result | query: "+c.getString("query"));embeddings.put(Json.obj("id",c.getString("id"),"query",c.getString("query"),"vector",new JSONArray(vector),"elapsed_ms",(System.nanoTime()-started)/1e6));save("semantic-vectors.json",Json.obj("model_identity",b.models.embeddingSha,"queries",embeddings,"complete",false));status("Actual query embeddings "+(++count));}
   save("semantic-vectors.json",Json.obj("model_identity",b.models.embeddingSha,"queries",embeddings,"complete",true));
   save("device-results.json",Json.obj("documents",documents.size(),"pages",pages.size(),"chunks",chunks.size(),"cases",results,"complete",true,"device","Android x86_64 emulator; not physical-phone latency"));
   for(JSONObject result:LibraryStore.objects(results))if(!result.optString("kind").equals("semantic"))assertTrue("Structured search failed: "+result.optString("id"),result.optBoolean("passed"));
  }finally{b.store.exec("DELETE FROM documents WHERE folder_id=?",folder);b.store.exec("DELETE FROM folders WHERE id=?",folder);b.paused=paused;}
 }
 @Test public void englishRewriteAblation()throws Exception{
  Context context=InstrumentationRegistry.getInstrumentation().getTargetContext();NativeBackend b=((LibraryApplication)context.getApplicationContext()).backend;JSONArray results=new JSONArray();
  String grammar="root ::= [^\\n\\r]+";
  for(JSONObject c:rows("semantic-cases.jsonl")){
   String original=c.getString("query");String prompt=ModelAssets.prompt("Translate the user's document search into one concise English search phrase. Preserve all names, identifiers, dates, numbers and constraints. Do not answer the question or invent details. Return only the English phrase.",original);
   String rewrite=NativeModels.generate(b.models.qwen(),prompt,grammar,72).trim();String model=b.models.embedding();
   float[] translated=NativeModels.embed(model,"task: search result | query: "+rewrite),combined=NativeModels.embed(model,"task: search result | query: "+SemanticQuery.combine(original,rewrite));
   results.put(Json.obj("id",c.getString("id"),"query",original,"rewrite",rewrite,"translated",new JSONArray(translated),"combined",new JSONArray(combined)));save("english-ablation.json",Json.obj("model_identity",b.models.embeddingSha,"queries",results,"complete",false));status("Translation ablation "+results.length());
  }save("english-ablation.json",Json.obj("model_identity",b.models.embeddingSha,"queries",results,"complete",true));
 }
}
