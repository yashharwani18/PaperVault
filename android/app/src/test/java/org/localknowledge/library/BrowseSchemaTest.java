package org.localknowledge.library;
import org.junit.Test;
import java.util.*;
import static org.junit.Assert.*;
public class BrowseSchemaTest {
 @Test public void oldBackupsMayOmitOnlyKnownBrowseIndexes(){
  Map<String,String> trusted=new HashMap<>();trusted.put("documents","CREATE TABLE documents(id TEXT)");trusted.put("documents_browse_updated","CREATE INDEX documents_browse_updated ON documents(updated_at DESC,id)");
  Map<String,String> old=new HashMap<>();old.put("documents",trusted.get("documents"));
  assertTrue(NativeTransfer.compatibleSchema(trusted,old));
  old.put("documents_browse_updated","CREATE INDEX documents_browse_updated ON documents(id)");assertFalse(NativeTransfer.compatibleSchema(trusted,old));
  old.remove("documents_browse_updated");old.put("evil","CREATE TRIGGER evil AFTER INSERT ON documents BEGIN SELECT 1; END");assertFalse(NativeTransfer.compatibleSchema(trusted,old));
  old.remove("evil");old.remove("documents");assertFalse(NativeTransfer.compatibleSchema(trusted,old));
 }
}
