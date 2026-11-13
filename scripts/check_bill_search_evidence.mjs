import fs from 'node:fs';
import {execFileSync} from 'node:child_process';
import path from 'node:path';
const root=process.cwd();
const adb=path.join(root,'.cache/android-tools/sdk/platform-tools/adb.exe');
const serial='emulator-5580';
const run=(...args)=>execFileSync(adb,['-s',serial,...args],{encoding:'utf8'}).trim();
let pid='';
for(let attempt=0;attempt<40&&!pid;attempt++){
 try{pid=run('shell','pidof','org.localknowledge.library');}catch{}
 if(!pid)await new Promise(r=>setTimeout(r,250));
}
if(!pid)throw Error('App did not start');
run('forward','tcp:9227','localabstract:webview_devtools_remote_'+pid);
let target;
for(let attempt=0;attempt<40&&!target;attempt++){
 try{const targets=await(await fetch('http://127.0.0.1:9227/json')).json();target=targets.find(t=>t.url?.includes('appassets.androidplatform.net'));}catch{}
 if(!target)await new Promise(r=>setTimeout(r,250));
}
if(!target)throw Error('App WebView not found');
const socket=new WebSocket(target.webSocketDebuggerUrl);
await new Promise((ok,bad)=>{socket.onopen=ok;socket.onerror=bad;});
let sequence=0;const pending=new Map();const errors=[];
socket.onmessage=event=>{const message=JSON.parse(event.data);if(message.id){const request=pending.get(message.id);if(request){pending.delete(message.id);message.error?request.bad(Error(JSON.stringify(message.error))):request.ok(message.result);}}else if(message.method==='Runtime.exceptionThrown')errors.push(message.params.exceptionDetails.text);};
function command(method,params={}){return new Promise((ok,bad)=>{const id=++sequence;pending.set(id,{ok,bad});socket.send(JSON.stringify({id,method,params}));});}
async function evaluate(expression){const response=await command('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true,userGesture:true});if(response.exceptionDetails)throw Error(JSON.stringify(response.exceptionDetails));return response.result.value;}
async function wait(expression,timeout=60000){const start=Date.now();while(Date.now()-start<timeout){if(await evaluate(expression))return;await new Promise(r=>setTimeout(r,200));}throw Error('UI did not settle: '+expression);}
await command('Runtime.enable');
await wait('Boolean(document.querySelector(".mobile-navigation"))');
const label=process.argv[2]||'current',output=path.join(root,'results/bill-search-ui',label);fs.mkdirSync(output,{recursive:true});
const state=await evaluate('(async()=>await(await fetch("/api/state")).json())()');
const folders=state.folders.filter(f=>f.name.startsWith('Synthetic Android test ')).sort((a,b)=>b.name.localeCompare(a.name));
if(!folders.length)throw Error('No synthetic Android UI collection available');
const prefix=`folder:"${folders[0].name}" `;
await evaluate(`document.querySelectorAll('.mobile-navigation button')[0].click()`);
await wait('Boolean(document.querySelector("form.search-box input"))');
const report={fontScale:run('shell','settings','get','system','font_scale'),screens:[],errors};
for(const [kind,query] of [['exact','total exactly 29000'],['nearby','total 28800']]){
 await evaluate(`(()=>{const input=document.querySelector('form.search-box input');Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(input,${JSON.stringify(prefix+query)});input.dispatchEvent(new Event('input',{bubbles:true}));})()`);
 await evaluate(`document.querySelector('form.search-box').requestSubmit()`);
 await wait(`Array.from(document.querySelectorAll('.match-evidence strong')).some(e=>e.textContent.startsWith(${JSON.stringify(kind==='exact'?'Exact total':'Nearby total')}))`);
 await evaluate(`document.querySelector('.match-evidence').scrollIntoView({block:'center'});document.activeElement?.blur()`);
 await new Promise(r=>setTimeout(r,750));
 const screen=await evaluate(`(()=>{const panels=Array.from(document.querySelectorAll('.match-evidence'));return {width:innerWidth,pageWidth:document.documentElement.scrollWidth,labels:panels.map(p=>p.querySelector('strong').textContent),details:panels.map(p=>p.querySelector('p').textContent),clipped:panels.some(p=>p.scrollWidth>p.clientWidth+1)};})()`);
 screen.kind=kind;report.screens.push(screen);
 fs.writeFileSync(path.join(output,kind+'.png'),execFileSync(adb,['-s',serial,'exec-out','screencap','-p']));
 if(kind==='nearby'&&!screen.details.some(s=>s.includes('Difference: +200.00')&&s.includes('not an exact match')))throw Error('Nearby difference is not visible');
}
report.passed=errors.length===0&&report.screens.every(s=>!s.clipped&&s.pageWidth<=s.width+1);
fs.writeFileSync(path.join(output,'report.json'),JSON.stringify(report,null,2));socket.close();console.log(JSON.stringify(report,null,2));if(!report.passed)process.exitCode=1;
