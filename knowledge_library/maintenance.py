"""Recoverable document deletion and portable, hash-verified committed backups."""
import base64
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import uuid
import zipfile
from contextlib import closing

from .library import Library, now
from .text_documents import TEXT_EXTENSIONS, SPREADSHEET_EXTENSIONS

MANAGED_EXTENSIONS = TEXT_EXTENSIONS | SPREADSHEET_EXTENSIONS | {".pdf"}

def managed_files(lib):
    return [p for p in (lib.root/"files").iterdir() if p.is_file() and p.suffix.lower() in MANAGED_EXTENSIONS]


def initialize(lib):
    from .workspace_features import initialize as workspace_initialize
    workspace_initialize(lib)
    lib.db.execute('CREATE TABLE IF NOT EXISTS trash(id TEXT PRIMARY KEY,filename TEXT NOT NULL,deleted_at TEXT NOT NULL,payload TEXT NOT NULL)')
    lib.db.execute('CREATE TABLE IF NOT EXISTS feedback(id TEXT PRIMARY KEY,created_at TEXT NOT NULL,query TEXT NOT NULL,kind TEXT NOT NULL,note TEXT NOT NULL)')
    lib.db.commit()


def trash_list(lib):
    return [dict(r) for r in lib.db.execute('SELECT id,filename,deleted_at FROM trash ORDER BY deleted_at DESC')]


def trash_document(lib,document_id):
    doc=lib.document(document_id)
    chunks=[dict(r) for r in lib.db.execute('SELECT * FROM chunks WHERE document_id=?',(document_id,))]
    for chunk in chunks:chunk['vector']=base64.b64encode(chunk['vector']).decode('ascii')
    from .bills import get
    original=lib.db.execute('SELECT * FROM document_sources WHERE document_id=?',(document_id,)).fetchone()
    payload=dict(document=doc,pages=[dict(r) for r in lib.db.execute('SELECT * FROM pages WHERE document_id=?',(document_id,))],chunks=chunks,bill=get(lib,document_id),original=dict(original) if original else None)
    payload['bill_history']=[dict(r) for r in lib.db.execute('SELECT * FROM bill_history WHERE document_id=?',(document_id,))]
    key=uuid.uuid4().hex
    with lib.db:
        lib.db.execute('INSERT INTO trash VALUES(?,?,?,?)',(key,doc['filename'],now(),json.dumps(payload)))
        lib.db.execute('DELETE FROM documents WHERE id=?',(document_id,))
        lib.db.execute('UPDATE folders SET updated_at=? WHERE id=?',(now(),doc['folder_id']))
    return dict(removed_document=document_id,trash_id=key,recoverable=True)


def restore_document(lib,key,folder_id=None):
    row=lib.db.execute('SELECT payload FROM trash WHERE id=?',(key,)).fetchone()
    if not row:raise ValueError('Deleted document not found')
    payload=json.loads(row[0]);doc=payload['document']
    columns={r[1] for r in lib.db.execute('PRAGMA table_info(documents)')}
    doc={key:value for key,value in doc.items() if key in columns}
    if folder_id:doc['folder_id']=folder_id
    try:lib._folder(doc['folder_id'])
    except ValueError:raise ValueError('The original folder was deleted. Choose a destination folder.')
    source=lib.source_path(doc,verify=True)
    if payload.get('original'):
        original=payload['original'];deck=(lib.root/original['source_path']).resolve()
        if deck.parent!=(lib.root/'originals').resolve() or not deck.is_file() or hashlib.sha256(deck.read_bytes()).hexdigest()!=original['source_sha256']:raise ValueError('Retained original PowerPoint is missing or changed')
    def insert(table,fields):
        columns=list(fields);lib.db.execute(f'INSERT INTO {table}('+','.join(columns)+') VALUES('+','.join('?' for _ in columns)+')',list(fields.values()))
    with lib.db:
        doc['version']+=1;doc['updated_at']=now();insert('documents',doc)
        for page in payload['pages']:insert('pages',page)
        for chunk in payload['chunks']:
            chunk.pop('id');chunk['vector']=base64.b64decode(chunk['vector']);insert('chunks',chunk)
        if payload['bill']:
            from .bills import save
            bill=payload['bill']
            # save() commits; perform the bill insertion directly for atomic restore.
            bill=dict(bill);bill['evidence']=json.dumps(bill['evidence']);insert('bill_records',bill)
        if payload.get('original'):insert('document_sources',payload['original'])
        for correction in payload.get('bill_history',[]):insert('bill_history',correction)
        from .workspace_features import assign_subjects
        assign_subjects(lib,doc['id'],commit=False)
        lib.db.execute('DELETE FROM trash WHERE id=?',(key,))
        lib.db.execute('UPDATE folders SET updated_at=? WHERE id=?',(now(),doc['folder_id']))
    return lib.document(doc['id'])


