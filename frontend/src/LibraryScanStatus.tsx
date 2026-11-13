import {useEffect,useState} from 'react';
import {ArrowUpRight,FolderSync} from 'lucide-react';

type Source={enabled:number;state:string;counts:Record<string,number>};
type API=(path:string,method?:string,body?:unknown)=>Promise<Response>;

export default function LibraryScanStatus({api,onManage,indexingPaused=false}:{api:API;onManage:()=>void;indexingPaused?:boolean}){
 const [sources,setSources]=useState<Source[]>([]),[error,setError]=useState(false);
 useEffect(()=>{let active=true;async function load(){try{const data=await(await api('/connections')).json();if(active){setSources(data.sources);setError(false);}}catch{if(active)setError(true);}}void load();const timer=setInterval(()=>void load(),3000);return()=>{active=false;clearInterval(timer);};},[]);
 const indexed=sources.reduce((n,s)=>n+(s.counts.indexed||0),0),waiting=sources.reduce((n,s)=>n+(s.counts.discovered||0)+(s.counts.queued||0),0);
 const failed=sources.reduce((n,s)=>n+(s.counts.failed||0),0),paused=sources.length>0&&sources.every(s=>!s.enabled),scanning=sources.some(s=>s.enabled&&s.state==='scanning');
 const attention=sources.some(s=>s.enabled&&['attention','unavailable'].includes(s.state));
 const label=error?'Scan status unavailable':!sources.length?'Loading scan status…':indexingPaused?'Indexing paused':paused?'Scan paused':scanning?'Finding PDFs':attention?'Scan needs attention':waiting?'Indexing PDFs':failed?'Some PDFs need attention':'Library up to date';
 return <section className="library-scan-status" aria-label="Scan progress"><FolderSync size={18}/><div><strong>{label}</strong>{!!sources.length&&<span>{indexed.toLocaleString()} indexed{waiting>0?` · ${waiting.toLocaleString()} remaining`:''}{failed>0?` · ${failed} need attention`:''}</span>}</div><button className="text-button" onClick={onManage}>Scan details<ArrowUpRight size={14}/></button></section>;
}
