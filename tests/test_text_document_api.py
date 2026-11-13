"""Native text ingress, provenance and PDF-boundary integration; no model downloads."""
import io
import time
import zipfile
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient
from tokenizers import Tokenizer

from knowledge_library import server

ROOT = Path(__file__).resolve().parents[1]


class Encoder:
    dimensions=128;batch_size=4;dtype='test'
    signature=dict(model_id='native-text-test',revision='1',configuration_version='1')
    def __init__(self,**kwargs):
        self.tokenizer=Tokenizer.from_file(str(next((ROOT/'models/embeddinggemma-2').rglob('tokenizer.json'))))
        self.stats=dict(document_texts_encoded=0,query_texts_encoded=0,model_loads=0)
        self._model=object()
        self._torch=None;self.device='cpu'
    def load(self):return self._model
    def query(self,text):
        self.stats['query_texts_encoded']+=1
        v=np.zeros(128,dtype='<f4');v[0]=1;return v
    def documents(self,title,texts):
        self.stats['document_texts_encoded']+=len(texts)
        return [self.query(t) for t in texts]


@pytest.fixture
def api(tmp_path,monkeypatch):
    monkeypatch.setattr(server,'EmbeddingGemma',Encoder)
    app=server.create_app(tmp_path/'library',device='cpu',preload=False)
    with TestClient(app) as client:
        client.headers['X-Library-Token']=client.get('/api/state').json()['token']
        folder=client.post('/api/folders',json={'name':'Text documents'}).json()['id']
        yield client,app.state.desktop,folder


def wait(client,ids):
    deadline=time.monotonic()+20
    while time.monotonic()<deadline:
        tasks={t['id']:t for t in client.get('/api/state').json()['tasks']}
        if all(tasks[i]['status'] not in ('queued','running') for i in ids):return [tasks[i] for i in ids]
        time.sleep(.05)
    raise AssertionError('Text indexing did not finish')


def upload(api,name,content):
    client,_,folder=api
    r=client.post('/api/uploads',data={'folder_id':folder},files=[('files',(name,content,'application/octet-stream'))])
    assert r.status_code==200,r.text
    jobs=wait(client,r.json()['task_ids']);assert all(j['status']=='completed' for j in jobs),jobs
    return jobs[0]['result']['document']


def test_skip_queued_file_and_retry(api,tmp_path):
    import threading
    client,desktop,folder=api
    blocker=threading.Event();started=threading.Event()
    def occupy():started.set();blocker.wait(10)
    desktop.index_pool.submit(occupy);assert started.wait(2)
    source=tmp_path/'queued.txt';source.write_text('Never index until explicitly retried')
    try:
        task=desktop.queue(folder,source,source.name)
        assert client.post(f'/api/tasks/{task}/skip').json()['status']=='skipped'
    finally:blocker.set()
    desktop.futures[task].result(timeout=10)
    assert client.get('/api/state').json()['documents']==[]
    assert source.exists()
    assert client.post(f'/api/tasks/{task}/retry').status_code==200
    assert wait(client,[task])[0]['status']=='completed'


def test_skip_active_replacement_keeps_old_index(api,tmp_path,monkeypatch):
    import threading
    client,desktop,folder=api
    old=upload(api,'current.txt',b'Original searchable content about impedance matching.')
    entered=threading.Event();release=threading.Event();original=desktop.model.documents
    def blocked(*args,**kwargs):
        entered.set();release.wait(10);return original(*args,**kwargs)
    monkeypatch.setattr(desktop.model,'documents',blocked)
    source=tmp_path/'new.txt';source.write_text('Replacement searchable content about amplifier design.')
    task=desktop.queue(folder,source,source.name,document_id=old['id'])
    try:
        assert entered.wait(5)
        assert client.post(f'/api/tasks/{task}/skip').json()['status']=='skipping'
    finally:release.set()
    desktop.futures[task].result(timeout=10)
    assert desktop.tasks([task])[0]['status']=='skipped'
    current=client.get('/api/documents/'+old['id']).json()['document']
    assert current['sha256']==old['sha256'] and source.exists()


