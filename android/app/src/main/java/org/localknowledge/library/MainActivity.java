package org.localknowledge.library;

import android.Manifest;
import android.app.*;
import android.content.*;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.net.Uri;
import android.os.*;
import android.provider.OpenableColumns;
import android.speech.*;
import android.view.*;
import android.webkit.*;
import android.widget.LinearLayout;
import androidx.documentfile.provider.DocumentFile;
import androidx.webkit.WebViewAssetLoader;
import org.json.*;
import java.io.*;
import java.util.*;

public final class MainActivity extends Activity {
    WebView web;LibraryApplication app;String pendingId;JSONObject pendingBody;String pendingAction;AndroidVoiceInput voiceInput;
    boolean pageReady,focusSearch,resumed;Intent incomingShare;
    final java.util.concurrent.ConcurrentHashMap<String,java.util.concurrent.FutureTask<Void>> cancellableSearches=new java.util.concurrent.ConcurrentHashMap<>();
    final String origin="https://appassets.androidplatform.net";
    @Override public void onCreate(Bundle state){super.onCreate(state);app=(LibraryApplication)getApplication();getWindow().setStatusBarColor(Color.TRANSPARENT);getWindow().setNavigationBarColor(Color.rgb(27,24,29));
        LinearLayout root=new LinearLayout(this);root.setBackgroundColor(Color.rgb(27,24,29));
        if(Build.VERSION.SDK_INT>=30){getWindow().setDecorFitsSystemWindows(false);root.setOnApplyWindowInsetsListener((v,insets)->{android.graphics.Insets system=insets.getInsets(WindowInsets.Type.systemBars()|WindowInsets.Type.displayCutout()),keyboard=insets.getInsets(WindowInsets.Type.ime());v.setPadding(system.left,system.top,system.right,Math.max(system.bottom,keyboard.bottom));return insets;});}
        else root.setFitsSystemWindows(true);
        web=new WebView(this);root.addView(web,new LinearLayout.LayoutParams(-1,-1));setContentView(root);web.setBackgroundColor(Color.rgb(27,24,29));
        WebSettings settings=web.getSettings();settings.setJavaScriptEnabled(true);settings.setDomStorageEnabled(true);settings.setAllowFileAccess(false);settings.setAllowContentAccess(false);settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);settings.setTextZoom(Math.round(getResources().getConfiguration().fontScale*100));
        if(Build.VERSION.SDK_INT>=29)settings.setForceDark(WebSettings.FORCE_DARK_OFF);
        web.addJavascriptInterface(new Bridge(),"AndroidLibrary");
        WebViewAssetLoader assets=new WebViewAssetLoader.Builder().addPathHandler("/",new WebViewAssetLoader.AssetsPathHandler(this)).build();
        web.setWebViewClient(new WebViewClient(){
            @Override public WebResourceResponse shouldInterceptRequest(WebView view,WebResourceRequest request){Uri uri=request.getUrl();
                if(!"appassets.androidplatform.net".equals(uri.getHost()))return blocked();
                String path=uri.getPath();if(path!=null&&path.matches("/api/documents/[a-f0-9]+/preview")){try{return app.backend.features.preview(path.split("/")[3],uri);}catch(Exception error){return new WebResourceResponse("application/json","UTF-8",409,"Preview unavailable",Map.of("Cache-Control","no-store"),new ByteArrayInputStream(Json.obj("detail","Page unavailable. Open the file or try again.").toString().getBytes(java.nio.charset.StandardCharsets.UTF_8)));}}
                if(path!=null&&path.matches("/api/documents/[a-f0-9]+/(file|original)")){
                    try{String id=path.split("/")[3];File file=app.backend.store.source(id,path.endsWith("/original"));String mime=sourceMime(file.getName());
                        return new WebResourceResponse(mime,null,200,"OK",Map.of("Content-Length",String.valueOf(file.length()),"Cache-Control","no-store","Accept-Ranges","none"),new FileInputStream(file));
                    }catch(Exception e){return new WebResourceResponse("text/plain","UTF-8",404,"Not Found",new HashMap<>(),new ByteArrayInputStream("Source unavailable".getBytes(java.nio.charset.StandardCharsets.UTF_8)));}
                }
                WebResourceResponse asset=assets.shouldInterceptRequest(uri);if(asset!=null&&path!=null&&path.endsWith(".mjs"))asset.setMimeType("application/javascript");return asset;
            }
            @Override public boolean shouldOverrideUrlLoading(WebView view,WebResourceRequest request){Uri uri=request.getUrl();if("appassets.androidplatform.net".equals(uri.getHost())){
                if(uri.getPath()!=null&&uri.getPath().matches("/api/documents/[a-f0-9]+/(file|original)")){share(uri.getPath());return true;}return false;}return true;}
            @Override public void onPageFinished(WebView view,String url){pageReady=true;web.evaluateJavascript("document.documentElement.classList.add('android');",null);focusSearch();AndroidSharing.deliver();}
            @Override public boolean onRenderProcessGone(WebView view,RenderProcessGoneDetail detail){view.destroy();recreate();return true;}
        });
        web.setWebChromeClient(new WebChromeClient());web.loadUrl(origin+"/index.html");
        if(Build.VERSION.SDK_INT>=33)getOnBackInvokedDispatcher().registerOnBackInvokedCallback(android.window.OnBackInvokedDispatcher.PRIORITY_DEFAULT,this::back);
        incoming(getIntent());
    }
    void incoming(Intent intent){if(intent==null)return;if(intent.getBooleanExtra("focus_search",false)){focusSearch=true;intent.removeExtra("focus_search");focusSearch();}String action=intent.getAction();if(Intent.ACTION_SEND.equals(action)||Intent.ACTION_SEND_MULTIPLE.equals(action)||(Intent.ACTION_VIEW.equals(action)&&intent.getData()!=null)){if(resumed){AndroidSharing.forward(this,intent);askNotifications();}else incomingShare=intent;}}
    void focusSearch(){if(pageReady&&focusSearch){focusSearch=false;web.evaluateJavascript("window.__khojFocusSearch=true;window.dispatchEvent(new Event('android-focus-search'));",null);}}
    void libraryChanged(String message){runOnUiThread(()->{if(isDestroyed())return;if(!pageReady){AndroidSharing.message=message;return;}web.evaluateJavascript("window.__khojLibraryMessage="+JSONObject.quote(message)+";window.dispatchEvent(new CustomEvent('android-library-changed',{detail:{message:"+JSONObject.quote(message)+"}}));",null);});}
    @Override protected void onResume(){super.onResume();resumed=true;app.backend.uiVisible=true;AndroidSharing.attach(this);app.api.submit(()->{try{app.backend.onAppOpen();}catch(Exception ignored){}});askNotifications();if(incomingShare!=null){Intent intent=incomingShare;incomingShare=null;AndroidSharing.forward(this,intent);askNotifications();}focusSearch();}
    @Override protected void onPause(){if(voiceInput!=null)voiceInput.pause();resumed=false;app.backend.uiVisible=false;AndroidSharing.detach(this);super.onPause();}
    @Override protected void onNewIntent(Intent intent){super.onNewIntent(intent);setIntent(intent);incoming(intent);}
    void askNotifications(){if(Build.VERSION.SDK_INT>=33&&checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS)!=PackageManager.PERMISSION_GRANTED&&!getPreferences(MODE_PRIVATE).getBoolean("asked_notifications",false)){getPreferences(MODE_PRIVATE).edit().putBoolean("asked_notifications",true).apply();requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS},110);}askBattery();}
    // One tap on the system dialog, once per install. Keeps overnight indexing
    // alive on aggressive OEM power management (vivo/iQOO/OPPO/Xiaomi skins);
    // users never need to find the battery settings screen themselves.
    void askBattery(){
        android.content.SharedPreferences remembered=getPreferences(MODE_PRIVATE);
        if(remembered.getBoolean("asked_battery",false))return;
        remembered.edit().putBoolean("asked_battery",true).apply();
        android.os.PowerManager power=getSystemService(android.os.PowerManager.class);
        if(power==null||power.isIgnoringBatteryOptimizations(getPackageName()))return;
        try{startActivity(new Intent(android.provider.Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS,Uri.parse("package:"+getPackageName())).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));}catch(Exception ignored){/* Launcher refused the request dialog; indexing still works while the app is open. */}
    }
    WebResourceResponse blocked(){return new WebResourceResponse("text/plain","UTF-8",403,"Offline app",new HashMap<>(),new ByteArrayInputStream(new byte[0]));}
    void back(){web.evaluateJavascript("window.dispatchEvent(new Event('android-back'));",null);}
    @Override public void onBackPressed(){back();}
    final class Bridge {
        @JavascriptInterface public void exit(){runOnUiThread(()->finish());}
        @JavascriptInterface public void cancel(String id){java.util.concurrent.FutureTask<Void> task=cancellableSearches.remove(id);if(task!=null)task.cancel(true);}
        @JavascriptInterface public void request(String id,String path,String method,String body){
            if(!path.startsWith("/api/")||path.contains("..")){resolve(id,400,Json.obj("detail","Invalid local API path"));return;}
            JSONObject data;try{data=body==null||body.isEmpty()?new JSONObject():Json.parse(body);removeNulls(data);}catch(Exception e){resolve(id,400,Json.obj("detail","Invalid request"));return;}
            if(path.startsWith("/api/native/")){runOnUiThread(()->nativeAction(id,path,data));return;}
            if(path.equals("/api/library-page")&&method.equals("POST")){app.metadataApi.submit(()->{try{resolve(id,200,NativeLibraryBrowse.page(app.backend,data));}catch(Throwable e){resolve(id,400,Json.obj("detail",String.valueOf(e.getMessage())));}});return;}
            if((path.equals("/api/filename-matches")||path.equals("/api/search"))&&method.equals("POST")){
                java.util.concurrent.FutureTask<Void> task=new java.util.concurrent.FutureTask<>(()->{try{NativeBackend.searchCheckpoint();JSONObject result=path.equals("/api/filename-matches")?app.backend.filenameMatches(data):app.backend.dispatch(path,method,data);NativeBackend.searchCheckpoint();resolve(id,200,result);}catch(java.util.concurrent.CancellationException ignored){}catch(Throwable e){resolve(id,400,Json.obj("detail",String.valueOf(e.getMessage())));}finally{cancellableSearches.remove(id);}return null;});
                cancellableSearches.put(id,task);(path.equals("/api/filename-matches")?app.metadataApi:app.api).execute(task);return;
            }
            app.api.submit(()->{try{JSONObject result=app.backend.dispatch(path,method,data);resolve(id,200,result.has("__array")?result.opt("__array"):result);}catch(Throwable e){resolve(id,400,Json.obj("detail",String.valueOf(e.getMessage())));}});
        }
    }
    static void removeNulls(JSONObject value)throws JSONException{List<String> keys=new ArrayList<>();Iterator<String> iterator=value.keys();while(iterator.hasNext())keys.add(iterator.next());for(String key:keys)if(value.isNull(key))value.remove(key);else if(value.opt(key) instanceof JSONObject)removeNulls(value.getJSONObject(key));}
    void resolve(String id,int status,Object body){String json=body==null?"null":body.toString();runOnUiThread(()->{if(!isDestroyed())web.evaluateJavascript("window.__androidResolve&&window.__androidResolve("+JSONObject.quote(id)+","+status+","+JSONObject.quote(json)+");",null);});}
    void nativeAction(String id,String path,JSONObject body){
        if(pendingId!=null){resolve(id,400,Json.obj("detail","Finish the current file or voice action first"));return;}
        pendingId=id;pendingBody=body;
        try{
            if(path.equals("/api/native/pin-search")){android.content.pm.ShortcutManager manager=getSystemService(android.content.pm.ShortcutManager.class);boolean supported=manager!=null&&manager.isRequestPinShortcutSupported();if(supported){Intent open=new Intent(this,MainActivity.class).setAction(Intent.ACTION_VIEW).putExtra("focus_search",true);android.content.pm.ShortcutInfo shortcut=new android.content.pm.ShortcutInfo.Builder(this,"khoj-search").setShortLabel("Search PaperVault").setIcon(android.graphics.drawable.Icon.createWithResource(this,org.localknowledge.library.R.drawable.ic_library)).setIntent(open).build();boolean requested=manager.requestPinShortcut(shortcut,null);finishPending(200,Json.obj("supported",requested,"message",requested?"Confirm Add on your home screen.":"Your launcher could not add the shortcut."));}else finishPending(200,Json.obj("supported",false,"message","Your launcher does not support adding shortcuts. Long-press PaperVault in your app drawer to move it to your home screen."));
            }else if(path.equals("/api/native/notifications")){if(Build.VERSION.SDK_INT<33||checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS)==PackageManager.PERMISSION_GRANTED){boolean enabled=getSystemService(NotificationManager.class).areNotificationsEnabled();if(!enabled)startActivity(new Intent(android.provider.Settings.ACTION_APP_NOTIFICATION_SETTINGS).putExtra(android.provider.Settings.EXTRA_APP_PACKAGE,getPackageName()));finishPending(200,Json.obj("granted",enabled,"message",enabled?"Indexing notifications are on.":"Turn on PaperVault notifications in Android settings, then return."));}else if(getPreferences(MODE_PRIVATE).getBoolean("asked_notifications",false)&&!shouldShowRequestPermissionRationale(Manifest.permission.POST_NOTIFICATIONS)){startActivity(new Intent(android.provider.Settings.ACTION_APP_NOTIFICATION_SETTINGS).putExtra(android.provider.Settings.EXTRA_APP_PACKAGE,getPackageName()));finishPending(200,Json.obj("granted",false,"message","Turn on PaperVault notifications in Android settings, then return."));}else{pendingAction="notifications";getPreferences(MODE_PRIVATE).edit().putBoolean("asked_notifications",true).apply();requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS},109);}
            }else if(path.equals("/api/native/pick-exclusion")){boolean folder=body.optString("kind").equals("folder");pendingAction="exclusion";Intent pick=new Intent(folder?Intent.ACTION_OPEN_DOCUMENT_TREE:Intent.ACTION_OPEN_DOCUMENT).addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);if(!folder)pick.addCategory(Intent.CATEGORY_OPENABLE).setType("application/pdf");startActivityForResult(pick,108);
            }else if(path.equals("/api/native/phone-scan")){pendingAction="phone-scan";if(app.backend.phoneScan.hasAccess()){completePhoneScan();}
                else if(Build.VERSION.SDK_INT>=30){try{startActivityForResult(new Intent(android.provider.Settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION,Uri.parse("package:"+getPackageName())),105);}catch(ActivityNotFoundException missing){startActivityForResult(new Intent(android.provider.Settings.ACTION_MANAGE_ALL_FILES_ACCESS_PERMISSION),105);}}
                else requestPermissions(new String[]{Manifest.permission.READ_EXTERNAL_STORAGE},106);
            }else if(path.equals("/api/native/diagnostics")){pendingAction="diagnostics";Intent intent=new Intent(Intent.ACTION_CREATE_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE).setType("application/json");intent.putExtra(Intent.EXTRA_TITLE,"PaperVault-support-report.json");startActivityForResult(intent,103);
            }else if(path.equals("/api/native/pick-import")){pendingAction="import";Intent intent=new Intent(body.optString("kind").equals("folder")?Intent.ACTION_OPEN_DOCUMENT_TREE:Intent.ACTION_OPEN_DOCUMENT);
                intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION|Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION);
                if(!body.optString("kind").equals("folder")){intent.addCategory(Intent.CATEGORY_OPENABLE);intent.setType("*/*");intent.putExtra(Intent.EXTRA_MIME_TYPES,new String[]{"application/pdf","application/vnd.openxmlformats-officedocument.presentationml.presentation","application/vnd.openxmlformats-officedocument.wordprocessingml.document","application/vnd.openxmlformats-officedocument.spreadsheetml.sheet","text/plain","text/markdown","text/csv","text/tab-separated-values"});intent.putExtra(Intent.EXTRA_ALLOW_MULTIPLE,body.optString("document_id").isEmpty());}
                startActivityForResult(intent,101);
            }else if(path.equals("/api/native/voice")){pendingAction="voice";String requestId=pendingId;voiceInput=new AndroidVoiceInput(this,(status,result)->{if(requestId.equals(pendingId)&&"voice".equals(pendingAction)){voiceInput=null;finishPending(status,result);}});voiceInput.start();
            }else if(path.equals("/api/native/export-embeddings")){pendingAction="embeddings";if(!app.backend.idle())throw new IllegalArgumentException("Wait for file reading to finish before exporting embeddings.");Intent intent=new Intent(Intent.ACTION_CREATE_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE).setType("application/zip");intent.putExtra(Intent.EXTRA_TITLE,"PaperVault-embeddings-"+java.time.LocalDate.now()+".zip");startActivityForResult(intent,103);
            }else if(path.equals("/api/native/backup")||path.equals("/api/native/export")){pendingAction=path.endsWith("backup")?"backup":"export";if(!app.backend.idle())throw new IllegalArgumentException("Wait for document indexing to finish first");
                Intent intent=new Intent(Intent.ACTION_CREATE_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE).setType(pendingAction.equals("backup")?"application/octet-stream":"application/pdf");intent.putExtra(Intent.EXTRA_TITLE,pendingAction.equals("backup")?"PaperVault-backup."+(body.optString("password").isEmpty()?"zip":"llandroid"):"PaperVault-context.pdf");startActivityForResult(intent,103);
            }else if(path.equals("/api/native/restore")){pendingAction="restore";if(!app.backend.idle())throw new IllegalArgumentException("Wait for indexing to finish first");Intent intent=new Intent(Intent.ACTION_OPEN_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE).setType("*/*");startActivityForResult(intent,104);
            }else throw new IllegalArgumentException("Unknown native action");
        }catch(Exception error){finishPending(400,Json.obj("detail",String.valueOf(error.getMessage())));}
    }
    void completePhoneScan(){app.api.submit(()->{try{app.backend.phoneScan.start();finishPending(200,app.backend.phoneScan.status());runOnUiThread(this::askNotifications);}catch(Exception error){finishPending(400,Json.obj("detail",String.valueOf(error.getMessage())));}});}
    static String sourceMime(String name){String lower=name.toLowerCase(Locale.ROOT);if(lower.endsWith(".docx"))return "application/vnd.openxmlformats-officedocument.wordprocessingml.document";if(lower.endsWith(".xlsx"))return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";if(lower.endsWith(".pptx"))return "application/vnd.openxmlformats-officedocument.presentationml.presentation";if(lower.endsWith(".csv"))return "text/csv";if(lower.endsWith(".tsv"))return "text/tab-separated-values";if(lower.endsWith(".md"))return "text/markdown";if(lower.endsWith(".txt"))return "text/plain";return "application/pdf";}
    String filename(Uri uri){try(android.database.Cursor c=getContentResolver().query(uri,new String[]{OpenableColumns.DISPLAY_NAME},null,null,null)){if(c!=null&&c.moveToFirst())return c.getString(0);}return "document.pdf";}
    void collect(DocumentFile folder,List<Uri> files,int depth,int[] visited){if(depth>16)throw new IllegalArgumentException("Folder is too deep");for(DocumentFile item:folder.listFiles()){if(++visited[0]>10000)throw new IllegalArgumentException("Folder contains too many entries");if(item.isDirectory()){collect(item,files,depth+1,visited);continue;}String name=item.getName();if(name!=null&&name.toLowerCase(Locale.ROOT).matches(".*\\.(pdf|pptx|docx|xlsx|txt|md|csv|tsv)$"))files.add(item.getUri());if(files.size()>500)throw new IllegalArgumentException("Choose a folder with at most 500 supported documents");}}
    @Override protected void onActivityResult(int request,int result,Intent data){super.onActivityResult(request,result,data);if(request==AndroidVoiceInput.SYSTEM_REQUEST){if(voiceInput!=null)voiceInput.systemResult(result,data);return;}if(pendingId==null)return;
        if(request==105){if(app.backend.phoneScan.hasAccess()){completePhoneScan();}else finishPending(200,Json.obj("permission",false));return;}
        if(result!=RESULT_OK||data==null){finishPending(200,Json.obj("cancelled",true,"task_ids",new JSONArray()));return;}
        String id=pendingId;JSONObject body=pendingBody;String action=pendingAction;Uri uri=data.getData();
        if(request==108){try{File file=AndroidLocations.resolve(this,uri,body.optString("kind").equals("folder"));finishPending(200,Json.obj("path",file.getPath(),"kind",body.optString("kind"),"cancelled",false));}catch(Exception error){finishPending(400,Json.obj("detail",String.valueOf(error.getMessage())));}return;}
        if(request==101){app.api.submit(()->{try{
            List<Uri> files=new ArrayList<>();if(uri!=null){try{getContentResolver().takePersistableUriPermission(uri,Intent.FLAG_GRANT_READ_URI_PERMISSION);}catch(SecurityException ignored){}if(body.optString("kind").equals("folder")){DocumentFile tree=DocumentFile.fromTreeUri(this,uri);if(tree==null)throw new IOException("Cannot read this folder");collect(tree,files,0,new int[]{0});}else files.add(uri);}
            if(data.getClipData()!=null)for(int i=0;i<data.getClipData().getItemCount();i++){Uri item=data.getClipData().getItemAt(i).getUri();try{getContentResolver().takePersistableUriPermission(item,Intent.FLAG_GRANT_READ_URI_PERMISSION);}catch(SecurityException ignored){}files.add(item);}
            JSONArray tasks=new JSONArray();for(Uri file:files){String name=filename(file);if(!name.toLowerCase(Locale.ROOT).matches(".*\\.(pdf|pptx|docx|xlsx|txt|md|csv|tsv)$"))continue;String replacement=body.optString("document_id");if(body.optBoolean("refresh_existing")&&replacement.isEmpty()){JSONArray matches=app.backend.store.query("SELECT id FROM documents WHERE folder_id=? AND filename=? AND trashed=0",body.optString("folder_id"),name);if(matches.length()>1)throw new IllegalArgumentException("Several documents share "+name+"; replace it individually");if(matches.length()==1)replacement=matches.optJSONObject(0).optString("id");}
                tasks.put(app.backend.enqueue(file.toString(),name,body.optString("folder_id"),replacement,body.optBoolean("ocr"),body.optBoolean("bill")));}
            if(tasks.length()==0)throw new IllegalArgumentException("No PDF or PPTX documents were found in this selection");finishPending(200,Json.obj("task_ids",tasks));
        }catch(Exception error){finishPending(400,Json.obj("detail",String.valueOf(error.getMessage())));}});
        }else if(request==103||request==104){app.api.submit(()->{try{NativeTransfer transfer=new NativeTransfer(app.backend);if(action.equals("diagnostics"))try(OutputStream out=getContentResolver().openOutputStream(uri)){out.write(app.backend.features.diagnostics().toString(2).getBytes(java.nio.charset.StandardCharsets.UTF_8));}else if(action.equals("backup"))try(OutputStream out=getContentResolver().openOutputStream(uri)){transfer.backup(out,body.optString("password"));}else if(action.equals("embeddings")){File staged=File.createTempFile("khoj-embeddings-",".zip",getCacheDir());try{try(OutputStream out=new FileOutputStream(staged)){EmbeddingExport.write(app.backend,out);}try(InputStream in=new FileInputStream(staged);OutputStream out=getContentResolver().openOutputStream(uri)){NativeTransfer.copy(in,out);}}finally{staged.delete();}}else if(action.equals("export"))try(OutputStream out=getContentResolver().openOutputStream(uri)){transfer.export(body,out);}else try(InputStream in=getContentResolver().openInputStream(uri)){transfer.restore(in,body.optString("password"));}finishPending(200,Json.obj("saved",true));}catch(Exception error){finishPending(400,Json.obj("detail",String.valueOf(error.getMessage())));}});}
    }
    void finishPending(int status,Object result){String id=pendingId;pendingId=null;pendingBody=null;pendingAction=null;if(id!=null)resolve(id,status,result);}
    void share(String path){try{String[] pieces=path.split("/");File file=app.backend.store.source(pieces[3],path.endsWith("/original"));Uri uri=androidx.core.content.FileProvider.getUriForFile(this,getPackageName()+".files",file);Intent intent=new Intent(Intent.ACTION_VIEW).setDataAndType(uri,sourceMime(file.getName())).addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);startActivity(intent);}catch(Exception e){new AlertDialog.Builder(this).setMessage("No compatible viewer is available. Use the in-app source viewer.").setPositiveButton("OK",null).show();}}
    @Override public void onRequestPermissionsResult(int request,String[] permissions,int[] grant){super.onRequestPermissionsResult(request,permissions,grant);if(request==110)return;if(request==109){boolean allowed=grant.length>0&&grant[0]==PackageManager.PERMISSION_GRANTED;finishPending(200,Json.obj("granted",allowed,"message",allowed?"Indexing notifications are on.":"Notifications are off. Progress and pause controls still work inside PaperVault."));return;}if(request==106){if(app.backend.phoneScan.hasAccess()){completePhoneScan();}else finishPending(200,Json.obj("permission",false));return;}if(request==AndroidVoiceInput.MICROPHONE_PERMISSION&&voiceInput!=null)voiceInput.permissionResult(grant.length>0&&grant[0]==PackageManager.PERMISSION_GRANTED);}
    @Override protected void onDestroy(){for(java.util.concurrent.FutureTask<Void> task:cancellableSearches.values())task.cancel(true);cancellableSearches.clear();AndroidSharing.detach(this);pageReady=false;if(voiceInput!=null){voiceInput.close();voiceInput=null;}web.removeJavascriptInterface("AndroidLibrary");web.destroy();super.onDestroy();}
}
