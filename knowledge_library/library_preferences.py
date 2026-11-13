"""Local library display and recent-search preferences."""
import json

KEY='khoj.library.preferences'
SORTS=frozenset(('name','name_desc','added_new','added_old','modified_new','modified_old','size_large','size_small','type','recent'))


def read(lib):
    row=lib.db.execute('SELECT value FROM workspace_settings WHERE key=?',(KEY,)).fetchone()
    try:value=json.loads(row[0]) if row else {}
    except (TypeError,ValueError):value={}
    if not isinstance(value,dict):value={}
    sort=value.get('sort','added_new')
    if not isinstance(sort,str) or sort not in SORTS:sort='added_new'
    history=value.get('search_history',[])
    if not isinstance(history,list):history=[]
    history=[q for q in history if isinstance(q,str) and 0<len(q.strip())<=4096][:20]
    return dict(sort=sort,search_history=history,saved=bool(row))


def update(lib,body):
    value=read(lib);value.pop('saved',None)
    if 'sort' in body:
        if not isinstance(body['sort'],str) or body['sort'] not in SORTS:raise ValueError('Choose a supported library sort order.')
        value['sort']=body['sort']
    if 'search_history' in body:
        history=body['search_history']
        if not isinstance(history,list) or len(history)>20 or any(not isinstance(q,str) or not q.strip() or len(q)>4096 for q in history):raise ValueError('Recent searches are invalid.')
        value['search_history']=history
    with lib.db:lib.db.execute('INSERT OR REPLACE INTO workspace_settings(key,value) VALUES(?,?)',(KEY,json.dumps(value,ensure_ascii=False)))
    return dict(**value,saved=True)
