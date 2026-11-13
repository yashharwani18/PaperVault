"""Actual PowerPoint conversion, inference, original-source recovery and backup."""
import hashlib
import io
import json
from pathlib import Path
import zipfile
import pymupdf
import pytest
from knowledge_library.presentations import available,convert
from knowledge_library.maintenance import restore_backup,schema
from knowledge_library.library import Library
from tests.test_desktop import session,upload,FIX


@pytest.mark.skipif(not available(),reason='Microsoft PowerPoint is not installed')
def test_actual_powerpoint_slide_search_and_original_backup(session,tmp_path):
    client,desktop=session;source=FIX/'presentations/college-toc-test.pptx';before=hashlib.sha256(source.read_bytes()).hexdigest()
    folder=client.post('/api/folders',json={'name':'College PPTX regression'}).json()['id']
    jobs=upload(client,folder,[source]);assert jobs[0]['status']=='completed',jobs
    doc=jobs[0]['result']['document'];assert doc['filename']==source.name and doc['page_count']==3
    original=client.get(f'/api/documents/{doc["id"]}/original');assert original.status_code==200 and hashlib.sha256(original.content).hexdigest()==before
    assert hashlib.sha256(source.read_bytes()).hexdigest()==before
    rendered=client.get(f'/api/documents/{doc["id"]}/file')
    with pymupdf.open(stream=rendered.content,filetype='pdf') as pdf:
        assert pdf.page_count==3 and 'Hidden slide' in pdf[1].get_text() and 'Pumping lemma' in pdf[2].get_text()
    result=client.post('/api/search',json={'query':'How can I prove that a language is not regular using the pumping lemma?','folder_id':folder}).json()
    assert result['results'] and result['results'][0]['page_number']==3,result
    calls=desktop.model.stats['document_texts_encoded']
    assert upload(client,folder,[source])[0]['result']['document_embeddings_generated']==0
    assert desktop.model.stats['document_texts_encoded']==calls
    deleted=client.delete('/api/documents/'+doc['id']).json()
    archive=client.post('/api/backup');assert archive.status_code==200
    with zipfile.ZipFile(io.BytesIO(archive.content)) as z:assert any(n.startswith('originals/') and n.endswith('.pptx') for n in z.namelist())
    backup=tmp_path/'backup.zip';backup.write_bytes(archive.content)
    with desktop.lib() as lib:trusted=schema(lib)
    restored=restore_backup(backup,tmp_path/'restored',desktop.model,trusted_schema=trusted)
    from knowledge_library.maintenance import restore_document,initialize
    with Library(restored['path'],desktop.model) as lib:
        initialize(lib);restore_document(lib,deleted['trash_id'])
        stored=lib.db.execute('SELECT * FROM document_sources').fetchone()
        assert hashlib.sha256((lib.root/stored['source_path']).read_bytes()).hexdigest()==before
    assert client.post('/api/trash/'+deleted['trash_id']+'/restore',json={}).status_code==200
    assert client.get(f'/api/documents/{doc["id"]}/original').content==source.read_bytes()


def test_invalid_batch_does_not_queue_earlier_files(session):
    client,desktop=session;folder=client.post('/api/folders',json={'name':'Atomic upload selection'}).json()['id']
    before=len(client.get('/api/state').json()['tasks'])
    r=client.post('/api/uploads',data={'folder_id':folder},files=[('files',('good.pdf',(FIX/'pdfs/native-unicode.pdf').read_bytes(),'application/pdf')),('files',('bad.exe',b'not-a-pdf','application/octet-stream'))])
    assert r.status_code==400 and len(client.get('/api/state').json()['tasks'])==before


@pytest.mark.skipif(not available(),reason='Microsoft PowerPoint is not installed')
def test_bad_pptx_and_macro_container_rejected(tmp_path):
    source=tmp_path/'damaged.pptx';source.write_bytes(b'not a presentation')
    with pytest.raises(ValueError,match='damaged or password'):convert(source,tmp_path/'library')
    with zipfile.ZipFile(source,'w') as archive:
        archive.writestr('[Content_Types].xml','x');archive.writestr('ppt/presentation.xml','x');archive.writestr('ppt/vbaProject.bin',b'not executed')
    with pytest.raises(ValueError,match='Macro-containing'):convert(source,tmp_path/'library')


def test_direct_pptx_fallback_without_powerpoint(monkeypatch,tmp_path):
    import knowledge_library.presentations as pres
    monkeypatch.setattr(pres,'_powerpoint_com_available',lambda:False)
    source=FIX/'presentations/college-toc-test.pptx'
    out_pdf,meta=pres.convert(source,tmp_path/'library')
    assert meta['converter']=='direct_pptx_xml'
    assert meta['slides']==3
    with pymupdf.open(out_pdf) as pdf:
        assert pdf.page_count==3
        assert 'Theory of computation' in pdf[0].get_text()
        assert 'Hidden slide' in pdf[1].get_text()
        assert 'Pumping lemma' in pdf[2].get_text()

