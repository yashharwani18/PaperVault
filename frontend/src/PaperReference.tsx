import {useEffect,useMemo,useState} from 'react';
import {BookOpen,Check,Copy,Download,LoaderCircle,Plus,Trash2} from 'lucide-react';
import {formatReference,REFERENCE_FORMATS} from './citations';
import type {PaperItem} from './citations';
import './paperReference.css';

type API=(path:string,method?:string,body?:unknown)=>Promise<Response>;
type Reference={detected:boolean;item:PaperItem;warnings:string[];reviewed:boolean;source_sha256:string;provenance:Record<string,string>};
type Author={given?:string;family?:string;literal?:string};
const STYLE_KEY='khoj.reference.style';
const CUSTOM_KEY='khoj.reference.custom-style';
function preference(key:string,fallback=''){try{return localStorage.getItem(key)||fallback;}catch{return fallback;}}
function remember(key:string,value:string){try{localStorage.setItem(key,value);}catch{/* Preview still works when browser storage is unavailable. */}}
function text(item:PaperItem,key:string){return typeof item[key]==='string'?item[key] as string:'';}

export default function PaperReference({id,api}:{id:string;api:API}){
 const [reference,setReference]=useState<Reference|null>(null),[item,setItem]=useState<PaperItem|null>(null);
 const [format,setFormat]=useState(()=>preference(STYLE_KEY,'apa'));
 const [styleXml,setStyleXml]=useState(()=>preference(CUSTOM_KEY)),[localeXml,setLocaleXml]=useState('');
 const [error,setError]=useState(''),[message,setMessage]=useState(''),[busy,setBusy]=useState(false),[dirty,setDirty]=useState(false);
 const [expanded,setExpanded]=useState(false),[editing,setEditing]=useState(false),[attempt,setAttempt]=useState(0);
 useEffect(()=>{let alive=true;setReference(null);setItem(null);setError('');setMessage('');setDirty(false);setEditing(false);
  void api(`/documents/${id}/reference`).then(r=>r.json()).then((r:Reference)=>{if(alive){setReference(r);setItem(r.item);setExpanded(r.detected);}}).catch(e=>{if(alive)setError((e as Error).message);});
  return()=>{alive=false;};
 },[id,attempt]);
 const output=useMemo(()=>{if(!item)return {text:'',extension:'txt',mimeType:'text/plain',error:''};try{return {...formatReference(item,format,{styleXml,localeXml}),error:''};}catch(e){return {text:'',extension:'txt',mimeType:'text/plain',error:(e as Error).message};}},[item,format,styleXml,localeXml]);
 function update(key:string,value:unknown){setItem(old=>old?{...old,[key]:value}:old);setDirty(true);setMessage('');}
 function authors(value:Author[]){update('author',value);}
 async function save(){if(!item||!reference)return;setBusy(true);setError('');setMessage('');try{
  const saved:Reference=await(await api(`/documents/${id}/reference`,'PUT',{item,reviewed:true,source_sha256:reference.source_sha256})).json();
  setReference(saved);setItem(saved.item);setDirty(false);setEditing(false);setMessage('Reference details saved.');
 }catch(e){setError((e as Error).message);}finally{setBusy(false);}}
 async function loadStyle(file:File|undefined,locale=false){if(!file)return;setError('');setMessage('');try{
  if(file.size>512_000)throw new Error('Choose a style or locale smaller than 500 KB.');
  const xml=await file.text();
  if(locale)setLocaleXml(xml);else{setStyleXml(xml);remember(CUSTOM_KEY,xml);setFormat('custom');remember(STYLE_KEY,'custom');}
 }catch(e){setError((e as Error).message);}}
 function download(){if(!output.text)return;const url=URL.createObjectURL(new Blob([output.text],{type:output.mimeType}));const link=document.createElement('a');link.href=url;link.download=`reference.${output.extension}`;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);setMessage('Reference downloaded.');}
 return <section className="paper-reference" aria-label="Document reference">
  <button type="button" className="reference-heading" aria-expanded={expanded} onClick={()=>setExpanded(v=>!v)}><BookOpen size={16}/><strong>{reference?.detected?'Paper reference':'Create a reference'}</strong><span>{reference?.reviewed?'Reviewed':reference?.detected?'Draft':''}</span></button>
  {error&&<p className="reference-error" role="alert">{error}{!reference&&<button className="text-button" onClick={()=>setAttempt(n=>n+1)}>Retry reference detection</button>}</p>}
  {expanded&&(!item?<p role="status">Reading reference details…</p>:<div className="reference-content">
   {!reference?.detected&&<p>No research paper was confidently detected. You can enter its reference details.</p>}
   <label className="field-label">Reference format<select aria-label="Reference format" value={format} onChange={e=>{setFormat(e.target.value);remember(STYLE_KEY,e.target.value);setMessage('');}}>{REFERENCE_FORMATS.map(f=><option key={f.id} value={f.id}>{f.label}</option>)}</select></label>
   {format==='custom'&&<div className="reference-custom"><label className="field-label">Journal or university style (.csl)<input type="file" accept=".csl,.xml" aria-label="Custom citation style" onChange={e=>void loadStyle(e.target.files?.[0])}/></label><p>Choose an independent CSL style. Formatting stays on this device.</p><details><summary>Style language</summary><label className="field-label">Optional CSL locale (.xml)<input type="file" accept=".xml" onChange={e=>void loadStyle(e.target.files?.[0],true)}/></label><p>English is bundled. Add a matching locale for a style in another language.</p></details></div>}
   {output.error?<p className="reference-error" role="alert">{output.error}</p>:<pre className="reference-preview" aria-label="Formatted reference">{output.text}</pre>}
   {!!reference?.warnings.length&&<details className="reference-warnings"><summary>Check reference details ({reference.warnings.length})</summary><ul>{reference.warnings.map((warning,i)=><li key={i}>{warning}</li>)}</ul></details>}
   {!reference?.reviewed&&!dirty&&<p className="reference-note">Automatically extracted draft. Check it against the paper before submitting.</p>}
   {dirty&&<p className="reference-note">Preview includes your unsaved changes.</p>}
   <div className="reference-actions"><button type="button" className="button secondary small" disabled={!output.text||!!output.error} onClick={()=>{setMessage('');void navigator.clipboard.writeText(output.text).then(()=>setMessage('Reference copied.')).catch(()=>setError('Copy failed. Select the reference text or download it instead.'));}}><Copy size={13}/>Copy</button><button type="button" className="button secondary small" disabled={!output.text||!!output.error} onClick={download}><Download size={13}/>Download</button><button type="button" className="text-button" aria-expanded={editing} onClick={()=>setEditing(v=>!v)}>{editing?'Hide details':'Edit details'}</button></div>
   {message&&<p className="reference-note" role="status">{message}</p>}
   <small className="reference-note">© Frank Bennett — <a href="https://citeproc-js.readthedocs.io/" target="_blank" rel="noreferrer">citeproc-js</a> implements the Citation Style Language.</small>
   {editing&&<form className="reference-editor" onSubmit={e=>{e.preventDefault();void save();}}><fieldset disabled={busy}>
    <label className="field-label">Publication type<select value={item.type} onChange={e=>update('type',e.target.value)}><option value="article-journal">Journal article</option><option value="paper-conference">Conference paper</option><option value="article">Preprint / article</option><option value="report">Report</option><option value="book">Book</option><option value="thesis">Thesis</option></select></label>
    <label className="field-label">Title<input required maxLength={2000} value={text(item,'title')} onChange={e=>update('title',e.target.value)}/></label>
    <div className="reference-authors"><span className="field-label">Authors, in paper order</span>{(item.author||[]).map((author,index)=><div className="reference-author" key={index}>{author.literal!==undefined?<label className="field-label">Organization / author name<input aria-label={`Author ${index+1} name`} maxLength={200} value={author.literal} onChange={e=>authors((item.author||[]).map((a,i)=>i===index?{literal:e.target.value}:a))}/></label>:<><label className="field-label">Given names<input aria-label={`Author ${index+1} given names`} maxLength={200} value={author.given||''} onChange={e=>authors((item.author||[]).map((a,i)=>i===index?{...a,given:e.target.value}:a))}/></label><label className="field-label">Family name<input aria-label={`Author ${index+1} family name`} maxLength={200} value={author.family||''} onChange={e=>authors((item.author||[]).map((a,i)=>i===index?{...a,family:e.target.value}:a))}/></label></>}<button type="button" className="icon-button" aria-label={`Remove author ${index+1}`} onClick={()=>authors((item.author||[]).filter((_,i)=>i!==index))}><Trash2 size={13}/></button></div>)}<button type="button" className="text-button" disabled={(item.author||[]).length>=100} onClick={()=>authors([...(item.author||[]),{given:'',family:''}])}><Plus size={13}/>Add author</button></div>
    <label className="field-label">Publication year<input type="number" min={1000} max={9999} value={item.issued?.['date-parts']?.[0]?.[0]||''} onChange={e=>update('issued',e.target.value?{'date-parts':[[Number(e.target.value)]]}:undefined)}/></label>
    {([['container-title','Journal / conference'],['volume','Volume'],['issue','Issue'],['page','Page range'],['publisher','Publisher'],['DOI','DOI'],['URL','Source URL']] as const).map(([key,label])=><label className="field-label" key={key}>{label}<input maxLength={2000} value={text(item,key)} onChange={e=>update(key,e.target.value)}/></label>)}
    <button className="button primary small" disabled={!text(item,'title').trim()||busy}>{busy?<LoaderCircle size={14} className="spin"/>:<Check size={14}/>}Save checked details</button>
   </fieldset></form>}
  </div>)}
 </section>;
}
