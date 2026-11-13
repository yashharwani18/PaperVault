"""Real indexing plus regression checks for bill ranges, evidence and recovery."""
import datetime as dt
import hashlib
import io
import json
from pathlib import Path
import zipfile
import pytest
from knowledge_library.bills import date_range,parse_query
from knowledge_library.maintenance import restore_backup,schema
from tests.test_desktop import session,upload,FIX


@pytest.mark.parametrize('text,start,end',[
 ('last September','2026-09-01','2026-09-30'),('this September','2026-09-01','2026-09-30'),
 ('September 2025','2025-09-01','2025-09-30'),('last month','2026-09-01','2026-09-30'),
 ('this month','2026-10-01','2026-10-31'),('yesterday','2026-10-16','2026-10-16'),
 ('from 01/09/2026 to 25/09/2026','2026-09-01','2026-09-25'),
 ('between 1 Sep 2026 and 30 Sep 2026','2026-09-01','2026-09-30')])
def test_date_ranges(text,start,end):assert date_range(text,dt.date(2026,10,17))==(start,end)


@pytest.mark.parametrize('text',['from 30/09/2026 to 01/09/2026','between yesterday and today','September 25','September'])
def test_ambiguous_or_invalid_range_rejected(text):
    with pytest.raises(ValueError):date_range(text,dt.date(2026,10,17))


def test_calendar_rollover_and_nonbill_queries():
    assert date_range('last September',dt.date(2026,9,25))==('2025-09-01','2025-09-30')
    assert date_range('last month',dt.date(2026,1,2))==('2025-12-01','2025-12-31')
    assert parse_query('Explain the September lecture on Fourier transforms',[])['date_from'] is None


@pytest.fixture(scope='module')
def invoices(session):
    client,desktop=session
    folder=client.post('/api/folders',json={'name':'Upgrade bill regression'}).json()['id']
    jobs=upload(client,folder,[FIX/'bills'/f'{n}.pdf' for n in ['sale-bhagwanti-2026-09-25','sale-bhagwanti-2026-09-24','sale-asha-2026-09-25','purchase-bhagwanti-2026-09-25']],bill='true')
    assert all(j['status']=='completed' for j in jobs)
    return client,desktop,folder,[j['result']['document']['id'] for j in jobs]


def test_range_alias_item_filters_and_no_inference(invoices):
    client,desktop,folder,ids=invoices;before=dict(desktop.model.stats)
    assert client.put('/api/party-aliases',json={'alias':'BT','party':'Bhagwanti Trading'}).status_code==200
    assert client.put('/api/party-aliases',json={'alias':'Asha Stationers','party':'Bhagwanti Trading'}).status_code==400
    result=client.post('/api/search',json={'query':'all sales to BT in September 2026','bills_only':True,'folder_id':folder}).json()
    assert result['bill_matches']==2,result
    result=client.post('/api/search',json={'query':'Which bill contained A4 paper?','bills_only':True,'folder_id':folder}).json()
    assert result['bill_matches']==4 and all('A4 printer paper' in h['passage'] for h in result['results']),result
    assert all(h['match_reasons'] for h in result['results'])
    result=client.post('/api/search',json={'query':'Find invoices','bills_only':True,'folder_id':folder,'bill_filters':{'party':'BT','date_from':'2026-09-25','date_to':'2026-09-25','direction':'sale'}}).json()
    assert result['bill_matches']==1 and result['results'][0]['document_id']==ids[0]
    assert client.post('/api/search',json={'query':'Which bill contained bananas?','bills_only':True,'folder_id':folder}).json()['bill_matches']==0
    assert client.post('/api/search',json={'query':'mysterious nonsense','bills_only':True,'folder_id':folder}).json()['bill_matches']==0
    assert client.post('/api/search',json={'query':'invoices from 30/09/2026 to 01/09/2026','bills_only':True}).status_code==400
    assert desktop.model.stats==before


def test_evidence_matches_real_pdf_text(invoices):
    client,desktop,folder,ids=invoices
    r=client.get(f'/api/documents/{ids[0]}/evidence',params={'field':'party','value':'Bhagwanti Trading','page':1})
    assert r.status_code==200 and r.json()['found'] and r.json()['boxes'],r.text
    assert not client.get(f'/api/documents/{ids[0]}/evidence',params={'field':'party','value':'Invented party','page':1}).json()['found']
    assert client.get(f'/api/documents/{ids[0]}/evidence',params={'page':999}).status_code==400


