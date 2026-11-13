package org.localknowledge.library;
import org.json.JSONObject;
import org.junit.Test;
import static org.junit.Assert.*;
public class ReadingPreferenceTest {
 @Test public void retainsFavoritesAndResetsPageWhenDocumentChanges(){
  JSONObject doc=Json.obj("sha256","new","page_count",3);
  JSONObject value=LibraryQoL.decode(doc,"{\"sha256\":\"old\",\"page\":3,\"favorite\":true,\"last_opened\":\"2026-01-01T00:00:00Z\"}");
  assertTrue(value.optBoolean("favorite"));assertEquals(1,value.optInt("page"));
  assertEquals("2026-01-01T00:00:00Z",value.optString("last_opened"));
 }
 @Test public void corruptPreferencesAreRecoverable(){JSONObject value=LibraryQoL.decode(Json.obj("sha256","a","page_count",2),"not-json");assertEquals(1,value.optInt("page"));assertFalse(value.optBoolean("favorite"));}
}
