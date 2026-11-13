"""Local reading preferences, keyed by stable document identity and revision."""
import json
from .library import now

PREFIX='khoj.reading:'


def _interpret(doc,raw):
    try:old=json.loads(raw) if raw else {}
    except (TypeError,ValueError):old={}
    if not isinstance(old,dict):old={}
    same=old.get('sha256')==doc['sha256']
    page=old.get('page',1) if same else 1
    if type(page) is not int:page=1
    page=max(1,min(max(1,doc['page_count']),page))
    opened=old.get('last_opened','')
    if not isinstance(opened,str):opened=''
    return dict(favorite=bool(old.get('favorite')),page=page,last_opened=opened,sha256=doc['sha256'])


def read(lib,doc):
    row=lib.db.execute('SELECT value FROM workspace_settings WHERE key=?',(PREFIX+doc['id'],)).fetchone()
    return _interpret(doc,row[0] if row else None)


def update(lib,document_id,body):
    doc=lib.document(document_id)
    if 'sha256' in body and body['sha256']!=doc['sha256']:raise ValueError('This file changed. Open its latest version.')
    value=read(lib,doc)
    if 'favorite' in body:
        if type(body['favorite']) is not bool:raise ValueError('Choose whether to star this file.')
        value['favorite']=body['favorite']
    if 'page' in body:
        page=body['page']
        if type(page) is not int or not 1<=page<=max(1,doc['page_count']):raise ValueError('This page is outside the document.')
        value['page']=page
    if body.get('opened') is True:value['last_opened']=now()
    with lib.db:lib.db.execute('INSERT OR REPLACE INTO workspace_settings(key,value) VALUES(?,?)',(PREFIX+document_id,json.dumps(value)))
    return value


def state(lib):
    rows=lib.db.execute("SELECT d.id,d.sha256,d.page_count,s.value FROM workspace_settings s JOIN documents d ON s.key=?||d.id WHERE s.key LIKE ?",(PREFIX,PREFIX+'%'))
    documents={r['id']:_interpret(r,r['value']) for r in rows}
    recent=sorted((key for key in documents if documents[key]['last_opened']),key=lambda key:documents[key]['last_opened'],reverse=True)
    return dict(documents=documents,recent_ids=recent)
