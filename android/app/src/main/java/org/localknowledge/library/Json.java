package org.localknowledge.library;

import org.json.*;

final class Json {
    static JSONObject obj(Object... pairs) {
        JSONObject out=new JSONObject();
        try { for(int i=0;i<pairs.length;i+=2)out.put((String)pairs[i],pairs[i+1]==null?JSONObject.NULL:pairs[i+1]); }
        catch(JSONException error){throw new IllegalArgumentException(error);}
        return out;
    }
    static JSONArray arr(Object... values){JSONArray out=new JSONArray();for(Object value:values)out.put(value);return out;}
    static JSONObject parse(String value){try{return new JSONObject(value);}catch(Exception e){throw new IllegalArgumentException("Invalid JSON request",e);}}
}
