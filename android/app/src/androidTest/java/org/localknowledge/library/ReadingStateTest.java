package org.localknowledge.library;
import android.content.*;
import android.database.sqlite.SQLiteDatabase;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import org.json.*;
import org.junit.Test;
import org.junit.runner.RunWith;
import java.util.*;
import static org.junit.Assert.*;

@RunWith(AndroidJUnit4.class)
public class ReadingStateTest {
    NativeBackend backend(){Context c=InstrumentationRegistry.getInstrumentation().getTargetContext();return ((LibraryApplication)c.getApplicationContext()).backend;}
    String document(NativeBackend b){String id=LibraryStore.id();ContentValues v=new ContentValues();v.put("id",id);v.put("folder_id",b.store.folders().optJSONObject(0).optString("id"));v.put("filename","Reading preference test.pdf");v.put("title","Reading preference test");v.put("sha256","a".repeat(64));v.put("page_count",12);v.put("chunk_count",0);v.put("source_mode","managed");v.put("source_path","sources/reading-"+id+".pdf");v.put("preview_path","sources/reading-"+id+".pdf");v.put("source_uri","");v.put("format","pdf");v.put("status","indexed");v.put("version",1);v.put("created_at",LibraryStore.now());v.put("updated_at",LibraryStore.now());b.store.getWritableDatabase().insertOrThrow("documents",null,v);return id;}
    void cleanup(NativeBackend b,String id){b.store.exec("DELETE FROM settings WHERE key=?","khoj.reading:"+id);b.store.exec("DELETE FROM documents WHERE id=?",id);}
    @Test public void retainedFilePathsUseOneCanonicalPrivateRoot()throws Exception {NativeBackend b=backend();java.io.File file=new java.io.File(b.store.root,"sources/canonical-test.pdf").getCanonicalFile();assertEquals("sources/canonical-test.pdf",b.relative(file).replace('\\','/'));try{b.relative(b.context.getCacheDir());fail("Outside source accepted");}catch(IllegalArgumentException expected){}}
    @Test public void favoritesAndPagesPersistAndRejectInvalidPositions()throws Exception {
        NativeBackend b=backend();String id=document(b);try{
            JSONObject value=b.dispatch("/documents/"+id+"/reading-state","POST",Json.obj("favorite",true,"page",7,"opened",true,"sha256","a".repeat(64)));assertTrue(value.getBoolean("favorite"));assertEquals(7,value.getInt("page"));assertFalse(value.getString("last_opened").isEmpty());
            JSONObject all=b.dispatch("/reading-state","GET",new JSONObject());assertEquals(7,all.getJSONObject("documents").getJSONObject(id).getInt("page"));assertEquals(id,all.getJSONArray("recent_ids").getString(0));
            for(Object page:new Object[]{0,-1,13,1.5,"3"})try{b.dispatch("/documents/"+id+"/reading-state","POST",Json.obj("page",page));fail("Invalid position accepted");}catch(IllegalArgumentException expected){}
            assertEquals(7,new LibraryQoL(b).read(b.store.document(id)).getInt("page"));
        }finally{cleanup(b,id);}
    }
    @Test public void changedFileResetsPageButKeepsFavoriteAndRejectsStaleSaves()throws Exception {
        NativeBackend b=backend();String id=document(b);try{
            b.dispatch("/documents/"+id+"/reading-state","POST",Json.obj("favorite",true,"page",9));b.store.exec("UPDATE documents SET sha256=?,page_count=3 WHERE id=?","b".repeat(64),id);
            JSONObject value=b.dispatch("/documents/"+id+"/reading-state","GET",new JSONObject());assertEquals(1,value.getInt("page"));assertTrue(value.getBoolean("favorite"));
            try{b.dispatch("/documents/"+id+"/reading-state","POST",Json.obj("page",2,"sha256","a".repeat(64)));fail("Stale save accepted");}catch(IllegalArgumentException expected){}
        }finally{cleanup(b,id);}
    }
    @Test public void restoredReadingPreferencesMapToNewDocumentIds()throws Exception {
        NativeBackend b=backend();String id=document(b);try(SQLiteDatabase archive=SQLiteDatabase.create(null)){
            archive.execSQL("CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT)");archive.execSQL("INSERT INTO settings VALUES(?,?)",new Object[]{"khoj.reading:old-document",Json.obj("favorite",true,"page",5,"sha256","a".repeat(64),"last_opened","2026-10-25T00:00:00Z").toString()});
            new LibraryQoL(b).restoreSettings(archive,Map.of("old-document",id));JSONObject value=b.dispatch("/documents/"+id+"/reading-state","GET",new JSONObject());assertTrue(value.getBoolean("favorite"));assertEquals(5,value.getInt("page"));assertEquals(0,b.store.query("SELECT key FROM settings WHERE key='khoj.reading:old-document'").length());
        }finally{cleanup(b,id);}
    }
    @Test public void browseIndexesSupportExistingAndScopedCatalogQueries()throws Exception {
        NativeBackend b=backend();JSONArray indexes=b.store.query("PRAGMA index_list(documents)");Set<String> names=new HashSet<>();for(JSONObject row:LibraryStore.objects(indexes))names.add(row.getString("name"));
        assertTrue(names.containsAll(Arrays.asList("documents_browse_updated","documents_browse_added","documents_browse_size","documents_browse_folder_added")));
        JSONArray plan=b.store.query("EXPLAIN QUERY PLAN SELECT id FROM documents WHERE trashed=0 ORDER BY updated_at DESC,id LIMIT 100");
        assertTrue(plan.toString(),plan.toString().contains("documents_browse_updated"));assertFalse(plan.toString(),plan.toString().contains("TEMP B-TREE"));
    }

}
