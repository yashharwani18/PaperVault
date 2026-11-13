package org.localknowledge.library;

import java.util.Locale;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/** Identifiers are matched as identifiers, never as monetary amounts. */
final class InvoiceNumbers {
    private static final String ID = "[A-Za-z0-9]+(?:[-/_][A-Za-z0-9]+)*";
    private static final String BILL="(?:inv(?:oice)?|bill|bil|इनवॉइस|इनवोइस|बिल)";
    private static final String NUMBER="(?:number|no\\.?|नंबर|नम्बर|संख्या|क्रमांक|#)";
    private static final String START="(?iu)^\\s*(?:(?:please|bhai|hello|hi|namaste|mujhe|muje|mera|meri|mere|नमस्ते|कृपया|मुझे|मेरा|मेरी|मेरे)[\\s,]+)*(?:(?:show|find|open|get)(?:\\s+me)?(?:\\s+the)?\\s+)?";
    private static final String END="(?:\\s+(?:please|dikha(?:o|na)?|dikha\\s+do|dikhana|chahiye|kholo|nikaalo|nikalo|दिखाओ|दिखा(?:\\s+दो)?|दिखाइए|दिखाएं|दिखाना|खोजो|खोलो|चाहिए|निकालो))?\\s*[?।!]?\\s*$";
    private static final Pattern QUERY = Pattern.compile(START+BILL+"(?=[\\s:#-]|[0-9])\\s*(?:"+NUMBER+"\\s*)?[:#-]?\\s*("+ID+")"+END);
    // A number-first request needs an explicit identifier cue: "25 ka bill" is money.
    private static final Pattern NUMBER_FIRST=Pattern.compile(START+"("+ID+")\\s+"+NUMBER+"\\s+(?:(?:ka|ki|wala|wali|वाला|वाली|का|की)\\s+)?"+BILL+END);
    private static final Pattern LABEL = Pattern.compile("(?im)\\b(?:invoice|inv|bill)\\s*(?:number|no\\.?|#)\\s*[:#：-]?\\s*((?:inv\\s*[-/]?\\s*)?" + ID + ")");
    static String query(String text) {
        StringBuilder normalized=new StringBuilder();
        for(char c:text.toCharArray()){int digit=Character.digit(c,10);normalized.append(digit>=0?(char)('0'+digit):c);}
        String input=normalized.toString().replaceAll("(?i)\\binv\\s*(?:[-/]\\s*|\\s+)(?=[0-9])","INV-");
        Matcher m=QUERY.matcher(input);
        if(!m.matches()){m=NUMBER_FIRST.matcher(input);if(!m.matches())return null;}
        String identifier=m.group(1);
        // Field requests belong to general/amount search, not an identifier lookup.
        if(identifier.matches("(?i)(?:total|subtotal|date|amount|details|number|no)"))return null;
        return identifier;
    }
    private static String canonical(String text) { return text.toLowerCase(Locale.ROOT).replaceAll("[^a-z0-9]", ""); }
    private static boolean equal(String wanted,String value) {
        String a=canonical(wanted), b=canonical(value);
        if(a.isEmpty())return false;
        if(a.equals(b))return true;
        String numericA=a.replaceFirst("^(?:inv)+(?=[0-9]+$)", ""),numericB=b.replaceFirst("^(?:inv)+(?=[0-9]+$)", "");
        return numericA.matches("[0-9]+")&&numericB.equals(numericA);
    }
    static boolean matches(String wanted,String saved,String text) {
        if(equal(wanted,saved))return true;
        Matcher m=LABEL.matcher(text);while(m.find())if(equal(wanted,m.group(1)))return true;
        return false;
    }
}