def referenced_files(lib):
    paths={d['managed_path'] for d in lib.documents() if d.get('source_mode')!='reference'}
    paths.update(r[0] for r in lib.db.execute('SELECT source_path FROM document_sources'))
    for row in lib.db.execute('SELECT payload FROM trash'):
        payload=json.loads(row[0])
        if payload['document'].get('source_mode')!='reference':paths.add(payload['document']['managed_path'])
        if payload.get('original'):paths.add(payload['original']['source_path'])
    return paths


def storage(lib):
    referenced=referenced_files(lib)
    orphan=[p for p in managed_files(lib) if str(p.relative_to(lib.root)) not in referenced]
    return dict(**lib.stats(),free_bytes=shutil.disk_usage(lib.root).free,trash_documents=len(trash_list(lib)),
                orphan_files=len(orphan),reclaimable_bytes=sum(p.stat().st_size for p in orphan),
                upload_bytes=sum(p.stat().st_size for p in (lib.root/'uploads').rglob('*') if p.is_file()) if (lib.root/'uploads').exists() else 0)


def cleanup(lib):
    # Never touch external originals, live PDFs, retained trash, uploads used by
    # refresh/retry, or directories. Deleting only unreferenced managed PDFs.
    referenced=referenced_files(lib);count=total=0
    for path in managed_files(lib):
        if path.is_symlink():continue
        if str(path.relative_to(lib.root)) not in referenced:
            total+=path.stat().st_size;path.unlink();count+=1
    return dict(removed_files=count,reclaimed_bytes=total)


def backup(lib):
    directory=lib.root/'backups';directory.mkdir(exist_ok=True)
    key=uuid.uuid4().hex;database=directory/f'{key}.sqlite3';target=directory/f'library-{key}.zip';temporary=target.with_suffix('.partial')
    try:
        with closing(sqlite3.connect(database)) as dest:
            with dest:lib.db.backup(dest)
        files=[('library.sqlite3',database)]
        for relative in sorted(referenced_files(lib)):
            source=(lib.root/relative).resolve()
            if source.parent not in ((lib.root/'files').resolve(),(lib.root/'originals').resolve()) or not source.is_file():raise ValueError('A retained source is missing; backup aborted')
            files.append((source.parent.name+'/'+source.name,source))
        required=sum(p.stat().st_size for _,p in files)
        if shutil.disk_usage(directory).free<required+32*1024*1024:raise OSError('Insufficient free space for a complete backup')
        manifest={name:hashlib.sha256(p.read_bytes()).hexdigest() for name,p in files}
        with zipfile.ZipFile(temporary,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=1) as archive:
            archive.writestr('manifest.json',json.dumps(dict(format='local-library-backup-v1',created_at=now(),files=manifest)))
            for name,path in files:archive.write(path,name)
        temporary.replace(target)
        return target
    finally:
        database.unlink(missing_ok=True);temporary.unlink(missing_ok=True)


def schema(lib):
    return {r['name']:r['sql'] for r in lib.db.execute("SELECT name,sql FROM sqlite_master WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%'")}


