"""Regression tests for PDF amount search, OCR evidence, and index migrations.

OCR tests run the installed recognizer. CountingEncoder tests only persistence
and exact-input vector reuse; it makes no semantic quality claim.
"""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import numpy as np
import pymupdf
import pytest
from tokenizers import Tokenizer

from knowledge_library.library import Library
from knowledge_library.pdf import PdfOptions,extract_page
from knowledge_library.evidence import physical_amounts,scoped_review
from knowledge_library.bill_amounts import search_amount,query_amount
from knowledge_library.search_response import respond

ROOT=Path(__file__).resolve().parents[1]


def make_scan(path,*,current_right=None):
    with pymupdf.open() as source:
        page=source.new_page(width=600,height=420)
        page.insert_text((35,35),'SYNTHETIC INVOICE - NOT A REAL BILL',fontsize=12)
        labels=[(325,'Current Invoice')] if current_right is None else [
            (265,'Previous Invoice' if current_right else 'Current Invoice'),
            (445,'Current Invoice' if current_right else 'Previous Invoice')]
        for center,text in labels:
            width=pymupdf.get_text_length(text,fontsize=16)
            page.insert_text((center-width/2,90),text,fontsize=16)
        page.insert_text((60,320),'Grand Total:',fontsize=16)
        if current_right is None:page.insert_text((290,320),'29074.00',fontsize=16)
        else:
            page.insert_text((230,320),'29000.00' if current_right else '29074.00',fontsize=16)
            page.insert_text((410,320),'29074.00' if current_right else '29000.00',fontsize=16)
        pix=page.get_pixmap(matrix=pymupdf.Matrix(300/72,300/72))
        with pymupdf.open() as scan:
            out=scan.new_page(width=600,height=420)
            out.insert_image(out.rect,stream=pix.tobytes('png'));scan.save(path)


def make_faint_header_scan(path):
    with pymupdf.open() as source:
        page=source.new_page(width=600,height=420)
        page.insert_text((35,35),'SYNTHETIC SCAN - NOT A REAL BILL',fontsize=12)
        for center,current in ((265,False),(445,True)):
            text='Current Invoice' if current else 'Previous Invoice'
            size=4; width=pymupdf.get_text_length(text,fontsize=size)
            page.insert_text((center-width/2,90),text,fontsize=size,
                             color=(.85,.85,.85))
        page.insert_text((60,320),'Grand Total:',fontsize=16)
        page.insert_text((230,320),'250.00',fontsize=16)
        page.insert_text((410,320),'10500.00',fontsize=16)
        pix=page.get_pixmap(matrix=pymupdf.Matrix(300/72,300/72))
        with pymupdf.open() as scanned:
            target=scanned.new_page(width=600,height=420)
            target.insert_image(target.rect,stream=pix.tobytes('png'))
            scanned.save(path)


class CountingEncoder:
    dimensions=4;batch_size=4;dtype='test'
    signature=dict(model_id='counting-test',revision='1',configuration_version='1')
    def __init__(self):
        self.stats=dict(document_texts_encoded=0)
        self.tokenizer=Tokenizer.from_file(str(next((ROOT/'models/embeddinggemma-2').rglob('tokenizer.json'))))
    def load(self):pass
    def documents(self,title,texts):
        self.stats['document_texts_encoded']+=len(texts)
        return [np.array([1,0,0,0],dtype='<f4') for _ in texts]


def make_native(path,*,right=False,headers=True):
    with pymupdf.open() as doc:
        page=doc.new_page(width=600,height=420)
        page.insert_text((30,30),'SYNTHETIC INVOICE - TEST ONLY')
        if headers:
            for x,text in [(230,'Previous Invoice' if right else 'Current Invoice'),(410,'Current Invoice' if right else 'Previous Invoice')]:page.insert_text((x,90),text)
        page.insert_text((60,320),'Grand Total:')
        page.insert_text((230,320),'29000.00' if right else '29074.00')
        page.insert_text((410,320),'29074.00' if right else '29000.00')
        doc.save(path)


def lookup(lib,folder,query):
    from knowledge_library.bills import all_bills
    return search_amount(lib,query,dict.fromkeys(['direction','party','invoice_number','date_from','date_to','item']),
        query_amount(query),all_bills(lib),folder,None)


