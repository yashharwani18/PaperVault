from pathlib import Path
import tempfile
import pytest
import numpy as np
from knowledge_library.library import Library
from tests.test_research_implementation import CountingEncoder
from knowledge_library import maintenance

class SearchEncoder(CountingEncoder):
    dimensions=128
    def documents(self,title,texts):
        self.stats["document_texts_encoded"]+=len(texts)
        vector=np.zeros(128,dtype="<f4");vector[0]=1
        return [vector.copy() for _ in texts]

@pytest.fixture
def work():
    root=Path(__file__).resolve().parents[1]/'.cache'/'text-library-tests'
    root.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(dir=root) as directory:yield Path(directory)

def test_native_import_refresh_locations_and_backup(work):
    path=work/'notes.md';path.write_text('# Launch\n\nThe zephyr launch checklist contains precise source evidence.',encoding='utf-8')
    with Library(work/'library',SearchEncoder()) as lib:
        folder=lib.create_folder('Notes')['id']
        with pytest.raises(ValueError):lib.import_pdf(path,folder)
        doc=lib.import_document(path,folder)['document'];key=doc['id']
        assert doc['source_kind']=='text' and doc['source_format']=='md'
        assert lib.source_path(doc).suffix=='.md'
        unit=lib.page(key,1)
        assert unit['unit_number']==1 and unit['location_label'] and unit['evidence']['frame']=='source_text'
        assert lib.page_summary(key)[0]['location']==unit['location']
        hit=lib.search('zephyr',mode='keyword')['results'][0]
        assert hit['location_label']==lib.page(key,hit['page_number'])['location_label'] and '#page=' not in hit['open_uri']
        from knowledge_library.export import context_pdf
        exported=context_pdf(lib,'zephyr',[hit['chunk_id']],work/'context.pdf')
        assert exported[0]['location_label']==hit['location_label']
        assert lib.refresh(key)['action']=='unchanged'
        assert lib.verify()['passed']
        maintenance.initialize(lib)
        trash=maintenance.trash_document(lib,key)
        restored=maintenance.restore_document(lib,trash['trash_id'])
        assert restored['source_format']=='md'
        archive=maintenance.backup(lib)
        report=maintenance.restore_backup(archive,work/'restored',CountingEncoder(),trusted_schema=maintenance.schema(lib))
        assert report['integrity']['passed']
        orphan=lib.root/'files'/'orphan.csv';orphan.write_text('a,b')
        unknown=lib.root/'files'/'keep.exe';unknown.write_bytes(b'keep')
        assert maintenance.storage(lib)['orphan_files']==1
        assert maintenance.cleanup(lib)['removed_files']==1 and unknown.exists()

def test_failed_native_replacement_and_reference_validation(work):
    path=work/'notes.txt';path.write_text('Original zephyr source evidence.',encoding='utf-8')
    model=SearchEncoder()
    with Library(work/'library',model) as lib:
        folder=lib.create_folder('Notes')['id']
        doc=lib.import_document(path,folder,retain_source=False)['document']
        assert lib.source_path(doc)==path
        before=[tuple(r) for r in lib.db.execute('SELECT * FROM chunks')]
        path.write_text('Changed zephyr source evidence.',encoding='utf-8')
        assert not lib.verify()['passed']
        def fail(*args):raise InterruptedError('simulated embedding failure')
        model.documents=fail
        with pytest.raises(InterruptedError):lib.import_document(path,folder,document_id=doc['id'])
        assert lib.document(doc['id'])['sha256']==doc['sha256']
        assert [tuple(r) for r in lib.db.execute('SELECT * FROM chunks')]==before


def test_native_later_batch_failure_does_not_publish_first_units(work):
    path=work/'notes.md'
    def content(word):return '\n\n'.join(f'{word} paragraph {n} has unique source content.' for n in range(12))
    path.write_text(content('Original'),encoding='utf-8')
    model=SearchEncoder()
    with Library(work/'library',model) as lib:
        folder=lib.create_folder('Notes')['id']
        doc=lib.import_document(path,folder)['document']
        assert doc['title']=='notes'
        before=[tuple(r) for r in lib.db.execute('SELECT * FROM chunks ORDER BY id')]
        path.write_text(content('Changed'),encoding='utf-8')
        encode=model.documents;calls=0
        def later_failure(title,texts):
            nonlocal calls
            calls+=1
            if calls==3:raise InterruptedError('interrupted after first five units')
            return encode(title,texts)
        model.documents=later_failure
        with pytest.raises(InterruptedError):lib.import_document(path,folder,document_id=doc['id'])
        assert calls==3
        assert lib.document(doc['id'])['version']==doc['version']
        assert [tuple(r) for r in lib.db.execute('SELECT * FROM chunks ORDER BY id')]==before
        assert lib.verify()['passed']

