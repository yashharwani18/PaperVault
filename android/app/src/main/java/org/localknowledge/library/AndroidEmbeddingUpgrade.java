package org.localknowledge.library;

import android.database.Cursor;
import android.database.sqlite.SQLiteDatabase;
import org.json.JSONObject;
import java.nio.charset.StandardCharsets;
import java.util.*;

/** Resumable shadow-vector migration; published legacy vectors stay readable. */
final class AndroidEmbeddingUpgrade {
    final NativeBackend b;volatile boolean running;volatile int completed,total;volatile String error="";
    static final String OLD=ModelAssets.LEGACY_SHA+":";
    AndroidEmbeddingUpgrade(NativeBackend backend){
        b=backend;b.store.exec("CREATE TABLE IF NOT EXISTS embedding_upgrade(chunk_id INTEGER PRIMARY KEY REFERENCES chunks(id) ON DELETE CASCADE,input_hash TEXT,new_hash TEXT,vector BLOB,old_vector BLOB)");
        b.models.selectLegacy(remaining()>0);
    }
    int remaining(){return b.store.one("SELECT count(*) n FROM chunks WHERE input_hash LIKE ?",OLD+"%").optInt("n");}
    JSONObject status(){return Json.obj("running",running,"completed",completed,"total",total,"error",error,"text_only",true);}
    static final class Work {long id;String oldHash,input,newHash;byte[] oldVector;}
    synchronized void ensure()throws Exception {
        if(remaining()==0){b.models.ready.get();b.models.selectLegacy(false);return;}
        running=true;error="";
        try{
            b.models.ready.get();b.models.selectLegacy(true);String path=b.models.textEmbedding();total=remaining();
            for(;;){
                b.checkpoint();List<Work> work=new ArrayList<>();
                try(Cursor c=b.store.getReadableDatabase().rawQuery("SELECT c.id,c.input_hash,c.text,c.vector,d.title FROM chunks c JOIN documents d ON d.id=c.document_id LEFT JOIN embedding_upgrade u ON u.chunk_id=c.id AND u.input_hash=c.input_hash WHERE c.input_hash LIKE ? AND u.chunk_id IS NULL ORDER BY c.id LIMIT 4",new String[]{OLD+"%"})){
                    while(c.moveToNext()){Work w=new Work();w.id=c.getLong(0);w.oldHash=c.getString(1);w.oldVector=c.getBlob(3);String title=c.getString(4);w.input="title: "+title.substring(0,Math.min(120,title.length()))+" | text: "+c.getString(2);w.newHash=b.models.textIdentity+":"+LibraryStore.hash(("embeddinggemma2-q8-mean512-v1:"+w.input).getBytes(StandardCharsets.UTF_8));work.add(w);}
                }
                if(work.isEmpty())break;
                String[] inputs=new String[work.size()];for(int i=0;i<inputs.length;i++)inputs[i]=work.get(i).input;
                // Legacy inputs may need a few extra task-prefix tokens. Use a
                // migration-only 1024 signature; normal indexing stays at 512.
                float[][] vectors=LiteRTTextEmbeddings.batch(path,inputs,1024);b.checkpoint();
                synchronized(b){SQLiteDatabase db=b.store.getWritableDatabase();db.beginTransaction();try{for(int i=0;i<work.size();i++){Work w=work.get(i);db.execSQL("INSERT OR REPLACE INTO embedding_upgrade SELECT id,input_hash,?,?,vector FROM chunks WHERE id=? AND input_hash=?",new Object[]{w.newHash,LibraryStore.vector(vectors[i]),w.id,w.oldHash});}db.setTransactionSuccessful();}finally{db.endTransaction();}}
                completed=b.store.one("SELECT count(*) n FROM embedding_upgrade u JOIN chunks c ON c.id=u.chunk_id AND c.input_hash=u.input_hash").optInt("n");
            }
            // Search dispatch owns the same monitor, so it sees one complete space.
            synchronized(b){SQLiteDatabase db=b.store.getWritableDatabase();db.beginTransaction();try{
                db.execSQL("INSERT OR REPLACE INTO vector_cache SELECT u.new_hash,u.vector FROM embedding_upgrade u JOIN chunks c ON c.id=u.chunk_id AND c.input_hash=u.input_hash");
                db.execSQL("UPDATE chunks SET vector=(SELECT u.vector FROM embedding_upgrade u WHERE u.chunk_id=chunks.id),input_hash=(SELECT u.new_hash FROM embedding_upgrade u WHERE u.chunk_id=chunks.id) WHERE input_hash LIKE ? AND EXISTS(SELECT 1 FROM embedding_upgrade u WHERE u.chunk_id=chunks.id AND u.input_hash=chunks.input_hash)",new Object[]{OLD+"%"});
                db.setTransactionSuccessful();
            }finally{db.endTransaction();}b.models.selectLegacy(remaining()>0);}
        }catch(Exception failure){error="Search model update paused: "+String.valueOf(failure.getMessage());throw failure;}
        finally{running=false;}
    }
}