def test_native_revision_and_pdf_evidence_boundary(api):
    client,desktop,_=api;doc=upload(api,'stable.txt',b'Source text with reliable provenance and a stable location.')
    assert client.get(f"/api/documents/{doc['id']}/units/1?revision=obsolete").status_code==409
    assert client.get(f"/api/documents/{doc['id']}/evidence").status_code==400


def test_skipped_discovered_file_stays_out_of_queue_until_source_changes(api,tmp_path):
    import threading
    from knowledge_library.library import now
    client,desktop,folder=api
    directory=tmp_path/'watched';directory.mkdir();source=directory/'skip.txt';source.write_text('User chose to skip this source.')
    stat=source.stat();signature=f'{stat.st_size}:{stat.st_mtime_ns}'
    with desktop.lib() as lib,lib.db:
        lib.db.execute("INSERT INTO watched_sources(id,path,name,folder_id,created_at,state) VALUES(?,?,?,?,?,'watching')",('skip-source',str(directory),'Watched',folder,now()))
        lib.db.execute('INSERT INTO watched_files(source_id,relative_path,signature) VALUES(?,?,?)',('skip-source',source.name,signature))
    blocker=threading.Event();started=threading.Event()
    def occupy():started.set();blocker.wait(10)
    desktop.index_pool.submit(occupy);assert started.wait(2)
    try:
        task=desktop.queue(folder,source,source.name,discovered=('skip-source',source.name,signature))
        assert desktop.skip(task)['status']=='skipped'
    finally:blocker.set()
    desktop.futures[task].result(timeout=10)
    desktop.discovery.reconcile();desktop.discovery.queue_pending()
    with desktop.lib() as lib:
        row=lib.db.execute('SELECT * FROM watched_files').fetchone()
        assert row['state']=='skipped' and row['task_id'] is None
        assert lib.db.execute('SELECT count(*) FROM app_tasks').fetchone()[0]==1
    # Explicit retry is allowed even while the source itself is unchanged.
    assert client.post(f'/api/tasks/{task}/retry').status_code==200
    assert wait(client,[task])[0]['status']=='completed'


def test_skip_active_pdf_does_not_leave_partial_pages(api,tmp_path,monkeypatch):
    import threading
    import pymupdf
    client,desktop,folder=api
    source=tmp_path/'long.pdf'
    with pymupdf.open() as pdf:
        for i in range(8):pdf.new_page().insert_text((50,60),f'Unique source section {i} on impedance and signal processing.')
        pdf.save(source)
    entered=threading.Event();release=threading.Event();encode=desktop.model.documents;calls=0
    def blocked(*args,**kwargs):
        nonlocal calls
        calls+=1
        if calls==3:entered.set();release.wait(10)
        return encode(*args,**kwargs)
    monkeypatch.setattr(desktop.model,'documents',blocked)
    task=desktop.queue(folder,source,source.name)
    try:
        assert entered.wait(5)
        assert desktop.skip(task)['status']=='skipping'
    finally:release.set()
    desktop.futures[task].result(timeout=10)
    assert desktop.tasks([task])[0]['status']=='skipped'
    assert client.get('/api/state').json()['documents']==[]


