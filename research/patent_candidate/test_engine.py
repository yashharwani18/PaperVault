import sqlite3
import json
import subprocess
import sys

import numpy as np
import pytest

from knowledge_library.bill_amounts import source_amounts
from research.patent_candidate.engine import EvidenceSearch, PAD


def record(id, vector, *, amount='100', field='subtotal', folder='A'):
    text = f'Invoice\n{field.title()}: INR {amount}\n'
    return dict(id=id, folder=folder, page=1, text=text, vector=vector,
                evidence=next(source_amounts(text)))


def finish(engine, job, budget=2):
    for _ in range(10000):
        result = engine.advance(job, exact_budget=budget)
        assert result['exact_reads_slice'] <= budget
        if result['status'] == 'complete':
            return result
    raise AssertionError('Did not finish')


def ids(result):
    return [row['id'] for row in result['hits']]


@pytest.mark.parametrize('seed', range(24))
def test_random_rank_resume_and_repair(tmp_path, seed):
    rng = np.random.default_rng(seed)
    engine = EvidenceSearch(tmp_path/'index.sqlite3', dimension=32)
    query = rng.normal(size=32)
    for i in range(60):
        engine.replace_document(str(i), [record(str(i), rng.normal(size=32),
            folder='A' if i % 2 else 'B', amount='100' if i % 3 else '200')])
    pred = {'folder':'A', 'field':'subtotal', 'value':'100'}
    job = engine.start(query, predicate=pred, k=5)
    first = engine.advance(job, exact_budget=1)
    assert first['status'] == 'pending'
    for i in range(10):
        engine.replace_document(str(i), [record(str(i), rng.normal(size=32), amount='100')])
    engine.replace_document('20', [])
    engine.replace_document('new', [record('new', query)])
    result = finish(engine, job)
    assert ids(result) == engine.exhaustive(query, pred)
    assert engine.current(result)
    engine.close()


def test_previously_excluded_document_reenters_and_old_receipt_expires(tmp_path):
    engine = EvidenceSearch(tmp_path/'index.sqlite3', 2)
    engine.replace_document('old', [record('old', [0.8, 0.6])])
    engine.replace_document('hidden', [record('hidden', [1, 0], amount='200')])
    pred = {'field':'subtotal', 'value':'100'}
    job = engine.start([1,0], predicate=pred, k=1)
    result = finish(engine, job)
    assert ids(result) == ['old']
    engine.replace_document('hidden', [record('hidden', [1,0])])
    assert not engine.current(result)
    repaired = finish(engine, job)
    assert ids(repaired) == ['hidden']
    assert repaired['coarse_total'] == 2  # No rescore of unchanged old source.
    engine.close()


def test_removed_winner_reopens_old_pruned_frontier(tmp_path):
    engine = EvidenceSearch(tmp_path/'index.sqlite3', 2)
    engine.replace_document('one', [record('one', [1,0])])
    engine.replace_document('two', [record('two', [0.5,0.8])])
    job = engine.start([1,0], k=1)
    assert ids(finish(engine, job)) == ['one']
    engine.replace_document('one', [])
    assert ids(finish(engine, job)) == ['two']
    engine.close()


def test_process_reopen_and_zero_budget(tmp_path):
    path = tmp_path/'index.sqlite3'
    engine = EvidenceSearch(path, 2)
    engine.replace_document('d', [record('b',[1,0]),record('a',[1,0])])
    job = engine.start([1,0], k=1)
    assert engine.advance(job,exact_budget=0)['status'] == 'pending'
    engine.advance(job,exact_budget=1)
    engine.close()
    engine = EvidenceSearch(path, 2)
    result = finish(engine, job, 1)
    assert ids(result) == ['a']  # Stable ID tie break, not first refined row.
    assert result['exact_reads_total'] == 2
    engine.close()


def test_atomic_failed_replacement(tmp_path):
    engine = EvidenceSearch(tmp_path/'index.sqlite3', 2)
    engine.replace_document('d', [record('ok',[1,0])])
    epoch = engine.epoch()
    broken = record('broken',[1,0]); broken['text'] = 'No financial evidence'
    with pytest.raises(ValueError, match='Evidence'):
        engine.replace_document('d',[broken])
    assert engine.epoch() == epoch
    assert engine.exhaustive([1,0]) == ['ok']
    engine.close()


@pytest.mark.parametrize('pred', [
    {'field':'total','value':'100'}, {'field':'subtotal','value':'200'},
    {'field':'subtotal','value':'100','currency':'USD'}, {'folder':'B'}])
