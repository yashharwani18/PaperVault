"""R13 local native/OCR relation controls on clearly synthetic invoice layouts."""
import hashlib
import json
from pathlib import Path
import time
import uuid

import pymupdf

from knowledge_library.bill_amounts import source_amounts
from research.patent_candidate.field_geometry import relations,candidate_pairs,header_pairs
from research.patent_candidate.relation_support import crop_hash


def make_fixture(path,case):
    with pymupdf.open() as doc:
        page=doc.new_page(width=600,height=420)
        page.insert_text((35,35),'SYNTHETIC INVOICE RESEARCH FIXTURE',fontsize=12)
        put=lambda x,y,text:page.insert_text((x,y),text,fontsize=16)
        truth={('total','10500.00')}
        if case=='side_by_side':
            put(35,80,'Invoice A');put(330,80,'Invoice B')
            put(35,140,'Total:');put(170,140,'10500.00')
            put(330,140,'Total:');put(465,140,'29074.00')
            truth.add(('total','29074.00'))
        elif case=='vertical':
            put(60,120,'Grand Total:');put(60,160,'10500.00')
        elif case in ('header_disambiguation','header_swapped'):
            put(230,90,'Amount Due' if case=='header_swapped' else 'Tax')
            put(410,90,'Tax' if case=='header_swapped' else 'Amount Due')
            put(60,150,'Grand Total:');put(230,150,'250.00');put(410,150,'10500.00')
            if case=='header_swapped':truth={('total','250.00')}
        else:
            truth.add(('subtotal','10000.00'))
            values=[(290,120,'10000.00'),(290,190,'10500.00')]
            labels=[(60,120,'Subtotal:'),(60,190,'Grand Total:')]
            if case=='values_first_stream':items=values+labels
            elif case=='interleaved_stream':items=[labels[1],values[0],labels[0],values[1]]
            else:items=[labels[0],values[0],labels[1],values[1]]
            for item in items:put(*item)
            if case=='tax_next_row':put(60,260,'SGST:');put(290,260,'250.00')
            if case=='rotated_90':page.set_rotation(90)
        doc.save(path)
    return truth


CASES=('row','values_first_stream','interleaved_stream','side_by_side','vertical',
       'tax_next_row','rotated_90','header_disambiguation','header_swapped')


def text_pairs(text):return {(m['field'],m['value']) for m in source_amounts(text)}


def summarize(pairs,truth):
    return dict(pairs=sorted(pairs),missing=sorted(truth-pairs),extra=sorted(pairs-truth))


def read_page(page,truth,root):
    native_text=page.get_text('text',sort=False)
    native_words=page.get_text('words');native_rows=relations(native_words)
    start=time.perf_counter()
    pix=page.get_pixmap(matrix=pymupdf.Matrix(200/72,200/72),colorspace=pymupdf.csRGB,alpha=False)
    render_s=time.perf_counter()-start
    start=time.perf_counter()
    raw=pix.pdfocr_tobytes(language='eng',tessdata=str(root/'models/tessdata'))
    ocr_s=time.perf_counter()-start
    with pymupdf.open(stream=raw,filetype='pdf') as recognized:
        ocr_text=recognized[0].get_text('text',sort=False)
        ocr_words=recognized[0].get_text('words');ocr_rows=relations(ocr_words)
    return dict(native_text=native_text,ocr_text=ocr_text,truth=sorted(truth),
        native_flat=summarize(text_pairs(native_text),truth),
        native_candidates=summarize(candidate_pairs(native_rows),truth),
        native_nearest=summarize(candidate_pairs(native_rows,nearest=True),truth),
        native_header_control=summarize(header_pairs(native_rows,native_words),truth),
        ocr_flat=summarize(text_pairs(ocr_text),truth),
        ocr_candidates=summarize(candidate_pairs(ocr_rows),truth),
        ocr_nearest=summarize(candidate_pairs(ocr_rows,nearest=True),truth),
        ocr_header_control=summarize(header_pairs(ocr_rows,ocr_words),truth),
        native_relation_rows=native_rows,ocr_relation_rows=ocr_rows,
        raster_width=pix.width,raster_height=pix.height,rgb_sample_bytes=len(pix.samples),
        render_s=render_s,ocr_s=ocr_s,ocr_calls=1,language_or_embedding_model_calls=0)


def run():
    root=Path(__file__).resolve().parents[2]
    work=root/'data/patent-research'/('r13-reader-'+uuid.uuid4().hex);work.mkdir(parents=True)
    rows=[]
    for case in CASES:
        path=work/(case+'.pdf');truth=make_fixture(path,case)
        with pymupdf.open(path) as doc:
            row=read_page(doc[0],truth,root)
            doc[0].get_pixmap().save(work/(case+'.png'))
        rows.append(dict(case=case,source_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),**row))
    crops=[]
    for case in ('header_disambiguation','header_swapped'):
        with pymupdf.open(work/(case+'.pdf')) as doc:
            page=doc[0];rect=(50,125,535,160)
            pix=page.get_pixmap(matrix=pymupdf.Matrix(200/72,200/72),clip=pymupdf.Rect(rect))
            raw=pix.pdfocr_tobytes(language='eng',tessdata=str(root/'models/tessdata'))
            with pymupdf.open(stream=raw,filetype='pdf') as recognized:text=recognized[0].get_text()
            crops.append(dict(case=case,pixel_hash=crop_hash(page,rect),ocr_text=text))
    assert crops[0]['pixel_hash']==crops[1]['pixel_hash'] and crops[0]['ocr_text']==crops[1]['ocr_text']
    report=dict(date='2026-10-21',engine=pymupdf.VersionBind,fixtures=str(work),cases=rows,
        header_counterexample=crops,total_ocr_calls=len(rows)+len(crops),
        limits=['Nine clean synthetic layouts; no production or Pawan documents used',
               'Actual full-page local English OCR; no injected OCR output',
               'No Qwen or EmbeddingGemma calls; the existing OCR engine may use neural recognition internally',
               'Ordinary row/proximity controls, not a trained or complete semantic reader',
               'Candidate recall is not relation correctness; conservative alternatives can be false',
               'Pair-set summaries collapse duplicate field instances; inspect located rows for physical links',
               'Single exploratory PC timings, no Android or selective-OCR savings',
               'No production changes, external source upload or novelty finding'])
    (root/'results/patent-r13-field-reader.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(dict(fixtures=str(work),cases=[dict(case=r['case'],
        **{k:dict(missing=r[k]['missing'],extra=r[k]['extra']) for k in
           ('native_flat','native_candidates','native_nearest','ocr_flat','ocr_candidates','ocr_nearest')}) for r in rows]),indent=2))


if __name__=='__main__':run()
