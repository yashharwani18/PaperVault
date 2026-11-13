package org.localknowledge.library;
import android.content.*;
import android.graphics.*;
import android.graphics.pdf.PdfDocument;
import android.net.Uri;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import org.json.*;
import org.junit.Test;
import org.junit.runner.RunWith;
import java.io.*;
import java.util.*;
import java.util.concurrent.TimeUnit;
import java.nio.charset.StandardCharsets;
import static org.junit.Assert.*;
@RunWith(AndroidJUnit4.class)
public class AndroidTextRuntimeTest {
 Context target(){return InstrumentationRegistry.getInstrumentation().getTargetContext();}
 Context isolated()throws Exception{
  ((LibraryApplication)target().getApplicationContext()).backend.models.ready.get(2,TimeUnit.MINUTES);
  File dir=new File(target().getCacheDir(),"litert-proof-"+LibraryStore.id());assertTrue(dir.mkdirs());
  return new ContextWrapper(target()){@Override public File getDatabasePath(String name){return new File(dir,name);}@Override public boolean deleteDatabase(String name){return android.database.sqlite.SQLiteDatabase.deleteDatabase(getDatabasePath(name));}};
 }
 File pdf(String text,int pages)throws Exception{File file=new File(target().getCacheDir(),"text-proof-"+LibraryStore.id()+".pdf");PdfDocument pdf=new PdfDocument();try{for(int i=1;i<=pages;i++){var p=pdf.startPage(new PdfDocument.PageInfo.Builder(595,842,i).create());Paint paint=new Paint();paint.setTextSize(12);p.getCanvas().drawText(text,30,60,paint);pdf.finishPage(p);}try(FileOutputStream out=new FileOutputStream(file)){pdf.writeTo(out);}}finally{pdf.close();}return file;}
 JSONObject importFile(NativeBackend b,File source,String folder)throws Exception{String task=b.enqueue(Uri.fromFile(source).toString(),source.getName(),folder,"",false,false);b.indexing.submit(()->{}).get(90,TimeUnit.SECONDS);JSONObject row=b.store.one("SELECT * FROM tasks WHERE id=?",task);assertEquals(row.optString("error"),"completed",row.optString("status"));return Json.parse(row.optString("result")).getJSONObject("document");}
 void cleanup(NativeBackend b,Context c)throws Exception{b.closed=true;b.indexing.shutdownNow();b.phoneScan.scheduler.shutdownNow();for(JSONObject d:LibraryStore.objects(b.store.documents())){File source=new File(b.store.root,d.optString("source_path"));if(source.getCanonicalPath().startsWith(new File(b.store.root,"sources").getCanonicalPath()+File.separator))source.delete();}b.store.close();c.deleteDatabase("library.sqlite3");c.getDatabasePath("library.sqlite3").getParentFile().delete();}
 void report(String file,JSONObject data)throws Exception{try(FileOutputStream out=new FileOutputStream(new File(target().getCacheDir(),file))){out.write(data.toString().getBytes(StandardCharsets.UTF_8));}}
 @Test public void textModelIndexesAndSearchesNewDocuments()throws Exception{
  Context c=isolated();NativeBackend b=new NativeBackend(c);File dsp=pdf("Convolution and Fourier transforms describe digital signal filters",5),sql=pdf("SQL relational databases use tables joins and transactions",1);
  try{b.models.ready.get(2,TimeUnit.MINUTES);assertTrue(b.models.embedding().endsWith(".litertlm"));String folder=b.store.folders().getJSONObject(0).getString("id");JSONObject d=importFile(b,dsp,folder);importFile(b,sql,folder);assertEquals(5,d.getInt("chunk_count"));
   JSONObject results=b.dispatch("/search","POST",Json.obj("query","Fourier transform signal filters","folder_id",folder));assertEquals("qwen",results.getString("query_interpreter"));assertFalse(results.getString("semantic_interpretation").isEmpty());assertEquals(d.getString("id"),results.getJSONArray("results").getJSONObject(0).getString("document_id"));
   String path=b.models.embedding();float[] v=NativeModels.embed(path,"task: search result | query: मुझे Fourier notes दिखाओ 😀");PageIndexer.validate(v);assertTrue(NativeModels.tokenCount(path,"title: Proof | text: नमस्ते 😀")<512);
   assertEquals(0,b.store.one("SELECT count(*) n FROM chunks WHERE input_hash NOT LIKE ?",b.models.textIdentity+":%").getInt("n"));report("litert-new-index.json",Json.obj("documents",2,"five_page_final_batch_published",true,"correct_top_source",true,"unicode_vector_valid",true,"model",ModelAssets.TEXT_MODEL));
  }finally{cleanup(b,c);dsp.delete();sql.delete();}
 }
 @Test public void invoiceNumberSearchFindsIndexedTextWhenSavedFieldIsMissing()throws Exception{
  Context c=isolated();NativeBackend b=new NativeBackend(c);File invoice=pdf("Invoice No: 25   Grand Total: 6600",1),other=pdf("Invoice No: 125   Grand Total: 25",1);
  try{b.models.ready.get(2,TimeUnit.MINUTES);String folder=b.store.folders().getJSONObject(0).getString("id");JSONObject expected=importFile(b,invoice,folder);importFile(b,other,folder);
   JSONObject bill=b.store.bill(expected.getString("id"));bill.put("invoice_number","");b.store.exec("UPDATE bills SET payload=? WHERE document_id=?",bill.toString(),expected.getString("id"));
   JSONObject scoped=b.dispatch("/filename-matches","POST",Json.obj("query",invoice.getName(),"folder_id",folder,"document_ids",Json.arr()));assertEquals(0,scoped.getJSONArray("matches").length());
   JSONObject selected=b.dispatch("/filename-matches","POST",Json.obj("query",invoice.getName(),"folder_id",folder,"document_ids",Json.arr(expected.getString("id"))));assertEquals(1,selected.getJSONArray("matches").length());
   for(String q:new String[]{"inv25","invoice number 25"}){JSONObject result=b.dispatch("/search","POST",Json.obj("query",q,"folder_id",folder));assertEquals("qwen",result.getString("query_interpreter"));JSONArray hits=result.getJSONArray("results");assertEquals(q,1,hits.length());assertEquals(expected.getString("id"),hits.getJSONObject(0).getString("document_id"));}
  }finally{cleanup(b,c);invoice.delete();other.delete();}
 }
 @Test public void literalPassageSearchFindsNonBillDocumentsAndRespectsScope()throws Exception{
  Context c=isolated();NativeBackend b=new NativeBackend(c);File match=pdf("Manual reference XR-25 and Fourier transform",1),other=pdf("Manual reference XR-125 and unrelated notes",1);
  try{b.models.ready.get(2,TimeUnit.MINUTES);String folder=b.store.folders().getJSONObject(0).getString("id");JSONObject expected=importFile(b,match,folder);importFile(b,other,folder);
   List<JSONObject> docs=LibraryStore.objects(b.store.documents());List<JSONObject> hits=b.literalHits(docs,"XR-25");assertEquals(1,hits.size());assertEquals(expected.getString("id"),hits.get(0).getString("document_id"));assertEquals("exact_text",hits.get(0).getString("score_type"));
   assertTrue(b.literalHits(java.util.Collections.emptyList(),"XR-25").isEmpty());
  }finally{cleanup(b,c);match.delete();other.delete();}
 }
 @Test public void plainTextImportSearchAndSourceNavigation()throws Exception{
  Context c=isolated();NativeBackend b=new NativeBackend(c);File text=new File(target().getCacheDir(),"text-fixture-"+LibraryStore.id()+".txt");
  try(FileOutputStream out=new FileOutputStream(text)){out.write("Gujarati ગુજરાતી and Hindi हिंदी.\nThe zephyr switch controls the fan.".getBytes(StandardCharsets.UTF_8));}
  try{b.models.ready.get(2,TimeUnit.MINUTES);String folder=b.store.folders().getJSONObject(0).getString("id");JSONObject doc=importFile(b,text,folder);String id=doc.getString("id"),sha=doc.getString("sha256");
   JSONObject detail=b.dispatch("/documents/"+id,"GET",new JSONObject());assertEquals("text",detail.getJSONObject("document").getString("preview_kind"));assertEquals(1,detail.getJSONArray("pages").length());
   JSONObject unit=b.dispatch("/documents/"+id+"/units/1?revision="+sha,"GET",new JSONObject());assertTrue(unit.getString("text").contains("zephyr switch"));
   JSONObject result=b.dispatch("/search","POST",Json.obj("query","zephyr switch","folder_id",folder));assertEquals(id,result.getJSONArray("results").getJSONObject(0).getString("document_id"));assertEquals("text",result.getJSONArray("results").getJSONObject(0).getString("preview_kind"));
   try{b.dispatch("/documents/"+id+"/units/1?revision=wrong","GET",new JSONObject());fail("changed source must not be shown");}catch(IllegalArgumentException expected){}
   ByteArrayOutputStream backup=new ByteArrayOutputStream();NativeTransfer transfer=new NativeTransfer(b);transfer.backup(backup,"");transfer.restore(new ByteArrayInputStream(backup.toByteArray()),"");
   JSONArray restored=b.store.query("SELECT id,filename,format FROM documents WHERE filename=?",text.getName());assertEquals(2,restored.length());for(JSONObject saved:LibraryStore.objects(restored))assertEquals("txt",saved.getString("format"));
  }finally{cleanup(b,c);text.delete();}
 }
 @Test public void officeDocumentsIndexAndExposeOriginalLocations()throws Exception {
  Context c=isolated();NativeBackend b=new NativeBackend(c);File word=new File(target().getCacheDir(),"office-proof-"+LibraryStore.id()+".docx"),book=new File(target().getCacheDir(),"office-proof-"+LibraryStore.id()+".xlsx");
  Map<String,String> wordParts=new LinkedHashMap<>();wordParts.put("word/document.xml","<w:document xmlns:w='http://schemas.openxmlformats.org/wordprocessingml/2006/main'><w:body><w:p><w:r><w:t>Zephyr document evidence</w:t></w:r></w:p></w:body></w:document>");
  Map<String,String> bookParts=new LinkedHashMap<>();bookParts.put("xl/workbook.xml","<workbook xmlns='http://schemas.openxmlformats.org/spreadsheetml/2006/main' xmlns:r='http://schemas.openxmlformats.org/officeDocument/2006/relationships'><sheets><sheet name='Revenue' sheetId='1' r:id='rId1'/></sheets></workbook>");bookParts.put("xl/_rels/workbook.xml.rels","<Relationships><Relationship Id='rId1' Target='worksheets/sheet1.xml' Type='x/worksheet'/></Relationships>");bookParts.put("xl/worksheets/sheet1.xml","<worksheet xmlns='http://schemas.openxmlformats.org/spreadsheetml/2006/main'><sheetData><row r='7'><c r='A7' t='inlineStr'><is><t>Zephyr sheet evidence</t></is></c><c r='B7'><f>2+3</f><v>5</v></c></row></sheetData></worksheet>");
  writeOffice(word,wordParts);writeOffice(book,bookParts);
  try {b.models.ready.get(2,TimeUnit.MINUTES);String folder=b.store.folders().getJSONObject(0).getString("id");JSONObject w=importFile(b,word,folder),x=importFile(b,book,folder);String id=x.getString("id");
   JSONObject detail=b.dispatch("/documents/"+id,"GET",new JSONObject());assertEquals("spreadsheet",detail.getJSONObject("document").getString("source_kind"));assertEquals("Revenue · row 7",detail.getJSONArray("pages").getJSONObject(0).getString("location_label"));
   JSONObject unit=b.dispatch("/documents/"+id+"/units/1?revision="+x.getString("sha256"),"GET",new JSONObject());assertTrue(unit.getString("text").contains("A7: Zephyr sheet evidence"));assertEquals(7,unit.getJSONObject("location").getInt("row_start"));assertTrue(unit.getJSONArray("warnings").toString().contains("not evaluated"));
   List<JSONObject> hits=b.literalHits(LibraryStore.objects(b.store.documents()),"Zephyr sheet evidence");assertEquals(1,hits.size());assertEquals(id,hits.get(0).getString("document_id"));assertEquals("Revenue · row 7",hits.get(0).getString("location_label"));
   JSONObject wordUnit=b.dispatch("/documents/"+w.getString("id")+"/units/1","GET",new JSONObject());assertTrue(wordUnit.getString("text").contains("Zephyr document evidence"));
   ByteArrayOutputStream backup=new ByteArrayOutputStream();NativeTransfer transfer=new NativeTransfer(b);transfer.backup(backup,"");transfer.restore(new ByteArrayInputStream(backup.toByteArray()),"");assertEquals(2,b.store.query("SELECT id FROM documents WHERE filename=?",book.getName()).length());
  }finally{cleanup(b,c);word.delete();book.delete();}
 }
 void writeOffice(File file,Map<String,String> parts)throws Exception {try(java.util.zip.ZipOutputStream zip=new java.util.zip.ZipOutputStream(new FileOutputStream(file))){for(Map.Entry<String,String> part:parts.entrySet()){zip.putNextEntry(new java.util.zip.ZipEntry(part.getKey()));zip.write(part.getValue().getBytes(StandardCharsets.UTF_8));zip.closeEntry();}}}
 @Test public void legacyIndexMigratesAtomicallyWithoutRereadingPdf()throws Exception{
  Context c=isolated();LibraryStore seed=new LibraryStore(c);String folder=seed.folders().getJSONObject(0).getString("id"),id=LibraryStore.id();String text="Fourier transforms and convolution describe digital signal filters";String raw="title: Legacy DSP | text: "+text,oldHash=ModelAssets.LEGACY_SHA+":"+LibraryStore.hash(("embeddinggemma2-q8-mean512-v1:"+raw).getBytes(StandardCharsets.UTF_8));
  String legacy=new File(new File(target().getFilesDir(),"models"),ModelAssets.LEGACY_MODEL).getPath();float[] oldVector=NativeModels.embed(legacy,raw);byte[] oldBytes=LibraryStore.vector(oldVector);
  File source=pdf(text,1),managed=new File(seed.root,"sources/"+id+".pdf");java.nio.file.Files.copy(source.toPath(),managed.toPath());String sha=LibraryStore.hash(managed),now=LibraryStore.now();
  seed.exec("INSERT INTO documents(id,folder_id,filename,title,sha256,source_path,preview_path,source_uri,format,page_count,chunk_count,status,version,created_at,updated_at,size_bytes) VALUES(?,?,?,?,?,?,?,?,?,1,1,'indexed',1,?,?,?)",id,folder,"legacy-proof.pdf","Legacy DSP",sha,"sources/"+id+".pdf","sources/"+id+".pdf",Uri.fromFile(managed).toString(),"pdf",now,now,managed.length());
  seed.exec("INSERT INTO pages VALUES(?,1,?,'native','[]','{}')",id,text);seed.exec("INSERT INTO chunks(document_id,page_number,chunk_index,text,char_start,char_end,vector,input_hash) VALUES(?,1,0,?,0,?,?,?)",id,text,text.length(),oldBytes,oldHash);seed.close();NativeBackend b=new NativeBackend(c);
  try{b.models.ready.get(2,TimeUnit.MINUTES);assertTrue(b.models.legacyEmbedding);JSONObject before=b.dispatch("/search","POST",Json.obj("query","Fourier signal filters","folder_id",folder));assertEquals(id,before.getJSONArray("results").getJSONObject(0).getString("document_id"));
   b.embeddingUpgrade.ensure();assertFalse(b.models.legacyEmbedding);assertEquals(1,b.store.documents().length());assertEquals(sha,LibraryStore.hash(managed));assertEquals(text,b.store.one("SELECT text FROM pages WHERE document_id=?",id).getString("text"));
   JSONObject after=b.dispatch("/search","POST",Json.obj("query","Fourier signal filters","folder_id",folder));assertEquals(id,after.getJSONArray("results").getJSONObject(0).getString("document_id"));
   try(var row=b.store.getReadableDatabase().rawQuery("SELECT old_vector FROM embedding_upgrade",null)){assertTrue(row.moveToFirst());assertArrayEquals(oldBytes,row.getBlob(0));}
   assertEquals(0,b.embeddingUpgrade.remaining());report("litert-legacy-migration.json",Json.obj("legacy_search_worked",true,"new_search_worked",true,"original_unchanged",true,"pages_preserved",true,"old_vectors_retained",true));
  }finally{cleanup(b,c);source.delete();}
 }
}
