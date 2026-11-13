"""SQLite metadata plus persisted float32 vectors; bounded exact cosine search.

Index each PDF into a private staging database. Commit its new pages/vectors in
one transaction only after extraction and inference finish. Existing versions
remain searchable after failed or interrupted replacement attempts.
"""
from __future__ import annotations
from collections import Counter
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import time
import uuid
from functools import lru_cache

import numpy as np
import psutil

from .chunking import ChunkingConfig, chunk_page
from .embedding import EmbeddingGemma
from .pdf import EXTRACTION_VERSION, PdfOptions, extract_page, native_text, open_pdf
from .text_documents import TEXT_EXTENSIONS, SPREADSHEET_EXTENSIONS, source_info, open_text_document, EXTRACTION_VERSION as TEXT_EXTRACTION_VERSION


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


@lru_cache(maxsize=128)
def source_digest(path,size,mtime,ctime):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def packed(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def memory_observation(start):
    info=psutil.Process().memory_info()
    return dict(process_rss_start_bytes=start,process_rss_end_bytes=info.rss,
        process_historical_peak_rss_bytes=getattr(info,'peak_wset',None),platform=os.name,
        scope='Observed desktop process, including shared concurrent activity; not a hard allocation or Android budget')


class Library:
    def __init__(self, root, embedder=None):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        for name in ("files", "staging"):
            (self.root / name).mkdir(exist_ok=True)
        self.embedder = embedder or EmbeddingGemma()
        self.db = sqlite3.connect(self.root / "library.sqlite3", timeout=15)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self._schema()
        self._recover_jobs()

    def close(self):
        self.db.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def _schema(self):
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS folders(id TEXT PRIMARY KEY, name TEXT NOT NULL COLLATE NOCASE UNIQUE,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS documents(
            id TEXT PRIMARY KEY, folder_id TEXT NOT NULL REFERENCES folders(id) ON DELETE RESTRICT,
            filename TEXT NOT NULL, title TEXT NOT NULL, original_path TEXT NOT NULL,
            managed_path TEXT NOT NULL, sha256 TEXT NOT NULL, size_bytes INTEGER NOT NULL,
            page_count INTEGER NOT NULL, chunk_count INTEGER NOT NULL, status TEXT NOT NULL,
            recipe TEXT NOT NULL, embedding_profile TEXT, created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1, UNIQUE(folder_id,sha256));
        CREATE INDEX IF NOT EXISTS documents_folder ON documents(folder_id);
        CREATE INDEX IF NOT EXISTS documents_browse_updated ON documents(updated_at DESC,id);
        CREATE INDEX IF NOT EXISTS documents_browse_added ON documents(created_at,id);
        CREATE INDEX IF NOT EXISTS documents_browse_size ON documents(size_bytes,id);
        CREATE INDEX IF NOT EXISTS documents_browse_folder_added ON documents(folder_id,created_at,id);
        CREATE TABLE IF NOT EXISTS document_sources(document_id TEXT PRIMARY KEY REFERENCES documents(id) ON DELETE CASCADE,
            original_name TEXT NOT NULL,source_path TEXT NOT NULL,source_sha256 TEXT NOT NULL,format TEXT NOT NULL,
            slides INTEGER NOT NULL,converter TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS pages(
            document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
            page_number INTEGER NOT NULL CHECK(page_number>=1), page_label TEXT NOT NULL,
            text TEXT NOT NULL, method TEXT NOT NULL, status TEXT NOT NULL, warnings TEXT NOT NULL,
            ocr_confidence REAL, PRIMARY KEY(document_id,page_number));
        CREATE TABLE IF NOT EXISTS chunks(
            id INTEGER PRIMARY KEY, document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
            page_number INTEGER NOT NULL, chunk_index INTEGER NOT NULL, title TEXT NOT NULL,
            text TEXT NOT NULL, char_start INTEGER NOT NULL, char_end INTEGER NOT NULL,
            token_count INTEGER NOT NULL, model_id TEXT NOT NULL, model_revision TEXT NOT NULL,
            model_configuration TEXT NOT NULL, dimensions INTEGER NOT NULL,
            vector BLOB NOT NULL CHECK(length(vector)=dimensions*4), vector_sha256 TEXT NOT NULL,
            UNIQUE(document_id,chunk_index), FOREIGN KEY(document_id,page_number)
                REFERENCES pages(document_id,page_number) ON DELETE CASCADE);
        CREATE INDEX IF NOT EXISTS chunks_document ON chunks(document_id,page_number);
        CREATE INDEX IF NOT EXISTS chunks_embedding_title ON chunks(title);
        CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(text,title,content='chunks',content_rowid='id');
        CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN
            INSERT INTO chunks_fts(rowid,text,title) VALUES(new.id,new.text,new.title); END;
        CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN
            INSERT INTO chunks_fts(chunks_fts,rowid,text,title) VALUES('delete',old.id,old.text,old.title); END;
        CREATE TABLE IF NOT EXISTS index_attempts(
            id TEXT PRIMARY KEY, document_id TEXT, folder_id TEXT NOT NULL, original_path TEXT NOT NULL,
            status TEXT NOT NULL, started_at TEXT NOT NULL, finished_at TEXT, owner_pid INTEGER NOT NULL,
            owner_created REAL NOT NULL, error TEXT, details TEXT);
        """)
        version = self.db.execute("SELECT value FROM settings WHERE key='schema_version'").fetchone()
        if 'source_mode' not in {r[1] for r in self.db.execute('PRAGMA table_info(documents)')}:
            with self.db:self.db.execute("ALTER TABLE documents ADD COLUMN source_mode TEXT NOT NULL DEFAULT 'managed'")
        if version and version[0] != "1":
            raise ValueError("Unsupported library schema version")
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO settings VALUES('schema_version','1')")
        # Additive lexical index migration; existing model vectors are untouched.
        self.db.executescript("""
        CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts_stemmed USING fts5(
            text,title,content='chunks',content_rowid='id',tokenize='porter unicode61');
        CREATE TRIGGER IF NOT EXISTS chunks_stem_ai AFTER INSERT ON chunks BEGIN
            INSERT INTO chunks_fts_stemmed(rowid,text,title) VALUES(new.id,new.text,new.title); END;
        CREATE TRIGGER IF NOT EXISTS chunks_stem_ad AFTER DELETE ON chunks BEGIN
            INSERT INTO chunks_fts_stemmed(chunks_fts_stemmed,rowid,text,title)
                VALUES('delete',old.id,old.text,old.title); END;
        """)
        stemmed = self.db.execute("SELECT 1 FROM settings WHERE key='stemmed_fts_version' AND value='1'").fetchone()
        if not stemmed:
            with self.db:
                self.db.execute("BEGIN IMMEDIATE")
                self.db.execute("INSERT INTO chunks_fts_stemmed(chunks_fts_stemmed) VALUES('rebuild')")
                self.db.execute("INSERT OR REPLACE INTO settings VALUES('stemmed_fts_version','1')")
        if 'color' not in {row['name'] for row in self.db.execute('PRAGMA table_info(folders)')}:
            with self.db:
                self.db.execute("ALTER TABLE folders ADD COLUMN color TEXT NOT NULL DEFAULT '#A78BFA'")
        if 'evidence' not in {r['name'] for r in self.db.execute('PRAGMA table_info(pages)')}:
            with self.db:self.db.execute("ALTER TABLE pages ADD COLUMN evidence TEXT NOT NULL DEFAULT '{}'")
        self.db.execute('CREATE INDEX IF NOT EXISTS chunks_input_lookup ON chunks(title,model_id,model_revision,model_configuration,dimensions)')
        from .bills import initialize
        initialize(self.db)

    def _recover_jobs(self):
        for job in self.db.execute("SELECT id,owner_pid,owner_created FROM index_attempts WHERE status='indexing'").fetchall():
            try:
                alive = abs(psutil.Process(job["owner_pid"]).create_time() - job["owner_created"]) < .01
            except psutil.NoSuchProcess:
                alive = False
            except psutil.AccessDenied:
                continue
            if not alive:
                with self.db:
                    self.db.execute("UPDATE index_attempts SET status='interrupted',finished_at=?,error=? WHERE id=? AND status='indexing'",
                                    (now(), "Indexing process ended before atomic commit; prior indexed version retained", job["id"]))

    def _folder(self, folder_id):
        row = self.db.execute("SELECT * FROM folders WHERE id=?", (folder_id,)).fetchone()
        if row is None:
            raise ValueError(f"Folder not found: {folder_id}")
        return row

    def document(self, document_id):
        row = self.db.execute("SELECT * FROM documents WHERE id=?", (document_id,)).fetchone()
        if row is None:
            raise ValueError(f"Document not found: {document_id}")
        result = dict(row)
        result.update(source_info(result))
        return result

    @staticmethod
    def _name(name):
        name = name.strip()
        if not name or len(name) > 128 or any(ord(c) < 32 for c in name):
            raise ValueError("Folder name must contain 1–128 printable characters")
        return name

    def create_folder(self, name, color="#A78BFA"):
        name = self._name(name)
        color = self._color(color)
        folder_id = uuid.uuid4().hex
        with self.db:
            self.db.execute("INSERT INTO folders(id,name,created_at,updated_at,color) VALUES(?,?,?,?,?)", (folder_id, name, now(), now(),color))
        return dict(self._folder(folder_id))

    @staticmethod
    def _color(color):
        if not re.fullmatch(r'#[0-9A-Fa-f]{6}',color):
            raise ValueError('Folder color must be a six-digit hex color')
        return color

    def color_folder(self,folder_id,color):
        self._folder(folder_id)
        with self.db:
            self.db.execute('UPDATE folders SET color=?,updated_at=? WHERE id=?',(self._color(color),now(),folder_id))
        return dict(self._folder(folder_id))

    def rename_folder(self, folder_id, name):
        self._folder(folder_id)
        with self.db:
            self.db.execute("UPDATE folders SET name=?,updated_at=? WHERE id=?", (self._name(name), now(), folder_id))
        return dict(self._folder(folder_id))

    def folders(self):
        return [dict(row) for row in self.db.execute("""SELECT f.*,count(d.id) document_count
            FROM folders f LEFT JOIN documents d ON d.folder_id=f.id GROUP BY f.id ORDER BY f.name COLLATE NOCASE""")]

    def delete_folder(self, folder_id):
        self._folder(folder_id)
        if self.db.execute("SELECT 1 FROM documents WHERE folder_id=?", (folder_id,)).fetchone():
            raise ValueError("Folder contains documents; move or remove them explicitly before deleting it")
        with self.db:
            self.db.execute("DELETE FROM folders WHERE id=?", (folder_id,))
        return {"deleted_folder": folder_id}

    def documents(self, folder_id=None):
        if folder_id:
            self._folder(folder_id)
        sql = "SELECT d.*,f.name folder_name FROM documents d JOIN folders f ON f.id=d.folder_id"
        rows = self.db.execute(sql + (" WHERE d.folder_id=?" if folder_id else "") + " ORDER BY d.updated_at DESC,d.id",
                               (folder_id,) if folder_id else ())
        return [dict(row, **source_info(dict(row))) for row in rows]

    def move_document(self, document_id, folder_id):
        self._folder(folder_id)
        doc = self.document(document_id)
        with self.db:
            self.db.execute("UPDATE documents SET folder_id=?,updated_at=?,version=version+1 WHERE id=?",
                            (folder_id, now(), document_id))
            self.db.execute("UPDATE folders SET updated_at=? WHERE id IN (?,?)", (now(), folder_id, doc["folder_id"]))
        return self.document(document_id)

    def remove_document(self, document_id):
        doc = self.document(document_id)
        with self.db:
            self.db.execute("DELETE FROM documents WHERE id=?", (document_id,))
            self.db.execute("UPDATE folders SET updated_at=? WHERE id=?", (now(), doc["folder_id"]))
        return {"removed_document": document_id, "source_copy_retained": True,
                "note": "Metadata, pages and vectors removed; original and managed PDF bytes are retained"}

    def _copy_snapshot(self, source, target):
        before = source.stat()
        if shutil.disk_usage(self.root).free < before.st_size + 32 * 1024 * 1024:
            raise OSError("Insufficient free storage for source snapshot plus indexing reserve")
        checksum = hashlib.sha256()
        with source.open("rb") as src, target.open("xb") as dst:
            while block := src.read(1024 * 1024):
                dst.write(block)
                checksum.update(block)
            dst.flush()
            os.fsync(dst.fileno())
        after = source.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise ValueError("Source changed while being copied; retry indexing a stable file")
        return checksum.hexdigest(), before.st_size

    def _profile(self):
        self.embedder.load()
        return {**self.embedder.signature, "dtype": self.embedder.dtype}

    def _check_profile(self, profile):
        row = self.db.execute("SELECT value FROM settings WHERE key='embedding_profile'").fetchone()
        if row and json.loads(row[0]) != profile:
            raise ValueError("Embedding configuration differs from this library. Use its original dimensions/precision or create a separate library.")

    def import_pdf(self, source, folder_id, *, document_id=None, title=None, chunking=None, pdf_options=None, progress=None, match_original=True, retain_source=True):
        if Path(source).suffix.lower() != '.pdf':
            raise ValueError("Import requires an existing .pdf file")
        return self.import_document(source, folder_id, document_id=document_id, title=title, chunking=chunking,
            pdf_options=pdf_options, progress=progress, match_original=match_original, retain_source=retain_source)

    def import_document(self, source, folder_id, *, document_id=None, title=None, chunking=None, pdf_options=None, progress=None, match_original=True, retain_source=True, publish_partial=True):
        self._folder(folder_id)
        source = Path(source).expanduser().resolve(strict=True)
        extension = source.suffix.lower()
        is_text = extension in TEXT_EXTENSIONS | SPREADSHEET_EXTENSIONS
        if not source.is_file() or extension not in TEXT_EXTENSIONS | SPREADSHEET_EXTENSIONS | {".pdf"}:
            raise ValueError("Import requires a supported document file")
        chunking, pdf_options = chunking or ChunkingConfig(), pdf_options or PdfOptions()
        old = self.document(document_id) if document_id else None
        if old is not None and old["folder_id"] != folder_id:
            raise ValueError("Replacement folder must match the current document folder; use move separately")
        if old is None and match_original:
            row = self.db.execute("SELECT * FROM documents WHERE folder_id=? AND original_path=?", (folder_id, str(source))).fetchone()
            old = dict(row) if row else None
        job_id = uuid.uuid4().hex
        with self.db:
            self.db.execute("INSERT INTO index_attempts(id,document_id,folder_id,original_path,status,started_at,owner_pid,owner_created) VALUES(?,?,?,?,?,?,?,?)",
                            (job_id, old["id"] if old else None, folder_id, str(source), "indexing", now(), os.getpid(), psutil.Process().create_time()))
        incoming, stage_path = (self.root / "staging" / f"{job_id}{suffix}" for suffix in (extension, ".sqlite3"))
        incoming_directory = None
        if is_text and retain_source:
            incoming_directory=self.root/"staging"/job_id
            incoming_directory.mkdir()
            incoming=incoming_directory/source.name
        begin = time.perf_counter()
        memory_start=psutil.Process().memory_info().rss
        stats_before = dict(self.embedder.stats)
        try:
            before=source.stat()
            if retain_source:
                sha256, size = self._copy_snapshot(source, incoming)
            else:
                if shutil.disk_usage(self.root).free<32*1024*1024:raise OSError('Insufficient free storage for indexing reserve')
                with source.open('rb') as stream:sha256=hashlib.file_digest(stream,'sha256').hexdigest()
                size=before.st_size
            prepared = None
            opener = open_text_document if is_text else open_pdf
            with opener(incoming if retain_source else source) as pdf:
                selected_title = (title or pdf.metadata.get("title") or source.stem).strip()
                recipe = {"chunking": chunking.to_dict(), "pdf": pdf_options.to_dict(), "extraction": EXTRACTION_VERSION,
                          "embedding": self.embedder.signature, "title": selected_title}
                if is_text:
                    recipe.pop("pdf")
                    recipe.update(source_kind="spreadsheet" if extension in SPREADSHEET_EXTENSIONS else "text",
                        source_format=extension.lstrip("."), extractor_version=TEXT_EXTRACTION_VERSION)
                if is_text:recipe["extraction"]=TEXT_EXTRACTION_VERSION
                if old and old['status']=='indexed' and old["sha256"] == sha256 and old["recipe"] == packed(recipe):
                    result = {"action": "unchanged", "document": old, "document_embeddings_generated": 0}
                else:
                    duplicate = self.db.execute("SELECT * FROM documents WHERE folder_id=? AND sha256=? AND id!=?",
                                                (folder_id, sha256, old["id"] if old else "")).fetchone()
                    if duplicate:
                        if old:
                            raise ValueError(f"Replacement duplicates document {duplicate['id']}; existing documents retained")
                        result = {"action": "duplicate", "document": dict(duplicate), "document_embeddings_generated": 0}
                    else:
                        reusable = self.db.execute("SELECT * FROM documents WHERE sha256=? AND recipe=? AND id!=? AND status='indexed'",
                                                  (sha256, packed(recipe), old["id"] if old else "")).fetchone()
                        if reusable:
                            self._clone_stage(stage_path, reusable["id"])
                            profile = json.loads(reusable["embedding_profile"]) if reusable["embedding_profile"] else None
                        else:
                            doc_id = old["id"] if old else uuid.uuid4().hex
                            blob = self.root / "files" / f"{sha256}{extension}"
                            doc = {"id": doc_id, "folder_id": folder_id, "filename": source.name,
                                   "title": selected_title, "original_path": str(source),
                                   "managed_path": str(blob.relative_to(self.root)), "sha256": sha256,
                                   "source_mode": 'managed' if retain_source else 'reference',
                                   "size_bytes": size, "page_count": pdf.page_count, "recipe": packed(recipe),
                                   "embedding_profile": None,
                                   "created_at": old["created_at"] if old else now(), "updated_at": now(),
                                   "version": old["version"] + 1 if old else 1}
                            def handle_tier1(stage_p, prof, count):
                                if retain_source and not blob.exists():
                                    shutil.copy2(incoming, blob)
                                doc_copy = dict(doc)
                                doc_copy["embedding_profile"] = packed(prof) if prof else None
                                self._commit_tier1(stage_p, doc_copy, prof, job_id=job_id)
                            profile = self._build_stage(stage_path, pdf, selected_title, chunking, pdf_options, progress, on_tier1=None if is_text or not publish_partial else handle_tier1)
                            doc["embedding_profile"] = packed(profile) if profile else None
                        if not reusable:
                            prepared = blob, doc, profile, False
                        else:
                            doc_id = old["id"] if old else uuid.uuid4().hex
                            blob = self.root / "files" / f"{sha256}{extension}"
                            doc = {"id": doc_id, "folder_id": folder_id, "filename": source.name,
                                   "title": selected_title, "original_path": str(source),
                                   "managed_path": str(blob.relative_to(self.root)), "sha256": sha256,
                                   "source_mode": 'managed' if retain_source else 'reference',
                                   "size_bytes": size, "page_count": pdf.page_count, "recipe": packed(recipe),
                                   "embedding_profile": packed(profile) if profile else None,
                                   "created_at": old["created_at"] if old else now(), "updated_at": now(),
                                   "version": old["version"] + 1 if old else 1}
                            prepared = blob, doc, profile, True
            if not retain_source:
                after=source.stat()
                if (before.st_size,before.st_mtime_ns,before.st_ctime_ns)!=(after.st_size,after.st_mtime_ns,after.st_ctime_ns):
                    raise ValueError('Source changed during indexing; prior index retained. Retry after saving the PDF.')
            # PyMuPDF must release the PDF handle before Windows can rename it.
            if prepared:
                if progress:progress(dict(stage='committing',page=prepared[1]['page_count'],total_pages=prepared[1]['page_count'],chunks=0))
                blob, doc, profile, reused = prepared
                if blob.resolve().parent != (self.root / "files").resolve() or incoming.resolve().parent != (incoming_directory or self.root / "staging").resolve():
                    raise ValueError("Managed file path escaped the library")
                if not retain_source:
                    doc['managed_path']=str(source)
                elif not blob.exists():
                    incoming.replace(blob)
                else:
                    try:incoming.unlink(missing_ok=True)
                    except OSError:pass
                details = {"action": "updated" if old else "added", "reused_embeddings": reused,
                           "document_embeddings_generated": self.embedder.stats["document_texts_encoded"] - stats_before["document_texts_encoded"],
                           "reused_chunk_embeddings":reusable['chunk_count'] if reused else getattr(self,'_reused_chunk_embeddings',0),
                           "resource_profile":memory_observation(memory_start)}
                self._commit_staged(stage_path, doc, old, profile, job_id=job_id, details=details)
                result = {"action": "updated" if old else "added", "document": self.document(doc["id"]),
                          "reused_embeddings": reused,
                          "reused_chunk_embeddings":details['reused_chunk_embeddings'],
                          "resource_profile":details['resource_profile'],
                          "document_embeddings_generated": self.embedder.stats["document_texts_encoded"] - stats_before["document_texts_encoded"]}
            result["elapsed_s"] = time.perf_counter() - begin
            result.setdefault('resource_profile',memory_observation(memory_start))
            if prepared is None:
                with self.db:
                    self.db.execute("UPDATE index_attempts SET status='completed',finished_at=?,document_id=?,details=? WHERE id=?",
                                    (now(), result["document"]["id"], packed({k:v for k,v in result.items() if k != "document"}), job_id))
            result["job_id"] = job_id
            result["document"].update(source_info(result["document"]))
            return result
        except BaseException as exc:
            try:
                with self.db:
                    self.db.execute("UPDATE index_attempts SET status=?,finished_at=?,error=? WHERE id=? AND status='indexing'",
                                    ("interrupted" if isinstance(exc, (KeyboardInterrupt, SystemExit)) else "failed", now(), f"{type(exc).__name__}: {exc}", job_id))
            except sqlite3.Error:
                # Original source and prior committed index are untouched even if disk-full prevents logging.
                pass
            raise
        finally:
            cleanup_warnings = []
            for temporary in (incoming, stage_path):
                try:
                    temporary.unlink(missing_ok=True)
                except OSError as exc:
                    # A native parser exception may retain a Windows file handle
                    # in its traceback. Keep the original import error, record the
                    # leftover stage path, and never delete a source or good index.
                    cleanup_warnings.append({"path": str(temporary), "error": str(exc)})
            if incoming_directory:
                try:incoming_directory.rmdir()
                except OSError:pass
            if cleanup_warnings:
                try:
                    row = self.db.execute("SELECT details FROM index_attempts WHERE id=?", (job_id,)).fetchone()
                    details = json.loads(row[0]) if row and row[0] else {}
                    details["cleanup_warnings"] = cleanup_warnings
                    with self.db:
                        self.db.execute("UPDATE index_attempts SET details=? WHERE id=?", (packed(details), job_id))
                except sqlite3.Error:
                    pass

    @staticmethod
    def _new_stage(path):
        stage = sqlite3.connect(path)
        stage.executescript("""
            CREATE TABLE p(page_number INTEGER PRIMARY KEY,page_label,text,method,status,warnings,ocr_confidence,evidence);
            CREATE TABLE c(page_number,chunk_index,title,text,char_start,char_end,token_count,
                          model_id,model_revision,model_configuration,dimensions,vector BLOB,vector_sha256);
        """)
        return stage

    def _clone_stage(self, path, source_id):
        stage = self._new_stage(path)
        try:
            for row in self.db.execute("SELECT page_number,page_label,text,method,status,warnings,ocr_confidence,evidence FROM pages WHERE document_id=? ORDER BY page_number", (source_id,)):
                stage.execute("INSERT INTO p VALUES(?,?,?,?,?,?,?,?)", tuple(row))
            for row in self.db.execute("SELECT page_number,chunk_index,title,text,char_start,char_end,token_count,model_id,model_revision,model_configuration,dimensions,vector,vector_sha256 FROM chunks WHERE document_id=? ORDER BY chunk_index", (source_id,)):
                self._decode_vector(row)
                stage.execute("INSERT INTO c VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", tuple(row))
            stage.commit()
        finally:
            stage.close()

    def _build_stage(self, path, pdf, title, chunking, options, progress, on_tier1=None):
        stage = self._new_stage(path)
        self._reused_chunk_embeddings=0
        index, profile = 0, None
        pending = []
        def flush():
            nonlocal index, profile
            if not pending:
                return
            if progress:progress({'page':pending[-1][0],'total_pages':pdf.page_count,'chunks':index,'stage':'embedding'})
            if profile is None:
                profile = self._profile()
                self._check_profile(profile)
            signature = self.embedder.signature
            profile_json = packed(profile)
            vectors = [None] * len(pending)
            missing = []
            for j, (_, chunk) in enumerate(pending):
                # Identical inputs and model profile only; source edits still
                # re-extract pages. The title index bounds the cache lookup.
                cached = self.db.execute('''SELECT c.* FROM chunks c JOIN documents d ON d.id=c.document_id
                    WHERE c.title=? AND c.text=? AND d.embedding_profile=? AND c.model_id=?
                    AND c.model_revision=? AND c.model_configuration=? AND c.dimensions=? LIMIT 1''',
                    (title, chunk['text'], profile_json, signature['model_id'],
                     signature['revision'], signature['configuration_version'], self.embedder.dimensions)).fetchone()
                if cached is not None:
                    vectors[j] = self._decode_vector(cached)
                    self._reused_chunk_embeddings += 1
                else:
                    missing.append(j)
            if missing:
                fresh = self.embedder.documents(title, [pending[j][1]['text'] for j in missing])
                for j, vector in zip(missing, fresh, strict=True):vectors[j] = vector
            for (page_number, chunk), vector in zip(pending, vectors, strict=True):
                blob = vector.tobytes()
                stage.execute('INSERT INTO c VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)', (
                    page_number, index, title, chunk['text'], chunk['char_start'], chunk['char_end'], chunk['token_count'],
                    signature['model_id'], signature['revision'], signature['configuration_version'], self.embedder.dimensions,
                    blob, hashlib.sha256(blob).hexdigest()))
                index += 1
            pending.clear()
        try:
            tier1_committed = False
            for page in pdf:
                if progress:progress({'page':page.number+1,'total_pages':pdf.page_count,'chunks':index,'stage':'reading'})
                extracted = page.extracted if hasattr(page, "extracted") else extract_page(page, options)
                stage.execute("INSERT INTO p VALUES(?,?,?,?,?,?,?,?)", tuple(packed(extracted[k]) if k in ("warnings", "evidence") else extracted[k]
                              for k in ("page_number", "page_label", "text", "method", "status", "warnings", "ocr_confidence", "evidence")))
                if extracted["status"] == "ok":
                    for chunk in chunk_page(extracted['text'], self.embedder.tokenizer, chunking):
                        pending.append((extracted['page_number'], chunk))
                        if len(pending) >= self.embedder.batch_size:
                            flush()
                if progress:
                    progress({"page": extracted["page_number"], "total_pages": pdf.page_count, "chunks": index, "status": extracted["status"]})
                if not tier1_committed and pdf.page_count > 5 and extracted["page_number"] == 5:
                    flush()
                    stage.commit()
                    if on_tier1:
                        try:
                            on_tier1(path, profile, index)
                            tier1_committed = True
                            if progress:
                                progress({"page": 5, "total_pages": pdf.page_count, "chunks": index, "stage": "tier1_ready", "message": "First 5 pages searchable immediately"})
                        except Exception:
                            pass
            flush()
            if progress:progress({'page':pdf.page_count,'total_pages':pdf.page_count,'chunks':index,'stage':'committing'})
            stage.commit()
        finally:
            stage.close()
        return profile

    def _commit_staged(self, path, doc, old, profile, *, job_id, details):
        self.db.execute("ATTACH DATABASE ? AS staged", (str(path),))
        try:
            with self.db:
                self.db.execute("BEGIN IMMEDIATE")
                if profile:
                    self._check_profile(profile)
                    self.db.execute("INSERT OR IGNORE INTO settings VALUES('embedding_profile',?)", (packed(profile),))
                existing = self.db.execute("SELECT id, version FROM documents WHERE id=?", (doc["id"],)).fetchone()
                if old:
                    current = self.db.execute("SELECT version FROM documents WHERE id=?", (old["id"],)).fetchone()
                    if current is None or current[0] != old["version"]:
                        raise ValueError("Document was changed or removed during indexing; previous committed changes retained")
                    self.db.execute("DELETE FROM chunks WHERE document_id=?", (old["id"],))
                    self.db.execute("DELETE FROM pages WHERE document_id=?", (old["id"],))
                elif existing:
                    self.db.execute("DELETE FROM chunks WHERE document_id=?", (doc["id"],))
                    self.db.execute("DELETE FROM pages WHERE document_id=?", (doc["id"],))
                statuses = Counter(dict(self.db.execute("SELECT status,count(*) FROM staged.p GROUP BY status")))
                count = self.db.execute("SELECT count(*) FROM staged.c").fetchone()[0]
                incomplete = statuses["needs_ocr"] + statuses["extraction_failed"]
                doc["chunk_count"] = count
                doc["status"] = ("partial" if incomplete else "indexed") if count else (
                    "needs_ocr" if statuses["needs_ocr"] else "extraction_failed" if statuses["extraction_failed"] else "empty")
                if old or existing:
                    columns = [k for k in doc if k != "id"]
                    self.db.execute("UPDATE documents SET " + ",".join(k+"=?" for k in columns) + " WHERE id=?",
                                    [doc[k] for k in columns] + [doc["id"]])
                else:
                    self.db.execute("INSERT INTO documents(" + ",".join(doc) + ") VALUES(" + ",".join("?" for _ in doc) + ")", list(doc.values()))
                self.db.execute("INSERT INTO pages(document_id,page_number,page_label,text,method,status,warnings,ocr_confidence,evidence) SELECT ?,page_number,page_label,text,method,status,warnings,ocr_confidence,evidence FROM staged.p", (doc["id"],))
                self.db.execute("""INSERT INTO chunks(document_id,page_number,chunk_index,title,text,char_start,char_end,token_count,
                    model_id,model_revision,model_configuration,dimensions,vector,vector_sha256)
                    SELECT ?,page_number,chunk_index,title,text,char_start,char_end,token_count,model_id,model_revision,
                    model_configuration,dimensions,vector,vector_sha256 FROM staged.c ORDER BY chunk_index""", (doc["id"],))
                self.db.execute("UPDATE folders SET updated_at=? WHERE id=?", (now(), doc["folder_id"]))
                self.db.execute("UPDATE index_attempts SET status='completed',finished_at=?,document_id=?,details=? WHERE id=?",
                                (now(), doc["id"], packed(details), job_id))
                from .papers import record_after_index
                record_after_index(self,doc)
        finally:
            self.db.execute("DETACH DATABASE staged")

    def _commit_tier1(self, path, doc, profile, *, job_id):
        self.db.execute("ATTACH DATABASE ? AS staged_t1", (str(path),))
        try:
            with self.db:
                self.db.execute("BEGIN IMMEDIATE")
                if profile:
                    self._check_profile(profile)
                    self.db.execute("INSERT OR IGNORE INTO settings VALUES('embedding_profile',?)", (packed(profile),))
                count = self.db.execute("SELECT count(*) FROM staged_t1.c").fetchone()[0]
                doc["chunk_count"] = count
                doc["status"] = "partial"
                existing = self.db.execute("SELECT id FROM documents WHERE id=?", (doc["id"],)).fetchone()
                if not existing:
                    self.db.execute("INSERT INTO documents(" + ",".join(doc) + ") VALUES(" + ",".join("?" for _ in doc) + ")", list(doc.values()))
                self.db.execute("DELETE FROM chunks WHERE document_id=?", (doc["id"],))
                self.db.execute("DELETE FROM pages WHERE document_id=?", (doc["id"],))
                self.db.execute("INSERT INTO pages(document_id,page_number,page_label,text,method,status,warnings,ocr_confidence,evidence) SELECT ?,page_number,page_label,text,method,status,warnings,ocr_confidence,evidence FROM staged_t1.p", (doc["id"],))
                self.db.execute("""INSERT INTO chunks(document_id,page_number,chunk_index,title,text,char_start,char_end,token_count,
                    model_id,model_revision,model_configuration,dimensions,vector,vector_sha256)
                    SELECT ?,page_number,chunk_index,title,text,char_start,char_end,token_count,model_id,model_revision,
                    model_configuration,dimensions,vector,vector_sha256 FROM staged_t1.c ORDER BY chunk_index""", (doc["id"],))
                self.db.execute("UPDATE folders SET updated_at=? WHERE id=?", (now(), doc["folder_id"]))
        finally:
            self.db.execute("DETACH DATABASE staged_t1")

    @staticmethod
    def _decode_vector(row):
        blob = row["vector"]
        if hashlib.sha256(blob).hexdigest() != row["vector_sha256"]:
            raise ValueError("Stored embedding checksum failed; restore or re-index the affected document")
        values = np.frombuffer(blob, dtype="<f4")
        if values.shape != (row["dimensions"],) or not np.isfinite(values).all() or not np.isclose(np.linalg.norm(values), 1, atol=1e-4):
            raise ValueError("Stored embedding is non-finite, incorrectly sized, or not normalized")
        return values

    def search(self,query,**options):
        # One WAL read snapshot covers metadata, vectors and lexical ranking even
        # if another process publishes an updated document during inference.
        own_transaction = not self.db.in_transaction
        if own_transaction:
            self.db.execute('BEGIN')
        try:
            return self._search(query,**options)
        finally:
            if own_transaction:
                self.db.rollback()

    def _search(self, query, *, folder_id=None, document_id=None, top_k=5, min_score=None, mode="semantic",
               search_dimensions=None, hybrid=None, document_ids=None, z_gate=None, semantic_query=None):
        from .retrieval import CHUNKS_FROM, MODES, SEARCH_FROM, SearchIndex, literal_ranking, preview_ranking, result_row
        begin = time.perf_counter()
        query = query.strip()
        if not query:
            raise ValueError("Search query cannot be empty")
        if not 1 <= top_k <= 100:
            raise ValueError("top_k must be between 1 and 100")
        if mode not in (*MODES, "preview"):
            raise ValueError("Unknown search mode")
        dimensions = self.embedder.dimensions if search_dimensions is None else search_dimensions
        if dimensions not in (128,256,512,768) or dimensions > self.embedder.dimensions:
            raise ValueError("Search dimensions must not exceed stored embedding dimensions")
        if min_score is not None and (mode != "semantic" or not -1 <= min_score <= 1):
            raise ValueError("A cosine cutoff must be within [-1,1] and used with semantic search")
        where, parameters = [], []
        if document_ids is not None:
            if len(document_ids)>10000:raise ValueError('Search collection is too large.')
            where.append('d.id IN ('+(','.join('?' for _ in document_ids) or 'NULL')+')')
            parameters.extend(document_ids)
        if folder_id:
            self._folder(folder_id)
            where.append("d.folder_id=?")
            parameters.append(folder_id)
        if document_id:
            self.document(document_id)
            where.append("d.id=?")
            parameters.append(document_id)
        clause = " WHERE " + " AND ".join(where) if where else ""
        # Foreign keys keep every chunk attached to a document, folder and page.
        count_from = SEARCH_FROM if where else CHUNKS_FROM
        count = None if mode == "preview" else self.db.execute("SELECT count(*)" + count_from + clause, parameters).fetchone()[0]
        results, query_s = [], 0.
        if mode == "preview":
            ranking = preview_ranking(self, query, where, parameters, top_k)
            results = [self._result(result_row(self, chunk_id), score, "fts5_bm25")
                       for chunk_id, score in ranking]
        elif count and mode == "literal":
            ranking = literal_ranking(self, query, where, parameters)
            results = [self._result(result_row(self, chunk_id), score, "exact_text")
                       for chunk_id, score in ranking[:top_k]]
        elif count:
            if mode in ("semantic", "hybrid"):
                profile = self._profile()
                self._check_profile(profile)
                encode_start = time.perf_counter()
                vector = self.embedder.query(semantic_query or query)
                query_s = time.perf_counter() - encode_start
            else:
                vector = None
            index = SearchIndex(self, where=where, parameters=parameters, vectors=mode in ("semantic","hybrid"),compact=True,count=count)
            ranking = index.rank(query, mode=mode, vector=vector, dimensions=dimensions, hybrid=hybrid, z_gate=z_gate)
            if min_score is not None:
                ranking = [(i,s) for i,s in ranking if s >= min_score]
            kind = {"semantic":"cosine","hybrid":"weighted_rrf","keyword":"distinct_query_terms"}.get(mode,"fts5_bm25")
            results = [self._result(index.result_row(i), score, kind) for i,score in ranking[:top_k]]
            if getattr(index, "last_z_scores", None) is not None:
                for result in results:
                    c_idx = index.by_id[result["chunk_id"]]
                    result["z_score"] = round(float(index.last_z_scores[c_idx]), 2)
        for rank, result in enumerate(results, 1):
            result["rank"] = rank
        return {"query": query, "folder_id": folder_id, "document_id": document_id, "mode": mode,
                "scoped_chunks": count, "results": results, "elapsed_s": time.perf_counter() - begin,
                "query_embedding_s": query_s, "min_score": min_score,
                "search_dimensions": dimensions, "hybrid": hybrid if mode=="hybrid" else None,
                "reliability": "uncalibrated_candidates" if results else "no_candidates",
                "note": "Scores rank actual source passages; no reliable-match threshold has been calibrated.",
                "empty_reason": ("empty_scope" if count == 0 else "no_candidates_for_query_or_cutoff") if not results else None}

    def source_path(self,doc,*,verify=False):
        source=(self.root/doc['managed_path']).resolve()
        if doc.get('source_mode')=='reference':
            if source!=Path(doc['original_path']).resolve():raise ValueError('Source reference does not match its indexed path')
        elif source.parent!=(self.root/'files').resolve():raise ValueError('Source PDF path escaped the managed library')
        if verify:
            candidates=[source]
            if doc.get('source_mode')=='reference' and self.db.execute("SELECT 1 FROM sqlite_master WHERE name='watched_files'").fetchone():
                for row in self.db.execute('''SELECT s.path,f.relative_path FROM watched_files f JOIN watched_sources s ON s.id=f.source_id
                        WHERE f.document_id=? AND f.indexed_signature IS NOT NULL''',(doc['id'],)):
                    alternative=(Path(row['path'])/row['relative_path']).resolve()
                    if alternative.is_relative_to(Path(row['path']).resolve()) and alternative not in candidates:candidates.append(alternative)
            found=False
            for candidate in candidates:
                try:
                    stat=candidate.stat();found=True
                    if stat.st_size==doc['size_bytes'] and source_digest(str(candidate),stat.st_size,stat.st_mtime_ns,stat.st_ctime_ns)==doc['sha256']:return candidate
                except FileNotFoundError:continue
            if not found:raise FileNotFoundError('Original PDF is unavailable')
            raise ValueError('Source PDF changed since indexing. Refresh the document before opening this version.')
        return source

    def adopt_source_references(self):
        """Relink scanned documents to unchanged originals; never delete copies."""
        changed=0
        if not self.db.execute("SELECT 1 FROM sqlite_master WHERE name='watched_files'").fetchone():return changed
        rows=self.db.execute('''SELECT d.id,d.size_bytes,s.path,f.relative_path,f.indexed_signature
            FROM watched_files f JOIN watched_sources s ON s.id=f.source_id JOIN documents d ON d.id=f.document_id
            WHERE d.source_mode='managed' AND f.indexed_signature IS NOT NULL''').fetchall()
        from .discovery import linked
        for row in rows:
            source=Path(row['path'])/row['relative_path']
            try:
                if linked(source) or not source.resolve().is_relative_to(Path(row['path']).resolve()):continue
                stat=source.stat()
                if stat.st_size!=row['size_bytes'] or f'{stat.st_size}:{stat.st_mtime_ns}'!=row['indexed_signature']:continue
            except OSError:continue
            with self.db:
                changed+=self.db.execute("UPDATE documents SET source_mode='reference',managed_path=?,original_path=? WHERE id=? AND source_mode='managed'",(str(source.resolve()),str(source.resolve()),row['id'])).rowcount
        return changed

    def _result(self, row, score, score_type):
        doc=self.document(row['document_id'])
        source=self.source_path(doc)
        return {"source_sha256":doc['sha256'], "source_revision":doc['version'],"chunk_id": row["id"], "document_id": row["document_id"], "filename": row["filename"],
                "folder_id": row["folder_id"], "folder": row["folder_name"], "page_number": row["page_number"],
                "page_label": row["page_label"], "chunk_index": row["chunk_index"], "passage": row["text"],
                "char_start": row["char_start"], "char_end": row["char_end"], "token_count": row["token_count"],
                "score": score, "score_type": score_type, "source_path": str(source),
                **source_info(doc), **self._unit_info(doc, row["page_number"]),
                "open_uri": source.as_uri() + (f"#page={row['page_number']}" if source_info(doc)["preview_kind"]=="pdf" else ""),
                "source_available": source.is_file(), "document_status": row["document_status"],
                "extraction_method": row["extraction_method"], "warnings": json.loads(row["page_warnings"]),
                "model_id": row["model_id"], "model_revision": row["model_revision"],
                "model_configuration": row["model_configuration"], "dimensions": row["dimensions"]}

    def page(self, document_id, page_number):
        self.document(document_id)
        row = self.db.execute("SELECT * FROM pages WHERE document_id=? AND page_number=?", (document_id, page_number)).fetchone()
        if row is None:
            raise ValueError("PDF page not found")
        result = dict(row)
        result["warnings"] = json.loads(result["warnings"])
        result['evidence']=json.loads(result['evidence'])
        doc=self.document(document_id)
        result['source_sha256']=doc['sha256']
        result['extraction_recipe']=json.loads(doc['recipe'])
        result.update(source_info(doc))
        result.update(self._unit_info(doc, page_number, result["evidence"]))
        return result

    def _unit_info(self, doc, number, evidence=None):
        if evidence is None:
            row=self.db.execute('SELECT evidence,page_label FROM pages WHERE document_id=? AND page_number=?',(doc['id'],number)).fetchone()
            evidence=json.loads(row['evidence']) if row else {}
        location=evidence.get('location')
        if not location:
            slide=source_info(doc)['source_kind']=='presentation'
            location={'kind':'slide' if slide else 'page','label':f'Slide {number}' if slide else f'PDF page {number}','page_number':number}
        return dict(unit_number=number,location=location,location_label=location['label'])

    def page_summary(self, document_id):
        doc=self.document(document_id)
        return [dict(row, **source_info(doc), **self._unit_info(doc,row['page_number'])) for row in self.db.execute("SELECT page_number,page_label,method,status,warnings,ocr_confidence,length(text) characters FROM pages WHERE document_id=? ORDER BY page_number", (document_id,))]

    def upgrade_evidence(self, document_id, *, include_ocr=False):
        """Add geometry without changing source text, chunk IDs, or embeddings.

        An OCR/extractor difference requires an ordinary atomic refresh instead;
        never attach new coordinates to different indexed text.
        """
        doc=self.document(document_id);source=self.source_path(doc,verify=True)
        if source_info(doc)['preview_kind']!='pdf':raise ValueError('Geometry evidence is available only for PDF documents')
        with source.open('rb') as stream:
            if hashlib.file_digest(stream,'sha256').hexdigest()!=doc['sha256']:
                raise ValueError('Managed source changed; evidence upgrade refused')
        options=PdfOptions(**json.loads(doc['recipe'])['pdf'])
        updated=skipped=0;needs_refresh=[]
        with open_pdf(source) as pdf:
            for row in self.db.execute('SELECT * FROM pages WHERE document_id=? ORDER BY page_number',(document_id,)).fetchall():
                if json.loads(row['evidence']).get('version') or row['status']!='ok':skipped+=1;continue
                if row['method']=='ocr' and not include_ocr:skipped+=1;continue
                extracted=extract_page(pdf[row['page_number']-1],options)
                if extracted['text']!=row['text'] or extracted['method']!=row['method']:
                    with self.db:
                        self.db.execute('UPDATE pages SET evidence=? WHERE document_id=? AND page_number=?',
                            (packed(dict(state='requires_refresh',words=[],version=0)),document_id,row['page_number']))
                    needs_refresh.append(row['page_number']);continue
                with self.db:
                    current=self.document(document_id)
                    if current['sha256']!=doc['sha256'] or current['version']!=doc['version']:
                        raise ValueError('Document changed during evidence upgrade')
                    self.db.execute('UPDATE pages SET evidence=? WHERE document_id=? AND page_number=?',
                        (packed(extracted['evidence']),document_id,row['page_number']))
                updated+=1
        return dict(document_id=document_id,updated=updated,skipped=skipped,needs_refresh=needs_refresh)

    def refresh(self, document_id):
        doc = self.document(document_id)
        recipe = json.loads(doc["recipe"])
        return self.import_document(doc["original_path"], doc["folder_id"], document_id=document_id,
                               title=recipe["title"], chunking=ChunkingConfig(**recipe["chunking"]),
                               pdf_options=PdfOptions(**recipe.get("pdf",{})),retain_source=doc.get('source_mode')!='reference')

    def sync(self, *, remove_missing=False):
        results = []
        for doc in self.documents():
            if not Path(doc["original_path"]).is_file():
                results.append(self.remove_document(doc["id"]) if remove_missing else
                               {"document_id": doc["id"], "action": "source_missing", "managed_copy_retained": doc.get('source_mode')!='reference'})
            else:
                try:
                    results.append(self.refresh(doc["id"]))
                except Exception as exc:
                    results.append({"document_id": doc["id"], "action": "failed", "error": str(exc)})
        return results

    def jobs(self):
        return [dict(row) for row in self.db.execute("SELECT * FROM index_attempts ORDER BY started_at DESC")]

    def stats(self):
        return {"root": str(self.root), "folders": self.db.execute("SELECT count(*) FROM folders").fetchone()[0],
                "documents": self.db.execute("SELECT count(*) FROM documents").fetchone()[0],
                "pages": self.db.execute("SELECT count(*) FROM pages").fetchone()[0],
                "chunks": self.db.execute("SELECT count(*) FROM chunks").fetchone()[0],
                "vector_bytes": self.db.execute("SELECT coalesce(sum(length(vector)),0) FROM chunks").fetchone()[0],
                "database_bytes": sum(p.stat().st_size for p in self.root.glob("library.sqlite3*")),
                "managed_document_bytes": sum(p.stat().st_size for p in (self.root / "files").iterdir() if p.is_file() and p.suffix.lower() in TEXT_EXTENSIONS | SPREADSHEET_EXTENSIONS | {".pdf"}),
                "managed_pdf_bytes": sum(p.stat().st_size for p in (self.root / "files").glob("*.pdf")),
                "embedding_runtime": dict(self.embedder.stats)}

    def verify(self,*,include_external_sources=True):
        issues, checked_chunks, checked_pages, external_sources_unchecked = [], 0, 0, 0
        for row in self.db.execute("PRAGMA integrity_check"):
            if row[0] != "ok":
                issues.append({"kind": "sqlite", "error": row[0]})
        for row in self.db.execute("PRAGMA foreign_key_check"):
            issues.append({"kind": "foreign_key", "error": list(row)})
        try:
            with self.db:
                self.db.execute("INSERT INTO chunks_fts(chunks_fts,rank) VALUES('integrity-check',1)")
                self.db.execute("INSERT INTO chunks_fts_stemmed(chunks_fts_stemmed,rank) VALUES('integrity-check',1)")
        except sqlite3.Error as exc:
            issues.append({"kind": "fts", "error": str(exc)})
        for doc in self.documents():
            try:
                original=self.db.execute('SELECT * FROM document_sources WHERE document_id=?',(doc['id'],)).fetchone()
                if original:
                    deck=(self.root/original['source_path']).resolve()
                    if deck.parent!=(self.root/'originals').resolve():raise ValueError('PowerPoint source path escaped managed originals')
                    with deck.open('rb') as stream:
                        if hashlib.file_digest(stream,'sha256').hexdigest()!=original['source_sha256']:raise ValueError('Original PowerPoint source checksum changed')
                    if original['slides']!=doc['page_count']:raise ValueError('PowerPoint slide count does not match converted PDF')
                if doc.get('source_mode')=='reference' and not include_external_sources:
                    external_sources_unchecked+=1
                else:
                    source = self.source_path(doc,verify=True)
                    if source_info(doc)['preview_kind']=='text':
                        with open_text_document(source) as native:
                            pages=self.db.execute('SELECT * FROM pages WHERE document_id=? ORDER BY page_number',(doc['id'],)).fetchall()
                            if native.page_count!=doc['page_count'] or len(pages)!=native.page_count:raise ValueError('Source unit count changed')
                            for unit,page in zip(native,pages,strict=True):
                                extracted=unit.extracted
                                if extracted['text']!=page['text'] or extracted['evidence'].get('location')!=json.loads(page['evidence']).get('location'):
                                    raise ValueError(f"Cached extracted text/location differs from source unit {page['page_number']}")
                                checked_pages+=1
                    else:
                        with open_pdf(source) as pdf:
                            if len(pdf) != doc["page_count"]:
                                raise ValueError("Source page count changed")
                            for page in self.db.execute("SELECT * FROM pages WHERE document_id=?", (doc["id"],)):
                                if page["method"] == "native" and page["status"] != "extraction_failed":
                                    evidence=json.loads(page['evidence'])
                                    original=page['text'][:evidence['native_text_length']] if 'native_text_length' in evidence else page['text'].split('\n[Table rows extracted from this page]')[0]
                                    if native_text(pdf[page["page_number"] - 1]) != original:
                                        raise ValueError(f"Cached extracted text differs from physical page {page['page_number']}")
                                checked_pages += 1
                for row in self.db.execute("SELECT c.*,p.text full_page FROM chunks c JOIN pages p ON p.document_id=c.document_id AND p.page_number=c.page_number WHERE c.document_id=?", (doc["id"],)):
                    self._decode_vector(row)
                    if row["full_page"][row["char_start"]:row["char_end"]] != row["text"]:
                        raise ValueError("Stored passage does not match its page character offsets")
                    checked_chunks += 1
            except Exception as exc:
                issues.append({"kind": "document", "document_id": doc["id"], "error": str(exc)})
        return {"passed": not issues, "checked_pages": checked_pages, "checked_chunks": checked_chunks, "issues": issues,
                "external_sources_unchecked":external_sources_unchecked,
                "scope": "Exact passage offsets, vector checksums/norms, SQLite and FTS integrity; file hashes and physical pages exclude external references when include_external_sources=False. Not a graphical viewer test."}
