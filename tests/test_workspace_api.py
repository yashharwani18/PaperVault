import time
import pytest
from tests.test_desktop import session,upload,FIX,wait


@pytest.fixture(scope='module')
def imported(session):
    client,desktop=session
    folder=client.post('/api/folders',json={'name':'Workspace feature checks'}).json()['id']
    jobs=upload(client,folder,[FIX/'bills/sale-bhagwanti-2026-09-25.pdf',FIX/'bills/sale-bhagwanti-2026-09-24.pdf'],bill='true')
    assert all(j['status']=='completed' for j in jobs),jobs
    return client,desktop,folder,[j['result']['document']['id'] for j in jobs]


def test_automatic_folders_scope_comparison_and_highlight(imported):
    client,desktop,folder,ids=imported
    data=client.get('/api/workspace').json()
    group=next(g for g in data['linked_folders'] if set(ids)<=set(g['document_ids']))
    r=client.post('/api/search',json={'query':'total 5310','linked_folder_id':group['id']}).json()
    assert r['results'] and all(h['document_id'] in group['document_ids'] for h in r['results'])
    r=client.post('/api/compare',json={'document_ids':ids,'query':'paper'}).json()
    assert len(r['documents'])==2 and all(d['bill'] for d in r['documents'])
    assert all(d['source_amounts'] for d in r['documents'])
    r=client.get(f'/api/documents/{ids[0]}/highlight',params={'page':1,'text':'5,310.00'}).json()
    assert r['boxes'] and all(0<=b[0]<=1 and 0<=b[1]<=1 for b in r['boxes'])
    assert client.get(f'/api/documents/{ids[0]}/tables?page=9999').status_code==400
    assert client.get(f'/api/documents/{ids[0]}/tables?page=1').status_code==200


def test_corrections_have_source_bound_undo(imported):
    client,desktop,folder,ids=imported;key=ids[0]
    saved=client.get(f'/api/documents/{key}/bill').json()['saved']
    for party in ['Correction One','Correction Two']:
        r=client.put(f'/api/documents/{key}/bill',json={**saved,'party':party})
        assert r.status_code==200,r.text
    history=client.get(f'/api/documents/{key}/checks').json()['history'];assert len(history)==2
    assert client.post(f'/api/documents/{key}/bill/undo').status_code==200
    assert client.get(f'/api/documents/{key}/bill').json()['saved']['party']=='Correction One'
    assert client.post(f'/api/documents/{key}/bill/undo').status_code==200
    assert client.get(f'/api/documents/{key}/bill').json()['saved']['party']==saved['party']


def test_pause_keeps_search_responsive_and_resume_finishes(imported):
    client,desktop,folder,ids=imported
    assert client.post('/api/processing',json={'paused':True}).status_code==200
    try:
        path=FIX/'bills/purchase-bhagwanti-2026-09-25.pdf'
        with path.open('rb') as stream:r=client.post('/api/uploads',data={'folder_id':folder},files=[('files',(path.name,stream,'application/pdf'))])
        task=r.json()['task_ids'][0]
        started=time.monotonic()
        result=client.post('/api/search',json={'query':'total 5310','folder_id':folder})
        assert result.status_code==200 and time.monotonic()-started<20
        assert next(t for t in client.get('/api/state').json()['tasks'] if t['id']==task)['status']=='queued'
    finally:assert client.post('/api/processing',json={'paused':False}).status_code==200
    assert wait(client,[task])[0]['status']=='completed'


def test_refresh_unchanged_reuses_index_and_backup_metadata(imported):
    client,desktop,folder,ids=imported
    before=desktop.model.stats['document_texts_encoded']
    jobs=upload(client,folder,[FIX/'bills/sale-bhagwanti-2026-09-25.pdf'],refresh_existing='true')
    assert jobs[0]['result']['action'] in ('unchanged','duplicate'),jobs
    assert desktop.model.stats['document_texts_encoded']==before
    assert client.post('/api/verify-backup-readiness').json()['passed']


def test_ambiguous_amount_asks_and_explicit_field_resolves(imported):
    import pymupdf
    client,desktop,folder,ids=imported
    folder=client.post('/api/folders',json={'name':'Amount clarification'}).json()['id']
    files=[]
    for name,sub,total in [('a',900,1000),('b',1000,1100)]:
        with pymupdf.open() as pdf:
            page=pdf.new_page()
            page.insert_text((40,40),f'SYNTHETIC SOFTWARE TEST\nInvoice\nSubtotal: {sub}\nGrand Total: {total}\nNot a real transaction.')
            files.append(('files',(f'{name}.pdf',pdf.tobytes(),'application/pdf')))
    task_ids=client.post('/api/uploads',data={'folder_id':folder},files=files).json()['task_ids']
    assert all(j['status']=='completed' for j in wait(client,task_ids))
    r=client.post('/api/search',json={'query':'bill of 1000','folder_id':folder}).json()
    assert r['clarification']['choices']==['total','subtotal'] and not r['results']
    for field in ['total','subtotal']:
        r=client.post('/api/search',json={'query':'bill of 1000','folder_id':folder,'amount_field':field}).json()
        assert len(r['results'])==1 and r['results'][0]['amount_match']['field']==field
        assert 'clarification' not in r


