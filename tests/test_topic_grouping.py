"""Behavioral regressions for coherent suggested topics, independent of model inference."""
import json
import sqlite3
from types import SimpleNamespace

import numpy as np
import pytest

from knowledge_library import organization as org
from knowledge_library import workspace_features as features


def examples():
    vectors = {}
    docs = []
    for key, coords, title in [
        ('a', [.8, .6, 0], 'Copper commodity markets'),
        ('b', [.8, .59, .01], 'Gold commodity markets'),
        ('c', [.8, -.6, 0], 'Smith chart impedance'),
        ('d', [.8, -.59, -.01], 'Smith chart impedance'),
        ('e', [0, 0, 1], 'Tourism destinations'),
    ]:
        v = np.array(coords + [0] * 5, dtype=np.float32)
        vectors[key] = v / np.linalg.norm(v)
        docs.append(dict(id=key, sha256=key, title=title, filename=title+'.pdf'))
    return docs, vectors


def test_topics_keep_neighbors_and_abstain_on_unrelated_document():
    from knowledge_library.topic_grouping import fit_topics
    docs, vectors = examples()
    state = fit_topics(docs, vectors)
    assert {frozenset(g['document_ids']) for g in state['groups']} == {frozenset('ab'), frozenset('cd')}
    assert state == fit_topics(list(reversed(docs)), vectors)


def test_identical_copies_do_not_create_a_topic_but_distinct_close_documents_do():
    from knowledge_library.topic_grouping import fit_topics
    docs, vectors = examples()
    docs[1]['sha256'] = docs[0]['sha256']
    state = fit_topics(docs[:2], vectors)
    assert not state['groups']
    docs[1]['sha256'] = 'different'
    assert len(fit_topics(docs[:2], vectors)['groups']) == 1


def test_invalid_vectors_are_rejected_without_poisoning_other_groups():
    from knowledge_library.topic_grouping import fit_topics
    docs, vectors = examples()
    vectors['e'] = np.full(8, np.nan)
    docs += [dict(id='bad', sha256='bad')]
    vectors['bad'] = np.zeros(8)
    state = fit_topics(docs, vectors)
    assert {frozenset(g['document_ids']) for g in state['groups']} == {frozenset('ab'), frozenset('cd')}
    assert np.isfinite(state['mean']).all()


def test_incremental_assignment_reuses_transform_and_rejects_old_or_ambiguous_state():
    from knowledge_library.topic_grouping import fit_topics, match_topic
    docs, vectors = examples()
    state = fit_topics(docs, vectors)
    for i, group in enumerate(state['groups']):
        group['name'] = f'Topic {i}'
    assert match_topic(state, vectors['a'], source_hash='a') == state['groups'][0]['name']
    assert match_topic(state, vectors['e'], source_hash='changed') is None
    assert match_topic([], vectors['a']) is None
    assert match_topic({'version': -1}, vectors['a']) is None
    assert match_topic(state, np.ones(3)) is None
    assert match_topic(state, np.full(8, np.inf)) is None
    state['groups'].append({**state['groups'][0], 'name': 'Ambiguous alternative'})
    assert match_topic(state, vectors['a']) is None


def test_pairwise_resource_bound_is_checked_before_allocating(monkeypatch):
    from knowledge_library import topic_grouping as grouping
    docs, vectors = examples()
    monkeypatch.setattr(grouping, 'MAX_DOCUMENTS', 3)
    with pytest.raises(grouping.TopicCapacityError):
        grouping.fit_topics(docs, vectors)


def test_incremental_assignment_cannot_violate_fitted_pairwise_distance():
    from knowledge_library.topic_grouping import fit_topics, match_topic
    def vector(degrees):
        angle = np.deg2rad(degrees)
        return np.array([np.cos(angle), np.sin(angle)] + [0]*6, dtype=np.float32)
    docs = [dict(id=str(i), sha256=str(i)) for i in [0,30,31]]
    state = fit_topics(docs, {d['id']: vector(int(d['id'])) for d in docs})
    assert len(state['groups']) == 1
    state['groups'][0]['name'] = 'Known subject'
    assert match_topic(state, vector(40)) is None
    assert match_topic(state, vector(15)) == 'Known subject'


def test_naming_examples_include_distinct_sources_not_duplicate_copies():
    docs = [dict(id=str(i),sha256='same',title='Representative subject',filename='same.pdf',topic_excerpt='First subject evidence') for i in range(3)]
    docs.append(dict(id='different',sha256='different',title='Second subject',filename='other.pdf',topic_excerpt='Second subject evidence'))
    calls = []
    def generate(system, prompt, schema, **kwargs):
        calls.append(prompt)
        return {'topic':'Shared Subject'},0
    qi = SimpleNamespace(status=lambda:{'available':True}, generate=generate)
    features.generate_cluster_name(docs, docs[0], qi)
    assert calls and 'Second subject' in calls[0]
    assert calls[0].count('Representative subject') == 1


