package org.localknowledge.library;

import android.content.Context;
import org.json.*;
import java.io.*;
import java.nio.file.Files;
import java.nio.file.StandardCopyOption;
import java.security.MessageDigest;
import java.util.concurrent.*;

final class ModelAssets {
    interface AssetSource { InputStream open(String name) throws IOException; }
    final File directory;
    static final String FULL_INSTALL_GUIDANCE="PaperVault's offline models are missing or damaged. Install the complete PaperVault APK over this app, then open PaperVault again. Keep this app installed to preserve your library.";
    volatile String state="loading",error=null;
    static final String TEXT_MODEL="embeddinggemma-2-text-270m.litertlm",TOKENIZER="embeddinggemma-2-tokenizer.gguf",LEGACY_MODEL="embeddinggemma-2-q8.gguf";
    static final String LEGACY_SHA="2188ac1deca4b77dffefd603c2776a9d76d9d74ec01841392982ebb840b09135";
    volatile String embeddingSha="",textIdentity="";volatile boolean legacyEmbedding;
    synchronized void selectLegacy(boolean legacy){legacyEmbedding=legacy;embeddingSha=legacy?LEGACY_SHA:textIdentity;}

    final CompletableFuture<Void> ready=new CompletableFuture<>();
    ModelAssets(Context context){this(new File(context.getFilesDir(),"models"),name->context.getAssets().open(name));}
    ModelAssets(File directory,AssetSource assets){this.directory=directory;
        Thread prepare=new Thread(()->{try{
            if(!directory.isDirectory()&&!directory.mkdirs())throw new IOException("PaperVault cannot create its offline model storage. Free some storage and open PaperVault again.");
            JSONObject manifest;try(InputStream in=assets.open("offline-models.json")){manifest=Json.parse(new String(read(in),java.nio.charset.StandardCharsets.UTF_8));}
            textIdentity=manifest.getJSONObject(TEXT_MODEL).getString("sha256")+"-litert-text-v1";
            for(String name:new String[]{TEXT_MODEL,TOKENIZER,"qwen3-0.6b-q4.gguf"}){
                JSONObject model=manifest.getJSONObject(name);File target=new File(directory,name);
                if(target.isFile()&&target.length()==model.getLong("bytes")&&sha256(target).equals(model.getString("sha256")))continue;
                // Open the asset before touching private files: small APKs cannot repair models.
                InputStream bundled;
                try{bundled=assets.open(name);}catch(FileNotFoundException missing){throw new IOException(FULL_INSTALL_GUIDANCE,missing);}
                File partial=new File(directory,name+".partial");
                try(InputStream in=bundled){
                    if(directory.getUsableSpace()<model.getLong("bytes")+100_000_000)throw new IOException("Free at least 1 GB of storage for the bundled offline models.");
                    try(FileOutputStream out=new FileOutputStream(partial)){byte[] b=new byte[1024*1024];int n;while((n=in.read(b))>=0)out.write(b,0,n);out.getFD().sync();}
                    if(partial.length()!=model.getLong("bytes")||!sha256(partial).equals(model.getString("sha256")))throw new IOException("PaperVault's bundled offline model is damaged. Install the complete PaperVault APK again.");
                    // Replace only after verification; never delete an installed model first.
                    Files.move(partial.toPath(),target.toPath(),StandardCopyOption.ATOMIC_MOVE,StandardCopyOption.REPLACE_EXISTING);
                }finally{if(partial.isFile())partial.delete();}
            }
            synchronized(ModelAssets.this){embeddingSha=legacyEmbedding?LEGACY_SHA:textIdentity;}
            state="ready";ready.complete(null);
        }catch(Throwable e){state="error";error=e.getMessage();ready.completeExceptionally(e);}},"prepare-local-models");prepare.start();}
    static byte[] read(InputStream input)throws IOException{ByteArrayOutputStream out=new ByteArrayOutputStream();byte[] b=new byte[8192];int n;while((n=input.read(b))>=0)out.write(b,0,n);return out.toByteArray();}
    static String sha256(File file)throws Exception{MessageDigest digest=MessageDigest.getInstance("SHA-256");try(InputStream in=new FileInputStream(file)){byte[] b=new byte[1024*1024];int n;while((n=in.read(b))>=0)digest.update(b,0,n);}StringBuilder hex=new StringBuilder();for(byte b:digest.digest())hex.append(String.format(java.util.Locale.ROOT,"%02x",b&255));return hex.toString();}
    String embedding()throws Exception{ready.get(10,TimeUnit.MINUTES);return new File(directory,legacyEmbedding?LEGACY_MODEL:TEXT_MODEL).getAbsolutePath();}
    String textEmbedding()throws Exception{ready.get(10,TimeUnit.MINUTES);return new File(directory,TEXT_MODEL).getAbsolutePath();}
    String qwen()throws Exception{ready.get(10,TimeUnit.MINUTES);return new File(directory,"qwen3-0.6b-q4.gguf").getAbsolutePath();}
    static String prompt(String system,String user){return "<|im_start|>system\n"+system+"<|im_end|>\n<|im_start|>user\n"+user+"<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n";}
}
