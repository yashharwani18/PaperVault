"""Compare full vs compact snapshots on the real index, read-only; no PDF copies."""
import argparse
import gc
import hashlib
import json
from pathlib import Path
import sqlite3
import statistics
import subprocess
import sys
import threading
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def worker(mode,library):
    import numpy as np
    import psutil
    from types import SimpleNamespace
    from knowledge_library.retrieval import SearchIndex
    process=psutil.Process();baseline=process.memory_info().rss;peak=[baseline];done=threading.Event()
    def sample():
        while not done.wait(.005):peak[0]=max(peak[0],process.memory_info().rss)
    monitor=threading.Thread(target=sample,daemon=True);monitor.start()
    db=sqlite3.connect(library.resolve().as_uri()+'?mode=ro',uri=True);db.row_factory=sqlite3.Row
    db.execute('BEGIN')
    count=db.execute('SELECT count(*) FROM documents').fetchone()[0]
    queries=np.random.default_rng(123).normal(size=(3,768)).astype(np.float32)
    runs=[];digests=[]
    try:
        for _ in range(3):
            started=time.perf_counter()
            index=SearchIndex(SimpleNamespace(db=db),compact=mode=='compact')
            loaded=time.perf_counter()-started
            rankings=[index.semantic(query) for query in queries]
            # Hydrate top results just as live search does, inside the read snapshot.
            selected=[index.result_row(i) for i,_ in rankings[0][:5]]
            elapsed=time.perf_counter()-started
            digest=hashlib.sha256(json.dumps([[(index.rows[i]['id'],s) for i,s in ranking] for ranking in rankings]).encode()).hexdigest()
            digests.append(digest)
            runs.append(dict(load_s=loaded,load_and_three_rankings_s=elapsed,chunks=len(index.rows)))
            del index,rankings,selected;gc.collect()
    finally:
        done.set();monitor.join();db.close()
    return dict(mode=mode,documents=count,runs=runs,ranking_digests=digests,
                process_baseline_rss_bytes=baseline,process_peak_rss_bytes=peak[0],
                process_peak_rss_growth_bytes=peak[0]-baseline)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--worker',choices=['full','compact']);parser.add_argument('--library',type=Path,default=ROOT/'data/pc-prototype/library.sqlite3')
    args=parser.parse_args()
    if args.worker:print(json.dumps(worker(args.worker,args.library)));return
    reports=[]
    for mode in ['full','compact']:
        run=subprocess.run([sys.executable,str(Path(__file__).resolve()),'--worker',mode,'--library',str(args.library)],capture_output=True,text=True,check=True)
        reports.append(json.loads(run.stdout))
    full,compact=reports
    assert len(set(full['ranking_digests']+compact['ranking_digests']))==1,'Index changed during comparison or rankings differ; do not claim equivalence.'
    old=statistics.median(r['load_s'] for r in full['runs']);new=statistics.median(r['load_s'] for r in compact['runs'])
    report=dict(scope='Read-only real library, full vs compact snapshots in separate processes. Three queries/runs; not an indexing concurrency or end-to-end model benchmark.',
                comparisons=reports,rankings_identical=True,load_median_s=dict(full=old,compact=new),load_speedup=old/new,
                peak_rss_growth_reduction_bytes=full['process_peak_rss_growth_bytes']-compact['process_peak_rss_growth_bytes'])
    (ROOT/'results/compact-retrieval-benchmark.json').write_text(json.dumps(report,indent=2))
    print(json.dumps({k:v for k,v in report.items() if k!='comparisons'},indent=2))


if __name__=='__main__':main()
