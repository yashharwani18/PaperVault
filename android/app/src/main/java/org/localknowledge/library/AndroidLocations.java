package org.localknowledge.library;
import android.content.Context;
import android.net.Uri;
import android.os.Environment;
import android.provider.DocumentsContract;
import java.io.*;

/** Resolve a picker choice only to a canonical eligible shared-storage path. */
final class AndroidLocations {
    static File resolve(Context context,Uri uri,boolean tree)throws IOException {
        if(uri==null||!"content".equals(uri.getScheme()))throw unsupported();
        String authority=uri.getAuthority();
        if("com.android.externalstorage.documents".equals(authority))try{
            String id=tree?DocumentsContract.getTreeDocumentId(uri):DocumentsContract.getDocumentId(uri);String[] parts=id.split(":",2);if(parts.length!=2)throw unsupported();
            for(File root:PhoneScan.roots(context))if((parts[0].equalsIgnoreCase("primary")&&root.equals(Environment.getExternalStorageDirectory().getCanonicalFile()))||root.getName().equalsIgnoreCase(parts[0])){
                File file=new File(root,parts[1]).getCanonicalFile();if(file.toPath().startsWith(root.toPath())&&PhoneScan.allowedPath(context,file))return file;
            }
        }catch(IllegalArgumentException ignored){}
        if(!tree)try(var cursor=context.getContentResolver().query(uri,new String[]{"_data"},null,null,null)){
            if(cursor!=null&&cursor.moveToFirst()){String value=cursor.getString(0);if(value!=null){File file=new File(value).getCanonicalFile();if(PhoneScan.allowedPath(context,file))return file;}}
        }catch(RuntimeException ignored){}
        throw unsupported();
    }
    static IOException unsupported(){return new IOException("Choose a folder or PDF under Internal storage or an SD card.");}
}
