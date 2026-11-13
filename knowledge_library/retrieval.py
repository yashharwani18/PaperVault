"""Shared exact retrieval for the CLI and reproducible offline evaluation.

An evaluation may reuse an immutable snapshot. The live Library builds a fresh
snapshot for each call, so additions, removals, and folder moves are visible.
"""
from __future__ import annotations
import re
import hashlib
import numpy as np

# Deliberately fixed, corpus-independent English query stop list. Keep negation.
STOP = frozenset("a an the and or of to in on at for from with by is are was were be been being it its this that these those as do does did can could would should will shall may might i me my we our you your he she they their how what which where when why who find show explain explaining notes discussing about into than then also some any all each more most very have has had get let please using use".split())
MODES = ("keyword", "bm25_raw", "bm25", "literal", "semantic", "hybrid")


def terms(query, *, raw=False):
    words = dict.fromkeys(re.findall(r"\w+", query.casefold(), re.UNICODE))
    return [w for w in words if raw or w not in STOP][:64]


def literal_query(query):
    """Preserve general searches; translate explicit numeric invoice references."""
    match = re.fullmatch(r"\s*invoice\s*(?:number|no\.?|#)\s*[:#-]?\s*(\d+)\s*", query, re.I)
    return 'inv'+match.group(1) if match else query


def literal_match(query, text):
    """Match complete case-insensitive words with flexible punctuation."""
    words = re.findall(r"[^\W_]+", query.casefold(), re.UNICODE)
    if not words:
        return False
    pattern = r"(?<![^\W_])" + r"[\W_]+".join(map(re.escape, words)) + r"(?![^\W_])"
    return bool(re.search(pattern, text.casefold(), re.UNICODE))


def truncate_normalize(values, dimensions):
    array = np.asarray(values, dtype=np.float32)
    if dimensions not in (128, 256, 512, 768) or array.shape[-1] < dimensions:
        raise ValueError("Search dimensions must be supported and no larger than the stored vectors")
    sliced = array[..., :dimensions].copy()
    norms = np.linalg.norm(sliced, axis=-1, keepdims=True)
    if not np.isfinite(sliced).all() or (norms <= 0).any():
        raise ValueError("Cannot normalize non-finite or zero truncated vectors")
    return sliced / norms


def page_ranking(rows, scores, *, positive_only=False, z_gate=None):
    best = {}
    z_scores = None
    if z_gate is not None and len(scores) > 1:
        arr = np.asarray(scores, dtype=np.float64)
        std = float(np.std(arr))
        if std > 1e-6:
            mean = float(np.mean(arr))
            z_scores = (arr - mean) / std

    for i, (row, score) in enumerate(zip(rows, scores, strict=True)):
        score = float(score)
        if positive_only and score <= 0:
            continue
        if z_scores is not None and z_scores[i] < z_gate:
            continue
        key = row["document_id"], row["page_number"]
        if key not in best or score > best[key][1]:
            best[key] = (i, score)
    return sorted(best.values(), key=lambda pair: (-pair[1], rows[pair[0]]["id"]))


def reciprocal_rank_fusion(rows, semantic, lexical, *, semantic_weight=.5, rank_constant=60, candidates=100):
    if not 0 <= semantic_weight <= 1 or rank_constant <= 0 or candidates <= 0:
        raise ValueError("Invalid reciprocal rank fusion configuration")
    fused = {}
    for ranking, weight in ((semantic, semantic_weight), (lexical, 1-semantic_weight)):
        if weight == 0:
            continue
        for rank, (i, _) in enumerate(ranking[:candidates], 1):
            key = rows[i]["document_id"], rows[i]["page_number"]
            if key not in fused:
                fused[key] = [i, 0.]
            fused[key][1] += weight / (rank_constant + rank)
    return sorted((tuple(v) for v in fused.values()), key=lambda pair: (-pair[1], rows[pair[0]]["id"]))


