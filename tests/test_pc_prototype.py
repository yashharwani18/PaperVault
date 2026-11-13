"""Connected-folder lifecycle with the real encoder; provider boundaries without paid calls."""
import json
from pathlib import Path
import time

import pymupdf
import pytest

from tests.test_desktop import session


def pdf(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    with pymupdf.open() as doc:
        doc.new_page().insert_text((40, 70), text)
        doc.save(path)


def until(client, check, timeout=150):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        data = client.get('/api/connections').json()['sources']
        if check(data):
            return data
        time.sleep(.2)
    raise AssertionError(client.get('/api/connections').json())


@pytest.mark.parametrize('stage', ['directory_check', 'walk_error'])
def test_protected_directory_is_skipped_and_timer_finishes(session, tmp_path, monkeypatch, stage):
    from knowledge_library import discovery
    client, desktop = session
    root = tmp_path / stage
    pdf(root / 'DSP.pdf', 'Digital signal processing studies discrete time signals and filters.')
    (root / 'Protected').mkdir()
    real_linked, real_walk = discovery.linked, discovery.os.walk
    def denied_link(path):
        if path == root / 'Protected':
            raise PermissionError(13, 'Access is denied', str(path))
        return real_linked(path)
    def denied_walk(top, **kwargs):
        if Path(top) == root:
            kwargs['onerror'](PermissionError(13, 'Access is denied', str(root / 'Protected')))
        yield from real_walk(top, **kwargs)
    if stage == 'directory_check':
        monkeypatch.setattr(discovery, 'linked', denied_link)
    else:
        monkeypatch.setattr(discovery.os, 'walk', denied_walk)
    response = client.post('/api/connections', json={'path': str(root)})
    assert response.status_code == 200, response.text
    key = response.json()['id']
    rows = until(client, lambda rows: any(r['id'] == key and r['counts'].get('indexed') == 1 and (r['timing'] or {}).get('finished_at') for r in rows))
    row = next(r for r in rows if r['id'] == key)
    assert row['state'] == 'watching' and row['error'] is None
    assert row['timing']['skipped_count'] >= 1
    assert row['timing']['started_at'] <= row['timing']['discovery_finished_at'] <= row['timing']['finished_at']
    finished = row['timing']['finished_at']
    desktop.discovery.reconcile()
    updated = next(r for r in client.get('/api/connections').json()['sources'] if r['id'] == key)
    assert updated['timing']['finished_at'] == finished
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        folders = client.get('/api/state').json()['linked_folders']
        if any(g['name'] == 'DSP' and row['files'][0]['document_id'] in g['document_ids'] for g in folders):
            break
        time.sleep(.2)
    else:
        raise AssertionError('Indexed DSP PDF did not get an automatic subject folder')
    assert (root / 'DSP.pdf').exists()
    client.delete(f'/api/connections/{key}')


def test_connected_folder_lifecycle(session, tmp_path):
    client, desktop = session
    root = tmp_path / 'Documents'
    pdf(root / 'notes.pdf', 'Operating systems use semaphores to coordinate concurrent processes.')
    pdf(root / 'nested' / 'notes.PDF', 'The pumping lemma proves that certain formal languages are not regular.')
    (root / 'ignore.txt').write_text('Not a PDF')
    response = client.post('/api/connections', json={'path': str(root)})
    assert response.status_code == 200, response.text
    connection = response.json()
    key = connection['id']
    sources = until(client, lambda rows: rows and rows[0]['counts'].get('indexed') == 2)
    assert len(sources[0]['files']) == 2
    state = client.get('/api/state').json()
    docs = [d for d in state['documents'] if d['folder_id'] == connection['folder_id']]
    assert len(docs) == 2 and root.joinpath('notes.pdf').exists()
    before = desktop.model.stats['document_texts_encoded']
    desktop.discovery.scan(key)
    desktop.discovery.reconcile()
    desktop.discovery.queue_pending()
    assert desktop.model.stats['document_texts_encoded'] == before
    first = next(d for d in docs if d['filename'] == 'notes.pdf')
    pdf(root / 'replacement.pdf', 'Updated operating systems notes explain deadlock prevention and resource ordering.')
    (root / 'replacement.pdf').replace(root / 'notes.pdf')
    client.post(f'/api/connections/{key}/scan')
    def changed(rows):
        documents = client.get('/api/state').json()['documents']
        return any(d['id'] == first['id'] and d['version'] == 2 for d in documents) and rows[0]['counts'].get('indexed') == 2
    until(client, changed)
    assert client.get(f"/api/documents/{first['id']}/file").status_code == 200
    # Discovery pause prevents new imports; resuming catches new files.
    assert client.patch(f'/api/connections/{key}', json={'enabled': False}).status_code == 200
    pdf(root / 'later.pdf', 'Binary search repeatedly halves the sorted search interval.')
    desktop.discovery.scan(key)
    assert len(client.get('/api/connections').json()['sources'][0]['files']) == 2
    client.patch(f'/api/connections/{key}', json={'enabled': True})
    until(client, lambda rows: rows[0]['counts'].get('indexed') == 3)
    # No-copy discovery retains indexed text, but needs the original to open PDF pages.
    (root / 'notes.pdf').unlink()
    desktop.discovery.scan(key)
    assert client.get('/api/connections').json()['sources'][0]['counts']['missing'] == 1
    assert client.get(f"/api/documents/{first['id']}/file").status_code == 404
    assert client.get(f"/api/documents/{first['id']}/pages/1").json()['text']
    # A deliberate library removal must not be silently undone by the watcher.
    docs = client.get('/api/state').json()['documents']
    later = next(d for d in docs if d['filename'] == 'later.pdf')
    assert client.delete(f"/api/documents/{later['id']}").status_code == 200
    desktop.discovery.reconcile()
    desktop.discovery.scan(key)
    desktop.discovery.queue_pending()
    assert client.get('/api/connections').json()['sources'][0]['counts']['excluded'] == 1
    count = client.get('/api/state').json()['stats']['documents']
    assert client.delete(f'/api/connections/{key}').status_code == 200
    assert client.get('/api/state').json()['stats']['documents'] == count
    assert (root / 'later.pdf').exists()


def test_duplicate_source_change_preserves_other_copy(session, tmp_path):
    client, desktop = session
    root = tmp_path / 'Duplicates'
    pdf(root / 'a.pdf', 'Original shared document about finite automata and regular expressions.')
    (root / 'b.pdf').write_bytes((root / 'a.pdf').read_bytes())
    response = client.post('/api/connections', json={'path': str(root)})
    key = response.json()['id']
    def indexed(rows):
        return any(s['id'] == key and s['counts'].get('indexed') == 2 for s in rows)
    rows = until(client, indexed)
    source = next(s for s in rows if s['id'] == key)
    old_ids = {f['document_id'] for f in source['files']}
    assert len(old_ids) == 1
    pdf(root / 'new.pdf', 'A different document about database transactions and serializable schedules.')
    (root / 'new.pdf').replace(root / 'a.pdf')
    client.post(f'/api/connections/{key}/scan')
    rows = until(client, lambda rows: any(s['id'] == key and s['counts'].get('indexed') == 2
        and len({f['document_id'] for f in s['files']}) == 2 for s in rows))
    source = next(s for s in rows if s['id'] == key)
    assert next(f for f in source['files'] if f['relative_path'] == 'b.pdf')['document_id'] in old_ids
    assert client.get(f'/api/documents/{next(iter(old_ids))}/file').content == (root / 'b.pdf').read_bytes()
    client.delete(f'/api/connections/{key}')


def test_connections_reject_overlap_and_require_token(session, tmp_path):
    client, desktop = session
    root = tmp_path / 'Empty'
    root.mkdir()
    assert client.post('/api/connections', json={'path': 'relative/folder'}).status_code == 400
    assert client.post('/api/connections', json={'path': str(desktop.root)}).status_code == 400
    key = client.post('/api/connections', json={'path': str(root)}).json()['id']
    assert client.post('/api/connections', json={'path': str(root)}).status_code == 400
    token = client.headers.pop('X-Library-Token')
    assert client.post('/api/connections/pick').status_code == 403
    client.headers['X-Library-Token'] = token
    client.delete(f'/api/connections/{key}')


def test_nested_connection_owns_child_subtree(session, tmp_path):
    client, desktop = session
    root = tmp_path / 'Nested'
    (root / 'child').mkdir(parents=True)
    (root / 'top.txt').write_text('Top level note', encoding='utf-8')
    (root / 'child' / 'note.json').write_text(json.dumps([{'text': 'JSON child note'}]), encoding='utf-8')
    parent = client.post('/api/connections', json={'path': str(root)}).json()
    response = client.post('/api/connections', json={'path': str(root / 'child')})
    assert response.status_code == 200, response.text
    child = response.json()
    desktop.discovery.scan(parent['id'])
    desktop.discovery.scan(child['id'])
    with desktop.lib() as lib:
        parent_paths = {r[0] for r in lib.db.execute('SELECT relative_path FROM watched_files WHERE source_id=?', (parent['id'],))}
        child_paths = {r[0] for r in lib.db.execute('SELECT relative_path FROM watched_files WHERE source_id=?', (child['id'],))}
        options = json.loads(lib.db.execute('SELECT value FROM workspace_settings WHERE key=?', ('source_options:' + parent['id'],)).fetchone()[0])
    assert parent_paths == {'top.txt'}
    assert child_paths == {'note.json'}
    assert str(root / 'child') in options['excluded_paths']
    client.delete(f"/api/connections/{child['id']}")
    client.delete(f"/api/connections/{parent['id']}")


def test_direct_path_retry_does_not_create_pdf_copy(session,tmp_path):
    client,desktop=session
    source=tmp_path/'retry.pdf'
    pdf(source,'Retry source stays in its original location without a managed PDF duplicate.')
    folder=client.post('/api/folders',json={'name':'Direct path retry'}).json()['id']
    task=desktop.queue(folder,source,source.name)
    desktop.futures[task].result(timeout=30)
    result=next(t for t in desktop.tasks([task]) if t['id']==task)
    assert result['status']=='completed',result
    doc=result['result']['document']
    assert doc['source_mode']=='reference'
    assert not (desktop.root/'files'/(doc['sha256']+'.pdf')).exists()
    assert client.get(f"/api/documents/{doc['id']}/file").content==source.read_bytes()


def test_optional_assistant_validates_sources_and_keeps_keys_session_only(session, monkeypatch):
    from knowledge_library import assistant as module
    client, desktop = session
    documents = client.get('/api/state').json()['documents']
    doc = next(d for d in documents if d['chunk_count'])
    with desktop.lib() as lib:
        chunk = lib.db.execute('SELECT * FROM chunks WHERE document_id=? LIMIT 1', (doc['id'],)).fetchone()
        key = str(chunk['id'])
        identity = f"{doc['id']}:{doc['sha256']}:{doc['version']}:{chunk['chunk_index']}:{chunk['page_number']}"
    body = dict(query='Explain the source', chunk_ids=[int(key)], sources={key: identity})
    calls = []
    def request(url, **kwargs):
        calls.append((url, kwargs))
        return {'message': {'content': 'This excerpt discusses the topic [1].'}}
    monkeypatch.setattr(module, 'request_json', request)
    assert client.put('/api/assistant/settings', json={'provider': 'claude', 'model': 'test-model'}).status_code == 400
    assert client.put('/api/assistant/settings', json={'provider': 'ollama', 'model': 'test-local'}).status_code == 200
    bad = {**body, 'sources': {key: 'stale'}}
    assert client.post('/api/assistant/ask', json=bad).status_code == 400
    assert not calls
    response = client.post('/api/assistant/ask', json=body)
    assert response.status_code == 200, response.text
    assert response.json()['cloud_used'] is False
    assert calls[0][0] == module.OLLAMA + '/chat'
    assert calls[0][1]['body']['stream'] is False
    assert response.json()['sources'][0]['document_id'] == doc['id']
    client.put('/api/assistant/settings', json={'provider': 'claude', 'model': 'test-cloud',
        'cloud_enabled': True, 'api_key': 'session-secret'})
    assert 'session-secret' not in client.get('/api/state').text
    with desktop.lib() as lib:
        saved = lib.db.execute("SELECT value FROM workspace_settings WHERE key='assistant'").fetchone()[0]
    assert 'session-secret' not in saved
    assert module.Assistant(desktop).key == ''
    assert not module.permitted_cloud_dns('api.anthropic.com')
    assert not module.permitted_cloud_address(('1.1.1.1', 443))
    client.put('/api/assistant/settings', json={'provider': 'builtin', 'api_key': ''})


def test_restored_connections_start_paused(session, tmp_path):
    from knowledge_library.library import Library
    from knowledge_library.maintenance import backup, restore_backup, schema
    client, desktop = session
    root = tmp_path / 'Portable'
    root.mkdir()
    key = client.post('/api/connections', json={'path': str(root)}).json()['id']
    with desktop.lib() as lib:
        result = restore_backup(backup(lib), tmp_path / 'restored', desktop.model, trusted_schema=schema(lib))
    with Library(result['path'], desktop.model) as restored:
        assert restored.db.execute('SELECT enabled FROM watched_sources WHERE id=?', (key,)).fetchone()[0] == 0
    client.delete(f'/api/connections/{key}')


def test_restart_discovers_new_files_without_upload(session, tmp_path):
    from fastapi.testclient import TestClient
    from knowledge_library.server import create_app
    from knowledge_library.library import Library
    _, existing = session
    root = tmp_path / 'Restart source'
    root.mkdir()
    library = tmp_path / 'restart-library'
    app = create_app(library)
    with TestClient(app) as client:
        client.headers['X-Library-Token'] = client.get('/api/state').json()['token']
        key = client.post('/api/connections', json={'path': str(root)}).json()['id']
        until(client, lambda rows: rows and rows[0]['state'] == 'watching')
    pdf(root / 'new.pdf', 'New documents are discovered automatically when the library starts again.')
    # Use the already loaded real encoder to avoid another model allocation.
    app = create_app(library)
    app.state.desktop.model = existing.model
    with TestClient(app) as client:
        client.headers['X-Library-Token'] = client.get('/api/state').json()['token']
        until(client, lambda rows: rows and rows[0]['counts'].get('indexed') == 1)
        assert client.get('/api/state').json()['stats']['documents'] == 1
        client.patch(f'/api/connections/{key}', json={'enabled': False})
        # The fixture's model stays owned by its original Desktop.
        from knowledge_library.embedding import EmbeddingGemma
        app.state.desktop.model = EmbeddingGemma()


def test_claude_network_exception_is_scoped_and_host_bound():
    import subprocess
    import sys
    code = '''
import socket,sys
from unittest.mock import patch
from knowledge_library.server import offline_guard
from knowledge_library.assistant import cloud_request
offline_guard()
def blocked(event,*args):
    try: sys.audit(event,*args)
    except PermissionError: return
    raise AssertionError('External operation was unexpectedly allowed')
blocked('socket.getaddrinfo','example.com',443,0,0,0)
blocked('socket.connect',None,('203.0.113.9',443))
sys.audit('socket.connect',None,('127.0.0.1',11434))
with patch('socket.getaddrinfo',return_value=[(socket.AF_INET,socket.SOCK_STREAM,6,'',('203.0.113.9',443))]):
    with cloud_request():
        sys.audit('socket.getaddrinfo','api.anthropic.com',443,0,0,0)
        sys.audit('socket.connect',None,('203.0.113.9',443))
        blocked('socket.getaddrinfo','example.com',443,0,0,0)
        blocked('socket.connect',None,('203.0.113.9',80))
        blocked('socket.connect',None,('203.0.113.10',443))
blocked('socket.connect',None,('203.0.113.9',443))
print('scoped network checks passed')
'''
    result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr


def test_provider_http_transport_and_redirect_refusal():
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    import threading
    from knowledge_library.assistant import request_json
    received = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_GET(self):
            self.send_response(302)
            self.send_header('Location', 'https://example.com/')
            self.end_headers()
        def do_POST(self):
            received.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'message': {'content': 'A test provider answer [1].'}}).encode())
    with ThreadingHTTPServer(('127.0.0.1', 0), Handler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = f'http://127.0.0.1:{server.server_port}'
            assert request_json(base + '/chat', body={'model': 'test', 'stream': False})['message']['content']
            assert received == [{'model': 'test', 'stream': False}]
            with pytest.raises(ValueError, match='HTTP 302'):
                request_json(base + '/redirect')
        finally:
            server.shutdown()
            thread.join()


def test_computer_scan_requires_opt_in_and_honors_exclusions(session, tmp_path, monkeypatch):
    from knowledge_library import discovery_routes
    client, desktop = session
    root = tmp_path / 'Local drive'
    pdf(root / 'Documents' / 'study.pdf', 'Computer networks use packet switching to transfer information.')
    pdf(root / 'Private' / 'excluded.pdf', 'This explicitly excluded PDF must not be indexed.')
    pdf(root / 'AppData' / 'cache.pdf', 'Application cache PDF must not be included in the default computer scan.')
    monkeypatch.setattr(discovery_routes, 'fixed_drives', lambda: [str(root)])
    plan = client.get('/api/computer-scan').json()
    assert plan['drives'] == [str(root)]
    assert client.get('/api/connections').json()['sources'] == []
    assert client.post('/api/computer-scan', json={}).status_code == 400
    assert not client.get('/api/connections').json()['sources']
    result = client.post('/api/computer-scan', json={'confirm': True, 'excluded_paths': [str(root / 'Private')]})
    assert result.status_code == 200, result.text
    key = result.json()['sources'][0]['id']
    rows = until(client, lambda rows: rows and rows[0]['counts'].get('indexed') == 1)
    assert len(rows[0]['files']) == 1
    assert rows[0]['options']['interval_seconds'] == 3600
    assert client.get('/api/computer-scan').json()['choice'] == 'computer'
    assert client.post('/api/computer-scan', json={'confirm': True}).status_code == 400
    client.delete(f'/api/connections/{key}')
    assert client.post('/api/computer-scan/skip').status_code == 200
    assert client.get('/api/computer-scan').json()['choice'] == 'folders'
