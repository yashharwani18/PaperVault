import {useEffect,useState} from 'react';
import {AlertCircle,FolderOpen,LoaderCircle,RefreshCw} from 'lucide-react';
type API=(path:string,method?:string,body?:unknown)=>Promise<Response>;
type Health={source:{code:string;message:string;actions:string[]};extraction:{code:string;message:string;page_statuses:Record<string,number>}|null;original_path:string;can_reconnect:boolean};

export default function Recovery({id,api,ocrAvailable,nativeText=false,onReplace,onChanged}:{id:string;api:API;ocrAvailable:boolean;nativeText?:boolean;onReplace:()=>void;onChanged:()=>Promise<void>}){
 const [health,setHealth]=useState<Health|null>(null),[path,setPath]=useState(''),[busy,setBusy]=useState(false),[error,setError]=useState(''),[note,setNote]=useState('');
 async function load(){setHealth(await(await api(`/documents/${id}/recovery`)).json());}
 useEffect(()=>{let alive=true;void api(`/documents/${id}/recovery`).then(r=>r.json()).then(data=>{if(alive)setHealth(data);}).catch(e=>{if(alive)setError((e as Error).message);});return()=>{alive=false;};},[id]);
 async function run(task:()=>Promise<void>){setBusy(true);setError('');setNote('');try{await task();await load();await onChanged();}catch(e){setError((e as Error).message);}finally{setBusy(false);}}
 return <div className="recovery-form" aria-busy={busy}>
  {error&&<p className="notice error" role="alert">{error}</p>}
  {!health&&!error&&<p role="status"><LoaderCircle className="spin" size={16}/>Checking the original document…</p>}
  {health&&<><p className="recovery-explanation"><AlertCircle size={18}/>{health.source.message}</p><p className="recovery-path">Expected location: <span>{health.original_path}</span></p>
   <button className="button secondary" disabled={busy} onClick={()=>void run(async()=>{await load();})}><RefreshCw size={15}/>Check again</button>
   {health.source.code!=='available'&&health.can_reconnect&&<form onSubmit={e=>{e.preventDefault();void run(async()=>{await api(`/documents/${id}/reconnect`,'POST',{path});setPath('');setNote('Original reconnected. You can open its source again.');});}}>
    <label className="field-label">Locate the same file<input value={path} onChange={e=>setPath(e.target.value)} placeholder="Paste its new full path" required disabled={busy}/></label>
    <div className="recovery-actions"><button type="button" className="button secondary" disabled={busy} onClick={()=>void run(async()=>{const result=await(await api('/recovery/pick','POST')).json();if(result.path)setPath(result.path);})}><FolderOpen size={15}/>Choose file</button><button className="button primary" disabled={busy||!path.trim()}>Reconnect original</button></div>
    <p className="subtle">The contents must match the indexed file. The original stays in place.</p>
   </form>}
   {health.extraction&&<div className="recovery-extraction"><h3>Text extraction needs attention</h3><p>{health.extraction.message}</p><p className="subtle">{Object.entries(health.extraction.page_statuses).filter(([status])=>['needs_ocr','extraction_failed','empty'].includes(status)).map(([status,count])=>`${count} ${status==='needs_ocr'?'scanned':status==='empty'?'empty':'unreadable'} ${nativeText?'section':'page'}${count===1?'':'s'}`).join(' · ')}</p>
   {!nativeText&&!ocrAvailable&&<p className="subtle">OCR is unavailable in this installation. Add a PDF with selectable text, or install English OCR support.</p>}</div>}
   {(health.source.code==='available'||health.source.code==='changed')&&<div className="recovery-actions"><button className="button secondary" disabled={busy} onClick={()=>void run(async()=>{await api(`/documents/${id}/refresh`,'POST');setNote('Extraction retry queued. Follow its progress in Indexing history.');})}>Retry extraction</button>{health.extraction&&!nativeText&&ocrAvailable&&<button className="button primary" disabled={busy} onClick={()=>void run(async()=>{await api(`/documents/${id}/refresh-ocr`,'POST');setNote('OCR queued. Scanned pages may take longer; follow progress in Indexing history.');})}>Read scanned pages with OCR</button>}</div>}
   <button className="text-button" disabled={busy} onClick={onReplace}>Replace with a repaired or updated document</button>
  </>}
  {note&&<p className="notice" role="status">{note}</p>}
 </div>;
}

export function TaskRecovery({task,api,onChanged,onDocument,onAdd}:{task:{id:string;document_id?:string|null;error:string|null;recovery?:{message:string;actions:string[]}},api:API;onChanged:()=>Promise<void>;onDocument:(id:string)=>void;onAdd:()=>void}){
 const [busy,setBusy]=useState(false),[error,setError]=useState('');
 return <div className="task-recovery"><p>{task.recovery?.message||'Indexing did not finish. Retry when the source is available.'}</p><div className="recovery-actions"><button className="button small secondary" disabled={busy} onClick={async()=>{setBusy(true);setError('');try{await api(`/tasks/${task.id}/retry`,'POST');await onChanged();}catch(e){setError((e as Error).message);}finally{setBusy(false);}}}>{busy?'Queuing…':'Retry indexing'}</button>{task.document_id?<button className="text-button" onClick={()=>onDocument(task.document_id!)}>Fix source or extraction</button>:<button className="text-button" onClick={onAdd}>Add a repaired copy</button>}</div>{error&&<p className="notice error" role="alert">{error}</p>}{task.error&&<details><summary>Technical details</summary><p>{task.error}</p></details>}</div>;
}
