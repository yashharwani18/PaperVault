package org.localknowledge.library;

import android.content.*;
import android.database.Cursor;
import android.database.sqlite.*;
import org.json.*;
import java.io.*;
import java.nio.*;
import java.security.MessageDigest;
import java.time.Instant;
import java.util.*;

final class LibraryStore extends SQLiteOpenHelper {
    final File root;final Context context;
    LibraryStore(Context context){super(context,"library.sqlite3",null,1);this.context=context;root=new File(context.getFilesDir(),"library");new File(root,"sources").mkdirs();new File(root,"previews").mkdirs();setWriteAheadLoggingEnabled(true);getWritableDatabase();}
    @Override public void onConfigure(SQLiteDatabase db){db.setForeignKeyConstraintsEnabled(true);}
    @Override public void onCreate(SQLiteDatabase db){
        db.execSQL("CREATE TABLE folders(id TEXT PRIMARY KEY,name TEXT UNIQUE COLLATE NOCASE,color TEXT,created_at TEXT,updated_at TEXT)");
        db.execSQL("CREATE TABLE documents(id TEXT PRIMARY KEY,folder_id TEXT REFERENCES folders(id),filename TEXT,title TEXT,sha256 TEXT,source_path TEXT,preview_path TEXT,source_uri TEXT,format TEXT,page_count INTEGER,chunk_count INTEGER,status TEXT,version INTEGER,created_at TEXT,updated_at TEXT,size_bytes INTEGER,trashed INTEGER DEFAULT 0)");
        db.execSQL("CREATE TABLE pages(document_id TEXT REFERENCES documents(id) ON DELETE CASCADE,page_number INTEGER,text TEXT,method TEXT,warnings TEXT,evidence TEXT,PRIMARY KEY(document_id,page_number))");
        db.execSQL("CREATE TABLE chunks(id INTEGER PRIMARY KEY AUTOINCREMENT,document_id TEXT REFERENCES documents(id) ON DELETE CASCADE,page_number INTEGER,chunk_index INTEGER,text TEXT,char_start INTEGER,char_end INTEGER,vector BLOB,input_hash TEXT)");
        db.execSQL("CREATE INDEX chunks_document ON chunks(document_id,page_number)");
        db.execSQL("CREATE TABLE vector_cache(input_hash TEXT PRIMARY KEY,vector BLOB)");
        db.execSQL("CREATE TABLE bills(document_id TEXT PRIMARY KEY REFERENCES documents(id) ON DELETE CASCADE,payload TEXT)");
        db.execSQL("CREATE TABLE history(id TEXT PRIMARY KEY,document_id TEXT,source_sha256 TEXT,created_at TEXT,before_json TEXT,after_json TEXT)");
        db.execSQL("CREATE TABLE tasks(id TEXT PRIMARY KEY,filename TEXT,status TEXT,progress TEXT,error TEXT,result TEXT,source_path TEXT,source_uri TEXT,folder_id TEXT,replace_id TEXT,ocr INTEGER,is_bill INTEGER,created_at TEXT)");
        db.execSQL("CREATE TABLE aliases(alias TEXT PRIMARY KEY,party TEXT)");
        db.execSQL("CREATE TABLE feedback(id TEXT PRIMARY KEY,created_at TEXT,payload TEXT)");
        db.execSQL("CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT)");
        String now=now();db.execSQL("INSERT INTO folders VALUES(?,?,?,?,?)",new Object[]{id(),"Documents","#A78BFA",now,now});
    }
    @Override public void onOpen(SQLiteDatabase db){super.onOpen(db);ensureColumn(db,"documents","source_mode","TEXT NOT NULL DEFAULT 'managed'");ensureColumn(db,"tasks","is_reference","INTEGER NOT NULL DEFAULT 0");db.execSQL("CREATE INDEX IF NOT EXISTS documents_browse_updated ON documents(trashed,updated_at DESC,id)");db.execSQL("CREATE INDEX IF NOT EXISTS documents_browse_added ON documents(trashed,created_at,id)");db.execSQL("CREATE INDEX IF NOT EXISTS documents_browse_size ON documents(trashed,size_bytes,id)");db.execSQL("CREATE INDEX IF NOT EXISTS documents_browse_folder_added ON documents(trashed,folder_id,created_at,id)");}
    void ensureColumn(SQLiteDatabase db,String table,String name,String declaration){try(Cursor c=db.rawQuery("PRAGMA table_info("+table+")",null)){while(c.moveToNext())if(c.getString(1).equals(name))return;}db.execSQL("ALTER TABLE "+table+" ADD COLUMN "+name+" "+declaration);}
    @Override public void onUpgrade(SQLiteDatabase db,int old,int next){throw new IllegalStateException("Unsupported library schema upgrade");}
    static String now(){return Instant.now().toString();}
    static String id(){return UUID.randomUUID().toString().replace("-","");}
    static String hex(byte[] bytes){StringBuilder out=new StringBuilder();for(byte b:bytes)out.append(String.format(Locale.ROOT,"%02x",b&255));return out.toString();}
    static String hash(byte[] bytes)throws Exception {return hex(MessageDigest.getInstance("SHA-256").digest(bytes));}
    static String hash(File file)throws Exception {MessageDigest digest=MessageDigest.getInstance("SHA-256");try(InputStream in=new FileInputStream(file)){byte[] b=new byte[1024*1024];int n;while((n=in.read(b))>=0)digest.update(b,0,n);}return hex(digest.digest());}
    static byte[] vector(float[] values){ByteBuffer b=ByteBuffer.allocate(values.length*4).order(ByteOrder.LITTLE_ENDIAN);for(float value:values)b.putFloat(value);return b.array();}
    static float[] vector(byte[] bytes){FloatBuffer b=ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN).asFloatBuffer();float[] values=new float[b.remaining()];b.get(values);return values;}
    JSONArray query(String sql,String... args){JSONArray result=new JSONArray();try(Cursor c=getReadableDatabase().rawQuery(sql,args)){while(c.moveToNext()){JSONObject row=new JSONObject();for(int i=0;i<c.getColumnCount();i++){
        Object value=c.isNull(i)?JSONObject.NULL:c.getType(i)==Cursor.FIELD_TYPE_INTEGER?c.getLong(i):c.getType(i)==Cursor.FIELD_TYPE_FLOAT?c.getDouble(i):c.getType(i)==Cursor.FIELD_TYPE_BLOB?JSONObject.NULL:c.getString(i);
        try{row.put(c.getColumnName(i),value);}catch(JSONException e){throw new IllegalArgumentException(e);}}
        result.put(row);}}return result;}
    JSONObject one(String sql,String... args){JSONObject row=query(sql,args).optJSONObject(0);if(row==null)throw new IllegalArgumentException("The requested item was not found");return row;}
    void exec(String sql,Object... args){getWritableDatabase().execSQL(sql,args);}
    JSONObject document(String id){return one("SELECT d.*,f.name folder_name FROM documents d JOIN folders f ON f.id=d.folder_id WHERE d.id=?",id);}
    JSONArray documents(){return query("SELECT d.*,f.name folder_name FROM documents d JOIN folders f ON f.id=d.folder_id WHERE trashed=0 ORDER BY d.updated_at DESC");}
    JSONArray folders(){return query("SELECT f.*,count(d.id) document_count FROM folders f LEFT JOIN documents d ON d.folder_id=f.id AND d.trashed=0 GROUP BY f.id ORDER BY f.name COLLATE NOCASE");}
    JSONArray bills(){JSONArray result=new JSONArray();for(JSONObject row:objects(query("SELECT b.payload,d.filename,d.title,d.folder_id FROM bills b JOIN documents d ON d.id=b.document_id WHERE d.trashed=0"))){JSONObject bill=Json.parse(row.optString("payload"));try{bill.put("filename",row.optString("filename"));bill.put("title",row.optString("title"));bill.put("folder_id",row.optString("folder_id"));}catch(JSONException ignored){}result.put(bill);}return result;}
    JSONObject bill(String id){JSONArray rows=query("SELECT payload FROM bills WHERE document_id=?",id);return rows.length()==0?null:Json.parse(rows.optJSONObject(0).optString("payload"));}
    static List<JSONObject> objects(JSONArray values){List<JSONObject> list=new ArrayList<>();for(int i=0;i<values.length();i++)list.add(values.optJSONObject(i));return list;}
    File source(String id,boolean original)throws Exception {JSONObject doc=document(id);String relative=doc.optString(original?"source_path":"preview_path");File file;
        if(doc.optString("source_mode").equals("reference")){file=new File(relative).getCanonicalFile();if(!PhoneScan.access(context)||!PhoneScan.allowedPath(context,file)||!android.net.Uri.fromFile(file).toString().equals(doc.optString("source_uri"))||!file.isFile())throw new FileNotFoundException("Original unavailable. Allow file access and scan again.");if(!hash(file).equals(doc.optString("sha256")))throw new IOException("Original changed. Scan again before opening this version.");}
        else{file=new File(root,relative).getCanonicalFile();if(!file.toPath().startsWith(root.getCanonicalFile().toPath())||!file.isFile())throw new FileNotFoundException("Original source is unavailable");}return file;}

    JSONArray tasks(){JSONArray result=query("SELECT id,filename,status,progress,error,result,folder_id,replace_id document_id,created_at FROM tasks ORDER BY created_at DESC LIMIT 500");for(JSONObject task:objects(result))try{for(String key:new String[]{"progress","result"})if(!task.isNull(key))task.put(key,Json.parse(task.optString(key)));}catch(JSONException ignored){}return result;}
}
