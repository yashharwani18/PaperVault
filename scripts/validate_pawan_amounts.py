"""Read-only, source-PDF-grounded acceptance tests for the user's Pawan Bills."""
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import time
import urllib.request

import pymupdf

ROOT=Path(__file__).resolve().parents[1]
LIBRARY=ROOT/'data/demo-invoices'
BASE='http://127.0.0.1:8766'


def main():
    db=sqlite3.connect(f'file:{LIBRARY / "library.sqlite3"}?mode=ro',uri=True)
    db.row_factory=sqlite3.Row
    folder=db.execute("SELECT id FROM folders WHERE name='Pawan Bills'").fetchone()['id']
    docs={d['filename']:dict(d) for d in db.execute('SELECT * FROM documents WHERE folder_id=?',(folder,))}
    # Independent oracle: read managed PDFs directly, not the search parser or index.
    source={}
    for name,d in docs.items():
        path=LIBRARY/d['managed_path']
        assert hashlib.sha256(path.read_bytes()).hexdigest()==d['sha256']
        with pymupdf.open(path) as pdf:
            for number,page in enumerate(pdf,1):
                for m in re.finditer(r'(?im)^(Subtotal|Total)\s*\n\s*(?:₹\s*)?([\d,.]+)',page.get_text()):
                    source[name,m[1].lower()]=(m[2],number)
    expected_subtotals=[('INV-45shiv.pdf','61800'),('INV-127panipat.pdf','27200'),
        ('INV-127dhariwal.pdf','33720'),('INV-329harekirshna.pdf','16620'),
        ('INV36handloomhouse.pdf','29280'),('INV-122mahashukbhai.pdf','61440'),
        ('INV-38banaras.pdf','91470'),('INV-39bhavnahandloom.pdf','13600'),
        ('INV-40shiv.pdf','99600'),('INV-120rankua.pdf','22200'),
        ('INV-120satguru.pdf','22000'),('INV-37jyoti.pdf','14520'),('INV-145nurani.pdf','29074')]
    assert len(docs)==len(expected_subtotals)==13,'Folder changed; review test expectations first.'
    cases=[]
    for name,value in expected_subtotals:
        assert source[name,'subtotal'][0]==value+'.00'
        cases.append((f'which invoice had {value} subtotal?','subtotal',value+'.00',[name],{}))
    cases.extend([
        ('which invoice had a subtotal of 13,600.00?','subtotal','13600.00',['INV-39bhavnahandloom.pdf'],{}),
        ('invoice sub-total = 13,600.0','subtotal','13600.00',['INV-39bhavnahandloom.pdf'],{}),
        ('which invoice had 14280 total?','total','14280.00',['INV-39bhavnahandloom.pdf'],{}),
        ('which invoice had 14280 subtotal?','subtotal','14280.00',[],{}),
        ('which invoice had 136000 subtotal?','subtotal','136000.00',[],{}),
        ('which invoice had 13600 subtotal?','subtotal','13600.00',[],{'document_id':docs['INV36handloomhouse.pdf']['id']}),
        ('invoice total INR 30,744.00','total','30744.00',['INV36handloomhouse.pdf'],{'document_id':docs['INV36handloomhouse.pdf']['id']}),
    ])
    state=json.load(urllib.request.urlopen(BASE+'/api/state'))
    results=[]
    for number,(query,field,value,expected,scope) in enumerate(cases,1):
        start=time.perf_counter()
        request=urllib.request.Request(BASE+'/api/search',data=json.dumps(dict(query=query,folder_id=folder,**scope)).encode(),
            headers={'Content-Type':'application/json','X-Library-Token':state['token']})
        try:
            result=json.load(urllib.request.urlopen(request,timeout=30))
            hits=result['results'];actual=sorted(h['filename'] for h in hits)
            assert actual==sorted(expected),(expected,actual)
            assert result['mode']=='bill_fields' and result['query_embedding_s']==0
            assert result['reliability']=='exact_source_amount'
            if not hits:assert result['empty_reason']=='no_matching_amount' and not result['closest_available']
            for hit in hits:
                evidence=hit['amount_match'];ground_amount,ground_page=source[hit['filename'],field]
                assert ground_amount==value==evidence['value']
                assert hit['folder_id']==folder and hit['page_number']==ground_page==evidence['page_number']
                assert evidence['field']==field and evidence['evidence'] in hit['passage']
                assert hit['source_identity'] and hit['score_type']=='bill_fields'
            results.append(dict(test=number,query=query,field=field,amount=value,expected=expected,actual=actual,
                passed=True,pages=[h['page_number'] for h in hits],elapsed_ms=round((time.perf_counter()-start)*1000,1)))
        except Exception as error:
            results.append(dict(test=number,query=query,expected=expected,passed=False,error=str(error)))
    report=dict(folder='Pawan Bills',documents=len(docs),oracle='Direct text extraction from SHA-verified PDFs; no embeddings or search parser used for expected values.',
        scope='Exact subtotal/total searches, formatting, absent amounts, source-page evidence and document scope. Does not certify every app feature.',
        passed=sum(r['passed'] for r in results),total=len(results),tests=results)
    output=ROOT/'results/pawan-20-search-tests.json'
    output.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(f"{report['passed']}/{report['total']} passed. Report: {output}")
    for r in results:print(f"{r['test']:02} {'PASS' if r['passed'] else 'FAIL'} {r['query']}"+(f" — {r['error']}" if not r['passed'] else ''))
    assert report['passed']==report['total']==20


if __name__=='__main__':main()
