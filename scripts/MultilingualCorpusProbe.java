package org.localknowledge.library;
import java.nio.file.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import org.json.*;

/** Host-only full-corpus source matching using production parsers, without model substitution. */
public final class MultilingualCorpusProbe {
 public static void main(String[] args)throws Exception {
  List<JSONObject> pages=new ArrayList<>();Map<String,Set<String>> amounts=new HashMap<>();
  for(String line:Files.readAllLines(Path.of(args[0]),StandardCharsets.UTF_8)){
   JSONObject p=new JSONObject(line);pages.add(p);String text=p.getString("text"),key=p.getString("document_id")+":"+p.getInt("page_number");
   if(!text.matches("(?is).*\\b(invoice|bill of supply|sales bill|purchase bill|cash memo)\\b.*"))continue;
   JSONObject evidence=new JSONObject(p.optString("evidence","{}"));
   JSONArray observations=Money.amounts(text,evidence);
   for(int i=0;i<observations.length();i++){
    // Pre-index source observations once, not once per language paraphrase.
    JSONObject a=observations.getJSONObject(i);
    amounts.computeIfAbsent(a.getString("field")+":"+a.getString("value"),k->new TreeSet<>()).add(key);
   }
  }
  Map<String,Set<String>> invoiceCache=new HashMap<>();
  for(String line:Files.readAllLines(Path.of(args[1]),StandardCharsets.UTF_8)){
   JSONObject c=new JSONObject(line),out=new JSONObject().put("id",c.getString("id"));String query=c.getString("query");
   try{
    String invoice=InvoiceNumbers.query(query),expanded=Money.expand(query);JSONObject amount=invoice==null?Money.request(expanded):null;
    out.put("invoice",invoice==null?JSONObject.NULL:invoice).put("amount",amount==null?JSONObject.NULL:amount);
    Set<String> found=new TreeSet<>();
    if(invoice!=null){
     if(!invoiceCache.containsKey(invoice)){
      Set<String> hits=new TreeSet<>();for(JSONObject p:pages)if(InvoiceNumbers.matches(invoice,"",p.getString("text")))hits.add(p.getString("document_id")+":"+p.getInt("page_number"));invoiceCache.put(invoice,hits);
     }found=invoiceCache.get(invoice);
    }else if(amount!=null)found=amounts.getOrDefault(amount.getString("field")+":"+amount.getString("value"),Collections.emptySet());
    out.put("pages",new JSONArray(found));
   }catch(Exception error){out.put("error",error.toString());}
   System.out.println(out);
  }
 }
}
