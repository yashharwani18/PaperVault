package org.localknowledge.library;
import org.junit.Test;
import static org.junit.Assert.*;
public class ScannedModifiedTest {
 @Test public void usesOnlyValidRecordedSourceTimestamp(){
  assertNull(PhoneScan.observedModifiedAt("123:0"));assertNull(PhoneScan.observedModifiedAt("bad"));
  assertTrue(PhoneScan.observedModifiedAt("123:1704067200000").startsWith("2024-01-01T00:00:00"));
 }
}
