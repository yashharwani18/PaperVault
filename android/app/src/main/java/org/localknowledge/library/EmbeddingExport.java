package org.localknowledge.library;

import android.database.Cursor;
import android.database.sqlite.SQLiteDatabase;
import org.json.*;
import java.io.*;
import java.nio.*;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.zip.*;

/** Portable analysis data, deliberately separate from a library restore archive. */
final class EmbeddingExport {
    static void write(NativeBackend b,OutputStream out) throws Exception {synchronized(b){
        if(!b.idle())throw new IllegalArgumentException("Wait for file reading to finish before exporting embeddings.");
        SQLiteDatabase db=b.store.getReadableDatabase();
        // WAL readers can continue. A transaction pins every exported table to one revision.
        db.beginTransactionNonExclusive();
        try(ZipOutputStream zip=new ZipOutputStream(out)) {
            JSONObject hashes=new JSONObject();
            int documents=jsonl(db,zip,"documents.jsonl","SELECT d.id,d.folder_id,f.name folder_name,d.filename,d.title,d.sha256 source_sha256,d.version,d.format,d.status,d.page_count,d.chunk_count,d.created_at,d.updated_at FROM documents d JOIN folders f ON f.id=d.folder_id WHERE d.trashed=0 ORDER BY d.id",hashes);
            int pages=jsonl(db,zip,"pages.jsonl","SELECT p.* FROM pages p JOIN documents d ON d.id=p.document_id WHERE d.trashed=0 ORDER BY p.document_id,p.page_number",hashes);
            String chunksSql=" FROM chunks c JOIN documents d ON d.id=c.document_id WHERE d.trashed=0 ORDER BY c.id";
            int chunks=0,vectors=0;long offset=0;
            zip.putNextEntry(new ZipEntry("chunks.jsonl"));MessageDigest digest=MessageDigest.getInstance("SHA-256");
            try(Cursor cursor=db.rawQuery("SELECT c.*"+chunksSql,null)) {
                while(cursor.moveToNext()) {
                    JSONObject row=NativeLibraryBrowse.row(cursor);row.remove("vector");
                    byte[] vector=cursor.getBlob(cursor.getColumnIndexOrThrow("vector"));
                    int size=vector==null?0:vector.length;
                    if(size%4!=0)throw new IOException("A stored embedding has an invalid byte length. Export stopped.");
                    if(size>0){FloatBuffer values=ByteBuffer.wrap(vector).order(ByteOrder.LITTLE_ENDIAN).asFloatBuffer();while(values.hasRemaining())if(!Float.isFinite(values.get()))throw new IOException("A stored embedding contains an invalid number. Export stopped.");}
                    row.put("dimensions",size/4);row.put("vector_offset_bytes",size==0?JSONObject.NULL:offset);
                    line(zip,digest,row);offset+=size;chunks++;if(size>0)vectors++;
                }
            }
            zip.closeEntry();hashes.put("chunks.jsonl",LibraryStore.hex(digest.digest()));
            zip.putNextEntry(new ZipEntry("vectors.f32"));digest=MessageDigest.getInstance("SHA-256");
            try(Cursor cursor=db.rawQuery("SELECT c.vector"+chunksSql,null)){while(cursor.moveToNext()){byte[] vector=cursor.getBlob(0);if(vector!=null){zip.write(vector);digest.update(vector);}}}
            zip.closeEntry();hashes.put("vectors.f32",LibraryStore.hex(digest.digest()));
            JSONObject models;try(InputStream input=b.context.getAssets().open("offline-models.json")){models=new JSONObject(new String(ModelAssets.read(input),StandardCharsets.UTF_8));}
            JSONObject manifest=Json.obj("format","khoj-embeddings-v1","created_at",LibraryStore.now(),"app_version",b.context.getPackageManager().getPackageInfo(b.context.getPackageName(),0).versionName,
                "dtype","float32","byte_order","little","vector_file","vectors.f32","vector_offset_unit","bytes","dimensions","Recorded per chunk; do not combine differing input_hash model prefixes.",
                "active_embedding_identity",b.models.embeddingSha,"model_metadata",models,"contains_indexed_text",true,"contains_original_files",false,"includes_trashed",false,
                "counts",Json.obj("documents",documents,"pages",pages,"chunks",chunks,"vectors",vectors,"chunks_without_vectors",chunks-vectors,"vector_bytes",offset),"sha256",hashes);
            zip.putNextEntry(new ZipEntry("manifest.json"));zip.write(manifest.toString(2).getBytes(StandardCharsets.UTF_8));zip.closeEntry();
        } finally {db.endTransaction();}
    }}

    static int jsonl(SQLiteDatabase db,ZipOutputStream zip,String name,String sql,JSONObject hashes) throws Exception {
        MessageDigest digest=MessageDigest.getInstance("SHA-256");int count=0;zip.putNextEntry(new ZipEntry(name));
        try(Cursor cursor=db.rawQuery(sql,null)){while(cursor.moveToNext()){line(zip,digest,NativeLibraryBrowse.row(cursor));count++;}}
        zip.closeEntry();hashes.put(name,LibraryStore.hex(digest.digest()));return count;
    }
    static void line(ZipOutputStream zip,MessageDigest digest,JSONObject row) throws Exception {byte[] bytes=(row.toString()+"\n").getBytes(StandardCharsets.UTF_8);zip.write(bytes);digest.update(bytes);}
}
