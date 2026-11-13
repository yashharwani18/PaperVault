"""R9 synthetic PDF mutations and ordinary query-dependency controls."""
from pathlib import Path
import json
import uuid

import pymupdf

from research.patent_candidate.relation_support import make_connector_pdf, crop_hash, NODE_CROP
from research.patent_candidate.relation_reuse import (
    extract_snapshot, sql_answer, cached_answer, positive_rows_reusable, partition_reusable,
)


CASES = ('unchanged', 'unrelated_text', 'unrelated_subtotal_link', 'insert_competing_total',
         'delete_total', 'reroute_both', 'insert_first_total')


def fixture(path, case, *, before=False):
    make_connector_pdf(path, swapped=case == 'reroute_both' and not before)
    remove_total = (case == 'delete_total' and not before) or (case == 'insert_first_total' and before)
    if before and not remove_total:
        return
    with pymupdf.open(path) as doc:
        page = doc[0]
        if remove_total:
            # Known generated fixture: its final two content streams are the two paths.
            streams = page.get_contents()
            remaining = [*streams[:-2], streams[-1]]
            doc.xref_set_key(page.xref, 'Contents', '[' + ' '.join(f'{x} 0 R' for x in remaining) + ']')
        if not before and case == 'unrelated_text':
            page.insert_text((40,570), 'Unrelated footer edit', fontsize=10)
        if not before and case in ('unrelated_subtotal_link', 'insert_competing_total'):
            start = (260,230) if case == 'insert_competing_total' else (260,310)
            end = (350,310) if case == 'insert_competing_total' else (350,230)
            # All four labels persist; adding a branch can also change local line pixels.
            points = [start, (280 if start[1] == 230 else 300,start[1]),
                      (280 if start[1] == 230 else 300,550), (550,550),
                      (550,40), (330 if end[1] == 230 else 320,40),
                      (330 if end[1] == 230 else 320,end[1]), end]
            shape = page.new_shape(); shape.draw_polyline(points)
            shape.finish(color=(0,0,0), width=1, closePath=False); shape.commit()
        raw = doc.tobytes()
    path.write_bytes(raw)


def run():
    root = Path(__file__).resolve().parents[2]
    work = root/'data/patent-research'/('r9-reuse-'+uuid.uuid4().hex)
    work.mkdir(parents=True)
    rows = []
    for case in CASES:
        old_path, new_path = work/(case+'-before.pdf'), work/(case+'-after.pdf')
        fixture(old_path, case, before=True); fixture(new_path, case)
        old, new = extract_snapshot(old_path), extract_snapshot(new_path)
        exact = sql_answer(new, 'total')
        observed, observed_reuse = cached_answer(old, new, 'total', positive_rows_reusable)
        guarded, guarded_reuse = cached_answer(old, new, 'total', partition_reusable)
        with pymupdf.open(old_path) as a, pymupdf.open(new_path) as b:
            same_crop = crop_hash(a[0],NODE_CROP) == crop_hash(b[0],NODE_CROP)
        rows.append(dict(case=case, old_revision=old.revision, new_revision=new.revision,
            before_answer=sql_answer(old,'total'), exact_answer=exact, same_node_crop=same_crop,
            positive_rows_answer=observed, positive_rows_reused=observed_reuse,
            positive_rows_correct=observed==exact, partition_answer=guarded,
            partition_reused=guarded_reuse, partition_correct=guarded==exact,
            parsed_paths_before=len(old.rows), parsed_paths_after=len(new.rows)))
    report = dict(date='2026-10-21', fixtures=str(work), cases=rows,
        positive_rows_failures=sum(not r['positive_rows_correct'] for r in rows),
        partition_failures=sum(not r['partition_correct'] for r in rows),
        limits=['Both source revisions fully parsed; no extraction/OCR work avoided',
                'Supplied static anchors and restricted native paths; not source-semantic completeness',
                'Direct SQL already answers all cases, with no OCR or model calls',
                'No latency, memory, power, Android or novelty claim; no production changes'])
    assert report['positive_rows_failures'] == 2 and report['partition_failures'] == 0
    (root/'results/patent-r9-reuse.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2))


if __name__ == '__main__': run()
