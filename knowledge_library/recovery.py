"""Bounded job recovery and verified reconnection of original documents."""
from pathlib import Path
import hashlib
import json
import os
import subprocess
import sys
from pydantic import BaseModel, Field
from .library import now
from .text_documents import TEXT_EXTENSIONS, SPREADSHEET_EXTENSIONS, source_info


def initialize(lib):
    columns={r[1] for r in lib.db.execute('PRAGMA table_info(app_tasks)')}
    if 'source_id' in columns:return
    with lib.db:
        lib.db.execute('ALTER TABLE app_tasks ADD COLUMN source_id TEXT')
        lib.db.execute('ALTER TABLE app_tasks ADD COLUMN relative_path TEXT')
        # One-time migration of old history whose watched task pointer was cleared.
        sources=[dict(r) for r in lib.db.execute('SELECT id,path FROM watched_sources')]
        for task in lib.db.execute('SELECT id,source FROM app_tasks').fetchall():
            for source in sources:
                try:relative=Path(task['source']).resolve().relative_to(Path(source['path']).resolve())
                except ValueError:continue
                lib.db.execute('UPDATE app_tasks SET source_id=?,relative_path=? WHERE id=?',(source['id'],str(relative),task['id']))
                break


def task_issue(task):
    error=(task.get('error') or '').lower()
    code='failed';message='Indexing could not finish. Your previously indexed documents are retained.'
    actions=['retry']
    if 'filenotfound' in error or 'source is still unavailable' in error:
        code='missing';message='The source file is unavailable. Reconnect its drive or restore it to its original location, then retry.'
        actions=['retry','replace']
    elif 'permission' in error or 'access is denied' in error:
        code='permission';message='Windows blocked access to this file. Check its permissions or close the program locking it, then retry.'
    elif 'out of memory' in error or 'memoryerror' in error:
        code='memory';message='There was not enough GPU or system memory. Close other memory-heavy apps, then retry. The saved index is retained.'
    elif task.get('status')=='interrupted' or 'interruptederror' in error:
        code='interrupted';message='The app stopped before this file finished. Retry safely; other indexed documents are retained.'
    elif any(term in error for term in ('filedataerror','emptyfileerror','encrypted','password','broken document','cannot open')):
        code='unreadable';message='This document could not be read. Open it in its document application and save a repaired or unlocked copy, then add it again.'
        actions=['retry','replace']
    return dict(code=code,message=message,actions=actions)


def document_health(lib,document_id):
    doc=lib.document(document_id)
    source=dict(code='available',message='The matching original document is available.',actions=['retry'])
    try:lib.source_path(doc,verify=True)
    except FileNotFoundError:
        source=dict(code='missing',message='The original document was moved, deleted, or its drive is disconnected. Indexed text remains searchable, but pages require the matching original.',actions=['retry','reconnect','replace'])
    except PermissionError:
        source=dict(code='permission',message='Windows denied access to the original. Check its permissions or close the program locking it, then check again.',actions=['retry'])
    except ValueError:
        source=dict(code='changed',message='This document has changed since indexing. Refresh its index before using the new pages as evidence.',actions=['refresh','reconnect'])
    except OSError:
        source=dict(code='unavailable',message='The original could not be read. Reconnect its drive and check again.',actions=['retry','reconnect'])
    native=source_info(doc)['preview_kind']=='text'
    if native:
        source['message']={
            'available':'The matching original document is available.',
            'missing':'The original document was moved, deleted, or its drive is disconnected. Indexed text remains searchable; reconnect the matching source to open it.',
            'changed':'This document has changed since indexing. Refresh its index before using the new text as evidence.'
        }.get(source['code'],source['message'])
    counts=dict(lib.db.execute('SELECT status,count(*) FROM pages WHERE document_id=? GROUP BY status',(document_id,)))
    extraction=None
    if doc['status'] in ('partial','needs_ocr','empty','extraction_failed'):
        extraction=dict(code=doc['status'],message=('Some pages contain images without searchable text. Read scanned pages with OCR.' if counts.get('needs_ocr') else 'Some pages could not be read completely. Retry extraction, or replace the PDF with a repaired copy.' if counts.get('extraction_failed') else 'No searchable text was found. This may be a blank or image-only PDF; try OCR for scanned pages.'),page_statuses=counts)
    if native and extraction:
        extraction['message']='No searchable text was found in this document.' if doc['status']=='empty' else 'Some document text could not be read completely. Retry extraction or replace it with a repaired copy.'
    return dict(document_id=document_id,source=source,extraction=extraction,original_path=doc['original_path'],can_reconnect=doc.get('source_mode')=='reference')


def reconnect(lib,document_id,path):
    path=Path(path).expanduser().resolve(strict=True)
    if not path.is_file():raise ValueError('Choose a source document file.')
    # Hash independently: never bind old evidence to a different document.
    with path.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
    with lib.db:
        lib.db.execute('BEGIN IMMEDIATE')
        doc=lib.document(document_id)
        if path.suffix.lower()!=Path(doc['filename']).suffix.lower():raise ValueError('Choose the same document format that was indexed.')
        if doc.get('source_mode')!='reference':raise ValueError('This document is stored by Library. Restore its backup or replace the document instead.')
        if lib.db.execute("SELECT 1 FROM sqlite_master WHERE name='app_tasks'").fetchone() and lib.db.execute("SELECT 1 FROM app_tasks WHERE document_id=? AND status IN ('queued','running','skipping')",(document_id,)).fetchone():raise ValueError('Wait for this document to finish indexing before reconnecting it.')
        if digest!=doc['sha256']:
            kind='PDF' if path.suffix.lower()=='.pdf' else 'document'
            raise ValueError(f'Choose the same {kind} that was indexed. This file has different contents; use Replace document to index a new version.')
        lib.db.execute('UPDATE documents SET original_path=?,managed_path=?,version=version+1,updated_at=? WHERE id=?',(str(path),str(path),now(),document_id))
    return dict(reconnected=True,document_id=document_id)