def test_unknown_transaction_type_is_not_silently_a_sale(invoices):
    client,desktop,folder,ids=invoices
    original=client.get(f'/api/documents/{ids[0]}/bill').json()['saved']
    fields={k:original[k] for k in ('party','bill_date','invoice_number','direction','amount','currency','source_page')}
    try:
        assert client.put(f'/api/documents/{ids[0]}/bill',json={**fields,'direction':'unspecified'}).status_code==200
        r=client.post('/api/search',json={'query':'sales to BT on 25 September 2026','bills_only':True,'folder_id':folder}).json()
        assert not r['results'],r
        r=client.post('/api/search',json={'query':'invoices to BT on 25 September 2026','bills_only':True,'folder_id':folder}).json()
        assert ids[0] in [h['document_id'] for h in r['results']]
    finally:assert client.put(f'/api/documents/{ids[0]}/bill',json=fields).status_code==200


def test_recoverable_delete_and_source_protection(invoices):
    client,desktop,folder,ids=invoices;before=dict(desktop.model.stats)
    removed=client.delete('/api/documents/'+ids[0]);assert removed.status_code==200
    key=removed.json()['trash_id']
    assert any(t['id']==key for t in client.get('/api/state').json()['trash'])
    assert client.post('/api/cleanup',json={'confirmation':'no'}).status_code==400
    assert client.post('/api/cleanup',json={'confirmation':'CLEAN UNUSED PDFS'}).status_code==200
    r=client.post('/api/trash/'+key+'/restore',json={});assert r.status_code==200,r.text
    assert r.json()['id']==ids[0]
    assert desktop.model.stats==before
    with desktop.lib() as lib:assert lib.verify()['passed']


def test_backup_restore_and_corruption(invoices,tmp_path):
    client,desktop,folder,ids=invoices
    assert client.post('/api/feedback',json={'query':'A4 paper','kind':'useful','note':'Found exact invoice'}).status_code==200
    archive=client.post('/api/backup');assert archive.status_code==200,archive.text
    path=tmp_path/'backup.zip';path.write_bytes(archive.content)
    with desktop.lib() as lib:trusted=schema(lib)
    restored=restore_backup(path,tmp_path/'restored',desktop.model,trusted_schema=trusted)
    assert restored['integrity']['passed'] and restored['documents']==4
    from knowledge_library.library import Library
    with Library(restored['path'],desktop.model) as lib:
        assert lib.db.execute('SELECT count(*) FROM party_aliases').fetchone()[0]==1
        assert lib.db.execute('SELECT count(*) FROM feedback').fetchone()[0]==1
        assert all(Path(d['original_path']).is_file() for d in lib.documents())
    with pytest.raises(ValueError,match='new directory'):restore_backup(path,tmp_path/'restored',desktop.model,trusted_schema=trusted)
    with zipfile.ZipFile(io.BytesIO(archive.content)) as original:
        entries={n:original.read(n) for n in original.namelist()}
    entries['library.sqlite3']=b'corrupted'
    with zipfile.ZipFile(tmp_path/'bad.zip','w') as bad:
        for n,data in entries.items():bad.writestr(n,data)
    with pytest.raises(ValueError,match='checksum'):restore_backup(tmp_path/'bad.zip',tmp_path/'bad-restore',desktop.model,trusted_schema=trusted)
    assert not (tmp_path/'bad-restore').exists()
    malicious=dict(entries);malicious['../outside.pdf']=b'bad'
    with zipfile.ZipFile(tmp_path/'traversal.zip','w') as bad:
        for n,data in malicious.items():bad.writestr(n,data)
    with pytest.raises(ValueError):restore_backup(tmp_path/'traversal.zip',tmp_path/'traversal',desktop.model,trusted_schema=trusted)


def test_restore_api_preserves_live_library(invoices):
    client,desktop,folder,ids=invoices;before=client.get('/api/state').json()['stats']['documents']
    archive=client.post('/api/backup')
    result=client.post('/api/restore-backup',files={'file':('backup.zip',archive.content,'application/zip')})
    assert result.status_code==200,result.text
    assert result.json()['integrity']['passed'] and Path(result.json()['path'])!=desktop.root
    assert client.get('/api/state').json()['stats']['documents']==before
