"""Local bibliography extraction, source identity, and correction regressions."""
import json
import pymupdf
import pytest

from knowledge_library.library import Library
from tests.test_pdf_search_regressions import CountingEncoder


def make_paper(path, *, title='Learning with Local Evidence', author='Ada Lovelace; Alan Turing', year='2024', doi='10.1234/local.2024'):
    with pymupdf.open() as pdf:
        first=pdf.new_page()
        first.insert_text((45,60),title,fontsize=18)
        first.insert_text((45,90),'Ada Lovelace and Alan Turing',fontsize=11)
        first.insert_text((45,115),f'Published {year}. DOI: {doi}',fontsize=10)
        first.insert_text((45,150),'Abstract',fontsize=12)
        first.insert_text((45,175),'We investigate grounded local document retrieval with an experimental evaluation.')
        last=pdf.new_page()
        last.insert_text((45,60),'References\n[1] Another author. DOI: 10.9999/not-this-paper. 1998.')
        pdf.set_metadata(dict(title=title,author=author))
        pdf.save(path)


@pytest.fixture
def library(tmp_path):
    with Library(tmp_path/'library',CountingEncoder()) as lib:
        folder=lib.create_folder('Papers')['id']
        yield lib,folder


def test_ingestion_automatically_records_reference_and_excludes_reference_doi(library,tmp_path):
    from knowledge_library import papers
    lib,folder=library;path=tmp_path/'paper.pdf';make_paper(path)
    doc=lib.import_pdf(path,folder,retain_source=False)['document']
    assert lib.db.execute('SELECT value FROM settings WHERE key=?',(papers.PREFIX+doc['id'],)).fetchone()
    ref=papers.reference(lib,doc['id'])
    assert ref['detected'] and not ref['reviewed']
    assert ref['item']['title']=='Learning with Local Evidence'
    assert ref['item']['author']==[{'given':'Ada','family':'Lovelace'},{'given':'Alan','family':'Turing'}]
    assert ref['item']['issued']=={'date-parts':[[2024]]}
    assert ref['item']['DOI']=='10.1234/local.2024'
    assert 'container-title' not in ref['item']
    assert ref['warnings'] and ref['source_sha256']==doc['sha256']


def test_invoice_with_a_cited_doi_is_not_detected_as_a_paper(library,tmp_path):
    from knowledge_library import papers
    lib,folder=library;path=tmp_path/'invoice.pdf'
    with pymupdf.open() as pdf:
        pdf.new_page().insert_text((45,60),'Invoice 2024\nAmount 50 INR\nReferences\nDOI: 10.1234/someone-else')
        pdf.save(path)
    doc=lib.import_pdf(path,folder,retain_source=False)['document'];ref=papers.reference(lib,doc['id'])
    assert not ref['detected'] and 'DOI' not in ref['item']


def test_manual_corrections_survive_refresh_restart_and_trash_restore(library,tmp_path):
    from knowledge_library import papers
    from knowledge_library.maintenance import initialize,trash_document,restore_document
    lib,folder=library;initialize(lib);path=tmp_path/'paper.pdf';make_paper(path)
    doc=lib.import_pdf(path,folder,retain_source=False)['document'];ref=papers.reference(lib,doc['id'])
    corrected={**ref['item'],'title':'Corrected title','container-title':'Verified Journal'}
    papers.save_reference(lib,doc['id'],corrected,True,doc['sha256'])
    lib.refresh(doc['id'])
    assert papers.reference(lib,doc['id'])['item']==corrected
    trash=trash_document(lib,doc['id']);restore_document(lib,trash['trash_id'])
    with Library(lib.root,CountingEncoder()) as reopened:
        assert papers.reference(reopened,doc['id'])['reviewed']
        assert papers.reference(reopened,doc['id'])['item']==corrected


