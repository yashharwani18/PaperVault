package org.localknowledge.library;
import org.junit.Test;
import static org.junit.Assert.*;
public class BillSearchIntentTest {
 @Test public void generalSalesTopicsDoNotBecomeSavedBillFilters(){
  assertFalse(BillSearchIntent.context("Show the sales register listing sales transactions",false,""));
  assertFalse(BillSearchIntent.context("sales register September 2026",false,""));
  assertFalse(BillSearchIntent.context("purchase accounting notes",false,""));
  assertTrue(BillSearchIntent.context("sales invoices",false,""));
  assertTrue(BillSearchIntent.context("sales to Bhagwanti",false,""));
  assertTrue(BillSearchIntent.context("sales",true,""));
  assertTrue(BillSearchIntent.context("Bhagwanti sales",false,"Bhagwanti"));
 }
}
