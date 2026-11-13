import sqlite3
from types import SimpleNamespace
import pymupdf
import pytest
from knowledge_library.library import Library
from knowledge_library import workspace_features as topics
from knowledge_library.search_response import respond
from tests.test_research_implementation import CountingEncoder


def pdf(path,text):
    with pymupdf.open() as doc:
        doc.new_page().insert_text((40,60),text)
        doc.save(path)


def test_reference_import_refresh_and_missing_source_never_copy_or_delete(tmp_path):
    source=tmp_path/'notes.pdf';pdf(source,'Unclassified original source with searchable text.')
    with Library(tmp_path/'library',CountingEncoder()) as lib:
        doc=lib.import_pdf(source,lib.create_folder('Notes')['id'],retain_source=False)['document']
        assert doc['source_mode']=='reference' and lib.source_path(doc,verify=True)==source
        assert not list((lib.root/'files').glob('*.pdf'))
        assert not list((lib.root/'staging').glob('*.pdf'))
        pdf(source,'Revised source with different and longer searchable text.')
        with pytest.raises(ValueError,match='changed'):lib.source_path(doc,verify=True)
        updated=lib.refresh(doc['id'])['document']
        assert updated['source_mode']=='reference' and not list((lib.root/'files').glob('*.pdf'))
        assert lib.verify()['passed']
        source.unlink()
        assert lib.page(doc['id'],1)['text']
        assert lib.sync()[0]['managed_copy_retained'] is False


def test_every_document_has_topic_and_incremental_updates_preserve_other_members(tmp_path):
    paths=[]
    for name in ['DSP_one','DSP_two','Unclassified']:
        path=tmp_path/(name+'.pdf');pdf(path,'Short text without any recognizable subject.');paths.append(path)
    with Library(tmp_path/'library',CountingEncoder()) as lib:
        topics.initialize(lib);folder=lib.create_folder('Notes')['id']
        docs=[lib.import_pdf(path,folder,retain_source=False)['document'] for path in paths]
        for doc in docs:topics.assign_subjects(lib,doc['id'])
        groups={g['name']:set(g['document_ids']) for g in topics.linked_folders(lib)}
        assert groups['DSP']=={docs[0]['id'],docs[1]['id']}
        assert groups['Miscellaneous']=={docs[2]['id']}
        with lib.db:lib.db.execute("UPDATE documents SET filename='linear_algebra.pdf' WHERE id=?",(docs[2]['id'],))
        topics.assign_subjects(lib,docs[2]['id'])
        groups={g['name']:set(g['document_ids']) for g in topics.linked_folders(lib)}
        assert 'Miscellaneous' not in groups and docs[2]['id'] in groups['Mathematics']
        topics.rebuild_links(lib)
        assigned={d for g in topics.linked_folders(lib) if g['basis'].startswith('Suggested subject') for d in g['document_ids']}
        assert assigned=={d['id'] for d in docs}


def test_fast_source_navigation_does_not_call_a_language_model():
    class DB:
        def execute(self,*args):return self
        def fetchone(self):return None
    def forbidden(*args,**kwargs):raise AssertionError('Ordinary source navigation must not generate text')
    hit=dict(document_id='d',chunk_id=1,source_identity='version',filename='notes.pdf',page_number=2,passage='A verified indexed passage about signal processing and convolution.')
    response=respond(SimpleNamespace(db=DB()),SimpleNamespace(generate=forbidden),'signal processing',dict(mode='semantic',results=[hit]),select_source=False)
    assert response['method']=='ranked_source' and response['citations'][0]['page_number']==2
    assert not respond(SimpleNamespace(db=DB()),SimpleNamespace(generate=forbidden),'unknown',dict(mode='semantic',results=[hit],below_cutoff=True),select_source=False)['citations']
