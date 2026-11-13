import fs from 'node:fs';
import path from 'node:path';
import {execFileSync} from 'node:child_process';
const root=process.cwd(),adb=path.join(root,'.cache/android-tools/sdk/platform-tools/adb.exe'),serial='emulator-5580';
const run=(...args)=>execFileSync(adb,['-s',serial,...args],{encoding:'utf8'}).trim();
const pid=run('shell','pidof','org.localknowledge.library');run('forward','tcp:9227','localabstract:webview_devtools_remote_'+pid);
const target=(await(await fetch('http://127.0.0.1:9227/json')).json()).find(t=>t.url?.includes('appassets'));
if(!target)throw Error('No Android WebView');
const socket=new WebSocket(target.webSocketDebuggerUrl);await new Promise((ok,bad)=>{socket.onopen=ok;socket.onerror=bad;});
const pending=new Map(),errors=[];let sequence=0;
socket.onmessage=e=>{const m=JSON.parse(e.data);if(m.id){const p=pending.get(m.id);if(p){pending.delete(m.id);m.error?p.bad(Error(JSON.stringify(m.error))):p.ok(m.result);}}else if(m.method==='Runtime.exceptionThrown')errors.push(m.params.exceptionDetails.text);};
function command(method,params={}){return new Promise((ok,bad)=>{const id=++sequence;pending.set(id,{ok,bad});socket.send(JSON.stringify({id,method,params}));});}
async function evaluate(expression){const r=await command('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true,userGesture:true});if(r.exceptionDetails)throw Error(JSON.stringify(r.exceptionDetails));return r.result.value;}
async function wait(expression,timeout=20000){const start=Date.now();while(Date.now()-start<timeout){if(await evaluate(expression))return;await new Promise(r=>setTimeout(r,200));}throw Error('Timed out: '+expression);}
const api=(route,method='GET',body={})=>evaluate(`(async()=>{const r=await fetch('/api'+${JSON.stringify(route)},{method:${JSON.stringify(method)},body:${method==='GET'?'undefined':JSON.stringify(JSON.stringify(body))}});if(!r.ok)throw Error(await r.text());return await r.json();})()`);
await command('Runtime.enable');await wait('Boolean(window.__androidResolve)&&document.readyState==="complete"');
const output=path.join(root,'results/android-voice-ui');fs.mkdirSync(output,{recursive:true});
const mic=`document.querySelector('button[aria-label="Voice search"]')`;
await wait(`Boolean(${mic})`);
await evaluate(`(()=>{const input=document.querySelector('.search-box input');const setter=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set;setter.call(input,'my existing query');input.dispatchEvent(new Event('input',{bubbles:true}));})()`);
const capabilities=(await api('/state')).voice;
await evaluate(`${mic}.click()`);
await new Promise(r=>setTimeout(r,1800));
run('shell','uiautomator','dump','/sdcard/voice-dialog.xml');
const native=run('shell','cat','/sdcard/voice-dialog.xml');fs.writeFileSync(path.join(output,'native-dialog.xml'),native);
fs.writeFileSync(path.join(output,'native-dialog.png'),execFileSync(adb,['-s',serial,'exec-out','screencap','-p']));
if(!/speech|Speak|Voice|microphone|audio|Google|record/i.test(native))throw Error('Speech dialog did not open');
run('shell','input','keyevent','4');
await wait(`!${mic}.disabled`);
const preserved=await evaluate('document.querySelector(".search-box input").value');if(preserved!=='my existing query')throw Error('Cancellation replaced query: '+preserved);
// Controlled provider response checks the editable transcript UI, not speech accuracy.
await evaluate(`(()=>{const original=window.fetch;window.__voiceSearchCalls=0;window.fetch=(input,init)=>{if(String(input).endsWith('/native/voice'))return Promise.resolve(new Response(JSON.stringify({transcript:'find Fourier notes',speech_mode:'android_service',offline_guaranteed:false}),{status:200}));if(String(input).endsWith('/search'))window.__voiceSearchCalls++;return original(input,init);};})()`);
await evaluate(`${mic}.click()`);
await wait('document.querySelector(".search-box input").value==="find Fourier notes"');
const autoSearch=await evaluate('window.__voiceSearchCalls');if(autoSearch!==0)throw Error('Voice submitted without review');
if(!await evaluate('document.querySelector(".voice-notice")?.textContent.includes("internet")'))throw Error('Fallback privacy note absent');
fs.writeFileSync(path.join(output,'transcript.png'),execFileSync(adb,['-s',serial,'exec-out','screencap','-p']));
const report={capabilities,checks:['Visible microphone opens native Android speech UI','Back cancels and preserves existing query','Controlled transcript fills editable search box','No automatic search','Fallback internet disclosure visible'],actualAudioRecognitionTested:false,errors};
fs.writeFileSync(path.join(output,'report.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report,null,2));
socket.close();