def test_field_amount_currency_scope_do_not_fallback(tmp_path, pred):
    engine = EvidenceSearch(tmp_path/'index.sqlite3', 2)
    engine.replace_document('d',[record('a',[1,0])])
    result = finish(engine,engine.start([1,0], predicate=pred))
    assert result['status'] == 'complete' and result['hits'] == []
    assert result['exact_reads_total'] == 0
    engine.close()


def test_vector_integrity_failure_rolls_back_slice(tmp_path):
    engine = EvidenceSearch(tmp_path/'index.sqlite3', 2)
    engine.replace_document('d',[record('a',[1,0])])
    job = engine.start([1,0])
    with engine.db:
        engine.db.execute('UPDATE sources SET vector=?', (b'corrupt',))
    with pytest.raises(ValueError,match='revision mismatch'):
        engine.advance(job,exact_budget=1)
    assert engine.db.execute('SELECT reads FROM jobs').fetchone()[0] == 0
    engine.close()


@pytest.mark.parametrize('vector', [[0,0], [float('nan'),1], [1,2,3]])
def test_invalid_vectors_rejected(tmp_path, vector):
    engine = EvidenceSearch(tmp_path/'index.sqlite3', 2)
    with pytest.raises(ValueError):
        engine.start(vector)
    engine.close()


def test_bound_encloses_real_scores(tmp_path):
    rng = np.random.default_rng(9201)
    engine = EvidenceSearch(tmp_path/'index.sqlite3',128)
    engine.replace_document('d',(record(str(i),rng.normal(size=128)) for i in range(100)))
    for _ in range(10):
        q = rng.normal(size=128)
        job = engine.start(q)
        from research.patent_candidate.engine import normalized
        query = normalized(q,128).astype(np.float64)
        for row in engine.db.execute('SELECT s.vector,f.upper FROM sources s JOIN frontier f ON s.id=f.id WHERE f.job=?',(job,)):
            score = float(query @ np.frombuffer(row['vector'],dtype='<f4').astype(np.float64))
            assert score <= row['upper'] + PAD
    engine.close()


def test_writer_locked_during_slice_transaction(tmp_path):
    path = tmp_path/'index.sqlite3'
    engine = EvidenceSearch(path,2)
    other = sqlite3.connect(path,timeout=0)
    engine.db.execute('BEGIN IMMEDIATE')
    with pytest.raises(sqlite3.OperationalError,match='locked'):
        other.execute("INSERT INTO changes(doc) VALUES('race')")
    other.rollback(); engine.db.rollback()
    other.close(); engine.close()


def test_repeated_edits_and_scope_changes_match_oracle(tmp_path):
    engine=EvidenceSearch(tmp_path/'index.sqlite3',16)
    rng=np.random.default_rng(71823)
    q=rng.normal(size=16)
    pred={'folder':'A','field':'subtotal','value':'100'}
    for i in range(40):
        engine.replace_document(str(i),[record(str(i),rng.normal(size=16))])
    job=engine.start(q,predicate=pred,k=3)
    for cycle in range(100):
        doc=str(int(rng.integers(0,40)))
        if cycle%7==0:
            engine.replace_document(doc,[])
        else:
            engine.replace_document(doc,[record(doc,rng.normal(size=16),
                folder='B' if cycle%3==0 else 'A', amount='200' if cycle%4==0 else '100')])
        result=finish(engine,job,budget=1)
        assert ids(result)==engine.exhaustive(q,pred,k=3)
    engine.close()


def test_near_ties_require_full_refinement(tmp_path):
    engine=EvidenceSearch(tmp_path/'index.sqlite3',16)
    vector=np.arange(1,17,dtype=np.float32)
    engine.replace_document('d',(record(f'{i:03}',vector) for i in range(200)))
    job=engine.start(vector,k=5)
    pending=engine.advance(job,exact_budget=10)
    assert pending['status']=='pending'
    done=finish(engine,job,budget=10)
    assert done['exact_reads_total']==200
    assert ids(done)==[f'{i:03}' for i in range(5)]
    engine.close()


def test_resume_in_a_separate_process(tmp_path):
    path=tmp_path/'index.sqlite3'
    engine=EvidenceSearch(path,2)
    engine.replace_document('d',[record('one',[1,0]),record('two',[0,1])])
    job=engine.start([1,0],k=1)
    engine.advance(job,exact_budget=0)
    engine.close()
    script='''import json,sys
from research.patent_candidate.engine import EvidenceSearch
engine=EvidenceSearch(sys.argv[1],2)
result=engine.advance(sys.argv[2],exact_budget=2)
print(json.dumps({'status':result['status'],'ids':[r['id'] for r in result['hits']]}))
engine.close()
'''
    output=subprocess.check_output([sys.executable,'-c',script,str(path),job],text=True)
    assert json.loads(output)=={'status':'complete','ids':['one']}
