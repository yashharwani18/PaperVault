package org.localknowledge.library;
import org.json.*;
import org.junit.Test;
import static org.junit.Assert.*;
public class LibraryPreferencesTest {
 @Test public void savesAndClearsHistoryAndSort()throws Exception{
  JSONObject value=LibraryPreferences.merge(new JSONObject(),Json.obj("sort","name","search_history",Json.arr("one","two")));
  assertEquals("name",value.getString("sort"));assertEquals(2,value.getJSONArray("search_history").length());
  assertEquals(0,LibraryPreferences.merge(value,Json.obj("search_history",new JSONArray())).getJSONArray("search_history").length());
 }
 @Test public void rejectsUnsupportedSortAndOversizedHistory(){
  try{LibraryPreferences.merge(new JSONObject(),Json.obj("sort","invalid"));fail();}catch(IllegalArgumentException expected){}
 }
}
