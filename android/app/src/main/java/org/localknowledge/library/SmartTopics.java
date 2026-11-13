package org.localknowledge.library;

import android.database.Cursor;
import android.database.sqlite.SQLiteDatabase;
import org.json.*;
import java.util.*;

/** On-demand, conservative semantic suggestions; originals and manual assignments stay intact. */
final class SmartTopics {
    final NativeBackend b;
    volatile boolean running; volatile int named; volatile String error="";
    SmartTopics(NativeBackend backend){b=backend;}
    JSONObject status(){return Json.obj("running",running,"groups",named,"error",error);}
    synchronized JSONObject start(){
        if(running)return status();
        if(!b.idle())throw new IllegalArgumentException("Wait for indexing to finish before suggesting topics.");
        if(!b.models.state.equals("ready"))throw new IllegalArgumentException("The local model is still preparing. Try again shortly.");
        running=true;named=0;error="";
        new Thread(()->{try{build();}catch(Exception e){error="Could not suggest topics. Try again after indexing finishes.";}finally{running=false;}},"khoj-topic-suggestions").start();
        return status();
    }
    static final class Doc { JSONObject data;float[] vector;Doc(JSONObject d,float[] v){data=d;vector=v;} }
    static double dot(float[] a,float[] c){double d=0;for(int i=0;i<a.length;i++)d+=a[i]*c[i];return d;}
    static boolean normalize(float[] v){double n=Math.sqrt(dot(v,v));if(n<1e-9)return false;for(int i=0;i<v.length;i++)v[i]/=(float)n;return true;}
    void build() throws Exception {
        List<Doc> docs=new ArrayList<>();Set<String> hashes=new HashSet<>();
        for(JSONObject d:LibraryStore.objects(b.store.documents())){
            String id=d.optString("id"),sha=d.optString("sha256");
            if(d.optInt("trashed")!=0||sha.isEmpty()||!hashes.add(sha)||b.features.setting("khoj.doc.topics:"+id)!=null)continue;
            float[] avg=null;int count=0;
            try(Cursor c=b.store.getReadableDatabase().rawQuery("SELECT vector FROM chunks WHERE document_id=? ORDER BY page_number,chunk_index LIMIT 32",new String[]{id})){
                while(c.moveToNext()){byte[] raw=c.getBlob(0);if(raw==null||raw.length!=3072)continue;float[] v=LibraryStore.vector(raw);if(avg==null)avg=new float[v.length];for(int i=0;i<v.length;i++)avg[i]+=v[i];count++;}
            }
            if(count>0&&normalize(avg))docs.add(new Doc(d,avg));if(docs.size()>=2000)break;
        }
        if(docs.size()<2)return;
        if(docs.size()>=8){float[] mean=new float[docs.get(0).vector.length];for(Doc d:docs)for(int i=0;i<mean.length;i++)mean[i]+=d.vector[i]/docs.size();for(Doc d:docs){float[] v=d.vector.clone();for(int i=0;i<v.length;i++)v[i]-=mean[i];if(normalize(v))d.vector=v;}}
        double threshold=docs.size()>=8?.45:.85;
        List<List<Doc>> groups=new ArrayList<>();
        for(Doc d:docs){List<Doc> best=null;double score=threshold;for(List<Doc> group:groups){double min=1,avg=0;for(Doc member:group){double x=dot(d.vector,member.vector);min=Math.min(min,x);avg+=x;}avg/=group.size();if(min>=threshold&&avg>=score){score=avg;best=group;}}if(best==null){best=new ArrayList<>();groups.add(best);}best.add(d);}
        int attempts=0;
        for(List<Doc> group:groups){if(group.size()<2||attempts>=12)continue;attempts++;
            StringBuilder examples=new StringBuilder();for(int i=0;i<Math.min(group.size(),3);i++){JSONObject d=group.get(i).data;String id=d.optString("id");JSONArray pages=b.store.query("SELECT substr(text,1,350) text FROM pages WHERE document_id=? ORDER BY page_number LIMIT 1",id);examples.append("\nFile: ").append(d.optString("title")).append("\nText: ").append(pages.length()>0?pages.optJSONObject(0).optString("text"):"");}
            String prompt=ModelAssets.prompt("Name the shared subject of these documents in 2 to 5 specific words. Return only the name. Do not use generic words like documents or miscellaneous alone.",examples.toString());
            String name;try{name=NativeModels.generate(b.models.qwen(),prompt,"root ::= [A-Za-z0-9 &\u0027-]+",40).trim().replaceAll("[\\r\\n].*","").replaceAll("^[\\\"'#* ]+|[\\\"'#* .]+$","").trim();}catch(Exception e){continue;}
            if(name.length()<4||name.length()>60||name.split("\\s+").length>6||name.matches("(?i)(documents|miscellaneous|files|general|other|unknown)"))continue;
            List<String> ids=new ArrayList<>();for(Doc d:group)ids.add(d.data.optString("id"));Collections.sort(ids);String topicId="semantic-"+Integer.toHexString(ids.toString().hashCode());
            SQLiteDatabase db=b.store.getWritableDatabase();db.beginTransaction();try{JSONObject all=b.features.catalogue(),topic=all.optJSONObject(topicId);if(topic==null)topic=Json.obj("id",topicId,"name",name,"basis","Suggested subject · Semantic group");all.put(topicId,topic);b.features.save("khoj.topics",all);for(Doc d:group){String id=d.data.optString("id");JSONObject current=b.store.document(id);if(current.optInt("trashed")==0&&current.optString("sha256").equals(d.data.optString("sha256"))&&b.features.setting("khoj.doc.topics:"+id)==null)b.features.save("khoj.semantic.doc:"+id,Json.obj("sha256",d.data.optString("sha256"),"topics",Json.arr(topicId)));}db.setTransactionSuccessful();named++;}finally{db.endTransaction();}
        }
    }
}
