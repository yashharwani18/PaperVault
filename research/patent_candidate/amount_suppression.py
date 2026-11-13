"""R10 audit of production amount search using explicitly injected text errors.

No OCR engine runs. Source truths are fixture metadata, never inferred by the
control. The per-document reference retains bounded candidates using the real
search function; it is a policy control, not an efficient replacement or patent.
"""
from decimal import Decimal
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace

from knowledge_library.bill_amounts import search_amount, query_amount, amount_tolerance


def fixture_library(documents):
    db = sqlite3.connect(':memory:'); db.row_factory = sqlite3.Row
    db.executescript('''CREATE TABLE documents(id,folder_id,filename,managed_path,status);
        CREATE TABLE folders(id,name);
        CREATE TABLE pages(document_id,page_number,text,page_label,method,warnings);
        CREATE TABLE chunks(id,document_id,page_number,char_start,char_end);
        CREATE TABLE document_sources(document_id,format);''')
    for folder in sorted({d.get('folder','bills') for d in documents}):
        db.execute('INSERT INTO folders VALUES (?,?)',(folder,folder))
    for i,d in enumerate(documents):
        text = f"Invoice\n{d.get('label','Grand Total')}: {d.get('currency','INR')} {d['indexed']}\n"
        db.execute('INSERT INTO documents VALUES (?,?,?,?,?)',
                   (d['id'],d.get('folder','bills'),d['id']+'.pdf','unused','ready'))
        db.execute('INSERT INTO pages VALUES (?,1,?,1,?,?)',
                   (d['id'],text,d.get('method','native'),'[]'))
        db.execute('INSERT INTO chunks VALUES (?,?,1,0,?)',(i,d['id'],len(text)))
        db.execute('INSERT INTO document_sources VALUES (?,?)',(d['id'],'pdf'))
    def result(row,*args):
        return dict(document_id=row['document_id'],chunk_id=row['id'],page_number=1,
                    filename=row['filename'],source_identity='synthetic-'+row['document_id'],
                    extraction_method=row['extraction_method'],warnings=[],
                    passage=db.execute('SELECT text FROM pages WHERE document_id=?',
                                       (row['document_id'],)).fetchone()[0])
    return SimpleNamespace(db=db,_result=result)


def lookup(lib,query,*,folder=None,ids=None):
    intent = dict.fromkeys(('direction','party','invoice_number','date_from','date_to','item'))
    return search_amount(lib,query,intent,query_amount(query),[],folder,None,document_ids=ids)


def bounded_reference(lib,query,*,folder=None):
    # Preserve production parser, amount tolerance, currency, field and folder gates.
    # Each controlled fixture document has one amount, so per-document calls avoid
    # only cross-document suppression. This does not solve within-document ambiguity.
    hits=[]
    for row in lib.db.execute('SELECT id FROM documents ORDER BY id').fetchall():
        hits.extend(lookup(lib,query,folder=folder,ids={row['id']})['results'])
    return sorted(hits,key=lambda h:(abs(Decimal(h['amount_match']['difference'])),h['document_id']))


def scenarios():
    near=dict(id='near',indexed='29074',truth='29074')
    bad=dict(id='apparent-exact',indexed='29000',truth='35000',method='ocr')
    return [
        dict(name='injected_ocr_error',query='total about INR 29000',docs=[bad,near],relevant=['near']),
        dict(name='injected_native_error',query='total about INR 29000',
             docs=[{**bad,'method':'native'},near],relevant=['near']),
        dict(name='genuine_exact_and_nearby',query='total about INR 29000',
             docs=[dict(id='exact',indexed='29000',truth='29000'),near],relevant=['exact','near']),
        dict(name='explicit_exact',query='total exactly INR 29000',
             docs=[dict(id='exact',indexed='29000',truth='29000'),near],relevant=['exact']),
        dict(name='wrong_currency',query='total about INR 29000',
             docs=[{**bad,'currency':'USD'},near],relevant=['near']),
        dict(name='wrong_field',query='total about INR 29000',
             docs=[{**bad,'label':'Subtotal'},near],relevant=['near']),
        dict(name='outside_folder',query='total about INR 29000',folder='bills',
             docs=[{**bad,'folder':'other'},near],relevant=['near']),
        dict(name='outside_tolerance',query='total about INR 29000',
             docs=[dict(id='too-far',indexed='29300',truth='29300'),near],relevant=['near']),
    ]


def evaluate(case):
    lib=fixture_library(case['docs'])
    try:
        primary=lookup(lib,case['query'],folder=case.get('folder'))
        reference=bounded_reference(lib,case['query'],folder=case.get('folder'))
        def summary(hits):
            ids=[h['document_id'] for h in hits]
            relevant=set(case['relevant'])
            return dict(ids=ids,missed=sorted(relevant-set(ids)),
                extra=sorted(set(ids)-relevant),
                values={h['document_id']:h['amount_match']['value'] for h in hits},
                evidence_preserved=all(h['amount_match']['evidence'] in h['passage'] for h in hits))
        requested=Decimal(query_amount(case['query'])['value'])
        return dict(name=case['name'],query=case['query'],documents=case['docs'],
            relevant=case['relevant'],tolerance=str(amount_tolerance(case['query'],requested)),
            production=summary(primary['results']),reference=summary(reference),
            production_response_note=primary['note'])
    finally: lib.db.close()


def run():
    root=Path(__file__).resolve().parents[2]
    rows=[evaluate(case) for case in scenarios()]
    report=dict(date='2026-10-21',cases=rows,
        production_cases_missing_candidate=sum(bool(r['production']['missed']) for r in rows),
        reference_cases_missing_candidate=sum(bool(r['reference']['missed']) for r in rows),
        limitation='Injected extraction errors, not observed OCR output or a representative accuracy benchmark. '
                   'The conventional reference retains false apparent-exact hits; source verification remains unsolved. '
                   'Per-document rescans are deliberately unoptimized; no phone performance claim. '
                   'No production or live library changes.')
    (root/'results/patent-r10-amount-suppression.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2))


if __name__=='__main__':run()