def test_replacement_invalidates_prior_manual_reference(library,tmp_path):
    from knowledge_library import papers
    lib,folder=library;path=tmp_path/'paper.pdf';make_paper(path)
    doc=lib.import_pdf(path,folder,retain_source=False)['document'];ref=papers.reference(lib,doc['id'])
    papers.save_reference(lib,doc['id'],{**ref['item'],'title':'Old correction'},True,doc['sha256'])
    other=tmp_path/'other.pdf';make_paper(other,title='New Research Paper',year='2025')
    lib.import_pdf(other,folder,document_id=doc['id'],retain_source=False)
    ref=papers.reference(lib,doc['id'])
    assert not ref['reviewed'] and ref['item']['title']=='New Research Paper'
    with pytest.raises(ValueError,match='changed'):
        papers.save_reference(lib,doc['id'],ref['item'],True,doc['sha256'])


def test_missing_and_changed_originals_use_indexed_text_not_new_metadata(library,tmp_path):
    from knowledge_library import papers
    lib,folder=library;path=tmp_path/'paper.pdf';make_paper(path)
    doc=lib.import_pdf(path,folder,retain_source=False)['document']
    path.unlink();make_paper(path,title='UNINDEXED WRONG TITLE')
    lib.db.execute('DELETE FROM settings WHERE key=?',(papers.PREFIX+doc['id'],));lib.db.commit()
    ref=papers.reference(lib,doc['id'])
    assert 'WRONG' not in ref['item']['title']
    assert any('indexed text' in warning.lower() for warning in ref['warnings'])


@pytest.mark.parametrize('bad',[{'title':'x','unknown':'value'}, {'title':'x','URL':'javascript:alert(1)'}, {'title':'x','author':[{'family':'x','weird':1}]}, {'title':'x','issued':{'date-parts':[[True]]}}, {'title':'x','DOI':'not-a-doi'}])
def test_reference_validation_rejects_unsafe_or_malformed_metadata(bad):
    from knowledge_library import papers
    with pytest.raises(ValueError):papers.validate_item(bad,'doc')


def test_xmp_and_document_metadata_take_precedence_over_body_citations(tmp_path):
    from knowledge_library import papers
    path=tmp_path/'xmp.pdf';make_paper(path)
    with pymupdf.open(path) as pdf:
        pdf.set_xml_metadata('''<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"><rdf:Description xmlns:prism="http://prismstandard.org/namespaces/basic/2.0/" prism:doi="10.7777/actual" prism:publicationName="Real Journal" prism:publicationDate="2023-05-12"/></rdf:RDF></x:xmpmeta>''')
        pdf.saveIncr()
    ref=papers.extract(path,document_id='doc',filename='xmp.pdf')
    assert ref['detected'] and ref['item']['DOI']=='10.7777/actual'
    assert ref['item']['container-title']=='Real Journal'
    assert ref['item']['issued']=={'date-parts':[[2023,5,12]]}


def test_multiline_author_block_and_comma_separated_full_names(tmp_path):
    from knowledge_library import papers
    path=tmp_path/'authors.pdf'
    with pymupdf.open() as pdf:
        page=pdf.new_page()
        page.insert_text((45,60),'Evidence Grounded Research',fontsize=18)
        page.insert_text((45,90),'Alice Smith*\nUniversity of Testing\nalice@example.org\nBob Jones\nCarol Chan, Dan White\nAbstract\nWe report an experiment.')
        pdf.new_page().insert_text((45,60),'References\n[1] Source.')
        pdf.save(path)
    ref=papers.extract(path,document_id='doc',filename=path.name)
    assert [p['family'] for p in ref['item']['author']]==['Smith','Jones','Chan','White']
    assert papers._authors('Diederik P. Kingma, Jimmy Lei Ba')==[{'given':'Diederik P.','family':'Kingma'},{'given':'Jimmy Lei','family':'Ba'}]
    assert papers._authors('Lovelace, Ada')==[{'given':'Ada','family':'Lovelace'}]


def test_reference_list_doi_on_first_page_is_not_the_papers_identifier(tmp_path):
    from knowledge_library import papers
    path=tmp_path/'one-page.pdf'
    with pymupdf.open() as pdf:
        pdf.new_page().insert_text((45,60),'Small Research Article\nAda Lovelace\nAbstract\nWe study a local problem.\nReferences\nDOI: 10.1111/someone-else')
        pdf.save(path)
    ref=papers.extract(path,document_id='doc',filename=path.name)
    assert ref['detected'] and 'DOI' not in ref['item']


