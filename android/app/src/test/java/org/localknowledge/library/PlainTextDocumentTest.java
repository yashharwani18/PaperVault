package org.localknowledge.library;
import java.nio.charset.*;
import java.nio.file.*;
import java.io.*;
import java.util.*;
import org.junit.Test;
import static org.junit.Assert.*;
public class PlainTextDocumentTest {
 @Test public void preservesUnicodeAcrossBoundedSections()throws Exception{
  String source="Gujarati: ગુજરાતી\nHindi: हिंदी\n"+"text 😀 ".repeat(5000);
  Path file=Files.createTempFile("khoj-text-",".txt");try{Files.write(file,source.getBytes(StandardCharsets.UTF_8));List<String> sections=PlainTextDocument.read(file.toFile());assertTrue(sections.size()>1);assertEquals(source,String.join("",sections));for(String part:sections)assertTrue(part.length()<=PlainTextDocument.SECTION_CHARS);}finally{Files.deleteIfExists(file);}
 }
 @Test public void limitsFormatsToSupportedPlainText(){assertTrue(PlainTextDocument.supports("TXT"));assertTrue(PlainTextDocument.supports("csv"));assertFalse(PlainTextDocument.supports("docx"));}
 @Test public void rejectsBinaryAndOversizedTextWithoutTruncation()throws Exception{
  Path file=Files.createTempFile("khoj-limit-",".txt");try{Files.write(file,new byte[]{'a',0,'b'});try{PlainTextDocument.read(file.toFile());fail();}catch(IOException expected){}try(RandomAccessFile out=new RandomAccessFile(file.toFile(),"rw")){out.setLength(PlainTextDocument.MAX_BYTES+1L);}try{PlainTextDocument.read(file.toFile());fail();}catch(IOException expected){}}finally{Files.deleteIfExists(file);}
 }
 @Test public void supportsUnicodeBomAndRejectsMalformedBytes()throws Exception{
  Path file=Files.createTempFile("khoj-text-",".txt");try{byte[] text="Hello हिंदी".getBytes(StandardCharsets.UTF_16LE);byte[] withBom=new byte[text.length+2];withBom[0]=(byte)0xff;withBom[1]=(byte)0xfe;System.arraycopy(text,0,withBom,2,text.length);Files.write(file,withBom);assertEquals("Hello हिंदी",String.join("",PlainTextDocument.read(file.toFile())));Files.write(file,new byte[]{(byte)0xc3,0x28});try{PlainTextDocument.read(file.toFile());fail();}catch(IOException expected){}}finally{Files.deleteIfExists(file);}
 }
}
