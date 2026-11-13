"""Read-only raster/OCR measurements on an existing synthetic invoice fixture.

Ground-truth boxes come from native fixture text. This is NOT a layout-detector
evaluation, scan robustness evaluation, alternative-hypothesis generator, or
phone power benchmark. No generated PDF artifact is saved.
"""
import json
from pathlib import Path
import statistics
import sys
import time

import pymupdf

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from knowledge_library.bill_amounts import source_amounts


def main():
    source=ROOT/'tests/fixtures/invoice-pack/classic.pdf'
    out=ROOT/'results/patent-r2-crop-ocr.json'
    document=pymupdf.open(source)
    page=document[0]
    value=page.search_for('5,310.00')[0]
    label=page.search_for('Grand Total:')[0]
    joint=pymupdf.Rect(label)|value
    cases={'full_page':page.rect,'value_only':value+(-4,-4,4,4),
           'label_and_value':joint+(-4,-4,4,4)}
    result={}
    # Three rotated-order rounds reduce a fixed first-call warmup bias.
    for round in range(3):
        names=list(cases)
        for name in names[round:]+names[:round]:
            start=time.perf_counter()
            pix=page.get_pixmap(matrix=pymupdf.Matrix(200/72,200/72),clip=cases[name],
                colorspace=pymupdf.csRGB,alpha=False)
            rendered=time.perf_counter()-start
            start=time.perf_counter()
            pdfbytes=pix.pdfocr_tobytes(language='eng',tessdata=str(ROOT/'models/tessdata'))
            recognized=pymupdf.open(stream=pdfbytes,filetype='pdf')
            text=recognized[0].get_text()
            recognized.close()
            ocr_s=time.perf_counter()-start
            row=result.setdefault(name,dict(pixels=pix.width*pix.height,raster_bytes=pix.stride*pix.height,
                width=pix.width,height=pix.height,rounds=[]))
            matches=list(source_amounts(text))
            row['rounds'].append(dict(render_s=rendered,ocr_s=ocr_s,
                total_s=rendered+ocr_s,exact_total_detected=any(r['field']=='total' and r['value']=='5310.00' for r in matches),
                recognized_text=text))
            if round==0 and name!='full_page':
                pix.save(str(ROOT/f'results/patent-r2-{name}.png'))
    for value in result.values():value['median_total_s']=statistics.median(x['total_s'] for x in value['rounds'])
    document.close()
    payload=dict(fixture='existing clearly marked synthetic classic invoice',dpi=200,cases=result,
        note='Native fixture boxes supplied, all text clean, fixed single template. Pixel bytes exclude renderer/OCR native allocations. Does not establish novel crop selection, production extraction accuracy, hard total RAM savings or phone energy savings.')
    out.write_text(json.dumps(payload,indent=2),encoding='utf-8')
    print(json.dumps(payload,indent=2))


if __name__=='__main__':main()
