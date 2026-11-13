"""Fresh native-engine research-paper evaluation with source-verified, frozen page labels.

Run: .venv/Scripts/python.exe scripts/evaluate_research_papers.py
The corpus/library are isolated from the user's library. No parameter tuning.
"""
from pathlib import Path
import argparse
import datetime as dt
import hashlib
import json
import re
import statistics
import sys
import time
import unicodedata

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
BASE=ROOT/'corpus/research-papers-2026-10-30'
OUT=ROOT/'results/research-paper-evaluation'
LABELS=ROOT/'evaluation/research-paper-queries.json'

# Written from inspecting the downloaded originals before running search.
# Pages are physical PDF pages, not printed page labels. Alternative passages
# are accepted only when their specific evidence anchors are verified too.
CASES=[
 ('tr-heads','transformer','How many parallel attention heads does the original Transformer use?',[(5,'h = 8 parallel attention')]),
 ('tr-position','transformer','How does the Transformer represent token order without recurrence?',[(6,'sine and cosine functions')]),
 ('tr-scale','transformer','Why does scaled dot product attention divide scores by the square root of the key dimension?',[(4,'extremely small gradients')]),
 ('tr-score','transformer','What English to German translation BLEU score did the Transformer report?',[(1,'28.4 BLEU'),(8,'28.4')]),
 ('bert-vocab','bert','What vocabulary and subword tokenization does BERT use?',[(4,'30,000 token vocabulary')]),
 ('bert-corpus','bert','Which text collections and word counts were used to pretrain BERT?',[(5,'BooksCorpus (800M words)')]),
 ('bert-mask','bert','What percentage of tokens are selected for masked language model prediction in BERT?',[(4,'15% of all WordPiece')]),
 ('bert-nsp','bert','How are positive and negative next sentence prediction examples constructed for BERT?',[(4,'50% of the time')]),
 ('rag-frozen','rag','Which parts of RAG are updated during training and why is the document encoder frozen?',[(4,'keep the document encoder')]),
 ('rag-variants','rag','How do RAG Sequence and RAG Token differ in their use of retrieved documents?',[(3,'same retrieved document')]),
 ('rag-index','rag','How many Wikipedia chunks are in the RAG index and how long is each chunk?',[(4,'21M documents')]),
 ('rag-generator','rag','Which pretrained generator is used by the original retrieval augmented generation model?',[(3,'BART-large')]),
 ('res-degradation','resnet','Why can adding more layers to a plain neural network increase training error?',[(1,'degradation'),(2,'degradation')]),
 ('res-shortcut','resnet','What function do shortcut connections add to the output of a residual block?',[(3,'identity mapping')]),
 ('res-bottleneck','resnet','What sequence of convolutions is used in the residual bottleneck design?',[(6,'bottleneck'),(7,'bottleneck')]),
 ('res-ensemble','resnet','What top five ImageNet test error did the ResNet ensemble achieve?',[(1,'3.57%'),(6,'3.57')]),
 ('adam-default','adam','What default learning rate and moment decay values does Adam recommend?',[(2,'0.001')]),
 ('adam-bias','adam','Why does Adam correct the bias of its moment estimates at the start of training?',[(2,'initialized as'),(3,'initialization bias')]),
 ('adam-rms','adam','How does Adam differ from RMSProp with momentum?',[(5,'RMSProp with momentum')]),
 ('adam-max','adam','What is AdaMax and which norm is its update rule based on?',[(1,'infinity norm'),(8,'7.1 ADAMAX'),(9,'infinity norm')]),
 ('w2v-analogy','word2vec','How can word vectors express the relationship between king man woman and queen?',[(2,'Queen')]),
 ('w2v-cbow','word2vec','How do CBOW and Skip gram differ in which word they predict?',[(4,'predicting the current word'),(5,'predicts surrounding words')]),
 ('w2v-distributed','word2vec','How were word vector models trained across machines using DistBelief?',[(4,'centralized server')]),
 ('w2v-questions','word2vec','How many semantic and syntactic analogy questions are in the word vector test set?',[(6,'8869 semantic and 10675 syntactic')]),
]
NEGATIVES=[
 ('absent-surgery','What randomized trial in these papers compares surgical treatments for appendicitis?'),
 ('absent-battery','What electrolyte composition produced the longest lithium battery cycle life?'),
 ('absent-tax','What GST invoice number belongs to vendor Shree Ganesh Traders in April 2026?'),
]

def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def norm(text):return re.sub(r'\s+',' ',unicodedata.normalize('NFKC',text)).casefold()
def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,indent=2,ensure_ascii=False),encoding='utf-8')

