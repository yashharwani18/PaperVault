"""Disk-backed, revision-repaired retrieval experiment, NOT a patent opinion.

Guarantee scope: top-k inner products over eligible, stored float32 vectors in
one SQLite transaction. Source text accuracy, model relevance and external file
freshness are outside that guarantee. No neural model is loaded here.
"""
from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import uuid
from pathlib import Path

import numpy as np

PAD = 1e-9  # Conservative engineering tolerance; not a machine-checked FP proof.


def packed(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def digest(value):
    return hashlib.sha256(value).hexdigest()


def normalized(vector, dimension):
    value = np.asarray(vector, dtype='<f4')
    if value.shape != (dimension,) or not np.isfinite(value).all():
        raise ValueError('Invalid vector')
    norm = np.linalg.norm(value.astype(np.float64))
    if norm <= 0:
        raise ValueError('Zero vector')
    return np.asarray(value / norm, dtype='<f4')


class EvidenceSearch:
    """Single-owner reference engine. SQLite serializes mutations with each slice.

    A fixed SQLite cache and one-row scoring avoid an N-by-D resident matrix.
    The budget counts full-vector refinements, NOT total RAM, energy or time.
    """

    def __init__(self, path, dimension=768):
        if not 1 <= dimension <= 4096:
            raise ValueError('Unsupported dimension')
        self.dimension = dimension
        self.db = sqlite3.connect(Path(path), timeout=15)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
            PRAGMA journal_mode=WAL;
            PRAGMA synchronous=FULL;
            PRAGMA cache_size=-2048;
            PRAGMA temp_store=FILE;
            PRAGMA mmap_size=0;
            CREATE TABLE IF NOT EXISTS config(dimension INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS changes(seq INTEGER PRIMARY KEY AUTOINCREMENT, doc TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS sources(
                id TEXT PRIMARY KEY, doc TEXT NOT NULL, rev INTEGER NOT NULL,
                folder TEXT NOT NULL, page INTEGER NOT NULL, text TEXT NOT NULL,
                field TEXT, value TEXT, currency TEXT, start INTEGER, end INTEGER,
                source_hash TEXT NOT NULL, vector BLOB NOT NULL, vector_hash TEXT NOT NULL,
                code BLOB NOT NULL, scale REAL NOT NULL, error REAL NOT NULL);
            CREATE INDEX IF NOT EXISTS sources_doc ON sources(doc);
            CREATE TABLE IF NOT EXISTS jobs(
                id TEXT PRIMARY KEY, query BLOB NOT NULL, predicate TEXT NOT NULL,
                k INTEGER NOT NULL, epoch INTEGER NOT NULL, reads INTEGER NOT NULL DEFAULT 0,
                coarse INTEGER NOT NULL DEFAULT 0, repaired INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS frontier(
                job TEXT NOT NULL, id TEXT NOT NULL, doc TEXT NOT NULL, rev INTEGER NOT NULL,
                upper REAL NOT NULL, score REAL, PRIMARY KEY(job,id));
            CREATE INDEX IF NOT EXISTS frontier_upper ON frontier(job,score,upper DESC);
            CREATE INDEX IF NOT EXISTS frontier_doc ON frontier(job,doc);
        ''')
        row = self.db.execute('SELECT dimension FROM config').fetchone()
        if row and row[0] != dimension:
            raise ValueError('Dimension mismatch')
        if not row:
            with self.db:
                self.db.execute('INSERT INTO config VALUES(?)', (dimension,))

    def close(self):
        self.db.close()

    def epoch(self):
        return self.db.execute('SELECT coalesce(max(seq),0) FROM changes').fetchone()[0]

    def replace_document(self, doc, records):
        """Atomically replace all records and advance their shared revision.

        A deletion uses an empty iterable. Evidence tuples are verified against
        the exact stored text using the existing deterministic amount parser.
        """
        from knowledge_library.bill_amounts import source_amounts
        with self.db:
            seq = self.db.execute('INSERT INTO changes(doc) VALUES(?)', (doc,)).lastrowid
            self.db.execute('DELETE FROM sources WHERE doc=?', (doc,))
            for item in records:
                text = item['text']
                if len(text) > 32768 or not 1 <= item['page']:
                    raise ValueError('Record exceeds reference implementation limits')
                evidence = item.get('evidence')
                if evidence is not None:
                    if evidence not in list(source_amounts(text)):
                        raise ValueError('Evidence does not match source text')
                evidence = evidence or {}
                vector = normalized(item['vector'], self.dimension)
                raw = vector.tobytes()
                full = vector.astype(np.float64)
                scale = float(np.max(np.abs(full))) / 127
                code = np.rint(full / scale).astype(np.int8)
                error = float(np.linalg.norm(full - code.astype(np.float64)*scale)) + PAD
                identity = dict(doc=doc, id=item['id'], folder=item['folder'], page=item['page'],
                                text=text, evidence=evidence, vector_hash=digest(raw))
                self.db.execute('INSERT INTO sources VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                    (item['id'], doc, seq, item['folder'], item['page'], text,
                     evidence.get('field'), evidence.get('value'), evidence.get('currency'),
                     evidence.get('start'), evidence.get('end'), digest(packed(identity).encode()),
                     raw, digest(raw), code.tobytes(), scale, error))

    @staticmethod
    def predicate(value):
        from knowledge_library.bill_amounts import money
        result = dict(value)
        if set(result) - {'folder', 'field', 'value', 'currency'}:
            raise ValueError('Unsupported predicate')
        if ('field' in result) != ('value' in result):
            raise ValueError('Field and value must occur together')
        if 'field' in result:
            if result['field'] not in ('subtotal', 'total'):
                raise ValueError('Unsupported field')
            result['value'] = format(money(str(result['value'])), '.2f')
        if any(not isinstance(v, str) or not v for v in result.values()):
            raise ValueError('Invalid predicate')
        return result

    @staticmethod
    def eligible(row, predicate):
        return all(row[key] == value for key, value in predicate.items())

    def _coarse(self, job, row, query, predicate):
        if not self.eligible(row, predicate):
            return 0
        code = np.frombuffer(row['code'], dtype=np.int8)
        if code.shape != (self.dimension,) or not math.isfinite(row['error']) or row['error'] < 0:
            raise ValueError('Invalid bound metadata')
        center = float(np.dot(query, code.astype(np.float64)*row['scale']))
        upper = center + np.linalg.norm(query)*row['error'] + PAD
        self.db.execute('INSERT INTO frontier VALUES(?,?,?,?,?,NULL)',
                        (job, row['id'], row['doc'], row['rev'], float(upper)))
        return 1

    def start(self, query, *, predicate=None, k=5):
        if not 1 <= k <= 100:
            raise ValueError('k must be 1..100')
        q = normalized(query, self.dimension).astype('<f8')
        pred = self.predicate(predicate or {})
        job = uuid.uuid4().hex
        with self.db:
            # BEGIN IMMEDIATE precedes all reads: query membership and epoch agree.
            self.db.execute('BEGIN IMMEDIATE')
            self.db.execute('INSERT INTO jobs(id,query,predicate,k,epoch) VALUES(?,?,?,?,?)',
                            (job, q.tobytes(), packed(pred), k, self.epoch()))
            count = 0
            for row in self.db.execute('SELECT id,doc,rev,folder,page,field,value,currency,code,scale,error FROM sources'):
                count += self._coarse(job, row, q, pred)
            self.db.execute('UPDATE jobs SET coarse=? WHERE id=?', (count, job))
        return job

    def advance(self, job, *, exact_budget):
        if type(exact_budget) is not int or exact_budget < 0:
            raise ValueError('Budget must be a nonnegative integer')
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            state = self.db.execute('SELECT * FROM jobs WHERE id=?', (job,)).fetchone()
            if state is None:
                raise ValueError('Unknown job')
            q = np.frombuffer(state['query'], dtype='<f8')
            pred = json.loads(state['predicate'])
            epoch = self.epoch()
            repaired = coarse = 0
            # Includes documents that previously had NO eligible rows. Merely
            # checking returned citations would miss these newly eligible sources.
            for change in self.db.execute('SELECT DISTINCT doc FROM changes WHERE seq>?', (state['epoch'],)):
                doc = change[0]
                self.db.execute('DELETE FROM frontier WHERE job=? AND doc=?', (job, doc))
                for row in self.db.execute('SELECT id,doc,rev,folder,page,field,value,currency,code,scale,error FROM sources WHERE doc=?', (doc,)):
                    coarse += self._coarse(job, row, q, pred)
                repaired += 1
            reads = 0
            while True:
                best = self.db.execute('SELECT * FROM frontier WHERE job=? AND score IS NOT NULL ORDER BY score DESC,id LIMIT ?', (job, state['k'])).fetchall()
                pending = self.db.execute('SELECT * FROM frontier WHERE job=? AND score IS NULL ORDER BY upper DESC,id LIMIT 1', (job,)).fetchone()
                complete = pending is None or (len(best) == state['k'] and best[-1]['score']-PAD > pending['upper'])
                if complete or reads >= exact_budget:
                    break
                row = self.db.execute('SELECT vector,vector_hash,rev FROM sources WHERE id=?', (pending['id'],)).fetchone()
                if row is None or row['rev'] != pending['rev'] or digest(row['vector']) != row['vector_hash']:
                    raise ValueError('Source/vector revision mismatch')
                vector = np.frombuffer(row['vector'], dtype='<f4').astype(np.float64)
                score = float(np.dot(q, vector))
                if not math.isfinite(score) or score > pending['upper']+PAD:
                    raise ValueError('Invalid score bound')
                self.db.execute('UPDATE frontier SET score=? WHERE job=? AND id=?', (score, job, pending['id']))
                reads += 1
            self.db.execute('UPDATE jobs SET epoch=?,reads=reads+?,coarse=coarse+?,repaired=repaired+? WHERE id=?',
                            (epoch, reads, coarse, repaired, job))
            hits = []
            for entry in best:
                row = self.db.execute('SELECT id,doc,rev,page,source_hash,field,value,currency,start,end,text FROM sources WHERE id=?', (entry['id'],)).fetchone()
                hits.append({**dict(row), 'score':entry['score']})
            return dict(job=job, status='complete' if complete else 'pending', epoch=epoch,
                        query_hash=digest(state['query']), predicate_hash=digest(state['predicate'].encode()),
                        hits=hits, next_upper=pending['upper'] if pending else None,
                        boundary_lower=best[-1]['score']-PAD if len(best)==state['k'] else None,
                        exact_reads_slice=reads, exact_reads_total=state['reads']+reads,
                        coarse_total=state['coarse']+coarse, repaired_documents=repaired)

    def current(self, receipt):
        """A returned receipt certifies only its epoch, never a future library."""
        return receipt['status'] == 'complete' and receipt['epoch'] == self.epoch()

    def exhaustive(self, query, predicate=None, k=5):
        """Independent streaming exact oracle with O(k+D) application arrays."""
        q = normalized(query, self.dimension).astype(np.float64)
        pred = self.predicate(predicate or {})
        best = []
        for row in self.db.execute('SELECT id,folder,field,value,currency,vector FROM sources'):
            if self.eligible(row, pred):
                score = float(np.dot(q, np.frombuffer(row['vector'], dtype='<f4').astype(np.float64)))
                best.append((row['id'], score))
                best.sort(key=lambda pair:(-pair[1], pair[0]))
                del best[k:]
        return [pair[0] for pair in best]
