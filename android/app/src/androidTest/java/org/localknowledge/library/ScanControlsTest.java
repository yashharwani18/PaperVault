package org.localknowledge.library;

import android.content.Context;
import android.os.Environment;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import org.json.*;
import org.junit.Test;
import org.junit.runner.RunWith;
import java.io.*;
import java.util.*;
import static org.junit.Assert.*;

@RunWith(AndroidJUnit4.class)
public class ScanControlsTest {
    NativeBackend backend(){Context c=InstrumentationRegistry.getInstrumentation().getTargetContext();return ((LibraryApplication)c.getApplicationContext()).backend;}
    @Test public void canonicalRulesRespectFolderBoundaries()throws Exception {
        File root=new File(Environment.getExternalStorageDirectory(),"Documents/Ignore");
        assertTrue(PhoneScan.matches(new File(root,"nested/book.pdf"),root,true));
        assertTrue(PhoneScan.matches(new File(root,"../Ignore/book.pdf"),root,true));
        assertFalse(PhoneScan.matches(new File(root.getPath()+"-other/book.pdf"),root,true));
        assertFalse(PhoneScan.matches(new File(root,"nested/book.pdf"),root,false));
    }
    @Test public void throttleHandlesRapidOpenAndClockChanges(){assertTrue(PhoneScan.autoCheckDue(100,0));assertFalse(PhoneScan.autoCheckDue(101,100));assertTrue(PhoneScan.autoCheckDue(100+PhoneScan.OPEN_THROTTLE_MS,100));assertTrue(PhoneScan.autoCheckDue(90,100));}
    @Test public void automaticDiscoveryRequiresPriorConsent()throws Exception {
        NativeBackend b=backend();String choice=b.phoneScan.value("phone_scan.choice"),enabled=b.phoneScan.value("phone_scan.enabled"),auto=b.phoneScan.value("phone_scan.auto_scan_on_open"),last=b.phoneScan.value("phone_scan.last_auto");
        try{b.phoneScan.set("phone_scan.choice","no");b.phoneScan.set("phone_scan.enabled","true");b.phoneScan.set("phone_scan.auto_scan_on_open","true");b.phoneScan.set("phone_scan.last_auto","123");b.phoneScan.onAppOpen();assertEquals("123",b.phoneScan.value("phone_scan.last_auto"));assertFalse(b.phoneScan.scheduledDiscovery());}
        finally{b.phoneScan.set("phone_scan.choice",choice);b.phoneScan.set("phone_scan.enabled",enabled);b.phoneScan.set("phone_scan.auto_scan_on_open",auto);b.phoneScan.set("phone_scan.last_auto",last);}
    }
    @Test public void rulesPersistSkipDiscoveryAndKeepManagedImportsVisible()throws Exception {
        NativeBackend b=backend();PhoneScan scan=b.phoneScan;assertTrue(scan.hasAccess());String saved=scan.value("phone_scan.exclusions");boolean paused=b.paused,allowed=scan.processingAllowed;
        File root=new File(Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOCUMENTS),"Khoj-ignore-"+System.nanoTime());assertTrue(root.mkdirs());File source=new File(root,"ignored.pdf");try(FileOutputStream out=new FileOutputStream(source)){out.write("test".getBytes());}
        try{b.paused=true;JSONObject rule=Json.obj("path",new File(root,"../"+root.getName()).getPath(),"kind","folder");scan.route("/phone-scan/exclusions","POST",rule);assertTrue(scan.isExcluded(source));assertEquals(root.getCanonicalPath(),scan.options().getJSONArray("exclusions").getJSONObject(scan.exclusions().length()-1).getString("path"));
            JSONArray docs=new JSONArray().put(Json.obj("source_mode","reference","source_path",source.getPath())).put(Json.obj("source_mode","managed","source_path",source.getPath()));assertEquals(1,scan.visibleDocuments(docs).length());
            scan.scanRoots(Collections.singletonList(root));long end=System.currentTimeMillis()+10000;while(scan.finding&&System.currentTimeMillis()<end)Thread.sleep(20);assertFalse(scan.finding);assertEquals(0,b.store.query("SELECT path FROM phone_scan_files WHERE path=?",source.getCanonicalPath()).length());
            scan.route("/phone-scan/exclusions","DELETE",rule);assertFalse(scan.isExcluded(source));scan.scanRoots(Collections.singletonList(root));while(scan.finding&&System.currentTimeMillis()<end)Thread.sleep(20);assertEquals("waiting",b.store.one("SELECT state FROM phone_scan_files WHERE path=?",source.getCanonicalPath()).getString("state"));
            assertTrue(scan.status().isNull("eta_s"));assertEquals("paused",scan.status().getString("stage"));assertTrue(source.isFile());
        }finally{scan.set("phone_scan.exclusions",saved);b.paused=paused;scan.processingAllowed=allowed;b.store.exec("DELETE FROM phone_scan_files WHERE path=?",source.getCanonicalPath());source.delete();root.delete();}
    }
}
