import {useEffect,useState} from 'react';
import {ArrowRight,HardDrive,LoaderCircle,Search} from 'lucide-react';
type API=(path:string,method?:string,body?:unknown)=>Promise<Response>;
type Plan={drives:string[];choice:string|null;exclusions:string[]};
type Hardware={device:string;gpu_name:string|null;ram_bytes:number;free_disk_bytes:number;warnings:string[]};

export default function ComputerScan({api,hasConnections,ocrAvailable,onStarted,onFolders}:{api:API;hasConnections:boolean;ocrAvailable:boolean;onStarted:()=>void;onFolders:()=>void}){
 const [plan,setPlan]=useState<Plan|null>(null),[busy,setBusy]=useState(false),[error,setError]=useState(''),[excluded,setExcluded]=useState(''),[ocr,setOcr]=useState(false),[dismissed,setDismissed]=useState(false);
 const [hardware,setHardware]=useState<Hardware|null>(null);
 useEffect(()=>{void api('/system').then(r=>r.json()).then(setHardware).catch(()=>{});},[]);
 useEffect(()=>{void api('/computer-scan').then(r=>r.json()).then(setPlan).catch(e=>setError(e.message));},[]);
 if(hasConnections||dismissed||plan?.choice)return null;
 if(!plan)return error?<p className="notice error" role="alert">Couldn’t load automatic scan setup. {error} You can still connect a folder.</p>:null;
 if(!plan.drives.length)return null;
 return <section className="computer-scan" aria-label="First-time document discovery">
  <div className="computer-scan-heading"><HardDrive size={26}/><div><h2>Find the documents already on this computer</h2><p>Find them automatically—without collecting or uploading files.</p></div></div>
  <p>Scan supported documents on this computer and make their contents searchable. PaperVault reads files in the background. Your originals stay in place.</p>
  {hardware&&<details className="scan-scope"><summary>Computer details</summary><strong>{hardware.device==='cuda'?'GPU acceleration ready':'Ready in CPU mode'}</strong><span>{hardware.gpu_name||'Search and indexing run locally on your CPU'} · {Math.round(hardware.ram_bytes/1073741824)} GB RAM · {Math.floor(hardware.free_disk_bytes/1073741824)} GB free for your library</span>{hardware.device==='cpu'&&<small>CUDA is not required. Initial indexing can take longer in CPU mode.</small>}{hardware.warnings.map(w=><small key={w}>{w}</small>)}</details>}
  <div className="scan-scope"><strong>Local drives</strong><span>{plan.drives.join(' · ')}</span><small>Network and removable drives are not included automatically.</small></div>

  <div className="computer-scan-actions"><button className="button primary" disabled={busy} onClick={async()=>{setBusy(true);setError('');try{await api('/computer-scan','POST',{confirm:true,ocr,excluded_paths:excluded.split('\n').map(p=>p.trim()).filter(Boolean)});setDismissed(true);onStarted();}catch(e){setError((e as Error).message);}finally{setBusy(false);}}}>{busy?<LoaderCircle className="spin" size={16}/>:<Search size={16}/>} {busy?'Starting discovery…':'Yes, scan this computer'}</button><button className="button secondary" disabled={busy} onClick={async()=>{setBusy(true);setError('');try{await api('/computer-scan/skip','POST');setDismissed(true);onFolders();}catch(e){setError((e as Error).message);}finally{setBusy(false);}}}>No, choose folders<ArrowRight size={15}/></button></div>
  <details className="scan-options"><summary>Scan scope and exclusions</summary><p>Skips Windows and application folders, AppData and dependency caches, protected locations, and the managed library. Choose folders separately if you need a skipped location.</p><label className="field-label">Additional folders to exclude<textarea rows={3} value={excluded} onChange={e=>setExcluded(e.target.value)} placeholder={'One full folder path per line'} disabled={busy}/></label><label className="ocr-option"><input type="checkbox" checked={ocr} onChange={e=>setOcr(e.target.checked)} disabled={!ocrAvailable||busy}/><span>Read scanned pages with English OCR<small>{ocrAvailable?'More thorough, but slower.':'English OCR data is not installed.'}</small></span></label></details>
  <p className="connection-footnote">The first scan may take a while. Documents become searchable as they finish indexing. Pause in Folders; minimize PaperVault to keep it working. Full-drive checks repeat hourly while running.</p>
  {error&&<p className="notice error" role="alert">{error}</p>}
 </section>;
}
