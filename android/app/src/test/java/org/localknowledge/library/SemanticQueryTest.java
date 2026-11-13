package org.localknowledge.library;
import org.junit.Test;
import static org.junit.Assert.*;
public class SemanticQueryTest {
 @Test public void preservesOriginalSearchAlongsideInterpretation(){assertEquals("how do computers find shortest paths\nshortest path algorithms",SemanticQuery.combine("how do computers find shortest paths","shortest path algorithms"));}
 @Test public void ignoresBlankAndDuplicateInterpretations(){assertEquals("tax rules",SemanticQuery.combine("tax rules","  "));assertEquals("tax rules",SemanticQuery.combine("tax rules","TAX RULES"));}
}