class SearchIndex:
    def __init__(self, library, *, where=(), parameters=(), vectors=True, compact=False):
        self.library, self.where, self.parameters = library, list(where), list(parameters)
        self.clause = " WHERE " + " AND ".join(where) if where else ""
        self.base = " FROM chunks c JOIN documents d ON d.id=c.document_id JOIN folders f ON f.id=d.folder_id JOIN pages p ON p.document_id=c.document_id AND p.page_number=c.page_number"
        self.columns = "c.*,d.filename,d.managed_path,d.status document_status,f.id folder_id,f.name folder_name,p.page_label,p.method extraction_method,p.warnings page_warnings"
        self.compact=compact
        if compact:
            self.rows,self.matrix=self._compact_snapshot(vectors)
        else:
            self.rows = [dict(r) for r in library.db.execute("SELECT " + self.columns + self.base + self.clause + " ORDER BY c.id", parameters)]
            self.matrix = self._matrix(library) if vectors and self.rows else None
        self.by_id = {r["id"]:i for i,r in enumerate(self.rows)}
        self.word_sets = None

    def _compact_snapshot(self,vectors):
        """Stream vectors once; keep only page identities beside the matrix.

        Live Library.search owns a WAL read transaction across scoring and result
        hydration. No cross-query cache: committed additions/removals stay visible.
        """
        columns='c.id,c.document_id,c.page_number'
        columns+=',c.dimensions,c.vector,c.vector_sha256' if vectors else ',c.text'
        count=self.library.db.execute('SELECT count(*)'+self.base+self.clause,self.parameters).fetchone()[0]
        rows=[];matrix=None
        for i,row in enumerate(self.library.db.execute('SELECT '+columns+self.base+self.clause+' ORDER BY c.id',self.parameters)):
            if vectors:
                if matrix is None:matrix=np.empty((count,row['dimensions']),dtype=np.float32)
                blob=row['vector']
                if hashlib.sha256(blob).hexdigest()!=row['vector_sha256']:
                    raise ValueError('Stored embedding checksum failed; restore or re-index the affected document')
                if row['dimensions']!=matrix.shape[1] or len(blob)!=matrix.shape[1]*4:
                    raise ValueError('Stored embedding has an incorrect size')
                matrix[i]=np.frombuffer(blob,dtype='<f4')
                rows.append(dict(id=row['id'],document_id=row['document_id'],page_number=row['page_number']))
            else:rows.append(dict(row))
        if matrix is not None:
            # Norm validation previously allocated a second full matrix. Small
            # batches retain identical row arithmetic with bounded temporary RAM.
            for start in range(0,len(matrix),1024):
                batch=matrix[start:start+1024]
                norms=np.linalg.norm(batch,axis=1,keepdims=True)
                if not np.isfinite(batch).all() or not np.isclose(norms,1,atol=1e-4).all():
                    raise ValueError('Stored embedding is non-finite, incorrectly sized, or not normalized')
                batch/=norms
        return rows,matrix

    def result_row(self,index):
        if not self.compact:return self.rows[index]
        # Fetch source text/metadata only for the pages that will be shown.
        return dict(self.library.db.execute('SELECT '+self.columns+self.base+' WHERE c.id=?',
                                            (self.rows[index]['id'],)).fetchone())

    def _matrix(self,library):
        """Keep checksum checks, but validate/normalize vectors in NumPy batches."""
        dimensions=self.rows[0]['dimensions']
        matrix=np.empty((len(self.rows),dimensions),dtype=np.float32)
        for i,row in enumerate(self.rows):
            blob=row['vector']
            if hashlib.sha256(blob).hexdigest()!=row['vector_sha256']:
                raise ValueError('Stored embedding checksum failed; restore or re-index the affected document')
            if row['dimensions']!=dimensions or len(blob)!=dimensions*4:
                raise ValueError('Stored embedding has an incorrect size')
            matrix[i]=np.frombuffer(blob,dtype='<f4')
        norms=np.linalg.norm(matrix,axis=1,keepdims=True)
        if not np.isfinite(matrix).all() or not np.isclose(norms,1,atol=1e-4).all():
            raise ValueError('Stored embedding is non-finite, incorrectly sized, or not normalized')
        matrix/=norms
        return matrix

    def semantic(self, vector, dimensions=768, z_gate=None):
        if not self.rows:
            return []
        if self.matrix is None:
            raise ValueError("Snapshot was opened without vectors")
        matrix = self.matrix if dimensions==self.matrix.shape[1] else truncate_normalize(self.matrix, dimensions)
        vector = truncate_normalize(vector, dimensions)
        scores = matrix @ vector
        self.last_z_scores = None
        if len(scores) > 1:
            arr = np.asarray(scores, dtype=np.float64)
            std = float(np.std(arr))
            if std > 1e-6:
                mean = float(np.mean(arr))
                self.last_z_scores = (arr - mean) / std
        return page_ranking(self.rows, scores, z_gate=z_gate)

    def lexical(self, query, *, mode="bm25"):
        words = terms(query, raw=mode=="bm25_raw")
        if not words or not self.rows:
            return []
        if mode == "keyword":
            if self.word_sets is None:
                if self.compact and 'text' not in self.rows[0]:
                    self.word_sets=[set() for _ in self.rows]
                    for row in self.library.db.execute('SELECT c.id,c.text'+self.base+self.clause,self.parameters):
                        self.word_sets[self.by_id[row['id']]]=set(re.findall(r'\w+',row['text'].casefold(),re.UNICODE))
                else:
                    self.word_sets = [set(re.findall(r"\w+", r["text"].casefold(), re.UNICODE)) for r in self.rows]
            scores = [len(set(words) & word_set) for word_set in self.word_sets]
            return page_ranking(self.rows, scores, positive_only=True)
        table = "chunks_fts" if mode == "bm25_raw" else "chunks_fts_stemmed"
        match = " OR ".join('"'+word.replace('"','""')+'"' for word in words)
        score = f"bm25({table})" if mode == "bm25_raw" else f"bm25({table},1.0,0.3)"
        sql = f"SELECT c.id,{score} lexical_score FROM chunks c JOIN documents d ON d.id=c.document_id JOIN {table} ON {table}.rowid=c.id WHERE {table} MATCH ?"
        if self.where:
            sql += " AND " + " AND ".join(self.where)
        scores = np.zeros(len(self.rows), dtype=np.float64)
        for row in self.library.db.execute(sql, [match,*self.parameters]):
            scores[self.by_id[row["id"]]] = -float(row["lexical_score"])
        return page_ranking(self.rows, scores, positive_only=True)

    def literal(self, query):
        words = re.findall(r"[^\W_]+", query, re.UNICODE)
        if not words or not self.rows:
            return []
        phrase='"'+' '.join(words).replace('"','""')+'"'
        sql="SELECT c.id,c.text,bm25(chunks_fts) lexical_score FROM chunks c JOIN documents d ON d.id=c.document_id JOIN chunks_fts ON chunks_fts.rowid=c.id WHERE chunks_fts MATCH ?"
        if self.where:sql+=" AND "+" AND ".join(self.where)
        scores=np.zeros(len(self.rows),dtype=np.float64)
        for row in self.library.db.execute(sql,[phrase,*self.parameters]):
            if literal_match(query,row['text']):scores[self.by_id[row['id']]]=-float(row['lexical_score'])
        return page_ranking(self.rows,scores,positive_only=True)

    def rank(self, query, *, mode="semantic", vector=None, dimensions=768, hybrid=None, z_gate=None):
        if mode not in MODES:
            raise ValueError("Unknown retrieval mode")
        if mode=="literal":
            return self.literal(query)
        if mode in ("keyword", "bm25", "bm25_raw"):
            return self.lexical(query, mode=mode)
        semantic = self.semantic(vector, dimensions, z_gate=z_gate)
        if mode == "semantic":
            return semantic
        return reciprocal_rank_fusion(self.rows, semantic, self.lexical(query), **(hybrid or {}))
