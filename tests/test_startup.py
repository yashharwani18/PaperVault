import json
from pathlib import Path
from types import SimpleNamespace
import threading

from knowledge_library.import_index import _install
from tests.test_desktop import session


def fake_package(tmp_path):
    root=tmp_path/'transformers';(root/'utils').mkdir(parents=True);(root/'models').mkdir()
    (root/'__init__.py').write_text('__version__ = "5.20.1"')
    (root/'utils/import_utils.py').write_text('# pinned import helper')
    record=tmp_path/'transformers-5.20.1.dist-info/RECORD';record.parent.mkdir();record.write_text('installed files v1')
    return root,record


def module(root,calls):
    def original(path,prefix=None):calls.append(str(path));return {frozenset({'torch'}):{'encoder':{'Encoder'}}}
    original.cache_clear=lambda:None
    return SimpleNamespace(__file__=str(root/'utils/import_utils.py'),define_import_structure=original)


def test_import_index_reused_and_invalidated(tmp_path):
    root,record=fake_package(tmp_path);path=tmp_path/'index.json';calls=[]
    first=module(root,calls);_install(first,path)
    expected=first.define_import_structure(root/'models');assert len(calls)==1
    second=module(root,calls);_install(second,path)
    assert second.define_import_structure(root/'models')==expected and len(calls)==1
    record.write_text('installed files v2')
    third=module(root,calls);_install(third,path)
    assert third.define_import_structure(root/'models')==expected and len(calls)==2
    path.write_text('{broken JSON')
    fourth=module(root,calls);_install(fourth,path)
    assert fourth.define_import_structure(root/'models')==expected and len(calls)==3
    path.write_text('[]')
    fifth=module(root,calls);_install(fifth,path)
    assert fifth.define_import_structure(root/'models')==expected and len(calls)==4


def test_background_preparation_does_not_block_api_worker(session,monkeypatch):
    client,desktop=session;entered=threading.Event();release=threading.Event();calls=[]
    def prepare(text):
        calls.append(text);entered.set();assert release.wait(5)
        desktop.model._model=object()
    monkeypatch.setattr(desktop.model,'query',prepare)
    try:
        first=client.post('/api/models/warmup');assert first.status_code==200
        assert entered.wait(2)
        future=desktop.warmup_future
        assert client.post('/api/models/warmup').status_code==200 and desktop.warmup_future is future
        assert client.get('/api/state').json()['semantic_status']['state']=='loading'
        # A mutation on the normal worker completes while model preparation waits.
        assert client.post('/api/folders',json={'name':'Available during startup'}).status_code==200
        assert not future.done()
    finally:release.set()
    future.result(timeout=3)
    assert client.get('/api/state').json()['semantic_status']['state']=='ready' and len(calls)==1
