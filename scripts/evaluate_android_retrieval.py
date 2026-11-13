"""Fixed BM25/RRF ablations over actual Android model vectors; dev selection first."""
from pathlib import Path
import argparse
import hashlib
import json
import re
import sqlite3
import time
import zipfile
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
STOP=set('a an the is are was were be been to of in on for from by with as at and or how why what which where when can could do does did find show me my it its this that these those there their them into than then both has have had not only more most much'.split())
STOP.update('का की के है हैं में से को और एक यह वह कैसे क्यों कौन क्या कहाँ मुझे दिखाओ'.split())
METHODS=['build21','original_only','combined_pages','hybrid_original_50','hybrid_original_75','hybrid_combined_50','hybrid_combined_75','separate_queries']


def page_unique(ranking,chunks,limit=100):
    seen=set();result=[]
    for index,_ in ranking:
        row=chunks[index];key=row['document'],row['page_number']
        if key not in seen:
            seen.add(key);result.append(index)
            if len(result)==limit:break
    return result


def fuse(rankings,chunks,weights,constant=60):
    scores={};representatives={}
    for ranking,weight in zip(rankings,weights):
        seen=set()
        for rank,index in enumerate(ranking,1):
            row=chunks[index];key=row['document'],row['page_number']
            if key in seen:continue
            seen.add(key);scores[key]=scores.get(key,0)+weight/(constant+rank)
            representatives.setdefault(key,index)
    return [representatives[key] for key in sorted(scores,key=lambda key:(-scores[key],chunks[representatives[key]]['id']))]


def lexical_database(chunks):
    db=sqlite3.connect(':memory:')
    db.execute("CREATE VIRTUAL TABLE passages USING fts5(text,title,tokenize='unicode61')")
    db.executemany('INSERT INTO passages(rowid,text,title) VALUES(?,?,?)',[(i+1,r['text'],r['title']) for i,r in enumerate(chunks)])
    return db


def bm25(db,query,chunks):
    terms=list(dict.fromkeys(w.casefold() for w in re.findall(r'\w+',query) if w.casefold() not in STOP and len(w)>1))
    if not terms:return []
    match=' OR '.join('"'+w.replace('"','""')+'"' for w in terms)
    rows=db.execute('SELECT rowid,bm25(passages,1.0,0.3) score FROM passages WHERE passages MATCH ? ORDER BY score,rowid',(match,))
    return page_unique([(r[0]-1,-r[1]) for r in rows],chunks)


def dense(matrix,vector):
    query=np.asarray(vector,dtype=np.float32)
    # Match Java's float multiplication and double accumulation, in bounded blocks.
    score=np.empty(len(matrix),dtype=np.float64)
    for start in range(0,len(matrix),256):score[start:start+256]=(matrix[start:start+256]*query).sum(axis=1,dtype=np.float64)
    return sorted(enumerate(score),key=lambda pair:(-pair[1],pair[0]))


def metrics(queries,rankings,chunks,method,split,language=None):
    rows=[]
    for q in queries:
        if q['split']!=split or not q['relevant'] or language and q['language']!=language:continue
        truth={(r['document'],r['page']) for r in q['relevant']}
        pages=[(chunks[i]['document'],chunks[i]['page_number']) for i in rankings[q['id']][method][:5]]
        item={}
        for k in (1,3,5):
            n=len(set(pages[:k])&truth);item[f'recall@{k}']=n/len(truth);item[f'hit@{k}']=float(n>0)
        item['mrr@5']=next((1/rank for rank,p in enumerate(pages,1) if p in truth),0)
        rows.append(item)
    return {key:sum(r[key] for r in rows)/len(rows) for key in rows[0]} if rows else None


