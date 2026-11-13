"""Score actual Android query embeddings against the unchanged exported index."""
from pathlib import Path
from collections import defaultdict
import json,argparse,numpy as np
parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('export',type=Path);parser.add_argument('suite',type=Path);parser.add_argument('vectors',type=Path);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
manifest=json.loads((args.export/'manifest.json').read_text());snapshot=json.loads(args.vectors.read_text(encoding='utf-8'));assert snapshot['complete'];assert snapshot['model_identity']==manifest['active_embedding_identity']
chunks=[json.loads(l) for l in (args.export/'chunks.jsonl').read_text(encoding='utf-8').splitlines()];data=(args.export/'vectors.f32').read_bytes();matrix=np.stack([np.frombuffer(data,dtype='<f4',count=c['dimensions'],offset=c['vector_offset_bytes']) for c in chunks]);cases={c['id']:c for c in map(json.loads,(args.suite/'semantic-cases.jsonl').read_text(encoding='utf-8').splitlines())};results=[];groups=defaultdict(list)
for row in snapshot['queries']:
 c=cases[row['id']];v=np.asarray(row['vector'],dtype=np.float32);assert v.shape==(matrix.shape[1],) and np.isfinite(v).all();scores=(matrix*v).sum(axis=1,dtype=np.float64);ranked=[];seen=set()
 for i in np.argsort(-scores,kind='stable'):
  key=f"{chunks[i]['document_id']}:{chunks[i]['page_number']}"
  if key not in seen:seen.add(key);ranked.append(dict(page=key,score=float(scores[i])))
  if len(ranked)==5:break
 truth=set(c['expected']);first=next((i for i,r in enumerate(ranked,1) if r['page'] in truth),0);result=dict(id=c['id'],language=c['language'],topic=c['topic'],query=c['query'],rank=first,top5=ranked,embedding_ms=row['elapsed_ms']);results.append(result);groups[c['language']].append(result)
assert len(results)==len(cases)
summary={lang:dict(queries=len(rows),hit1=sum(r['rank']==1 for r in rows),hit3=sum(0<r['rank']<=3 for r in rows),hit5=sum(r['rank']>0 for r in rows),mrr5=sum(1/r['rank'] if r['rank'] else 0 for r in rows)/len(rows)) for lang,rows in groups.items()}
args.output.mkdir(exist_ok=True,parents=True);report=dict(model_identity=snapshot['model_identity'],groups=summary,results=results,limitations='24 manually authored queries, automatic category labels; actual Android LiteRT query inference and host ranking; no heldout human relevance evaluation or physical-phone timing.')
(args.output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(summary,indent=2))
