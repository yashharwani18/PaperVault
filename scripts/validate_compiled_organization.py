"""Native-module acceptance against generated UI-test documents; no user data."""
import json
from pathlib import Path
import uuid
from fastapi.testclient import TestClient
from knowledge_library.server import create_app
from knowledge_library import organization

ROOT=Path(__file__).resolve().parents[1]


def main():
    assert Path(organization.__file__).suffix=='.pyd'
    app=create_app(ROOT/'.cache/organization-ui-library','cpu',preload=False)
    with TestClient(app) as client:
        state=client.get('/api/state').json();client.headers['X-Library-Token']=state['token']
        ids=[d['id'] for d in state['documents']];assert len(ids)==2
        suffix=uuid.uuid4().hex[:6]
        topic=client.post('/api/organization/topics',json={'name':'Compiled topic '+suffix}).json()
        assert client.post('/api/organization/topics/assign',json={'document_ids':ids,'topic_ids':[topic['id']]}).status_code==200
        folder=client.post('/api/folders',json={'name':'Compiled destination '+suffix}).json()
        response=client.post('/api/organization/move',json={'document_ids':ids,'folder_id':folder['id']});assert response.status_code==200,response.text
        undo=response.json()['undo_token'];assert client.post('/api/organization/moves/'+undo+'/undo').status_code==200
        assert client.patch('/api/organization/topics/'+topic['id'],json={'name':'Compiled renamed topic '+suffix}).status_code==200
        assert client.post('/api/linked-folders/rebuild').status_code==200
        assert client.get('/api/organization/documents/'+ids[0]).json()['topic_ids']==[topic['id']]
        removed=client.delete('/api/documents/'+ids[0]).json()
        response=client.post('/api/trash/'+removed['trash_id']+'/restore',json={});assert response.status_code==200,response.text
        assert client.get('/api/organization/documents/'+ids[0]).json()['topic_ids']==[topic['id']]
        assert client.put('/api/organization/documents/'+ids[0]+'/name',json={'name':'Compiled saved name'}).status_code==200
        doc=next(d for d in client.get('/api/state').json()['documents'] if d['id']==ids[0]);assert doc['display_title']=='Compiled saved name'
    report=dict(passed=True,native_module=str(organization.__file__),bulk_move_undo=True,
                topic_choices_survive_rebuild=True,trash_restore_topics=True,display_name=True)
    (ROOT/'results/compiled-organization-validation.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))


if __name__=='__main__':main()
