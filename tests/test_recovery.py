import hashlib
import shutil
import uuid
from pathlib import Path
import pytest
from knowledge_library import recovery
from tests.test_organization import library


def test_missing_original_can_be_reconnected_without_copy_or_inference(library,tmp_path):
    lib,docs,_,_=library;doc=docs[0]
    before=lib.embedder.stats.copy()
    source=Path(doc['original_path']);moved=tmp_path/'moved.pdf';source.rename(moved)
    assert recovery.document_health(lib,doc['id'])['source']['code']=='missing'
    wrong=tmp_path/'wrong.pdf';shutil.copyfile(docs[1]['original_path'],wrong)
    with pytest.raises(ValueError,match='same PDF'):recovery.reconnect(lib,doc['id'],wrong)
    recovery.reconnect(lib,doc['id'],moved)
    assert lib.source_path(lib.document(doc['id']),verify=True)==moved.resolve()
    assert lib.document(doc['id'])['version']==doc['version']+1
    assert recovery.document_health(lib,doc['id'])['source']['code']=='available'
    assert lib.embedder.stats==before and not list((lib.root/'files').glob('*.pdf'))


def test_changed_original_is_not_opened_as_old_evidence(library):
    lib,docs,_,_=library;doc=docs[0]
    Path(doc['original_path']).write_bytes(b'changed file')
    health=recovery.document_health(lib,doc['id'])
    assert health['source']['code']=='changed'
    assert 'refresh' in health['source']['actions']


def test_retry_extraction_revisits_unchanged_incomplete_pdf(library,monkeypatch):
    lib,docs,_,_=library;doc=docs[0]
    with lib.db:lib.db.execute("UPDATE documents SET status='extraction_failed' WHERE id=?",(doc['id'],))
    calls=[];original=lib._build_stage
    def build(*args,**kwargs):calls.append(True);return original(*args,**kwargs)
    monkeypatch.setattr(lib,'_build_stage',build)
    result=lib.refresh(doc['id'])
    assert calls and result['document']['status']=='indexed'


@pytest.mark.parametrize('error,code',[
    ('FileNotFoundError: absent','missing'),('PermissionError: denied','permission'),
    ('RuntimeError: CUDA out of memory','memory'),('FileDataError: cannot open broken document','unreadable'),
    ('InterruptedError: shutdown','interrupted'),('Something unexpected','failed')])
def test_task_errors_have_plain_language_actions(error,code):
    issue=recovery.task_issue({'status':'failed','error':error})
    assert issue['code']==code and issue['message'] and issue['actions']


def test_restart_reuses_job_and_leaves_missing_sources_for_user(tmp_path,monkeypatch):
    from knowledge_library.server import Desktop
    desktop=Desktop(tmp_path/'app','cpu');seen=[]
    try:
        monkeypatch.setattr(desktop,'_index',lambda task:seen.append(task))
        source=tmp_path/'exists.pdf';source.write_bytes(b'test')
        with desktop.lib() as lib:
            folder=lib.create_folder('Recovery')['id']
            for key,path in [('exists',source),('missing',tmp_path/'absent.pdf')]:
                lib.db.execute("INSERT INTO app_tasks(id,folder_id,source,filename,ocr,status,created_at) VALUES(?,?,?,?,0,'interrupted','2026-10-24')",(key,folder,str(path),path.name))
            lib.db.commit()
            lib.db.execute("INSERT INTO app_tasks(id,folder_id,source,filename,ocr,status,created_at,source_id,relative_path) VALUES('watched',?,?,?,0,'interrupted','2026-10-24','connection','exists.pdf')",(folder,str(source),'exists.pdf'))
            lib.db.commit()
        recovery.resume_interrupted(desktop)
        desktop.futures['exists'].result(timeout=5)
        assert seen==['exists']
        assert recovery.retry_task(desktop,'exists')=='exists'
        assert seen==['exists']
        with desktop.lib() as lib:
            assert lib.db.execute('SELECT status FROM app_tasks WHERE id=?',('missing',)).fetchone()[0]=='interrupted'
        assert next(t for t in desktop.tasks() if t['id']=='missing')['recovery']['code']=='missing'
        with desktop.lib() as lib,lib.db:
            lib.db.execute("INSERT INTO app_tasks(id,folder_id,source,filename,ocr,status,created_at) VALUES('older',?,?,?,0,'failed','2026-10-24')",(folder,str(source),'exists.pdf'))
        assert recovery.retry_task(desktop,'older')=='exists'
        assert seen==['exists']
    finally:
        desktop.index_pool.shutdown();desktop.pool.shutdown();desktop.warmup_pool.shutdown();desktop.lease.close()