def test_xmp_entities_are_ignored_and_pdf_creation_date_is_not_publication_date(tmp_path):
    from knowledge_library import papers
    path=tmp_path/'dates.pdf';make_paper(path)
    with pymupdf.open(path) as pdf:
        pdf.set_metadata({'creationDate':'D:20300101000000Z'})
        pdf.set_xml_metadata('<!DOCTYPE x [<!ENTITY xxe SYSTEM "file:///not-a-source">]><x>&xxe;</x>')
        pdf.saveIncr()
    ref=papers.extract(path,document_id='doc',filename=path.name)
    assert ref['item']['issued']=={'date-parts':[[2024]]}
    assert 'not-a-source' not in json.dumps(ref)


def test_metadata_errors_do_not_break_document_ingestion(library,tmp_path,monkeypatch):
    from knowledge_library import papers
    lib,folder=library;path=tmp_path/'paper.pdf';make_paper(path)
    def failed(*args,**kwargs):raise RuntimeError('bad PDF metadata')
    monkeypatch.setattr(papers,'extract',failed)
    doc=lib.import_pdf(path,folder,retain_source=False)['document']
    assert doc['status']=='indexed' and lib.page(doc['id'],1)['text']


def test_manual_reference_survives_verified_backup(library,tmp_path):
    from knowledge_library import papers
    from knowledge_library.maintenance import initialize,backup,restore_backup,schema
    lib,folder=library;initialize(lib);path=tmp_path/'paper.pdf';make_paper(path)
    doc=lib.import_pdf(path,folder)['document'];ref=papers.reference(lib,doc['id'])
    item={**ref['item'],'title':'Backed up title'};papers.save_reference(lib,doc['id'],item,True,doc['sha256'])
    destination=tmp_path/'restored';restore_backup(backup(lib),destination,CountingEncoder(),trusted_schema=schema(lib))
    with Library(destination,CountingEncoder()) as restored:
        assert papers.reference(restored,doc['id'])['item']==item


def test_conference_statement_keeps_conference_type():
    from knowledge_library import papers
    ref=papers.extract(document_id='conference',filename='paper.pdf',first_text='Published as a conference paper at ICLR 2015\nA Research Paper\nAbstract\nSome findings.',tail_text='References\nOther work')
    assert ref['item']['type']=='paper-conference'
    assert ref['item']['container-title']=='ICLR 2015'


def test_reference_api_requires_token_and_preserves_source_identity(library,tmp_path):
    from fastapi.testclient import TestClient
    from knowledge_library.server import create_app
    lib,folder=library;path=tmp_path/'api-paper.pdf';make_paper(path)
    doc=lib.import_pdf(path,folder)['document']
    app=create_app(lib.root,preload=False)
    with TestClient(app) as client:
        route=f"/api/documents/{doc['id']}/reference"
        ref=client.get(route).json()
        assert ref['detected']
        body={'item':ref['item'],'source_sha256':doc['sha256'],'reviewed':True}
        assert client.put(route,json=body).status_code==403
        client.headers['X-Library-Token']=client.get('/api/state').json()['token']
        assert client.put(route,json=body).json()['reviewed']
        assert client.put(route,json={**body,'source_sha256':'0'*64}).status_code==400
        assert client.post(route+'/reset').json()['reviewed'] is False


def test_headingless_preprint_requires_own_versioned_stamp():
    from knowledge_library import papers
    body='A Study of Local Retrieval\nAda Lovelace\nWe study retrieval with local evidence.\n1\nIntroduction\nSome results.\narXiv:2610.12345v1 [cs.IR] 29 Oct 2026'
    ref=papers.extract(document_id='local',filename='paper.pdf',first_text=body)
    assert ref['detected']
    ordinary=papers.extract(document_id='ordinary',filename='notes.pdf',first_text=body.replace('arXiv:2610.12345v1 [cs.IR] 29 Oct 2026','See arXiv:2610.12345 for background.'))
    assert not ordinary['detected']
