package org.localknowledge.library;
import android.app.Activity;
import android.content.*;
import android.net.Uri;
import android.os.Bundle;
import java.util.*;

public class ShareSenderActivity extends Activity {
    @Override public void onCreate(Bundle state){super.onCreate(state);String run=getIntent().getStringExtra("run");Uri one=Uri.parse("content://org.localknowledge.library.test.share/grant-"+run+"-one.pdf"),two=Uri.parse("content://org.localknowledge.library.test.share/grant-"+run+"-two.pdf");
        Intent share=new Intent(Intent.ACTION_SEND_MULTIPLE).setClassName("org.localknowledge.library","org.localknowledge.library.MainActivity").setType("application/pdf").addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION|Intent.FLAG_ACTIVITY_NEW_TASK);
        share.putParcelableArrayListExtra(Intent.EXTRA_STREAM,new ArrayList<>(Arrays.asList(one,two)));ClipData clip=new ClipData("Test PDFs",new String[]{"application/pdf"},new ClipData.Item(one));clip.addItem(new ClipData.Item(two));share.setClipData(clip);startActivity(share);finish();}
}
