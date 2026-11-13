package org.localknowledge.library;
import android.content.*;
import android.database.*;
import android.graphics.Paint;
import android.graphics.pdf.PdfDocument;
import android.net.Uri;
import android.os.ParcelFileDescriptor;
import android.provider.OpenableColumns;
import java.io.*;

/** Separate test APK provider: target app must receive genuine temporary URI grants. */
public class ShareGrantProvider extends ContentProvider {
    public boolean onCreate(){return true;}
    public String getType(Uri uri){return "application/pdf";}
    public Cursor query(Uri uri,String[] projection,String selection,String[] args,String sort){String[] cols=projection==null?new String[]{OpenableColumns.DISPLAY_NAME,OpenableColumns.SIZE}:projection;MatrixCursor result=new MatrixCursor(cols);Object[] row=new Object[cols.length];for(int i=0;i<cols.length;i++)row[i]=cols[i].equals(OpenableColumns.DISPLAY_NAME)?uri.getLastPathSegment():null;result.addRow(row);return result;}
    public ParcelFileDescriptor openFile(Uri uri,String mode)throws FileNotFoundException {
        String name=uri.getLastPathSegment();if(!"r".equals(mode)||name==null||!name.matches("grant-[a-zA-Z0-9-]+\\.pdf"))throw new FileNotFoundException();
        try{Thread.sleep(1200);File file=new File(getContext().getCacheDir(),name);if(!file.isFile()){PdfDocument pdf=new PdfDocument();try{PdfDocument.Page page=pdf.startPage(new PdfDocument.PageInfo.Builder(300,400,1).create());Paint p=new Paint();p.setTextSize(12);page.getCanvas().drawText(name,15,40,p);pdf.finishPage(page);try(OutputStream out=new FileOutputStream(file)){pdf.writeTo(out);}}finally{pdf.close();}}return ParcelFileDescriptor.open(file,ParcelFileDescriptor.MODE_READ_ONLY);}catch(Exception e){throw new FileNotFoundException("Fixture unavailable");}
    }
    public Uri insert(Uri uri,ContentValues values){throw new UnsupportedOperationException();}public int delete(Uri uri,String where,String[] args){throw new UnsupportedOperationException();}public int update(Uri uri,ContentValues values,String where,String[] args){throw new UnsupportedOperationException();}
}
