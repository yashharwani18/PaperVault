"""R25 ordinary subset planning with measured render-profile thresholds.

Query/action semantics are supplied synthetic graph contracts, not readings of
the R23 pattern images. Rendering costs are actual Windows measurements. This
does not establish source completeness, hard RAM admission or a new optimizer.
"""
from contextlib import ExitStack
import hashlib
from itertools import combinations,permutations
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pymupdf

from research.patent_candidate.assignment_evidence import AssignmentEvidence
from research.patent_candidate.bounded_matching import opposite_pair
from research.patent_candidate.measure_decode_memory import memory


ACTIONS={
    'f0':dict(file='progressive.pdf',clip=[0,0,8,8],pixels=4096),
    'f1':dict(file='jpeg.pdf',clip=[0,0,16,16],pixels=16384),
    'f2':dict(file='jpeg.pdf',clip=[62.5,62.5,78.5,78.5],pixels=16384),
}


def worker(work,fields):
    with ExitStack() as stack:
        docs={file:stack.enter_context(pymupdf.open(work/file)) for file in {ACTIONS[f]['file'] for f in fields}}
        before=memory();start=time.perf_counter();outputs=[]
        for field in fields:
            action=ACTIONS[field]
            pix=docs[action['file']][0].get_pixmap(matrix=pymupdf.Matrix(8,8),
                clip=pymupdf.Rect(action['clip']),colorspace=pymupdf.csRGB,alpha=False)
            assert pix.width*pix.height==action['pixels']
            outputs.append(dict(field=field,pixels=pix.width*pix.height,
                sha256=hashlib.sha256(pix.samples_mv).hexdigest()))
            del pix
        after=memory()
        return dict(before=before,after=after,historical_peak_increase=max(0,
            after['peak_working_set']-before['peak_working_set']),elapsed_s=time.perf_counter()-start,outputs=outputs)


def run():
    if os.name!='nt':raise RuntimeError('Windows profile only')
    root=Path(__file__).resolve().parents[2]
    previous=json.loads((root/'results/patent-r23-decode-memory.json').read_text(encoding='utf-8'))
    work=Path(previous['fixtures'])
    fields=sorted(ACTIONS)
    boxes={f:(i*10,0,i*10+5,5) for i,f in enumerate(fields)}
    values={f'v{i}':(i*10,10,i*10+5,15) for i in range(3)}
    model=AssignmentEvidence({f:set(values) for f in fields},boxes,values,revision='r25-supplied-contract')
    worlds=[dict(zip(fields,p)) for p in permutations(values)]
    subsets=[s for n in range(1,4) for s in combinations(fields,n)]
    runs=[]
    for round_number in range(3):
        for subset in (subsets if round_number%2==0 else list(reversed(subsets))):
            completed=subprocess.run([sys.executable,'-m','research.patent_candidate.measure_memory_plan',
                '--worker',str(work),json.dumps(subset)],cwd=root,capture_output=True,text=True,
                encoding='utf-8',timeout=30,creationflags=subprocess.CREATE_NO_WINDOW)
            if completed.returncode:raise RuntimeError(completed.stderr)
            runs.append(dict(fields=subset,round=round_number,**json.loads(completed.stdout)))
    profiles=[]
    for subset in subsets:
        groups={}
        for world in worlds:
            groups.setdefault(tuple(world[f] for f in subset),set()).add(world['f0']=='v0')
        partition_agreement=all(len(outcomes)==1 for outcomes in groups.values())
        oracle=opposite_pair(model,'f0',{'v0'},subset)
        assert partition_agreement==(oracle['status']=='determines_in_model')
        direct_agreement='f0' in subset or {'f1','f2'}<=set(subset)
        assert partition_agreement==direct_agreement
        subset_runs=[r for r in runs if r['fields']==subset]
        profiles.append(dict(fields=subset,pixels=sum(ACTIONS[f]['pixels'] for f in subset),
            all_outcome_agreement_in_model=partition_agreement,
            observed_peak_increase=max(r['historical_peak_increase'] for r in subset_runs),
            total_peak_range=[min(r['after']['peak_working_set'] for r in subset_runs),
                              max(r['after']['peak_working_set'] for r in subset_runs)]))
    allowance=16*1024*1024
    agreements=[p for p in profiles if p['all_outcome_agreement_in_model']]
    area_min=min(agreements,key=lambda p:(p['pixels'],p['fields']))
    admitted=[p for p in agreements if p['observed_peak_increase']<=allowance]
    joint=min(admitted,key=lambda p:(p['pixels'],p['fields'])) if admitted else None
    assert area_min['fields']==('f0',) and area_min['observed_peak_increase']>allowance
    assert joint and joint['fields']==('f1','f2')
    observations=[]
    for world in worlds:
        observed={f:world[f] for f in joint['fields']}
        agrees={w['f0']=='v0' for w in worlds if all(w[f]==v for f,v in observed.items())}
        assert len(agrees)==1
        observations.append(dict(world=world,observed=observed,predicate=agrees.pop()))
    report=dict(date='2026-10-22',fixtures=str(work),actions=ACTIONS,measured_runs=runs,profiles=profiles,
        profile_threshold_bytes=allowance,area_minimum=area_min,
        area_then_reject='unresolved_under_profile_threshold',ordinary_joint_subset_control=joint,
        all_six_observation_outcomes=observations,
        limits=['Synthetic one-to-one action/evidence graph; no source-reading or OCR semantics assigned by a recognizer',
                'Actual rendering costs for pattern images, not an end-to-end document-answering experiment',
                'Observed maximum of three historical-peak differences is not a guaranteed RAM bound',
                'Threshold applies after PDF opens and excludes query planner, OCR, models, UI and other processes',
                'Sequential schedule discards crop pixmaps; no concurrency or alternative schedules measured',
                'Ordinary exhaustive subset/partition and direct structural controls attain the same result',
                'No new optimizer, production change, Android proof or patentability conclusion'])
    (root/'results/patent-r25-memory-plan.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(dict(runs=len(runs),area_minimum=area_min,joint_control=joint,
        graph_worlds_checked=len(observations),threshold=allowance),indent=2))


if __name__=='__main__':
    if len(sys.argv)>1 and sys.argv[1]=='--worker':print(json.dumps(worker(Path(sys.argv[2]),json.loads(sys.argv[3]))))
    else:run()