@pytest.mark.parametrize('suffix,text',[('.txt','Zephyr plain lines.\nAnother line.'),('.csv','name,value\nZephyr,42'),('.tsv','name\tvalue\nZephyr\t42'),('.html','<h1>Zephyr</h1><p>Launch details</p>')])
def test_native_format_storage_and_validation(work,suffix,text):
    path=work/('source'+suffix);path.write_text(text,encoding='utf-8')
    with Library(work/'library',SearchEncoder()) as lib:
        folder=lib.create_folder('Notes')['id']
        doc=lib.import_document(path,folder)['document']
        assert doc['source_format']==suffix[1:] and lib.source_path(doc).suffix==suffix
        assert lib.verify()['passed']
        assert lib.refresh(doc['id'])['action']=='unchanged'


def test_native_reconnect_preserves_source_identity(work):
    from knowledge_library.recovery import reconnect
    path=work/'notes.txt';path.write_text('Original source evidence.',encoding='utf-8')
    with Library(work/'library',SearchEncoder()) as lib:
        folder=lib.create_folder('Notes')['id']
        doc=lib.import_document(path,folder,retain_source=False)['document']
        moved=work/'relocated.txt';path.rename(moved)
        assert reconnect(lib,doc['id'],moved)['reconnected']
        assert lib.source_path(lib.document(doc['id']),verify=True)==moved
        wrong=work/'wrong.txt';wrong.write_text('Different bytes',encoding='utf-8')
        with pytest.raises(ValueError,match='same document'):reconnect(lib,doc['id'],wrong)
        assert lib.verify()['passed']


def test_empty_native_recovery_does_not_offer_pdf_ocr(work):
    from knowledge_library.recovery import document_health
    path=work/'empty.txt';path.write_text('',encoding='utf-8')
    with Library(work/'library',SearchEncoder()) as lib:
        folder=lib.create_folder('Notes')['id']
        doc=lib.import_document(path,folder)['document']
        health=document_health(lib,doc['id'])
        assert health['extraction']['code']=='empty'
        assert 'PDF' not in health['extraction']['message'] and 'OCR' not in health['extraction']['message']
        assert lib.verify()['passed']


def test_native_backup_rejects_windows_stream_paths_before_writing(work):
    import hashlib,json,zipfile
    archive=work/'unsafe.zip';files={'library.sqlite3':b'', 'files/source:stream.txt':b'text'}
    with zipfile.ZipFile(archive,'w') as output:
        output.writestr('manifest.json',json.dumps(dict(format='local-library-backup-v1',files={name:hashlib.sha256(data).hexdigest() for name,data in files.items()})))
        for name,data in files.items():output.writestr(name,data)
    destination=work/'restored'
    with pytest.raises(ValueError,match='Invalid backup path'):
        maintenance.restore_backup(archive,destination,SearchEncoder(),trusted_schema={})
    assert not destination.exists()


def test_browse_indexes_are_used_and_older_backups_remain_restorable(work):
    from knowledge_library.workspace_features import initialize as initialize_workspace
    from knowledge_library.maintenance import initialize as initialize_maintenance
    with Library(work/'library',SearchEncoder()) as lib:
        initialize_workspace(lib);initialize_maintenance(lib)
        indexes={r['name'] for r in lib.db.execute("PRAGMA index_list(documents)")}
        expected={'documents_browse_updated','documents_browse_added','documents_browse_size','documents_browse_folder_added'}
        assert expected <= indexes
        plan=' '.join(str(r['detail']) for r in lib.db.execute("EXPLAIN QUERY PLAN SELECT id FROM documents ORDER BY updated_at DESC,id LIMIT 100"))
        assert 'documents_browse_updated' in plan and 'TEMP B-TREE' not in plan
        trusted=maintenance.schema(lib)
        for name in expected:lib.db.execute('DROP INDEX '+name)
        archive=maintenance.backup(lib)
    report=maintenance.restore_backup(archive,work/'restored-old',CountingEncoder(),trusted_schema=trusted)
    assert report['integrity']['passed']
    with Library(work/'restored-old',SearchEncoder()) as restored:
        assert expected <= {r['name'] for r in restored.db.execute('PRAGMA index_list(documents)')}
