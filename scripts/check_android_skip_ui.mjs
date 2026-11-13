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
const before=await api('/state'),paused=before.processing.paused;
const names=[];const output=path.join(root,'results/android-skip-ui');fs.mkdirSync(output,{recursive:true});
try{
 await api('/phone-scan/pause','POST',{paused:true});
 const stamp=Date.now();
 for(let i=1;i<=2;i++){
  const name=`Khoj-skip-ui-${stamp}-${i}.pdf`;names.push(name);const file=path.join(root,'.cache',name);
  execFileSync(path.join(root,'.venv/Scripts/python.exe'),['-c','import pymupdf,sys; p=pymupdf.open(); p.new_page().insert_text((40,60),sys.argv[2]); p.save(sys.argv[1]); p.close()',file,'Skip verification '+name]);
  run('push',file,'/data/local/tmp/'+name);run('shell','run-as','org.localknowledge.library','mkdir','-p','cache/exports');run('shell','run-as','org.localknowledge.library','cp','/data/local/tmp/'+name,'cache/exports/'+name);
  run('shell','am','start','-W','-a','android.intent.action.SEND','-t','application/pdf','--eu','android.intent.extra.STREAM','content://org.localknowledge.library.files/exports/'+name,'-n','org.localknowledge.library/.MainActivity');
 }
 await wait(`(async()=>{const s=await(await fetch('/api/state')).json();return ${JSON.stringify(names)}.every(n=>s.tasks.some(t=>t.filename===n&&['queued','running'].includes(t.status)));})()`);
 await wait('Boolean(document.querySelector(".indexing-pill"))');await evaluate('document.querySelector(".indexing-pill").click()');
 await wait('document.querySelectorAll(".task-row").length>0');
 for(const name of names.slice().reverse()){
  await wait(`Array.from(document.querySelectorAll('.task-row')).some(r=>r.querySelector('strong')?.textContent===${JSON.stringify(name)}&&Array.from(r.querySelectorAll('button')).some(b=>b.textContent==='Skip this file'))`);
  await evaluate(`(()=>{const row=Array.from(document.querySelectorAll('.task-row')).find(r=>r.querySelector('strong')?.textContent===${JSON.stringify(name)});Array.from(row.querySelectorAll('button')).find(b=>b.textContent==='Skip this file').click();})()`);
  await wait(`(async()=>{const s=await(await fetch('/api/state')).json();return s.tasks.find(t=>t.filename===${JSON.stringify(name)})?.status==='skipped';})()`);
 }
 await wait(`Array.from(document.querySelectorAll('.task-row')).filter(r=>${JSON.stringify(names)}.includes(r.querySelector('strong')?.textContent)).every(r=>Array.from(r.querySelectorAll('button')).some(b=>b.textContent==='Retry'))`);
 const after=await api('/state');if(after.documents.some(d=>names.includes(d.filename)))throw Error('Skipped fixture was published');
 if(errors.length)throw Error(JSON.stringify(errors));
 fs.writeFileSync(path.join(output,'file-progress.png'),execFileSync(adb,['-s',serial,'exec-out','screencap','-p']));
 const report={checks:['Android File progress displays Skip this file','Queued and active paused files become skipped through the visible button','Retry is visible after Skip','Skipped fixture documents were never published'],tasks:after.tasks.filter(t=>names.includes(t.filename)).map(t=>({filename:t.filename,status:t.status})),errors};
 fs.writeFileSync(path.join(output,'report.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report,null,2));
}finally{await api('/phone-scan/pause','POST',{paused});socket.close();}
