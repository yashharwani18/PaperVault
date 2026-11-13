package org.localknowledge.library;

import org.json.*;
import java.math.BigDecimal;
import java.util.*;
import java.util.regex.*;

final class Money {
    static final String NUMBER="(?<![\\w.,+\\-])\\d[\\d,]*(?:\\.\\d+)?(?![\\w,]|\\.\\d)";
    static final String LABEL="(?:sub[ \\t-]*total|grand[ \\t]+total|invoice[ \\t]+total|total[ \\t]+amount|net[ \\t]+payable|total)";
    static final Pattern SOURCE=Pattern.compile("(?im)^[ \\t]*("+LABEL+")\\b[ \\t]*(?:\\((INR|USD|EUR|GBP|Rs\\.?)\\))?[ \\t]*[:=]?[ \\t]*\\n?[ \\t]*(INR|USD|EUR|GBP|Rs\\.?|₹|\\$|€|£)?\\s*("+NUMBER+")");
    static BigDecimal decimal(String text) {
        if(!text.matches("(?:\\d+|\\d{1,3}(?:,\\d{3})+|\\d{1,2}(?:,\\d{2})*,\\d{3})(?:\\.\\d{1,2})?"))throw new IllegalArgumentException("Use a valid amount such as 29,074.00");
        return new BigDecimal(text.replace(",","")).setScale(2);
    }
    static String currency(String raw) {
        if(raw==null)return null;
        switch(raw.toUpperCase(Locale.ROOT).replace(".","")){case "₹":case "RS":return "INR";case "$":return "USD";case "€":return "EUR";case "£":return "GBP";default:return raw.toUpperCase(Locale.ROOT);}
    }
    static JSONArray amounts(String text,JSONObject evidence) {
        JSONArray result=new JSONArray();Matcher match=SOURCE.matcher(text);
        while(match.find())try{result.put(Json.obj("field",match.group(1).toLowerCase(Locale.ROOT).startsWith("sub")?"subtotal":"total","value",decimal(match.group(4)).toPlainString(),
            "currency",currency(match.group(3)!=null?match.group(3):match.group(2)),"evidence",match.group(),"start",match.start(),"end",match.end(),"association","label_sequence"));}catch(IllegalArgumentException ignored){}
        JSONArray words=evidence.optJSONArray("words");if(words==null||evidence.optInt("rotation")!=0||evidence.optBoolean("non_horizontal_text"))return result;
        List<JSONArray> all=new ArrayList<>();Map<JSONArray,Integer> offsets=new IdentityHashMap<>();int cursor=0;
        for(int i=0;i<words.length();i++){JSONArray word=words.optJSONArray(i);all.add(word);String literal=word.optString(4);int at=text.indexOf(literal,cursor);if(at<0)at=text.indexOf(literal);if(at>=0){offsets.put(word,at);cursor=at+literal.length();}}
        List<List<JSONArray>> rows=new ArrayList<>();all.sort(Comparator.comparingDouble(w->w.optDouble(1)));
        for(JSONArray word:all){List<JSONArray> row=null;for(List<JSONArray> old:rows)if(Math.abs(old.get(0).optDouble(1)-word.optDouble(1))<4){row=old;break;}if(row==null){row=new ArrayList<>();rows.add(row);}row.add(word);}
        List<double[]> headers=new ArrayList<>();
        for(List<JSONArray> row:rows){row.sort(Comparator.comparingDouble(w->w.optDouble(0)));for(int i=0;i+1<row.size();i++){
            String first=row.get(i).optString(4).toLowerCase(Locale.ROOT);
            String second=row.get(i+1).optString(4);
            // Observed ML Kit header spelling, retained as an explicit label cue.
            // This never edits source text or creates digit alternatives.
            if((first.equals("current")||first.equals("previous"))&&second.matches("(?i)[il]nvoice"))headers.add(new double[]{first.equals("current")?1:0,(row.get(i).optDouble(0)+row.get(i+1).optDouble(2))/2,row.get(i).optDouble(1),second.equalsIgnoreCase("invoice")?0:1});
        }}
        for(List<JSONArray> row:rows){StringBuilder joined=new StringBuilder();for(JSONArray word:row)joined.append(word.optString(4)).append(' ');
            Matcher label=Pattern.compile("(?i)^\\s*("+LABEL+")\\b").matcher(joined);if(!label.find())continue;
            List<JSONArray> values=new ArrayList<>();for(JSONArray word:row)try{decimal(word.optString(4));values.add(word);}catch(IllegalArgumentException ignored){}
            if(values.size()<2)continue;
            String field=label.group(1).toLowerCase(Locale.ROOT).startsWith("sub")?"subtotal":"total";
            int rowStart=Integer.MAX_VALUE,rowEnd=-1;
            for(JSONArray word:row){int at=offsets.getOrDefault(word,-1);if(at>=0){rowStart=Math.min(rowStart,at);rowEnd=Math.max(rowEnd,at+word.optString(4).length());}}
            // A multi-column row can supersede its own sequential reading, but
            // must not erase an independent explicit total elsewhere on the page.
            JSONArray retained=new JSONArray();for(int i=0;i<result.length();i++){JSONObject old=result.optJSONObject(i);if(!old.optString("field").equals(field)||old.optInt("end")<=rowStart||old.optInt("start")>=rowEnd)retained.put(old);}result=retained;
            Integer current=null,previous=null;int currentCount=0,previousCount=0;
            for(double[] header:headers){if(header[2]>=row.get(0).optDouble(1))continue;int index=0;double best=Double.MAX_VALUE;
                for(int i=0;i<values.size();i++){double distance=Math.abs((values.get(i).optDouble(0)+values.get(i).optDouble(2))/2-header[1]);if(distance<best){best=distance;index=i;}}
                if(header[0]==1){current=index;currentCount++;}else{previous=index;previousCount++;}}
            boolean resolved=currentCount==1&&previousCount==1&&!current.equals(previous);
            Set<String> units=new HashSet<>();Matcher unit=Pattern.compile("(?i)\\b(?:INR|USD|EUR|GBP|Rs\\.?)\\b|₹|\\$|€|£").matcher(joined);while(unit.find())units.add(currency(unit.group()));
            for(int i=0;i<values.size();i++){if(resolved&&i!=current)continue;JSONArray word=values.get(i);String literal=word.optString(4);int start=offsets.getOrDefault(word,-1);if(start<0)continue;
                result.put(Json.obj("field",field,"value",decimal(literal).toPlainString(),"currency",units.size()==1?units.iterator().next():null,"evidence",literal,"start",start,"end",start+literal.length(),
                    "bbox",Json.arr(word.optDouble(0),word.optDouble(1),word.optDouble(2),word.optDouble(3)),"association",resolved?"current_column":"unresolved","label_variant_used",headers.stream().anyMatch(h->h[3]==1)));}
        }
        return result;
    }
    static JSONObject request(String query) {
        if(query.matches("(?is).*(?:\\b(invoice|bill|bil|total|subtotal)\\b|बिल|इनवॉइस|कुल).*")&&Pattern.compile(NUMBER).matcher(query).find()&&Pattern.compile("(?i)\\b(?:under|over|between|above|below|zyada|jyada|kam|beech)\\b|[<>]|(?<![\\p{L}\\p{M}])(?:कम|ज्यादा|ज़्यादा|अधिक|नीचे|ऊपर|बीच)(?![\\p{L}\\p{M}])").matcher(query).find())throw new IllegalArgumentException("Range comparisons need an explicit supported filter. Search one amount.");
        if(query.matches("(?is).*(?:\\b(?:invoice|bill|"+LABEL+")\\b|बिल|इनवॉइस|कुल|कर से पहले).*")&&Pattern.compile("(?i)"+NUMBER+"\\s*(?:or|and|ya|aur|या|और)\\s*"+NUMBER).matcher(query).find())throw new IllegalArgumentException("Search one field and amount at a time.");
        query=query.replaceAll("(?i)\\b(?:tax\\s+se\\s+pehle|before\\s+tax)\\b","subtotal");
        query=query.replaceAll("(?<![\\p{L}\\p{M}])(?:कर\\s+से\\s+पहले|उपकुल|सबटोटल)(?![\\p{L}\\p{M}])","subtotal")
            .replaceAll("(?<![\\p{L}\\p{M}])(?:कुल(?:\\s+राशि)?|टोटल)(?![\\p{L}\\p{M}])","total");
        // Hindi amount phrases carry the same explicit total cue as "6600 wala bill".
        // Rewrite only the query cue; amounts in source documents stay untouched.
        Matcher hindi=Pattern.compile("("+NUMBER+")\\s*(रुपये|रुपए|रुपयों)?\\s*(?:वाला|वाली|वाले|का|की|के)\\s*(?:बिल|इनवॉइस|इनवोइस)(?![\\p{L}\\p{M}])").matcher(query);
        StringBuffer normalized=new StringBuffer();
        while(hindi.find()){
            boolean labelled=query.substring(0,hindi.start()).trim().matches("(?is).*\\b"+LABEL+"\\b$");
            hindi.appendReplacement(normalized,Matcher.quoteReplacement((labelled?"":"total ")+(hindi.group(2)==null?"":"INR ")+hindi.group(1)));
        }
        hindi.appendTail(normalized);query=normalized.toString();
        Matcher matcher=Pattern.compile("(?i)\\b("+LABEL+")\\b\\s*(?:(?:of|was|is|had|at|exactly|equals|about|around|approximately|lagbhag)\\s*|[:=]\\s*)*(?:(INR|USD|EUR|GBP|Rs\\.?|₹|\\$|€|£)\\s*)?("+NUMBER+")").matcher(query);
        if(!matcher.find()){
            Matcher spoken=Pattern.compile("(?i)^\\s*(?:(?:please|bhai|hello|namaste|mujhe|muje)\\s+)*(?:(?:exact(?:ly)?|about|around|lagbhag)\\s+)?(?:(INR|Rs\\.?|₹|USD|\\$)\\s*)?("+NUMBER+")\\s+(?:(rupees|rupaye|rupay)\\s+)?(?:ka|ki|ke|wala|wali|wale)\\s+(?:invoice|bill)(?:\\s+(?:dikhao|dikha(?:\\s+do)?|dikhana|chahiye|please))?\\s*[?!.]?\\s*$").matcher(query);
            if(spoken.matches()){
                String unit=currency(spoken.group(1));if(spoken.group(3)!=null){if(unit!=null&&!unit.equals("INR"))throw new IllegalArgumentException("Search one currency at a time.");unit="INR";}
                return Json.obj("field","total","value",decimal(spoken.group(2)).toPlainString(),"currency",unit);
            }
            Matcher english=Pattern.compile("(?i)^\\s*(?:(?:please\\s+)?(?:show|find|get)(?:\\s+me)?(?:\\s+the)?\\s+)?(?:invoice|bill)\\s+(?:of|for|worth)\\s+(?:(INR|Rs\\.?|₹|USD|\\$)\\s*)?("+NUMBER+")\\s*(?:please)?[?!.]?\\s*$").matcher(query);
            if(english.matches())return Json.obj("field","total","value",decimal(english.group(2)).toPlainString(),"currency",currency(english.group(1)));
            Matcher shorthand=Pattern.compile("(?i)^\\s*(?:exact(?:ly)?\\s+|about\\s+|around\\s+|lagbhag\\s+)?(?:(INR|USD|EUR|GBP|Rs\\.?|₹|\\$|€|£)\\s*)?("+NUMBER+")\\s*(?:inv\\.?|invoice|bill|बिल|इनवॉइस)\\s*$").matcher(query);
            if(shorthand.matches())return Json.obj("field","total","value",decimal(shorthand.group(2)).toPlainString(),"currency",currency(shorthand.group(1)));
            if(query.matches("(?is).*\\b(?:"+LABEL+")\\b\\s*(?:under|over|between|above|below|[<>]).*\\d.*"))throw new IllegalArgumentException("Range comparisons are not supported; use one field and amount.");
            return null;
        }
        if(Pattern.compile("(?i)\\b(under|over|between|above|below|at least|at most|zyada|kam)\\b|[<>]|(?<![\\p{L}\\p{M}])(?:कम|ज्यादा|ज़्यादा|अधिक|नीचे|ऊपर|बीच)(?![\\p{L}\\p{M}])").matcher(query).find())throw new IllegalArgumentException("Range comparisons need an explicit supported filter. Search one amount.");
        JSONObject result=Json.obj("field",matcher.group(1).toLowerCase(Locale.ROOT).startsWith("sub")?"subtotal":"total","value",decimal(matcher.group(3)).toPlainString(),"currency",currency(matcher.group(2)));
        if(matcher.find())throw new IllegalArgumentException("Search one field and amount at a time.");
        Set<String> currencies=new HashSet<>();Matcher units=Pattern.compile("(?i)\\b(?:INR|USD|EUR|GBP|Rs\\.?)\\b|₹|\\$|€|£").matcher(query);while(units.find())currencies.add(currency(units.group()));if(currencies.size()>1)throw new IllegalArgumentException("Search one currency at a time.");
        return Json.obj("field",result.optString("field"),"value",result.optString("value"),"currency",currencies.size()==1?currencies.iterator().next():result.opt("currency"));
    }
    static boolean candidate(String query){
        if(!query.matches("(?is).*(?:\\b(invoice|bill|bil)\\b|बिल|इनवॉइस).*"))return false;
        String months="jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?";
        String remaining=query.replaceAll("\\b20\\d{2}-\\d{2}-\\d{2}\\b|\\b\\d{1,2}[/.]\\d{1,2}[/.](?:20)?\\d{2}\\b","").replaceAll("(?i)\\b(?:\\d{1,2}\\s+(?:"+months+")|(?:"+months+")\\s+\\d{1,2}),?\\s+20\\d{2}\\b","");
        if(!Pattern.compile(NUMBER).matcher(remaining).find())return false;
        return remaining.matches("(?is).*(?:\\b(ka|ki|wala|wali|lagbhag|around|about|amount|total|subtotal|worth|rupees|rupaye|bana|ban)\\b|₹|\\b(?:invoice|bill)\\s+(?:of|for)\\s+\\d).*");
    }
    static String expand(String query){StringBuilder digits=new StringBuilder();for(char c:query.toCharArray()){int n=Character.digit(c,10);digits.append(n>=0?(char)('0'+n):c);}query=digits.toString().replaceAll("(?i)\\binv\\b\\.?","invoice");if(!query.matches("(?is).*\\b(invoice|bill)\\b.*"))return query;Matcher m=Pattern.compile("(?i)(?<![\\w.,+\\-])(\\d+(?:\\.\\d{1,2})?)\\s*(k|thousand|lakh|lakhs|lac|lacs)\\b").matcher(query);StringBuffer out=new StringBuffer();while(m.find()){BigDecimal scale=m.group(2).toLowerCase(Locale.ROOT).startsWith("la")?new BigDecimal("100000"):new BigDecimal("1000");m.appendReplacement(out,Matcher.quoteReplacement(new BigDecimal(m.group(1)).multiply(scale).toPlainString()));}m.appendTail(out);return out.toString();}
    static BigDecimal tolerance(String query,JSONObject amount,JSONObject matching) {
        if(query.matches("(?is).*\\b(exact|exactly|equals|precisely)\\b.*")||Pattern.compile("(?<![\\p{L}\\p{M}])(?:ठीक|बिल्कुल|सटीक)(?![\\p{L}\\p{M}])").matcher(query).find()||query.contains("=")||matching.optString("mode").equals("exact"))return BigDecimal.ZERO;
        BigDecimal value=decimal(amount.optString("value"));String mode=matching.optString("mode","auto");
        if(mode.equals("absolute")||mode.equals("percent")){BigDecimal delta=decimal(matching.optString("value","0"));if(delta.signum()<0||delta.compareTo(new BigDecimal(mode.equals("percent")?"50":"100000"))>0)throw new IllegalArgumentException("Tolerance outside supported range");return mode.equals("percent")?value.multiply(delta).movePointLeft(2):delta;}
        return value.multiply(new BigDecimal("0.02")).min(new BigDecimal("500"));
    }
}