def xlsx():
    b=io.BytesIO()
    with zipfile.ZipFile(b,'w') as z:
        z.writestr('[Content_Types].xml','<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        z.writestr('xl/workbook.xml','<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Revenue" sheetId="1" r:id="rId1"/></sheets></workbook>')
        z.writestr('xl/_rels/workbook.xml.rels','<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Target="worksheets/sheet1.xml" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"/></Relationships>')
        z.writestr('xl/worksheets/sheet1.xml','<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="7"><c r="A7" t="inlineStr"><is><t>Acme retained revenue</t></is></c><c r="C7"><v>13600</v></c></row></sheetData></worksheet>')
    return b.getvalue()


def test_capabilities_include_native_text_but_exclude_media_and_legacy(api):
    state=api[0].get('/api/state').json();caps=state['import_capabilities']
    expected={'pdf','docx','odt','txt','md','markdown','html','htm','json','jsonl','xlsx','ods','csv','tsv'}
    assert expected<=set(caps['upload_extensions']) and expected<=set(caps['scan_extensions'])
    assert not {'jpg','mp3','mp4','doc','xls','rtf','docm','xlsm'}&set(caps['upload_extensions'])


def test_native_upload_search_view_and_original_are_not_fake_pdf_pages(api):
    client,_,folder=api;content='Heading\nCafé source evidence about impedance matching.\n'.encode()
    doc=upload(api,'notes.txt',content)
    assert doc['preview_kind']=='text' and doc['source_format']=='txt'
    detail=client.get('/api/documents/'+doc['id']).json();unit=detail['pages'][0]
    assert unit['location']['label'] and unit['unit_number']==1
    page=client.get(f"/api/documents/{doc['id']}/units/1");assert page.status_code==200
    assert 'Café' in page.json()['text']
    r=client.post('/api/search',json={'query':'impedance matching','document_id':doc['id'],'folder_id':folder}).json()
    assert r['results'],r
    hit=r['results'][0];assert hit['preview_kind']=='text' and hit['location']['label']
    assert '#page=' not in hit['open_uri']
    original=client.get(f"/api/documents/{doc['id']}/file")
    assert original.status_code==200 and original.content==content
    assert 'attachment' in original.headers['content-disposition'] and 'notes.txt' in original.headers['content-disposition']
    assert 'text/plain' in original.headers['content-type']
    assert client.post(f"/api/documents/{doc['id']}/refresh-ocr").status_code==400
    assert client.get(f"/api/documents/{doc['id']}/tables?page=1").status_code==400
    assert client.get(f"/api/documents/{doc['id']}/highlight?page=1&text=impedance").status_code==400


def test_spreadsheet_upload_preserves_sheet_and_sparse_row_location(api):
    client,_,folder=api;doc=upload(api,'revenue.xlsx',xlsx())
    result=client.post('/api/search',json={'query':'Acme revenue','document_id':doc['id'],'folder_id':folder}).json()
    assert result['results'],result
    hit=result['results'][0];loc=hit['location']
    assert hit['source_kind']=='spreadsheet' and loc['sheet']=='Revenue'
    assert loc['row_start']<=7<=loc['row_end']
    assert '13600' in hit['passage'] and 'C7' in hit['passage']
    citation=result['response']['citations'][0]
    assert citation['location']=='Revenue · Row 7' and citation['preview_kind']=='text'


def test_mixed_invalid_upload_is_rejected_before_any_queueing(api):
    client,_,folder=api;before=len(client.get('/api/state').json()['tasks'])
    r=client.post('/api/uploads',data={'folder_id':folder},files=[('files',('ok.txt',b'Valid text','text/plain')),('files',('bad.mp4',b'not media','video/mp4'))])
    assert r.status_code==400 and len(client.get('/api/state').json()['tasks'])==before


def test_folder_discovery_imports_native_sources_in_place_and_ignores_media(api,tmp_path):
    client,desktop,_=api;directory=tmp_path/'Documents';directory.mkdir()
    (directory/'notes.md').write_text('# Notes\nOriginal visible paragraphs about signals.',encoding='utf-8')
    (directory/'rows.csv').write_text('Name,Value\nAcme,13600\n',encoding='utf-8')
    (directory/'photo.jpg').write_bytes(b'not decoded');(directory/'audio.mp3').write_bytes(b'not decoded')
    r=client.post('/api/connections',json={'path':str(directory)});assert r.status_code==200,r.text
    deadline=time.monotonic()+20
    while time.monotonic()<deadline:
        docs=client.get('/api/state').json()['documents']
        if len(docs)>=2:break
        time.sleep(.05)
    else:raise AssertionError(client.get('/api/connections').text)
    assert {d['filename'] for d in docs}=={'notes.md','rows.csv'}
    assert all(d['source_mode']=='reference' and Path(d['managed_path']).parent==directory for d in docs)
    with desktop.lib() as lib:assert not list((lib.root/'files').iterdir())

def test_hybrid_search_prioritizes_literal_passage_and_respects_scope(api, monkeypatch):
    client,desktop,folder=api
    other_folder=client.post('/api/folders',json={'name':'Other scope'}).json()['id']
    upload(api,'irrelevant.txt',b'Unrelated text about weather and clouds.')
    wanted=upload(api,'invoice.txt',b'Invoice Number INV-inv25 customer\nTotal 6627.60')
    upload(api,'different.txt',b'Invoice Number INV-inv125 customer')
    # An uninformative semantic model must not hide an exact indexed hit.
    desktop.policy['threshold']=2.0
    for query in ('inv25','invoice number 25'):
        response=client.post('/api/search',json={'query':query,'folder_id':folder})
        assert response.status_code==200,response.text
        result=response.json();assert result['results'],result
        assert result['results'][0]['document_id']==wanted['id']
        assert 'Exact text match' in result['results'][0]['match_reasons'][0]
        assert not result['below_cutoff']
    assert not client.post('/api/search',json={'query':'inv25','folder_id':other_folder}).json()['results']

def test_general_qwen_interpretation_is_used_with_original_query(api, monkeypatch):
    client,desktop,folder=api
    doc=upload(api,'algorithms.txt',b'Dijkstra shortest path algorithms')
    calls=[];embeddings=[]
    monkeypatch.setattr(desktop.interpreter,'interpret_general',lambda q: calls.append(q) or 'Dijkstra shortest path algorithms')
    original=desktop.model.query
    monkeypatch.setattr(desktop.model,'query',lambda q: embeddings.append(q) or original(q))
    response=client.post('/api/search',json={'query':'find routes in a graph','folder_id':folder})
    assert response.status_code==200,response.text
    data=response.json();assert calls==['find routes in a graph']
    assert data['query_interpreter']=='qwen'
    assert embeddings[-1]=='find routes in a graph\nDijkstra shortest path algorithms'
    assert data['results'][0]['document_id']==doc['id']

def test_search_preview_prioritizes_formats_and_respects_scope(api, monkeypatch):
    client, desktop, folder = api
    docs = [upload(api, f'notes-{n}.txt', f'Shortest path algorithms. Note {n}.'.encode()) for n in range(6)]
    filenames = ['slides.pptx', 'notes.docx', 'sheet.csv', 'notes.pdf', 'other.pdf', 'readme.txt']
    with desktop.lib() as lib, lib.db:
        lib.db.executemany('UPDATE documents SET filename=? WHERE id=?',
                           [(filename, doc['id']) for filename, doc in zip(filenames, docs)])

    def unexpected_model_call(*args):
        pytest.fail('Quick matches should use the existing text index')

    monkeypatch.setattr(desktop.model, 'query', unexpected_model_call)
    monkeypatch.setattr(desktop.interpreter, 'interpret_general', unexpected_model_call)
    body = {'query': 'find shortest path', 'folder_id': folder, 'preview_only': True}
    response = client.post('/api/search', json=body)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data['mode'] == 'preview'
    hits = data['results']
    assert [hit['filename'].rsplit('.', 1)[-1] for hit in hits] == ['pdf', 'docx', 'csv', 'pptx', 'txt']
    assert all(hit['source_identity'] and 'Shortest path' in hit['passage'] for hit in hits)
    assert client.post('/api/search', json={**body, 'query': 'ext:csv shortest path'}).json()['results'][0]['filename'] == 'sheet.csv'
    assert client.post('/api/search', json={**body, 'document_ids': []}).json()['results'] == []
    assert client.post('/api/search', json={**body, 'bills_only': True}).json()['results'] == []


def test_literal_results_survive_semantic_model_failure(api, monkeypatch):
    client,desktop,folder=api
    doc=upload(api,'notes.txt',b'EXPERIMENT 45 contains a concrete identifier')
    monkeypatch.setattr(desktop.interpreter,'interpret_general',lambda q: (_ for _ in ()).throw(ValueError('unavailable')))
    monkeypatch.setattr(desktop.model,'query',lambda q: (_ for _ in ()).throw(RuntimeError('unavailable')))
    response=client.post('/api/search',json={'query':'EXPERIMENT 45','folder_id':folder})
    assert response.status_code==200,response.text
    result=response.json();assert result['results'][0]['document_id']==doc['id']
    assert result['query_interpreter']=='unavailable' and 'semantic search was unavailable' in result['note']

def test_exact_filename_lookup_is_scoped_and_never_loads_models(api,monkeypatch):
    client,desktop,folder=api
    first=upload(api,'Operating Systems Unit 3.txt',b'Topic of the first note')
    second_folder=client.post('/api/folders',json={'name':'Another course'}).json()['id']
    second=upload((client,desktop,second_folder),'Operating Systems Unit 3.txt',b'Topic of a different note')
    monkeypatch.setattr(desktop.model,'query',lambda q: (_ for _ in ()).throw(AssertionError('embedding called')))
    monkeypatch.setattr(desktop.interpreter,'interpret_general',lambda q: (_ for _ in ()).throw(AssertionError('LLM called')))
    matches=client.post('/api/filename-matches',json={'query':' operating-systems unit 3 '}).json()['matches']
    assert {m['document_id'] for m in matches}=={first['id'],second['id']}
    assert all(m['available'] for m in matches)
    scoped=client.post('/api/filename-matches',json={'query':'OPERATING SYSTEMS UNIT 3.TXT','folder_id':folder}).json()['matches']
    assert len(scoped)==1 and scoped[0]['document_id']==first['id']
    with desktop.lib() as lib: lib.source_path(lib.document(first['id'])).unlink()
    missing=client.post('/api/filename-matches',json={'query':'Operating Systems Unit 3','folder_id':folder}).json()['matches']
    assert len(missing)==1 and not missing[0]['available']

def test_desktop_reading_state_persists_favorites_and_position(api):
    client,_,folder=api
    doc=upload(api,'favorites.txt',b'A private document')
    response=client.post(f"/api/documents/{doc['id']}/reading-state",json={'sha256':doc['sha256'],'favorite':True,'opened':True,'page':1})
    assert response.status_code==200,response.text
    state=client.get('/api/reading-state').json()
    assert state['documents'][doc['id']]['favorite'] is True
    assert state['documents'][doc['id']]['page']==1
    assert doc['id'] in state['recent_ids']
    assert client.post(f"/api/documents/{doc['id']}/reading-state",json={'sha256':'changed','page':1}).status_code==400
    assert client.post(f"/api/documents/{doc['id']}/reading-state",json={'page':100}).status_code==400

def test_search_document_scope_composes_with_exact_and_content_search(api,monkeypatch):
    client,desktop,folder=api
    first=upload(api,'notes.txt',b'ZEPHYR source in the first file')
    second=upload(api,'other.txt',b'ZEPHYR source in the second file')
    monkeypatch.setattr(desktop.interpreter,'interpret_general',lambda q: q)
    lookup=client.post('/api/filename-matches',json={'query':'notes','folder_id':folder,'document_ids':[second['id']]}).json()
    assert lookup['matches']==[]
    result=client.post('/api/search',json={'query':'ZEPHYR','folder_id':folder,'document_ids':[second['id']]}).json()
    assert result['results'] and all(h['document_id']==second['id'] for h in result['results'])
    empty=client.post('/api/search',json={'query':'ZEPHYR','folder_id':folder,'document_ids':[]}).json()
    assert empty['results']==[]

def test_selected_documents_can_be_removed_and_restored_without_deleting_sources(api):
    client,desktop,folder=api
    docs=[upload(api,'first.txt',b'first unique text'),upload(api,'second.txt',b'second unique text')]
    with desktop.lib() as lib:paths=[lib.source_path(lib.document(d['id'])) for d in docs]
    keys=[]
    for doc in docs:
        response=client.delete('/api/documents/'+doc['id']);assert response.status_code==200,response.text
        keys.append(response.json()['trash_id'])
    assert all(path.exists() for path in paths)
    assert not {d['id'] for d in docs}&{d['id'] for d in client.get('/api/state').json()['documents']}
    for key in keys:
        response=client.post('/api/trash/'+key+'/restore',json={'folder_id':None});assert response.status_code==200,response.text
    assert {d['id'] for d in docs}<={d['id'] for d in client.get('/api/state').json()['documents']}
    assert all(path.exists() for path in paths)

def test_filename_lookup_is_not_queued_behind_an_active_ai_search(api):
    import threading
    client,desktop,folder=api
    doc=upload(api,'quick.txt',b'a quick document')
    blocked=threading.Event();started=threading.Event()
    def occupy():
        with desktop.lib() as lib:
            lib.db.execute('BEGIN');lib.db.execute('SELECT count(*) FROM documents').fetchone()
            started.set();blocked.wait(10)
    job=desktop.pool.submit(occupy);assert started.wait(2)
    try:
        began=time.monotonic()
        result=client.post('/api/filename-matches',json={'query':'quick','folder_id':folder})
        assert result.status_code==200,result.text
        assert result.json()['matches'][0]['document_id']==doc['id']
        assert time.monotonic()-began<3
    finally:blocked.set();job.result(timeout=10)

def test_library_preferences_survive_desktop_restart(tmp_path,monkeypatch):
    monkeypatch.setattr(server,'EmbeddingGemma',Encoder)
    root=tmp_path/'persisted-library'
    def app_client():return TestClient(server.create_app(root,device='cpu',preload=False))
    with app_client() as client:
        client.headers['X-Library-Token']=client.get('/api/state').json()['token']
        result=client.patch('/api/library-preferences',json={'sort':'name','search_history':['one','two']})
        assert result.status_code==200,result.text
    with app_client() as client:
        client.headers['X-Library-Token']=client.get('/api/state').json()['token']
        prefs=client.get('/api/library-preferences').json()
        assert prefs['sort']=='name' and prefs['search_history']==['one','two']
        assert client.patch('/api/library-preferences',json={'search_history':[]}).status_code==200
        assert client.get('/api/library-preferences').json()['search_history']==[]


def test_incremental_catalog_refresh_returns_changed_documents(api):
    client,_,_=api
    original=client.get('/api/state').json()
    assert isinstance(original['documents'],list)
    revision=original['documents_revision']
    unchanged=client.get('/api/state',params={'documents_revision':revision}).json()
    assert unchanged['documents'] is None and unchanged['documents_revision']==revision
    upload(api,'refresh-proof.txt',b'Catalog change test source.')
    updated=client.get('/api/state',params={'documents_revision':revision}).json()
    assert updated['documents_revision']!=revision
    assert any(d['filename']=='refresh-proof.txt' for d in updated['documents'])


def test_database_page_applies_scope_and_filters_before_pagination(api):
    client,_,folder=api
    docs=[upload(api,name,name.encode()) for name in ('one.txt','two.txt','three.txt')]
    assert client.post('/api/documents/'+docs[1]['id']+'/reading-state',json={'favorite':True,'opened':True}).status_code==200
    scoped=client.post('/api/library-page',json={'folder_id':folder,'favorites':True,'recent':True,'name':'two','limit':1}).json()
    assert scoped['total']==1 and scoped['documents'][0]['id']==docs[1]['id']
    response=client.post('/api/library-page',json={'folder_id':folder,'extension':'txt','sort':'added_old','limit':2,'offset':1})
    assert response.status_code==200,response.text
    data=response.json();assert data['total']==3 and len(data['documents'])==2
    assert [d['filename'] for d in data['documents']]==['two.txt','three.txt']
    assert client.post('/api/library-page',json={'limit':101}).status_code==400
    for name in ('Lecture 10.txt','Lecture 2.txt','alpha.txt'):upload(api,name,name.encode())
    listing=client.post('/api/library-page',json={'folder_id':folder,'sort':'name','limit':2}).json()
    assert [d['filename'] for d in listing['documents']]==['alpha.txt','Lecture 2.txt']
    assert listing['letters'][:2]==[{'letter':'A','offset':0},{'letter':'L','offset':1}] and listing['types']==['txt']
    named=client.post('/api/library-page',json={'folder_id':folder,'sort':'name','name':'lecture 1','limit':10}).json()
    assert named['total']==1 and named['documents'][0]['filename']=='Lecture 10.txt'
    candidates=client.post('/api/filename-candidates',json={'folder_id':folder,'query':'lectur 2'}).json()
    assert 'Lecture 2.txt' in {d['filename'] for d in candidates['documents']}
    without=client.get('/api/state',params={'include_documents':'false'}).json()
    assert without['documents'] is None and without['documents_revision']=='' and 'name' in without['library_page']['filters']


def test_folder_prefix_never_silently_broadens_or_overrides_scope(api):
    client,_,folder=api
    other=client.post('/api/folders',json={'name':'Invoices 2025'}).json()['id']
    client.post('/api/folders',json={'name':'Invoices 2026'})
    for query in ('folder:missing terms','folder:Invoices terms'):
        assert client.post('/api/search',json={'query':query}).status_code==400
    response=client.post('/api/search',json={'query':'folder:"Invoices 2025" terms','folder_id':folder})
    assert response.status_code==400 and other!=folder


def test_invoice_field_result_prefers_page_and_passage_containing_identifier(api):
    import pymupdf
    from knowledge_library import bills
    client,desktop,folder=api
    with pymupdf.open() as pdf:
        pdf.new_page().insert_text((50,60),'Cover page, no invoice identifier here.')
        pdf.new_page().insert_text((50,60),'Invoice No: B25\nTotal: 6600')
        data=pdf.tobytes()
    doc=upload(api,'two-page-invoice.pdf',data)
    with desktop.lib() as lib:
        bills.save(lib,doc['id'],{'invoice_number':'B25','source_page':1})
        result=bills.search(lib,'invoice B25',folder_id=folder,force=True,filters={'invoice_number':'B25'})
        assert result['results'][0]['page_number']==2
        assert 'B25' in result['results'][0]['passage']


def test_uploaded_modified_time_is_saved_for_matching_revision(api):
    client,desktop,folder=api
    r=client.post('/api/uploads',data={'folder_id':folder,'modified_times':'[1609459200000]'},files=[('files',('dated.txt',b'Original dated file.','text/plain'))])
    assert r.status_code==200,r.text
    task=wait(client,r.json()['task_ids'])[0];assert task['status']=='completed',task
    doc=next(d for d in client.get('/api/state').json()['documents'] if d['id']==task['result']['document']['id'])
    assert doc['modified_at'].startswith('2021-01-01T00:00:00')
    with desktop.lib() as lib,lib.db:lib.db.execute('UPDATE documents SET sha256=? WHERE id=?',('a'*64,doc['id']))
    changed=next(d for d in client.get('/api/state').json()['documents'] if d['id']==doc['id'])
    assert changed['modified_at'] is None


def test_direct_search_prioritizes_exact_filename_without_a_model(api):
    client,desktop,folder=api
    doc=upload(api,'Operating Systems Unit 3.txt',b'Unrelated content for filename match.')
    before=dict(desktop.model.stats)
    response=client.post('/api/search',json={'query':'operating systems unit 3','folder_id':folder})
    assert response.status_code==200,response.text
    result=response.json();assert result['mode']=='filename' and result['query_interpreter']=='not_needed'
    assert result['results'][0]['document_id']==doc['id'] and result['results'][0]['score_type']=='exact_filename'
    assert result['results'][0]['page_number'] is None and result['results'][0]['passage']==''
    assert desktop.model.stats==before


def test_library_filters_scope_filename_and_content_search(api):
    client,_,folder=api
    text=upload(api,'Shared title.txt',b'Quartz heliotrope alpha.')
    other=upload(api,'Shared title.md',b'Quartz heliotrope beta.')
    filters={'extension':'txt','status':'indexed'}
    lookup=client.post('/api/filename-matches',json={'query':'Shared title','folder_id':folder,'library_filters':filters})
    assert lookup.status_code==200 and [m['document_id'] for m in lookup.json()['matches']]==[text['id']]
    result=client.post('/api/search',json={'query':'Quartz heliotrope','folder_id':folder,'library_filters':filters,'content_only':True})
    assert result.status_code==200,result.text
    assert result.json()['results'] and all(hit['document_id']==text['id'] for hit in result.json()['results'])
    assert other['id']!=text['id']
    assert client.post('/api/filename-matches',json={'query':'Shared title','library_filters':{'unknown':True}}).status_code==400
