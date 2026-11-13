package org.localknowledge.library;
import android.content.Context;
import android.graphics.Paint;
import android.graphics.pdf.PdfDocument;
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
public class PhoneScanTest {
    void writePdf(File file,String text)throws Exception {PdfDocument pdf=new PdfDocument();try{PdfDocument.Page page=pdf.startPage(new PdfDocument.PageInfo.Builder(595,842,1).create());Paint paint=new Paint();paint.setTextSize(18);page.getCanvas().drawText(text,30,60,paint);pdf.finishPage(page);try(OutputStream out=new FileOutputStream(file)){pdf.writeTo(out);}}finally{pdf.close();}}
    @Test public void discoversAndIndexesOriginalsWithoutCopiesAndRemembersScan()throws Exception {
        Context context=InstrumentationRegistry.getInstrumentation().getTargetContext();NativeBackend b=((LibraryApplication)context.getApplicationContext()).backend;
        assertTrue("Test runner must grant all-files access on emulator",b.phoneScan.hasAccess());
        File root=new File(Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOCUMENTS),"Khoj-scan-test-"+System.nanoTime());assertTrue(root.mkdirs());
        File source=new File(root,"Signal notes.PDF"),broken=new File(root,"Broken.pdf");
        // Each run needs distinct bytes: earlier fixtures intentionally remain
        // in the persistent scan registry and are correctly deduplicated.
        writePdf(source,"Digital signal processing uses filters and convolution. "+System.nanoTime());
        try(OutputStream out=new FileOutputStream(broken)){out.write("Not a readable PDF".getBytes());}
        int before=new File(b.store.root,"sources").list().length;String hash=LibraryStore.hash(source);
        b.phoneScan.scanRoots(Collections.singletonList(root));
        long deadline=System.currentTimeMillis()+120000;while((b.phoneScan.finding||b.phoneScan.pending())&&System.currentTimeMillis()<deadline)Thread.sleep(250);
        assertFalse("Scan indexing timed out",b.phoneScan.pending());
        JSONObject file=b.store.one("SELECT * FROM phone_scan_files WHERE path=?",source.getCanonicalPath());assertEquals(file.toString(),"indexed",file.getString("state"));
        JSONObject doc=b.store.document(file.getString("document_id"));assertEquals("reference",doc.getString("source_mode"));assertEquals(source.getCanonicalFile(),b.store.source(doc.getString("id"),false));
        assertEquals(hash,LibraryStore.hash(source));assertEquals(before,new File(b.store.root,"sources").list().length);
        assertEquals("failed",b.store.one("SELECT state FROM phone_scan_files WHERE path=?",broken.getCanonicalPath()).getString("state"));
        int tasks=b.store.one("SELECT count(*) n FROM tasks").getInt("n");b.phoneScan.scanRoots(Collections.singletonList(root));while(b.phoneScan.finding)Thread.sleep(100);Thread.sleep(1500);
        assertEquals(tasks,b.store.one("SELECT count(*) n FROM tasks").getInt("n"));
        File moved=new File(root,"Moved notes.pdf");assertTrue(source.renameTo(moved));b.phoneScan.scanRoots(Collections.singletonList(root));while((b.phoneScan.finding||b.phoneScan.pending())&&System.currentTimeMillis()<deadline)Thread.sleep(200);
        assertEquals(moved.getCanonicalFile(),b.store.source(doc.getString("id"),false));
        File duplicate=new File(root,"Copy.pdf");try(InputStream in=new FileInputStream(moved);OutputStream out=new FileOutputStream(duplicate)){NativeTransfer.copy(in,out);}
        b.phoneScan.scanRoots(Collections.singletonList(root));deadline=System.currentTimeMillis()+120000;while((b.phoneScan.finding||b.phoneScan.pending())&&System.currentTimeMillis()<deadline)Thread.sleep(200);
        writePdf(duplicate,"Database systems use relational algebra and SQL queries.");
        b.phoneScan.scanRoots(Collections.singletonList(root));deadline=System.currentTimeMillis()+120000;while((b.phoneScan.finding||b.phoneScan.pending())&&System.currentTimeMillis()<deadline)Thread.sleep(200);
        String newId=b.store.one("SELECT document_id FROM phone_scan_files WHERE path=?",duplicate.getCanonicalPath()).getString("document_id");assertNotEquals(doc.getString("id"),newId);assertEquals(moved.getCanonicalFile(),b.store.source(doc.getString("id"),false));assertEquals(hash,LibraryStore.hash(moved));
        assertFalse(PhoneScan.allowedPath(context,new File(Environment.getExternalStorageDirectory(),"Android/data/another.app/secret.pdf")));
    }
}
