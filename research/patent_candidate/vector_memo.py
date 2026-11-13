"""Conventional exact-input embedding cache for the R5 control experiment.

Research only. This is deliberately NOT promoted as an invention. It does not
cache OCR, document metadata, citations, field labels or search results.
"""
from __future__ import annotations

import hashlib
import inspect
import json
import sqlite3

import numpy as np


class VectorMemo:
    """Wrap an embedder without changing Library's transactional publication.

    Keys include the full formatted model input and the embedding profile.
    A cached vector is merely a computation result; source identity is always
    rebuilt by the ordinary ingestion path. One writer is assumed in this probe.
    """

    def __init__(self, underlying, path):
        self.underlying = underlying
        self.cache = sqlite3.connect(path)
        self.cache.execute("""CREATE TABLE IF NOT EXISTS memo(
            key TEXT PRIMARY KEY, identity TEXT NOT NULL, vector BLOB NOT NULL,
            checksum TEXT NOT NULL)""")
        self.hits = self.misses = self.corruptions = 0

    def __getattr__(self, name):
        return getattr(self.underlying, name)

    def _identity(self, title, text):
        # Bind actual formatting behavior, model revision, configuration and dtype.
        # Storing only passage text would be wrong for title-conditioned embeddings.
        return json.dumps({
            "signature": self.underlying.signature,
            "dtype": self.underlying.dtype,
            "dimensions": self.underlying.dimensions,
            "formatter": inspect.getsource(self.underlying.format_document),
            "input": self.underlying.format_document(title, text),
            "role": "document",
        }, sort_keys=True, ensure_ascii=False, separators=(",", ":"))

    def documents(self, title, texts):
        if not texts:
            return np.empty((0, self.dimensions), dtype="<f4")
        identities = [self._identity(title, text) for text in texts]
        keys = [hashlib.sha256(identity.encode()).hexdigest() for identity in identities]
        values, missing = {}, {}
        for key, identity, text in zip(keys, identities, texts, strict=True):
            if key in values or key in missing:
                continue
            row = self.cache.execute("SELECT identity,vector,checksum FROM memo WHERE key=?", (key,)).fetchone()
            valid = False
            if row and row[0] == identity and len(row[1]) == 4 * self.dimensions:
                vector = np.frombuffer(row[1], dtype="<f4")
                valid = (hashlib.sha256(row[1]).hexdigest() == row[2]
                         and vector.shape == (self.dimensions,)
                         and np.isfinite(vector).all()
                         and np.isclose(np.linalg.norm(vector), 1, atol=1e-4))
                if valid:
                    values[key] = vector.copy()
                    self.hits += 1
            if not valid:
                if row:
                    self.corruptions += 1
                missing[key] = (identity, text)
        if missing:
            vectors = self.underlying.documents(title, [item[1] for item in missing.values()])
            if vectors.shape != (len(missing), self.dimensions):
                raise ValueError("Unexpected embedding output shape")
            staged = []
            for (key, (identity, _)), vector in zip(missing.items(), vectors, strict=True):
                vector = np.asarray(vector, dtype="<f4")
                if not np.isfinite(vector).all() or not np.isclose(np.linalg.norm(vector), 1, atol=1e-4):
                    raise ValueError("Invalid embedding output")
                blob = vector.tobytes()
                staged.append((key, identity, blob, hashlib.sha256(blob).hexdigest()))
                values[key] = vector.copy()
            with self.cache:
                self.cache.executemany("INSERT OR REPLACE INTO memo VALUES(?,?,?,?)", staged)
            self.misses += len(missing)
        return np.stack([values[key] for key in keys])

    def close(self):
        self.cache.close()
