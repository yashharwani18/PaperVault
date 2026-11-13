package org.localknowledge.library;

import com.google.ai.edge.litertlm.Backend;
import com.google.ai.edge.litertlm.EmbeddingEngine;
import com.google.ai.edge.litertlm.EmbeddingEngineConfig;
import com.google.ai.edge.litertlm.EmbeddingOptions;
import com.google.ai.edge.litertlm.InputData;
import java.io.File;
import java.util.*;

/** Android text-only inference. Source offsets remain owned by PageIndexer. */
final class LiteRTTextEmbeddings {
    static EmbeddingEngine engine;static String loaded="";static int loadedBudget;
    static final EmbeddingOptions OPTIONS=new EmbeddingOptions(true,true,768);
    static String prepare(String input){
        String old="task: search result | query: ";
        if(input.startsWith(old))return "task: search query | text: "+input.substring(old.length()).strip();
        if(input.startsWith("task: "))return input.strip();
        return "task: search result | text: "+input.strip();
    }
    static int count(String path,String input){return NativeModels.tokenCountVocabulary(new File(new File(path).getParentFile(),"embeddinggemma-2-tokenizer.gguf").getPath(),prepare(input))+2;}
    static synchronized EmbeddingEngine engine(String path,int budget){
        if(engine!=null&&loaded.equals(path)&&loadedBudget==budget)return engine;
        release();File cache=new File(new File(path).getParentFile(),"litert-cache");cache.mkdirs();
        EmbeddingEngine next=new EmbeddingEngine(new EmbeddingEngineConfig(path,new Backend.CPU(Math.min(4,Runtime.getRuntime().availableProcessors()),null),null,null,cache.getPath(),null,budget));
        try{next.initialize();engine=next;loaded=path;loadedBudget=budget;return next;}catch(RuntimeException|Error error){next.close();throw error;}
    }
    static synchronized float[][] batch(String path,String[] inputs){
        return batch(path,inputs,512);
    }
    static synchronized float[][] batch(String path,String[] inputs,int budget){
        if(inputs.length<1||inputs.length>4)throw new IllegalArgumentException("Embedding batch must contain 1 to 4 passages");
        List<List<InputData>> work=new ArrayList<>();
        for(String input:inputs){if(count(path,input)>budget)throw new IllegalArgumentException("Embedding passage exceeds token budget");work.add(Collections.singletonList(new InputData.Text(prepare(input))));}
        var results=engine(path,budget).computeEmbeddingBatch(work,OPTIONS);
        if(results.size()!=inputs.length)throw new IllegalStateException("Invalid text embedding batch");
        float[][] out=new float[inputs.length][];for(int i=0;i<out.length;i++){out[i]=results.get(i).getEmbedding();PageIndexer.validate(out[i]);}return out;
    }
    static synchronized void release(){EmbeddingEngine previous=engine;engine=null;loaded="";if(previous!=null)previous.close();}
}
