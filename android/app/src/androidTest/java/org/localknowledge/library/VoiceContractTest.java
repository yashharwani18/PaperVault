package org.localknowledge.library;

import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import org.json.JSONObject;
import org.junit.Test;
import org.junit.runner.RunWith;
import android.app.Activity;
import android.content.Intent;
import android.speech.RecognizerIntent;
import android.speech.SpeechRecognizer;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import static org.junit.Assert.*;

@RunWith(AndroidJUnit4.class)
public class VoiceContractTest {
    @Test public void stateExplainsNativeVoiceAvailabilityAndFallback()throws Exception {
        NativeBackend b=((LibraryApplication)InstrumentationRegistry.getInstrumentation().getTargetContext().getApplicationContext()).backend;
        JSONObject state=b.state();assertTrue("Phone UI needs both voice paths, not an Android-12-only flag",state.has("voice"));
        JSONObject voice=state.getJSONObject("voice");assertTrue(voice.has("on_device"));assertTrue(voice.has("system"));
        assertEquals(voice.getBoolean("on_device")||voice.getBoolean("system"),state.getBoolean("voice_available"));
        assertTrue(voice.getString("note").contains("internet"));
    }

    @Test public void systemIntentRequestsDictationAndReturnsToKhoj(){
        Intent intent=AndroidVoiceInput.systemIntent();assertEquals(RecognizerIntent.ACTION_RECOGNIZE_SPEECH,intent.getAction());
        assertEquals(RecognizerIntent.LANGUAGE_MODEL_FREE_FORM,intent.getStringExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL));
        assertEquals(1,intent.getIntExtra(RecognizerIntent.EXTRA_MAX_RESULTS,0));
        assertNotNull(intent.getStringExtra(RecognizerIntent.EXTRA_LANGUAGE));
    }
    @Test public void transcriptPreservesHindiAndEnglishAndRejectsEmptyOrLongInput(){
        assertEquals("मुझे Fourier वाले notes दिखाओ",AndroidVoiceInput.transcript(Arrays.asList("  ","  मुझे Fourier वाले notes दिखाओ  ")));
        assertEquals("Fourier notes",AndroidVoiceInput.transcript(Collections.singletonList("Fourier\n notes")));
        try{AndroidVoiceInput.transcript(Collections.emptyList());fail("Empty result must not replace typed text");}catch(IllegalArgumentException expected){}
        try{AndroidVoiceInput.transcript(Collections.singletonList("a".repeat(501)));fail("Oversized result must not be silently truncated");}catch(IllegalArgumentException expected){}
    }
    @Test public void systemResultCompletesOnceAndReportsItsProvider()throws Exception {
        AtomicInteger calls=new AtomicInteger();AtomicReference<org.json.JSONObject> result=new AtomicReference<>();
        InstrumentationRegistry.getInstrumentation().runOnMainSync(()->{
            AndroidVoiceInput session=new AndroidVoiceInput(new Activity(),(status,value)->{assertEquals(200,status);calls.incrementAndGet();result.set(value);});
            session.systemResult(Activity.RESULT_OK,new Intent().putStringArrayListExtra(RecognizerIntent.EXTRA_RESULTS,new ArrayList<>(Collections.singletonList("find my notes"))));
            session.systemResult(Activity.RESULT_OK,new Intent());
        });
        assertEquals(1,calls.get());assertEquals("find my notes",result.get().getString("transcript"));assertFalse(result.get().getBoolean("offline_guaranteed"));
    }
    @Test public void cancellationAndPermissionDenialPreserveTypedSearch()throws Exception {
        AtomicInteger calls=new AtomicInteger();AtomicReference<org.json.JSONObject> result=new AtomicReference<>();
        InstrumentationRegistry.getInstrumentation().runOnMainSync(()->{
            AndroidVoiceInput cancelled=new AndroidVoiceInput(new Activity(),(status,value)->{assertEquals(200,status);calls.incrementAndGet();result.set(value);});
            cancelled.systemResult(Activity.RESULT_CANCELED,null);cancelled.recognized(Collections.singletonList("late callback"),"on_device");
        });
        assertEquals(1,calls.get());assertTrue(result.get().getBoolean("cancelled"));assertFalse(result.get().has("transcript"));
        InstrumentationRegistry.getInstrumentation().runOnMainSync(()->{
            AndroidVoiceInput denied=new AndroidVoiceInput(new Activity(),(status,value)->{assertEquals(400,status);result.set(value);});denied.permissionResult(false);
        });
        assertFalse(result.get().has("transcript"));assertTrue(result.get().getString("detail").contains("permission"));
    }
    @Test public void closingOrPausingDoesNotLeakALateRecognitionResult(){
        AtomicInteger calls=new AtomicInteger();InstrumentationRegistry.getInstrumentation().runOnMainSync(()->{
            AndroidVoiceInput session=new AndroidVoiceInput(new Activity(),(status,value)->calls.incrementAndGet());session.close();session.recognized(Collections.singletonList("late"),"on_device");
            AndroidVoiceInput permission=new AndroidVoiceInput(new Activity(),(status,value)->calls.incrementAndGet());permission.awaitingPermission=true;permission.pause();assertFalse(permission.finished);permission.close();
            AndroidVoiceInput system=new AndroidVoiceInput(new Activity(),(status,value)->calls.incrementAndGet());system.usingSystem=true;system.pause();assertFalse(system.finished);system.close();
        });assertEquals(0,calls.get());
    }
    @Test public void silenceAndDeniedMicrophoneNeverSwitchToSystemSpeech(){
        assertFalse(AndroidVoiceInput.shouldFallback(SpeechRecognizer.ERROR_INSUFFICIENT_PERMISSIONS));
        assertFalse(AndroidVoiceInput.shouldFallback(SpeechRecognizer.ERROR_NO_MATCH));
        assertTrue(AndroidVoiceInput.shouldFallback(SpeechRecognizer.ERROR_LANGUAGE_UNAVAILABLE));
    }
}
