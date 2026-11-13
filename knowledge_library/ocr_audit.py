"""Optional bounded residual-ink retries. This is not a completeness detector."""
import math
import numpy as np
import pymupdf
from scipy import ndimage


def audit(page,words,options):
    scale=min(150/72,math.sqrt(1_000_000/max(1,page.rect.get_area())))
    pix=page.get_pixmap(matrix=pymupdf.Matrix(scale,scale),colorspace=pymupdf.csGRAY,alpha=False)
    ink=np.frombuffer(pix.samples_mv,dtype=np.uint8).reshape(pix.height,pix.width)<240
    for w in words:
        left=max(0,math.floor((w[0]-2)*scale));right=min(pix.width,math.ceil((w[2]+2)*scale))
        top=max(0,math.floor((w[1]-2)*scale));bottom=min(pix.height,math.ceil((w[3]+2)*scale))
        ink[top:bottom,left:right]=False
    grouped=ndimage.binary_dilation(ink,structure=np.ones((3,11),dtype=bool))
    labels,_=ndimage.label(grouped)
    regions=[]
    for region in ndimage.find_objects(labels):
        if region is None:continue
        y,x=region
        if np.count_nonzero(ink[y,x])<10:continue
        box=pymupdf.Rect(x.start/scale-4,y.start/scale-4,x.stop/scale+4,y.stop/scale+4)&page.rect
        if box.height>0 and box.width/box.height>=1.5:regions.append(box)
    record=dict(state='bounded_audit',detector_pixels=pix.width*pix.height,regions_detected=len(regions),
        attempts=[],complete=False,limit=options.ocr_retry_limit,
        note='Residual ink may be decoration; missed regions and unread text remain possible. Decode memory is additional.')
    extra=[];remaining=min(4_000_000,options.max_ocr_pixels)
    for box in sorted(regions,key=lambda b:(b.y0,b.x0)):
        if len(record['attempts'])>=options.ocr_retry_limit:break
        bounds=(box*pymupdf.Matrix(600/72,600/72)).irect
        cost=bounds.width*bounds.height
        if cost>remaining:continue
        remaining-=cost;attempt=dict(bbox=list(box),pixels=cost,status='unread')
        record['attempts'].append(attempt)
        try:
            crop=page.get_pixmap(matrix=pymupdf.Matrix(600/72,600/72),clip=box,colorspace=pymupdf.csRGB,alpha=False)
            crop.set_dpi(600,600)
            with pymupdf.open('pdf',crop.pdfocr_tobytes(language=options.ocr_language,tessdata=options.tessdata)) as doc:
                read=doc[0].get_text('words',sort=False)
            ox,oy=crop.x*72/600,crop.y*72/600
            for w in read:
                mapped=[w[0]+ox,w[1]+oy,w[2]+ox,w[3]+oy,w[4],1_000_000+len(record['attempts'])*1000+w[5],w[6],w[7]]
                if not any(old[4]==mapped[4] and (pymupdf.Rect(old[:4])&pymupdf.Rect(mapped[:4])).get_area()>0 for old in words+extra):extra.append(mapped)
            attempt['status']='text_observed' if read else 'no_text_observed'
        except Exception as exc:attempt['status']='failed';attempt['error']=str(exc)
    record['work_exhausted']=len(record['attempts'])<len(regions)
    return extra,record