def restore_backup(archive_path,destination,embedder=None,*,trusted_schema):
    """Restore to a new directory only; never overwrite the running library."""
    destination=Path(destination).resolve()
    if destination.exists():raise ValueError('Restore destination must be a new directory')
    with zipfile.ZipFile(archive_path) as archive:
        infos=archive.infolist();names=[i.filename for i in infos]
        if len(names)!=len(set(names)) or len(infos)>20000:raise ValueError('Duplicate or excessive backup entries')
        if sum(i.file_size for i in infos)>10*1024**3:raise ValueError('Backup exceeds the 10 GiB restored-size limit')
        if any(i.file_size>1024**3 for i in infos):raise ValueError('Backup entry is too large')
        if 'manifest.json' not in names or archive.getinfo('manifest.json').file_size>4*1024**2:raise ValueError('Missing or excessive backup manifest')
        manifest=json.loads(archive.read('manifest.json'))
        if manifest.get('format')!='local-library-backup-v1':raise ValueError('Unsupported backup format')
        expected=manifest['files']
        if set(names)!=set(expected)|{'manifest.json'} or 'library.sqlite3' not in expected:raise ValueError('Backup contents do not match manifest')
        for name in expected:
            if name!='library.sqlite3' and not (len(name.split('/'))==2 and '\\' not in name and ':' not in name and not any(ord(c)<32 for c in name) and '..' not in name and ((name.startswith('files/') and Path(name).suffix.lower() in MANAGED_EXTENSIONS) or (name.startswith('originals/') and name.endswith(('.ppt','.pptx'))))):raise ValueError('Invalid backup path')
        if shutil.disk_usage(destination.parent).free<sum(i.file_size for i in infos)+32*1024**2:raise OSError('Insufficient storage for restore')
        # Validate every entry before writing. No archive-controlled extraction paths.
        for name,checksum in expected.items():
            digest=hashlib.sha256()
            with archive.open(name) as stream:
                while block:=stream.read(1024**2):digest.update(block)
            if digest.hexdigest()!=checksum:raise ValueError('Backup checksum mismatch')
        destination.mkdir()
        (destination/'files').mkdir()
        (destination/'originals').mkdir()
        for name in expected:
            with archive.open(name) as src,(destination/name).open('xb') as dst:shutil.copyfileobj(src,dst)
    # Refuse SQL with untrusted schema triggers before opening it as a library.
    with closing(sqlite3.connect(destination/'library.sqlite3')) as db:
        db.execute('PRAGMA trusted_schema=OFF')
        definitions={r[0]:r[1] for r in db.execute("SELECT name,sql FROM sqlite_master WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%'")}
        # The previous pages schema is an explicitly known safe predecessor.
        # Compare SQL before enabling the normal additive migration; never accept
        # arbitrary archive triggers or a merely similar column list.
        old_pages=trusted_schema.get('pages','').replace(", evidence TEXT NOT NULL DEFAULT '{}'",'')
        if definitions.get('pages')==old_pages:definitions['pages']=trusted_schema['pages']
        optional_workspace={'linked_folders','linked_members','bill_history','workspace_settings','chunks_input_lookup',
            'watched_sources','watched_files','watched_files_task',
            'documents_browse_updated','documents_browse_added','documents_browse_size','documents_browse_folder_added'}
        if (any(name not in trusted_schema or sql!=trusted_schema[name] for name,sql in definitions.items())
                or not (set(trusted_schema)-set(definitions))<=optional_workspace):
            raise ValueError('Backup database schema differs from this app version; restore with the matching app version')
        if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('Backup database integrity failed')
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='app_tasks'").fetchone():db.execute('DELETE FROM app_tasks')
        if 'watched_sources' in definitions:
            # Backups are portable: external folder access must be resumed deliberately.
            db.execute("UPDATE watched_sources SET enabled=0,state='waiting',error=NULL")
            db.execute("UPDATE watched_files SET task_id=NULL,state=CASE WHEN indexed_signature=signature THEN 'indexed' ELSE 'discovered' END")
        reference_column='source_mode' in {r[1] for r in db.execute('PRAGMA table_info(documents)')}
        db.execute('UPDATE documents SET original_path=? || managed_path'+(" WHERE source_mode!='reference'" if reference_column else ''),(str(destination)+'/',))
        for key,payload in db.execute('SELECT id,payload FROM trash').fetchall():
            record=json.loads(payload)
            if record['document'].get('source_mode')!='reference':record['document']['original_path']=str(destination/record['document']['managed_path'])
            db.execute('UPDATE trash SET payload=? WHERE id=?',(json.dumps(record),key))
        db.commit()
    with Library(destination,embedder) as restored:
        initialize(restored)
        report=restored.verify(include_external_sources=False)
        if not report['passed']:raise ValueError('Restored source/vector integrity failed')
        return dict(path=str(destination),documents=restored.stats()['documents'],integrity=report,
                    note='Restored into a separate library. Stop the app and launch this directory to use it. The current library was preserved.')
