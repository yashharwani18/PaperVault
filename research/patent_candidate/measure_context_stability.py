"""R16 actual local OCR audit of crop agreement, not a sufficiency certificate."""
import hashlib
import json
from pathlib import Path
import uuid

import pymupdf

from research.patent_candidate.field_geometry import relations, candidate_pairs


def fixture(path,*,current_right,header_size):
    with pymupdf.open() as doc:
        page=doc.new_page(width=600,height=420)
        page.insert_text((35,35),'SYNTHETIC CONTEXT RESEARCH - NOT A REAL BILL',fontsize=12)
        for center,current in ((265,not current_right),(445,current_right)):
            text='Current Invoice' if current else 'Previous Invoice'
            width=pymupdf.get_text_length(text,fontsize=header_size)
            page.insert_text((center-width/2,90),text,fontsize=header_size)
        page.insert_text((60,320),'Grand Total:',fontsize=16)
        page.insert_text((230,320),'250.00',fontsize=16)
        page.insert_text((410,320),'10500.00',fontsize=16)
        doc.save(path)


def header_control(words):
    """Fixture-specific current-invoice column control; no generic semantics claim."""
    headers=[]
    for word in words:
        if word[4].casefold()!='current':continue
        following=[w for w in words if w[4].casefold()=='invoice'
                   and 0<=w[0]-word[2]<20 and abs(w[1]-word[1])<3]
        if following:headers.append((word[0],min(following,key=lambda w:w[0])[2],word[3]))
    return sorted({v['value'] for row in relations(words) for v in row['candidates']
        if any(left<=(v['box'][0]+v['box'][2])/2<=right and bottom<v['box'][1]
               for left,right,bottom in headers)})


def ocr(page,root,*,dpi,clip=None):
    pix=page.get_pixmap(matrix=pymupdf.Matrix(dpi/72,dpi/72),
                        clip=None if clip is None else pymupdf.Rect(clip),
                        colorspace=pymupdf.csRGB,alpha=False)
    # Keep OCR word coordinates in page points at every resolution; matrix
    # rendering alone does not set Pixmap resolution metadata.
    pix.set_dpi(dpi,dpi)
    raw=pix.pdfocr_tobytes(language='eng',tessdata=str(root/'models/tessdata'))
    with pymupdf.open(stream=raw,filetype='pdf') as recognized:
        words=recognized[0].get_text('words');text=recognized[0].get_text()
    return dict(text=text,words=words,nearest_pairs=sorted(candidate_pairs(relations(words),nearest=True)),
                header_values=header_control(words),pixels=pix.width*pix.height,
                raster_hash=hashlib.sha256(pix.samples).hexdigest(),dpi=dpi,clip=clip)


def run():
    root=Path(__file__).resolve().parents[2]
    work=root/'data/patent-research'/('r16-context-'+uuid.uuid4().hex);work.mkdir(parents=True)
    cases=[]
    for size in (16,4):
        for right in (False,True):
            name=f'header_{size}_current_right_{right}'
            path=work/(name+'.pdf');fixture(path,current_right=right,header_size=size)
            with pymupdf.open(path) as doc:
                page=doc[0]
                reads=dict(tight=ocr(page,root,dpi=200,clip=(50,295,535,335)),
                    expanded=ocr(page,root,dpi=200,clip=(25,250,560,380)),
                    full_72=ocr(page,root,dpi=72),full_300=ocr(page,root,dpi=300))
                native=header_control(page.get_text('words'))
                page.get_pixmap(matrix=pymupdf.Matrix(2,2)).save(work/(name+'.png'))
            truth='10500.00' if right else '250.00'
            assert native==[truth]
            assert reads['tight']['nearest_pairs']==[('total','250.00')]
            assert reads['expanded']['nearest_pairs']==[('total','250.00')]
            cases.append(dict(case=name,truth=truth,native_header_control=native,reads=reads,
                nested_nearest_agreement=reads['tight']['nearest_pairs']==reads['expanded']['nearest_pairs'],
                nested_nearest_wrong=('total',truth) not in reads['tight']['nearest_pairs']))
    # Within each font-size pair, both nested observations omit the changed header.
    for left,right in ((cases[0],cases[1]),(cases[2],cases[3])):
        assert left['truth']!=right['truth']
        for key in ('tight','expanded'):
            assert left['reads'][key]['raster_hash']==right['reads'][key]['raster_hash']
            assert left['reads'][key]['text']==right['reads'][key]['text']
    report=dict(date='2026-10-21',fixtures=str(work),engine=pymupdf.VersionBind,cases=cases,
        actual_ocr_calls_per_run=16,language_or_embedding_model_calls=0,
        limits=['Synthetic two-column current/previous invoice contract, not representative bill evaluation',
                'Fixture-specific column reader, not a learned or complete document parser',
                'Two tested nested crops only; no test of arbitrary adaptive policies',
                'Agreement is not asserted to be sufficient; full context can also be recognized incorrectly',
                'Pixel payload is not total memory and desktop OCR is not an Android performance measurement',
                'No production change or patentability conclusion'])
    (root/'results/patent-r16-context-stability.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(dict(fixtures=str(work),cases=[dict(case=c['case'],truth=c['truth'],
        nested_agreement=c['nested_nearest_agreement'],nested_wrong=c['nested_nearest_wrong'],
        full_72_header=c['reads']['full_72']['header_values'],
        full_300_header=c['reads']['full_300']['header_values']) for c in cases]),indent=2))


if __name__=='__main__':run()
