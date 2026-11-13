import {useEffect,useState} from 'react';
import {FolderInput,Plus,LoaderCircle,Check,Pencil,X} from 'lucide-react';

type API=(path:string,method?:string,body?:unknown)=>Promise<Response>;
type Document={id:string;title:string;filename:string;folder_id:string};
type Folder={id:string;name:string};
type Topic={id:string;name:string;basis:string};
export type OrganizationMode='move'|'topics'|'rename';
export type SavedOrganization={message:string;undo_token?:string|null};

export function OrganizeForm({documents,folders,mode:initialMode,api,onSaved}:{documents:Document[];folders:Folder[];mode:OrganizationMode;api:API;onSaved:(result:SavedOrganization)=>Promise<void>}){
 const [mode,setMode]=useState(initialMode),[busy,setBusy]=useState(false),[error,setError]=useState('');
 const [choices,setChoices]=useState(folders),[destination,setDestination]=useState(''),[newFolder,setNewFolder]=useState('');
 const [topics,setTopics]=useState<Topic[]>([]),[chosen,setChosen]=useState<string[]>([]),[filter,setFilter]=useState(''),[newTopic,setNewTopic]=useState(''),[loaded,setLoaded]=useState(false);
 const [name,setName]=useState(documents[0]?.title||''),[manual,setManual]=useState(false);
 const ids=documents.map(d=>d.id),single=documents.length===1;
 useEffect(()=>{let active=true;void (async()=>{try{
  const data=await(await api('/organization')).json();
  const info=single?await(await api(`/organization/documents/${ids[0]}`)).json():null;
  if(active){setTopics(data.topics);setChosen(info?.topic_ids||[]);setManual(info?.manual_topics||false);setLoaded(true);}
 }catch(cause){if(active)setError((cause as Error).message);}})();return()=>{active=false;};},[]);
 async function run(work:()=>Promise<void>){setBusy(true);setError('');try{await work();}catch(cause){setError((cause as Error).message);}finally{setBusy(false);}}
 async function save(){await run(async()=>{
  if(mode==='move'){
   const result=await(await api('/organization/move','POST',{document_ids:ids,folder_id:destination})).json();
   await onSaved({message:result.updated?`Moved ${result.updated} ${result.updated===1?'document':'documents'}`:'Documents are already in this folder',undo_token:result.undo_token});
  }else if(mode==='topics'){
   await api('/organization/topics/assign','POST',{document_ids:ids,topic_ids:chosen});await onSaved({message:'Topic choices saved. Automatic indexing will keep your corrections.'});
  }else{
   await api(`/organization/documents/${ids[0]}/name`,'PUT',{name});await onSaved({message:'Document display name saved'});
  }
 });}
 return <form className="organize-form" onSubmit={e=>{e.preventDefault();void save();}}>
  <p className="dialog-copy">{single?documents[0].title:`${documents.length} selected documents`}<small>Library organization keeps original files in place.</small></p>
  <div className="organize-modes" role="group" aria-label="Organization action">{(['move','topics',...(single?['rename']:[])] as OrganizationMode[]).map(value=><button type="button" key={value} aria-pressed={mode===value} disabled={busy} onClick={()=>{setMode(value);setError('');}}>{value==='move'?'Move to folder':value==='topics'?'Edit topics':'Rename'}</button>)}</div>
  {error&&<p className="notice error" role="alert">{error}</p>}
  <fieldset disabled={busy} className="organize-fields">
   {mode==='move'?<>
    <label className="field-label">Destination folder<select aria-label="Destination folder" value={destination} onChange={e=>setDestination(e.target.value)}><option value="">Choose a folder</option>{choices.map(f=><option key={f.id} value={f.id}>{f.name}{single&&f.id===documents[0].folder_id?' (current)':''}</option>)}</select></label>
    <details className="inline-create"><summary>Create a new folder</summary><div className="organize-create"><input aria-label="New destination folder name" maxLength={128} value={newFolder} placeholder="Folder name" onChange={e=>setNewFolder(e.target.value)}/><button type="button" className="button secondary" disabled={!newFolder.trim()} onClick={()=>void run(async()=>{const folder=await(await api('/folders','POST',{name:newFolder,color:'#A78BFA'})).json();setChoices(old=>[...old,folder]);setDestination(folder.id);setNewFolder('');})}><Plus size={14}/>Create</button></div></details>
   </>:mode==='topics'?<>
    <p className="organization-hint">{single?(manual?'These are your saved topic choices.':'Choose the topics that fit this document.'):'These topics will replace the existing topics for every selected document.'} Your choices survive rescans and topic refreshes.</p>
    {chosen.length>0&&<div className="chosen-topics" role="group" aria-label="Selected topics">{topics.filter(t=>chosen.includes(t.id)).map(topic=><button type="button" key={topic.id} aria-label={`Remove topic ${topic.name}`} onClick={()=>setChosen(old=>old.filter(id=>id!==topic.id))}>{topic.name}<X size={12}/></button>)}</div>}
    <label className="field-label">Find a topic<input aria-label="Filter topics" value={filter} onChange={e=>setFilter(e.target.value)} placeholder="Search topics"/></label>
    {!loaded?<p role="status">Loading topics…</p>:<div className="topic-checklist" role="group" aria-label="Document topics">{topics.filter(t=>t.name.toLocaleLowerCase().includes(filter.toLocaleLowerCase())).map(topic=><label key={topic.id}><input type="checkbox" checked={chosen.includes(topic.id)} onChange={e=>setChosen(old=>e.target.checked?[...old,topic.id]:old.filter(id=>id!==topic.id))}/><span>{topic.name}</span>{topic.basis==='Personal topic'&&<small>Custom</small>}</label>)}</div>}
    {loaded&&<p className="organization-hint">{chosen.length?`${chosen.length} ${chosen.length===1?'topic':'topics'} selected`:'No topics selected; Miscellaneous will apply.'}</p>}
    <details className="inline-create"><summary>Create a new topic</summary><div className="organize-create"><input aria-label="New topic name" maxLength={128} value={newTopic} placeholder="Topic name" onChange={e=>setNewTopic(e.target.value)}/><button type="button" className="button secondary" disabled={!newTopic.trim()} onClick={()=>void run(async()=>{const topic=await(await api('/organization/topics','POST',{name:newTopic})).json();setTopics(old=>[...old,topic]);setChosen(old=>[...old,topic.id]);setFilter('');setNewTopic('');})}><Plus size={14}/>Create</button></div></details>
    <button type="button" className="text-button" onClick={()=>void run(async()=>{await api('/organization/topics/reset','POST',{document_ids:ids});await onSaved({message:'Automatic topic suggestions restored'});})}>Use automatic topics again</button>
   </>:<>
    <label className="field-label">Display name<input aria-label="Document display name" required maxLength={128} value={name} onChange={e=>setName(e.target.value)}/></label>
    <p className="organization-hint">Original filename: {documents[0].filename}</p>
    <button type="button" className="text-button" onClick={()=>void run(async()=>{await api(`/organization/documents/${ids[0]}/name`,'DELETE');await onSaved({message:'Original document name restored'});})}>Use original name</button>
   </>}
  </fieldset>
  <div className="dialog-actions"><button className="button primary" disabled={busy||(mode==='move'&&!destination)||(mode==='topics'&&!loaded)||(mode==='rename'&&!name.trim())}>{busy?<LoaderCircle className="spin" size={15}/>:mode==='move'?<FolderInput size={15}/>:mode==='topics'?<Check size={15}/>:<Pencil size={15}/>} {mode==='move'?'Move documents':mode==='topics'?'Save topics':'Save name'}</button></div>
 </form>;
}

