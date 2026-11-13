package org.localknowledge.library;

import android.content.*;
import android.graphics.Paint;
import android.graphics.pdf.PdfDocument;
import android.net.Uri;
import android.os.Environment;
import androidx.core.content.FileProvider;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import org.json.*;
import org.junit.Test;
import org.junit.runner.RunWith;
import java.io.*;
import java.util.*;
import static org.junit.Assert.*;

@RunWith(AndroidJUnit4.class)
public class SharedImportsTest {
    Context context(){return InstrumentationRegistry.getInstrumentation().getTargetContext();}
    NativeBackend backend(){return ((LibraryApplication)context().getApplicationContext()).backend;}
    File fixture(String text)throws Exception {
        File dir=new File(context().getCacheDir(),"exports");assertTrue(dir.isDirectory()||dir.mkdirs());File file=new File(dir,"share-"+System.nanoTime()+".pdf");
        PdfDocument pdf=new PdfDocument();try{PdfDocument.Page page=pdf.startPage(new PdfDocument.PageInfo.Builder(300,400,1).create());Paint paint=new Paint();paint.setTextSize(14);page.getCanvas().drawText(text,20,40,paint);pdf.finishPage(page);try(OutputStream out=new FileOutputStream(file)){pdf.writeTo(out);}}finally{pdf.close();}return file;
    }
    Uri uri(File file){return FileProvider.getUriForFile(context(),context().getPackageName()+".files",file);}
    int partials(){File[] files=context().getCacheDir().listFiles((dir,name)->name.startsWith("khoj-share-")&&name.endsWith(".partial"));return files==null?0:files.length;}

