package org.localknowledge.library;

final class SemanticQuery {
    static String combine(String original, String interpretation) {
        String value=interpretation==null?"":interpretation.trim();
        return value.isEmpty()||value.equalsIgnoreCase(original.trim()) ? original : original+"\n"+value;
    }
}
