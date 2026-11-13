"""Download six primary-source research PDFs, pin their bytes, and extract inspection text."""
from pathlib import Path
import datetime as dt
import hashlib
import json
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'corpus/research-papers-2026-10-30'
PAPERS = [
    ('transformer','1706.03762','Attention Is All You Need'),
    ('bert','1810.04805','BERT: Pre-training of Deep Bidirectional Transformers for Language Understanding'),
    ('rag','2005.11401','Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks'),
    ('resnet','1512.03385','Deep Residual Learning for Image Recognition'),
    ('adam','1412.6980','Adam: A Method for Stochastic Optimization'),
    ('word2vec','1301.3781','Efficient Estimation of Word Representations in Vector Space'),
]

def main():
    import pymupdf
    BASE.mkdir(parents=True,exist_ok=True)
    rows=[]
    for id,arxiv,title in PAPERS:
        path=BASE/(id+'.pdf');url='https://arxiv.org/pdf/'+arxiv
        if not path.exists():
            req=urllib.request.Request(url,headers={'User-Agent':'Khoj research evaluation/0.1'})
            with urllib.request.urlopen(req,timeout=60) as response:
                data=response.read(20*1024*1024+1)
            if len(data)>20*1024*1024 or not data.lstrip().startswith(b'%PDF-'):
                raise ValueError('Invalid or oversized PDF download: '+url)
            with pymupdf.open(stream=data,filetype='pdf') as pdf:
                assert len(pdf)>0
            path.write_bytes(data)
        with pymupdf.open(path) as pdf:
            rows.append(dict(id=id,arxiv=arxiv,title=title,url=url,file=path.relative_to(ROOT).as_posix(),sha256=hashlib.sha256(path.read_bytes()).hexdigest(),pages=len(pdf),pdf_metadata=pdf.metadata))
            (BASE/(id+'.txt')).write_text('\n\n'.join('=== PHYSICAL PAGE '+str(i+1)+' ===\n'+page.get_text() for i,page in enumerate(pdf)),encoding='utf-8')
        print(id,rows[-1]['pages'],path.stat().st_size,flush=True)
        time.sleep(3)
    (BASE/'manifest.json').write_text(json.dumps(dict(downloaded_at=dt.datetime.now(dt.timezone.utc).isoformat(),source='Primary arXiv PDFs; latest available versions at download; bytes pinned by SHA256',documents=rows),indent=2),encoding='utf-8')

if __name__=='__main__':main()