export function TopicNameForm({topic,api,onSaved}:{topic?:{id:string;name:string};api:API;onSaved:(result:SavedOrganization)=>Promise<void>}){
 const [name,setName]=useState(topic?.name||''),[busy,setBusy]=useState(false),[error,setError]=useState('');
 return <form onSubmit={e=>{e.preventDefault();setBusy(true);setError('');void (async()=>{try{await api(topic?`/organization/topics/${topic.id}`:'/organization/topics',topic?'PATCH':'POST',{name});await onSaved({message:topic?'Topic renamed':'Topic created'});}catch(cause){setError((cause as Error).message);}finally{setBusy(false);}})();}}>
  <p className="dialog-copy">{topic?'This name stays when automatic topics are refreshed.':'Create a topic, then add documents through Edit topics.'}</p>
  <label className="field-label">Topic name<input aria-label="Topic name" required maxLength={128} disabled={busy} value={name} onChange={e=>setName(e.target.value)}/></label>
  {error&&<p className="notice error" role="alert">{error}</p>}
  <div className="dialog-actions"><button className="button primary" disabled={busy||!name.trim()}>{busy?<LoaderCircle size={15} className="spin"/>:<Check size={15}/>} {topic?'Save name':'Create topic'}</button></div>
 </form>;
}