def evaluate(snapshot,output):
    output.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(snapshot) as archive:
        manifest=json.loads(archive.read('manifest.json'))
        chunks=[json.loads(line) for line in archive.read('chunks.jsonl').splitlines()]
        queries=[json.loads(line) for line in archive.read('queries.jsonl').splitlines()]
    matrix=np.asarray([r.pop('vector') for r in chunks],dtype=np.float32)
    if matrix.shape[1]!=768 or not np.isfinite(matrix).all() or not np.allclose(np.linalg.norm(matrix,axis=1),1,atol=.001):raise ValueError('Invalid Android vectors')
    db=lexical_database(chunks);rankings={};timings=[];max_scores={}
    for q in queries:
        start=time.perf_counter()
        original=dense(matrix,q['original_vector']);combined=dense(matrix,q['combined_vector']);rewritten=dense(matrix,q['rewrite_vector'])
        lexical=bm25(db,q['query'],chunks)
        original_pages=page_unique(original,chunks);combined_pages=page_unique(combined,chunks);rewrite_pages=page_unique(rewritten,chunks)
        rankings[q['id']]={
            'build21':page_unique(combined[:20],chunks,5),
            'original_only':page_unique(original[:20],chunks,5),
            'combined_pages':combined_pages[:5],
            'hybrid_original_50':fuse([original_pages,lexical],chunks,[.5,.5])[:5],
            'hybrid_original_75':fuse([original_pages,lexical],chunks,[.75,.25])[:5],
            'hybrid_combined_50':fuse([combined_pages,lexical],chunks,[.5,.5])[:5],
            'hybrid_combined_75':fuse([combined_pages,lexical],chunks,[.75,.25])[:5],
            'separate_queries':fuse([original_pages,rewrite_pages,lexical],chunks,[1/3]*3)[:5],
        }
        max_scores[q['id']]={'original':float(original[0][1]),'combined':float(combined[0][1])}
        timings.append((time.perf_counter()-start)*1000)
    dev={m:metrics(queries,rankings,chunks,m,'dev') for m in METHODS}
    # A tie favors no generation, then the existing recipe, then added ranking work.
    simplicity={'original_only':0,'build21':1,'combined_pages':2}
    selected=min(METHODS,key=lambda m:(-dev[m]['recall@3'],-dev[m]['recall@5'],-dev[m]['mrr@5'],simplicity.get(m,3),METHODS.index(m)))
    lock={'selected':selected,'development':dev,'snapshot_sha256':hashlib.sha256(snapshot.read_bytes()).hexdigest(),
          'protocol_sha256':hashlib.sha256((ROOT/'docs/superpowers/specs/2026-10-28-offline-retrieval-upgrade.md').read_bytes()).hexdigest(),
          'selection':'Development queries only; written before test metrics are computed.'}
    (output/'selection-lock.json').write_text(json.dumps(lock,indent=2),encoding='utf-8')
    test={m:metrics(queries,rankings,chunks,m,'test') for m in METHODS}
    language={lang:{m:metrics(queries,rankings,chunks,m,'test',lang) for m in METHODS} for lang in ('en','hi')}
    negatives=[q for q in queries if not q['relevant'] and q['split']=='test']
    negative_rate={m:sum(bool(rankings[q['id']][m]) for q in negatives)/len(negatives) for m in METHODS}
    base=test['build21'];chosen=test[selected]
    gates={'recall3_gain_at_least_02':chosen['recall@3']>=base['recall@3']+.02-1e-10,
           'recall5_no_regression':chosen['recall@5']>=base['recall@5']-1e-10,
           'english_hit5_no_regression':language['en'][selected]['hit@5']>=language['en']['build21']['hit@5']-1e-10,
           'hindi_hit5_no_regression':language['hi'][selected]['hit@5']>=language['hi']['build21']['hit@5']-1e-10,
           'absent_candidate_rate_no_increase':negative_rate[selected]<=negative_rate['build21']}
    report={'model':manifest,'selected':selected,'development':dev,'test':test,'test_languages':language,'promotion_gates':gates,'quality_gate_passed':all(gates.values()),
            'no_answer_candidate_return_rate':negative_rate,'negative_max_cosines':{q['id']:max_scores[q['id']] for q in negatives},
            'desktop_all_ablation_rank_ms_p50':float(np.median(timings)),
            'limitations':['Existing development-era page labels, not independent human judgments','12 developer-authored Hindi translations; only six Hindi test questions','Rank timing is a desktop ablation, not Android end-to-end latency','Candidate return rate is not a calibrated answerability measure']}
    (output/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    (output/'rankings.json').write_text(json.dumps({'chunks':chunks,'rankings':rankings}),encoding='utf-8')
    print(json.dumps({'selected':selected,'baseline_test':base,'selected_test':chosen,'gates':gates,'quality_gate_passed':all(gates.values())},indent=2))
    db.close()
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('snapshot',type=Path);parser.add_argument('--output',type=Path,default=ROOT/'results/retrieval-upgrade');args=parser.parse_args()
    evaluate(args.snapshot,args.output)
