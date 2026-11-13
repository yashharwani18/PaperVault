package org.localknowledge.library;
import org.junit.Test;
import org.kxml2.io.KXmlParser;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;
import java.util.zip.*;
import static org.junit.Assert.*;
public class OfficeTextDocumentTest {
 private File archive(Map<String,String> entries)throws Exception{
  File file=Files.createTempFile("khoj-office-",".zip").toFile();try(ZipOutputStream zip=new ZipOutputStream(new FileOutputStream(file))){for(Map.Entry<String,String> entry:entries.entrySet()){zip.putNextEntry(new ZipEntry(entry.getKey()));zip.write(entry.getValue().getBytes(StandardCharsets.UTF_8));zip.closeEntry();}}return file;
 }
 @Test public void docxExtractsTextAndParagraphsWithoutVisualContent()throws Exception{
  File file=archive(Map.of("word/document.xml","<w:document xmlns:w='http://schemas.openxmlformats.org/wordprocessingml/2006/main'><w:body><w:p><w:r><w:t>ગુજરાતી &amp; Hindi</w:t></w:r></w:p><w:p><w:r><w:t>Second paragraph</w:t></w:r></w:p></w:body></w:document>"));
  try{List<OfficeTextDocument.Section> sections=OfficeTextDocument.read(file,"docx",KXmlParser::new);String text=sections.get(0).text;assertTrue(text.contains("ગુજરાતી & Hindi"));assertTrue(text.contains("Second paragraph"));assertTrue(text.contains("\n"));}finally{file.delete();}
 }
 @Test public void workbookUsesSheetNamesCellAddressesAndCachedValues()throws Exception{
  Map<String,String> entries=new LinkedHashMap<>();entries.put("xl/workbook.xml","<workbook xmlns='http://schemas.openxmlformats.org/spreadsheetml/2006/main' xmlns:r='http://schemas.openxmlformats.org/officeDocument/2006/relationships'><sheets><sheet name='Revenue' sheetId='1' r:id='rId1'/></sheets></workbook>");
  entries.put("xl/_rels/workbook.xml.rels","<Relationships xmlns='http://schemas.openxmlformats.org/package/2006/relationships'><Relationship Id='rId1' Target='worksheets/sheet1.xml' Type='http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet'/></Relationships>");
  entries.put("xl/sharedStrings.xml","<sst xmlns='http://schemas.openxmlformats.org/spreadsheetml/2006/main'><si><t>Acme</t></si></sst>");
  entries.put("xl/worksheets/sheet1.xml","<worksheet xmlns='http://schemas.openxmlformats.org/spreadsheetml/2006/main'><sheetData><row r='7'><c r='A7' t='s'><v>0</v></c><c r='C7'><f>1+2</f><v>3</v></c></row></sheetData></worksheet>");
  File file=archive(entries);try{List<OfficeTextDocument.Section> sections=OfficeTextDocument.read(file,"xlsx",KXmlParser::new);assertEquals(1,sections.size());OfficeTextDocument.Section section=sections.get(0);assertEquals("Revenue",section.sheet);assertEquals(7,section.rowStart);assertTrue(section.text.contains("A7: Acme"));assertTrue(section.text.contains("C7: 3"));}finally{file.delete();}
 }
 @Test public void rejectsDoctypeAndUnsafeRelationship()throws Exception{
  File xml=archive(Map.of("word/document.xml","<!DOCTYPE document [<!ENTITY x 'invented'>]><document xmlns='http://schemas.openxmlformats.org/wordprocessingml/2006/main'><p><t>&x;</t></p></document>"));
  try{try{OfficeTextDocument.read(xml,"docx",KXmlParser::new);fail();}catch(IOException expected){}}finally{xml.delete();}
 }
 @Test public void workbookReportsOnlyReliableRowRanges() throws Exception {
  Map<String,String> entries=new LinkedHashMap<>();
  entries.put("xl/workbook.xml","<workbook xmlns='http://schemas.openxmlformats.org/spreadsheetml/2006/main' xmlns:r='http://schemas.openxmlformats.org/officeDocument/2006/relationships'><sheets><sheet name='Data' sheetId='1' r:id='rId1'/></sheets></workbook>");
  entries.put("xl/_rels/workbook.xml.rels","<Relationships><Relationship Id='rId1' Target='worksheets/sheet1.xml' Type='x/worksheet'/></Relationships>");
  entries.put("xl/worksheets/sheet1.xml","<worksheet xmlns='http://schemas.openxmlformats.org/spreadsheetml/2006/main'><sheetData><row r='9'><c r='A9'><v>9</v></c></row><row r='2'><c r='A2'><v>2</v></c></row></sheetData></worksheet>");
  File file=archive(entries);try {OfficeTextDocument.Section section=OfficeTextDocument.read(file,"xlsx",KXmlParser::new).get(0);assertEquals(2,section.rowStart);assertEquals(9,section.rowEnd);} finally {file.delete();}
  entries.put("xl/worksheets/sheet1.xml","<worksheet xmlns='http://schemas.openxmlformats.org/spreadsheetml/2006/main'><sheetData><row><c><v>unknown</v></c></row><row r='2'><c r='A2'><v>2</v></c></row></sheetData></worksheet>");
  file=archive(entries);try {OfficeTextDocument.Section section=OfficeTextDocument.read(file,"xlsx",KXmlParser::new).get(0);assertEquals(0,section.rowStart);assertEquals(0,section.rowEnd);} finally {file.delete();}
 }

 @Test public void workbookRejectsExternalAndEscapingWorksheetPaths()throws Exception {
  for(String relation:new String[]{"Target='../secret.xml'", "Target='https://example.org/sheet.xml' TargetMode='External'", "Target='worksheets/../secret.xml'"}) {
   Map<String,String> entries=new LinkedHashMap<>();entries.put("xl/workbook.xml","<workbook xmlns='http://schemas.openxmlformats.org/spreadsheetml/2006/main' xmlns:r='http://schemas.openxmlformats.org/officeDocument/2006/relationships'><sheets><sheet name='Data' sheetId='1' r:id='rId1'/></sheets></workbook>");
   entries.put("xl/_rels/workbook.xml.rels","<Relationships><Relationship Id='rId1' "+relation+" Type='x/worksheet'/></Relationships>");
   File file=archive(entries);try {try {OfficeTextDocument.read(file,"xlsx",KXmlParser::new);fail("unsafe worksheet relation accepted");} catch(IOException expected) {}} finally {file.delete();}
  }
 }

}
