import hashlib
import pymupdf
import pytest
from knowledge_library.library import Library
from knowledge_library import workspace_features as features
from knowledge_library import organization as org
from tests.test_pdf_search_regressions import CountingEncoder


@pytest.fixture
def library(tmp_path):
    model=CountingEncoder()
    with Library(tmp_path/'library',model) as lib:
        features.initialize(lib)
        first=lib.create_folder('Original')['id'];second=lib.create_folder('Courses')['id']
        docs=[]
        for i in range(2):
            path=tmp_path/f'DSP-{i}.pdf'
            with pymupdf.open() as pdf:
                pdf.new_page().insert_text((40,60),f'Digital signal processing uses filters and convolution. Document {i}.')
                pdf.save(path)
            doc=lib.import_pdf(path,first,retain_source=False)['document'];features.assign_subjects(lib,doc['id']);docs.append(doc)
        yield lib,docs,first,second


def test_topic_names_and_classification_survive_rebuild_reindex_and_restart(library):
    lib,docs,_,_=library;doc=docs[0]
    dsp=next(t for t in org.topics(lib) if t['name']=='DSP')
    org.rename_topic(lib,dsp['id'],'Signal processing')
    personal=org.create_topic(lib,'Robotics')
    org.set_topics(lib,[doc['id']],[personal['id']])
    features.assign_subjects(lib,doc['id']);features.rebuild_links(lib)
    assert org.document_info(lib,doc['id'])['topic_ids']==[personal['id']]
    assert any(g['name']=='Signal processing' for g in features.linked_folders(lib))
    lib.refresh(doc['id']);features.assign_subjects(lib,doc['id'])
    with Library(lib.root,CountingEncoder()) as reopened:
        assert org.document_info(reopened,doc['id'])['manual_topics']
        assert org.document_info(reopened,doc['id'])['topic_ids']==[personal['id']]
        org.reset_topics(reopened,[doc['id']])
        assert dsp['id'] in org.document_info(reopened,doc['id'])['topic_ids']
        assert not org.document_info(reopened,doc['id'])['manual_topics']


def test_empty_topic_choice_uses_miscellaneous_and_empty_custom_topics_stay_visible(library):
    lib,docs,_,_=library
    custom=org.create_topic(lib,'Personal reading')
    assert any(g['id']==custom['id'] and g['document_count']==0 for g in features.linked_folders(lib))
    org.set_topics(lib,[d['id'] for d in docs],[])
    misc=next(t for t in org.topics(lib) if t['name']=='Miscellaneous')
    assert all(org.document_info(lib,d['id'])['topic_ids']==[misc['id']] for d in docs)
    with pytest.raises(ValueError):org.rename_topic(lib,custom['id'],'dsp')
    with pytest.raises(ValueError):org.set_topics(lib,[docs[0]['id']],['missing'])


def test_bulk_move_and_undo_are_atomic_and_do_not_touch_source_or_vectors(library):
    lib,docs,first,second=library
    before=[(d['original_path'],hashlib.sha256(open(d['original_path'],'rb').read()).hexdigest()) for d in docs]
    vectors=[r[0] for r in lib.db.execute('SELECT vector_sha256 FROM chunks ORDER BY id')]
    result=org.move_documents(lib,[d['id'] for d in docs],second)
    assert all(lib.document(d['id'])['folder_id']==second for d in docs)
    org.undo_move(lib,result['undo_token'])
    assert all(lib.document(d['id'])['folder_id']==first for d in docs)
    assert vectors==[r[0] for r in lib.db.execute('SELECT vector_sha256 FROM chunks ORDER BY id')]
    assert all(hashlib.sha256(open(p,'rb').read()).hexdigest()==sha for p,sha in before)
    assert not list((lib.root/'files').glob('*.pdf'))
    result=org.move_documents(lib,[docs[0]['id']],second)
    lib.move_document(docs[0]['id'],first)
    with pytest.raises(ValueError,match='changed'):org.undo_move(lib,result['undo_token'])


def test_bulk_move_collision_keeps_every_document_in_original_folder(library):
    lib,docs,first,second=library
    lib.import_pdf(docs[0]['original_path'],second,retain_source=False)
    with pytest.raises(ValueError,match='already'):org.move_documents(lib,[d['id'] for d in docs],second)
    assert all(lib.document(d['id'])['folder_id']==first for d in docs)


def test_display_rename_does_not_change_embedding_title_or_encode_again(library):
    lib,docs,_,_=library;doc=docs[0];before=dict(lib.embedder.stats)
    org.rename_document(lib,doc['id'],'DSP class notes')
    assert next(d for d in org.decorate_documents(lib,lib.documents()) if d['id']==doc['id'])['display_title']=='DSP class notes'
    assert lib.document(doc['id'])['title']==doc['title']
    assert lib.embedder.stats==before


def test_restore_from_trash_reinstates_saved_topics_immediately(library):
    from knowledge_library.maintenance import initialize,trash_document,restore_document
    lib,docs,_,_=library;initialize(lib);key=docs[0]['id']
    topic=org.create_topic(lib,'Restored reading')
    org.set_topics(lib,[key],[topic['id']])
    trash=trash_document(lib,key)
    restore_document(lib,trash['trash_id'])
    assert org.document_info(lib,key)['topic_ids']==[topic['id']]


def test_backup_restore_keeps_custom_names_topics_and_corrections(library,tmp_path):
    from knowledge_library.maintenance import initialize,backup,restore_backup,schema
    lib,docs,_,_=library;initialize(lib);key=docs[0]['id']
    topic=org.create_topic(lib,'Portable notes');org.set_topics(lib,[key],[topic['id']])
    org.rename_document(lib,key,'Remembered document name')
    org.rename_topic(lib,topic['id'],'Remembered topic name')
    destination=tmp_path/'restored-library'
    restore_backup(backup(lib),destination,CountingEncoder(),trusted_schema=schema(lib))
    with Library(destination,CountingEncoder()) as restored:
        assert org.document_info(restored,key)['topic_ids']==[topic['id']]
        assert org.document_info(restored,key)['display_title']=='Remembered document name'
        assert next(t for t in org.topics(restored) if t['id']==topic['id'])['name']=='Remembered topic name'
