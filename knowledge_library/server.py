"""Loopback-only desktop API, persistent indexing jobs, and an offline React bundle."""
from __future__ import annotations
import argparse
import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
import ipaddress
import hashlib
import json
import os
import re
from pathlib import Path
import secrets
import shutil
import sqlite3
import sys
import time
import threading
import uuid
import zipfile

from fastapi import FastAPI, Request, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel, Field
from .embedding import EmbeddingGemma, PROJECT
from .library import Library, now
from .chunking import ChunkingConfig
from .pdf import PdfOptions
from .text_documents import NATIVE_EXTENSIONS, SUPPORTED_EXTENSIONS, MIME_TYPES, source_info


def offline_guard():
    """Permit only literal loopback network access in this server process."""
    def audit(event,args):
        if event=='socket.getaddrinfo':
            host=args[0]
            if host not in ('localhost','127.0.0.1','::1',None):
                from .assistant import permitted_cloud_dns
                if not permitted_cloud_dns(host):raise PermissionError('Local library forbids external DNS')
        if event in ('socket.connect','socket.sendto'):
            address=args[-1]
            if isinstance(address,tuple):
                try:allowed=ipaddress.ip_address(address[0]).is_loopback
                except ValueError:allowed=False
                if not allowed:
                    from .assistant import permitted_cloud_address
                    if not permitted_cloud_address(address):raise PermissionError('Local library forbids external network connections')
    sys.addaudithook(audit)


class FolderBody(BaseModel):
    name:str=Field(min_length=1,max_length=128)
    color:str='#A78BFA'


class MoveBody(BaseModel):
    folder_id:str


class SearchBody(BaseModel):
    query:str=Field(min_length=1,max_length=4096)
    folder_id:str|None=None
    document_id:str|None=None
    show_closest:bool=False
    bills_only:bool=False
    bill_filters:dict[str,str]=Field(default_factory=dict)
    diversify:bool=False
    content_only:bool=False
    preview_only:bool=False
    matching:dict=Field(default_factory=lambda:{'mode':'auto'})
    amount_field:str|None=None
    linked_folder_id:str|None=None
    document_ids:list[str]|None=Field(default=None,max_length=10000)
    library_filters:dict|None=None


class BackupBody(BaseModel):
    password:str=Field(default='',max_length=1024)


class TaskStatusBody(BaseModel):
    ids:list[str]=Field(min_length=1,max_length=500)


class AliasBody(BaseModel):
    alias:str=Field(min_length=1,max_length=160)
    party:str=Field(min_length=1,max_length=160)


class FeedbackBody(BaseModel):
    query:str=Field(max_length=4096)
    kind:str
    note:str=Field(default='',max_length=2000)


class RestoreDocumentBody(BaseModel):
    folder_id:str|None=None


class CleanupBody(BaseModel):
    confirmation:str


class BillBody(BaseModel):
    party:str=Field(default='',max_length=160)
    bill_date:str|None=None
    invoice_number:str=Field(default='',max_length=80)
    direction:str='unspecified'
    amount:str|None=None
    currency:str=Field(default='',max_length=12)
    source_page:int=Field(default=1,ge=1)
    reviewed:bool=False
    amount_reviewed:bool=False


class ExportBody(BaseModel):
    query:str=Field(min_length=1,max_length=4096)
    chunk_ids:list[int]=Field(min_length=1,max_length=25)
    sources:dict[str,str] # chunk id -> immutable source identity from the search response


