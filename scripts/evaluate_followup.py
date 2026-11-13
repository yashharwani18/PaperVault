"""Run frozen follow-up queries without changing the model or confidence policy."""
import json
import hashlib
import sys
import time
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from knowledge_library.library import Library
from knowledge_library.retrieval import SearchIndex
from knowledge_library.embedding import EmbeddingGemma
from knowledge_library.server import offline_guard


def main():
    offline_guard();path=ROOT/'evaluation/followup-queries.json';protocol=json.loads(path.read_text());policy=json.loads((ROOT/'evaluation/confidence-policy.json').read_text())
    digest=hashlib.sha256(path.read_bytes()).hexdigest();model=EmbeddingGemma();rows=[]
    with Library(protocol['library'],model) as lib:
        index=SearchIndex(lib)
        for q in protocol['questions']:
            begin=time.perf_counter();vector=model.query(q['query']);rankings=dict(semantic=index.semantic(vector),bm25=index.lexical(q['query']))
            rankings['diversified']=[];seen=set()
            for i,score in rankings['semantic'][:20]:
                if index.rows[i]['document_id'] not in seen:rankings['diversified'].append((i,score));seen.add(index.rows[i]['document_id'])
            rankings['diversified']=(rankings['diversified']+[x for x in rankings['semantic'][:20] if x not in rankings['diversified']])[:5]
            ranked={mode:[dict(document_id=index.rows[i]['document_id'],filename=index.rows[i]['filename'],page=index.rows[i]['page_number'],score=float(score),passage=index.rows[i]['text']) for i,score in ranking[:5]] for mode,ranking in rankings.items()}
            relevant={(p['document_id'],p['page']) for p in q['relevant']}
            metrics={mode:{f'recall_at_{k}':len(relevant & {(h['document_id'],h['page']) for h in hits[:k]})/len(relevant) if relevant else None for k in (1,3,5)} for mode,hits in ranked.items()}
            top=ranked['semantic'][0]['score'] if ranked['semantic'] else None
            rows.append(dict(id=q['id'],query=q['query'],answerable=bool(relevant),rankings=ranked,metrics=metrics,top_cosine=top,rejected=top is None or top<policy['threshold'],elapsed_s=time.perf_counter()-begin))
            print(q['id'],round(top,3),'rejected',rows[-1]['rejected'],flush=True)
    positives=[r for r in rows if r['answerable']];negatives=[r for r in rows if not r['answerable']]
    summary={mode:{f'recall_at_{k}':float(np.mean([r['metrics'][mode][f'recall_at_{k}'] for r in positives])) for k in (1,3,5)} for mode in ('semantic','bm25','diversified')}
    result=dict(protocol_sha256=digest,policy=policy['version'],threshold=policy['threshold'],annotation=protocol['annotation'],
                metrics=summary,answerable_retained=sum(not r['rejected'] for r in positives),answerable_total=len(positives),
                missing_fact_rejected=sum(r['rejected'] for r in negatives),missing_fact_total=len(negatives),rows=rows,
                interpretation='Additional source-checked evaluation, not independently human labeled. Do not retune this set and call it held-out.')
    (ROOT/'results/followup-evaluation.json').write_text(json.dumps(result,indent=2));print(json.dumps({k:v for k,v in result.items() if k!='rows'},indent=2))


if __name__=='__main__':main()
