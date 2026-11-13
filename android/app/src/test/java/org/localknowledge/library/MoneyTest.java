package org.localknowledge.library;

import org.junit.Test;
import org.json.*;
import java.math.BigDecimal;
import static org.junit.Assert.*;

public class MoneyTest {
    @Test public void indentedLabelStillReplacesOnlyItsOwnSequentialObservation(){
        JSONArray values=Money.amounts("Invoice\n  Grand Total:\n29000.00\n29074.00",layout(true));
        assertEquals(1,values.length());assertEquals("29074.00",values.optJSONObject(0).optString("value"));
    }
    @Test public void spokenRupeesAndMultiwordPolitenessKeepTheAmount(){
        for(String query:new String[]{"bhai 9777.60 rupaye ka bill dikha do","namaste mujhe 9777.60 rupees wala invoice chahiye"}){
            JSONObject amount=Money.request(Money.expand(query));assertNotNull(query,amount);assertEquals("9777.60",amount.optString("value"));assertEquals("INR",amount.optString("currency"));
        }
        for(String query:new String[]{"6600 se kam ka bill","6600 se jyada wala bill","6600 aur 7700 ke beech ka bill"})
            try{Money.request(Money.expand(query));fail(query);}catch(IllegalArgumentException expected){}
    }
    @Test public void ambiguousTableRowDoesNotEraseSeparateExplicitTotal()throws Exception{
        JSONObject evidence=layout(true);JSONArray words=evidence.optJSONArray("words"),filtered=new JSONArray();
        for(int i=4;i<words.length();i++)filtered.put(words.opt(i));evidence.put("words",filtered);
        JSONArray values=Money.amounts("Invoice\nGrand Total:\n29000.00\n29074.00\nTotal 395850.00",evidence);
        boolean found=false;for(int i=0;i<values.length();i++)found|=values.optJSONObject(i).optString("value").equals("395850.00");assertTrue(found);
    }
    @Test public void hinglishBeforeTaxIsDeterministicAndAlternativesCannotVanish(){
        JSONObject amount=Money.request(Money.expand("tax se pehle 6600 wala bill"));
        assertNotNull(amount);assertEquals("subtotal",amount.optString("field"));assertEquals("6600.00",amount.optString("value"));
        for(String query:new String[]{"total 6600 ya 7700","total ६६०० aur ७७००"})
            try{Money.request(Money.expand(query));fail(query);}catch(IllegalArgumentException expected){}
    }
    @Test public void ordinaryAmountRequestsDoNotNeedModelInterpretation(){
        for(String text:new String[]{"mujhe 6600 wala bill dikhao","6600 ka invoice","show me the invoice for 6600","कुल 6600 वाला बिल"}){
            JSONObject amount=Money.request(Money.expand(text));assertNotNull(text,amount);assertEquals(text,"6600.00",amount.optString("value"));
        }
        assertEquals("subtotal",Money.request(Money.expand("कर से पहले 6600 वाला बिल")).optString("field"));
        assertEquals(BigDecimal.ZERO,Money.tolerance("बिल्कुल 6600 वाला बिल",Json.obj("value","6600.00"),new JSONObject()));
        assertNull(Money.request(Money.expand("Bhagwanti Trading ka 6600 wala bill dikhao")));
    }
    @Test public void unlabelledSecondAmountsDoNotDisappear(){
        for(String text:new String[]{"6600 या 7700 वाला बिल","6600 or 7700 wala bill","कुल 6600 और 7700 वाला बिल"})
            try{Money.request(Money.expand(text));fail(text);}catch(IllegalArgumentException expected){}
    }
    @Test public void hindiBillAmountIsReadWithoutModelTranslation(){
        for(String text:new String[]{"6600 वाला बिल","मुझे 6600 वाला बिल दिखाओ","६६०० वाला बिल","6600 रुपये का बिल","₹6600 वाली इनवॉइस"}){
            JSONObject amount=Money.request(Money.expand(text));assertNotNull(text,amount);
            assertEquals(text,"6600.00",amount.optString("value"));assertEquals("total",amount.optString("field"));
        }
        assertNull(Money.request(Money.expand("बिल नंबर 25 दिखाओ")));
    }
    @Test public void hindiAmountConstraintsAreNotDropped(){
        for(String text:new String[]{"6600 वाला बिल या 7700 वाला बिल","6600 वाला बिल से कम","6600 वाला बिल से ज्यादा"})
            try{Money.request(Money.expand(text));fail(text);}catch(IllegalArgumentException expected){}
    }
    @Test public void westernAndIndianGrouping(){assertEquals(new BigDecimal("136000.00"),Money.decimal("1,36,000"));assertEquals(Money.decimal("136,000.00"),Money.decimal("136000"));}
    @Test public void malformedAmountsNeverReinterpreted(){for(String invalid:new String[]{"13,60","1,3600","-29000","NaN","29000.001"})try{Money.decimal(invalid);fail(invalid);}catch(IllegalArgumentException expected){}}
    @Test public void taxAndLineItemsAreNotSubtotal(){JSONArray values=Money.amounts("Invoice\nWidget 13600.00\nSubtotal\n29280.00\nSGST (2.5%)\n13600.00\nGrand Total: 30680.00\n",new JSONObject());assertEquals(2,values.length());assertEquals("29280.00",values.optJSONObject(0).optString("value"));assertEquals("subtotal",values.optJSONObject(0).optString("field"));}
    @Test public void exactFieldAndCurrency(){JSONObject amount=Money.request("invoice subtotal of INR 13,600.00");assertEquals("subtotal",amount.optString("field"));assertEquals("13600.00",amount.optString("value"));assertEquals("INR",amount.optString("currency"));}
    @Test public void nearbyToleranceKeepsActualValue(){JSONObject amount=Json.obj("field","total","value","29000.00");assertEquals(new BigDecimal("500"),Money.tolerance("total 29000",amount,new JSONObject()));assertEquals(BigDecimal.ZERO,Money.tolerance("total exactly 29000",amount,new JSONObject()));assertEquals(BigDecimal.ZERO,Money.tolerance("total 29000",amount,Json.obj("mode","exact")));assertEquals(new BigDecimal("500"),Money.tolerance("total 100000",Json.obj("value","100000"),new JSONObject()));}
    @Test public void shorthandFindsNearbyInvoiceAmount(){String query=Money.expand("17000 inv");JSONObject amount=Money.request(query);assertNotNull(amount);assertEquals("total",amount.optString("field"));assertEquals("17000.00",amount.optString("value"));assertTrue(Money.tolerance(query,amount,new JSONObject()).compareTo(new BigDecimal("200"))>=0);assertEquals(BigDecimal.ZERO,Money.tolerance("exactly 17000 invoice",amount,new JSONObject()));}
    JSONObject layout(boolean currentRight){return Json.obj("words",Json.arr(Json.arr(230,80,275,92,currentRight?"Previous":"Current",0,0,0),Json.arr(280,80,320,92,"Invoice",0,0,1),Json.arr(410,80,455,92,currentRight?"Current":"Previous",0,0,2),Json.arr(460,80,500,92,"Invoice",0,0,3),Json.arr(60,310,100,322,"Grand",0,1,0),Json.arr(105,310,145,322,"Total:",0,1,1),Json.arr(230,310,295,322,currentRight?"29000.00":"29074.00",0,1,2),Json.arr(410,310,475,322,currentRight?"29074.00":"29000.00",0,1,3)));}
    @Test public void currentColumnSurvivesHeaderSwap(){for(boolean right:new boolean[]{false,true}){String text="Invoice\nGrand Total:\n"+(right?"29000.00\n29074.00":"29074.00\n29000.00");JSONArray values=Money.amounts(text,layout(right));assertEquals(1,values.length());assertEquals("29074.00",values.optJSONObject(0).optString("value"));assertEquals("current_column",values.optJSONObject(0).optString("association"));}}
    @Test public void unknownColumnHeadersStayUnresolved()throws Exception{JSONObject evidence=layout(true);JSONArray words=evidence.getJSONArray("words"),filtered=new JSONArray();for(int i=4;i<words.length();i++)filtered.put(words.get(i));evidence.put("words",filtered);JSONArray values=Money.amounts("Invoice\nGrand Total:\n29000.00\n29074.00",evidence);assertEquals(2,values.length());for(int i=0;i<2;i++)assertEquals("unresolved",values.optJSONObject(i).optString("association"));}
    @Test public void subtotalDoesNotMatchTotalQuery(){assertEquals("total",Money.request("total 29000").optString("field"));assertEquals("subtotal",Money.request("subtotal 29000").optString("field"));}
    @Test public void observedOcrLabelVariantIsExplicit()throws Exception{JSONObject evidence=layout(true);evidence.getJSONArray("words").getJSONArray(3).put(4,"lnvoice");JSONObject amount=Money.amounts("Invoice\nGrand Total:\n29000.00\n29074.00",evidence).getJSONObject(0);assertEquals("29074.00",amount.getString("value"));assertTrue(amount.getBoolean("label_variant_used"));assertEquals("lnvoice",evidence.getJSONArray("words").getJSONArray(3).getString(4));}
    @Test public void datesAndIdentifiersAreNotMoney(){assertFalse(Money.candidate("invoice INV-13800"));assertFalse(Money.candidate("sales to Bhagwanti Trading on Sept 25 2026"));assertFalse(Money.candidate("25 September 2026 ka invoice dikhao"));assertTrue(Money.candidate("hello mere bhai muje 13800 ka invoice dikha"));assertTrue(Money.candidate("13800 ka bill on 25 September 2026"));}
    @Test public void constraintsCannotDisappear(){for(String text:new String[]{"total under 29000","subtotal 13600 and total 14280","total INR 29000 USD"})try{Money.request(text);fail(text);}catch(IllegalArgumentException expected){}}
    @Test public void explicitMagnitudeIsExpanded(){assertEquals("bhai 29000 ka invoice",Money.expand("bhai 29k ka invoice"));assertEquals("bill worth 150000.0",Money.expand("bill worth 1.5 lakh"));assertEquals("lecture 29k",Money.expand("lecture 29k"));}
    @Test public void identicalAmountsKeepDistinctPhysicalAndTextLocations()throws Exception{JSONObject evidence=layout(true);evidence.getJSONArray("words").getJSONArray(7).put(4,"29000.00");String text="Invoice\nGrand Total:\n29000.00\n29000.00";JSONObject amount=Money.amounts(text,evidence).getJSONObject(0);assertEquals(text.lastIndexOf("29000.00"),amount.getInt("start"));assertEquals(410,amount.getJSONArray("bbox").getDouble(0),.01);}
}
