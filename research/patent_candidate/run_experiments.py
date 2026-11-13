"""Reproducible local experiments; no network and no writes to the live library."""
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import time
import tracemalloc

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from knowledge_library.bill_amounts import source_amounts
from research.patent_candidate.engine import EvidenceSearch, normalized


def ids(result):
    return [row['id'] for row in result['hits']]


def finish(engine, job, budget=5):
    slices = 0
    while True:
        result = engine.advance(job, exact_budget=budget)
        slices += 1
        if result['status'] == 'complete':
            return result, slices
        if slices > 100000:
            raise RuntimeError('Nontermination')


def item(id, vector, *, amount='100', field='subtotal', folder='A'):
    text = f'Invoice\n{field.title()}: INR {amount}\n'
    return dict(id=id, vector=vector, text=text, page=1, folder=folder,
                evidence=next(source_amounts(text)))


def synthetic(path):
    engine = EvidenceSearch(path, 128)
    rng = np.random.default_rng(20261018)
    n = 4000
    start = time.perf_counter()
    # Document groups permit selective whole-document replacement experiments.
    for doc in range(100):
        engine.replace_document(str(doc), (item(f'{doc}:{j}',rng.normal(size=128),
            folder='A' if j%2 else 'B', amount='100' if j%3 else '200') for j in range(40)))
    setup_s = time.perf_counter()-start
    checks=[]
    for number in range(20):
        query = rng.normal(size=128)
        pred = {} if number%2==0 else {'folder':'A','field':'subtotal','value':'100'}
        start = time.perf_counter()
        job = engine.start(query,predicate=pred,k=5)
        result, slices = finish(engine,job)
        candidate_s = time.perf_counter()-start
        start = time.perf_counter()
        oracle = engine.exhaustive(query,pred,k=5)
        oracle_s = time.perf_counter()-start
        assert ids(result)==oracle
        checks.append(dict(query=number,passed=True,coarse=result['coarse_total'],
            exact_reads=result['exact_reads_total'],slices=slices,candidate_s=candidate_s,
            streaming_exact_s=oracle_s))
    # Completed receipt -> removed winner -> reopen -> previously filtered source
    # becomes eligible and most similar. Repairs only two changed documents.
    query = rng.normal(size=128)
    pred={'folder':'A','field':'subtotal','value':'100'}
    job=engine.start(query,predicate=pred,k=5)
    before,_=finish(engine,job)
    winner_doc=before['hits'][0]['doc']
    engine.replace_document(winner_doc,[])
    engine.replace_document('new-eligible',[item('new-eligible',query)])
    assert not engine.current(before)
    start=time.perf_counter()
    repaired,slices=finish(engine,job)
    repair_s=time.perf_counter()-start
    assert ids(repaired)==engine.exhaustive(query,pred,k=5)
    fresh=engine.start(query,predicate=pred,k=5)
    fresh_result,_=finish(engine,fresh)
    reuse=dict(passed=ids(repaired)==ids(fresh_result),changed_documents=2,
        additional_coarse=repaired['coarse_total']-before['coarse_total'],
        fresh_coarse=fresh_result['coarse_total'],
        additional_exact_reads=repaired['exact_reads_total']-before['exact_reads_total'],
        fresh_exact_reads=fresh_result['exact_reads_total'],repair_s=repair_s)
    engine.close()
    return dict(seed=20261018,vectors=n,dimensions=128,setup_s=setup_s,checks=checks,repair=reuse)


