package org.localknowledge.library;

public final class NativeModels {
    static { System.loadLibrary("library_models"); }
    private NativeModels() {}
    public static native void configure(String nativeLibraryDirectory);
    public static native String cpuInfo();
    public static native long[] performance();
    public static float[] embed(String path,String input){return path.endsWith(".litertlm")?LiteRTTextEmbeddings.batch(path,new String[]{input})[0]:embedNative(path,input);}
    public static float[][] embedBatch(String path,String[] inputs){return path.endsWith(".litertlm")?LiteRTTextEmbeddings.batch(path,inputs):embedBatchNative(path,inputs);}
    public static int tokenCount(String path,String input){return path.endsWith(".litertlm")?LiteRTTextEmbeddings.count(path,input):tokenCountNative(path,input);}
    private static native float[] embedNative(String modelPath,String input);
    private static native float[][] embedBatchNative(String modelPath,String[] inputs);
    private static native int tokenCountNative(String modelPath,String input);
    static native int tokenCountVocabulary(String modelPath,String input);
    public static native String generate(String modelPath,String prompt,String grammar,int maxTokens);
    private static native void releaseNative();
    public static void release(){try{LiteRTTextEmbeddings.release();}finally{releaseNative();}}
}
