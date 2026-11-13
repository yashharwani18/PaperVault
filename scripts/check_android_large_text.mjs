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
const label=process.argv[2]||'current';
const output=path.join(root,'results','android-large-text',label);fs.mkdirSync(output,{recursive:true});
await wait('Boolean(document.querySelector(".mobile-navigation"))');
const report={label,fontScale:run('shell','settings','get','system','font_scale'),screens:[],errors};
async function inspect(name,keepScroll=false){
 await evaluate('document.activeElement?.blur();'+(keepScroll?'':'window.scrollTo(0,0)'));
 await new Promise(r=>setTimeout(r,750));
 const metrics=await evaluate(`(()=>{
  const visible=e=>e.checkVisibility()&&!e.closest('[inert]');
  const controls=Array.from(document.querySelectorAll('button,select')).filter(visible);
  const overflow=controls.filter(e=>e.clientWidth>0&&e.scrollWidth>e.clientWidth+2).map(e=>({text:e.textContent.trim().slice(0,70),class:e.className,width:e.clientWidth,content:e.scrollWidth}));
  const input=Array.from(document.querySelectorAll('.search-box input')).find(visible),style=input&&getComputedStyle(input);
  const searchInputFits=!input||input.clientHeight>=parseFloat(style.fontSize)*1.2+parseFloat(style.paddingTop)+parseFloat(style.paddingBottom);
  const titles=Array.from(document.querySelectorAll('.document-main strong')).filter(visible);
  const clippedTitles=titles.filter(e=>e.scrollHeight>e.clientHeight+2).length;
  const clippedPanels=Array.from(document.querySelectorAll('.dialog,.viewer-header,.pdf-toolbar')).filter(visible).filter(e=>e.scrollWidth>e.clientWidth+2).map(e=>e.className);
  const reader=document.querySelector('.pdf-reader-shell'),readerHeight=reader?.getBoundingClientRect().height;
  const readerHasSpace=!reader||readerHeight>=Math.min(100,innerHeight*.2);
  return {width:innerWidth,pageWidth:document.documentElement.scrollWidth,overflow,clippedPanels,clippedTitles,documentRows:titles.length,searchInputFits,readerHasSpace,readerHeight,searchFont:style?.fontSize,searchHeight:input?.clientHeight};
 })()`);
 report.screens.push({name,...metrics});
 fs.writeFileSync(path.join(output,name+'.png'),execFileSync(adb,['-s',serial,'exec-out','screencap','-p']));
}
await evaluate(`document.querySelectorAll('.mobile-navigation button')[0].click()`);
await inspect('search');
await evaluate(`document.querySelector('.heading-actions button').click()`);
await wait(`Boolean(document.querySelector('.dialog'))`);await inspect('add-files');
await evaluate(`document.querySelector('.dialog-actions').scrollIntoView({block:'end'})`);
// Inspect the scrollable dialog's final actions, as well as its initial content.
await inspect('add-files-actions');
await evaluate(`document.querySelector('[aria-label="Close dialog"]').click()`);
await evaluate(`document.querySelectorAll('.mobile-navigation button')[1].click()`);
await wait(`Boolean(document.querySelector('.document-filter'))`);await inspect('documents');
if(await evaluate(`Boolean(document.querySelector('.document-row'))`)){
 await evaluate(`document.querySelector('.document-list').scrollIntoView({block:'start'})`);
 await inspect('file-list',true);
 await evaluate(`document.querySelector('.document-main').click()`);
 await wait(`Boolean(document.querySelector('.viewer-header'))`);await inspect('viewer');
 await evaluate(`document.querySelector('[aria-label="Close document viewer"]').click()`);
}
await evaluate(`document.querySelector('[aria-label="More navigation"]').click()`);
await wait(`Boolean(document.querySelector('.mobile-open'))`);await inspect('navigation');
await evaluate(`Array.from(document.querySelectorAll('.sidebar button')).find(e=>e.textContent.trim()==='Settings').click()`);
await wait(`Boolean(document.querySelector('.simple-settings'))`);await inspect('settings');
report.passed=errors.length===0&&report.screens.every(s=>s.pageWidth<=s.width+1&&s.overflow.length===0&&s.clippedPanels.length===0&&s.clippedTitles===0&&s.searchInputFits&&s.readerHasSpace);
fs.writeFileSync(path.join(output,'report.json'),JSON.stringify(report,null,2));
socket.close();console.log(JSON.stringify(report,null,2));if(!report.passed)process.exitCode=1;
