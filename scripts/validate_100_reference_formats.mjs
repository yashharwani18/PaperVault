import fs from 'node:fs';
import {formatReference,REFERENCE_FORMATS} from '../frontend/src/citations.ts';
const root=new URL('../',import.meta.url),path=new URL('results/research-papers-100/report.json',root);
const report=JSON.parse(fs.readFileSync(path,'utf8'));
if(report.status!=='complete'||report.documents.length!==100)throw Error('Complete the 100-paper evaluation first');
const results=[];
for(const doc of report.documents){
 for(const format of REFERENCE_FORMATS.filter(f=>f.id!=='custom')){
  try{const out=formatReference(doc.item,format.id);if(!out.text.trim())throw Error('Empty reference');if(format.id==='json')JSON.parse(out.text);results.push({paper:doc.id,format:format.id,passed:true});}
  catch(e){results.push({paper:doc.id,format:format.id,passed:false,error:String(e)});}
 }
 if(results.length%90===0)console.log('FORMATTED',results.length);
}
const result={scope:'Rendering/export smoke test, not bibliographic correctness',papers:100,formatsPerPaper:9,total:results.length,passed:results.filter(r=>r.passed).length,failures:results.filter(r=>!r.passed)};
fs.writeFileSync(new URL('results/research-papers-100/format-report.json',root),JSON.stringify(result,null,2));console.log(JSON.stringify(result));
if(result.failures.length)process.exitCode=1;
