package org.localknowledge.library;
import android.content.Context;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import org.json.*;
import org.junit.Test;
import org.junit.runner.RunWith;
import static org.junit.Assert.*;

@RunWith(AndroidJUnit4.class)
public class BillTopicScopeTest {
 @Test public void datedGeneralTopicsDoNotAcquireSavedBillFilters()throws Exception{
  Context context=InstrumentationRegistry.getInstrumentation().getTargetContext();NativeBackend b=((LibraryApplication)context.getApplicationContext()).backend;
  JSONObject filters=b.filters("sales register September 2026",new JSONObject(),false,false);
  assertEquals("",filters.optString("direction"));assertEquals("",filters.optString("date_from"));assertEquals("",filters.optString("date_to"));
  JSONObject explicit=b.filters("sales invoices September 2026",new JSONObject(),false,false);
  assertEquals("sale",explicit.optString("direction"));assertEquals("2026-09-01",explicit.optString("date_from"));assertEquals("2026-09-30",explicit.optString("date_to"));
 }
}
