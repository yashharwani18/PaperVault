"""Compare R1 against incremental exact-score maintenance, not full restart."""
import argparse
import json
from pathlib import Path
import statistics
import sys
import time

import numpy as np

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from research.patent_candidate.engine import EvidenceSearch
from research.patent_candidate.exact_view_baseline import ExactView
from research.patent_candidate.run_experiments import finish,item,ids


def timed(call):
    begin=time.perf_counter();value=call()
    return value,time.perf_counter()-begin


def scenario(path,name,seed):
    rng=np.random.default_rng(seed)
    d=128;n=2000
    engine=EvidenceSearch(path,d)
    q=rng.normal(size=d)
    anchor=q/np.linalg.norm(q)
    def vector():
        if name=='ties':return anchor.copy()
        if name=='clustered':return anchor+rng.normal(size=d)*0.005
        return rng.normal(size=d)
    for doc in range(100):
        engine.replace_document(str(doc),(item(f'{doc}:{j}',vector(),
            amount='100' if j%2 else '200') for j in range(20)))
    pred={'field':'subtotal','value':'100'}
    baseline=ExactView(engine)
    # Alternate which initial query runs first across seeded repetitions.
    def start_candidate():
        job=engine.start(q,predicate=pred,k=5)
        result,_=finish(engine,job)
        return job,result
    def start_view():
        job=baseline.start(q,predicate=pred,k=5)
        return job,baseline.advance(job)
    if seed%2:
        (v,v0),vt=timed(start_view);(c,c0),ct=timed(start_candidate)
    else:
        (c,c0),ct=timed(start_candidate);(v,v0),vt=timed(start_view)
    assert ids(c0)==ids(v0)==engine.exhaustive(q,pred,k=5)
    initial=dict(candidate_s=ct,exact_view_s=vt,
        candidate_full_vectors=c0['exact_reads_total'],
        view_full_vectors=v0['exact_reads_total'],
        candidate_coarse=c0['coarse_total'])
    events=[]
    for event in range(24):
        kind=('newly_eligible','delete_winner','scope_exit','replace_document','no_change','insert')[event%6]
        if kind=='newly_eligible':
            # Existing document initially excluded entirely, then enters predicate.
            doc=f'outside:{event}'
            engine.replace_document(doc,[item(doc,vector(),amount='200')])
            # Both systems observe the excluded version first.
            finish(engine,c);baseline.advance(v)
            engine.replace_document(doc,[item(doc,q)])
        elif kind=='delete_winner':
            winner=engine.exhaustive(q,pred,k=1)[0]
            doc=engine.db.execute('SELECT doc FROM sources WHERE id=?',(winner,)).fetchone()[0]
            engine.replace_document(doc,[])
        elif kind=='scope_exit':
            doc=str(event)
            engine.replace_document(doc,[item(doc,q,amount='200')])
        elif kind=='replace_document':
            doc=str(event)
            engine.replace_document(doc,(item(f'{doc}:{j}',vector()) for j in range(20)))
        elif kind=='insert':
            doc=f'insert:{event}'
            engine.replace_document(doc,[item(doc,vector())])
        def advance_candidate():return finish(engine,c)[0]
        if event%2:
            vr,vt=timed(lambda:baseline.advance(v));cr,ct=timed(advance_candidate)
        else:
            cr,ct=timed(advance_candidate);vr,vt=timed(lambda:baseline.advance(v))
        assert ids(cr)==ids(vr)==engine.exhaustive(q,pred,k=5)
        events.append(dict(kind=kind,candidate_s=ct,exact_view_s=vt,
            candidate_full_vectors=cr['exact_reads_total']-c0['exact_reads_total'],
            view_full_vectors=vr['exact_reads_total']-v0['exact_reads_total'],
            candidate_coarse=cr['coarse_total']-c0['coarse_total'],matched=True))
        c0,v0=cr,vr
    engine.close()
    return dict(workload=name,seed=seed,vectors_initial=n,dimensions=d,initial=initial,
        events=events,median_repair_candidate_s=statistics.median(x['candidate_s'] for x in events),
        median_repair_view_s=statistics.median(x['exact_view_s'] for x in events))


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    folder=ROOT/'data/patent-research'/('exact-view-'+time.strftime('%Y%m%d-%H%M%S'))
    folder.mkdir(parents=True,exist_ok=False)
    runs=[scenario(folder/f'{name}-{seed}.sqlite3',name,seed)
          for name in ('uniform','clustered','ties') for seed in (211,212,213)]
    result=dict(runs=runs,passed=True,
        comparisons=sum(len(r['events'])+1 for r in runs),
        note='Same stored-vector arithmetic, literal predicates and source payloads. '
             'Baseline is exhaustive initially and incrementally materializes exact scores. '
             'R1 uses compressed bounds and resumable refinement. '
             'Times are local exploratory measurements with warm OS cache, not phone results. '
             'Changed source ingestion and index construction are outside query timing.')
    args.out.write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(dict(passed=True,comparisons=result['comparisons'],
        summary=[{k:r[k] for k in ('workload','seed','initial','median_repair_candidate_s','median_repair_view_s')} for r in runs]),indent=2))


if __name__=='__main__':main()
