"""Folder-import progress must include jobs older than the activity-list window."""
from tests.test_desktop import session
from knowledge_library.library import now


def test_specific_task_status_is_not_limited_to_latest_100(session):
    client,desktop=session
    with desktop.lib() as lib:
        folder=lib.create_folder('Folder progress regression')['id']
        with lib.db:
            for i in range(125):
                lib.db.execute('INSERT INTO app_tasks(id,folder_id,source,filename,ocr,is_bill,status,created_at) VALUES(?,?,?,?,?,?,?,?)',
                               (f'folder-status-{i:03d}',folder,'test-status-fixture',f'file-{i}.pdf',0,0,'completed',now()))
    assert len(client.get('/api/state').json()['tasks'])==100
    ids=[f'folder-status-{i:03d}' for i in range(125)]
    result=client.post('/api/tasks/status',json={'ids':ids})
    assert result.status_code==200 and {t['id'] for t in result.json()}==set(ids)
    assert all('source' not in t for t in result.json())
    assert client.post('/api/tasks/status',json={'ids':[]}).status_code==422
    assert client.post('/api/tasks/status',json={'ids':['x']*501}).status_code==422
    assert client.post('/api/tasks/status',json={'ids':['unknown-id']}).json()==[]
