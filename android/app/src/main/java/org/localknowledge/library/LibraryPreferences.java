package org.localknowledge.library;
import org.json.*;
import java.util.*;

/** Local sort and search-history preferences; no document evidence or model calls. */
final class LibraryPreferences {
    static final Set<String> SORTS=new HashSet<>(Arrays.asList("name","name_desc","added_new","added_old","modified_new","modified_old","size_large","size_small","type","recent"));
    static JSONObject merge(JSONObject old,JSONObject body){
        String previous=old.optString("sort","added_new");if(!SORTS.contains(previous))previous="added_new";
        JSONArray previousHistory=old.optJSONArray("search_history"),history=new JSONArray();
        if(previousHistory!=null)for(int i=0;i<Math.min(20,previousHistory.length());i++){Object item=previousHistory.opt(i);if(item instanceof String&&!((String)item).trim().isEmpty()&&((String)item).length()<=4096)history.put(item);}
        if(body.has("sort")){Object value=body.opt("sort");if(!(value instanceof String)||!SORTS.contains(value))throw new IllegalArgumentException("Choose a supported library sort order.");previous=(String)value;}
        if(body.has("search_history")){Object value=body.opt("search_history");if(!(value instanceof JSONArray)||((JSONArray)value).length()>20)throw new IllegalArgumentException("Recent searches are invalid.");
            history=new JSONArray();JSONArray input=(JSONArray)value;for(int i=0;i<input.length();i++){Object item=input.opt(i);if(!(item instanceof String)||((String)item).trim().isEmpty()||((String)item).length()>4096)throw new IllegalArgumentException("Recent searches are invalid.");history.put(item);}}
        return Json.obj("sort",previous,"search_history",history);
    }
}