def test_readable_titles_are_not_drowned_by_content_in_small_naming_model():
    docs = [dict(id='gold',sha256='gold',title='Gold_Bull_Run',topic_excerpt='Long content about gold only.'),
            dict(id='copper',sha256='copper',title='Copper_Commodities',topic_excerpt='Long content about copper only.')]
    calls = []
    def generate(system, prompt, schema, **kwargs):
        calls.append(prompt)
        return {'topic':'Commodity Markets'},0
    qi = SimpleNamespace(status=lambda:{'available':True}, generate=generate)
    assert features.generate_cluster_name(docs, docs[0], qi) == 'Commodity Markets'
    assert 'Long content' not in calls[0]
    assert 'Gold_Bull_Run' in calls[0] and 'Copper_Commodities' in calls[0]


def test_fallback_names_require_distinct_source_support():
    docs = [dict(id=str(i),sha256='same',title='Smith Chart',filename='smith.pdf') for i in range(4)]
    docs.append(dict(id='other',sha256='other',title='Impedance matching',filename='matching.pdf'))
    assert features.generate_cluster_name(docs, docs[0]) == 'Miscellaneous'


@pytest.fixture
def library(monkeypatch):
    db = sqlite3.connect(':memory:')
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    db.executescript('''CREATE TABLE documents(id TEXT PRIMARY KEY,sha256 TEXT);
        CREATE TABLE chunks(document_id,vector,dimensions);
        CREATE TABLE pages(document_id,page_number,text,status);
        CREATE TABLE bill_records(document_id,party,party_normalized,source_sha256);''')
    docs, vectors = examples()
    for d in docs:
        db.execute('INSERT INTO documents VALUES (?,?)', (d['id'], d['sha256']))
        db.execute('INSERT INTO chunks VALUES (?,?,8)', (d['id'], vectors[d['id']].astype('<f4').tobytes()))
        db.execute('INSERT INTO pages VALUES (?,1,?,?)', (d['id'], d['title'], 'ok'))
    lib = SimpleNamespace(db=db, documents=lambda: docs, document=lambda key: next(d for d in docs if d['id']==key), _name=lambda s: s.strip())
    features.initialize(lib)
    monkeypatch.setattr('knowledge_library.query_interpreter.QueryInterpreter', lambda: SimpleNamespace(status=lambda: {'available': False}))
    yield lib
    db.close()


def test_rebuild_does_not_force_outlier_into_group_and_records_naming_path(library):
    report = features.rebuild_links(library)
    groups = {g['name']: set(g['document_ids']) for g in report['folders']}
    assert groups['Miscellaneous'] == {'e'}
    assert {'a', 'b'} in groups.values() and {'c', 'd'} in groups.values()
    state = json.loads(library.db.execute("SELECT value FROM workspace_settings WHERE key='organization.cluster_centroids'").fetchone()[0])
    assert state['version'] == 1 and len(state['groups']) == 2
    assert all(g['naming']['method'] == 'extractive' for g in state['groups'])
    assert features.document_subjects(library, library.document('e')) == {'Miscellaneous'}


def test_equal_generated_names_do_not_merge_distant_components(library, monkeypatch):
    monkeypatch.setattr(features, 'generate_cluster_name', lambda *a, **k: 'Shared Broad Name')
    report = features.rebuild_links(library)
    groups = [set(g['document_ids']) for g in report['folders'] if g['name']!='Miscellaneous']
    assert {'a','b'} in groups and {'c','d'} in groups
    assert not any({'a','c'} <= members for members in groups)


def test_rebuild_preserves_retired_automatic_topic_corrections(library):
    library.db.execute("INSERT INTO linked_folders VALUES ('retired','Earlier automatic topic','Suggested subject from embeddings','yesterday')")
    org.rename_topic(library, 'retired', 'My research')
    org.set_topics(library, ['e'], ['retired'])
    features.rebuild_links(library)
    assert org.document_info(library, 'e')['topic_ids'] == ['retired']
    assert next(t for t in org.topics(library) if t['id']=='retired')['name'] == 'My research'


def test_failed_publication_rolls_back_groups_and_transform(library, monkeypatch):
    features.rebuild_links(library)
    def snapshot():
        return [[tuple(r) for r in library.db.execute(f'SELECT * FROM {table} ORDER BY 1,2')] for table in ['linked_folders','linked_members','workspace_settings']]
    before = snapshot()
    def fail(*args, **kwargs):
        raise RuntimeError('interrupted publication')
    monkeypatch.setattr(org, 'reapply', fail)
    with pytest.raises(RuntimeError, match='interrupted'):
        features.rebuild_links(library)
    assert snapshot() == before


def test_corrupt_chunk_does_not_crash_vector_loading(library):
    library.db.execute("UPDATE chunks SET vector=? WHERE document_id='e'", (b'invalid',))
    vectors, dims = features.get_document_vectors(library)
    assert 'e' not in vectors and dims == 8 and len(vectors) == 4
