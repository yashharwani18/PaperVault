"""User-owned organization, separate from source files and embedding recipes."""
import hashlib
import json
import uuid
from contextlib import nullcontext
from .library import now


def _get(lib,key,default):
    row=lib.db.execute('SELECT value FROM workspace_settings WHERE key=?',(key,)).fetchone()
    return json.loads(row[0]) if row else default


def _put(lib,key,value):
    lib.db.execute('INSERT INTO workspace_settings VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(key,json.dumps(value)))


def topic_id(name):return 'linked-'+hashlib.sha256(name.encode()).hexdigest()[:20]


def topics(lib):
    from .workspace_features import SUBJECTS
    aliases=_get(lib,'organization.topic_names',{})
    try:
        existing = [dict(id=r['id'], name=r['name'], basis=r['basis'])
                    for r in lib.db.execute("SELECT id, name, basis FROM linked_folders WHERE basis LIKE 'Suggested subject%' ORDER BY name")]
    except Exception:
        existing = []
    seen = {t['id'] for t in existing}
    result = list(existing)
    for key, definition in _get(lib,'organization.remembered_topics',{}).items():
        if key not in seen:
            result.append(dict(id=key, name=definition['name'], basis='Personal topic'))
            seen.add(key)
    misc_id = topic_id('Miscellaneous')
    if misc_id not in seen:
        result.append(dict(id=misc_id, name='Miscellaneous', basis='Suggested subject fallback; no confident topic found'))
        seen.add(misc_id)
    for s in SUBJECTS:
        sid = topic_id(s[0])
        if sid not in seen:
            result.append(dict(id=sid, name=s[0], basis='Suggested subject from indexed title/text; review classification'))
            seen.add(sid)
    result.extend(dict(id=key,name=name,basis='Personal topic') for key,name in _get(lib,'organization.personal_topics',{}).items())
    for topic in result:topic['name']=aliases.get(topic['id'],topic['name'])
    return sorted(result,key=lambda t:(t['id']==misc_id,t['name'].casefold()))


def _unique_name(lib,name,except_id=None):
    name=lib._name(name)
    if any(t['id']!=except_id and t['name'].casefold()==name.casefold() for t in topics(lib)):
        raise ValueError('A topic with this name already exists. Choose it from the list.')
    return name


def _ensure_group(lib,topic):
    lib.db.execute('''INSERT INTO linked_folders VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE
        SET name=excluded.name,basis=excluded.basis,updated_at=excluded.updated_at''',
        (topic['id'],topic['name'],topic['basis'],now()))


def create_topic(lib,name):
    name=_unique_name(lib,name);key='personal-'+uuid.uuid4().hex
    with lib.db:
        definitions=_get(lib,'organization.personal_topics',{});definitions[key]=name
        _put(lib,'organization.personal_topics',definitions)
        topic=dict(id=key,name=name,basis='Personal topic');_ensure_group(lib,topic)
    return topic


def rename_topic(lib,key,name):
    topic=next((t for t in topics(lib) if t['id']==key),None)
    if topic is None:raise ValueError('Topic no longer exists. Refresh the library.')
    name=_unique_name(lib,name,key)
    with lib.db:
        remember_topics(lib, [key])
        aliases=_get(lib,'organization.topic_names',{});aliases[key]=name
        _put(lib,'organization.topic_names',aliases);topic['name']=name;_ensure_group(lib,topic)
    return topic


def decorate_groups(lib,groups):
    aliases=_get(lib,'organization.topic_names',{})
    return [{**g,'name':aliases.get(g['id'],g['name'])} for g in groups]


def apply_document_topics(lib,document_id):
    """Caller owns the transaction; overlay survives automatic reassignment."""
    keys=_get(lib,'organization.topics:'+document_id,None)
    if keys is None:return
    catalogue={t['id']:t for t in topics(lib)}
    keys=[key for key in keys if key in catalogue] or [topic_id('Miscellaneous')]
    lib.db.execute("DELETE FROM linked_members WHERE document_id=? AND folder_id IN (SELECT id FROM linked_folders WHERE basis LIKE 'Suggested subject%' OR basis='Personal topic')",(document_id,))
    for key in keys:
        _ensure_group(lib,catalogue[key])
        lib.db.execute('INSERT OR IGNORE INTO linked_members VALUES(?,?,?)',(key,document_id,'Your saved topic selection'))


def remember_topics(lib, keys=()):
    """Preserve automatic definitions explicitly selected or renamed by a user.

    Also captures pre-existing corrections made before this catalogue existed.
    Caller owns the transaction so rebuild publication stays atomic.
    """
    referenced = set(keys) | set(_get(lib, 'organization.topic_names', {}))
    for row in lib.db.execute("SELECT value FROM workspace_settings WHERE key LIKE 'organization.topics:%'"):
        referenced.update(json.loads(row[0]))
    saved = _get(lib, 'organization.remembered_topics', {})
    for row in lib.db.execute("SELECT id,name FROM linked_folders WHERE basis LIKE 'Suggested subject%'"):
        if row['id'] in referenced:
            saved[row['id']] = dict(name=row['name'])
    if saved:
        _put(lib, 'organization.remembered_topics', saved)


def reapply(lib, *, commit=True):
    with lib.db if commit else nullcontext():
        for topic in topics(lib):
            if topic['basis']=='Personal topic':_ensure_group(lib,topic)
        rows=lib.db.execute("SELECT d.id FROM documents d JOIN workspace_settings s ON s.key='organization.topics:'||d.id").fetchall()
        for row in rows:apply_document_topics(lib,row[0])


def _documents(lib,ids):
    ids=list(dict.fromkeys(ids))
    if not 1<=len(ids)<=2000:raise ValueError('Select between 1 and 2,000 documents.')
    return [lib.document(key) for key in ids]


def set_topics(lib,ids,keys):
    docs=_documents(lib,ids);keys=sorted(set(keys));known={t['id'] for t in topics(lib)}
    if len(keys)>100 or any(key not in known for key in keys):raise ValueError('A selected topic no longer exists. Refresh and try again.')
    keys=keys or [topic_id('Miscellaneous')]
    with lib.db:
        remember_topics(lib, keys)
        for doc in docs:
            _put(lib,'organization.topics:'+doc['id'],keys);apply_document_topics(lib,doc['id'])
    return dict(updated=len(docs))


def reset_topics(lib,ids):
    from .workspace_features import assign_subjects
    docs=_documents(lib,ids)
    with lib.db:
        for doc in docs:
            lib.db.execute('DELETE FROM workspace_settings WHERE key=?',('organization.topics:'+doc['id'],))
            assign_subjects(lib,doc['id'],commit=False)
    return dict(updated=len(docs))


def document_info(lib,key):
    doc=lib.document(key)
    ids=[r[0] for r in lib.db.execute("SELECT m.folder_id FROM linked_members m JOIN linked_folders f ON f.id=m.folder_id WHERE m.document_id=? AND (f.basis LIKE 'Suggested subject%' OR f.basis='Personal topic') ORDER BY m.folder_id",(key,))]
    return dict(topic_ids=ids,manual_topics=_get(lib,'organization.topics:'+key,None) is not None,
                display_title=_get(lib,'organization.document_name:'+key,''),filename=doc['filename'])


def rename_document(lib,key,name):
    lib.document(key)
    with lib.db:
        if name is None:lib.db.execute('DELETE FROM workspace_settings WHERE key=?',('organization.document_name:'+key,))
        else:_put(lib,'organization.document_name:'+key,lib._name(name))
    return document_info(lib,key)


def decorate_documents(lib,documents):
    prefix='organization.document_name:'
    names={r[0][len(prefix):]:json.loads(r[1]) for r in lib.db.execute('SELECT key,value FROM workspace_settings WHERE key LIKE ?',(prefix+'%',))}
    return [{**doc,'display_title':names.get(doc['id'],'')} for doc in documents]


def _validate_destinations(lib,docs,destinations):
    for doc in docs:
        target=destinations[doc['id']];lib._folder(target)
        if lib.db.execute('SELECT 1 FROM documents WHERE folder_id=? AND sha256=? AND id!=?',(target,doc['sha256'],doc['id'])).fetchone():
            raise ValueError(f'“{doc["filename"]}” already exists in the destination. No documents were moved.')
    seen=set()
    for doc in docs:
        identity=destinations[doc['id']],doc['sha256']
        if identity in seen:raise ValueError('Selected documents contain identical PDFs. Move them separately; no documents were moved.')
        seen.add(identity)


def _move(lib,docs,destinations):
    for doc in docs:
        target=destinations[doc['id']]
        lib.db.execute('UPDATE documents SET folder_id=?,updated_at=?,version=version+1 WHERE id=?',(target,now(),doc['id']))
        lib.db.execute('UPDATE folders SET updated_at=? WHERE id IN (?,?)',(now(),target,doc['folder_id']))


def move_documents(lib,ids,destination):
    with lib.db:
        lib.db.execute('BEGIN IMMEDIATE')
        docs=_documents(lib,ids);docs=[d for d in docs if d['folder_id']!=destination];lib._folder(destination)
        if not docs:return dict(updated=0,undo_token=None)
        destinations={d['id']:destination for d in docs};token=uuid.uuid4().hex
        _validate_destinations(lib,docs,destinations)
        _move(lib,docs,destinations)
        _put(lib,'organization.move:'+token,dict(created_at=now(),documents=[dict(id=d['id'],folder_id=d['folder_id'],version=d['version']+1) for d in docs]))
        history=lib.db.execute("SELECT key,value FROM workspace_settings WHERE key LIKE 'organization.move:%'").fetchall()
        for row in sorted(history,key=lambda r:json.loads(r[1])['created_at'],reverse=True)[20:]:lib.db.execute('DELETE FROM workspace_settings WHERE key=?',(row[0],))
    return dict(updated=len(docs),undo_token=token)


def undo_move(lib,token):
    with lib.db:
        lib.db.execute('BEGIN IMMEDIATE')
        record=_get(lib,'organization.move:'+token,None)
        if not record:raise ValueError('This move can no longer be undone.')
        docs=_documents(lib,[d['id'] for d in record['documents']])
        expected={d['id']:d for d in record['documents']}
        if any(d['version']!=expected[d['id']]['version'] for d in docs):raise ValueError('A document changed after this move. Move it manually to keep newer changes.')
        destinations={key:d['folder_id'] for key,d in expected.items()}
        _validate_destinations(lib,docs,destinations);_move(lib,docs,destinations)
        lib.db.execute('DELETE FROM workspace_settings WHERE key=?',('organization.move:'+token,))
    return dict(updated=len(docs))
