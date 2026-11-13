"""Rebuild a SQLite backup with real local naming; never write to the source library."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import time
from types import SimpleNamespace
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from knowledge_library import workspace_features as features


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, default=ROOT/'data/pc-prototype/library.sqlite3')
    args = parser.parse_args()
    target = ROOT/'.cache'/('topic-evaluation-'+uuid.uuid4().hex[:8])
    target.mkdir(parents=True)
    source = sqlite3.connect(args.source.resolve().as_uri()+'?mode=ro', uri=True)
    copied = sqlite3.connect(target/'library.sqlite3')
    source.backup(copied)
    copied.row_factory = sqlite3.Row
    copied.execute('PRAGMA foreign_keys=ON')
    def fingerprint():
        h = hashlib.sha256()
        for table in ['documents', 'chunks']:
            for row in copied.execute(f'SELECT * FROM {table} ORDER BY id'):
                h.update(repr(tuple(row)).encode())
        return h.hexdigest()
    before = fingerprint()
    lib = SimpleNamespace(db=copied, documents=lambda: [dict(r) for r in copied.execute('SELECT * FROM documents ORDER BY updated_at DESC,id')])
    naming = features.generate_cluster_name
    count = 0
    def traced_name(*args, **kwargs):
        nonlocal count
        result = naming(*args, **kwargs)
        count += 1
        print(f'Named group {count}: {result}', flush=True)
        return result
    features.generate_cluster_name = traced_name
    started = time.perf_counter()
    try:
        result = features.rebuild_links(lib)
    finally:
        features.generate_cluster_name = naming
    elapsed = time.perf_counter()-started
    docs = lib.documents()
    memberships = {}
    for group in result['folders']:
        if group['name'] != 'Miscellaneous' and group['basis'].startswith('Suggested subject'):
            for key in group['document_ids']:
                memberships.setdefault(key, set()).add(group['name'])
    def topics(filename):
        return set().union(*(memberships.get(d['id'], set()) for d in docs if d['filename']==filename))
    probes = [
        ('Gold_Bull_Run.pdf','Copper_Commodities.pdf',True),
        ('Smart_Tourism.pdf','Gold_Bull_Run.pdf',False),
        ('Smart_Tourism.pdf','Copper_Commodities.pdf',False),
        ('Smart_Tourism.pdf','Cancel_Culture.pdf',False),
        ('Cancel_Culture.pdf','rfc-http.pdf',False),
        ('Smith Chart_2026_vkp+Harish_sir_-5.pdf','Smith Chart_2026_vkp+Harish_sir_-4.pdf',True),
        ('Smith Chart_2026_vkp+Harish_sir_-5.pdf','Olympiad_Flyer.pdf',False),
        ('rfc-9089.pdf','rfc-9088.pdf',True),
        ('VayuRakshak_SIH_SightLine_Format.pptx.pdf','Sub-metre_Lunar_DEM_Generation_and_Validation_from.pdf',False),
    ]
    available = {d['filename'] for d in docs}
    checks = [dict(a=a,b=b,expected=expected,actual=bool(topics(a)&topics(b))) for a,b,expected in probes if a in available and b in available]
    state = json.loads(copied.execute("SELECT value FROM workspace_settings WHERE key='organization.cluster_centroids'").fetchone()[0])
    report = dict(library_copy=str(target), elapsed_s=round(elapsed,2), source_opened_read_only=True,
                  documents_and_chunks_unchanged=before==fingerprint(), checks=checks,
                  checks_passed=sum(c['expected']==c['actual'] for c in checks), checks_total=len(checks),
                  naming_paths=dict(Counter(g['naming']['method'] for g in state['groups'])),
                  naming_reasons=dict(Counter(g['naming']['reason'] for g in state['groups'])),
                  groups=[dict(name=g['name'],count=g['document_count'],basis=g['basis'],
                               examples=[d['filename'] for d in docs if d['id'] in g['document_ids']][:8]) for g in result['folders']],
                  note='Diagnostic pairs, not a held-out quality estimate.')
    copied.close()
    source.close()
    destination = ROOT/'results/topic-grouping-implementation-validation.json'
    destination.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='groups'}),flush=True)
    if not report['documents_and_chunks_unchanged'] or report['checks_passed'] != report['checks_total'] or not checks:
        raise SystemExit('Topic evaluation failed; see '+str(destination))


if __name__ == '__main__':
    main()
