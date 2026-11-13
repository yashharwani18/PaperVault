package org.localknowledge.library;

import java.util.regex.Matcher;
import java.util.regex.Pattern;

/** Literal, whole-token matching across scripts and punctuation. */
final class LiteralSearch {
    private static final String WORD="[\\p{L}\\p{N}\\p{M}]";
    static Pattern pattern(String query) {
        Matcher m=Pattern.compile(WORD+"+").matcher(query);StringBuilder expression=new StringBuilder();
        while(m.find()) {if(expression.length()>0)expression.append("[^\\p{L}\\p{N}\\p{M}]+");expression.append(Pattern.quote(m.group()));}
        if(expression.length()==0)return null;
        return Pattern.compile("(?<!"+WORD+")"+expression+"(?!"+WORD+")",Pattern.CASE_INSENSITIVE|Pattern.UNICODE_CASE);
    }
    static boolean matches(String query,String text) {Pattern p=pattern(query);return p!=null&&p.matcher(text).find();}
}
