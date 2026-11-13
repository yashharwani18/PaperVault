package org.localknowledge.library;

import android.content.ContentValues;
import android.database.Cursor;
import android.database.sqlite.SQLiteDatabase;
import android.graphics.*;
import android.graphics.pdf.PdfDocument;
import org.json.*;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.security.*;
import java.util.*;
import java.util.zip.*;
import javax.crypto.*;
import javax.crypto.spec.*;

final class NativeTransfer {
    final NativeBackend backend;
    NativeTransfer(NativeBackend backend){this.backend=backend;}
    Cipher cipher(int mode,String password,byte[] salt,byte[] iv)throws Exception {PBEKeySpec spec=new PBEKeySpec(password.toCharArray(),salt,200000,256);byte[] key=SecretKeyFactory.getInstance("PBKDF2WithHmacSHA256").generateSecret(spec).getEncoded();spec.clearPassword();Cipher cipher=Cipher.getInstance("AES/GCM/NoPadding");cipher.init(mode,new SecretKeySpec(key,"AES"),new GCMParameterSpec(128,iv));Arrays.fill(key,(byte)0);return cipher;}
    void backup(OutputStream destination,String password)throws Exception {synchronized(backend){
        if(!backend.idle())throw new IllegalArgumentException("Wait for indexing to finish before backup");if(!password.isEmpty()&&password.length()<12)throw new IllegalArgumentException("Use at least 12 characters for backup encryption");
        JSONObject verified=backend.verify();if(!verified.optBoolean("passed"))throw new IllegalArgumentException("Source integrity needs attention before backup");
        try(Cursor checkpoint=backend.store.getWritableDatabase().rawQuery("PRAGMA wal_checkpoint(FULL)",null)){if(checkpoint.moveToFirst()&&checkpoint.getInt(0)!=0)throw new IOException("Database is busy; retry backup");}
        OutputStream stream=destination;if(!password.isEmpty()){byte[] salt=new byte[16],iv=new byte[12];SecureRandom random=new SecureRandom();random.nextBytes(salt);random.nextBytes(iv);destination.write("LLANDROID1".getBytes(StandardCharsets.US_ASCII));destination.write(salt);destination.write(iv);stream=new CipherOutputStream(destination,cipher(Cipher.ENCRYPT_MODE,password,salt,iv));}
        File snapshot=new File(backend.context.getCacheDir(),"backup-"+LibraryStore.id()+".sqlite3");
        try{try(InputStream in=new FileInputStream(backend.context.getDatabasePath("library.sqlite3"));OutputStream out=new FileOutputStream(snapshot)){copy(in,out);}
            Map<String,File> paths=new TreeMap<>();SQLiteDatabase saved=SQLiteDatabase.openDatabase(snapshot.getPath(),null,SQLiteDatabase.OPEN_READWRITE);
            try{for(JSONObject doc:LibraryStore.objects(backend.store.query("SELECT * FROM documents"))){String id=doc.optString("id");File original=backend.store.source(id,true),preview=backend.store.source(id,false);String source=doc.optString("source_path"),rendered=doc.optString("preview_path");if(doc.optString("source_mode").equals("reference")){source="sources/ref-"+id+".pdf";rendered=source;saved.execSQL("UPDATE documents SET source_path=?,preview_path=?,source_mode='managed' WHERE id=?",new Object[]{source,rendered,id});}paths.put(source,original);paths.put(rendered,preview);}}finally{saved.close();}
            JSONObject hashes=new JSONObject();try(ZipOutputStream zip=new ZipOutputStream(stream)){
                add(zip,"library.sqlite3",snapshot,hashes);
                for(Map.Entry<String,File> entry:paths.entrySet()){String path=entry.getKey().replace('\\','/');if(!path.matches("(?:sources|previews)/[a-zA-Z0-9._-]+\\.(?:pdf|pptx|docx|xlsx|txt|md|csv|tsv)"))throw new IOException("Unsupported backup path");add(zip,path,entry.getValue(),hashes);}
                zip.putNextEntry(new ZipEntry("manifest.json"));zip.write(Json.obj("format","local-library-android-v1","files",hashes).toString().getBytes(StandardCharsets.UTF_8));zip.closeEntry();
            }
        }finally{snapshot.delete();}
    }}

