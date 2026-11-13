package org.localknowledge.library;

import android.content.ContentValues;
import android.content.Context;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import org.json.*;
import org.junit.Test;
import org.junit.runner.RunWith;
import static org.junit.Assert.*;

@RunWith(AndroidJUnit4.class)
public class LibraryBrowseTest {
    @Test public void nameOrderPrecedesPaginationAndMatchesLetterOffsets() throws Exception {
        Context context=InstrumentationRegistry.getInstrumentation().getTargetContext();
        NativeBackend b=((LibraryApplication)context.getApplicationContext()).backend;
        String folder=LibraryStore.id(),prefix=LibraryStore.id();
        String[] filenames={"Zulu.pdf","Report 10.pdf","alpine.pdf","Report 2.pdf","Alpha.pdf","Beta.pdf"};
        String savedExclusions=b.phoneScan.value("phone_scan.exclusions");
        b.store.exec("INSERT INTO folders VALUES(?,?,'blue',?,?)",folder,"Sort test "+folder,LibraryStore.now(),LibraryStore.now());
        try {
            b.phoneScan.set("phone_scan.exclusions","[]");
            for(int i=0;i<filenames.length;i++) {
                ContentValues row=new ContentValues();
                row.put("id",prefix+i);row.put("folder_id",folder);row.put("filename",filenames[i]);row.put("title",filenames[i]);
                row.put("sha256","sort-fixture");row.put("source_path","missing");row.put("preview_path","missing");row.put("source_uri","");
                row.put("source_mode","managed");row.put("format","pdf");row.put("page_count",1);row.put("chunk_count",0);
                row.put("status","indexed");row.put("version",1);row.put("size_bytes",0);row.put("created_at",LibraryStore.now());row.put("updated_at",LibraryStore.now());
                b.store.getWritableDatabase().insertOrThrow("documents",null,row);
            }
            assertPages(b,folder,"name","",new String[]{"Alpha.pdf","alpine.pdf","Beta.pdf","Report 2.pdf","Report 10.pdf","Zulu.pdf"});
            assertPages(b,folder,"name_desc","",new String[]{"Zulu.pdf","Report 10.pdf","Report 2.pdf","Beta.pdf","alpine.pdf","Alpha.pdf"});
            // A name filter takes the other database path; both must agree.
            assertPages(b,folder,"name","Report",new String[]{"Report 2.pdf","Report 10.pdf"});
            assertPages(b,folder,"name_desc","Report",new String[]{"Report 10.pdf","Report 2.pdf"});
            JSONObject page=NativeLibraryBrowse.page(b,Json.obj("folder_id",folder,"sort","name","limit",2));
            JSONArray letters=page.getJSONArray("letters");
            assertEquals(4,letters.length());
            String[] expectedLetters={"A","B","R","Z"};int[] expectedOffsets={0,2,3,5};
            for(int i=0;i<letters.length();i++) {
                assertEquals(expectedLetters[i],letters.getJSONObject(i).getString("letter"));
                assertEquals(expectedOffsets[i],letters.getJSONObject(i).getInt("offset"));
            }
        } finally {
            b.phoneScan.set("phone_scan.exclusions",savedExclusions);
            b.store.exec("DELETE FROM documents WHERE folder_id=?",folder);
            b.store.exec("DELETE FROM folders WHERE id=?",folder);
        }
    }

    void assertPages(NativeBackend b,String folder,String sort,String filter,String[] expected) throws Exception {
        for(int offset=0;offset<expected.length;offset+=2) {
            JSONObject page=NativeLibraryBrowse.page(b,Json.obj("folder_id",folder,"sort",sort,"name",filter,"offset",offset,"limit",2));
            assertEquals(expected.length,page.getInt("total"));
            JSONArray documents=page.getJSONArray("documents");
            assertEquals(Math.min(2,expected.length-offset),documents.length());
            for(int i=0;i<documents.length();i++)assertEquals(sort+" offset "+(offset+i),expected[offset+i],documents.getJSONObject(i).getString("filename"));
        }
    }
}
