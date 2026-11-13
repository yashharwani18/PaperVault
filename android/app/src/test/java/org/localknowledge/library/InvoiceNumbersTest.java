package org.localknowledge.library;
import org.junit.Test;
import static org.junit.Assert.*;
public class InvoiceNumbersTest {
 @Test public void multilingualRequestsSupportNaturalWordOrderAndGreetings(){
  for(String query:new String[]{"मुझे २५ नंबर वाला बिल चाहिए","25 नंबर का बिल दिखाओ","इनवॉइस संख्या 25 खोजो","कृपया बिल क्रमांक 25 दिखाइए","नमस्ते, मुझे बिल नंबर 25 दिखा दो","mujhe invoice number 25 dikhao","25 number ka bill dikhao","bhai inv25 dikha do","bill no 25 chahiye","namaste mujhe invoice no 25 dikhana","mera bill number 25 kholo","please 25 number wala invoice nikaalo"})
   assertEquals(query,"25",InvoiceNumbers.query(query));
  assertEquals("INV-148",InvoiceNumbers.query("invoice number inv -148"));
  assertEquals("INV-177",InvoiceNumbers.query("बिल नंबर INV 177 दिखाओ"));
  for(String query:new String[]{"25 ka bill","6600 रुपये वाला बिल","25 number ka bill aur 125 number ka bill","invoice 25 from yesterday","25 September 2026 ka bill"})assertNull(query,InvoiceNumbers.query(query));
 }
 @Test public void ordinaryWordsAndFieldRequestsAreNotInvoiceIdentifiers(){
  for(String query:new String[]{"inventory","investment","billing","invoices","invoice","bill","show invoices","find inventory","invoice total","invoice date","invoice amount","invoice details"})
   assertNull(query,InvoiceNumbers.query(query));
 }
 @Test public void underscoreIdentifiersAreNotTruncated(){
  assertEquals("AT_65",InvoiceNumbers.query("invoice number AT_65"));
  assertTrue(InvoiceNumbers.matches("AT_65","","Invoice No. AT_65\nTotal 6600"));
  assertFalse(InvoiceNumbers.matches("AT","","Invoice No. AT_65\nTotal 6600"));
  assertFalse(InvoiceNumbers.matches("AT_65","","Invoice No. AT_650\nTotal 6600"));
 }
 @Test public void identifiersSurviveLabelAndPrefixLineWrapping(){
  assertTrue(InvoiceNumbers.matches("120","","Invoice Number\nINV- 120\nsatguru"));
  assertTrue(InvoiceNumbers.matches("36","","Invoice\nNumber\nINV 36 handloom house"));
  assertFalse(InvoiceNumbers.matches("12","","Invoice Number\nINV- 120\nsatguru"));
 }
 @Test public void conversationalRequestsKeepTheInvoiceIdentifier(){
  for(String query:new String[]{"show me the invoice 25","Show me invoice no. 25 please","find invoice number INV-25","invoice 25 dikhao","मुझे इनवॉइस नंबर २५ दिखाओ","बिल नंबर 25 दिखाओ"})
   assertEquals(query,query.contains("INV-25")?"INV-25":"25",InvoiceNumbers.query(query));
  for(String query:new String[]{"6600 वाला बिल","show me the invoice for 6600","show me invoice total 6600","invoice 25 and invoice 125","show me invoice 25 from yesterday"})
   assertNull(query,InvoiceNumbers.query(query));
 }
 @Test public void understandsNumberQueriesWithoutConfusingAmounts(){
  assertEquals("25", InvoiceNumbers.query("inv25"));
  assertEquals("25", InvoiceNumbers.query("invoice number 25"));
  assertEquals("25", InvoiceNumbers.query("invoice no. 25"));
  assertNull(InvoiceNumbers.query("6.6k wala invoice"));
 }
 @Test public void findsExactIdentifiersInSavedFieldsAndPageText(){
  assertTrue(InvoiceNumbers.matches("25", "INV-25", ""));
  assertTrue(InvoiceNumbers.matches("INV-25", "", "Invoice No: 25"));
  assertFalse(InvoiceNumbers.matches("INV-25", "", "Invoice No: ABC-25"));
  assertTrue(InvoiceNumbers.matches("25", "INV-inv25 customer", "Invoice Number INV-inv25 customer"));
  assertFalse(InvoiceNumbers.matches("25", "", "Invoice Number INV-inv125 customer"));
  assertTrue(InvoiceNumbers.matches("25", "", "TAX INVOICE\nInvoice No: 25\nTotal 6600"));
  assertFalse(InvoiceNumbers.matches("25", "", "Invoice No: 125\nTotal 25"));
  assertFalse(InvoiceNumbers.matches("25", "", "Invoice\nTotal: 25"));
 }
}