@pytest.mark.parametrize('scanned',[False,True])
@pytest.mark.parametrize('right',[False,True])
def test_actual_extraction_current_column_and_persisted_lookup(tmp_path,scanned,right):
    path=tmp_path/'invoice.pdf'
    if scanned:make_scan(path,current_right=right)
    else:make_native(path,right=right)
    with Library(tmp_path/'lib',CountingEncoder()) as lib:
        folder=lib.create_folder('Invoices')['id']
        key=lib.import_pdf(path,folder,pdf_options=PdfOptions(ocr=scanned,tables=False,tessdata=str(ROOT/'models/tessdata')))['document']['id']
        evidence=lib.page(key,1)['evidence']
        assert evidence['words'] and evidence['frame']=='unrotated_page_points'
        assert evidence['ocr_alternatives'] is None
        result=lookup(lib,folder,'total about 29000')
        assert [h['amount_match']['value'] for h in result['results']]==['29074.00']
        assert result['results'][0]['amount_match']['association']=='current_column'
        box=result['results'][0]['amount_match']['highlight_box']
        assert 0<=box[0]<box[0]+box[2]<=1 and 0<=box[1]<box[1]+box[3]<=1
        assert not lookup(lib,folder,'total exactly 29000')['results']


def test_unknown_columns_remain_unresolved(tmp_path):
    path=tmp_path/'unknown.pdf';make_native(path,headers=False)
    with pymupdf.open(path) as pdf:r=extract_page(pdf[0],PdfOptions(tables=False))
    amounts=physical_amounts(r['text'],r['evidence'])
    assert len(amounts)==2 and {a['association'] for a in amounts}=={'unresolved'}
    assert {a['value'] for a in amounts}=={'29000.00','29074.00'}


def test_rotated_geometry_does_not_claim_association(tmp_path):
    path=tmp_path/'rotated.pdf';make_native(path)
    with pymupdf.open(path) as pdf:
        pdf[0].set_rotation(90);r=extract_page(pdf[0],PdfOptions(tables=False))
    assert physical_amounts(r['text'],r['evidence']) is None


def test_geometry_upgrade_preserves_passages_and_vectors(tmp_path):
    path=tmp_path/'invoice.pdf';make_native(path,right=True)
    encoder=CountingEncoder()
    with Library(tmp_path/'lib',encoder) as lib:
        folder=lib.create_folder('Bills')['id'];key=lib.import_pdf(path,folder,pdf_options=PdfOptions(tables=False))['document']['id']
        before=[tuple(r) for r in lib.db.execute('SELECT * FROM chunks')]
        with lib.db:lib.db.execute("UPDATE pages SET evidence='{}'")
        assert lib.upgrade_evidence(key)['updated']==1
        assert [tuple(r) for r in lib.db.execute('SELECT * FROM chunks')]==before
        assert encoder.stats['document_texts_encoded']==1
        assert lib.upgrade_evidence(key)['skipped']==1
        assert lookup(lib,folder,'total 29000')['results'][0]['amount_match']['value']=='29074.00'


def test_changed_indexed_text_rejects_geometry_upgrade(tmp_path):
    path=tmp_path/'invoice.pdf';make_native(path)
    with Library(tmp_path/'lib',CountingEncoder()) as lib:
        folder=lib.create_folder('Bills')['id'];key=lib.import_pdf(path,folder)['document']['id']
        with lib.db:lib.db.execute("UPDATE pages SET evidence='{}',text=text || ' altered'")
        assert lib.upgrade_evidence(key)['needs_refresh']==[1]
        assert lib.page(key,1)['evidence']['state']=='requires_refresh'


def test_edit_reuses_identical_embedding_inputs(tmp_path):
    path=tmp_path/'pages.pdf';encoder=CountingEncoder()
    def write(last):
        with pymupdf.open() as pdf:
            for text in ['Unchanged first page contains material about finite automata.',last]:pdf.new_page().insert_text((30,40),text)
            pdf.save(path)
    write('Second page original content for the first version.')
    with Library(tmp_path/'lib',encoder) as lib:
        folder=lib.create_folder('Notes')['id'];first=lib.import_pdf(path,folder)
        assert first['document_embeddings_generated']==2
        write('Second page revised content for the next version.')
        second=lib.import_pdf(path,folder)
        assert second['document_embeddings_generated']==1
        assert second['document']['id']==first['document']['id']
        assert lib.verify()['passed']


