"""R8 controlled vector-connector experiment, not a general diagram parser.

Native source anchors are supplied. Only open, line-only PDF paths whose
endpoints touch supplied field/value rectangles are interpreted as connectors.
The closure operation is ordinary geometry, not an invention assertion.
"""
import hashlib
import math

import pymupdf
from research.patent_candidate.raster_cost import raster_pixels


FIELDS={'total':(170,210,260,250),'subtotal':(170,290,260,330)}
VALUES={'13600':(350,210,440,250),'13900':(350,290,440,330)}
NODE_CROP=(170,210,440,330)


def make_connector_pdf(path,swapped=False):
    with pymupdf.open() as doc:
        page=doc.new_page(width=600,height=600)
        page.insert_text((40,40),'Synthetic connector worksheet. Crossings without dots do not join.',fontsize=10)
        for name,box in FIELDS.items():
            page.draw_rect(box,color=(0,0,0))
            page.insert_text((box[0]+10,box[1]+25),name.title(),fontsize=14)
        for name,box in VALUES.items():
            page.draw_rect(box,color=(0,0,0))
            page.insert_text((box[0]+10,box[1]+25),name+'.00',fontsize=14)
        if not swapped:
            paths=[[(260,230),(280,230),(280,140),(280,100),(330,100),(330,140),(330,230),(350,230)],
                   [(260,310),(300,310),(300,400),(300,450),(320,450),(320,400),(320,310),(350,310)]]
        else:
            paths=[[(260,230),(280,230),(280,140),(280,100),(80,100),(80,450),(320,450),(320,400),(320,310),(350,310)],
                   [(260,310),(300,310),(300,400),(300,500),(520,500),(520,80),(330,80),(330,140),(330,230),(350,230)]]
        for points in paths:
            shape=page.new_shape();shape.draw_polyline(points)
            shape.finish(color=(0,0,0),width=1,closePath=False);shape.commit()
        doc.save(path)


def _touch(point,anchors):
    for name,rect in anchors.items():
        if point in pymupdf.Rect(rect)+(-.1,-.1,.1,.1):return name
    return None


def vector_relations(page,fields=FIELDS,values=VALUES):
    result=[]
    for drawing in page.get_drawings():
        items=drawing['items']
        if drawing['closePath'] or len(items)<2 or any(item[0]!='l' for item in items):continue
        start,end=items[0][1],items[-1][2]
        field,value=_touch(start,fields),_touch(end,values)
        if field is None or value is None:
            field,value=_touch(end,fields),_touch(start,values)
        if field is None or value is None:continue
        points=[list(items[0][1])]+[list(item[2]) for item in items]
        result.append(dict(field=field,value=value,points=points,source_sequence=drawing['seqno']))
    return result


def closure_plan(page,relations,*,node_crop=NODE_CROP,scale=1,pixel_budget=200_000):
    if not math.isfinite(scale) or scale<=0 or type(pixel_budget) is not int or pixel_budget<0:
        raise ValueError('Invalid raster allowance')
    crop=pymupdf.Rect(node_crop)
    clipped=[]
    for relation in relations:
        outside=any(not (crop.x0<=x<=crop.x1 and crop.y0<=y<=crop.y1) for x,y in relation['points'])
        if outside:clipped.append(relation['source_sequence'])
    support=pymupdf.Rect(crop)
    for relation in relations:
        for x,y in relation['points']:
            support|=pymupdf.Rect(x-.5,y-.5,x+.5,y+.5)
    support=(support+(-2,-2,2,2))&page.rect
    pixels=raster_pixels(support,scale)
    admitted=bool(pixels and pixels<=pixel_budget)
    return dict(node_crop=list(crop),connector_support_clipped=clipped,
        support_crop=list(support),estimated_pixels=pixels,
        admitted=admitted,
        outcome='source_support_available' if admitted else 'unknown_empty_raster' if not pixels else 'unknown_budget_exhausted',
        limitation='Closure covers supplied native line paths only; it does not prove all semantic evidence is present.')


def crop_hash(page,rect,scale=2):
    pix=page.get_pixmap(matrix=pymupdf.Matrix(scale,scale),clip=pymupdf.Rect(rect),alpha=False)
    return hashlib.sha256(pix.samples).hexdigest()
