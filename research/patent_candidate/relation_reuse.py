"""R9 conventional dependency controls over a restricted native-path relation.

Every revision is fully parsed first. No OCR savings or source completeness is
claimed. Existing-row dependencies are intentionally weak; the equally scoped
partition control includes newly inserted rows. SQL itself already answers the
fixture queries without a model, so cache hits are not a speedup claim.
"""
from dataclasses import dataclass
import hashlib
import json
import sqlite3

import pymupdf

from research.patent_candidate.relation_support import vector_relations, FIELDS, VALUES


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


@dataclass(frozen=True)
class Snapshot:
    revision: str
    profile: str
    rows: tuple  # (content ID, field, value); all supported paths, full page


def extract_snapshot(path, *, recipe='r9-open-native-path-v1'):
    # The file bytes and parsing input are the same snapshot, avoiding a hash/read race.
    raw = path.read_bytes()
    with pymupdf.open(stream=raw, filetype='pdf') as doc:
        relations = vector_relations(doc[0])
    rows = tuple(sorted({(digest([r['field'], r['value'], r['points']]),
                          r['field'], r['value']) for r in relations}))
    return Snapshot(hashlib.sha256(raw).hexdigest(), digest([recipe, FIELDS, VALUES]), rows)


def partition(snapshot, field):
    return tuple(row for row in snapshot.rows if row[1] == field)


def sql_answer(snapshot, field):
    """Independent ordinary relational control, with DISTINCT value semantics."""
    with sqlite3.connect(':memory:') as conn:
        conn.execute('CREATE TABLE relations(id TEXT PRIMARY KEY, field TEXT, value TEXT)')
        conn.execute('CREATE INDEX by_field ON relations(field)')
        conn.executemany('INSERT INTO relations VALUES(?,?,?)', snapshot.rows)
        values = tuple(row[0] for row in conn.execute(
            'SELECT DISTINCT value FROM relations WHERE field=? ORDER BY value', (field,)))
    return ('unresolved' if not values else 'candidate' if len(values) == 1 else 'ambiguous', values)


def positive_rows_reusable(old, new, field):
    """Deliberately incomplete control: only checks previously observed rows."""
    return old.profile == new.profile and set(partition(old, field)).issubset(new.rows)


def partition_reusable(old, new, field):
    """Ordinary complete key-range dependency, within the supplied relation."""
    return old.profile == new.profile and partition(old, field) == partition(new, field)


def cached_answer(old, new, field, can_reuse):
    reuse = can_reuse(old, new, field)
    return sql_answer(old if reuse else new, field), reuse
