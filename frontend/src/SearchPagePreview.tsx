import {useEffect,useRef,useState} from 'react';
import {LoaderCircle,RefreshCw} from 'lucide-react';

type Props={documentId:string;page:number;chunkId:number;revision:string;filename:string};

export default function SearchPagePreview({documentId,page,chunkId,revision,filename}:Props){
 const container=useRef<HTMLDivElement>(null);
 const [visible,setVisible]=useState(false);
 const [attempt,setAttempt]=useState(0);
 const [preview,setPreview]=useState<{url:string;highlights:number;width:number;height:number}|null>(null);
 const [error,setError]=useState('');
 useEffect(()=>{
  const observer=new IntersectionObserver(entries=>{if(entries.some(e=>e.isIntersecting)){setVisible(true);observer.disconnect();}},{rootMargin:'900px'});
  if(container.current)observer.observe(container.current);
  return()=>observer.disconnect();
 },[]);
 useEffect(()=>{
  if(!visible)return;
  const abort=new AbortController();let objectUrl='';
  setPreview(null);setError('');
  const params=new URLSearchParams({page:String(page),chunk_id:String(chunkId),revision});
  void (async()=>{
   try{
    const response=await fetch(`/api/documents/${encodeURIComponent(documentId)}/preview?${params}`,{signal:abort.signal,cache:'no-store'});
    if(!response.ok){const body=await response.json().catch(()=>null);throw new Error(body?.detail||'Page preview unavailable. Open the PDF to check this result.');}
    const blob=await response.blob();if(abort.signal.aborted)return;
    objectUrl=URL.createObjectURL(blob);
    setPreview({url:objectUrl,highlights:Number(response.headers.get('X-Highlight-Count')),width:Number(response.headers.get('X-Page-Width')),height:Number(response.headers.get('X-Page-Height'))});
   }catch(cause){if(!abort.signal.aborted)setError(cause instanceof Error?cause.message:'Page preview unavailable.');}
  })();
  return()=>{abort.abort();if(objectUrl)URL.revokeObjectURL(objectUrl);};
 },[visible,documentId,page,chunkId,revision,attempt]);
 return <div className="search-page-preview" ref={container} data-testid="search-page-preview">
  <div className="search-page-caption"><span>PDF page {page}</span><span>{preview?(preview.highlights?'Matched passage highlighted':'No exact highlight available'):error?'Preview unavailable':'Loading original page…'}</span></div>
  {preview?<img src={preview.url} width={preview.width} height={preview.height} alt={`${filename}, PDF page ${page}${preview.highlights?', with matched passage highlighted':''}`} onError={()=>{setPreview(null);setError('Page image could not load. Try again.');}}/>:
   <div className="search-page-placeholder" role="status">{error?<><p>{error}</p><button className="button secondary" onClick={()=>setAttempt(n=>n+1)}><RefreshCw size={14}/>Retry preview</button></>:<><LoaderCircle size={22} className="spin"/><p>{visible?'Rendering page with source highlights…':'Page loads as you scroll'}</p></>}</div>}
 </div>;
}