def test_explicit_folder_refresh_updates_changed_file(imported):
    client,desktop,_,_=imported
    folder=client.post('/api/folders',json={'name':'Incremental refresh'}).json()['id']
    def send(path):
        with path.open('rb') as stream:
            r=client.post('/api/uploads',data={'folder_id':folder,'refresh_existing':'true'},files=[('files',('same-name.pdf',stream,'application/pdf'))])
        return wait(client,r.json()['task_ids'])[0]
    first=send(FIX/'bills/sale-bhagwanti-2026-09-25.pdf')
    second=send(FIX/'bills/sale-bhagwanti-2026-09-24.pdf')
    assert first['status']==second['status']=='completed'
    a=first['result']['document'];b=second['result']['document']
    assert a['id']==b['id'] and a['sha256']!=b['sha256'] and b['version']==a['version']+1
    before_tasks=len(client.get('/api/state').json()['tasks'])
    payload=(FIX/'bills/sale-bhagwanti-2026-09-25.pdf').read_bytes()
    r=client.post('/api/uploads',data={'folder_id':folder,'refresh_existing':'true'},files=[('files',('collision.pdf',payload,'application/pdf')),('files',('collision.pdf',payload,'application/pdf'))])
    assert r.status_code==400 and len(client.get('/api/state').json()['tasks'])==before_tasks


def test_ocr_refresh_is_explicit_and_normal_refresh_keeps_ocr(imported):
    import json
    client,desktop,folder,ids=imported;key=ids[0]
    r=client.post(f'/api/documents/{key}/refresh-ocr')
    assert r.status_code==200,r.text
    job=wait(client,[r.json()['task_id']])[0]
    assert job['status']=='completed',job
    assert json.loads(job['result']['document']['recipe'])['pdf']['ocr'] is True
    r=client.post(f'/api/documents/{key}/refresh')
    job=wait(client,[r.json()['task_id']])[0]
    assert job['status']=='completed' and job['result']['action']=='unchanged',job


def test_encrypted_backup_roundtrip_and_wrong_password_preserve_library(imported):
    from pathlib import Path
    client,desktop,folder,ids=imported
    before=client.get('/api/state').json()['stats']['documents']
    password='synthetic backup test password'
    r=client.post('/api/backup',json={'password':password})
    assert r.status_code==200 and r.content.startswith(b'LLBK01\r\n'),r.text[:100]
    encrypted_content=r.content
    def restore(secret):
        return client.post('/api/restore-backup',data={'password':secret},files={'file':('test.llbackup',encrypted_content,'application/octet-stream')})
    assert restore('wrong synthetic password').status_code==400
    restored=restore(password)
    assert restored.status_code==200,restored.text
    assert restored.json()['documents']==before and restored.json()['integrity']['passed']
    assert client.get('/api/state').json()['stats']['documents']==before
    assert not list((desktop.root/'uploads').glob('*.decrypted.zip*'))


def test_charging_policy_waits_and_resumes_at_checkpoint(imported,monkeypatch):
    from types import SimpleNamespace
    import psutil
    client,desktop,folder,ids=imported
    power=SimpleNamespace(power_plugged=False)
    monkeypatch.setattr(psutil,'sensors_battery',lambda:power)
    assert client.post('/api/processing',json={'paused':False,'charging_only':True}).status_code==200
    try:
        path=FIX/'bills/sale-bhagwanti-2026-09-25.pdf'
        with path.open('rb') as stream:
            r=client.post('/api/uploads',data={'folder_id':folder},files=[('files',(path.name,stream,'application/pdf'))])
        task=r.json()['task_ids'][0]
        assert client.get('/api/state').json()['processing']['waiting_for_power']
        assert next(t for t in client.get('/api/state').json()['tasks'] if t['id']==task)['status']=='queued'
        assert client.post('/api/search',json={'query':'total 5310','folder_id':folder}).status_code==200
        power.power_plugged=True
        assert wait(client,[task])[0]['status']=='completed'
    finally:assert client.post('/api/processing',json={'paused':False,'charging_only':False}).status_code==200
