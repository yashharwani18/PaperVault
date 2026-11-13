from knowledge_library.filename_search import filename_exact

def test_name_or_stem_is_unicode_case_and_punctuation_normalized():
    assert filename_exact(' Operating  Systems Unit 3 ', 'Operating Systems Unit 3.pdf')
    assert filename_exact('OPERATING-systems unit 3.PDF', 'Operating Systems Unit 3.pdf')
    assert filename_exact('Cafe\u0301', 'Café.pdf')
    assert not filename_exact('Lecture 2', 'Lecture 20.pdf')
    assert not filename_exact('  ', 'untitled.pdf')
from knowledge_library.filename_search import observed_modified_at

def test_scanned_modified_date_uses_only_valid_recorded_source_timestamp():
    assert observed_modified_at('123:0') is None
    assert observed_modified_at('123:not-a-time') is None
    assert observed_modified_at('123:1704067200000000000').startswith('2024-01-01T00:00:00')

def test_modified_metadata_belongs_only_to_the_matching_scanned_source():
    import sqlite3
    from pathlib import Path
    from types import SimpleNamespace
    from knowledge_library.filename_search import attach_scanned_modified_times
    db=sqlite3.connect(':memory:');db.row_factory=sqlite3.Row
    db.executescript('CREATE TABLE watched_sources(id TEXT,path TEXT); CREATE TABLE watched_files(source_id TEXT,document_id TEXT,relative_path TEXT,signature TEXT);')
    base=str(Path('C:/sample'));path=str(Path(base)/'a.pdf')
    db.execute('INSERT INTO watched_sources VALUES(?,?)',('s',base))
    db.execute('INSERT INTO watched_files VALUES(?,?,?,?)',('s','d','a.pdf','10:1704067200000000000'))
    docs=[dict(id='d',managed_path=path,source_mode='reference'),dict(id='d',managed_path=str(Path(base)/'other.pdf'),source_mode='reference'),dict(id='d',managed_path=path,source_mode='managed')]
    actual=attach_scanned_modified_times(SimpleNamespace(db=db),docs)
    assert actual[0]['modified_at'].startswith('2024-01-01')
    assert actual[1]['modified_at'] is None and actual[2]['modified_at'] is None
    db.close()