class LibraryLease:
    """One desktop process per library; OS releases the lock after a crash."""
    def __init__(self,root):
        self.file=(root/'desktop.lock').open('a+b')
        self.file.seek(0,2)
        if self.file.tell()==0:self.file.write(b'0');self.file.flush()
        self.file.seek(0)
        try:
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(self.file.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:
            self.file.close();raise ValueError('Another desktop server is already using this library. Open it or stop it before starting another.')

    def close(self):self.file.close()


class Desktop:
    def __init__(self,root,device):
        self.root=Path(root).resolve();self.root.mkdir(parents=True,exist_ok=True)
        self.lease=LibraryLease(self.root)
        for name in ('uploads','exports'):(self.root/name).mkdir(exist_ok=True)
        self.model=EmbeddingGemma(device=device,dimensions=768)
        from .query_interpreter import QueryInterpreter
        self.interpreter=QueryInterpreter()
        self.pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='library-engine')
        self.metadata_pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='library-metadata')
        self.index_pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='library-index')
        self.indexing_allowed=threading.Event();self.indexing_allowed.set()
        self.charging_only=False
        self.closing=threading.Event();self.search_guard=threading.Lock();self.active_searches=0
        self.warmup_pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='search-startup')
        self.warmup_future=None
        self.warmup_guard=threading.Lock()
        self.warmup_status={'state':'not_loaded','error':None}
        self.token=secrets.token_urlsafe(32)
        self.policy=json.loads((PROJECT/'evaluation/confidence-policy.json').read_text())
        self.futures={}
        self.discovery_tasks=set()
        with self.lib() as lib:
            from .maintenance import initialize
            initialize(lib)
            saved_power=lib.db.execute('SELECT value FROM workspace_settings WHERE key=?',('charging_only',)).fetchone()
            self.charging_only=bool(saved_power and saved_power[0]=='true')
            lib.db.execute('''CREATE TABLE IF NOT EXISTS app_tasks(id TEXT PRIMARY KEY,folder_id TEXT NOT NULL,
                source TEXT NOT NULL,filename TEXT NOT NULL,document_id TEXT,ocr INTEGER NOT NULL,is_bill INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL,progress TEXT,created_at TEXT NOT NULL,finished_at TEXT,error TEXT,result TEXT)''')
            if 'is_bill' not in {r['name'] for r in lib.db.execute('PRAGMA table_info(app_tasks)')}:
                lib.db.execute('ALTER TABLE app_tasks ADD COLUMN is_bill INTEGER NOT NULL DEFAULT 0')
            with lib.db:
                lib.db.execute("UPDATE app_tasks SET status='skipped',finished_at=?,error=NULL WHERE status='skipping'",(now(),))
                lib.db.execute("UPDATE app_tasks SET status='interrupted',finished_at=?,error='Application stopped before the indexing task completed. Retry to continue.' WHERE status IN ('queued','running')",(now(),))
            from .workspace_features import rebuild_links,LINK_VERSION
            link_version=lib.db.execute('SELECT value FROM workspace_settings WHERE key=?',('link_version',)).fetchone()
            if lib.documents() and (not link_version or link_version[0]!=LINK_VERSION):rebuild_links(lib)
            from .discovery import initialize as initialize_discovery
            initialize_discovery(lib)
            from .recovery import initialize as initialize_recovery
            initialize_recovery(lib)
            lib.adopt_source_references()
        from .discovery import Discovery
        from .assistant import Assistant
        self.discovery=Discovery(self)
        self.assistant=Assistant(self)

    def lib(self):return Library(self.root,self.model)

    def semantic_status(self):
        if self.warmup_status['state']=='error':return dict(self.warmup_status)
        if self.model._model is not None and (self.warmup_future is None or self.warmup_future.done()):return {'state':'ready','error':None}
        return dict(self.warmup_status)

    def start_warmup(self):
        with self.warmup_guard:self._start_warmup()

    def _start_warmup(self):
        if self.warmup_future is not None and not self.warmup_future.done():return
        if self.semantic_status()['state']=='ready':return
        self.warmup_status={'state':'loading','error':None}
        def prepare():
            try:
                self.model.query('Search readiness')
                self.warmup_status={'state':'ready','error':None}
            except Exception as error:self.warmup_status={'state':'error','error':str(error)}
        self.warmup_future=self.warmup_pool.submit(prepare)

    def require_idle(self):
        if any(t['status'] in ('queued','running','skipping') for t in self.tasks()):raise ValueError('Wait for indexing to finish before maintenance operations')

    async def work(self,callback):
        return await asyncio.wrap_future(self.pool.submit(self._work,callback))

    async def metadata_work(self,callback):
        return await asyncio.wrap_future(self.metadata_pool.submit(self._work,callback))

    async def search_work(self,callback):
        with self.search_guard:self.active_searches+=1
        try:return await self.work(callback)
        finally:
            with self.search_guard:self.active_searches-=1

    def index_checkpoint(self,task=None):
        def check():
            if task:
                with self.lib() as lib:
                    row=lib.db.execute('SELECT status FROM app_tasks WHERE id=?',(task,)).fetchone()
                if row and row[0] in ('skipping','skipped'):raise InterruptedError('Skipped by you; original file retained.')
        check()
        while not self.indexing_allowed.is_set() or self.active_searches or (self.charging_only and self.processing_status()['waiting_for_power']):
            check()
            if self.closing.is_set():raise InterruptedError('Indexing interrupted by application shutdown; retry to continue.')
            self.closing.wait(.25)
        if self.closing.is_set():raise InterruptedError('Indexing interrupted by application shutdown; retry to continue.')

    def skip(self,task):
        with self.lib() as lib,lib.db:
            lib.db.execute('BEGIN IMMEDIATE')
            row=lib.db.execute('SELECT * FROM app_tasks WHERE id=?',(task,)).fetchone()
            if row is None:raise ValueError('Unknown indexing task')
            if row['status'] not in ('queued','running','skipping'):return dict(status=row['status'])
            if json.loads(row['progress'] or '{}').get('stage')=='committing':
                return dict(status=row['status'],message='This file is finishing its saved index.')
            status='skipped' if row['status']=='queued' else 'skipping'
            lib.db.execute('UPDATE app_tasks SET status=?,finished_at=?,error=NULL WHERE id=?',(status,now() if status=='skipped' else None,task))
        return dict(status=status)

    def processing_status(self):
        import psutil
        battery=psutil.sensors_battery()
        return dict(paused=not self.indexing_allowed.is_set(),charging_only=self.charging_only,
            battery_available=battery is not None,power_plugged=bool(battery and battery.power_plugged),
            waiting_for_power=bool(self.charging_only and (battery is None or not battery.power_plugged)))

    def _work(self,callback):
        with self.lib() as lib:return callback(lib)

    def tasks(self,ids=None):
        with self.lib() as lib:
            if ids is None:rows=[dict(r) for r in lib.db.execute('SELECT * FROM app_tasks ORDER BY created_at DESC LIMIT 100')]
            else:rows=[dict(r) for r in lib.db.execute('SELECT * FROM app_tasks WHERE id IN ('+','.join('?' for _ in ids)+') ORDER BY created_at DESC',ids)]
        for r in rows:
            if r['status'] in ('failed','interrupted'):
                from .recovery import task_issue
                r['recovery']=task_issue(r)
            r.pop('source',None)
            for key in ('progress','result'):r[key]=json.loads(r[key]) if r[key] else None
        return rows

    def queue(self,folder_id,source,filename,document_id=None,ocr=False,bill=False,discovered=None,modified_ms=None):
        task=uuid.uuid4().hex
        with self.lib() as lib:
            lib._folder(folder_id)
            if document_id:lib.document(document_id)
            with lib.db:
                lib.db.execute('BEGIN IMMEDIATE')
                pending=lib.db.execute("SELECT id FROM app_tasks WHERE status IN ('queued','running','skipping') AND ((document_id IS NOT NULL AND document_id=?) OR (folder_id=? AND source=?)) LIMIT 1",(document_id,folder_id,str(source))).fetchone()
                if pending:return pending[0]
                lib.db.execute('INSERT INTO app_tasks(id,folder_id,source,filename,document_id,ocr,is_bill,status,created_at) VALUES(?,?,?,?,?,?,?,?,?)',
                               (task,folder_id,str(source),filename,document_id,int(ocr),int(bill),'queued',now()))
                if modified_ms is not None:
                    lib.db.execute('INSERT OR REPLACE INTO workspace_settings(key,value) VALUES(?,?)',('khoj.import.modified:'+task,json.dumps(dict(source=str(source),epoch_ms=modified_ms))))
                if discovered:
                    source_id,relative_path,signature=discovered
                    lib.db.execute('UPDATE app_tasks SET source_id=?,relative_path=? WHERE id=?',(source_id,relative_path,task))
                    lib.db.execute("UPDATE app_tasks SET status='recovered',error=NULL WHERE source_id=? AND relative_path=? AND id!=? AND status IN ('failed','interrupted')",(source_id,relative_path,task))
                    lib.db.execute("UPDATE watched_files SET task_id=?,queued_signature=?,state='queued',error=NULL WHERE source_id=? AND relative_path=?",
                        (task,signature,source_id,relative_path))
        if discovered:self.discovery_tasks.add(task)
        self.futures[task]=self.index_pool.submit(self._index,task)
        return task

    def _index(self,task):
        with self.lib() as lib:
            row=dict(lib.db.execute('SELECT * FROM app_tasks WHERE id=?',(task,)).fetchone())
            try:
                self.index_checkpoint(task)
                with lib.db:
                    changed=lib.db.execute("UPDATE app_tasks SET status='running' WHERE id=? AND status='queued'",(task,)).rowcount
                if not changed:return
                last_progress_write = 0.
                def progress(value):
                    nonlocal last_progress_write
                    self.index_checkpoint(task)
                    current = time.monotonic()
                    # Keep pause/search/shutdown checks at every checkpoint,
                    # without forcing a durable SQLite write for every page.
                    if current - last_progress_write < .25 and value.get('stage') != 'committing':
                        return
                    with lib.db:
                        lib.db.execute('BEGIN IMMEDIATE')
                        status=lib.db.execute('SELECT status FROM app_tasks WHERE id=?',(task,)).fetchone()[0]
                        if status in ('skipped','skipping'):raise InterruptedError('Skipped by you; original file retained.')
                        lib.db.execute('UPDATE app_tasks SET progress=? WHERE id=?',(json.dumps(value),task))
                    last_progress_write = current
                source=Path(row['source']);original=None
                discovered=task in self.discovery_tasks
                if source.suffix.lower() in ('.ppt','.pptx'):
                    from .presentations import convert
                    progress(dict(stage='converting',page=0,total_pages=0,chunks=0))
                    source,original=convert(source,self.root);original['original_name']=row['filename']
                destination=lib.document(row['document_id'])['folder_id'] if row['document_id'] else row['folder_id']
                importer=lib.import_document
                result=importer(source,destination,document_id=row['document_id'],title=Path(row['filename']).stem if original else None,chunking=ChunkingConfig(256,64),
                                      pdf_options=PdfOptions(ocr=bool(row['ocr']),audit_ocr=bool(row['ocr'] and row['is_bill']),tessdata=str(PROJECT/'models/tessdata')),progress=progress,match_original=not discovered,retain_source=original is not None or source.resolve().is_relative_to((self.root/'uploads').resolve()),publish_partial=False)
                if result['action']!='duplicate':
                    with lib.db:
                        lib.db.execute('DELETE FROM document_sources WHERE document_id=?',(result['document']['id'],))
                        observed=lib.db.execute('SELECT value FROM workspace_settings WHERE key=?',('khoj.import.modified:'+task,)).fetchone()
                        observed=json.loads(observed[0]) if observed else None
                        doc_key='khoj.modified:'+result['document']['id']
                        if observed and observed.get('source')==row['source']:
                            lib.db.execute('INSERT OR REPLACE INTO workspace_settings(key,value) VALUES(?,?)',(doc_key,json.dumps(dict(sha256=result['document']['sha256'],epoch_ms=observed['epoch_ms']))))
                        elif result['action'] in ('added','updated'):
                            lib.db.execute('DELETE FROM workspace_settings WHERE key=?',(doc_key,))
                        lib.db.execute('DELETE FROM workspace_settings WHERE key=?',('khoj.import.modified:'+task,))
                        if original:
                            fields={'document_id':result['document']['id'],**original}
                            lib.db.execute('INSERT INTO document_sources VALUES(?,?,?,?,?,?,?)',tuple(fields[k] for k in ('document_id','original_name','source_path','source_sha256','format','slides','converter')))
                            lib.db.execute('UPDATE documents SET filename=? WHERE id=?',(row['filename'],result['document']['id']))
                    result['document']=lib.document(result['document']['id'])
                from .bills import auto_extract
                if source_info(result['document'])['preview_kind']=='pdf':
                    auto_extract(lib,result['document']['id'],force=bool(row['is_bill']))
                from .workspace_features import assign_subjects
                try:assign_subjects(lib,result['document']['id'])
                except Exception as exc:
                    with lib.db:lib.db.execute('INSERT OR REPLACE INTO workspace_settings VALUES(?,?)',('last_link_error',str(exc)))
                with lib.db:
                    lib.db.execute("UPDATE app_tasks SET status='completed',finished_at=?,result=? WHERE id=?",(now(),json.dumps(result),task))
                    lib.db.execute('DELETE FROM workspace_settings WHERE key=?',('khoj.import.modified:'+task,))
                # Subject memberships are updated above per document. Expensive
                # shared-term regrouping stays in the explicit rebuild tool.
            except Exception as exc:
                skipped=lib.db.execute('SELECT status FROM app_tasks WHERE id=?',(task,)).fetchone()[0] in ('skipping','skipped')
                with lib.db:lib.db.execute("UPDATE app_tasks SET status=?,finished_at=?,error=? WHERE id=?",('skipped' if skipped else 'interrupted' if isinstance(exc,InterruptedError) else 'failed',now(),None if skipped else f'{type(exc).__name__}: {exc}',task))


