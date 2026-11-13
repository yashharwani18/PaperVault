import json
from types import SimpleNamespace
from pathlib import Path
import pytest
from knowledge_library import release_info
from tests.test_organization import library


def test_release_identity_and_manual_update_policy():
    info=release_info.about()
    assert info['name']=='Khoj' and info['version']=='0.5.0' and info['display_version']=='v0.5'
    assert info['updates']['mode']=='manual' and info['updates']['automatic_checks'] is False
    assert 'Claude' in ' '.join(info['privacy'])


def test_diagnostics_exclude_contents_paths_queries_secrets_and_raw_errors(library):
    lib,docs,_,_=library
    sentinel='PRIVATE-DOCUMENT-CONTENT-DO-NOT-EXPORT'
    with lib.db:
        lib.db.execute('UPDATE documents SET title=?,filename=?,original_path=? WHERE id=?',(sentinel,sentinel+'.pdf','C:/Users/Private/'+sentinel,docs[0]['id']))
        lib.db.execute('UPDATE pages SET text=?',(sentinel,))
        lib.db.execute('INSERT OR REPLACE INTO workspace_settings VALUES(?,?)',('cloud_api_key',sentinel))
        lib.db.execute('CREATE TABLE IF NOT EXISTS app_tasks(id TEXT PRIMARY KEY,status TEXT,error TEXT)')
        lib.db.execute('INSERT INTO app_tasks VALUES(?,?,?)',(sentinel,'failed','FileNotFoundError: '+sentinel))
    runtime=SimpleNamespace(model=SimpleNamespace(device='cpu'),assistant=SimpleNamespace(config={'provider':'claude','model':sentinel,'cloud_enabled':True}),warmup_status={'state':'error','error':sentinel})
    data=release_info.diagnostics(lib,runtime)
    encoded=json.dumps(data)
    for forbidden in [sentinel,str(lib.root),'original_path','filename','traceback','api_key','query']:
        assert forbidden not in encoded,forbidden
    assert data['library']['documents']==2
    assert data['tasks']['failed']==1 and data['errors']['missing']==1
    assert data['runtime']['device']=='cpu' and data['runtime']['cloud_enabled'] is True
    assert data['schema']=='khoj-diagnostics-v1'


def test_diagnostic_download_is_explicit_and_authenticated(tmp_path):
    from fastapi.testclient import TestClient
    from knowledge_library.server import create_app
    app=create_app(tmp_path/'app','cpu')
    with TestClient(app) as client:
        assert client.get('/api/about').json()['name']=='Khoj'
        assert client.get('/api/diagnostics').status_code in (404,405)
        assert client.post('/api/diagnostics').status_code==403
        client.headers['X-Library-Token']=client.get('/api/state').json()['token']
        response=client.post('/api/diagnostics')
        assert response.status_code==200
        assert 'attachment' in response.headers['content-disposition']
        assert response.headers['cache-control']=='no-store'
        assert response.json()['product']['display_version']=='v0.5'
