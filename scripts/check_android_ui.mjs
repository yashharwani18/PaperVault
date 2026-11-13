import fs from 'node:fs';
import {execFileSync} from 'node:child_process';
import path from 'node:path';
const root=process.cwd();
const adb=path.join(root,'.cache/android-tools/sdk/platform-tools/adb.exe');
const serial='emulator-5580';
const run=(...args)=>execFileSync(adb,['-s',serial,...args],{encoding:'utf8'}).trim();
const pid=run('shell','pidof','org.localknowledge.library');
run('forward','tcp:9227','localabstract:webview_devtools_remote_'+pid);
const targets=await(await fetch('http://127.0.0.1:9227/json')).json();
const target=targets.find(t=>t.url?.includes('appassets.androidplatform.net'));
if(!target)throw Error('App WebView not found');
const socket=new WebSocket(target.webSocketDebuggerUrl);
await new Promise((ok,bad)=>{socket.onopen=ok;socket.onerror=bad;});
let sequence=0;const pending=new Map();const errors=[];
socket.onmessage=event=>{const message=JSON.parse(event.data);if(message.id){const request=pending.get(message.id);if(request){pending.delete(message.id);message.error?request.bad(Error(JSON.stringify(message.error))):request.ok(message.result);}}else if(message.method==='Runtime.exceptionThrown')errors.push(message.params.exceptionDetails.text);};
function command(method,params={}){return new Promise((ok,bad)=>{const id=++sequence;pending.set(id,{ok,bad});socket.send(JSON.stringify({id,method,params}));});}
async function evaluate(expression){const response=await command('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true,userGesture:true});if(response.exceptionDetails)throw Error(JSON.stringify(response.exceptionDetails));return response.result.value;}
async function wait(expression,timeout=60000){const start=Date.now();while(Date.now()-start<timeout){if(await evaluate(expression))return;await new Promise(r=>setTimeout(r,200));}throw Error('UI did not settle: '+expression);}
await command('Runtime.enable');
await wait('Boolean(window.__androidResolve)&&document.readyState==="complete"');
const state=await evaluate('(async()=>await(await fetch("/api/state")).json())()');
const report={device:'Android 15 x86-64 emulator, 3072 MiB RAM',webview:target.title,models:state.semantic_status,documents:state.documents.length,errors};
const output=path.join(root,'results/android-qa');fs.mkdirSync(output,{recursive:true});
fs.writeFileSync(path.join(output,'home.png'),execFileSync(adb,['-s',serial,'exec-out','screencap','-p']));
// Select the newest synthetic test collection and keep both result tiers visible.
const folders=state.folders.filter(f=>f.name.startsWith('Synthetic Android test ')).sort((a,b)=>b.created_at.localeCompare(a.created_at));
if(!folders.length)throw Error('Run Android integration tests before UI checks');
const folder=folders[0];const docs=state.documents.filter(d=>d.folder_id===folder.id);
await evaluate(`document.querySelector('[aria-label="Khoj home"]').click()`);await wait(`document.querySelectorAll('.folder-open').length>0`);
for(const doc of docs){if(doc.filename==='synthetic-exact.pdf')await evaluate(`(async()=>await(await fetch('/api/documents/${doc.id}/bill',{method:'PUT',body:JSON.stringify({party:'Synthetic Trading',bill_date:'2026-09-25',amount:'29000',currency:'INR',reviewed:false})})).json())()`);}
await evaluate(`Array.from(document.querySelectorAll('.folder-open')).find(b=>b.querySelector("strong")?.textContent===${JSON.stringify(folder.name)})?.click()`);
await wait(`Boolean(document.querySelector('input[aria-label="Search this folder"]'))`);
await evaluate(`(()=>{const input=document.querySelector('input[aria-label="Search this folder"]');const setter=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set;setter.call(input,'total about 29000');input.dispatchEvent(new Event('input',{bubbles:true}));})()`);
await evaluate(`document.querySelector('form.search-box').requestSubmit()`);
await wait(`document.querySelectorAll('.result-card').length===2`);
await wait(`Boolean(document.querySelector('.search-page-preview img')?.naturalWidth)`);
report.highlighted_preview=await evaluate(`Array.from(document.querySelectorAll('.search-page-caption')).some(e=>e.textContent.includes('Matched passage highlighted'))`);
report.scores_hidden=await evaluate(`Array.from(document.querySelectorAll('.similarity')).every(e=>!e.checkVisibility())`);
report.search=await evaluate(`(async()=>await(await fetch('/api/search',{method:'POST',body:JSON.stringify({query:'total about 29000',folder_id:${JSON.stringify(folder.id)}})})).json())()`);
report.no_horizontal_overflow=await evaluate('document.documentElement.scrollWidth<=window.innerWidth');
await evaluate(`document.querySelector('.search-page-preview')?.scrollIntoView({block:'start'})`);
fs.writeFileSync(path.join(output,'search.png'),execFileSync(adb,['-s',serial,'exec-out','screencap','-p']));
await evaluate(`Array.from(document.querySelectorAll('.result-title button')).find(b=>b.textContent.includes('synthetic-scan-columns')).click()`);
await wait(`Boolean(document.querySelector('[data-testid="pdf-canvas"][data-pdf-page="1"]'))`,45000);
report.pdf_text=await evaluate(`document.querySelector('[data-testid="pdf-page-text"]').textContent`);
report.viewer_pixels=await evaluate(`(()=>{const c=document.querySelector('[data-testid="pdf-canvas"]');return c.width*c.height;})()`);
const scan=docs.find(d=>d.filename==='synthetic-scan-columns.pdf');report.ocr_page=await evaluate(`(async()=>await(await fetch('/api/documents/${scan.id}/pages/1')).json())()`);
fs.writeFileSync(path.join(output,'viewer.png'),execFileSync(adb,['-s',serial,'exec-out','screencap','-p']));
report.passed=report.highlighted_preview&&report.scores_hidden&&report.no_horizontal_overflow&&report.viewer_pixels>0&&report.ocr_page.text.includes('29074')&&errors.length===0;
fs.writeFileSync(path.join(root,'results/android-ui.json'),JSON.stringify(report,null,2));
socket.close();console.log(JSON.stringify({passed:report.passed,errors,method:report.search.response.method,pdf_text:report.pdf_text.slice(0,80)},null,2));if(!report.passed)process.exitCode=1;
