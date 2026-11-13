"""Actual API, GPU inference, OCR, source export, and bill specialization checks."""
import json
from pathlib import Path
import time
import uuid
import pymupdf
import pytest
from fastapi.testclient import TestClient
from knowledge_library.server import create_app
from knowledge_library.bills import parse_date,parse_query

ROOT=Path(__file__).resolve().parents[1]
FIX=ROOT/'tests/fixtures'


@pytest.fixture(scope='module')
def session():
    root=ROOT/'.cache/desktop-tests'/uuid.uuid4().hex
    app=create_app(root)
    with TestClient(app) as client:
        state=client.get('/api/state').json();client.headers['X-Library-Token']=state['token']
        yield client,app.state.desktop


def wait(client,ids):
    deadline=time.monotonic()+120
    while time.monotonic()<deadline:
        jobs={j['id']:j for j in client.get('/api/state').json()['tasks']}
        if all(jobs[k]['status'] not in ('queued','running') for k in ids):return [jobs[k] for k in ids]
        time.sleep(.1)
    raise AssertionError('Indexing did not finish in 120 seconds')


def upload(client,folder,paths,**fields):
    streams=[p.open('rb') for p in paths]
    try:
        response=client.post('/api/uploads',data={'folder_id':folder,**fields},files=[('files',(p.name,s,'application/pdf')) for p,s in zip(paths,streams)])
    finally:
        for stream in streams:stream.close()
    assert response.status_code==200,response.text
    return wait(client,response.json()['task_ids'])


@pytest.mark.parametrize('text',['Sept 25 2026','September 25, 2026','25 Sep 2026','25/09/2026','2026-09-25','25.09.2026','Sep 25th, 2026'])
def test_bill_date_aliases(text):assert parse_date(text)=='2026-09-25'


def test_invalid_dates_and_nonbill_query_do_not_create_dates():
    assert parse_date('31/09/2026') is None
    assert parse_date('Invoice 2026-12345') is None
    assert parse_date('25/09') is None
    parsed=parse_query('Find invoice INV-PURCHASE-2020-01-01',[{'party':'Example','party_normalized':'example','invoice_number':'INV-PURCHASE-2020-01-01'}])
    assert parsed['invoice_number']=='INV-PURCHASE-2020-01-01' and parsed['date'] is None and parsed['direction'] is None


def test_local_api_csrf_host_and_empty_scope(session):
    client,desktop=session
    with pytest.raises(ValueError,match='already using this library'):
        create_app(desktop.root)
    token=client.headers.pop('X-Library-Token')
    assert client.post('/api/folders',json={'name':'Forbidden'}).status_code==403
    client.headers['X-Library-Token']=token
    assert client.post('/api/folders',json={'name':'Forbidden'},headers={'Origin':'https://external.example'}).status_code==403
    assert client.get('/api/state',headers={'Host':'external.example'}).status_code==400
    folder=client.post('/api/folders',json={'name':'Empty folder','color':'#54C8A4'}).json()
    calls=dict(desktop.model.stats)
    result=client.post('/api/search',json={'query':'anything','folder_id':folder['id']}).json()
    assert not result['results'] and result['empty_reason']=='empty_scope'
    assert calls==desktop.model.stats
    assert client.patch('/api/folders/'+folder['id'],json={'name':'Not changed','color':'invalid'}).status_code==400
    assert next(f for f in client.get('/api/state').json()['folders'] if f['id']==folder['id'])['name']=='Empty folder'


def test_bulk_index_search_export_and_remove(session):
    client,desktop=session
    folder=client.post('/api/folders',json={'name':'Actual model tests'}).json()['id']
    jobs=upload(client,folder,[FIX/'pdfs/native-unicode.pdf',FIX/'pdfs/malformed.pdf',FIX/'pdfs/scanned.pdf'],ocr='true')
    assert [j['status'] for j in jobs]==['completed','failed','completed']
    result=client.post('/api/search',json={'query':'How can I prove a language is not regular?','folder_id':folder}).json()
    assert result['results'],result
    assert result['results'][0]['page_number']==2
    hits=result['results'][:1]
    body={'query':result['query'],'chunk_ids':[h['chunk_id'] for h in hits],'sources':{str(h['chunk_id']):h['source_identity'] for h in hits}}
    exported=client.post('/api/export',json=body)
    assert exported.status_code==200,exported.text
    output=ROOT/'results/desktop-context-test.pdf';output.write_bytes(exported.content)
    with pymupdf.open(stream=exported.content,filetype='pdf') as pdf:
        text=' '.join(p.get_text() for p in pdf)
        assert result['query'] in text and 'native-unicode.pdf' in text and 'PDF page 2' in text
    calls=desktop.model.stats['document_texts_encoded']
    duplicate=upload(client,folder,[FIX/'pdfs/native-unicode.pdf'])
    assert duplicate[0]['result']['action']=='duplicate' and desktop.model.stats['document_texts_encoded']==calls
    assert client.delete('/api/folders/'+folder).status_code==400
    assert client.delete('/api/documents/'+hits[0]['document_id']).status_code==200
    assert client.post('/api/export',json=body).status_code==400
    with desktop.lib() as lib:assert lib.verify()['passed']


