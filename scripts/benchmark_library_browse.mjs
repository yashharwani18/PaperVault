// Synthetic in-process sorting only; this does not measure database, UI rendering or phone behavior.
import {performance} from 'node:perf_hooks';
import {sortDocuments} from '../frontend/src/libraryBrowse.ts';
const results=[];
for(const n of [100,1000,2000,10000]){
 const docs=Array.from({length:n},(_,i)=>({id:String(i),filename:`Lecture ${n-i}.pdf`,created_at:'2026-01-01T00:00:00Z',size_bytes:i,status:'indexed'}));
 let seed=1234567;for(let i=docs.length-1;i>0;i--){seed=(Math.imul(seed,1664525)+1013904223)>>>0;const j=seed%(i+1);[docs[i],docs[j]]=[docs[j],docs[i]];}
 for(let i=0;i<3;i++)sortDocuments(docs,'name');
 const samples=[];for(let i=0;i<20;i++){const start=performance.now();const sorted=sortDocuments(docs,'name');samples.push(performance.now()-start);if(sorted.length!==n)throw Error('sort dropped documents');}
 samples.sort((a,b)=>a-b);results.push({documents:n,median_ms:+samples[10].toFixed(3),p95_ms:+samples[18].toFixed(3)});
}
console.log(JSON.stringify({kind:'synthetic_in_process_filename_sort',node:process.version,platform:process.platform,arch:process.arch,results,limitations:'No database, rendering, PDF indexing, phone, battery, or thermal measurement.'},null,2));
