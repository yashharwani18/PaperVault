package org.localknowledge.library;

import java.util.*;

/** Bounded best-chunk selection per physical page, before the candidate cutoff. */
final class PageCandidates<T> {
    private static final class Entry<T> {
        final String key; final double score; final long order; final T value;
        Entry(String key,double score,long order,T value){this.key=key;this.score=score;this.order=order;this.value=value;}
    }
    private final int limit;
    private long sequence;
    private final Map<String,Entry<T>> pages=new HashMap<>();
    private final PriorityQueue<Entry<T>> worst=new PriorityQueue<>(
        Comparator.comparingDouble((Entry<T> e)->e.score).thenComparing(Comparator.comparingLong((Entry<T> e)->e.order).reversed()));
    PageCandidates(int limit){if(limit<1)throw new IllegalArgumentException("Positive candidate limit required");this.limit=limit;}
    boolean accepts(String key,double score){
        if(!Double.isFinite(score))return false;
        Entry<T> old=pages.get(key);
        if(old!=null)return score>old.score;
        return pages.size()<limit||score>worst.peek().score;
    }
    void add(String key,double score,T value){
        if(!accepts(key,score))return;
        Entry<T> old=pages.remove(key);
        if(old!=null)worst.remove(old);
        else if(pages.size()==limit){Entry<T> removed=worst.poll();pages.remove(removed.key);}
        Entry<T> entry=new Entry<>(key,score,sequence++,value);pages.put(key,entry);worst.add(entry);
    }
    List<T> values(){
        List<Entry<T>> ranked=new ArrayList<>(pages.values());
        ranked.sort(Comparator.comparingDouble((Entry<T> e)->e.score).reversed().thenComparingLong(e->e.order));
        List<T> result=new ArrayList<>();for(Entry<T> entry:ranked)result.add(entry.value);return result;
    }
}
