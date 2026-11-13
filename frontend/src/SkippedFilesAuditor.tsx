import {useEffect,useState} from 'react';
import {AlertCircle,RefreshCw,FileQuestion,ShieldAlert,FolderSync} from 'lucide-react';

type AuditorData={
 summary:{
  total_skipped:number;
  needs_ocr:number;
  unreadable_or_corrupt:number;
  partial:number;
  access_denied:number;
 };
 documents:{
  id:string;
  folder_id:string;
  folder_name:string;
  filename:string;
  title:string;
  status:string;
  page_count:number;
  chunk_count:number;
  reason:string;
  suggested_action:string;
 }[];
 tasks:{
  task_id:string;
  filename:string;
  folder_id:string;
  status:string;
  error:string;
  created_at:string;
 }[];
 discovered:{
  relative_path:string;
  folder_name:string;
  folder_root:string;
  error:string;
 }[];
};

type Props={
 api:(path:string,method?:string,body?:unknown)=>Promise<Response>;
 onRecovery?:(id:string)=>void;
 onRefresh?:()=>void;
};

export default function SkippedFilesAuditor({api,onRecovery,onRefresh}:Props){
 const [data,setData]=useState<AuditorData|null>(null);
 const [loading,setLoading]=useState(false);
 const [open,setOpen]=useState(false);
 const [actioning,setActioning]=useState<string|null>(null);
 const [message,setMessage]=useState('');

 async function load(){
  setLoading(true);
  try{
   const res=await(await api('/auditor/skipped-files')).json() as AuditorData;
   setData(res);
  }catch(e){
   setMessage((e as Error).message);
  }finally{
   setLoading(false);
  }
 }

 useEffect(()=>{void load();},[]);

 if(!data||data.summary.total_skipped===0)return null;

 return <div className="skipped-auditor-card">
  <div className="auditor-header" onClick={()=>setOpen(!open)}>
   <div className="auditor-title">
    <AlertCircle size={18} className="amber"/>
    <div>
     <strong>File Auditor · {data.summary.total_skipped} {data.summary.total_skipped===1?'file':'files'} need attention</strong>
     <p>See why files weren't fully read and how to fix them.</p>
    </div>
   </div>
   <div className="auditor-chips">
    {data.summary.needs_ocr>0&&<span className="auditor-chip chip-ocr">{data.summary.needs_ocr} need OCR</span>}
    {data.summary.unreadable_or_corrupt>0&&<span className="auditor-chip chip-error">{data.summary.unreadable_or_corrupt} failed/unreadable</span>}
    {data.summary.access_denied>0&&<span className="auditor-chip chip-warn">{data.summary.access_denied} access locked</span>}
    <button className="text-button" type="button">{open?'Collapse':'Inspect'}</button>
   </div>
  </div>

  {open&&<div className="auditor-body">
   {message&&<p className="notice error">{message}</p>}
   
   {data.documents.length>0&&<div className="auditor-section">
    <h4>Unindexed Documents in Library ({data.documents.length})</h4>
    <div className="auditor-list">
     {data.documents.map(doc=><div key={doc.id} className="auditor-row">
      <div className="auditor-row-info">
       <span className="auditor-filename">{doc.filename}</span>
       <span className="auditor-reason">{doc.reason}</span>
       <small className="subtle">{doc.folder_name} · {doc.page_count} pages</small>
      </div>
      <div className="auditor-row-actions">
       {doc.suggested_action==='ocr'&&<button
        className="button secondary small"
        disabled={actioning===doc.id}
        onClick={async()=>{
         setActioning(doc.id);
         try{
          await api(`/documents/${doc.id}/refresh-ocr`,'POST');
          setMessage(`Queued OCR re-reading for ${doc.filename}`);
          await load();
          onRefresh?.();
         }catch(e){setMessage((e as Error).message);}
         finally{setActioning(null);}
        }}>
        <RefreshCw size={12}/>Re-read with OCR
       </button>}
       <button
        className="button secondary small"
        onClick={()=>onRecovery?.(doc.id)}>
        Fix extraction
       </button>
      </div>
     </div>)}
    </div>
   </div>}

   {data.tasks.length>0&&<div className="auditor-section">
    <h4>Failed Upload / Indexing Tasks ({data.tasks.length})</h4>
    <div className="auditor-list">
     {data.tasks.map(t=><div key={t.task_id} className="auditor-row">
      <div className="auditor-row-info">
       <span className="auditor-filename">{t.filename}</span>
       <span className="auditor-reason">{t.error}</span>
      </div>
      <div className="auditor-row-actions">
       <button
        className="button secondary small"
        disabled={actioning===t.task_id}
        onClick={async()=>{
         setActioning(t.task_id);
         try{
          await api(`/tasks/${t.task_id}/retry`,'POST');
          setMessage(`Retried indexing for ${t.filename}`);
          await load();
          onRefresh?.();
         }catch(e){setMessage((e as Error).message);}
         finally{setActioning(null);}
        }}>
        <RefreshCw size={12}/>Retry
       </button>
      </div>
     </div>)}
    </div>
   </div>}

   {data.discovered.length>0&&<div className="auditor-section">
    <h4>Connected Folder Scan Errors ({data.discovered.length})</h4>
    <div className="auditor-list">
     {data.discovered.map((disc,idx)=><div key={idx} className="auditor-row">
      <div className="auditor-row-info">
       <span className="auditor-filename">{disc.relative_path}</span>
       <span className="auditor-reason">{disc.error}</span>
       <small className="subtle">{disc.folder_name}</small>
      </div>
     </div>)}
    </div>
   </div>}
  </div>}
 </div>;
}
