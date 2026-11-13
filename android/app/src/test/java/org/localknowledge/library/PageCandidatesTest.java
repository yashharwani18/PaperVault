package org.localknowledge.library;

import java.util.*;
import org.junit.Test;
import static org.junit.Assert.*;

public class PageCandidatesTest {
 @Test public void repeatedChunksCannotCrowdOutOtherPages(){
  PageCandidates<String> top=new PageCandidates<>(5);
  for(int i=0;i<50;i++)top.add("long:1",1.0-i*.001,"long page");
  for(int i=0;i<4;i++)top.add("other:"+i,.8-i*.01,"other "+i);
  assertEquals(Arrays.asList("long page","other 0","other 1","other 2","other 3"),top.values());
 }
 @Test public void retainsOnlyTheBestChunkForEachPhysicalPage(){
  PageCandidates<String> top=new PageCandidates<>(2);
  top.add("a:1",.4,"old");top.add("b:1",.5,"second");
  assertTrue(top.accepts("a:1",.9));top.add("a:1",.9,"best");
  assertFalse(top.accepts("a:1",.8));top.add("a:1",.8,"worse");
  top.add("c:1",.6,"third");
  assertEquals(Arrays.asList("best","third"),top.values());
  assertFalse(top.accepts("d:1",Double.NaN));
 }
 @Test public void boundedRankingAgreesWithAnExhaustivePageOracle(){
  PageCandidates<Integer> top=new PageCandidates<>(20);
  Map<String,Integer> best=new HashMap<>();Map<Integer,Double> scores=new HashMap<>();Random random=new Random(25);
  for(int i=0;i<5000;i++){
   String key="d"+random.nextInt(100)+":"+random.nextInt(3);double score=random.nextDouble();scores.put(i,score);
   if(!best.containsKey(key)||score>scores.get(best.get(key)))best.put(key,i);
   top.add(key,score,i);
  }
  List<Integer> expected=new ArrayList<>(best.values());expected.sort(Comparator.comparingDouble((Integer i)->scores.get(i)).reversed());
  assertEquals(expected.subList(0,20),top.values());
 }
 @Test public void tiesKeepFirstEncounteredPagesAndPageKeysIncludeDocument(){
  PageCandidates<String> top=new PageCandidates<>(2);
  top.add("a:1",.5,"first");top.add("b:1",.5,"second");top.add("c:1",.5,"third");
  assertEquals(Arrays.asList("first","second"),top.values());
 }
}