    void add(ZipOutputStream zip,String name,File file,JSONObject hashes)throws Exception {MessageDigest digest=MessageDigest.getInstance("SHA-256");zip.putNextEntry(new ZipEntry(name));try(InputStream in=new FileInputStream(file)){byte[] b=new byte[262144];int n;while((n=in.read(b))>=0){zip.write(b,0,n);digest.update(b,0,n);}}zip.closeEntry();hashes.put(name,LibraryStore.hex(digest.digest()));}
    void restore(InputStream input,String password)throws Exception {synchronized(backend){
        if(!backend.idle())throw new IllegalArgumentException("Wait for indexing before restoring");File work=new File(backend.context.getCacheDir(),"restore-"+LibraryStore.id());work.mkdirs();
        PushbackInputStream probe=new PushbackInputStream(input,10);byte[] magic=new byte[10];int count=0;while(count<magic.length){int n=probe.read(magic,count,magic.length-count);if(n<0)break;count+=n;}InputStream data;
        if(count==10&&new String(magic,StandardCharsets.US_ASCII).equals("LLANDROID1")){byte[] salt=new byte[16],iv=new byte[12];new DataInputStream(probe).readFully(salt);new DataInputStream(probe).readFully(iv);if(password.isEmpty())throw new IllegalArgumentException("Enter this backup's password");data=new CipherInputStream(probe,cipher(Cipher.DECRYPT_MODE,password,salt,iv));}
        else{if(count>0)probe.unread(magic,0,count);data=probe;}
        long total=0;int entries=0;Set<String> names=new HashSet<>();
        try(ZipInputStream zip=new ZipInputStream(data)){ZipEntry entry;while((entry=zip.getNextEntry())!=null){String name=entry.getName();if(!names.add(name)||++entries>10000||entry.isDirectory()||(!name.equals("library.sqlite3")&&!name.equals("manifest.json")&&!name.matches("(?:sources|previews)/[a-zA-Z0-9._-]+\\.(?:pdf|pptx|docx|xlsx|txt|md|csv|tsv)")))throw new IOException("Unsupported or unsafe backup entry");File target=new File(work,name).getCanonicalFile();if(!target.toPath().startsWith(work.getCanonicalFile().toPath()))throw new IOException("Unsafe backup path");target.getParentFile().mkdirs();long size=0;try(OutputStream out=new FileOutputStream(target)){byte[] b=new byte[262144];int n;while((n=zip.read(b))>=0){size+=n;total+=n;if(size>150_000_000||total>2_000_000_000L||work.getUsableSpace()<50_000_000)throw new IOException("Backup exceeds the restore work/storage limit");out.write(b,0,n);}}}
            // Read through the GCM tag before trusting any restored metadata.
            if(data instanceof CipherInputStream){byte[] drain=new byte[65536];while(data.read(drain)!=-1){}}
        }
        File manifestFile=new File(work,"manifest.json");if(!manifestFile.isFile()||manifestFile.length()>4_000_000)throw new IOException("Missing or oversized backup manifest");JSONObject manifest;try(InputStream in=new FileInputStream(manifestFile)){manifest=Json.parse(new String(ModelAssets.read(in),StandardCharsets.UTF_8));}
        if(!manifest.optString("format").equals("local-library-android-v1"))throw new IOException("This Android build imports Android-format backups. PC backups remain separate.");JSONObject files=manifest.getJSONObject("files");if(files.length()+1!=names.size())throw new IOException("Backup contents differ from manifest");Iterator<String> expected=files.keys();while(expected.hasNext()){String name=expected.next();if(!names.contains(name)||!LibraryStore.hash(new File(work,name)).equals(files.getString(name)))throw new IOException("Backup checksum mismatch");}
        SQLiteDatabase restored=SQLiteDatabase.openDatabase(new File(work,"library.sqlite3").getAbsolutePath(),null,SQLiteDatabase.OPEN_READONLY|SQLiteDatabase.NO_LOCALIZED_COLLATORS);
        try{
            Map<String,String> trusted=new HashMap<>();try(Cursor c=backend.store.getReadableDatabase().rawQuery("SELECT name,sql FROM sqlite_master WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%'",null)){while(c.moveToNext())trusted.put(c.getString(0),c.getString(1));}
            Map<String,String> observed=new HashMap<>();try(Cursor c=restored.rawQuery("SELECT name,sql FROM sqlite_master WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%'",null)){while(c.moveToNext())observed.put(c.getString(0),c.getString(1));}if(!compatibleSchema(trusted,observed))throw new IOException("Backup schema differs from this app version");
            try(Cursor c=restored.rawQuery("PRAGMA integrity_check",null)){if(!c.moveToFirst()||!c.getString(0).equals("ok"))throw new IOException("Backup database integrity failed");}
            Map<String,String> folders=new HashMap<>(),documents=new HashMap<>(),paths=new HashMap<>();String suffix=LibraryStore.id().substring(0,6);
            // Copy verified bytes to new unique names before committing any metadata.
            Iterator<String> keys=files.keys();while(keys.hasNext()){String old=keys.next();if(old.equals("library.sqlite3"))continue;String target=old.substring(0,old.indexOf('/')+1)+"restored-"+suffix+"-"+old.substring(old.indexOf('/')+1);File destination=new File(backend.store.root,target);try(InputStream in=new FileInputStream(new File(work,old));OutputStream out=new FileOutputStream(destination)){copy(in,out);}paths.put(old,target);}
            SQLiteDatabase db=backend.store.getWritableDatabase();db.beginTransaction();try{
                try(Cursor c=restored.rawQuery("SELECT * FROM folders",null)){while(c.moveToNext()){String old=c.getString(c.getColumnIndexOrThrow("id")),id=LibraryStore.id();folders.put(old,id);backend.store.exec("INSERT INTO folders VALUES(?,?,?,?,?)",id,"Restored · "+c.getString(c.getColumnIndexOrThrow("name"))+" · "+suffix,c.getString(c.getColumnIndexOrThrow("color")),LibraryStore.now(),LibraryStore.now());}}
                try(Cursor c=restored.rawQuery("SELECT * FROM documents",null)){while(c.moveToNext()){ContentValues row=values(c);String old=row.getAsString("id"),id=LibraryStore.id();documents.put(old,id);row.put("id",id);row.put("folder_id",folders.get(row.getAsString("folder_id")));String source=paths.get(row.getAsString("source_path")),preview=paths.get(row.getAsString("preview_path"));if(source==null||preview==null)throw new IOException("Backup is missing a source");row.put("source_path",source);row.put("preview_path",preview);row.put("source_mode","managed");row.put("source_uri",android.net.Uri.fromFile(new File(backend.store.root,source)).toString());db.insertOrThrow("documents",null,row);}}
                for(String table:new String[]{"pages","chunks","bills","history"})try(Cursor c=restored.rawQuery("SELECT * FROM "+table,null)){while(c.moveToNext()){ContentValues row=values(c);String id=documents.get(row.getAsString("document_id"));if(id==null)continue;row.put("document_id",id);if(table.equals("chunks"))row.remove("id");if(table.equals("history")){row.put("id",LibraryStore.id());for(String key:new String[]{"before_json","after_json"})if(row.getAsString(key)!=null){JSONObject bill=Json.parse(row.getAsString(key));bill.put("document_id",id);row.put(key,bill.toString());}}if(table.equals("bills")){JSONObject bill=Json.parse(row.getAsString("payload"));bill.put("document_id",id);row.put("payload",bill.toString());}db.insertOrThrow(table,null,row);}}
                try(Cursor c=restored.rawQuery("SELECT * FROM aliases",null)){while(c.moveToNext())db.insertWithOnConflict("aliases",null,values(c),SQLiteDatabase.CONFLICT_IGNORE);}backend.features.restoreSettings(restored,documents);db.setTransactionSuccessful();
            }finally{db.endTransaction();}
        }finally{restored.close();}
    }}
    static boolean compatibleSchema(Map<String,String> trusted,Map<String,String> observed){
        Set<String> optional=new HashSet<>(Arrays.asList("documents_browse_updated","documents_browse_added","documents_browse_size","documents_browse_folder_added"));
        for(Map.Entry<String,String> item:observed.entrySet())if(!Objects.equals(trusted.get(item.getKey()),item.getValue()))return false;
        Set<String> missing=new HashSet<>(trusted.keySet());missing.removeAll(observed.keySet());return optional.containsAll(missing);
    }
    static ContentValues values(Cursor c){ContentValues out=new ContentValues();for(int i=0;i<c.getColumnCount();i++){String key=c.getColumnName(i);if(c.isNull(i))out.putNull(key);else if(c.getType(i)==Cursor.FIELD_TYPE_BLOB)out.put(key,c.getBlob(i));else if(c.getType(i)==Cursor.FIELD_TYPE_INTEGER)out.put(key,c.getLong(i));else if(c.getType(i)==Cursor.FIELD_TYPE_FLOAT)out.put(key,c.getDouble(i));else out.put(key,c.getString(i));}return out;}
    static void copy(InputStream in,OutputStream out)throws IOException{byte[] b=new byte[262144];int n;while((n=in.read(b))>=0)out.write(b,0,n);}
    void export(JSONObject body,OutputStream out)throws Exception {JSONArray ids=body.getJSONArray("chunk_ids");if(ids.length()<1||ids.length()>25)throw new IllegalArgumentException("Select one to 25 passages");JSONObject sources=body.getJSONObject("sources");List<String> lines=new ArrayList<>();lines.add("Local Library · source context");lines.add("Query: "+body.optString("query"));
        for(int i=0;i<ids.length();i++){String id=String.valueOf(ids.getLong(i));JSONObject chunk=backend.store.one("SELECT * FROM chunks WHERE id=?",id),doc=backend.store.document(chunk.optString("document_id"));String identity=doc.optString("id")+":"+doc.optString("sha256")+":"+doc.optInt("version")+":"+chunk.optInt("chunk_index")+":"+chunk.optInt("page_number");if(!identity.equals(sources.optString(id)))throw new IllegalArgumentException("A selected source changed; search again before export");lines.add("");lines.add(doc.optString("filename")+" · page "+chunk.optInt("page_number"));lines.addAll(Arrays.asList(chunk.optString("text").split("\\n")));}
        lines.add("");lines.add("Indexed source excerpts only; OCR and field association may need review.");
        PdfDocument pdf=new PdfDocument();try{Paint paint=new Paint(Paint.ANTI_ALIAS_FLAG);paint.setTextSize(11);int number=1;PdfDocument.Page page=pdf.startPage(new PdfDocument.PageInfo.Builder(595,842,number).create());float y=35;
            for(String line:lines){List<String> wrapped=new ArrayList<>();String current="";for(String word:line.split("\\s+")){if(!current.isEmpty()&&paint.measureText(current+" "+word)>520){wrapped.add(current);current=word;}else current+=(current.isEmpty()?"":" ")+word;}wrapped.add(current);for(String value:wrapped){if(y>805){pdf.finishPage(page);page=pdf.startPage(new PdfDocument.PageInfo.Builder(595,842,++number).create());y=35;}page.getCanvas().drawText(value,35,y,paint);y+=16;}}
            pdf.finishPage(page);pdf.writeTo(out);}finally{pdf.close();}
    }
}
