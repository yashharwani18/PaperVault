package org.localknowledge.library;

import android.content.ClipData;
import android.content.Context;
import android.content.Intent;
import android.database.Cursor;
import android.net.Uri;
import android.provider.OpenableColumns;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.*;
import java.util.*;

/** Captures temporary share grants before durable background indexing begins. */
final class SharedImports {
    static final int MAX_FILES=50;
    static final long MAX_FILE_BYTES=100L*1048576,MAX_BATCH_BYTES=500L*1048576;
    private SharedImports(){}

    static List<Uri> uris(Intent intent){
        LinkedHashSet<Uri> found=new LinkedHashSet<>();
        if(intent==null)return new ArrayList<>();
        String action=intent.getAction();
        if(!Intent.ACTION_SEND.equals(action)&&!Intent.ACTION_SEND_MULTIPLE.equals(action)&&!Intent.ACTION_VIEW.equals(action))return new ArrayList<>();
        ClipData clip=intent.getClipData();
        boolean pdf="application/pdf".equalsIgnoreCase(intent.getType());
        if(!pdf&&intent.getType()==null&&clip!=null)pdf=clip.getDescription().hasMimeType("application/pdf");
        if(!pdf)return new ArrayList<>();
        try {
            if(Intent.ACTION_VIEW.equals(action))add(found,intent.getData());
            else if(Intent.ACTION_SEND.equals(action))add(found,intent.getParcelableExtra(Intent.EXTRA_STREAM));
            else {ArrayList<Uri> values=intent.getParcelableArrayListExtra(Intent.EXTRA_STREAM);if(values!=null)for(Uri uri:values)add(found,uri);}
            if(clip!=null)for(int i=0;i<clip.getItemCount();i++)add(found,clip.getItemAt(i).getUri());
        }catch(RuntimeException invalid){return new ArrayList<>();}
        return new ArrayList<>(found);
    }
    private static void add(Set<Uri> out,Uri uri){if(out.size()<MAX_FILES&&uri!=null&&"content".equalsIgnoreCase(uri.getScheme()))out.add(uri);}