    @Test public void filtersSchemesActionsMimeAndDeduplicatesMultiple(){
        Uri one=Uri.parse("content://pdf.provider/one"),two=Uri.parse("content://pdf.provider/two");
        Intent intent=new Intent(Intent.ACTION_SEND_MULTIPLE).setType("application/pdf");
        intent.putParcelableArrayListExtra(Intent.EXTRA_STREAM,new ArrayList<>(Arrays.asList(one,one,Uri.parse("file:///secret.pdf"),Uri.parse("https://example.org/file.pdf"),two)));
        intent.setClipData(new ClipData("PDF",new String[]{"application/pdf"},new ClipData.Item(one)));
        assertEquals(Arrays.asList(one,two),SharedImports.uris(intent));
        assertEquals(Collections.singletonList(one),SharedImports.uris(new Intent(Intent.ACTION_VIEW).setDataAndType(one,"application/pdf")));
        assertTrue(SharedImports.uris(new Intent(Intent.ACTION_VIEW).setDataAndType(one,"text/html")).isEmpty());
        assertTrue(SharedImports.uris(new Intent(Intent.ACTION_EDIT).setDataAndType(one,"application/pdf")).isEmpty());
        assertTrue(SharedImports.uris(new Intent(Intent.ACTION_VIEW).setDataAndType(Uri.parse("file:///x.pdf"),"application/pdf")).isEmpty());
        ArrayList<Uri> many=new ArrayList<>();for(int i=0;i<70;i++)many.add(Uri.parse("content://pdf.provider/"+i));intent.putParcelableArrayListExtra(Intent.EXTRA_STREAM,many);assertEquals(50,SharedImports.uris(intent).size());
    }
    @Test public void capturesOnceAndRepeatedSharesReusePendingManagedCopy()throws Exception {
        NativeBackend b=backend();boolean old=b.paused;b.paused=true;File source=fixture("Shared capture "+System.nanoTime());String hash=LibraryStore.hash(source);int before=partials();
        try{
            JSONObject first=SharedImports.capture(context(),b,Collections.singletonList(uri(source)));assertEquals(1,first.getJSONArray("task_ids").length());String task=first.getJSONArray("task_ids").getString(0);
            JSONObject row=b.store.one("SELECT * FROM tasks WHERE id=?",task);File owned=new File(row.getString("source_path"));
            assertTrue(owned.isFile());assertEquals(new File(b.store.root,"sources").getCanonicalFile(),owned.getParentFile().getCanonicalFile());assertEquals(hash,LibraryStore.hash(owned));assertEquals(1,row.getInt("ocr"));assertEquals(0,row.getInt("is_reference"));assertEquals("file",Uri.parse(row.getString("source_uri")).getScheme());
            assertEquals("Shared with PaperVault",b.store.one("SELECT name FROM folders WHERE id=?",row.getString("folder_id")).getString("name"));
            JSONObject again=SharedImports.capture(context(),b,Arrays.asList(uri(source),uri(source)));assertEquals(1,again.getJSONArray("task_ids").length());assertEquals(task,again.getJSONArray("task_ids").getString(0));assertEquals(hash,LibraryStore.hash(source));assertEquals(before,partials());
        }finally{b.paused=old;source.delete();}
    }
    @Test public void capturesMultiplePdfGrantsAsSeparateManagedTasks()throws Exception {
        NativeBackend b=backend();boolean old=b.paused;b.paused=true;File first=fixture("First shared PDF "+System.nanoTime()),second=fixture("Second shared PDF "+System.nanoTime());
        try{JSONObject result=SharedImports.capture(context(),b,Arrays.asList(uri(first),uri(second)));assertEquals(2,result.getJSONArray("task_ids").length());for(int i=0;i<2;i++){JSONObject row=b.store.one("SELECT source_path FROM tasks WHERE id=?",result.getJSONArray("task_ids").getString(i));assertTrue(new File(row.getString("source_path")).isFile());}}
        finally{b.paused=old;first.delete();second.delete();}
    }
    @Test public void reusesAvailableDocumentInAnotherFolder()throws Exception {
        NativeBackend b=backend();File source=fixture("Existing shared PDF "+System.nanoTime());String sha=LibraryStore.hash(source),id=LibraryStore.id(),folder=b.store.folders().getJSONObject(0).getString("id"),now=LibraryStore.now();
        File owned=new File(b.store.root,"sources/existing-share-"+id+".pdf");try(InputStream in=new FileInputStream(source);OutputStream out=new FileOutputStream(owned)){NativeTransfer.copy(in,out);}
        b.store.exec("INSERT INTO documents(id,folder_id,filename,title,sha256,source_path,preview_path,source_uri,format,page_count,chunk_count,status,version,created_at,updated_at,size_bytes,trashed,source_mode) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",id,folder,"Existing.pdf","Existing",sha,"sources/"+owned.getName(),"sources/"+owned.getName(),Uri.fromFile(owned).toString(),"pdf",1,0,"indexed",1,now,now,owned.length(),0,"managed");
        try{JSONObject result=SharedImports.capture(context(),b,Collections.singletonList(uri(source)));assertEquals(0,result.getJSONArray("task_ids").length());assertEquals(id,result.getJSONArray("document_ids").getString(0));assertEquals(sha,LibraryStore.hash(source));}
        finally{b.store.exec("DELETE FROM documents WHERE id=?",id);owned.delete();source.delete();}
    }
    @Test public void sharingScannedReferenceRetainsManagedCopyWhenOriginalIsRemovedOrIgnored()throws Exception {
        NativeBackend b=backend();assertTrue("Grant all-files access for reference fixture",b.phoneScan.hasAccess());
        File captured=fixture("Retained reference share "+System.nanoTime());File directory=Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOCUMENTS);assertTrue(directory.isDirectory()||directory.mkdirs());
        File original=new File(directory,"Khoj-shared-reference-"+System.nanoTime()+".pdf");try(InputStream in=new FileInputStream(captured);OutputStream out=new FileOutputStream(original)){NativeTransfer.copy(in,out);}
        String sha=LibraryStore.hash(captured),id=LibraryStore.id(),now=LibraryStore.now(),oldRules=b.phoneScan.value("phone_scan.exclusions");
        JSONArray folders=b.store.query("SELECT id FROM folders WHERE name=? COLLATE NOCASE","Shared with Khoj");String folder;
        if(folders.length()>0)folder=folders.getJSONObject(0).getString("id");else{folder=LibraryStore.id();b.store.exec("INSERT INTO folders VALUES(?,?,?,?,?)",folder,"Shared with Khoj","#A78BFA",now,now);}
        b.store.exec("INSERT INTO documents(id,folder_id,filename,title,sha256,source_path,preview_path,source_uri,format,page_count,chunk_count,status,version,created_at,updated_at,size_bytes,trashed,source_mode) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",id,folder,"Scanned.pdf","Keep this name",sha,original.getAbsolutePath(),original.getAbsolutePath(),Uri.fromFile(original).toString(),"pdf",1,0,"indexed",1,now,now,original.length(),0,"reference");
        b.store.exec("INSERT INTO pages VALUES(?,?,?,?,?,?)",id,1,"Existing indexed passage","native","[]","{}");
        File retained=null;
        try{
            b.dispatch("/documents/"+id+"/reading-state","POST",Json.obj("favorite",true,"page",1,"opened",true,"sha256",sha));
            int tasks=b.store.one("SELECT count(*) n FROM tasks").getInt("n");
            JSONObject result=SharedImports.capture(context(),b,Collections.singletonList(uri(captured)));
            assertEquals(0,result.getJSONArray("task_ids").length());assertEquals(id,result.getJSONArray("document_ids").getString(0));
            JSONObject promoted=b.store.document(id);assertEquals("managed",promoted.getString("source_mode"));assertEquals("Keep this name",promoted.getString("title"));assertEquals(sha,promoted.getString("sha256"));
            retained=b.store.source(id,true);assertNotEquals(original.getCanonicalFile(),retained.getCanonicalFile());assertEquals(sha,LibraryStore.hash(retained));
            assertEquals("Existing indexed passage",b.store.one("SELECT text FROM pages WHERE document_id=?",id).getString("text"));
            assertTrue(b.dispatch("/reading-state","GET",new JSONObject()).getJSONObject("documents").getJSONObject(id).getBoolean("favorite"));
            assertTrue(original.delete());b.phoneScan.set("phone_scan.exclusions",Json.arr(Json.obj("path",original.getAbsolutePath(),"kind","file")).toString());
            assertEquals(sha,LibraryStore.hash(b.store.source(id,false)));assertEquals(1,b.phoneScan.visibleDocuments(b.store.query("SELECT * FROM documents WHERE id=?",id)).length());
            JSONObject repeat=SharedImports.capture(context(),b,Collections.singletonList(uri(captured)));assertEquals(0,repeat.getJSONArray("task_ids").length());assertEquals(id,repeat.getJSONArray("document_ids").getString(0));assertEquals(tasks,b.store.one("SELECT count(*) n FROM tasks").getInt("n"));
        }finally{b.phoneScan.set("phone_scan.exclusions",oldRules);b.store.exec("DELETE FROM documents WHERE id=?",id);if(retained!=null)retained.delete();captured.delete();original.delete();}
    }
    @Test public void rejectsNonPdfAndUnsupportedContentWithoutOrphanPartial()throws Exception {
        NativeBackend b=backend();File source=fixture("placeholder");try(OutputStream out=new FileOutputStream(source)){out.write("Not a PDF".getBytes("UTF-8"));}int before=partials();
        try{try{SharedImports.capture(context(),b,Collections.singletonList(uri(source)));fail("Invalid PDF accepted");}catch(IOException expected){assertFalse(expected.getMessage().contains(source.getPath()));assertFalse(expected.getMessage().contains("content://"));}assertEquals(before,partials());
            try{SharedImports.capture(context(),b,Collections.singletonList(Uri.parse("https://example.org/private.pdf")));fail("Remote URL accepted");}catch(IOException expected){assertFalse(expected.getMessage().contains("example.org"));}assertEquals(before,partials());
        }finally{source.delete();}
    }
}
