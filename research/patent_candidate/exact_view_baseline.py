"""Ordinary disk-materialized exact-score view: a stronger R1 comparator.

This is an experimental baseline, not proposed new subject matter. It uses the
same authoritative source table to avoid changing ingestion, predicates or score
arithmetic. Initial evaluation is exhaustive; updates rescore changed eligible
documents only. No quantized bounds, search budget or partial frontier is used.
"""
import json
import uuid

import numpy as np

from .engine import EvidenceSearch, normalized, packed, digest


class ExactView:
    def __init__(self, engine):
        self.engine=engine
        self.db=engine.db
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS exact_jobs(
                id TEXT PRIMARY KEY, query BLOB NOT NULL, predicate TEXT NOT NULL,
                k INTEGER NOT NULL, epoch INTEGER NOT NULL, reads INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS exact_scores(
                job TEXT NOT NULL,id TEXT NOT NULL,doc TEXT NOT NULL,
                rev INTEGER NOT NULL,score REAL NOT NULL,PRIMARY KEY(job,id));
            CREATE INDEX IF NOT EXISTS exact_score_order ON exact_scores(job,score DESC,id);
            CREATE INDEX IF NOT EXISTS exact_score_doc ON exact_scores(job,doc);
        ''')

    def _insert(self, job, q, predicate, row):
        if not EvidenceSearch.eligible(row,predicate):return 0
        if digest(row['vector'])!=row['vector_hash']:
            raise ValueError('Source/vector checksum mismatch')
        vector=np.frombuffer(row['vector'],dtype='<f4').astype(np.float64)
        score=float(np.dot(q,vector))
        self.db.execute('INSERT INTO exact_scores VALUES(?,?,?,?,?)',
                        (job,row['id'],row['doc'],row['rev'],score))
        return 1

    def start(self,query,*,predicate=None,k=5):
        if not 1<=k<=100:raise ValueError('Invalid k')
        q=normalized(query,self.engine.dimension).astype('<f8')
        pred=self.engine.predicate(predicate or {})
        job=uuid.uuid4().hex
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            reads=0
            for row in self.db.execute('SELECT id,doc,rev,folder,field,value,currency,vector,vector_hash FROM sources'):
                reads+=self._insert(job,q,pred,row)
            self.db.execute('INSERT INTO exact_jobs VALUES(?,?,?,?,?,?)',
                (job,q.tobytes(),packed(pred),k,self.engine.epoch(),reads))
        return job

    def advance(self,job):
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            state=self.db.execute('SELECT * FROM exact_jobs WHERE id=?',(job,)).fetchone()
            if state is None:raise ValueError('Unknown job')
            q=np.frombuffer(state['query'],dtype='<f8')
            pred=json.loads(state['predicate'])
            epoch=self.engine.epoch()
            reads=changed=0
            for delta in self.db.execute('SELECT DISTINCT doc FROM changes WHERE seq>?',(state['epoch'],)):
                doc=delta[0];changed+=1
                self.db.execute('DELETE FROM exact_scores WHERE job=? AND doc=?',(job,doc))
                for row in self.db.execute('SELECT id,doc,rev,folder,field,value,currency,vector,vector_hash FROM sources WHERE doc=?',(doc,)):
                    reads+=self._insert(job,q,pred,row)
            self.db.execute('UPDATE exact_jobs SET epoch=?,reads=reads+? WHERE id=?',(epoch,reads,job))
            # Return source identity/payload too, so receipt construction is not
            # omitted from this comparator while being charged to R1.
            hits=[dict(r) for r in self.db.execute('''SELECT s.id,s.doc,s.rev,s.page,
                s.source_hash,s.field,s.value,s.currency,s.start,s.end,s.text,e.score
                FROM exact_scores e JOIN sources s ON s.id=e.id
                WHERE e.job=? ORDER BY e.score DESC,e.id LIMIT ?''',(job,state['k']))]
            return dict(status='complete',epoch=epoch,hits=hits,
                query_hash=digest(state['query']),predicate_hash=digest(state['predicate'].encode()),
                exact_reads_slice=reads,exact_reads_total=state['reads']+reads,
                repaired_documents=changed)
