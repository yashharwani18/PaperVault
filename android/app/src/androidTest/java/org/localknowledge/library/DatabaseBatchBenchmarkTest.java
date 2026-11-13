package org.localknowledge.library;

import android.content.Context;
import android.database.Cursor;
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

/** Compare the original per-row disk commits with PageIndexer's grouped writes. */
@RunWith(AndroidJUnit4.class)
public class DatabaseBatchBenchmarkTest {
    @Test public void compareDiskWritesAndPersistedContents()throws Exception {
        Context c=InstrumentationRegistry.getInstrumentation().getTargetContext();LibraryStore s=((LibraryApplication)c.getApplicationContext()).backend.store;JSONArray oldTimes=new JSONArray(),newTimes=new JSONArray();int rows=0;
        for(int round=0;round<3;round++){
            String sha="database-benchmark-"+LibraryStore.id();File oldFile=new File(c.getCacheDir(),"old-writes.sqlite3"),newFile=new File(c.getCacheDir(),"new-writes.sqlite3");oldFile.delete();newFile.delete();
            try(SQLiteDatabase old=SQLiteDatabase.openOrCreateDatabase(oldFile,null);SQLiteDatabase grouped=SQLiteDatabase.openOrCreateDatabase(newFile,null)){
                for(SQLiteDatabase db:new SQLiteDatabase[]{old,grouped}){db.execSQL("CREATE TABLE pages(page_number INTEGER,text TEXT,method TEXT,warnings TEXT,evidence TEXT)");db.execSQL("CREATE TABLE chunks(page_number INTEGER,chunk_index INTEGER,text TEXT,char_start INTEGER,char_end INTEGER,vector BLOB,input_hash TEXT)");}
                String[] pages=new String[60];for(int i=0;i<pages.length;i++)pages[i]="Page "+i+". "+"Signals use convolution filters and transforms. ".repeat(70);
                byte[] vector=LibraryStore.vector(PageIndexerTest.vector());int index=0;long start=System.nanoTime();
                for(int page=0;page<pages.length;page++){
                    old.execSQL("INSERT INTO pages VALUES(?,?,?,?,?)",new Object[]{page+1,pages[page],"native","[]","{}"});
                    for(int offset=0;offset<pages[page].length();){int end=Math.min(pages[page].length(),offset+900);String text=pages[page].substring(offset,end),input="title: Test | text: "+text,hash=sha+"-old:"+LibraryStore.hash(("embeddinggemma2-q8-mean512-v1:"+input).getBytes(StandardCharsets.UTF_8));
                        try(Cursor cached=s.getReadableDatabase().rawQuery("SELECT vector FROM vector_cache WHERE input_hash=?",new String[]{hash})){if(!cached.moveToFirst())s.exec("INSERT INTO vector_cache VALUES(?,?)",hash,vector);}
                        old.execSQL("INSERT INTO chunks VALUES(?,?,?,?,?,?,?)",new Object[]{page+1,index++,text,offset,end,vector,hash});if(end==pages[page].length())break;offset=end-80;
                    }
                }
                oldTimes.put((System.nanoTime()-start)/1e6);PageIndexer p=new PageIndexer(s,grouped,sha+"-new","Test",new PageIndexerTest.Engine(),()->{},4);start=System.nanoTime();for(int page=0;page<pages.length;page++)p.indexPage(page+1,pages[page],"native","[]","{}",n->{});newTimes.put((System.nanoTime()-start)/1e6);assertEquals(index,p.chunkCount);rows=index;
                try(Cursor a=old.rawQuery("SELECT page_number,chunk_index,text,char_start,char_end,vector FROM chunks ORDER BY chunk_index",null);Cursor b=grouped.rawQuery("SELECT page_number,chunk_index,text,char_start,char_end,vector FROM chunks ORDER BY chunk_index",null)){while(a.moveToNext()){assertTrue(b.moveToNext());for(int col=0;col<5;col++)assertEquals(a.getString(col),b.getString(col));assertArrayEquals(a.getBlob(5),b.getBlob(5));}assertFalse(b.moveToNext());}
            }finally{s.exec("DELETE FROM vector_cache WHERE input_hash LIKE ?",sha+"%");oldFile.delete();newFile.delete();}
        }
        try(OutputStream out=new FileOutputStream(new File(c.getCacheDir(),"database-batch-benchmark.json"))){out.write(Json.obj("pages",60,"chunks",rows,"legacy_ms",oldTimes,"grouped_ms",newTimes,"contents_identical",true).toString().getBytes(StandardCharsets.UTF_8));}
    }
}
