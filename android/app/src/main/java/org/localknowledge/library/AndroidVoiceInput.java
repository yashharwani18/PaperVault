package org.localknowledge.library;

import android.Manifest;
import android.app.Activity;
import android.app.AlertDialog;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.speech.RecognitionListener;
import android.speech.RecognizerIntent;
import android.speech.SpeechRecognizer;
import org.json.JSONObject;
import java.util.List;
import java.util.Locale;

/** One user-initiated dictation session; audio is never stored in the library. */
final class AndroidVoiceInput {
    static final int MICROPHONE_PERMISSION=102,SYSTEM_REQUEST=107;
    static final String NOTE="Voice prefers on-device recognition. Android speech fallback may use internet; document search stays on this phone.";
    interface Result {void complete(int status,JSONObject result);}
    final Activity activity;final Result result;final Handler handler=new Handler(Looper.getMainLooper());
    String language="hi-IN";SpeechRecognizer recognizer;AlertDialog dialog;boolean finished,usingSystem,awaitingPermission;
    final Runnable timeout=()->finish(400,Json.obj("detail","Voice input timed out. Try again or type your search."));

    AndroidVoiceInput(Activity activity,Result result){this.activity=activity;this.result=result;}
    static boolean onDeviceAvailable(Context context){try{return Build.VERSION.SDK_INT>=31&&SpeechRecognizer.isOnDeviceRecognitionAvailable(context);}catch(RuntimeException error){return false;}}
    static boolean systemAvailable(Context context){try{return systemIntent().resolveActivity(context.getPackageManager())!=null;}catch(RuntimeException error){return false;}}
    static JSONObject capabilities(Context context){boolean local=onDeviceAvailable(context),system=systemAvailable(context);return Json.obj("available",local||system,"on_device",local,"system",system,"note",NOTE);}
    static Intent systemIntent(){return systemIntent(Locale.getDefault().toLanguageTag());}
    static Intent systemIntent(String language){return new Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH)
        .putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL,RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
        .putExtra(RecognizerIntent.EXTRA_LANGUAGE,language)
        .putExtra(RecognizerIntent.EXTRA_MAX_RESULTS,1)
        .putExtra(RecognizerIntent.EXTRA_PROMPT,"Speak your PaperVault search. Android speech may use internet.");}
    static String transcript(List<String> values){if(values!=null)for(String value:values)if(value!=null&&!value.trim().isEmpty()){
        String text=value.trim().replaceAll("\\s+"," ");if(text.length()>500)throw new IllegalArgumentException("That search is too long. Speak a shorter query or edit it by typing.");return text;
    }throw new IllegalArgumentException("No words were recognized. Try again or type your search.");}
    static boolean shouldFallback(int error){return error==SpeechRecognizer.ERROR_LANGUAGE_NOT_SUPPORTED||error==SpeechRecognizer.ERROR_LANGUAGE_UNAVAILABLE||error==SpeechRecognizer.ERROR_SERVER||error==SpeechRecognizer.ERROR_SERVER_DISCONNECTED||error==SpeechRecognizer.ERROR_CLIENT;}

    void start(){
        language=activity.getPreferences(Context.MODE_PRIVATE).getString("voice_language","hi-IN");
        String[] languages={"Hindi / Hinglish", "English (India)"};
        dialog=new AlertDialog.Builder(activity).setTitle("Speak in")
            .setSingleChoiceItems(languages,language.equals("hi-IN")?0:1,(d,which)->language=which==0?"hi-IN":"en-IN")
            .setPositiveButton("Listen",(d,w)->{activity.getPreferences(Context.MODE_PRIVATE).edit().putString("voice_language",language).apply();dialog.dismiss();dialog=null;begin();})
            .setNegativeButton("Cancel",(d,w)->cancel()).setOnCancelListener(d->cancel()).create();dialog.show();
    }
    void begin(){if(onDeviceAvailable(activity)){
        if(activity.checkSelfPermission(Manifest.permission.RECORD_AUDIO)!=PackageManager.PERMISSION_GRANTED){awaitingPermission=true;activity.requestPermissions(new String[]{Manifest.permission.RECORD_AUDIO},MICROPHONE_PERMISSION);}
        else startOnDevice();
    }else startSystem();}
    void permissionResult(boolean granted){if(finished)return;awaitingPermission=false;if(granted)startOnDevice();else finish(400,Json.obj("detail","Microphone permission is off. Enable it in Android app settings to use on-device voice, or type your search."));}
    void startOnDevice(){if(finished)return;if(!onDeviceAvailable(activity)){startSystem();return;}
        try{
            recognizer=SpeechRecognizer.createOnDeviceSpeechRecognizer(activity);
            recognizer.setRecognitionListener(new RecognitionListener(){
                public void onReadyForSpeech(Bundle b){message("Listening… Speak your search. Your words stay on this phone.");}
                public void onBeginningOfSpeech(){}public void onRmsChanged(float f){}public void onBufferReceived(byte[] b){}
                public void onEndOfSpeech(){message("Recognizing your words…");}
                public void onPartialResults(Bundle b){if(!finished&&!usingSystem){var values=b.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION);if(values!=null&&!values.isEmpty())message(values.get(0));}}
                public void onEvent(int t,Bundle b){}
                public void onResults(Bundle b){if(finished||usingSystem)return;recognized(b==null?null:b.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION),"on_device");}
                public void onError(int error){if(finished||usingSystem)return;if(shouldFallback(error)&&systemAvailable(activity)){startSystem();return;}
                    String text=error==SpeechRecognizer.ERROR_NO_MATCH||error==SpeechRecognizer.ERROR_SPEECH_TIMEOUT?"No words were recognized. Try again or type your search.":error==SpeechRecognizer.ERROR_INSUFFICIENT_PERMISSIONS?"Microphone permission is off. Enable it in Android app settings or type your search.":"On-device speech is unavailable for this language. Check Android speech settings or type your search.";
                    finish(400,Json.obj("detail",text));}
            });
            dialog=new AlertDialog.Builder(activity).setTitle("Voice search").setMessage("Starting the microphone…")
                .setPositiveButton("Stop",null).setNegativeButton("Cancel",(d,w)->cancel()).setOnCancelListener(d->cancel()).create();
            dialog.setOnShowListener(d->dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener(v->{if(recognizer!=null){recognizer.stopListening();message("Recognizing your words…");dialog.getButton(AlertDialog.BUTTON_POSITIVE).setEnabled(false);}}));
            dialog.show();handler.postDelayed(timeout,30000);
            Intent intent=systemIntent(language).putExtra(RecognizerIntent.EXTRA_PREFER_OFFLINE,true).putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS,true);
            recognizer.startListening(intent);
        }catch(RuntimeException error){if(systemAvailable(activity))startSystem();else finish(400,Json.obj("detail","Speech recognition could not start. Check Android speech settings or type your search."));}
    }
    void startSystem(){if(finished)return;usingSystem=true;cleanupCapture();
        if(!systemAvailable(activity)){finish(400,Json.obj("detail","No Android speech service is available. Enable a speech-recognition service in Android settings or use your keyboard microphone."));return;}
        try{activity.startActivityForResult(systemIntent(language),SYSTEM_REQUEST);}catch(RuntimeException error){finish(400,Json.obj("detail","Android speech recognition could not open. Check your speech service or type your search."));}
    }
    void systemResult(int status,Intent data){if(finished)return;if(status!=Activity.RESULT_OK){cancel();return;}
        recognized(data==null?null:data.getStringArrayListExtra(RecognizerIntent.EXTRA_RESULTS),"android_service");}
    void recognized(List<String> values,String mode){try{finish(200,Json.obj("transcript",transcript(values),"speech_mode",mode,"offline_guaranteed",mode.equals("on_device")));}catch(IllegalArgumentException error){finish(400,Json.obj("detail",error.getMessage()));}}
    void message(String text){if(!finished&&!usingSystem&&dialog!=null)dialog.setMessage(text);}
    void pause(){if(!usingSystem&&!awaitingPermission)cancel();}
    void cancel(){finish(200,Json.obj("cancelled",true));}
    void finish(int status,JSONObject value){if(finished)return;finished=true;cleanupCapture();result.complete(status,value);}
    void cleanupCapture(){handler.removeCallbacks(timeout);SpeechRecognizer old=recognizer;recognizer=null;if(old!=null){try{old.cancel();}catch(RuntimeException ignored){}try{old.destroy();}catch(RuntimeException ignored){}}if(dialog!=null){dialog.setOnCancelListener(null);dialog.dismiss();dialog=null;}}
    void close(){finished=true;cleanupCapture();}
}