def test_recovery_api_reconnect_and_bounded_retry(tmp_path):
    import pymupdf
    from fastapi.testclient import TestClient
    from knowledge_library.server import create_app
    from tests.test_desktop import wait
    app=create_app(tmp_path/'desktop','cpu')
    with TestClient(app) as client:
        desktop=app.state.desktop
        client.headers['X-Library-Token']=client.get('/api/state').json()['token']
        folder=client.post('/api/folders',json={'name':'Originals'}).json()['id']
        source=tmp_path/'original.pdf'
        with pymupdf.open() as pdf:
            pdf.new_page().insert_text((40,60),'Recovery keeps original signal processing evidence.');pdf.save(source)
        key=desktop.queue(folder,source,source.name)
        job=wait(client,[key])[0];assert job['status']=='completed',job
        doc=job['result']['document'];moved=tmp_path/'moved.pdf';source.rename(moved)
        assert client.get('/api/documents/'+doc['id']+'/recovery').json()['source']['code']=='missing'
        token=client.headers.pop('X-Library-Token')
        assert client.post('/api/documents/'+doc['id']+'/reconnect',json={'path':str(moved)}).status_code==403
        client.headers['X-Library-Token']=token
        assert client.post('/api/documents/'+doc['id']+'/reconnect',json={'path':str(moved)}).status_code==200
        assert client.get('/api/documents/'+doc['id']+'/file').status_code==200
        broken=tmp_path/'broken.pdf';broken.write_bytes(b'not a pdf')
        failed=desktop.queue(folder,broken,broken.name)
        assert wait(client,[failed])[0]['status']=='failed'
        desktop.indexing_allowed.clear()
        try:
            first=client.post('/api/tasks/'+failed+'/retry').json()['task_id']
            assert client.post('/api/tasks/'+failed+'/retry').json()['task_id']==first==failed
        finally:desktop.indexing_allowed.set()
        assert wait(client,[failed])[0]['status']=='failed'
        with desktop.lib() as lib:
            assert lib.db.execute('SELECT count(*) FROM app_tasks WHERE source=?',(str(broken),)).fetchone()[0]==1


def test_watched_retry_retains_scan_ownership_after_failed_reconciliation(tmp_path,monkeypatch):
    from knowledge_library.server import Desktop
    desktop=Desktop(tmp_path/'app','cpu');seen=[]
    try:
        monkeypatch.setattr(desktop,'_index',lambda task:seen.append((task,task in desktop.discovery_tasks)))
        source=tmp_path/'exists.pdf';source.write_bytes(b'fixture')
        with desktop.lib() as lib,lib.db:
            folder=lib.create_folder('Connected')['id']
            lib.db.execute("INSERT INTO watched_sources(id,path,name,folder_id,created_at) VALUES('watch',?,'Watch',?,'2026-10-24')",(str(tmp_path),folder))
            lib.db.execute("INSERT INTO watched_files(source_id,relative_path,signature,queued_signature,task_id,state) VALUES('watch','exists.pdf','sig','sig','failed-watch','queued')")
            lib.db.execute("INSERT INTO app_tasks(id,folder_id,source,filename,ocr,status,created_at,source_id,relative_path,error) VALUES('failed-watch',?,?,?,0,'failed','2026-10-24','watch','exists.pdf','Read failed')",(folder,str(source),source.name))
        desktop.discovery.reconcile()
        with desktop.lib() as lib:assert lib.db.execute("SELECT task_id FROM watched_files").fetchone()[0] is None
        assert recovery.retry_task(desktop,'failed-watch')=='failed-watch'
        desktop.futures['failed-watch'].result(timeout=5)
        assert seen==[('failed-watch',True)]
        with desktop.lib() as lib:assert lib.db.execute("SELECT task_id,state FROM watched_files").fetchone()[:]==('failed-watch','queued')
    finally:
        desktop.index_pool.shutdown();desktop.pool.shutdown();desktop.warmup_pool.shutdown();desktop.lease.close()


def test_real_startup_recovers_durable_jobs_without_creating_new_attempts(tmp_path):
    from fastapi.testclient import TestClient
    from knowledge_library.server import Desktop,create_app
    from tests.test_desktop import wait
    root=tmp_path/'restart';desktop=Desktop(root,'cpu')
    broken=tmp_path/'broken.pdf';broken.write_bytes(b'not a pdf')
    try:
        with desktop.lib() as lib,lib.db:
            folder=lib.create_folder('Interrupted imports')['id']
            for key,source,status in [('restart-readable',broken,'running'),('restart-missing',tmp_path/'gone.pdf','queued')]:
                lib.db.execute('INSERT INTO app_tasks(id,folder_id,source,filename,ocr,status,created_at) VALUES(?,?,?,?,0,?,?)',(key,folder,str(source),source.name,status,'2026-10-24'))
    finally:
        desktop.index_pool.shutdown();desktop.pool.shutdown();desktop.warmup_pool.shutdown();desktop.lease.close()
    app=create_app(root,'cpu')
    with TestClient(app) as client:
        row=wait(client,['restart-readable'])[0]
        assert row['status']=='failed' and row['recovery']['code']=='unreadable'
        missing=next(t for t in client.get('/api/state').json()['tasks'] if t['id']=='restart-missing')
        assert missing['status']=='interrupted' and missing['recovery']['code']=='missing'
        with app.state.desktop.lib() as lib:assert lib.db.execute('SELECT count(*) FROM app_tasks').fetchone()[0]==2