def real_library(path, live):
    # mode=ro, explicit read snapshot, never instantiate Library (which migrates).
    db=sqlite3.connect(f'{live.resolve().as_uri()}?mode=ro',uri=True)
    db.row_factory=sqlite3.Row
    db.execute('BEGIN')
    dimension=db.execute('SELECT dimensions FROM chunks LIMIT 1').fetchone()[0]
    engine=EvidenceSearch(path,dimension)
    vector_count=0
    query_samples=[]
    folder_counts={}
    for doc in db.execute('SELECT id,folder_id FROM documents ORDER BY id'):
        def records():
            nonlocal vector_count
            for row in db.execute('SELECT * FROM chunks WHERE document_id=? ORDER BY id',(doc['id'],)):
                assert hashlib.sha256(row['vector']).hexdigest()==row['vector_sha256']
                vector=np.frombuffer(row['vector'],dtype='<f4')
                if len(query_samples)<24 and vector_count%29==0:
                    query_samples.append(vector.copy())
                vector_count+=1
                evidence=next(source_amounts(row['text']),None)
                yield dict(id=str(row['id']),folder=doc['folder_id'],page=row['page_number'],
                    text=row['text'],vector=vector,evidence=evidence)
        engine.replace_document(doc['id'],records())
        folder_counts[doc['folder_id']]=folder_counts.get(doc['folder_id'],0)+1
    db.rollback();db.close()
    checks=[]
    for i,q in enumerate(query_samples):
        start=time.perf_counter()
        job=engine.start(q,k=5)
        result,slices=finish(engine,job)
        elapsed=time.perf_counter()-start
        assert ids(result)==engine.exhaustive(q,k=5)
        checks.append(dict(query=i,passed=True,exact_reads=result['exact_reads_total'],
                           coarse=result['coarse_total'],slices=slices,elapsed_s=elapsed))
    # Each indexed field tuple is tested as a hard predicate; contains no raw
    # amounts, names, paths or passages in the shareable aggregate result JSON.
    amount_checks=0
    fields=list(engine.db.execute('SELECT DISTINCT field,value,currency FROM sources WHERE field IS NOT NULL'))
    for field in fields:
        pred=dict(field=field['field'],value=field['value'])
        if field['currency']:pred['currency']=field['currency']
        q=query_samples[0]
        result,_=finish(engine,engine.start(q,predicate=pred,k=5))
        assert ids(result)==engine.exhaustive(q,pred,k=5)
        amount_checks+=1
    engine.close()
    return dict(vectors=vector_count,documents=sum(folder_counts.values()),dimensions=dimension,
        vector_query_checks=checks,field_predicate_checks=amount_checks,
        note='Stored document vectors used as query probes; not a natural-language semantic accuracy evaluation. Only first complete label/amount span per chunk is admitted. Original library opened read-only; local research DB contains private source text.')


def memory(path,mode):
    engine=EvidenceSearch(path,128)
    q=np.random.default_rng(42).normal(size=128)
    tracemalloc.start()
    start=time.perf_counter()
    if mode=='dense':
        # Deliberately simple eager matrix baseline; row metadata not included.
        matrix=np.stack([np.frombuffer(r[0],dtype='<f4') for r in engine.db.execute('SELECT vector FROM sources ORDER BY id')])
        scores=matrix.astype(np.float64) @ normalized(q,128).astype(np.float64)
        order=np.argsort(-scores)[:5]
        count=len(order)
    elif mode=='stream':
        count=len(engine.exhaustive(q))
    else:
        result,_=finish(engine,engine.start(q))
        count=len(result['hits'])
    _,peak=tracemalloc.get_traced_memory();tracemalloc.stop()
    engine.close()
    return dict(mode=mode,query_s=time.perf_counter()-start,traced_peak_bytes=peak,hits=count,
        note='Python/NumPy traced query allocations only; excludes SQLite native page cache, OS cache, neural models, interpreter baseline and indexing. Not total RAM or a phone benchmark.')


def ablation(path):
    engine=EvidenceSearch(path,2)
    engine.replace_document('visible',[item('visible',[0.8,0.6])])
    engine.replace_document('excluded',[item('excluded',[1,0],amount='200')])
    pred={'field':'subtotal','value':'100'}
    job=engine.start([1,0],predicate=pred,k=1)
    old,_=finish(engine,job)
    old_winner_hash=old['hits'][0]['source_hash']
    engine.replace_document('excluded',[item('excluded',[1,0])])
    unchanged_winner=engine.db.execute('SELECT source_hash FROM sources WHERE id=?',('visible',)).fetchone()[0]==old_winner_hash
    oracle=engine.exhaustive([1,0],pred,k=1)
    repaired,_=finish(engine,job)
    result=dict(old_winner_source_unchanged=unchanged_winner,
        returned_sources_only_validation_would_accept=unchanged_winner,
        stale_answer_differs_from_oracle=ids(old)!=oracle,
        repaired_answer_matches_oracle=ids(repaired)==oracle,
        previously_excluded_document_recovered=ids(repaired)==['excluded'])
    engine.close()
    return result


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--out',required=True,type=Path)
    parser.add_argument('--live',type=Path)
    parser.add_argument('--memory',choices=['dense','stream','candidate'])
    parser.add_argument('--database',type=Path)
    args=parser.parse_args()
    args.out.parent.mkdir(parents=True,exist_ok=True)
    if args.memory:
        result=memory(args.database,args.memory)
    else:
        private=ROOT/'data/patent-research'/time.strftime('%Y%m%d-%H%M%S')
        private.mkdir(parents=True,exist_ok=False)
        result=dict(synthetic=synthetic(private/'synthetic.sqlite3'),
                    synthetic_database=str(private/'synthetic.sqlite3'),
                    ablation=ablation(private/'ablation.sqlite3'))
        if args.live:result['real_library']=real_library(private/'real.sqlite3',args.live)
    args.out.write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
