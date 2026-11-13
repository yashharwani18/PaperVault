import time
import pymupdf
from tests.test_desktop import session,wait


def write_pdf(path,text):
    with pymupdf.open() as pdf:
        pdf.new_page().insert_text((40,60),text);pdf.save(path)


def test_organization_api_and_stale_queued_refresh_keep_user_choices(session,tmp_path):
    client,desktop=session
    first=client.post('/api/folders',json={'name':'Organization originals'}).json()['id']
    second=client.post('/api/folders',json={'name':'Organization destination'}).json()['id']
    path=tmp_path/'DSP-notes.pdf';write_pdf(path,'Digital signal processing uses convolution and filters.')
    job=desktop.queue(first,path,path.name)
    document=wait(client,[job])[0]['result']['document'];key=document['id']
    topic=client.post('/api/organization/topics',json={'name':'My exam revision'}).json()
    assert client.post('/api/organization/topics/assign',json={'document_ids':[key],'topic_ids':[topic['id']]}).status_code==200
    assert client.put(f'/api/organization/documents/{key}/name',json={'name':'Exam notes'}).status_code==200
    assert next(d for d in client.get('/api/state').json()['documents'] if d['id']==key)['display_title']=='Exam notes'
    move=client.post('/api/organization/move',json={'document_ids':[key],'folder_id':second})
    assert move.status_code==200,move.text
    assert client.post(f"/api/organization/moves/{move.json()['undo_token']}/undo").status_code==200
    assert client.post('/api/organization/move',json={'document_ids':[key],'folder_id':second}).status_code==200
    write_pdf(path,'Digital signal processing uses convolution and filters. Revised notes explain sampled signals.')
    # A task can retain the pre-move collection while waiting in the queue.
    job=desktop.queue(first,path,path.name,document_id=key)
    assert wait(client,[job])[0]['status']=='completed'
    state=client.get('/api/state').json();doc=next(d for d in state['documents'] if d['id']==key)
    assert doc['folder_id']==second and doc['display_title']=='Exam notes'
    info=client.get(f'/api/organization/documents/{key}').json()
    assert info['topic_ids']==[topic['id']] and info['manual_topics']
    assert client.post('/api/linked-folders/rebuild').status_code==200
    assert key in next(t for t in client.get('/api/state').json()['linked_folders'] if t['id']==topic['id'])['document_ids']
    assert client.post('/api/organization/topics/reset',json={'document_ids':[key]}).status_code==200
    assert not client.get(f'/api/organization/documents/{key}').json()['manual_topics']
    trash=client.delete(f'/api/documents/{key}').json()
    assert client.request('DELETE',f"/api/trash/{trash['trash_id']}",json={'confirmation':'DELETE PERMANENTLY'}).status_code==200
    with desktop.lib() as lib:
        assert not lib.db.execute('SELECT 1 FROM workspace_settings WHERE key IN (?,?)',('organization.document_name:'+key,'organization.topics:'+key)).fetchone()
