package org.localknowledge.library;

import android.database.sqlite.SQLiteDatabase;
import android.database.Cursor;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.function.IntConsumer;

/** Bounded page-local embedding and staging; document publication stays in NativeBackend. */
final class PageIndexer {
    interface Engine {
        int tokens(String input)throws Exception;
        float[] scalar(String input)throws Exception;
        float[][] batch(String[] inputs)throws Exception;
    }
    interface Checkpoint {void check()throws Exception;}
    static final String RECIPE="page-paragraph-512-v2";
    int chunkCount;
    long embeddingNs,databaseNs;
    final LibraryStore store;final SQLiteDatabase stage;final String modelSha,title;final Engine engine;final Checkpoint checkpoint;final int capacity;
    final boolean acrossPages;final List<Chunk> buffered=new ArrayList<>();
    static class Chunk {int page,start,end;String text,input,hash;float[] vector;}
    PageIndexer(LibraryStore store,SQLiteDatabase stage,String modelSha,String title,Engine engine,Checkpoint checkpoint,int capacity){
        this(store,stage,modelSha,title,engine,checkpoint,capacity,false);
    }
    PageIndexer(LibraryStore store,SQLiteDatabase stage,String modelSha,String title,Engine engine,Checkpoint checkpoint,int capacity,boolean acrossPages){
        this.acrossPages=acrossPages;
        if(capacity<1||capacity>4)throw new IllegalArgumentException("Batch capacity must be 1 to 4");
        this.store=store;this.stage=stage;this.modelSha=modelSha;this.title=title.substring(0,Math.min(120,title.length()));this.engine=engine;this.checkpoint=checkpoint;this.capacity=capacity;
    }
    static void validate(float[] vector){if(vector==null||vector.length!=768)throw new IllegalStateException("Invalid embedding dimensions");double norm=0;for(float v:vector){if(!Float.isFinite(v))throw new IllegalStateException("Invalid embedding values");norm+=v*v;}if(Math.abs(norm-1)>0.001)throw new IllegalStateException("Invalid embedding normalization");}
    float[] cached(String hash){long t=System.nanoTime();try(Cursor c=store.getReadableDatabase().rawQuery("SELECT vector FROM vector_cache WHERE input_hash=?",new String[]{hash})){if(c.moveToFirst()){byte[] blob=c.getBlob(0);if(blob!=null&&blob.length==768*4){float[] v=LibraryStore.vector(blob);try{validate(v);return v;}catch(IllegalStateException ignored){}}}return null;}finally{databaseNs+=System.nanoTime()-t;}}
    String input(String text){return "title: "+title+" | text: "+text;}
    String hash(String input)throws Exception{return modelSha+":"+LibraryStore.hash(("embeddinggemma2-q8-mean512-v1:"+input).getBytes(StandardCharsets.UTF_8));}
    int boundary(String text,int end){if(end>0&&end<text.length()&&Character.isHighSurrogate(text.charAt(end-1)))end--;return end;}
    int fittingEnd(String text,int start)throws Exception {
        int good=start,bad=text.length()+1,probe=boundary(text,Math.min(text.length(),start+1024));
        while(probe>good){checkpoint.check();if(engine.tokens(input(text.substring(start,probe)))<=480){good=probe;if(probe==text.length())return probe;probe=boundary(text,Math.min(text.length(),start+2*(probe-start)));}else{bad=probe;break;}}
        while(bad-good>1){int middle=boundary(text,good+(bad-good)/2);if(middle<=good)break;checkpoint.check();if(engine.tokens(input(text.substring(start,middle)))<=480)good=middle;else bad=middle;}
        if(good<=start)throw new IllegalStateException("Title and a source character exceed the embedding token budget");
        return good;
    }
    int naturalEnd(String text,int start,int end){
        if(end==text.length())return end;int floor=start+Math.max(1,(end-start)/2);
        for(String separator:new String[]{"\r\n\r\n","\n\n","\n"}){int i=text.lastIndexOf(separator,end-separator.length());if(i>=floor)return i+separator.length();}
        for(int i=end-1;i>=floor;i--)if(".!?।".indexOf(text.charAt(i))>=0&&i+1<text.length()&&Character.isWhitespace(text.charAt(i+1)))return i+1;
        for(int i=end-1;i>=floor;i--)if(Character.isWhitespace(text.charAt(i)))return i+1;
        return end;
    }
    int overlapStart(String text,int start,int end)throws Exception {
        int next=boundary(text,end-Math.min(200,(end-start)/4));
        while(next<end&&engine.tokens(text.substring(next,end))>64){int moved=boundary(text,next+Math.max(1,(end-next)/2));next=moved>next?moved:end;}
        return Math.max(start+1,next);
    }
    void indexPage(int page,String text,String method,String warnings,String evidence,IntConsumer progress)throws Exception {
        checkpoint.check();long t=System.nanoTime();stage.beginTransaction();try{stage.execSQL("INSERT INTO pages VALUES(?,?,?,?,?)",new Object[]{page,text,method,warnings,evidence});stage.setTransactionSuccessful();}finally{stage.endTransaction();databaseNs+=System.nanoTime()-t;}
        if(!text.trim().isEmpty()){
            String full=input(text),fullHash=hash(full);float[] fullVector=cached(fullHash);
            boolean whole=fullVector!=null||engine.tokens(full)<=512;int start=0,previousEnd=0;
            while(start<text.length()){
                checkpoint.check();int end=whole?text.length():naturalEnd(text,start,fittingEnd(text,start));
                if(end<=previousEnd){start=previousEnd;continue;}
                Chunk c=new Chunk();c.page=page;c.start=start;c.end=end;c.text=text.substring(start,end);c.input=whole?full:input(c.text);c.hash=whole?fullHash:hash(c.input);c.vector=whole?fullVector:cached(c.hash);
                // Natural boundaries can change tokenization: validate the exact final input.
                if(c.vector==null&&engine.tokens(c.input)>512)throw new IllegalStateException("Final passage exceeds embedding token budget");
                buffered.add(c);if(buffered.size()==capacity){flushBuffered(progress);}
                previousEnd=end;if(end==text.length())break;start=overlapStart(text,start,end);
            }
        }
        if(!acrossPages)finish(progress);
    }
    void finish(IntConsumer progress)throws Exception{if(!buffered.isEmpty())flushBuffered(progress);}
    void flushBuffered(IntConsumer progress)throws Exception {
        List<Chunk> chunks=buffered;
        checkpoint.check();LinkedHashMap<String,Chunk> missing=new LinkedHashMap<>();for(Chunk c:chunks)if(c.vector==null)missing.putIfAbsent(c.hash,c);
        if(!missing.isEmpty()){
            progress.accept(chunkCount);checkpoint.check();long t=System.nanoTime();List<Chunk> work=new ArrayList<>(missing.values());float[][] output=null;
            try{
                if(work.size()>1){try{String[] inputs=new String[work.size()];for(int i=0;i<work.size();i++)inputs[i]=work.get(i).input;output=engine.batch(inputs);if(output==null||output.length!=work.size())throw new IllegalStateException("Invalid embedding batch output");for(float[] v:output)validate(v);}catch(IllegalStateException|IllegalArgumentException error){output=null;}}
                if(output==null){output=new float[work.size()][];for(int i=0;i<work.size();i++){checkpoint.check();output[i]=engine.scalar(work.get(i).input);validate(output[i]);}}
                for(int i=0;i<work.size();i++)work.get(i).vector=output[i];
            }finally{embeddingNs+=System.nanoTime()-t;}
            checkpoint.check();t=System.nanoTime();SQLiteDatabase db=store.getWritableDatabase();db.beginTransaction();try{for(Chunk c:work)db.execSQL("INSERT OR REPLACE INTO vector_cache VALUES(?,?)",new Object[]{c.hash,LibraryStore.vector(c.vector)});db.setTransactionSuccessful();}finally{db.endTransaction();databaseNs+=System.nanoTime()-t;}
        }
        checkpoint.check();long t=System.nanoTime();stage.beginTransaction();try{
            int index=chunkCount;for(Chunk c:chunks){float[] v=c.vector==null?missing.get(c.hash).vector:c.vector;stage.execSQL("INSERT INTO chunks VALUES(?,?,?,?,?,?,?)",new Object[]{c.page,index++,c.text,c.start,c.end,LibraryStore.vector(v),c.hash});}
            stage.setTransactionSuccessful();
        }finally{stage.endTransaction();databaseNs+=System.nanoTime()-t;}
        chunkCount+=chunks.size();buffered.clear();
    }
}
