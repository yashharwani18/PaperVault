"""R22 real local PDF OCR -> production amount parsing/search, synthetic only."""
import json
from pathlib import Path
import uuid

import pymupdf

from knowledge_library.pdf import PdfOptions,extract_page
from knowledge_library.bill_amounts import source_amounts
from research.patent_candidate.amount_suppression import fixture_library,lookup,bounded_reference
from research.patent_candidate.measure_context_stability import header_control


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


def run():
    root=Path(__file__).resolve().parents[2]
    work=root/'data/patent-research'/('r22-chain-'+uuid.uuid4().hex);work.mkdir(parents=True)
    options=PdfOptions(ocr=True,tessdata=str(root/'models/tessdata'),tables=False)
    pages={}
    for name,right in [('current_left',False),('current_right',True),('clear_nearby',None)]:
        path=work/(name+'.pdf');make_scan(path,current_right=right)
        with pymupdf.open(path) as doc:
            page=doc[0];assert not page.get_text().strip()
            extracted=extract_page(page,options)
            assert extracted['status']=='ok' and extracted['method']=='ocr'
            # Independent ordinary contextual control at the same OCR resolution.
            # This second OCR call exposes word geometry; no native text is used.
            tp=page.get_textpage_ocr(language='eng',dpi=200,full=True,tessdata=options.tessdata)
            words=page.get_text('words',textpage=tp)
            contextual=header_control(words)
            page.get_pixmap(matrix=pymupdf.Matrix(2,2)).save(work/(name+'.png'))
        assert contextual==['29074.00']
        pages[name]=dict(extracted=extracted,parsed_amounts=list(source_amounts(extracted['text'])),
                         contextual_control=contextual,source=str(path))
    cases=[]
    for main in ('current_left','current_right'):
        docs=[dict(id=main,indexed='0'),dict(id='clear_nearby',indexed='0')]
        lib=fixture_library(docs)
        try:
            for name in (main,'clear_nearby'):
                extracted=pages[name]['extracted']
                # Populate index fixture with actual production extraction output.
                # No amount or OCR result string is injected or edited.
                lib.db.execute('UPDATE pages SET text=?,method=?,warnings=? WHERE document_id=?',
                    (extracted['text'],extracted['method'],json.dumps(extracted['warnings']),name))
                lib.db.execute('UPDATE chunks SET char_end=? WHERE document_id=?',(len(extracted['text']),name))
            def summary(hits):
                return [dict(document_id=h['document_id'],value=h['amount_match']['value'],
                             evidence=h['amount_match']['evidence'],difference=h['amount_match']['difference']) for h in hits]
            queries=[]
            for query in ('total about 29000','total exactly 29000'):
                production=lookup(lib,query);control=bounded_reference(lib,query)
                queries.append(dict(query=query,production=summary(production['results']),
                    production_note=production['note'],bounded_control=summary(control)))
            cases.append(dict(main=main,queries=queries))
        finally:lib.db.close()
    left,right=cases
    assert {h['document_id'] for h in left['queries'][0]['production']}=={'current_left','clear_nearby'}
    assert [h['document_id'] for h in right['queries'][0]['production']]==['current_right']
    assert {h['document_id'] for h in right['queries'][0]['bounded_control']}=={'current_right','clear_nearby'}
    assert not left['queries'][1]['production']
    assert [h['document_id'] for h in right['queries'][1]['bounded_control']]==['current_right']
    report=dict(date='2026-10-21',fixtures=str(work),pages=pages,cases=cases,
        actual_ocr_calls_per_run=6,
        limits=['Three image-only synthetic PDFs; no private or production-library documents',
                'Real production extraction/parser/search with an isolated SQLite schema and result adapter',
                'No full ingestion/vector/model/server/UI execution or representative error-rate estimate',
                'Current-invoice total is the supplied fixture semantics; indexed literal equality is different',
                'Bounded control improves availability but retains the misassociated apparent exact hit',
                'Contextual reader is an ordinary fixture-specific column control, not a complete field recognizer',
                'No performance, memory, mobile advantage or inventive-step conclusion'])
    (root/'results/patent-r22-ocr-search-chain.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(dict(fixtures=str(work),pages={k:dict(parsed=v['parsed_amounts'],contextual=v['contextual_control']) for k,v in pages.items()},
        cases=cases,ocr_calls=6),indent=2))


if __name__=='__main__':run()
