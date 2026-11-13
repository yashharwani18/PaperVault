package org.localknowledge.library;

/** Saved bill filters require transaction context, not just a general subject word. */
final class BillSearchIntent {
    static boolean context(String query,boolean force,String party){
        return force||!party.isEmpty()||query.matches("(?is).*(?:\\b(?:invoices?|bills?|sold\\s+to|sales?\\s+to|bought\\s+from|purchased\\s+from)\\b|बिल|इनवॉइस).*");
    }
}