    static synchronized JSONObject capture(Context context,NativeBackend backend,List<Uri> selected)throws Exception {
        if(selected==null||selected.isEmpty()||selected.size()>MAX_FILES)throw new IOException("Share between 1 and 50 PDF files with PaperVault.");
        List<File> staged=new ArrayList<>();List<String> names=new ArrayList<>();
        JSONArray tasks=new JSONArray(),documents=new JSONArray();Set<String> seenTasks=new HashSet<>(),seenDocuments=new HashSet<>();
        long total=0;
        try {
            // Capture the entire batch first: provider grants need not survive indexing.
            for(Uri uri:new LinkedHashSet<>(selected)){
                if(uri==null||!"content".equalsIgnoreCase(uri.getScheme()))throw new IOException("Only shared PDF content is supported.");
                String mime=context.getContentResolver().getType(uri);
                if(mime!=null&&!"application/pdf".equalsIgnoreCase(mime)&&!"application/octet-stream".equalsIgnoreCase(mime))throw new IOException("Only PDF files can be shared with PaperVault.");
                File partial=File.createTempFile("khoj-share-",".partial",context.getCacheDir());staged.add(partial);names.add(filename(context,uri));
                try(InputStream in=context.getContentResolver().openInputStream(uri);FileOutputStream out=new FileOutputStream(partial)){
                    if(in==null)throw new IOException("The shared PDF could not be opened.");
                    byte[] buffer=new byte[262144];int count;long size=0;
                    while((count=in.read(buffer))!=-1){size+=count;total+=count;if(size>MAX_FILE_BYTES)throw new IOException("Each shared PDF must be 100 MB or smaller.");if(total>MAX_BATCH_BYTES)throw new IOException("Share at most 500 MB at a time.");out.write(buffer,0,count);}out.getFD().sync();
                }
                try(InputStream in=new FileInputStream(partial)){byte[] header=new byte[5];if(in.read(header)!=5||!Arrays.equals(header,new byte[]{'%', 'P', 'D', 'F', '-'}))throw new IOException("A shared file is not a readable PDF.");}
            }
            String folder=null;
            for(int i=0;i<staged.size();i++){
                File partial=staged.get(i);String sha=LibraryStore.hash(partial);String existing=existingDocument(backend,sha);
                if(existing!=null){if(seenDocuments.add(existing))documents.put(existing);continue;}
                if(folder==null)folder=folder(backend.store);
                File owned=new File(backend.store.root,"sources/shared-"+sha+".pdf");
                if(owned.exists()&&(!owned.isFile()||!sha.equals(LibraryStore.hash(owned))))owned=new File(backend.store.root,"sources/shared-"+sha+"-"+LibraryStore.id()+".pdf");
                boolean created=!owned.exists();
                if(created&&!partial.renameTo(owned)){
                    try(InputStream in=new FileInputStream(partial);FileOutputStream out=new FileOutputStream(owned)){NativeTransfer.copy(in,out);out.getFD().sync();}
                    catch(Exception copyFailure){owned.delete();throw copyFailure;}
                }
                try {
                    String task;
                    synchronized(backend){
                        String source=Uri.fromFile(owned).toString();
                        JSONArray pending=backend.store.query("SELECT id FROM tasks WHERE source_uri=? AND is_reference=0 AND status IN ('queued','running') LIMIT 1",source);
                        task=pending.length()>0?pending.optJSONObject(0).optString("id"):backend.enqueue(source,names.get(i),folder,null,true,false);
                        backend.store.exec("UPDATE tasks SET source_path=? WHERE id=?",owned.getAbsolutePath(),task);
                    }
                    if(seenTasks.add(task))tasks.put(task);
                }catch(Exception failure){
                    if(created&&backend.store.query("SELECT id FROM tasks WHERE source_uri=? LIMIT 1",Uri.fromFile(owned).toString()).length()==0)owned.delete();
                    throw failure;
                }
            }
            return Json.obj("task_ids",tasks,"document_ids",documents,"message",tasks.length()>0?"Shared PDFs added to PaperVault. Reading continues in the background.":"These PDFs are already in PaperVault.");
        }catch(SecurityException denied){throw new IOException("PaperVault could not read the shared PDF. Share it again from the app that owns it.");}
        catch(IOException expected){String message=expected.getMessage();if(message!=null&&(message.startsWith("Only ")||message.startsWith("Each shared ")||message.startsWith("Share at most ")||message.startsWith("A shared file ")))throw new IOException(message);throw new IOException("Could not capture the shared PDFs. Share them again; files already added remain in PaperVault.");}
        catch(Exception failure){throw new IOException("Could not capture the shared PDFs. Share them again; files already added remain in PaperVault.");}
        finally{for(File file:staged)if(file.exists())file.delete();}
    }
    private static String existingDocument(NativeBackend backend,String sha)throws Exception {
        for(JSONObject doc:LibraryStore.objects(backend.phoneScan.visibleDocuments(backend.store.query("SELECT * FROM documents WHERE sha256=? AND trashed=0",sha)))){
            if(!sha.equals(doc.optString("sha256")))continue;
            try{File source=backend.store.source(doc.optString("id"),true);if(sha.equals(LibraryStore.hash(source)))return doc.optString("id");}catch(Exception unavailable){/* A fresh managed copy can recover an unavailable source. */}
        }return null;
    }
    private static String folder(LibraryStore store){
        JSONArray found=store.query("SELECT id FROM folders WHERE name COLLATE NOCASE IN (?, ?) ORDER BY name=? DESC LIMIT 1","Shared with PaperVault","Shared with Khoj","Shared with PaperVault");if(found.length()>0)return found.optJSONObject(0).optString("id");
        String id=LibraryStore.id(),now=LibraryStore.now();store.exec("INSERT OR IGNORE INTO folders VALUES(?,?,?,?,?)",id,"Shared with PaperVault","#A78BFA",now,now);return store.one("SELECT id FROM folders WHERE name=? COLLATE NOCASE","Shared with PaperVault").optString("id");
    }
    private static String filename(Context context,Uri uri){
        String value="Shared PDF.pdf";
        try(Cursor cursor=context.getContentResolver().query(uri,new String[]{OpenableColumns.DISPLAY_NAME},null,null,null)){if(cursor!=null&&cursor.moveToFirst()&&!cursor.isNull(0))value=cursor.getString(0);}catch(RuntimeException ignored){}
        StringBuilder safe=new StringBuilder();for(int i=0;i<value.length();i++){char c=value.charAt(i);safe.append(c=='/'||c==92||Character.isISOControl(c)?'_':c);}value=safe.toString().trim();
        if(value.isEmpty())value="Shared PDF";if(value.length()>180)value=value.substring(0,180);if(!value.toLowerCase(Locale.ROOT).endsWith(".pdf"))value+=".pdf";return value;
    }
}