def test_bill_party_date_type_and_source_ocr(session):
    client,desktop=session
    folder=client.post('/api/folders',json={'name':'Synthetic bill tests'}).json()['id']
    paths=[FIX/f'bills/{name}.pdf' for name in ['sale-bhagwanti-2026-09-25','sale-bhagwanti-2026-09-24','sale-asha-2026-09-25','purchase-bhagwanti-2026-09-25','scanned-sale-bhagwanti']]
    jobs=upload(client,folder,paths,bill='true',ocr='true')
    assert all(j['status']=='completed' for j in jobs),jobs
    state=client.get('/api/state').json()
    bills=[b for b in state['bills'] if b['folder_id']==folder]
    assert len(bills)==5
    for bill in bills:
        assert bill['amount']=='5310.00' and bill['currency']=='INR'
        assert bill['reviewed']==0
    calls=dict(desktop.model.stats)
    for query in ['What did I sell to Bhagwanti Trading on Sept 25 2026?','sold to BHAGWANTI TRADING on 25/09/2026','sales invoice to Bhagwanti Trading on September 25, 2026']:
        result=client.post('/api/search',json={'query':query,'folder_id':folder}).json()
        assert result['mode']=='bill_fields' and len(result['results'])==2,result
        assert all(h['bill']['party']=='Bhagwanti Trading' and h['bill']['bill_date']=='2026-09-25' and h['bill']['direction']=='sale' for h in result['results'])
    assert calls==desktop.model.stats # Structured lookup needs no query or document inference.
    invoice=bills[0]['invoice_number']
    found=client.post('/api/search',json={'query':'Find invoice '+invoice,'folder_id':folder,'bills_only':True}).json()
    assert found['results'] and all(h['bill']['invoice_number']==invoice for h in found['results'])
    assert client.post('/api/search',json={'query':'sold to Bhagwanti Trading on September 31 2026','bills_only':True}).status_code==400
    purchase=client.post('/api/search',json={'query':'What did I purchase from Bhagwanti Trading on 25 Sep 2026?','folder_id':folder}).json()
    assert len(purchase['results'])==1 and purchase['results'][0]['bill']['direction']=='purchase'
    for query in ['sold to Bhagwanti Trading on Sept 26 2026','sold to Bhagwanti Traders on Sept 25 2026','sold to Bhagwanti Trading on Sept 25 2025']:
        assert not client.post('/api/search',json={'query':query,'folder_id':folder}).json()['results']
    for h in result['results']:
        raw=client.get(f"/api/documents/{h['document_id']}/file").content
        with pymupdf.open(stream=raw,filetype='pdf') as pdf:assert len(pdf)==1
        if 'scanned' in h['filename']:assert h['extraction_method']=='ocr'
    # A generic knowledge question containing 'to' must not be misrouted to bills.
    from knowledge_library.bills import search
    with desktop.lib() as lib:
        assert search(lib,'Where are ways to limit identifying and linking people during data processing described?') is None


def test_bill_review_correction_replacement_and_delete(session):
    client,desktop=session
    folder=client.post('/api/folders',json={'name':'Bill lifecycle'}).json()['id']
    doc=upload(client,folder,[FIX/'bills/sale-bhagwanti-2026-09-25.pdf'],bill='true')[0]['result']['document']
    response=client.get(f"/api/documents/{doc['id']}/bill").json();fields=response['saved']
    body={k:fields[k] for k in ['party','bill_date','invoice_number','direction','amount','currency','source_page']}
    body.update(party='Bhagwanti Trading Limited',reviewed=True)
    saved=client.put(f"/api/documents/{doc['id']}/bill",json=body)
    assert saved.status_code==200,saved.text
    assert saved.json()['reviewed']==1
    found=client.post('/api/search',json={'query':'sold to Bhagwanti Trading Limited on Sept 25 2026','folder_id':folder}).json()
    assert found['results'] and found['reliability']=='reviewed_bill_fields'
    replaced=upload(client,folder,[FIX/'bills/sale-asha-2026-09-25.pdf'],document_id=doc['id'],bill='true')
    assert replaced[0]['status']=='completed'
    assert not client.post('/api/search',json={'query':'sold to Bhagwanti Trading Limited on Sept 25 2026','folder_id':folder}).json()['results']
    changed=client.get(f"/api/documents/{doc['id']}/bill").json()['saved']
    assert changed['party']=='Asha Stationers' and changed['reviewed']==0
    assert client.delete(f"/api/documents/{doc['id']}").status_code==200
    assert not [b for b in client.get('/api/state').json()['bills'] if b['document_id']==doc['id']]
