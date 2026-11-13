"""Opt-in PC folder discovery. Originals are read, never moved or deleted."""
from __future__ import annotations

import json
import os
from pathlib import Path
import threading
import time
import uuid

from .library import now
from .text_documents import NATIVE_EXTENSIONS

INTERVAL = 60
MAX_FILES = 25000
SKIP_DIRS = {'.git', '.venv', 'node_modules', '$recycle.bin', 'system volume information'}


def initialize(lib):
    lib.db.executescript('''
        CREATE TABLE IF NOT EXISTS watched_sources(
            id TEXT PRIMARY KEY, path TEXT NOT NULL UNIQUE, name TEXT NOT NULL,
            folder_id TEXT NOT NULL REFERENCES folders(id) ON DELETE RESTRICT,
            enabled INTEGER NOT NULL DEFAULT 1, ocr INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL, last_scan TEXT, state TEXT NOT NULL DEFAULT 'waiting', error TEXT);
        CREATE TABLE IF NOT EXISTS watched_files(
            source_id TEXT NOT NULL REFERENCES watched_sources(id) ON DELETE CASCADE,
            relative_path TEXT NOT NULL, signature TEXT NOT NULL, indexed_signature TEXT,
            document_id TEXT, task_id TEXT, queued_signature TEXT,
            state TEXT NOT NULL DEFAULT 'discovered', error TEXT,
            PRIMARY KEY(source_id,relative_path));
        CREATE INDEX IF NOT EXISTS watched_files_task ON watched_files(task_id);
    ''')


def sources(lib):
    result = []
    for row in lib.db.execute('SELECT * FROM watched_sources ORDER BY created_at'):
        item = dict(row)
        options = lib.db.execute('SELECT value FROM workspace_settings WHERE key=?', ('source_options:' + row['id'],)).fetchone()
        item['options'] = json.loads(options[0]) if options else {}
        run = lib.db.execute('SELECT value FROM workspace_settings WHERE key=?', ('scan_run:' + row['id'],)).fetchone()
        item['timing'] = json.loads(run[0]) if run else None
        item['counts'] = dict(lib.db.execute(
            'SELECT state,count(*) FROM watched_files WHERE source_id=? GROUP BY state', (row['id'],)))
        item['files'] = [dict(r) for r in lib.db.execute('''
            SELECT relative_path,state,error,document_id FROM watched_files WHERE source_id=?
            ORDER BY CASE state WHEN 'failed' THEN 0 WHEN 'queued' THEN 1 WHEN 'discovered' THEN 2 ELSE 3 END,
            relative_path LIMIT 40''', (row['id'],))]
        result.append(item)
    return result


def linked(path):
    return path.is_symlink() or bool(getattr(path, 'is_junction', lambda: False)())


