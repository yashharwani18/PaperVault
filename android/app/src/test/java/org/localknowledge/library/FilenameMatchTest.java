package org.localknowledge.library;
import org.junit.Test;
import static org.junit.Assert.*;
public class FilenameMatchTest {
 @Test public void comparesActualNameAndStemWithUnicodeAndPunctuation(){
  assertTrue(FilenameMatch.exact("Operating  Systems Unit 3", "Operating Systems Unit 3.pdf"));
  assertTrue(FilenameMatch.exact(" operating-systems unit 3.PDF ", "Operating Systems Unit 3.pdf"));
  assertTrue(FilenameMatch.exact("Cafe\u0301", "Café.pdf"));
  assertFalse(FilenameMatch.exact("Lecture 2", "Lecture 20.pdf"));
  assertFalse(FilenameMatch.exact("  ", "untitled.pdf"));
 }
}
