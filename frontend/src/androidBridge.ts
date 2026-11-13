declare global {
 interface Window {
  AndroidLibrary?:{request:(id:string,path:string,method:string,body:string)=>void;cancel?:(id:string)=>void;exit:()=>void};
  __androidResolve?:(id:string,status:number,body:string)=>void;
 }
}

export const isAndroid=()=>!!window.AndroidLibrary;

export function installAndroidBridge(){
 if(!window.AndroidLibrary)return;
 const fetchOriginal=window.fetch.bind(window);
 const pending=new Map<string,{resolve:(value:Response)=>void;reject:(error:Error)=>void;timer:ReturnType<typeof setTimeout>;cleanup:()=>void}>();
 window.__androidResolve=(id,status,body)=>{const request=pending.get(id);if(!request)return;clearTimeout(request.timer);request.cleanup();pending.delete(id);request.resolve(new Response(body,{status,headers:{'Content-Type':'application/json'}}));};
 window.fetch=(input:RequestInfo|URL,init?:RequestInit)=>{
  const url=new URL(typeof input==='string'?input:input instanceof URL?input.href:input.url,window.location.href);
  if(url.origin!==window.location.origin||!url.pathname.startsWith('/api/')||/\/(file|original|preview)$/.test(url.pathname))return fetchOriginal(input,init);
  if(init?.body instanceof FormData)return Promise.reject(new Error('Use the Android file picker for this action.'));
  return new Promise<Response>((resolve,reject)=>{const id=crypto.randomUUID(),signal=init?.signal;
   if(signal?.aborted){reject(new DOMException('Request cancelled','AbortError'));return;}
   const abort=()=>{const request=pending.get(id);if(!request)return;clearTimeout(request.timer);request.cleanup();pending.delete(id);window.AndroidLibrary?.cancel?.(id);reject(new DOMException('Request cancelled','AbortError'));};
   const cleanup=()=>signal?.removeEventListener('abort',abort);
   const timer=setTimeout(()=>{cleanup();pending.delete(id);window.AndroidLibrary?.cancel?.(id);reject(new Error('The local action did not finish. Check indexing activity.'));},15*60*1000);
   pending.set(id,{resolve,reject,timer,cleanup});signal?.addEventListener('abort',abort,{once:true});
   window.AndroidLibrary!.request(id,url.pathname+url.search,init?.method||'GET',typeof init?.body==='string'?init.body:'{}');
  });
 };
 document.documentElement.classList.add('android');
}
