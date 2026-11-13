import fs from 'node:fs';
import path from 'node:path';
import {execFileSync} from 'node:child_process';
const root=process.cwd(),adb=path.join(root,'.cache/android-tools/sdk/platform-tools/adb.exe');
const shell=(...args)=>execFileSync(adb,['-s','emulator-5580',...args],{encoding:'utf8'}).trim();
shell('push','tests/fixtures/bills/sale-bhagwanti-2026-09-25.pdf','/sdcard/Download/Android-picker-test.pdf');
shell('shell','am','broadcast','-a','android.intent.action.MEDIA_SCANNER_SCAN_FILE','-d','file:///sdcard/Download/Android-picker-test.pdf');
const pid=shell('shell','pidof','org.localknowledge.library');shell('forward','tcp:9227','localabstract:webview_devtools_remote_'+pid);
const target=(await(await fetch('http://127.0.0.1:9227/json')).json()).find(t=>t.url?.includes('appassets'));
const ws=new WebSocket(target.webSocketDebuggerUrl);await new Promise(r=>ws.onopen=r);let next=0;const pending=new Map();
ws.onmessage=e=>{const r=JSON.parse(e.data);const p=pending.get(r.id);if(p){pending.delete(r.id);r.error?p.bad(Error(JSON.stringify(r.error))):p.ok(r.result);}};
async function evaluate(expression){const result=await new Promise((ok,bad)=>{const id=++next;pending.set(id,{ok,bad});ws.send(JSON.stringify({id,method:'Runtime.evaluate',params:{expression,awaitPromise:true,returnByValue:true,userGesture:true}}));});if(result.exceptionDetails)throw Error(JSON.stringify(result.exceptionDetails));return result.result.value;}
const report={passed:false};
try{
 await evaluate(`document.querySelector('[aria-label="Close document viewer"]')?.click()`);
 await evaluate(`Array.from(document.querySelectorAll('button')).find(b=>b.textContent.trim()==='Add documents').click()`);
 await evaluate(`Array.from(document.querySelectorAll('button')).find(b=>b.textContent.trim()==='Choose files').click()`);
 function dump(){for(let n=0;n<12;n++){shell('shell','uiautomator','dump','/sdcard/library-picker-ui.xml');const xml=shell('shell','cat','/sdcard/library-picker-ui.xml');if(xml.includes('<hierarchy'))return xml;}throw Error('Android picker did not expose its hierarchy');}
 function node(xml,label){return [...xml.matchAll(/<node\s+[^>]*>/g)].map(m=>m[0]).find(t=>t.includes('text="'+label+'"')||t.includes('content-desc="'+label+'"'));}
 function tap(tag){if(!tag)throw Error('Picker control not found');const b=tag.match(/bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"/).slice(1).map(Number);shell('shell','input','tap',String(Math.round((b[0]+b[2])/2)),String(Math.round((b[1]+b[3])/2)));}
 let xml=dump();if(!node(xml,'Android-picker-test.pdf')){const roots=node(xml,'Show roots');if(roots){tap(roots);xml=dump();}tap(node(xml,'Downloads'));xml=dump();}
 tap(node(xml,'Android-picker-test.pdf'));
 const deadline=Date.now()+120000;let tasks=[];
 while(Date.now()<deadline){tasks=await evaluate(`(async()=>await(await fetch('/api/state')).json())().then(s=>s.tasks.filter(t=>t.filename==='Android-picker-test.pdf'))`);if(tasks.length&&tasks.every(t=>['completed','failed','interrupted'].includes(t.status)))break;await new Promise(r=>setTimeout(r,400));}
 if(!tasks.length||tasks.some(t=>t.status!=='completed'))throw Error(JSON.stringify(tasks));
 report.tasks=tasks.map(t=>({filename:t.filename,status:t.status}));
 report.passed=true;
 await evaluate(`Array.from(document.querySelectorAll('button')).find(b=>b.textContent.trim()==='Done').click()`);
 fs.writeFileSync('results/android-qa/picker-import.png',execFileSync(adb,['-s','emulator-5580','exec-out','screencap','-p']));
}catch(error){report.error=String(error);throw error;}finally{ws.close();fs.writeFileSync('results/android-picker.json',JSON.stringify(report,null,2));}
console.log(JSON.stringify(report));
