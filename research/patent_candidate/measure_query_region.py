"""R11 coordinate/constraint experiment; no real recognizer or phone benchmark."""
from itertools import combinations,permutations
import json
from pathlib import Path

from research.patent_candidate.assignment_evidence import AssignmentEvidence
from research.patent_candidate.query_region import QueryRegion,union_box,pixels


def exhaustive_control(planner,targets):
    fields=sorted(planner.evidence.domains)
    worlds=[dict(zip(fields,vs)) for vs in permutations(planner.evidence.value_boxes)
            if all(v in planner.evidence.domains[f] for f,v in zip(fields,vs))]
    goal=planner.nominal['f0'] in targets;choices=[]
    for size in range(1,len(planner.actions)+1):
        for subset in combinations(sorted(planner.actions),size):
            remaining=[w for w in worlds if all(w[f]==planner.nominal[f] for f in subset)]
            if remaining and all((w['f0'] in targets)==goal for w in remaining):
                rect=union_box(planner.actions[f] for f in subset)
                choices.append(dict(fields=subset,rect=rect,pixels=pixels(rect,1)))
    return min(choices,key=lambda c:(c['pixels'],c['fields'])) if choices else None


def subset_matching_control(planner,targets):
    # Stronger ordinary control: enumerate action subsets, use matching directly,
    # and never enumerate worlds. Do not attribute world-enumeration savings to
    # geometric planning when this equally scoped alternative has the same benefit.
    choices=[];tested=0
    for size in range(1,len(planner.actions)+1):
        for subset in combinations(sorted(planner.actions),size):
            tested+=1
            if planner.conditional_agreement('f0',targets,subset):
                rect=union_box(planner.actions[f] for f in subset)
                choices.append(dict(fields=subset,rect=rect,pixels=pixels(rect,1)))
    best=min(choices,key=lambda c:(c['pixels'],c['fields'])) if choices else None
    return dict(best=best,tested_action_sets=tested)


def run():
    fields={f'f{i}':(0,i*20,10,i*20+10) for i in range(3)}
    values={f'v{i}':(20,i*20,30,i*20+10) for i in range(3)}
    evidence=AssignmentEvidence({'f0':{'v0','v1','v2'},'f1':{'v0','v1'},'f2':{'v0','v2'}},
                                fields,values,revision='synthetic-layout-r11')
    actions={'f0':(0,0,100,100),'f1':(110,10,120,20),'f2':(125,10,135,20)}
    planner=QueryRegion(evidence,{'f0':'v0','f1':'v1','f2':'v2'},actions)
    rows=[]
    for name,targets in [('single_matching_value',{'v0'}),('two_predicate_equivalent_values',{'v0','v1'})]:
        plan=planner.plan('f0',targets);control=exhaustive_control(planner,targets)
        stronger=subset_matching_control(planner,targets)
        assert plan['pixels']==control['pixels']==stronger['best']['pixels']
        rows.append(dict(case=name,targets=sorted(targets),plan=plan,exhaustive_control=control,
            subset_matching_control=stronger,
            actual_nominal_observations=planner.observe(plan,plan['expected'],revision=evidence.revision)))
    first=rows[0]['plan']
    report=dict(date='2026-10-21',cases=rows,
        one_peer_observation_status=planner.after('f0',{'v0'},{'f1':'v1'})['status'],
        differing_observation=planner.observe(first,{'f1':'v0','f2':'v2'},revision=evidence.revision),
        conflicting_observation=planner.observe(first,{'f1':'v0','f2':'v0'},revision=evidence.revision),
        budget_249=planner.plan('f0',{'v0'},pixel_budget=249),
        direct_query_action_pixels=pixels(actions['f0'],1),
        limits=['Complete supports and one-to-one domains are supplied, not extracted or proven',
                'Conditional minimum for nominal observations, not an optimal adaptive policy',
                'Coordinate estimates, zero OCR/model calls, no measured phone benefit',
                'Conventional exhaustive subset/world control attains the same optimum',
                'At most eight supplied actions; no production changes or novelty finding'])
    root=Path(__file__).resolve().parents[2]
    (root/'results/patent-r11-query-region.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2))


if __name__=='__main__':run()