def retry_task(desktop,task_id):
    with desktop.lib() as lib:
        with lib.db:
            lib.db.execute('BEGIN IMMEDIATE')
            row=lib.db.execute('SELECT * FROM app_tasks WHERE id=?',(task_id,)).fetchone()
            if row is None:raise ValueError('Task not found')
            if row['status'] in ('queued','running','skipping'):return task_id
            if row['status'] not in ('failed','interrupted','skipped'):raise ValueError('Only a failed, interrupted or skipped task can be retried.')
            source=Path(row['source'])
            if row['document_id']:
                doc=lib.document(row['document_id'])
                original=lib.db.execute('SELECT source_path FROM document_sources WHERE document_id=?',(row['document_id'],)).fetchone()
                source=desktop.root/original[0] if original else Path(doc['original_path'])
            pending=lib.db.execute("SELECT id FROM app_tasks WHERE id!=? AND status IN ('queued','running','skipping') AND ((document_id IS NOT NULL AND document_id=?) OR (folder_id=? AND source=?)) LIMIT 1",(task_id,row['document_id'],row['folder_id'],str(source))).fetchone()
            if pending:
                lib.db.execute("UPDATE app_tasks SET status='recovered',error=NULL WHERE id=?",(task_id,))
                return pending[0]
            if row['source_id']:
                watched=lib.db.execute('SELECT f.*,s.path FROM watched_files f JOIN watched_sources s ON s.id=f.source_id WHERE f.source_id=? AND f.relative_path=?',(row['source_id'],row['relative_path'])).fetchone()
                if watched is None:raise ValueError('This folder connection no longer contains the file. Add the PDF again from its current location.')
                source=(Path(watched['path'])/watched['relative_path']).resolve()
                from .discovery import linked
                if not source.is_relative_to(Path(watched['path']).resolve()) or linked(source):raise ValueError('The source no longer points inside its connected folder.')
                if watched['task_id'] and watched['task_id']!=task_id:
                    active=lib.db.execute("SELECT id FROM app_tasks WHERE id=? AND status IN ('queued','running','skipping')",(watched['task_id'],)).fetchone()
                    if active:return active[0]
                lib.db.execute("UPDATE watched_files SET task_id=?,queued_signature=signature,state='queued',error=NULL WHERE source_id=? AND relative_path=?",(task_id,row['source_id'],row['relative_path']))
                desktop.discovery_tasks.add(task_id)
            if not source.is_file():raise ValueError('The source is still unavailable. Reconnect its drive or restore the file before retrying.')
            if lib.db.execute('SELECT 1 FROM watched_files WHERE task_id=?',(task_id,)).fetchone():desktop.discovery_tasks.add(task_id)
            lib.db.execute("UPDATE app_tasks SET source=?,status='queued',progress=NULL,finished_at=NULL,error=NULL,result=NULL WHERE id=?",(str(source),task_id))
        desktop.futures[task_id]=desktop.index_pool.submit(desktop._index,task_id)
    return task_id


def resume_interrupted(desktop):
    # Discovery already owns recovery of watched jobs; do not submit them twice.
    with desktop.lib() as lib:
        ids=[r[0] for r in lib.db.execute("SELECT id FROM app_tasks WHERE status='interrupted' AND source_id IS NULL AND id NOT IN (SELECT task_id FROM watched_files WHERE task_id IS NOT NULL)")]
    for task_id in ids:
        try:retry_task(desktop,task_id)
        except (OSError,ValueError) as exc:
            with desktop.lib() as lib,lib.db:
                lib.db.execute('UPDATE app_tasks SET error=? WHERE id=?',(f'{type(exc).__name__}: {exc}',task_id))


def pick_pdf():
    patterns=' '.join('*'+extension for extension in sorted(TEXT_EXTENSIONS | SPREADSHEET_EXTENSIONS | {'.pdf'}))
    code="""import json,tkinter as tk
from tkinter import filedialog
root=tk.Tk();root.withdraw();root.attributes('-topmost',True)
try:print(json.dumps({'path':filedialog.askopenfilename(title='Locate the original document',filetypes=[('Supported documents',__PATTERNS__)],parent=root) or None}))
finally:root.destroy()
"""
    code=code.replace("__PATTERNS__",repr(patterns))
    interpreter=Path(sys.executable).with_name('python.exe')
    result=subprocess.run([str(interpreter) if interpreter.is_file() else sys.executable,'-c',code],capture_output=True,text=True,timeout=120,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    if result.returncode:raise ValueError('The file picker could not open. Paste the full document path instead.')
    return json.loads(result.stdout)


class ReconnectBody(BaseModel):
    path:str=Field(min_length=1,max_length=4096)


def install(app,desktop):
    @app.get('/api/documents/{document_id}/recovery')
    async def health(document_id:str):return await desktop.work(lambda lib:document_health(lib,document_id))

    @app.post('/api/documents/{document_id}/reconnect')
    async def relink(document_id:str,body:ReconnectBody):return await desktop.work(lambda lib:reconnect(lib,document_id,body.path))

    @app.post('/api/recovery/pick')
    def pick():return pick_pdf()
