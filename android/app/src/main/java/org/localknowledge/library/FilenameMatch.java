package org.localknowledge.library;

import java.text.Normalizer;
import java.util.Locale;

/** Filename comparison independent of embeddings or document content. */
final class FilenameMatch {
    static String normalized(String text){
        return Normalizer.normalize(text,Normalizer.Form.NFKC).toLowerCase(Locale.ROOT)
            .replaceAll("[^\\p{L}\\p{N}\\p{M}]+"," ").trim().replaceAll("\\s+"," ");
    }
    static boolean exact(String query,String filename){
        return exactNormalized(normalized(query),filename);
    }
    static boolean exactNormalized(String wanted,String filename){
        if(wanted.isEmpty())return false;
        int dot=filename.lastIndexOf('.');String stem=dot>0?filename.substring(0,dot):filename;
        return wanted.equals(normalized(filename))||wanted.equals(normalized(stem));
    }
}
