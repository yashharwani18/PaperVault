package org.localknowledge.library;

import org.junit.Test;
import org.junit.Rule;
import org.junit.rules.TemporaryFolder;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.security.MessageDigest;
import java.util.concurrent.*;
import static org.junit.Assert.*;

public class ModelAssetsTest {
    @Rule public TemporaryFolder temporary = new TemporaryFolder();
    static final String TEXT_MODEL=ModelAssets.TEXT_MODEL, TOKENIZER=ModelAssets.TOKENIZER, QWEN="qwen3-0.6b-q4.gguf";
    static final byte[] WEIGHT="small verified fixture".getBytes(StandardCharsets.UTF_8);
    String recipe() throws Exception {
        StringBuilder sha=new StringBuilder();
        for(byte b:MessageDigest.getInstance("SHA-256").digest(WEIGHT))sha.append(String.format("%02x",b&255));
        String entry="{\"bytes\":"+WEIGHT.length+",\"sha256\":\""+sha+"\"}";
        return "{\""+TEXT_MODEL+"\":"+entry+",\""+TOKENIZER+"\":"+entry+",\""+QWEN+"\":"+entry+"}";
    }
    ModelAssets.AssetSource assets(boolean full) throws Exception {
        byte[] metadata=recipe().getBytes(StandardCharsets.UTF_8);
        return name->{if(name.equals("offline-models.json"))return new ByteArrayInputStream(metadata);
            if(full)return new ByteArrayInputStream(WEIGHT);
            throw new FileNotFoundException(name);};
    }
    @Test public void fullThenSmallUpdateReusesVerifiedFilesWithoutRewriting() throws Exception {
        File directory=temporary.newFolder();
        ModelAssets full=new ModelAssets(directory,assets(true));full.ready.get(5,TimeUnit.SECONDS);
        File embedding=new File(directory,TEXT_MODEL);long written=embedding.lastModified();
        ModelAssets update=new ModelAssets(directory,assets(false));update.ready.get(5,TimeUnit.SECONDS);
        assertEquals("ready",update.state);assertEquals(written,embedding.lastModified());
        assertArrayEquals(WEIGHT,Files.readAllBytes(embedding.toPath()));
    }
    @Test public void freshSmallInstallFailsPromptlyWithFullInstallerGuidance() throws Exception {
        ModelAssets update=new ModelAssets(temporary.newFolder(),assets(false));
        try{update.ready.get(5,TimeUnit.SECONDS);fail("Missing models must prevent readiness");}
        catch(ExecutionException expected){assertTrue(update.error.contains("complete PaperVault APK"));}
        assertEquals("error",update.state);
    }
    @Test public void damagedSmallInstallRetainsEveryExistingFile() throws Exception {
        File directory=temporary.newFolder();File damaged=new File(directory,TEXT_MODEL),good=new File(directory,QWEN);
        byte[] broken="damaged model".getBytes(StandardCharsets.UTF_8);
        Files.write(damaged.toPath(),broken);Files.write(good.toPath(),WEIGHT);
        ModelAssets update=new ModelAssets(directory,assets(false));
        try{update.ready.get(5,TimeUnit.SECONDS);fail("Damaged models must prevent readiness");}
        catch(ExecutionException expected){assertTrue(update.error.contains("complete PaperVault APK"));}
        assertArrayEquals(broken,Files.readAllBytes(damaged.toPath()));
        assertArrayEquals(WEIGHT,Files.readAllBytes(good.toPath()));
    }
    @Test public void corruptFullInstallerCannotDeleteExistingModel() throws Exception {
        File directory=temporary.newFolder();File existing=new File(directory,TEXT_MODEL);
        byte[] retained="existing damaged model awaiting repair".getBytes(StandardCharsets.UTF_8);
        Files.write(existing.toPath(),retained);
        byte[] metadata=recipe().getBytes(StandardCharsets.UTF_8);
        ModelAssets broken=new ModelAssets(directory,name->new ByteArrayInputStream(name.equals("offline-models.json")?metadata:new byte[]{1,2,3}));
        try{broken.ready.get(5,TimeUnit.SECONDS);fail("An invalid bundled model must not be installed");}
        catch(ExecutionException expected){assertTrue(broken.error.contains("complete PaperVault APK"));}
        assertArrayEquals(retained,Files.readAllBytes(existing.toPath()));
        assertFalse(new File(directory,TEXT_MODEL+".partial").exists());
    }
}