def freeze_labels(manifest):
    import pymupdf
    texts={}
    for entry in manifest['documents']:
        source=ROOT/entry['file'];assert digest(source)==entry['sha256']
        with pymupdf.open(source) as pdf:texts[entry['id']]=[p.get_text() for p in pdf]
    rows=[]
    for id,doc,query,expected in CASES:
        evidence=[]
        for page,anchor in expected:
            source=texts[doc][page-1]
            if norm(anchor) not in norm(source):
                raise ValueError(f'Unverified label {id} page {page}: {anchor}')
            evidence.append(dict(document=doc,page=page,anchor=anchor,page_text_sha256=hashlib.sha256(source.encode()).hexdigest()))
        rows.append(dict(id=id,query=query,relevant=evidence))
    rows.extend(dict(id=id,query=query,relevant=[]) for id,query in NEGATIVES)
    value=dict(judgment_provenance='Agent-authored from direct inspection of these PDF originals before scoring; not independent human judgments.',
               judgment_scope='Non-exhaustive page labels. A miss means no labeled page was in the cutoff; unlabeled pages may also be relevant. Small ML-only corpus, native-text PDFs, English queries; no claim of general accuracy.',
               queries=rows)
    if LABELS.exists() and json.loads(LABELS.read_text(encoding='utf-8'))!=value:
        raise ValueError('Labels changed; preserve original labels before any diagnostic iteration.')
    write(LABELS,value)
    return value

def main():
    sys.stdout.reconfigure(encoding='utf-8')
    parser=argparse.ArgumentParser();parser.add_argument('--labels-only',action='store_true');args=parser.parse_args()
    manifest=json.loads((BASE/'manifest.json').read_text(encoding='utf-8'))
    labels=freeze_labels(manifest)
    print('Verified and froze',len(labels['queries']),'questions. Labels SHA256:',digest(LABELS),flush=True)
    if args.labels_only:return
    from knowledge_library.library import Library
    from knowledge_library.embedding import EmbeddingGemma
    model=EmbeddingGemma(device='cuda',batch_size=8)
    isolated=ROOT/'.cache/research-paper-evaluation/library'
    report=dict(status='running',recorded_at=dt.datetime.now(dt.timezone.utc).isoformat(),labels_sha256=digest(LABELS),
                labels_provenance=labels['judgment_provenance'],limitations=labels['judgment_scope'],
                isolated_library=str(isolated),documents=[],queries=[],summaries={})
    write(OUT/'report.json',report)
    started=time.perf_counter()
    with Library(isolated,model) as lib:
        folders=lib.folders();folder=next((r['id'] for r in folders if r['name']=='Research-paper test'),None)
        if folder is None:folder=lib.create_folder('Research-paper test')['id']
        mapping={}
        for entry in manifest['documents']:
            t=time.perf_counter()
            result=lib.import_pdf(ROOT/entry['file'],folder,title=entry['title'])
            doc=result['document'];mapping[doc['id']]=entry['id']
            report['documents'].append(dict(id=entry['id'],document_id=doc['id'],pages=doc['page_count'],chunks=doc['chunk_count'],status=doc['status'],action=result['action'],seconds=time.perf_counter()-t))
            print('INDEX',report['documents'][-1],flush=True)
            write(OUT/'report.json',report)
            assert doc['status']=='indexed',report['documents'][-1]
        report['index_seconds']=time.perf_counter()-started
        assert sum(r['pages'] for r in report['documents'])==sum(r['pages'] for r in manifest['documents'])
        report['integrity']=lib.verify();assert report['integrity']['passed']
        for mode in ('semantic','hybrid','bm25','literal'):
            for q in labels['queries']:
                result=lib.search(q['query'],mode=mode,top_k=5)
                hits=[dict(document=mapping[h['document_id']],page=h['page_number'],score=h['score'],text=h['passage']) for h in result['results']]
                row=dict(id=q['id'],query=q['query'],mode=mode,relevant=q['relevant'],hits=hits,seconds=result['elapsed_s'])
                if q['relevant']:
                    gold={(r['document'],r['page']) for r in q['relevant']}
                    ranks=[i for i,h in enumerate(hits,1) if (h['document'],h['page']) in gold]
                    row.update(page_hit1=bool(ranks and ranks[0]==1),page_hit5=bool(ranks),reciprocal_rank=1/ranks[0] if ranks else 0,
                               file_hit1=bool(hits and hits[0]['document'] in {d for d,p in gold}),file_hit5=any(h['document'] in {d for d,p in gold} for h in hits))
                else:row['returned_candidates']=len(hits)
                report['queries'].append(row)
                print(mode,q['id'],('HIT' if row['page_hit5'] else 'MISS') if q['relevant'] else 'NEGATIVE: '+str(len(hits))+' candidates',flush=True)
                write(OUT/'report.json',report)
            positive=[r for r in report['queries'] if r['mode']==mode and r['relevant']]
            negative=[r for r in report['queries'] if r['mode']==mode and not r['relevant']]
            report['summaries'][mode]={k:sum(r[k] for r in positive)/len(positive) for k in ('page_hit1','page_hit5','file_hit1','file_hit5','reciprocal_rank')}
            report['summaries'][mode].update(answerable_queries=len(positive),no_answer_controls=len(negative),no_answer_controls_returning_candidates=sum(bool(r['returned_candidates']) for r in negative),median_query_seconds=statistics.median(r['seconds'] for r in positive))
        report.update(status='complete',model_signature=model.signature,model_stats=model.stats,total_seconds=time.perf_counter()-started)
    write(OUT/'report.json',report)
    print(json.dumps(report['summaries'],indent=2),flush=True)

if __name__=='__main__':main()
