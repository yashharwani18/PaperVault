"""Actual native paint-state and English OCR observations on synthetic PDFs."""
from pathlib import Path
import json
import statistics
import time
import uuid

import pymupdf

from research.patent_candidate.visibility_probe import inspect_occurrences
from research.patent_candidate.test_visibility_probe import fixture


def run():
    root=Path(__file__).resolve().parents[2]
    tessdata=root/'models/tessdata'
    if not (tessdata/'eng.traineddata').is_file():
        raise RuntimeError('Existing local English OCR data is required; nothing downloaded.')
    work=root/'data/patent-research'/('r6-visibility-'+uuid.uuid4().hex);work.mkdir(parents=True)
    rows=[]
    for kind in ('normal','invisible','transparent','covered','sandwich','transparent_overlay','white','rotated'):
        with fixture(kind) as doc:
            path=work/(kind+'.pdf');doc.save(path)
        with pymupdf.open(path) as doc:
            page=doc[0];times=[]
            for _ in range(11):
                start=time.perf_counter();observations=inspect_occurrences(page,'13600.00');times.append(time.perf_counter()-start)
            start=time.perf_counter()
            textpage=page.get_textpage_ocr(language='eng',dpi=200,full=True,tessdata=str(tessdata))
            ocr=page.get_text('text',textpage=textpage)
            ocr_s=time.perf_counter()-start
            pix=page.get_pixmap(dpi=200)
            rows.append(dict(case=kind,native_contains_amount='13600.00' in page.get_text(),
                observations=observations,rendered_ocr_text=ocr.strip(),
                rendered_ocr_contains_amount='13600' in ocr.replace(',','').replace(' ',''),
                native_triage_median_s=statistics.median(times),full_page_ocr_single_s=ocr_s,
                render_pixels=pix.width*pix.height,
                ground_truth_visible_amount=kind in ('normal','sandwich','transparent_overlay','rotated')))
    report=dict(date='2026-10-21',fixtures=str(work),engine=pymupdf.VersionBind,ocr_dpi=200,
        repetitions=dict(native_triage=11,full_page_ocr=1),cases=rows,
        limits=['Synthetic small pages and simple Helvetica amounts only',
                'Native timing is warm; single OCR sample is exploratory PC timing, not a fair benchmark or phone measurement',
                'OCR observations are not a semantic truth or universal visibility oracle',
                'No source PDFs, active library data or production search behavior changed'])
    out=root/'results/patent-r6-visibility.json';out.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps([{k:row[k] for k in ('case','native_contains_amount','rendered_ocr_contains_amount','ground_truth_visible_amount')} for row in rows],indent=2))


if __name__=='__main__':run()