def create_app(root=None,device='cuda',*,preload=False):
    desktop=Desktop(root or os.environ.get('KNOWLEDGE_LIBRARY_ROOT',PROJECT/'data/desktop'),device)
    @asynccontextmanager
    async def lifespan(app):
        from .recovery import resume_interrupted
        await asyncio.to_thread(resume_interrupted,desktop)
        desktop.discovery.start()
        if preload:
            with desktop.lib() as lib:
                if lib.db.execute('SELECT 1 FROM chunks LIMIT 1').fetchone():desktop.start_warmup()
        try:yield
        finally:
            desktop.closing.set();desktop.indexing_allowed.set()
            desktop.discovery.stop()
            desktop.index_pool.shutdown(wait=True,cancel_futures=False)
            desktop.warmup_pool.shutdown(wait=True,cancel_futures=False)
            desktop.pool.shutdown(wait=True,cancel_futures=False)
            desktop.metadata_pool.shutdown(wait=True,cancel_futures=False)
            desktop.model._model=None
            if desktop.model._torch is not None and desktop.model.device=='cuda':
                desktop.model._torch.cuda.empty_cache()
            desktop.lease.close()
    app=FastAPI(title='Local Knowledge Library',docs_url=None,redoc_url=None,lifespan=lifespan)
    app.state.desktop=desktop
    @app.get('/api/system')
    def system():
        from .hardware import system_report
        return getattr(app.state,'hardware',None) or system_report(desktop.root,dict(device=desktop.model.device,gpu_name=None,reason='Current engine device.'))
    from .workspace_routes import install as install_workspace
    install_workspace(app,desktop)
    from .organization_routes import install as install_organization
    install_organization(app,desktop)
    from .paper_routes import install as install_papers
    install_papers(app,desktop)
    from .recovery import install as install_recovery
    install_recovery(app,desktop)
    from .release_info import install as install_release_info
    install_release_info(app,desktop)
    from .search_previews import install as install_previews
    install_previews(app,desktop)
    from .discovery_routes import install as install_discovery
    install_discovery(app,desktop)
    from .assistant import install as install_assistant
    install_assistant(app,desktop)
    app.add_middleware(TrustedHostMiddleware,allowed_hosts=['127.0.0.1','localhost','testserver'])

    @app.middleware('http')
    async def local_only(request,call_next):
        if request.method not in ('GET','HEAD','OPTIONS') and request.url.path.startswith('/api/'):
            if request.headers.get('x-library-token')!=desktop.token:
                return JSONResponse({'detail':'Reload this local app before making changes.'},status_code=403)
            origin=request.headers.get('origin')
            if origin and origin!=str(request.base_url).rstrip('/'):
                return JSONResponse({'detail':'Cross-origin requests are forbidden.'},status_code=403)
        response=await call_next(request)
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['Content-Security-Policy']="default-src 'self'; img-src 'self' blob: data:; style-src 'self' 'unsafe-inline'; script-src 'self' 'wasm-unsafe-eval'; worker-src 'self' blob:; connect-src 'self'; font-src 'self' data:; frame-ancestors 'none'; object-src 'none'"
        return response

    @app.exception_handler(ValueError)
    async def invalid(request,exc):return JSONResponse({'detail':str(exc)},status_code=400)
    @app.exception_handler(sqlite3.IntegrityError)
    async def conflict(request,exc):return JSONResponse({'detail':'This name or document already exists in the destination folder.'},status_code=409)
    @app.exception_handler(OSError)
    async def storage(request,exc):return JSONResponse({'detail':f'Local file operation failed: {exc}'},status_code=507)
    @app.exception_handler(MemoryError)
    async def memory(request,exc):return JSONResponse({'detail':'Not enough memory to complete this operation. Close other applications and retry. The stored index is retained.'},status_code=503)
    @app.exception_handler(RuntimeError)
    async def runtime_failure(request,exc):
        if 'out of memory' in str(exc).lower():return JSONResponse({'detail':'The GPU or system ran out of memory. Close other applications and retry; your stored index is retained.'},status_code=503)
        if 'CUDA' in str(exc) and 'unavailable' in str(exc):return JSONResponse({'detail':'CUDA is unavailable. Restart the app with --device cpu, or check the NVIDIA driver.'},status_code=503)
        return JSONResponse({'detail':'The local model operation failed. Check the local server log and retry.'},status_code=500)

    @app.get('/api/library-preferences')
    def library_preferences():
        from .library_preferences import read
        with desktop.lib() as lib:return read(lib)

    @app.patch('/api/library-preferences')
    def update_library_preferences(body:dict):
        from .library_preferences import update
        with desktop.lib() as lib:return update(lib,body)

    @app.get('/api/reading-state')
    def reading_state():
        from .reading_state import state
        with desktop.lib() as lib:return state(lib)

    @app.post('/api/documents/{document_id}/reading-state')
    def update_reading_state(document_id:str,body:dict):
        from .reading_state import update
        with desktop.lib() as lib:return update(lib,document_id,body)

    @app.get('/api/state')
    def state(documents_revision:str="",include_documents:bool=True):
        from .bills import all_bills,aliases
        from .maintenance import trash_list
        with desktop.lib() as lib:
            from .presentations import available
            from .workspace_features import linked_folders
            from .organization import decorate_documents
            from .filename_search import attach_scanned_modified_times
            from .library_browse import PAGE_FILTERS,PAGE_SORTS
            documents=None;revision=''
            if include_documents:
                documents=attach_scanned_modified_times(lib,decorate_documents(lib,lib.documents()))
                revision=hashlib.sha256(json.dumps(documents,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode('utf-8')).hexdigest()
            return dict(folders=lib.folders(),documents=None if not include_documents or documents_revision==revision else documents,documents_revision=revision,library_page=dict(sorts=PAGE_SORTS,filters=PAGE_FILTERS),tasks=desktop.tasks(),stats=lib.stats(),powerpoint_available=available(),
                        import_capabilities=dict(upload_extensions=sorted(e.lstrip('.') for e in SUPPORTED_EXTENSIONS),
                            folder_extensions=sorted(e.lstrip('.') for e in SUPPORTED_EXTENSIONS),
                            scan_extensions=sorted(e.lstrip('.') for e in NATIVE_EXTENSIONS|{'.pdf'}),share_extensions=[]),
                        linked_folders=linked_folders(lib),processing=desktop.processing_status(),
                        bills=all_bills(lib),aliases=aliases(lib),trash=trash_list(lib),query_interpreter=desktop.interpreter.status(),semantic_status=desktop.semantic_status(),
                        token=desktop.token,policy={k:v for k,v in desktop.policy.items() if k!='scores'},
                        ocr_available=(PROJECT/'models/tessdata/eng.traineddata').is_file(),local_only=True,
                        assistant=desktop.assistant.status(),
                        connections=[dict(r) for r in lib.db.execute('SELECT id,name,enabled FROM watched_sources ORDER BY created_at')])

    @app.post('/api/library-page')
    async def library_page(body:dict):
        from .library_browse import page
        return await desktop.metadata_work(lambda lib:page(lib,body))

    @app.post('/api/filename-candidates')
    async def filename_candidate_documents(body:dict):
        from .library_browse import filename_candidates
        return await desktop.metadata_work(lambda lib:filename_candidates(lib,body))

    @app.post('/api/folders')
    async def create_folder(body:FolderBody):return await desktop.work(lambda lib:lib.create_folder(body.name,body.color))

    @app.post('/api/models/warmup')
    def warmup():
        desktop.start_warmup();return desktop.semantic_status()
    @app.patch('/api/folders/{folder_id}')
    async def edit_folder(folder_id:str,body:FolderBody):
        def change(lib):
            lib._folder(folder_id);name=lib._name(body.name);color=lib._color(body.color)
            with lib.db:lib.db.execute('UPDATE folders SET name=?,color=?,updated_at=? WHERE id=?',(name,color,now(),folder_id))
            return dict(lib._folder(folder_id))
        return await desktop.work(change)
    @app.delete('/api/folders/{folder_id}')
    async def delete_folder(folder_id:str):
        def remove(lib):
            if lib.db.execute("SELECT 1 FROM app_tasks WHERE folder_id=? AND status IN ('queued','running','skipping')",(folder_id,)).fetchone():
                raise ValueError('Wait for indexing to finish before deleting this folder.')
            return lib.delete_folder(folder_id)
        return await desktop.work(remove)

    @app.post('/api/uploads')
    async def upload(folder_id:str=Form(...),files:list[UploadFile]=File(...),document_id:str|None=Form(None),ocr:bool=Form(False),bill:bool=Form(False),refresh_existing:bool=Form(False),modified_times:str|None=Form(None)):
        if not 1<=len(files)<=30 or (document_id and len(files)!=1):raise ValueError('Choose 1-30 files, or one replacement file.')
        try:timestamps=json.loads(modified_times) if modified_times is not None else [None]*len(files)
        except (ValueError,TypeError):raise ValueError('Invalid file modification dates.') from None
        if not isinstance(timestamps,list) or len(timestamps)!=len(files) or any(t is not None and (type(t) is not int or t<=0 or t>253402300799999) for t in timestamps):raise ValueError('Invalid file modification dates.')
        with desktop.lib() as lib:
            lib._folder(folder_id)
            if document_id and lib.document(document_id)['folder_id']!=folder_id:raise ValueError('Replacement must stay in the document folder.')
        # Validate the whole selection before accepting any file. A mixed invalid
        # batch must not silently queue earlier files and then appear to fail.
        from .presentations import available
        for item in files:
            name=Path(item.filename or '').name;suffix=Path(name).suffix.lower()
            if suffix not in SUPPORTED_EXTENSIONS or len(name)>180 or not name or any(c in name for c in '<>:"|?*') or any(ord(c)<32 for c in name):raise ValueError(f'{name or "Unnamed file"}: choose a supported PDF, presentation, text document or spreadsheet with a valid filename.')
            if bill and suffix in NATIVE_EXTENSIONS:raise ValueError('Structured invoice review currently requires a PDF or presentation; import this document as searchable text.')
            if suffix in ('.ppt','.pptx') and not available():raise ValueError('Microsoft PowerPoint is required for direct slide import on this PC. Export the slides as PDF instead.')
        refresh_targets={}
        if refresh_existing and not document_id:
            names=[Path(item.filename).name for item in files]
            if len(names)!=len(set(names)):raise ValueError('Several selected files share a filename. Refresh them individually or turn off filename matching.')
            with desktop.lib() as lib:
                for name in names:
                    existing=lib.db.execute('SELECT id FROM documents WHERE folder_id=? AND filename=?',(folder_id,name)).fetchall()
                    if len(existing)>1:raise ValueError(f'{name}: several documents have this name. Choose an explicit replacement instead.')
                    if existing:refresh_targets[name]=existing[0]['id']
        tasks=[]
        for upload_file,modified_ms in zip(files,timestamps):
            filename=Path(upload_file.filename or 'untitled.pdf').name
            directory=desktop.root/'uploads'/uuid.uuid4().hex;directory.mkdir()
            source=directory/filename;size=0
            try:
                with source.open('xb') as stream:
                    while block:=await upload_file.read(1024*1024):
                        size+=len(block)
                        if size>100*1024*1024:raise ValueError('Each file must be at most 100 MiB.')
                        if shutil.disk_usage(directory).free<len(block)+32*1024*1024:raise OSError('Insufficient free storage for upload reserve')
                        stream.write(block)
                target=document_id or refresh_targets.get(filename)
                tasks.append(desktop.queue(folder_id,source,filename,target,ocr,bill,modified_ms=modified_ms))
            finally:await upload_file.close()
        return dict(task_ids=tasks)

    @app.post('/api/tasks/{task_id}/retry')
    def retry(task_id:str):
        from .recovery import retry_task
        return dict(task_id=retry_task(desktop,task_id))

    @app.post('/api/tasks/status')
    def task_status(body:TaskStatusBody):return desktop.tasks(body.ids)

    @app.post('/api/tasks/{task_id}/skip')
    def skip_task(task_id:str):return desktop.skip(task_id)

    @app.get('/api/documents/{document_id}/bill')
    def bill_details(document_id:str):
        from .bills import get,suggestions
        with desktop.lib() as lib:return dict(saved=get(lib,document_id),suggested=suggestions(lib,document_id))

    @app.get('/api/documents/{document_id}/evidence')
    def bill_evidence(document_id:str,page:int=1,field:str='party',value:str=''):
        from .bills import get,suggestions,parse_date
        with desktop.lib() as lib:
            doc=lib.document(document_id)
            if source_info(doc)['preview_kind']=='text':raise ValueError('PDF evidence is unavailable for native text documents')
            record=get(lib,document_id) or suggestions(lib,document_id)
            source=lib.page(document_id,page)
        if field not in ('party','bill_date','invoice_number','amount','direction'):raise ValueError('Unknown bill field')
        text=value or str(record.get(field) or '')
        if len(text)>200:raise ValueError('Field text too long')
        if field=='bill_date' and parse_date(text):
            import re
            for line in source['text'].splitlines():
                if parse_date(line)==text:
                    text=re.sub(r'^\s*(?:(?:invoice|bill)\s+)?date\s*[:\-]?\s*','',line,flags=re.I).strip();break
        if field=='amount' and text:
            import re
            from decimal import Decimal,InvalidOperation
            try:
                target=Decimal(text.replace(',',''))
                for number in re.findall(r'\b\d[\d,]*(?:\.\d{1,2})?\b',source['text']):
                    if Decimal(number.replace(',',''))==target:text=number;break
            except InvalidOperation:pass
        import pymupdf
        boxes=[]
        with desktop.lib() as lib:pdf_path=lib.source_path(doc,verify=True)
        with pymupdf.open(pdf_path) as pdf:
            physical=pdf[page-1]
            if text:boxes=[[r.x0/physical.rect.width,r.y0/physical.rect.height,r.width/physical.rect.width,r.height/physical.rect.height] for r in physical.search_for(text)][:30]
        return dict(text=source['text'],method=source['method'],field=field,value=text,boxes=boxes,
                    found=bool(text and text.casefold() in source['text'].casefold()),page=page,
                    note='Highlights locate literal text; they do not validate its meaning. Scanned pages may have no PDF text boxes.')

    @app.put('/api/party-aliases')
    async def alias(body:AliasBody):
        from .bills import save_alias
        return await desktop.work(lambda lib:save_alias(lib,body.alias,body.party))

    @app.delete('/api/party-aliases/{alias}')
    async def remove_alias(alias:str):
        from .bills import normalized
        def remove(lib):
            with lib.db:lib.db.execute('DELETE FROM party_aliases WHERE alias=?',(normalized(alias),))
            return dict(removed=True)
        return await desktop.work(remove)

    @app.get('/api/maintenance')
    async def maintenance():
        from .maintenance import storage
        return await desktop.work(storage)

    @app.post('/api/backup')
    async def make_backup(body:BackupBody|None=None):
        from .maintenance import backup
        password=body.password if body else ''
        desktop.require_idle()
        if password:
            from .encrypted_backup import backup as secure_backup
            path=await desktop.work(lambda lib:secure_backup(lib,password))
        else:path=await desktop.work(backup)
        return FileResponse(path,media_type='application/octet-stream' if password else 'application/zip',filename=path.name)

    @app.post('/api/restore-backup')
    async def restore_archive(file:UploadFile=File(...),password:str=Form('',max_length=1024)):
        from .maintenance import restore_backup,schema
        desktop.require_idle()
        directory=desktop.root.parent/'restored';directory.mkdir(parents=True,exist_ok=True)
        uploaded=desktop.root/'uploads'/f'backup-{uuid.uuid4().hex}.zip';size=0
        decrypted=uploaded.with_suffix('.decrypted.zip')
        try:
            with uploaded.open('xb') as stream:
                while block:=await file.read(1024**2):
                    size+=len(block)
                    if size>2*1024**3:raise ValueError('Backup upload must be at most 2 GiB')
                    if shutil.disk_usage(uploaded.parent).free<len(block)+32*1024**2:raise OSError('Insufficient storage for backup upload')
                    stream.write(block)
            destination=directory/uuid.uuid4().hex
            def restore(lib):
                from .encrypted_backup import encrypted,decrypt
                archive=decrypt(uploaded,decrypted,password) if encrypted(uploaded) else uploaded
                return restore_backup(archive,destination,desktop.model,trusted_schema=schema(lib))
            try:return await desktop.work(restore)
            except (KeyError,json.JSONDecodeError,zipfile.BadZipFile) as exc:raise ValueError('Invalid or corrupted backup archive') from exc
        finally:
            await file.close();uploaded.unlink(missing_ok=True);decrypted.unlink(missing_ok=True)

    @app.post('/api/cleanup')
    async def clean(body:CleanupBody):
        from .maintenance import cleanup
        if body.confirmation!='CLEAN UNUSED PDFS':raise ValueError('Type CLEAN UNUSED PDFS to confirm cleanup')
        desktop.require_idle();return await desktop.work(cleanup)

    @app.post('/api/trash/{key}/restore')
    async def restore_deleted(key:str,body:RestoreDocumentBody):
        from .maintenance import restore_document
        desktop.require_idle();return await desktop.work(lambda lib:restore_document(lib,key,body.folder_id))

    @app.delete('/api/trash/{key}')
    async def purge_deleted(key:str,body:CleanupBody):
        if body.confirmation!='DELETE PERMANENTLY':raise ValueError('Type DELETE PERMANENTLY to confirm permanent deletion')
        desktop.require_idle()
        def purge(lib):
            with lib.db:
                row=lib.db.execute('SELECT payload FROM trash WHERE id=?',(key,)).fetchone()
                if row:
                    document_id=json.loads(row[0])['document']['id']
                    lib.db.execute('DELETE FROM workspace_settings WHERE key IN (?,?)',('organization.document_name:'+document_id,'organization.topics:'+document_id))
                lib.db.execute('DELETE FROM trash WHERE id=?',(key,))
            return dict(purged=True)
        return await desktop.work(purge)

    @app.post('/api/feedback')
    async def feedback(body:FeedbackBody):
        if body.kind not in ('useful','wrong_match','missing_result','extraction_error','friction'):raise ValueError('Unknown feedback category')
        def record(lib):
            with lib.db:lib.db.execute('INSERT INTO feedback VALUES(?,?,?,?,?)',(uuid.uuid4().hex,now(),body.query,body.kind,body.note))
            return dict(saved=True,local_only=True)
        return await desktop.work(record)

    @app.get('/api/feedback')
    def feedback_log():
        with desktop.lib() as lib:return [dict(r) for r in lib.db.execute('SELECT * FROM feedback ORDER BY created_at DESC LIMIT 500')]

    @app.put('/api/documents/{document_id}/bill')
    async def save_bill(document_id:str,body:BillBody):
        from .workspace_features import save_correction
        return await desktop.work(lambda lib:save_correction(lib,document_id,body.model_dump(),body.reviewed))

    @app.delete('/api/documents/{document_id}/bill')
    async def unmark_bill(document_id:str):
        def remove(lib):
            lib.document(document_id)
            with lib.db:lib.db.execute('DELETE FROM bill_records WHERE document_id=?',(document_id,))
            return dict(removed_bill_details=True)
        return await desktop.work(remove)

    @app.patch('/api/documents/{document_id}/move')
    async def move(document_id:str,body:MoveBody):return await desktop.work(lambda lib:lib.move_document(document_id,body.folder_id))
    @app.delete('/api/documents/{document_id}')
    async def remove_document(document_id:str):
        from .maintenance import trash_document
        desktop.require_idle();return await desktop.work(lambda lib:trash_document(lib,document_id))
    @app.post('/api/documents/{document_id}/refresh')
    def refresh(document_id:str):
        with desktop.lib() as lib:
            doc=lib.document(document_id)
            original=lib.db.execute('SELECT * FROM document_sources WHERE document_id=?',(document_id,)).fetchone()
            source=desktop.root/original['source_path'] if original else doc['original_path']
            ocr=json.loads(doc['recipe']).get('pdf',{}).get('ocr',False)
            return dict(task_id=desktop.queue(doc['folder_id'],source,doc['filename'],document_id,ocr=ocr))

    @app.post('/api/documents/{document_id}/refresh-ocr')
    def refresh_ocr(document_id:str):
        if not (PROJECT/'models/tessdata/eng.traineddata').is_file():raise ValueError('English OCR data is not installed.')
        with desktop.lib() as lib:
            doc=lib.document(document_id)
            if source_info(doc)['preview_kind']=='text':raise ValueError('OCR is available for PDFs and rendered presentations, not native text documents.')
            if lib.db.execute("SELECT 1 FROM app_tasks WHERE document_id=? AND status IN ('queued','running','skipping')",(document_id,)).fetchone():raise ValueError('This document is already being indexed.')
            original=lib.db.execute('SELECT * FROM document_sources WHERE document_id=?',(document_id,)).fetchone()
            source=desktop.root/original['source_path'] if original else doc['original_path']
            return dict(task_id=desktop.queue(doc['folder_id'],source,doc['filename'],document_id,ocr=True))

    @app.get('/api/documents/{document_id}')
    def document(document_id:str):
        with desktop.lib() as lib:
            original=lib.db.execute('SELECT * FROM document_sources WHERE document_id=?',(document_id,)).fetchone()
            return dict(document=lib.document(document_id),pages=lib.page_summary(document_id),original=dict(original) if original else None)
    @app.get('/api/documents/{document_id}/original')
    def original_file(document_id:str):
        with desktop.lib() as lib:
            lib.document(document_id);row=lib.db.execute('SELECT * FROM document_sources WHERE document_id=?',(document_id,)).fetchone()
            if not row:raise HTTPException(404,'No PowerPoint source is stored for this document')
            original=dict(row)
        path=(desktop.root/original['source_path']).resolve()
        if path.parent!=(desktop.root/'originals').resolve() or not path.is_file():raise HTTPException(404,'Original presentation unavailable')
        return FileResponse(path,filename=original['original_name'],media_type='application/vnd.openxmlformats-officedocument.presentationml.presentation' if original['format']=='pptx' else 'application/vnd.ms-powerpoint')
    @app.get('/api/documents/{document_id}/file')
    def pdf_file(document_id:str, download:bool=False):
        with desktop.lib() as lib:
            doc=lib.document(document_id)
            try:source=lib.source_path(doc,verify=True)
            except FileNotFoundError:raise HTTPException(404,'Original file is unavailable. Reconnect its drive or restore the file.')
            except ValueError as exc:raise HTTPException(409,str(exc))
        disposition = 'attachment' if download else 'inline'
        suffix = source.suffix.lower()
        if source_info(doc)['preview_kind']=='text' or suffix in MIME_TYPES:
            return FileResponse(source,media_type=MIME_TYPES.get(suffix,'text/plain'),filename=doc['filename'],content_disposition_type=disposition)
        return FileResponse(source,media_type='application/pdf',filename=Path(doc['filename']).stem+'.pdf',content_disposition_type=disposition)
    @app.get('/api/documents/{document_id}/units/{number}')
    @app.get('/api/documents/{document_id}/pages/{number}')
    def page(document_id:str,number:int,revision:str=''):
        with desktop.lib() as lib:
            if revision and lib.document(document_id)['sha256']!=revision:raise HTTPException(409,'The source changed. Search again to open the current text.')
            return lib.page(document_id,number)

    @app.post('/api/documents/{document_id}/reveal')
    def reveal_document(document_id:str):
        with desktop.lib() as lib:
            doc=lib.document(document_id)
            try:source=lib.source_path(doc,verify=True)
            except Exception:source=Path(doc.get('original_path',''))
        target=Path(source)
        if os.name=='nt' and target.exists():
            import subprocess
            subprocess.Popen(['explorer.exe',f'/select,{str(target)}'])
        return dict(revealed=True,path=str(target),filename=doc['filename'])

    @app.post('/api/estimate')
    def estimate_import(body:dict):
        items=body.get('files',[])
        total_files=len(items)
        estimated_pages=0
        for item in items:
            name=item.get('name','')
            size=int(item.get('size',0))
            ext=Path(name).suffix.lower()
            if ext=='.pdf':
                estimated_pages+=max(1,round(size/65000))
            elif ext in ('.ppt','.pptx'):
                estimated_pages+=max(1,round(size/80000))
            else:
                estimated_pages+=1
        estimated_seconds=max(1,round(estimated_pages*0.08))
        mins=estimated_seconds//60
        secs=estimated_seconds%60
        time_str=f"{mins} min {secs} sec" if mins>0 else f"{secs} sec"
        return dict(total_files=total_files,estimated_pages=estimated_pages,estimated_seconds=estimated_seconds,formatted_time=time_str)

    @app.get('/api/auditor/skipped-files')
    def skipped_files():
        with desktop.lib() as lib:
            doc_rows = lib.db.execute('''
                SELECT d.id, d.folder_id, f.name as folder_name, d.filename, d.title, d.status,
                       d.page_count, d.chunk_count, d.updated_at
                FROM documents d
                JOIN folders f ON f.id=d.folder_id
                WHERE d.status != 'indexed'
                ORDER BY d.updated_at DESC
            ''').fetchall()
            problem_docs = []
            for r in doc_rows:
                st = r['status']
                if st == 'needs_ocr':
                    reason = 'Scanned page(s) · No digital text detected; re-read with OCR.'
                    action = 'ocr'
                elif st == 'empty':
                    reason = 'Empty document · No text or extractable structure found.'
                    action = 'recovery'
                elif st == 'extraction_failed':
                    reason = 'Extraction failed · Damaged structure or password-protected.'
                    action = 'recovery'
                elif st == 'partial':
                    reason = 'Partially indexed · Some pages had scan noise or warnings.'
                    action = 'recovery'
                else:
                    reason = f'Status: {st}'
                    action = 'recovery'
                problem_docs.append({
                    'id': r['id'],
                    'folder_id': r['folder_id'],
                    'folder_name': r['folder_name'],
                    'filename': r['filename'],
                    'title': r['title'],
                    'status': st,
                    'page_count': r['page_count'],
                    'chunk_count': r['chunk_count'],
                    'reason': reason,
                    'suggested_action': action
                })
            task_rows = lib.db.execute('''
                SELECT id, filename, folder_id, status, error, created_at
                FROM app_tasks
                WHERE status IN ('failed', 'interrupted')
                ORDER BY created_at DESC LIMIT 50
            ''').fetchall()
            problem_tasks = []
            for r in task_rows:
                problem_tasks.append({
                    'task_id': r['id'],
                    'filename': r['filename'],
                    'folder_id': r['folder_id'],
                    'status': r['status'],
                    'error': r['error'] or 'Indexing did not complete',
                    'created_at': r['created_at']
                })
            discovered_rows = lib.db.execute('''
                SELECT w.relative_path, w.state, w.error, s.name as folder_name, s.path as folder_root
                FROM watched_files w
                JOIN watched_sources s ON s.id=w.source_id
                WHERE w.state='failed' LIMIT 50
            ''').fetchall()
            problem_discovered = []
            for r in discovered_rows:
                problem_discovered.append({
                    'relative_path': r['relative_path'],
                    'folder_name': r['folder_name'],
                    'folder_root': r['folder_root'],
                    'error': r['error'] or 'Access denied or file locked by another process'
                })
            total = len(problem_docs) + len(problem_tasks) + len(problem_discovered)
            summary = {
                'total_skipped': total,
                'needs_ocr': sum(1 for d in problem_docs if d['status'] == 'needs_ocr'),
                'unreadable_or_corrupt': sum(1 for d in problem_docs if d['status'] in ('extraction_failed', 'empty')) + len(problem_tasks),
                'partial': sum(1 for d in problem_docs if d['status'] == 'partial'),
                'access_denied': len(problem_discovered)
            }
            return {
                'summary': summary,
                'documents': problem_docs,
                'tasks': problem_tasks,
                'discovered': problem_discovered
            }

    @app.post('/api/filename-matches')
    async def filename_matches(body:SearchBody):
        from .filename_search import FilenameMatcher
        from .workspace_features import scope
        def run(lib):
            ids=set(scope(lib,body.linked_folder_id)) if body.linked_folder_id else None
            if body.document_ids is not None:ids=set(body.document_ids) if ids is None else ids.intersection(body.document_ids)
            if body.library_filters is not None:
                from .library_browse import scope_ids
                filtered=set(scope_ids(lib,body.library_filters));ids=filtered if ids is None else ids.intersection(filtered)
            matches=[];matcher=FilenameMatcher(body.query)
            if body.folder_id:lib._folder(body.folder_id)
            sql='SELECT d.id,d.filename,d.folder_id,d.managed_path,d.original_path,d.source_mode,f.name folder_name FROM documents d JOIN folders f ON f.id=d.folder_id'
            params=[]
            if body.folder_id:sql+=' WHERE d.folder_id=?';params.append(body.folder_id)
            for row in lib.db.execute(sql,params):
                if body.document_id and row['id']!=body.document_id:continue
                if ids is not None and row['id'] not in ids:continue
                if not matcher.matches(row['filename']):continue
                doc=dict(row)
                try:
                    source=lib.source_path(doc)
                    available=source.is_file() and os.access(source,os.R_OK)
                except (ValueError,OSError):available=False
                matches.append(dict(document_id=doc['id'],filename=doc['filename'],folder_id=doc['folder_id'],folder=doc['folder_name'],available=available))
            return dict(matches=matches)
        return await desktop.metadata_work(run)

    @app.post('/api/search')
    async def search(body:SearchBody):
        from .query_interpreter import expand_amount_shorthand
        original_query=body.query
        filename_started=time.perf_counter()
        # A whole-filename match is a document match, not a fabricated passage.
        # Explicit in-document, bill and content-only searches retain their normal path.
        if not body.preview_only and not body.content_only and not body.document_id and not body.bills_only and not any(body.bill_filters.values()):
            matches=(await filename_matches(body))['matches']
            if matches:
                matches=sorted(matches,key=lambda item:(item['folder'].casefold(),item['filename'].casefold(),item['document_id']))
                results=[dict(document_id=item['document_id'],filename=item['filename'],folder_id=item['folder_id'],folder=item['folder'],
                    page_number=None,chunk_id=None,passage='',score=1.0,score_type='exact_filename',source_available=item['available'],
                    match_reasons=['Exact filename'],open_uri='/api/documents/'+item['document_id']+'/file',rank=rank)
                    for rank,item in enumerate(matches,1)]
                return dict(query=original_query,mode='filename',results=results,exact_filename_matches=matches,elapsed_s=time.perf_counter()-filename_started,
                    reliability='filename_match',empty_reason=None,closest_available=False,below_cutoff=False,
                    query_interpreter='not_needed',response=None)

        expanded=expand_amount_shorthand(original_query)
        body=body.model_copy(update={'query':expanded})
        def run(lib):
            from .bills import search as search_bills
            from .bills import parse_query,all_bills,aliases
            from .bill_amounts import query_amount
            from .query_interpreter import candidate
            from .search_response import respond
            started=time.perf_counter()
            interpretation=None
            # Extract power-user search prefixes (folder:, bill:, ext:, party:, date:)
            prefixes={'folder_id':None,'bills_only':False,'bill_filters':{},'ext':None,'applied':[]}
            clean_q=body.query.strip()
            folder_match=re.search(r'\bfolder:(?:"([^"]+)"|(\S+))',clean_q,re.I)
            if folder_match:
                f_val=folder_match.group(1) or folder_match.group(2)
                if re.search(r'\bfolder:(?:"([^"]+)"|(\S+))',clean_q[folder_match.end():],re.I):raise ValueError('Use one folder per search.')
                folders=lib.folders()
                exact=[f for f in folders if f['name'].casefold()==f_val.casefold()]
                matches=exact or [f for f in folders if f_val.casefold() in f['name'].casefold()]
                if len(matches)!=1:raise ValueError('Folder name is missing or ambiguous. Use the full folder name.')
                selected=matches[0]
                if body.folder_id and body.folder_id!=selected['id']:raise ValueError('The folder in the search differs from the selected folder.')
                prefixes['folder_id']=selected['id']
                prefixes['applied'].append(f'Folder: {selected["name"]}')
                clean_q=clean_q[:folder_match.start()]+' '+clean_q[folder_match.end():]
            bill_match=re.search(r'\b(?:type|is):bill\b|\b(?:bill|invoice):',clean_q,re.I)
            if bill_match:
                prefixes['bills_only']=True
                prefixes['applied'].append('Bills only')
                clean_q=clean_q[:bill_match.start()]+' '+clean_q[bill_match.end():]
            party_match=re.search(r'\bparty:(?:"([^"]+)"|(\S+))',clean_q,re.I)
            if party_match:
                p_val=party_match.group(1) or party_match.group(2)
                prefixes['bill_filters']['party']=p_val
                prefixes['bills_only']=True
                prefixes['applied'].append(f'Party: {p_val}')
                clean_q=clean_q[:party_match.start()]+' '+clean_q[party_match.end():]
            ext_match=re.search(r'\bext:(?:"([^"]+)"|(\S+))',clean_q,re.I)
            if ext_match:
                e_val=(ext_match.group(1) or ext_match.group(2)).lower().lstrip('.')
                prefixes['ext']=e_val
                prefixes['applied'].append(f'Extension: .{e_val}')
                clean_q=clean_q[:ext_match.start()]+' '+clean_q[ext_match.end():]
            date_match=re.search(r'\bdate:(\d{4}-\d{2}-\d{2})\b',clean_q,re.I)
            if date_match:
                d_val=date_match.group(1)
                prefixes['bill_filters']['date_from']=d_val
                prefixes['bill_filters']['date_to']=d_val
                prefixes['bills_only']=True
                prefixes['applied'].append(f'Date: {d_val}')
                clean_q=clean_q[:date_match.start()]+' '+clean_q[date_match.end():]
            clean_q=' '.join(clean_q.split())
            search_query=clean_q or body.query
            active_folder=prefixes['folder_id'] or body.folder_id
            active_bills_only=body.bills_only or prefixes['bills_only']

            from .workspace_features import scope,diagnostics
            document_ids=scope(lib,body.linked_folder_id) if body.linked_folder_id else None
            if body.document_ids is not None:document_ids=list(body.document_ids if document_ids is None else set(document_ids).intersection(body.document_ids))
            if body.library_filters is not None:
                from .library_browse import scope_ids
                filtered=set(scope_ids(lib,body.library_filters));document_ids=list(filtered if document_ids is None else filtered.intersection(document_ids))
            if prefixes['ext']:
                ext_suffix=f".{prefixes['ext']}"
                ext_doc_ids={d['id'] for d in lib.documents() if d['filename'].lower().endswith(ext_suffix)}
                document_ids=list(ext_doc_ids if document_ids is None else set(document_ids) & ext_doc_ids)

            diagnostic_ids=([body.document_id] if document_ids is None or body.document_id in document_ids else []) if body.document_id else document_ids
            if body.amount_field not in (None,'total','subtotal'):raise ValueError('Choose total or subtotal.')
            # Exact English field lookups and recognized identifiers bypass generation.
            amount=query_amount(search_query)
            if body.preview_only:
                preview=[]
                if not active_bills_only and not any(body.bill_filters.values()) and not amount and not candidate(search_query):
                    # Structured bill searches have their own match rules.
                    intent=search_bills(lib,search_query,folder_id=active_folder,document_id=body.document_id,document_ids=document_ids)
                    if intent is None:
                        preview=lib.search(search_query,folder_id=active_folder,document_id=body.document_id,
                            document_ids=document_ids,top_k=5,mode='preview')['results']
                        for hit in preview:
                            hit['match_reasons']=['Indexed keyword match']
                            hit['source_identity']=f"{hit['document_id']}:{hit['source_sha256']}:{hit['source_revision']}:{hit['chunk_index']}:{hit['page_number']}"
                return dict(query=original_query,mode='preview',results=preview,elapsed_s=time.perf_counter()-started,
                    reliability='keyword_preview',empty_reason=None,closest_available=False,below_cutoff=False)

            try:
                semantic_interpretation=desktop.interpreter.interpret_general(original_query)
                general_interpreter='qwen'
            except (ValueError,OSError):
                semantic_interpretation=''
                general_interpreter='unavailable'

            if not amount and candidate(search_query):
                intent=parse_query(search_query,all_bills(lib),aliases(lib))
                needs_interpretation=not intent['invoice_number'] and (not intent['date_from'] or re.search(r'\b(?:ka|wala|wali|dikha|dikhao|becha|kharida)\b',search_query,re.I))
                if needs_interpretation:
                    interpretation=desktop.interpreter.interpret(search_query)
            filters={**(interpretation['filters'] if interpretation else {}),**prefixes['bill_filters'],**{k:v for k,v in body.bill_filters.items() if v}}
            requested_amount=(interpretation['amount'] if interpretation else amount)
            if requested_amount and body.amount_field:requested_amount={**requested_amount,'field':body.amount_field}
            result=search_bills(lib,search_query,folder_id=active_folder,document_id=body.document_id,force=active_bills_only,filters=filters,
                amount_override=requested_amount,document_ids=document_ids,matching=body.matching)
            if result is not None:
                result['query_interpreter']=general_interpreter
                result['query']=original_query
                if expanded!=original_query:result['normalized_query']=expanded
                if prefixes['applied']:result['applied_prefixes']=prefixes['applied']
                if requested_amount and not body.amount_field and not re.search(r'\b(?:total|subtotal|sub-total|before tax)\b|tax se pehle',search_query,re.I):
                    other=search_bills(lib,search_query,folder_id=active_folder,document_id=body.document_id,force=True,filters=filters,
                        amount_override={**requested_amount,'field':'subtotal'},document_ids=document_ids,matching=body.matching)
                    from decimal import Decimal
                    def closest_ids(hits):
                        if not hits:return set(),None
                        best=min(abs(Decimal(h['amount_match']['difference'])) for h in hits)
                        return {h['document_id'] for h in hits if abs(Decimal(h['amount_match']['difference']))==best},best
                    totals,total_gap=closest_ids(result['results']);subs,sub_gap=closest_ids(other['results'])
                    if subs and totals!=subs and (total_gap is None or sub_gap<=total_gap):
                        result.update(results=[],clarification={'question':'Do you mean the final total or the subtotal before tax?','choices':['total','subtotal']},
                            response=dict(text='This amount could refer to the final total or the subtotal. Choose a field to continue.',citations=[],method='clarification',limitation=None),
                            elapsed_s=time.perf_counter()-started)
                        return result
                if interpretation:result['interpretation']=interpretation
                result['elapsed_s']=time.perf_counter()-started
                for hit in result['results']:
                    doc=lib.document(hit['document_id']);hit['source_identity']=f"{doc['id']}:{doc['sha256']}:{doc['version']}:{hit['chunk_index']}:{hit['page_number']}"
                result['response']=respond(lib,desktop.interpreter,search_query,result,select_source=False)
                result['diagnostics']=diagnostics(lib,active_folder,diagnostic_ids)
                result['elapsed_s']=time.perf_counter()-started
                return result
            from .retrieval import literal_query
            literal_text=literal_query(search_query)
            literal_response=lib.search(literal_text,folder_id=active_folder,document_id=body.document_id,document_ids=document_ids,top_k=5,mode='literal')
            exact=literal_response['results']
            for hit in exact:hit['match_reasons']=['Exact text match in indexed passage']
            semantic_unavailable=False
            try:
                result=lib.search(search_query,folder_id=active_folder,document_id=body.document_id,document_ids=document_ids,top_k=20 if body.diversify else 5,mode='semantic',semantic_query=(search_query+'\n'+semantic_interpretation if semantic_interpretation else search_query))
            except (ValueError,RuntimeError,OSError):
                if not exact:raise
                result={**literal_response,'results':[]};semantic_unavailable=True
            result['query_interpreter']=general_interpreter
            if semantic_interpretation:result['semantic_interpretation']=semantic_interpretation
            result['query']=original_query
            if expanded!=original_query:result['normalized_query']=expanded
            if prefixes['applied']:result['applied_prefixes']=prefixes['applied']
            if body.diversify:
                seen=set();diverse=[]
                for hit in result['results']:
                    if hit['document_id'] not in seen:diverse.append(hit);seen.add(hit['document_id'])
                result['results']=(diverse+[h for h in result['results'] if h not in diverse])[:5]
            from .retrieval import terms
            for hit in result['results']:hit['match_terms']=[w for w in terms(search_query) if w in hit['passage'].casefold()]
            result['presentation']='document_diversity' if body.diversify else 'semantic_rank'
            below=bool(result['results']) and result['results'][0]['score']<desktop.policy['threshold']
            result.update(policy_version=desktop.policy['version'],cutoff=desktop.policy['threshold'],below_cutoff=below,closest_available=below)
            if below and not body.show_closest:result['results']=[];result['reliability']='no_confident_match'
            elif result['results']:result['reliability']='closest_candidates' if below else 'tentative_source_matches'
            seen={(h['document_id'],h['page_number']) for h in exact}
            result['results']=(exact+[h for h in result['results'] if (h['document_id'],h['page_number']) not in seen])[:5]
            for rank,hit in enumerate(result['results'],1):hit['rank']=rank
            if exact:
                result['below_cutoff']=False;result['closest_available']=False;result['reliability']='literal_and_semantic_candidates'
                result['empty_reason']=None
            result['note']='Exact indexed text matches; semantic search was unavailable.' if semantic_unavailable else 'Exact text matches are shown first; other results use similarity. Verify the source.'
            for hit in result['results']:
                doc=lib.document(hit['document_id']);hit['source_identity']=f"{doc['id']}:{doc['sha256']}:{doc['version']}:{hit['chunk_index']}:{hit['page_number']}"
            result['response']=respond(lib,desktop.interpreter,search_query,result,select_source=False)
            result['diagnostics']=diagnostics(lib,active_folder,diagnostic_ids)
            result['elapsed_s']=time.perf_counter()-started
            return result
        return await (desktop.metadata_work(run) if body.preview_only else desktop.search_work(run))

    @app.post('/api/export')
    async def export(body:ExportBody):
        from .export import context_pdf
        def generate(lib):
            for chunk_id in body.chunk_ids:
                row=lib.db.execute('SELECT c.document_id,c.chunk_index,c.page_number,d.sha256,d.version FROM chunks c JOIN documents d ON d.id=c.document_id WHERE c.id=?',(chunk_id,)).fetchone()
                if row is None or body.sources.get(str(chunk_id))!=f"{row['document_id']}:{row['sha256']}:{row['version']}:{row['chunk_index']}:{row['page_number']}":
                    raise ValueError('A selected source changed. Search again before exporting.')
            path=desktop.root/'exports'/f'context-{uuid.uuid4().hex}.pdf'
            context_pdf(lib,body.query,body.chunk_ids,path);return path
        path=await desktop.work(generate)
        return FileResponse(path,media_type='application/pdf',filename='Library context.pdf')

    dist=PROJECT/'frontend/dist'
    if dist.is_dir():
        app.mount('/',StaticFiles(directory=dist,html=True),name='desktop')
    return app


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--library',type=Path,default=PROJECT/'data/desktop');parser.add_argument('--device',choices=['cuda','cpu'],default='cuda');parser.add_argument('--port',type=int,default=8765);parser.add_argument('--no-preload',action='store_true')
    args=parser.parse_args();offline_guard()
    import uvicorn
    uvicorn.run(create_app(args.library,args.device,preload=not args.no_preload),host='127.0.0.1',port=args.port,access_log=False)


if __name__=='__main__':main()
