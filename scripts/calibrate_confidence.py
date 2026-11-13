"""Calibrate a query-level candidate rejection cutoff on Phase 3 dev only.

Test results are retrospective checks, not a fresh blinded evaluation. This policy
is explicitly tentative; cosine scores are never represented as probabilities.
"""
import json
from pathlib import Path
import sys
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from knowledge_library.library import Library
from knowledge_library.retrieval import SearchIndex


def main():
    r=json.loads((ROOT/'results/phase3-validation.json').read_text())
    run=next(x for x in r['runs'] if x['chunk_tokens']==256)
    queries=json.loads((ROOT/'evaluation/phase3-queries.json').read_text())['queries']
    vectors=np.load(Path(r['library_parent'])/'query-vectors.npz')
    with Library(run['library']) as lib:
        index=SearchIndex(lib)
        scores={q['id']:float(index.semantic(vectors[q['id']],768)[0][1]) for q in queries}
    positive=[scores[q['id']] for q in queries if q['split']=='dev' and q['relevant']]
    negative=[scores[q['id']] for q in queries if q['split']=='dev' and not q['relevant']]
    threshold=(min(positive)+max(negative))/2
    record=dict(version='dev-cosine-gate-v1',dimensions=768,model_revision=r['model']['revision'],
                chunk_tokens=256,threshold=threshold,dev_min_positive=min(positive),dev_max_negative=max(negative),
                provenance='Phase 3 dev only: 12 positive and 3 unrelated negative questions. Test check is retrospective. Not a general reliability guarantee.',
                interpretation='Reject the query if the highest cosine is below the cutoff; otherwise show tentative source matches, not an answer.',
                test=dict(positive_queries=sum(q['split']=='test' and bool(q['relevant']) for q in queries),
                          positives_retained=sum(q['split']=='test' and bool(q['relevant']) and scores[q['id']]>=threshold for q in queries),
                          no_answer_queries=sum(q['split']=='test' and not q['relevant'] for q in queries),
                          no_answer_rejected=sum(q['split']=='test' and not q['relevant'] and scores[q['id']]<threshold for q in queries)),scores=scores)
    (ROOT/'evaluation/confidence-policy.json').write_text(json.dumps(record,indent=2)+'\n')
    print(json.dumps({k:v for k,v in record.items() if k!='scores'},indent=2))


if __name__=='__main__':main()
