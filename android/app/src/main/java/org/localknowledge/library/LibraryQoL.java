package org.localknowledge.library;

import android.database.sqlite.SQLiteDatabase;
import org.json.*;
import java.io.File;
import java.util.*;

/** Personal reading preferences; no document bytes or new database schema. */
final class LibraryQoL {
    final NativeBackend b;final LibraryStore s;
    LibraryQoL(NativeBackend backend){b=backend;s=b.store;}
    JSONObject route(String path,String method,JSONObject body)throws Exception {
        if(path.equals("/library-preferences")){
            if(!method.equals("GET")&&!method.equals("PATCH"))throw new IllegalArgumentException("Unsupported preferences action.");
            JSONArray rows=s.query("SELECT value FROM settings WHERE key=?","khoj.library.preferences");JSONObject old=new JSONObject();
            if(rows.length()>0)try{old=Json.parse(rows.optJSONObject(0).optString("value"));}catch(Exception ignored){}
            JSONObject value=LibraryPreferences.merge(old,method.equals("PATCH")?body:new JSONObject());
            if(method.equals("PATCH"))s.exec("INSERT OR REPLACE INTO settings VALUES(?,?)","khoj.library.preferences",value.toString());
            value.put("saved",method.equals("PATCH")||rows.length()>0);return value;
        }
        if(path.equals("/reading-state")&&method.equals("GET"))return state();
        String[] p=path.split("/");if(p.length==4&&p[1].equals("documents")&&p[3].equals("reading-state")){
            JSONObject doc=s.document(p[2]);if(doc.optInt("trashed")!=0)throw new IllegalArgumentException("This file was removed from PaperVault.");
            if(hidden(doc))throw new IllegalArgumentException("This file is ignored. Include it in PaperVault first.");
            if(method.equals("GET"))return read(doc);
            if(!method.equals("POST"))throw new IllegalArgumentException("Use the reading controls to update this file.");
            if(body.has("sha256")&&!body.optString("sha256").equals(doc.optString("sha256")))throw new IllegalArgumentException("This file changed. Open its latest version.");
            JSONObject value=read(doc);
            if(body.has("favorite")){if(!(body.opt("favorite") instanceof Boolean))throw new IllegalArgumentException("Choose whether to star this file.");value.put("favorite",body.optBoolean("favorite"));}
            if(body.has("page")){Object raw=body.opt("page");if(!(raw instanceof Number))throw new IllegalArgumentException("Choose a valid page.");double number=((Number)raw).doubleValue();if(!Double.isFinite(number)||number!=Math.rint(number)||number<1||number>Math.max(1,doc.optInt("page_count")))throw new IllegalArgumentException("This page is outside the document.");value.put("page",(int)number);}
            if(body.optBoolean("opened"))value.put("last_opened",LibraryStore.now());
            s.exec("INSERT OR REPLACE INTO settings VALUES(?,?)","khoj.reading:"+p[2],value.toString());return value;
        }
        return null;
    }
    boolean hidden(JSONObject doc){return doc.optString("source_mode").equals("reference")&&b.phoneScan.isExcluded(new File(doc.optString("source_path")));}
    static JSONObject decode(JSONObject doc,String stored){
        JSONObject old=new JSONObject();if(stored!=null&&!stored.isEmpty())try{old=Json.parse(stored);}catch(Exception ignored){}
        int page=old.optString("sha256").equals(doc.optString("sha256"))?old.optInt("page",1):1;page=Math.max(1,Math.min(Math.max(1,doc.optInt("page_count")),page));
        return Json.obj("favorite",old.optBoolean("favorite"),"page",page,"last_opened",old.optString("last_opened"),"sha256",doc.optString("sha256"));
    }
    JSONObject read(JSONObject doc){
        JSONArray rows=s.query("SELECT value FROM settings WHERE key=?","khoj.reading:"+doc.optString("id"));
        return decode(doc,rows.length()>0?rows.optJSONObject(0).optString("value"):null);
    }
    JSONObject state()throws Exception {
        JSONObject documents=new JSONObject();List<Map.Entry<String,String>> recent=new ArrayList<>();
        JSONArray rows=s.query("SELECT d.*,s.value reading_value FROM settings s JOIN documents d ON s.key='khoj.reading:'||d.id WHERE s.key LIKE 'khoj.reading:%' AND d.trashed=0");
        for(JSONObject doc:LibraryStore.objects(rows))if(!hidden(doc)){JSONObject value=decode(doc,doc.optString("reading_value"));String id=doc.optString("id");documents.put(id,value);if(!value.optString("last_opened").isEmpty())recent.add(new AbstractMap.SimpleEntry<>(id,value.optString("last_opened")));}
        recent.sort(Comparator.comparingLong((Map.Entry<String,String> item)->openedAt(item.getValue())).reversed());JSONArray ids=new JSONArray();for(var item:recent)ids.put(item.getKey());return Json.obj("documents",documents,"recent_ids",ids);
    }
    static long openedAt(String value){try{return java.time.Instant.parse(value).toEpochMilli();}catch(Exception ignored){return 0;}}
    void restoreSettings(SQLiteDatabase archived,Map<String,String> ids){try(var cursor=archived.rawQuery("SELECT key,value FROM settings WHERE key LIKE 'khoj.reading:%'",null)){while(cursor.moveToNext()){String id=ids.get(cursor.getString(0).substring("khoj.reading:".length()));if(id!=null)s.exec("INSERT OR REPLACE INTO settings VALUES(?,?)","khoj.reading:"+id,cursor.getString(1));}}}
}
