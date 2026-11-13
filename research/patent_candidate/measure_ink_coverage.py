"""R17 ordinary residual-ink connected-component control, synthetic scans only."""
import json
import math
from pathlib import Path
import uuid

import numpy as np
from scipy import ndimage
import pymupdf

from research.patent_candidate.measure_context_stability import ocr,header_control


def make_scan(path,*,right=True,decor=False,gray=False):
    with pymupdf.open() as source:
        page=source.new_page(width=600,height=420)
        page.insert_text((35,35),'SYNTHETIC SCAN - NOT A REAL BILL',fontsize=12)
        for center,current in ((265,not right),(445,right)):
            text='Current Invoice' if current else 'Previous Invoice'
            size=4; width=pymupdf.get_text_length(text,fontsize=size)
            page.insert_text((center-width/2,90),text,fontsize=size,
                             color=(.85,.85,.85) if gray else (0,0,0))
        page.insert_text((60,320),'Grand Total:',fontsize=16)
        page.insert_text((230,320),'250.00',fontsize=16)
        page.insert_text((410,320),'10500.00',fontsize=16)
        if decor:
            for i in range(8):
                page.draw_rect((60+i*4,175,62+i*4,180),color=None,fill=(0,0,0))
        pix=page.get_pixmap(matrix=pymupdf.Matrix(300/72,300/72))
        with pymupdf.open() as scanned:
            target=scanned.new_page(width=600,height=420)
            target.insert_image(target.rect,stream=pix.tobytes('png'))
            scanned.save(path)


def residual_regions(page,words,*,dpi=150,threshold=180):
    pix=page.get_pixmap(matrix=pymupdf.Matrix(dpi/72,dpi/72),
                        colorspace=pymupdf.csGRAY,alpha=False)
    ink=np.frombuffer(pix.samples,dtype=np.uint8).reshape(pix.height,pix.width)<threshold
    for w in words:
        x0,y0,x1,y1=w[:4]
        left=max(0,math.floor((x0-2)*dpi/72));right=min(pix.width,math.ceil((x1+2)*dpi/72))
        top=max(0,math.floor((y0-2)*dpi/72));bottom=min(pix.height,math.ceil((y1+2)*dpi/72))
        ink[top:bottom,left:right]=False
    grouped=ndimage.binary_dilation(ink,structure=np.ones((3,11),dtype=bool))
    labels,_=ndimage.label(grouped)
    boxes=[]
    for region in ndimage.find_objects(labels):
        if region is None:continue
        y,x=region
        if np.count_nonzero(ink[y,x])<10:continue
        box=pymupdf.Rect((x.start*72/dpi-4,y.start*72/dpi-4,
                          x.stop*72/dpi+4,y.stop*72/dpi+4)) & page.rect
        boxes.append(tuple(box))
    return sorted(boxes),int(np.count_nonzero(ink)),pix.width*pix.height


def run():
    root=Path(__file__).resolve().parents[2]
    work=root/'data/patent-research'/('r17-ink-'+uuid.uuid4().hex);work.mkdir(parents=True)
    cases=[];calls=0
    for name,options in [('left',dict(right=False)),('right',{}),
                         ('decoration',dict(decor=True)),('faint',dict(gray=True))]:
        path=work/(name+'.pdf');make_scan(path,**options)
        with pymupdf.open(path) as doc:
            page=doc[0];assert page.get_text().strip()==''
            first=ocr(page,root,dpi=72);full=ocr(page,root,dpi=300);calls+=2
            regions,uncovered,scan_pixels=residual_regions(page,first['words'])
            retries=[];merged=list(first['words'])
            for box in regions:
                read=ocr(page,root,dpi=600,clip=box);calls+=1
                # Crop raster starts at an integer pixel boundary; OCR PDF words
                # are local page points because the helper sets resolution metadata.
                origin=[math.floor(box[i]*600/72)*72/600 for i in (0,1)]
                mapped=[(w[0]+origin[0],w[1]+origin[1],w[2]+origin[0],w[3]+origin[1],*w[4:])
                        for w in read['words']]
                merged.extend(mapped);retries.append(dict(box=box,read=read))
            answer=header_control(merged)
            truth='250.00' if name=='left' else '10500.00'
            # Equally scoped stronger conventional control: retain light ink.
            # No threshold is selected using a case's expected answer.
            light_regions,light_uncovered,_=residual_regions(page,first['words'],threshold=240)
            light_retries=[];light_merged=list(first['words'])
            for box in light_regions:
                read=ocr(page,root,dpi=600,clip=box);calls+=1
                origin=[math.floor(box[i]*600/72)*72/600 for i in (0,1)]
                light_merged.extend((w[0]+origin[0],w[1]+origin[1],w[2]+origin[0],w[3]+origin[1],*w[4:])
                                    for w in read['words'])
                light_retries.append(dict(box=box,read=read))
            light_answer=header_control(light_merged)
            assert light_answer==[truth], 'Conventional light-ink control failed the synthetic fixture'
            # Detection does not use the following scoring-only fixture geometry.
            hit_headers=sum(any(pymupdf.Rect(b).intersects(pymupdf.Rect(c-20,85,c+20,92))
                                for b in regions) for c in (265,445))
            preview=page.get_pixmap(matrix=pymupdf.Matrix(2,2));preview.save(work/(name+'.png'))
            cases.append(dict(case=name,truth=truth,baseline_72=first,baseline_300=full,
                detected_regions=regions,uncovered_dark_pixels=uncovered,coverage_scan_pixels=scan_pixels,
                scoring_only_headers_hit=hit_headers,retries=retries,merged_header_values=answer,
                correct=answer==[truth],retry_pixels=sum(r['read']['pixels'] for r in retries),
                light_threshold_control=dict(threshold=240,regions=light_regions,
                    uncovered_pixels=light_uncovered,retries=light_retries,answer=light_answer,
                    correct=light_answer==[truth],retry_pixels=sum(r['read']['pixels'] for r in light_retries))))
    report=dict(date='2026-10-21',fixtures=str(work),cases=cases,actual_ocr_calls_per_run=calls,
        parameters=dict(coverage_dpi=150,dark_threshold=180,ocr_box_padding_points=2,
                        dilation_pixels=[3,11],minimum_ink_pixels=10,retry_dpi=600),
        limits=['Conventional residual-ink and connected-component baseline, not a new algorithm',
                'Image-only synthetic PDFs with 300-DPI source rasters; no hidden native text',
                'Detected ink is not necessarily text or query-relevant; detection can miss faint content',
                'No completeness certificate, learned detector, Qwen, embedding, production or phone execution',
                'Raster pixels exclude decode/mask/label/OCR memory and are not a peak RAM or speed measurement'])
    (root/'results/patent-r17-ink-coverage.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(dict(fixtures=str(work),ocr_calls=calls,cases=[dict(case=c['case'],
        headers_hit=c['scoring_only_headers_hit'],regions=len(c['detected_regions']),
        merged=c['merged_header_values'],correct=c['correct'],retry_pixels=c['retry_pixels'],
        light_threshold_answer=c['light_threshold_control']['answer'],
        light_threshold_correct=c['light_threshold_control']['correct']) for c in cases]),indent=2))


if __name__=='__main__':run()
