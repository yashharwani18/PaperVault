import fs from 'node:fs';
import path from 'node:path';
import {execFileSync} from 'node:child_process';
const root=process.cwd(),adb=path.join(root,'.cache/android-tools/sdk/platform-tools/adb.exe');
const run=(...args)=>execFileSync(adb,['-s','emulator-5580',...args],{encoding:'utf8'}).trim();
const proof='Khoj-whole-phone-'+Date.now()+'.pdf';
const generated=path.join(root,'.cache',proof);
execFileSync(path.join(root,'.venv/Scripts/python.exe'),['-c','import pymupdf,sys; p=pymupdf.open(); p.new_page().insert_text((40,60),sys.argv[2]); p.save(sys.argv[1]); p.close()',generated,'Whole phone discovery '+proof]);
run('push',generated,'/sdcard/Download/'+proof);
run('shell','am','force-stop','com.android.settings');
run('shell','am','force-stop','org.localknowledge.library');
run('shell','appops','set','--uid','org.localknowledge.library','MANAGE_EXTERNAL_STORAGE','deny');
run('shell','am','start','-W','-n','org.localknowledge.library/.MainActivity');
const pid=run('shell','pidof','org.localknowledge.library');run('forward','tcp:9227','localabstract:webview_devtools_remote_'+pid);
let target;for(let i=0;i<30;i++){try{target=(await(await fetch('http://127.0.0.1:9227/json')).json()).find(t=>t.url?.includes('appassets'));if(target)break;}catch{}await new Promise(r=>setTimeout(r,200));}if(!target)throw Error('No Android test WebView');
const ws=new WebSocket(target.webSocketDebuggerUrl);await new Promise(r=>ws.onopen=r);let next=0;const pending=new Map();
ws.onmessage=e=>{const r=JSON.parse(e.data),p=pending.get(r.id);if(p){pending.delete(r.id);r.error?p.bad(Error(JSON.stringify(r.error))):p.ok(r.result);}};
async function evaluate(expression){const r=await new Promise((ok,bad)=>{const id=++next;pending.set(id,{ok,bad});ws.send(JSON.stringify({id,method:'Runtime.evaluate',params:{expression,awaitPromise:true,returnByValue:true,userGesture:true}}));});if(r.exceptionDetails)throw Error(JSON.stringify(r.exceptionDetails));return r.result.value;}
async function wait(expression,timeout=120000){const start=Date.now();while(Date.now()-start<timeout){if(await evaluate(expression))return;await new Promise(r=>setTimeout(r,250));}throw Error('Timeout: '+expression);}
const api=(route,method='GET',body={})=>evaluate(`(async()=>await(await fetch('/api'+${JSON.stringify(route)},{method:${JSON.stringify(method)},body:${method==='GET'?'undefined':JSON.stringify(JSON.stringify(body))}})).json())()`);
const report={passed:false,emulator_only:true};
try{
 await wait('Boolean(document.querySelector(".phone-scan button"))');
 const before=await api('/phone-scan');if(before.permission)throw Error('Permission not denied');
 const storage=await api('/maintenance');
 await evaluate(`document.querySelector('.phone-scan button').click()`);
 let xml='';for(let i=0;i<12;i++){run('shell','uiautomator','dump','/sdcard/phone-access-ui.xml');xml=run('shell','cat','/sdcard/phone-access-ui.xml');if(xml.includes('Allow access to manage all files'))break;}
 const nodes=[...xml.matchAll(/<node\s+[^>]*>/g)].map(m=>m[0]);const node=nodes.find(n=>n.includes('switch_widget')||n.includes('android.widget.Switch'))||nodes.find(n=>{const b=n.match(/bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"/);return n.includes('clickable="true"')&&b&&Number(b[3])-Number(b[1])>500&&Number(b[2])>300;});
 if(!node)throw Error('Android all-files switch not found');
 const bounds=node.match(/bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"/).slice(1).map(Number);
 run('shell','input','tap',String(Math.round((bounds[0]+bounds[2])/2)),String(Math.round((bounds[1]+bounds[3])/2)));
 run('shell','input','keyevent','4');
 await wait(`(async()=>{const s=await(await fetch('/api/phone-scan')).json();return s.permission&&s.choice==='yes';})()`);
 await api('/phone-scan/pause','POST',{paused:true});if(!(await api('/phone-scan')).paused)throw Error('Pause did not apply');
 await api('/phone-scan/pause','POST',{paused:false});
 await wait(`(async()=>{const s=await(await fetch('/api/phone-scan')).json();return !s.finding&&!s.pending&&s.found>=2;})()`);
 const after=await api('/phone-scan'),afterStorage=await api('/maintenance');
 const state=await api('/state');if(!state.documents.some(d=>d.filename===proof&&d.source_mode==='reference'))throw Error('A new PDF outside the chosen test folder was not discovered in place');
 report.new_download_pdf_found_in_place=true;
 if(afterStorage.managed_pdf_bytes!==storage.managed_pdf_bytes)throw Error('Phone scan copied PDF bytes into managed storage');
 report.permission_screen_verified=true;report.full_shared_storage_scan=true;report.pause_resume=true;report.originals_not_copied=true;report.found=after.found;report.counts=after.counts;report.elapsed_s=after.elapsed_s;
 fs.mkdirSync('results/phone-scan-ui',{recursive:true});
 await evaluate(`document.querySelector('.phone-scan').scrollIntoView({block:'start'})`);
 fs.writeFileSync('results/phone-scan-ui/scan.png',execFileSync(adb,['-s','emulator-5580','exec-out','screencap','-p']));
 report.passed=true;
}finally{ws.close();fs.writeFileSync('results/phone-scan-ui.json',JSON.stringify(report,null,2));}
console.log(JSON.stringify(report,null,2));