def test_source_decode_admission_retains_needs_review(tmp_path):
    path=tmp_path/'scan.pdf';make_scan(path,current_right=True)
    with pymupdf.open(path) as pdf:
        r=extract_page(pdf[0],PdfOptions(ocr=True,tables=False,max_source_pixels=100))
    assert r['status']=='needs_ocr' and r['ocr_confidence'] is None
    assert any('work limit' in w for w in r['warnings'])
    assert 'additional' in r['evidence']['resource_profile']['scope']


def test_optional_audit_is_bounded_and_does_not_certify_completeness(tmp_path):
    path=tmp_path/'tiny.pdf';make_faint_header_scan(path)
    with pymupdf.open(path) as pdf:
        r=extract_page(pdf[0],PdfOptions(ocr=True,tables=False,audit_ocr=True,ocr_retry_limit=2,tessdata=str(ROOT/'models/tessdata')))
    record=r['evidence']['coverage']
    assert r['status']=='ok' and record['complete'] is False and len(record['attempts'])<=2
    assert sum(a['pixels'] for a in record['attempts'])<=4_000_000
    assert record['detector_pixels']<=1_003_000
    assert any('audit_is_not_completeness' in w for w in r['warnings'])


@pytest.mark.parametrize('key,value',[('source_sha256','other'),('page_number',2),('field','subtotal'),('value','29000.00'),('currency','USD'),('evidence','different'),('bbox',[0,0,1,1])])
def test_field_review_rejects_every_scope_mismatch(key,value):
    match=dict(field='total',value='29074.00',currency='INR',evidence='Total: 29074.00',page_number=1)
    review=dict(source_sha256='sha',**match);review[key]=value
    assert not scoped_review(dict(reviewed=1,evidence={'amount_review':review}),match,'sha')


def test_document_review_is_not_amount_review():
    match=dict(field='total',value='29074.00',currency=None,evidence='Total: 29074.00',page_number=1)
    assert not scoped_review(dict(reviewed=1,evidence={}),match,'sha')
    assert scoped_review(dict(reviewed=1,evidence={'amount_review':dict(source_sha256='sha',**match)}),match,'sha')


def test_response_keeps_ocr_source_status_and_closing_context():
    from tests.test_search_response import hit,DB
    source=hit();source.update(extraction_method='ocr',source_available=False,warnings=['partial_read'])
    calls=[]
    def generate(*a,**kw):calls.append(json.loads(a[1]));return {'choice':1},0
    lib=SimpleNamespace(db=DB(),page=lambda *a:dict(text=source['passage']+'\nCancelled. Replaced by invoice 44, total USD 31000.'))
    r=respond(lib,SimpleNamespace(generate=generate),'pumping lemma',dict(mode='semantic',results=[source]))
    citation=r['citations'][0]
    assert citation['source_available'] is False and citation['extraction_method']=='ocr'
    assert any('unavailable' in n for n in r['qualifications'])
    assert any('Cancelled' in line['text'] for line in calls[0]['sources'][0]['context']['lines'])
    assert r['answer_scope']=='source_navigation'


def test_oversized_status_context_is_explicit():
    from knowledge_library.search_response import context
    r=context(dict(passage=('Revised total 29074\n'*100)))
    assert r['budget_exceeded'] and r['lines']==[] and r['complete'] is False


def test_status_context_keeps_values_on_following_lines():
    from knowledge_library.search_response import context
    r=context(dict(passage='Invoice\nGrand Total\n29074.00\nCorrection\nGrand Total\n31000.00'))
    kept='\n'.join(line['text'] for line in r['lines'])
    assert '29074.00' in kept and '31000.00' in kept and 'Correction' in kept


def test_actual_qwen_tokenizer_and_context_admission(monkeypatch):
    from knowledge_library.query_interpreter import QueryInterpreter
    interpreter=QueryInterpreter()
    assert interpreter.token_count('hello mere bhai')==4
    interpreter._verified=True
    calls=[]
    monkeypatch.setattr(interpreter,'token_count',lambda text:2000)
    # The model subprocess must never start after rejection by the tokenizer.
    monkeypatch.setattr('knowledge_library.query_interpreter.subprocess.run',lambda *a,**kw:calls.append(a))
    with pytest.raises(ValueError,match='budget'):interpreter.generate('test','question',{},max_tokens=16)
    assert not calls