class Discovery:
    def __init__(self, desktop):
        self.desktop = desktop
        self.lock = threading.RLock()
        self.wake = threading.Event()
        self.thread = None
        self.pending = set()
        self.cancelled = set()
        self.progress = {}
        self.next_scan = {}

    def start(self):
        self.thread = threading.Thread(target=self._loop, name='document-discovery', daemon=True)
        self.thread.start()

    def stop(self):
        self.wake.set()
        if self.thread:
            self.thread.join()

    def request(self, key):
        with self.lock:
            with self.desktop.lib() as lib:
                if not lib.db.execute('SELECT 1 FROM watched_sources WHERE id=?', (key,)).fetchone():
                    raise ValueError('Connected folder no longer exists.')
                with lib.db:
                    lib.db.execute("UPDATE watched_sources SET state='waiting' WHERE id=?", (key,))
            self.pending.add(key)
        self.wake.set()

    def add(self, path, ocr=False, *, computer=False, excluded_paths=()):
        raw = Path(path).expanduser()
        if not raw.is_absolute():
            raise ValueError('Choose a folder or enter its full absolute path.')
        path = raw.resolve(strict=True)
        if not path.is_dir():
            raise ValueError('Choose an existing folder.')
        if path.is_relative_to(self.desktop.root):
            raise ValueError('Choose your original documents, outside the app’s managed library.')
        with self.lock, self.desktop.lib() as lib:
            nested = []
            for row in lib.db.execute('SELECT id,path FROM watched_sources'):
                other = Path(row['path'])
                if path == other:
                    raise ValueError('This folder is already connected.')
                if other.is_relative_to(path):
                    raise ValueError('This folder contains an existing connection. Connect the narrower folder instead.')
                if path.is_relative_to(other):
                    nested.append(row)
            name = path.name or str(path)
            folder_name = name[:128]
            existing = {f['name'].casefold() for f in lib.folders()}
            i = 2
            while folder_name.casefold() in existing:
                suffix = f' · connected {i}'
                folder_name = name[:128-len(suffix)] + suffix
                i += 1
            folder = lib.create_folder(folder_name[:128])
            key = uuid.uuid4().hex
            with lib.db:
                lib.db.execute('''INSERT INTO watched_sources
                    (id,path,name,folder_id,ocr,created_at) VALUES(?,?,?,?,?,?)''',
                    (key, str(path), name, folder['id'], int(ocr), now()))
                lib.db.execute('INSERT OR REPLACE INTO workspace_settings VALUES(?,?)',
                    ('source_options:' + key, json.dumps(dict(computer=computer, excluded_paths=list(excluded_paths), interval_seconds=3600 if computer else INTERVAL))))
                # A narrower connection owns its subtree: exclude it from broader
                # scans so the same files are not discovered and indexed twice.
                for parent in nested:
                    options_row = lib.db.execute('SELECT value FROM workspace_settings WHERE key=?', ('source_options:' + parent['id'],)).fetchone()
                    options = json.loads(options_row[0]) if options_row else {}
                    options['excluded_paths'] = [p for p in options.get('excluded_paths', []) if Path(p) != path] + [str(path)]
                    lib.db.execute('INSERT OR REPLACE INTO workspace_settings VALUES(?,?)',
                        ('source_options:' + parent['id'], json.dumps(options)))
                    relative = str(path.relative_to(parent['path']))
                    lib.db.execute('''DELETE FROM watched_files WHERE source_id=? AND task_id IS NULL
                        AND (relative_path=? OR relative_path LIKE ?)''',
                        (parent['id'], relative, relative + os.sep + '%'))
            self.pending.add(key)
        self.wake.set()
        return dict(id=key, folder_id=folder['id'])

    def change(self, key, *, enabled=None, disconnect=False):
        # Signal before waiting for the scan lock, so a long walk stops promptly.
        if disconnect or not enabled:
            self.cancelled.add(key)
        with self.lock, self.desktop.lib() as lib:
            source = lib.db.execute('SELECT path FROM watched_sources WHERE id=?', (key,)).fetchone()
            if not source:
                raise ValueError('Connected folder no longer exists.')
            with lib.db:
                if disconnect:
                    removed = Path(source['path'])
                    for row in lib.db.execute('SELECT id FROM watched_sources WHERE id<>?', (key,)).fetchall():
                        options_row = lib.db.execute('SELECT value FROM workspace_settings WHERE key=?', ('source_options:' + row['id'],)).fetchone()
                        if not options_row:
                            continue
                        options = json.loads(options_row[0])
                        excluded = [p for p in options.get('excluded_paths', []) if Path(p) != removed]
                        if excluded != options.get('excluded_paths', []):
                            options['excluded_paths'] = excluded
                            lib.db.execute('INSERT OR REPLACE INTO workspace_settings VALUES(?,?)',
                                ('source_options:' + row['id'], json.dumps(options)))
                    lib.db.execute('DELETE FROM watched_sources WHERE id=?', (key,))
                    lib.db.execute('DELETE FROM workspace_settings WHERE key=?', ('source_options:' + key,))
                    lib.db.execute('DELETE FROM workspace_settings WHERE key=?', ('scan_run:' + key,))
                    self.pending.discard(key)
                else:
                    lib.db.execute('UPDATE watched_sources SET enabled=? WHERE id=?', (int(enabled), key))
                    if enabled:
                        self.cancelled.discard(key)
                        self.pending.add(key)
        self.wake.set()
        return dict(disconnected=disconnect)

    def retry(self, key):
        with self.lock, self.desktop.lib() as lib:
            with lib.db:
                lib.db.execute("UPDATE watched_files SET state='discovered',task_id=NULL,error=NULL WHERE source_id=? AND state='failed'", (key,))
        self.request(key)

    def _loop(self):
        while not self.desktop.closing.is_set():
            try:
                with self.lock:
                    with self.desktop.lib() as lib:
                        keys = [r[0] for r in lib.db.execute('SELECT id FROM watched_sources WHERE enabled=1')]
                        intervals = {}
                        for key in keys:
                            row = lib.db.execute('SELECT value FROM workspace_settings WHERE key=?', ('source_options:' + key,)).fetchone()
                            intervals[key] = json.loads(row[0]).get('interval_seconds', INTERVAL) if row else INTERVAL
                    due = [k for k in keys if k in self.pending or time.monotonic() >= self.next_scan.get(k, 0)]
                    self.pending.difference_update(due)
                for key in due:
                    if self.desktop.closing.is_set():
                        break
                    self.scan(key)
                    self.next_scan[key] = time.monotonic() + intervals.get(key, INTERVAL)
                self.reconcile()
                self.queue_pending()
            except Exception as exc:
                # Keep discovery alive after transient disk/SQLite failures.
                import logging
                logging.getLogger(__name__).exception('Folder discovery failed: %s', exc)
            self.wake.wait(3)
            self.wake.clear()

    def scan(self, key):
        with self.lock, self.desktop.lib() as lib:
            row = lib.db.execute('SELECT * FROM watched_sources WHERE id=? AND enabled=1', (key,)).fetchone()
            if not row:
                return
            root = Path(row['path'])
            options_row = lib.db.execute('SELECT value FROM workspace_settings WHERE key=?', ('source_options:' + key,)).fetchone()
            options = json.loads(options_row[0]) if options_row else {}
            excluded = [Path(p).resolve() for p in options.get('excluded_paths', [])]
            skips = SKIP_DIRS | ({'windows', 'program files', 'program files (x86)', 'programdata', 'appdata', '.cache', 'perflogs'} if options.get('computer') else set())
            saved_run = lib.db.execute('SELECT value FROM workspace_settings WHERE key=?', ('scan_run:' + key,)).fetchone()
            run = json.loads(saved_run[0]) if saved_run else {}
            if not run.get('started_at') or run.get('finished_at'):
                run = dict(started_at=now(), discovery_finished_at=None, finished_at=None)
            run['discovery_finished_at'] = None
            run.update(skipped_count=0, skipped_paths=[])
            def save_run():
                with lib.db:
                    lib.db.execute('INSERT OR REPLACE INTO workspace_settings VALUES(?,?)', ('scan_run:' + key, json.dumps(run)))
            def skipped(error):
                run['skipped_count'] += 1
                if len(run['skipped_paths']) < 10:
                    run['skipped_paths'].append(str(getattr(error, 'filename', '') or error))
            save_run()
            with lib.db:
                lib.db.execute("UPDATE watched_sources SET state='scanning',error=NULL WHERE id=?", (key,))
            errors, seen = [], set()
            limited = False
            folders = 0
            last_publish = 0
            try:
                if not root.is_dir():
                    raise ValueError('Folder is unavailable. Reconnect its drive or resume after restoring access.')
                def onerror(error):
                    if isinstance(error, PermissionError) or getattr(error, 'winerror', None) == 5:
                        skipped(error)
                    else:
                        errors.append(str(error))
                for directory, dirs, files in os.walk(root, followlinks=False, onerror=onerror):
                    if self.desktop.closing.is_set() or key in self.cancelled:
                        return
                    base = Path(directory)
                    folders += 1
                    self.progress[key] = dict(folders_scanned=folders, files_found=len(seen), current_path=str(base))
                    allowed = []
                    for d in dirs:
                        if d.casefold() in skips:
                            continue
                        try:
                            child = base / d
                            resolved = child.resolve()
                            if not linked(child) and not resolved.is_relative_to(self.desktop.root) and not any(resolved.is_relative_to(p) for p in excluded):
                                allowed.append(d)
                        except PermissionError as exc:
                            skipped(exc)
                        except OSError as exc:
                            onerror(exc)
                    dirs[:] = sorted(allowed)
                    if time.monotonic() - last_publish > 2:
                        self.reconcile()
                        self.queue_pending()
                        save_run()
                        last_publish = time.monotonic()
                    for name in sorted(files):
                        if Path(name).suffix.lower() not in NATIVE_EXTENSIONS|{'.pdf'}:
                            continue
                        path = base / name
                        try:
                            if self.desktop.closing.is_set() or key in self.cancelled:
                                return
                            if linked(path) or not path.resolve().is_relative_to(root):
                                continue
                            if any(path.resolve().is_relative_to(p) for p in excluded):
                                continue
                            stat = path.stat()
                            rel = str(path.relative_to(root))
                            signature = f'{stat.st_size}:{stat.st_mtime_ns}'
                            seen.add(rel)
                            with lib.db:
                                old = lib.db.execute('SELECT * FROM watched_files WHERE source_id=? AND relative_path=?', (key, rel)).fetchone()
                                if old is None:
                                    lib.db.execute('INSERT INTO watched_files(source_id,relative_path,signature) VALUES(?,?,?)', (key, rel, signature))
                                elif old['signature'] != signature:
                                    lib.db.execute("UPDATE watched_files SET signature=?,state=CASE WHEN task_id IS NULL THEN 'discovered' ELSE state END,error=NULL WHERE source_id=? AND relative_path=?", (signature, key, rel))
                                elif old['state'] == 'missing':
                                    lib.db.execute("UPDATE watched_files SET state=CASE WHEN indexed_signature=signature THEN 'indexed' ELSE 'discovered' END WHERE source_id=? AND relative_path=?", (key, rel))
                        except OSError as exc:
                            onerror(exc)
                        if len(seen) % 100 == 0:
                            self.reconcile()
                            self.queue_pending()
                        if not options.get('computer') and len(seen) >= MAX_FILES:
                            limited = True
                            break
                    if limited:
                        break
                if limited:
                    errors.append(f'This prototype scans up to {MAX_FILES:,} supported documents per connection. Connect smaller folders to cover the remainder.')
                if not errors and not run['skipped_count']:
                    with lib.db:
                        for f in lib.db.execute('SELECT relative_path FROM watched_files WHERE source_id=?', (key,)).fetchall():
                            if f['relative_path'] not in seen:
                                lib.db.execute("UPDATE watched_files SET state='missing' WHERE source_id=? AND relative_path=?", (key, f['relative_path']))
                with lib.db:
                    lib.db.execute("UPDATE watched_sources SET state=?,last_scan=?,error=? WHERE id=?",
                        ('attention' if errors else 'watching', now(), '\n'.join(errors[:10]) or None, key))
                run['discovery_finished_at'] = now()
                save_run()
            except (OSError, ValueError) as exc:
                with lib.db:
                    lib.db.execute("UPDATE watched_sources SET state='unavailable',last_scan=?,error=? WHERE id=?", (now(), str(exc), key))
                run['discovery_finished_at'] = now()
                run['finished_at'] = now()
                save_run()

    def reconcile(self):
        with self.lock, self.desktop.lib() as lib:
            with lib.db:
                lib.db.execute("""UPDATE watched_files SET state='excluded' WHERE state='indexed'
                    AND document_id IS NOT NULL AND document_id NOT IN (SELECT id FROM documents)""")
                lib.db.execute("""UPDATE watched_files SET state='indexed' WHERE state='excluded'
                    AND document_id IN (SELECT id FROM documents) AND indexed_signature=signature""")
            rows = lib.db.execute('''SELECT f.*,t.status task_status,t.result,t.error task_error
                FROM watched_files f JOIN app_tasks t ON t.id=f.task_id''').fetchall()
            with lib.db:
                for row in rows:
                    if row['task_status'] in ('queued', 'running', 'skipping'):
                        continue
                    if row['task_status']=='skipped':
                        lib.db.execute("UPDATE watched_files SET state=CASE WHEN signature=queued_signature THEN 'skipped' ELSE 'discovered' END,task_id=NULL,queued_signature=NULL,error=NULL WHERE source_id=? AND relative_path=?",(row['source_id'],row['relative_path']))
                        continue
                    if row['task_status'] == 'completed':
                        doc = json.loads(row['result'])['document']
                        state = 'indexed' if row['signature'] == row['queued_signature'] else 'discovered'
                        if row['state'] == 'missing':
                            state = 'missing'
                        lib.db.execute('''UPDATE watched_files SET document_id=?,indexed_signature=?,task_id=NULL,state=?,error=NULL
                            WHERE source_id=? AND relative_path=?''',
                            (doc['id'], row['queued_signature'], state, row['source_id'], row['relative_path']))
                    elif row['task_status'] == 'interrupted' or (row['task_error'] or '').startswith('InterruptedError:'):
                        lib.db.execute("UPDATE watched_files SET state='discovered',task_id=NULL,error=NULL WHERE source_id=? AND relative_path=?",
                            (row['source_id'], row['relative_path']))
                    else:
                        lib.db.execute("UPDATE watched_files SET state='failed',task_id=NULL,error=? WHERE source_id=? AND relative_path=?",
                            (row['task_error'], row['source_id'], row['relative_path']))
            for source in lib.db.execute('SELECT id FROM watched_sources').fetchall():
                saved = lib.db.execute('SELECT value FROM workspace_settings WHERE key=?', ('scan_run:' + source['id'],)).fetchone()
                if not saved:
                    continue
                run = json.loads(saved[0])
                if run.get('discovery_finished_at') and not run.get('finished_at') and not lib.db.execute(
                        "SELECT 1 FROM watched_files WHERE source_id=? AND state IN ('discovered','queued') LIMIT 1", (source['id'],)).fetchone():
                    run['finished_at'] = now()
                    with lib.db:
                        lib.db.execute('UPDATE workspace_settings SET value=? WHERE key=?', (json.dumps(run), 'scan_run:' + source['id']))

    def queue_pending(self):
        with self.lock, self.desktop.lib() as lib:
            capacity = max(0, 12 - lib.db.execute("SELECT count(*) FROM app_tasks WHERE status IN ('queued','running','skipping')").fetchone()[0])
            rows = lib.db.execute('''SELECT f.*,s.path,s.folder_id,s.ocr FROM watched_files f
                JOIN watched_sources s ON s.id=f.source_id WHERE s.enabled=1 AND s.state IN ('watching','attention','scanning')
                AND f.state='discovered' AND f.task_id IS NULL
                ORDER BY length(s.path) DESC,s.created_at,f.relative_path LIMIT ?''', (capacity,)).fetchall()
            for row in rows:
                if self.desktop.closing.is_set():
                    return
                if row['source_id'] in self.cancelled:
                    continue
                path = Path(row['path']) / row['relative_path']
                doc = lib.db.execute('SELECT id,folder_id FROM documents WHERE id=?', (row['document_id'],)).fetchone()
                # A manual removal stays removed until its source changes.
                if row['indexed_signature'] == row['signature'] and not doc:
                    with lib.db:
                        lib.db.execute("UPDATE watched_files SET state='excluded' WHERE source_id=? AND relative_path=?", (row['source_id'], row['relative_path']))
                    continue
                shared = doc and lib.db.execute('SELECT count(*) FROM watched_files WHERE document_id=?', (doc['id'],)).fetchone()[0] > 1
                try:
                    if not path.is_file() or linked(path) or not path.resolve().is_relative_to(Path(row['path'])):
                        raise ValueError('Source is missing or now points outside the connected folder.')
                    # Register before submission so the worker knows not to infer a replacement by filename/path.
                    task = self.desktop.queue(doc['folder_id'] if doc else row['folder_id'], path, path.name,
                        document_id=doc['id'] if doc and not shared else None, ocr=bool(row['ocr']),
                        discovered=(row['source_id'], row['relative_path'], row['signature']))
                except (OSError, ValueError) as exc:
                    with lib.db:
                        lib.db.execute("UPDATE watched_files SET state='failed',error=? WHERE source_id=? AND relative_path=?", (str(exc), row['source_id'], row['relative_path']))
