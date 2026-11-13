"""R12 actual renderer accounting, preserving historical R8 raw results."""
import json
import math
from pathlib import Path
import random

import pymupdf

from research.patent_candidate.raster_cost import raster_cost
from research.patent_candidate.relation_support import closure_plan,vector_relations


def old_cost(rect,scale):
    return math.ceil((rect[2]-rect[0])*scale)*math.ceil((rect[3]-rect[1])*scale)


def run():
    root=Path(__file__).resolve().parents[2];rows=[]
    samples=[((.4,.4,10.4,10.4),1)]
    rng=random.Random(1212)
    for _ in range(64):
        x,y=rng.uniform(0,100),rng.uniform(0,100)
        samples.append(((x,y,x+rng.uniform(1,70),y+rng.uniform(1,70)),rng.choice((.5,1,1.25,200/72,3))))
    with pymupdf.open() as doc:
        page=doc.new_page(width=200,height=200)
        for rect,scale in samples:
            planned=raster_cost(rect,scale,page_rect=page.rect)
            pix=page.get_pixmap(matrix=pymupdf.Matrix(scale,scale),clip=pymupdf.Rect(rect),alpha=False)
            actual=pix.width*pix.height
            assert planned['pixels']==actual
            rows.append(dict(rect=rect,scale=scale,old_formula_pixels=old_cost(rect,scale),
                             renderer_grid=planned,actual_pixels=actual,rgb_sample_bytes=len(pix.samples)))
    historical=json.loads((root/'results/patent-r8-relations.json').read_text(encoding='utf-8'))
    comparisons=[]
    for item in historical['cases']:
        path=Path(historical['fixtures'])/(item['case']+'.pdf')
        with pymupdf.open(path) as doc:
            page=doc[0];plan=closure_plan(page,vector_relations(page),pixel_budget=100_000)
            pix=page.get_pixmap(clip=pymupdf.Rect(plan['support_crop']))
            assert plan['estimated_pixels']==pix.width*pix.height
            comparisons.append(dict(case=item['case'],historical_estimate=item['plan']['estimated_pixels'],
                current_grid_pixels=plan['estimated_pixels'],actual_pixels=pix.width*pix.height,
                admitted_at_100000=plan['admitted']))
    report=dict(date='2026-10-21',engine=pymupdf.VersionBind,samples=rows,
        old_undercharges=sum(r['old_formula_pixels']<r['actual_pixels'] for r in rows),
        new_grid_mismatches=sum(r['renderer_grid']['pixels']!=r['actual_pixels'] for r in rows),
        historical_r8_recheck=comparisons,
        limits=['Synthetic geometry and actual raster dimensions; not OCR or phone memory',
                'Positive uniform scales, render-coordinate clips, known page rectangle',
                'Only pixel/sample payload measured; no bound on working allocations',
                'Ordinary documented renderer rounding, no novelty claim',
                'Historical raw R8 result preserved; no production changes'])
    (root/'results/patent-r12-raster-cost.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='samples'},indent=2))


if __name__=='__main__':run()
