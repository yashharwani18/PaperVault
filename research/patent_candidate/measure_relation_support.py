"""R8 actual rendering counterexample and native-connector control."""
from pathlib import Path
import hashlib
import json
import uuid

import pymupdf

from research.patent_candidate.relation_support import (
    make_connector_pdf,vector_relations,closure_plan,crop_hash,NODE_CROP,
)


def run():
    root=Path(__file__).resolve().parents[2]
    work=root/'data/patent-research'/('r8-relations-'+uuid.uuid4().hex);work.mkdir(parents=True)
    rows=[]
    for name,swapped in [('straight',False),('swapped',True)]:
        path=work/(name+'.pdf');make_connector_pdf(path,swapped)
        with pymupdf.open(path) as doc:
            page=doc[0];relations=vector_relations(page)
            plan=closure_plan(page,relations,pixel_budget=100_000)
            page.get_pixmap().save(work/(name+'-full.png'))
            page.get_pixmap(clip=pymupdf.Rect(NODE_CROP)).save(work/(name+'-nodes.png'))
            page.get_pixmap(clip=pymupdf.Rect(plan['support_crop'])).save(work/(name+'-support.png'))
            rows.append(dict(case=name,source_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                extracted_text=page.get_text('text'),node_crop_hash=crop_hash(page,NODE_CROP),
                full_render_hash=crop_hash(page,page.rect),
                native_relations={r['field']:r['value'] for r in relations},
                plan=plan,neural_model_calls=0,ocr_calls=0))
    assert rows[0]['node_crop_hash']==rows[1]['node_crop_hash']
    assert rows[0]['extracted_text']==rows[1]['extracted_text']
    assert rows[0]['native_relations']!=rows[1]['native_relations']
    report=dict(date='2026-10-21',fixtures=str(work),engine=pymupdf.VersionBind,cases=rows,
        finding='Identical node pixels/text admit opposite query relations. Ordinary native connector tracing already distinguishes the fixtures.',
        limits=['Supplied node boxes, open line-only vector paths, no raster connector detection',
                'Not a trained relation extractor or a representative accuracy test',
                'Closure is conventional bbox expansion, not a novelty finding',
                'Pixel estimates are not total process memory or phone resource bounds',
                'No live library changes or external disclosures'])
    (root/'results/patent-r8-relations.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({'fixtures':str(work),'cases':[dict(case=r['case'],relations=r['native_relations'],
        estimated_pixels=r['plan']['estimated_pixels'],admitted_at_100000=r['plan']['admitted']) for r in rows]},indent=2))


if __name__=='__main__':run()
