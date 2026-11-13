package org.localknowledge.library;
import org.junit.Test;
import static org.junit.Assert.*;
public class LiteralSearchTest {
 @Test public void matchesWholeTermsAndPunctuationAcrossSubjects(){
  assertTrue(LiteralSearch.matches("inv25","Invoice Number INV-inv25 customer"));
  assertFalse(LiteralSearch.matches("inv25","Invoice Number INV-inv125 customer"));
  assertTrue(LiteralSearch.matches("shortest-path", "Shortest path algorithms"));
  assertTrue(LiteralSearch.matches("Fourier transform", "FOURIER transform notes"));
  assertFalse(LiteralSearch.matches("cat", "education"));
  assertFalse(LiteralSearch.matches("!!!", "anything"));
 }
}