def test_explicit_field_review_controls_nearby_policy_and_invalidates(tmp_path):
    from knowledge_library.bills import save
    def write(path,value):
        with pymupdf.open() as pdf:
            page=pdf.new_page();page.insert_text((30,50),f'Invoice\nGrand Total: INR {value}')
            pdf.save(path)
    with Library(tmp_path/'lib',CountingEncoder()) as lib:
        folder=lib.create_folder('Bills')['id'];keys=[]
        for i,value in enumerate(['29000','29074']):
            path=tmp_path/f'{i}.pdf';write(path,value);keys.append(lib.import_pdf(path,folder)['document']['id'])
        fields=dict(party='Synthetic Trading',bill_date='2026-09-25',source_page=1,amount='29000',currency='INR')
        save(lib,keys[0],fields,reviewed=True)
        assert len(lookup(lib,folder,'total 29000')['results'])==2  # Document review alone does not qualify.
        save(lib,keys[0],dict(fields,amount_reviewed=True),reviewed=True)
        r=lookup(lib,folder,'total 29000')
        assert len(r['results'])==1 and r['results'][0]['amount_match']['verified']
        with lib.db:lib.db.execute('UPDATE documents SET sha256=? WHERE id=?',('new revision',keys[0]))
        r=lookup(lib,folder,'total 29000')
        assert len(r['results'])==2 and not any(h['amount_match']['verified'] for h in r['results'])


def test_missing_source_keeps_indexed_matches_during_automatic_migration(tmp_path):
    path=tmp_path/'invoice.pdf';make_native(path)
    with Library(tmp_path/'lib',CountingEncoder()) as lib:
        folder=lib.create_folder('Bills')['id'];doc=lib.import_pdf(path,folder)['document']
        with lib.db:lib.db.execute("UPDATE pages SET evidence='{}'")
        (lib.root/doc['managed_path']).unlink()
        r=lookup(lib,folder,'total 29000')
        assert r['results'] and r['results'][0]['source_available'] is False
        assert not r['results'][0]['amount_match']['verified']


def test_automatic_migration_on_amount_search(tmp_path):
    path=tmp_path/'invoice.pdf';make_native(path,right=True)
    with Library(tmp_path/'lib',CountingEncoder()) as lib:
        folder=lib.create_folder('Bills')['id'];key=lib.import_pdf(path,folder)['document']['id']
        with lib.db:lib.db.execute("UPDATE pages SET evidence='{}'")
        assert lookup(lib,folder,'total exactly 29074')['results'][0]['amount_match']['value']=='29074.00'
        assert lookup(lib,folder,'total 29000')['results'][0]['amount_match']['value']=='29074.00'
        assert lib.page(key,1)['evidence']['version']==1


def test_previous_schema_backup_restores_with_evidence_migration(tmp_path):
    import sqlite3
    import zipfile
    from knowledge_library.maintenance import initialize,schema,restore_backup
    root=tmp_path/'old'
    with Library(root,CountingEncoder()) as lib:
        initialize(lib);trusted=schema(lib)
    with sqlite3.connect(root/'library.sqlite3') as db:
        db.execute('ALTER TABLE pages DROP COLUMN evidence')
        db.execute('DROP INDEX chunks_input_lookup')
    database=(root/'library.sqlite3').read_bytes();archive=tmp_path/'old.zip'
    manifest=dict(format='local-library-backup-v1',files={'library.sqlite3':hashlib.sha256(database).hexdigest()})
    with zipfile.ZipFile(archive,'w') as z:
        z.writestr('library.sqlite3',database);z.writestr('manifest.json',json.dumps(manifest))
    r=restore_backup(archive,tmp_path/'restored',CountingEncoder(),trusted_schema=trusted)
    assert r['integrity']['passed']
    with Library(tmp_path/'restored',CountingEncoder()) as lib:
        assert 'evidence' in {row['name'] for row in lib.db.execute('PRAGMA table_info(pages)')}
