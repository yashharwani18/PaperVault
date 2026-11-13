"""Storage/ranking equivalence checks; synthetic vectors make no quality claim."""
import hashlib
import sqlite3
from types import SimpleNamespace
import numpy as np
import pytest
from knowledge_library.retrieval import SearchIndex


@pytest.fixture
def library():
    db=sqlite3.connect(':memory:');db.row_factory=sqlite3.Row
    db.executescript('''
      CREATE TABLE chunks(id INTEGER PRIMARY KEY,document_id TEXT,page_number INTEGER,text TEXT,dimensions INTEGER,vector BLOB,vector_sha256 TEXT);
      CREATE TABLE documents(id TEXT,filename TEXT,managed_path TEXT,status TEXT,folder_id TEXT);
      CREATE TABLE folders(id TEXT,name TEXT);
      CREATE TABLE pages(document_id TEXT,page_number INTEGER,page_label TEXT,method TEXT,warnings TEXT);
      INSERT INTO folders VALUES('f','Notes');
      INSERT INTO documents VALUES('a','notes.pdf','notes.pdf','indexed','f');
    ''')
    for i in range(12):
        v=np.zeros(128,dtype='<f4');v[i]=1;blob=v.tobytes()
        db.execute('INSERT INTO chunks VALUES(?,?,?,?,?,?,?)',(i+1,'a',i//2+1,'signal filters '+str(i),128,blob,hashlib.sha256(blob).hexdigest()))
    for i in range(6):db.execute("INSERT INTO pages VALUES('a',?,?, 'native','[]')",(i+1,str(i+1)))
    db.commit()
    yield SimpleNamespace(db=db)
    db.close()


def test_compact_snapshot_streams_vectors_and_hydrates_only_selected_results(library):
    full=SearchIndex(library);compact=SearchIndex(library,compact=True)
    assert np.array_equal(full.matrix,compact.matrix)
    assert all('vector' not in row and 'text' not in row and 'filename' not in row for row in compact.rows)
    query=np.arange(1,129,dtype=np.float32)
    assert full.semantic(query,128)==compact.semantic(query,128)
    assert full.lexical('filters',mode='keyword')==compact.lexical('filters',mode='keyword')
    for i,_ in compact.semantic(query,128)[:3]:assert compact.result_row(i)==full.rows[i]
    assert SearchIndex(library,where=['d.id=?'],parameters=['missing'],compact=True).rows==[]


def test_compact_lexical_snapshot_does_not_read_embedding_blobs(library):
    selected=[]
    library.db.set_authorizer(lambda action,arg1,arg2,*rest: (selected.append(arg2) or sqlite3.SQLITE_OK) if action==sqlite3.SQLITE_READ and arg1=='chunks' else sqlite3.SQLITE_OK)
    compact=SearchIndex(library,compact=True,vectors=False)
    assert 'vector' not in selected and 'vector_sha256' not in selected
    assert compact.lexical('filters',mode='keyword')==SearchIndex(library,vectors=False).lexical('filters',mode='keyword')


@pytest.mark.parametrize('corruption',['checksum','size','norm','nonfinite'])
def test_compact_snapshot_keeps_vector_integrity_checks(library,corruption):
    values=np.zeros(128,dtype='<f4');values[0]=1
    if corruption=='norm':values[0]=2
    if corruption=='nonfinite':values[0]=np.nan
    blob=values.tobytes() if corruption!='size' else b'short'
    checksum=hashlib.sha256(blob).hexdigest() if corruption!='checksum' else 'bad'
    library.db.execute('UPDATE chunks SET vector=?,vector_sha256=? WHERE id=1',(blob,checksum))
    with pytest.raises(ValueError):SearchIndex(library,compact=True)


def test_new_compact_snapshot_observes_updates_and_removals(library):
    first=SearchIndex(library,compact=True)
    library.db.execute("UPDATE chunks SET text='changed passage' WHERE id=1")
    library.db.execute('DELETE FROM chunks WHERE id=2')
    current=SearchIndex(library,compact=True)
    assert len(current.rows)==len(first.rows)-1
    assert current.result_row(0)['text']=='changed passage'


def test_result_hydration_stays_in_same_wal_snapshot_during_index_commit(library,tmp_path):
    path=tmp_path/'index.sqlite3'
    writer=sqlite3.connect(path);library.db.backup(writer);writer.execute('PRAGMA journal_mode=WAL')
    reader=sqlite3.connect(path);reader.row_factory=sqlite3.Row
    try:
        reader.execute('BEGIN')
        index=SearchIndex(SimpleNamespace(db=reader),compact=True)
        with writer:
            writer.execute('DELETE FROM chunks WHERE id=1')
            writer.execute("UPDATE folders SET name='Renamed'")
        assert index.result_row(0)['text']=='signal filters 0'
        assert index.result_row(0)['folder_name']=='Notes'
        reader.rollback()
        reader.execute('BEGIN')
        current=SearchIndex(SimpleNamespace(db=reader),compact=True)
        assert current.rows[0]['id']==2 and current.result_row(0)['folder_name']=='Renamed'
    finally:reader.close();writer.close()

def test_literal_ranking_keeps_exact_matches_when_many_partial_matches_exist(library):
    library.db.execute('CREATE VIRTUAL TABLE chunks_fts USING fts5(text)')
    library.db.executemany('INSERT INTO chunks_fts(rowid,text) VALUES(?,?)',[(r['id'],r['text']) for r in library.db.execute('SELECT id,text FROM chunks')])
    library.db.execute("UPDATE chunks SET text='shortest unrelated notes' WHERE id<12")
    library.db.execute("UPDATE chunks_fts SET text='shortest unrelated notes' WHERE rowid<12")
    library.db.execute("UPDATE chunks SET text='shortest path algorithms' WHERE id=12")
    library.db.execute("UPDATE chunks_fts SET text='shortest path algorithms' WHERE rowid=12")
    index=SearchIndex(library,compact=True,vectors=False)
    ranked=index.rank('shortest-path',mode='literal')
    assert [index.result_row(i)['id'] for i,_ in ranked]==[12]
