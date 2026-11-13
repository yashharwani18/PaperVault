"""R14 conditional/all-outcome distinction and equally scoped ordinary controls."""
from itertools import combinations,permutations
import json
import math
from pathlib import Path

import scipy

from research.patent_candidate.assignment_evidence import AssignmentEvidence
from research.patent_candidate.query_region import QueryRegion,union_box,pixels
from research.patent_candidate.robust_region import opposite_pair,plan_region,observe_plan


def instance(n):
    fields={f'f{i}':(i*10,0,i*10+5,5) for i in range(n)}
    values={f'v{i}':(i*10,10,i*10+5,15) for i in range(n)}
    evidence=AssignmentEvidence({f:set(values) for f in fields},fields,values,revision='r14-synthetic')
    nominal={f'f{i}':f'v{i}' for i in range(n)}
    nominal['f0'],nominal['f1']='v1','v0'
    actions={'f0':(0,0,100,100),'f1':(110,10,120,20),'f2':(125,10,135,20)}
    return QueryRegion(evidence,nominal,actions)


def exhaustive_control(planner):
    fields=sorted(planner.evidence.domains)
    worlds=[dict(zip(fields,p)) for p in permutations(planner.evidence.value_boxes)]
    candidates=[]
    for size in range(1,len(planner.actions)+1):
        for subset in combinations(planner.actions,size):
            groups={}
            for w in worlds:groups.setdefault(tuple(w[f] for f in subset),set()).add(w['f0']=='v0')
            if all(len(g)==1 for g in groups.values()):
                rect=union_box(planner.actions[f] for f in subset)
                candidates.append(dict(fields=subset,rect=rect,pixels=pixels(rect,1)))
    return min(candidates,key=lambda c:(c['pixels'],c['fields'])),worlds


def run():
    planner=instance(3);conditional=planner.plan('f0',{'v0'})
    robust=plan_region(planner,'f0',{'v0'});control,worlds=exhaustive_control(planner)
    assert robust['pixels']==control['pixels']==250
    assert conditional['pixels']==100
    unexpected={'f1':'v1'}
    conditional_actual=planner.observe(conditional,unexpected,revision=planner.evidence.revision)
    assert conditional_actual['status']=='ambiguous'
    outcomes=[]
    for w in worlds:
        actual={f:w[f] for f in robust['fields']}
        decision=observe_plan(planner,robust,actual,revision=planner.evidence.revision)['status']
        assert decision in ('candidate_match','candidate_nonmatch')
        outcomes.append(dict(world=w,observations=actual,decision=decision))
    larger=instance(12);large=[]
    for observed_count in (10,11):
        observed=[f'f{i}' for i in range(1,observed_count+1)]
        answer=opposite_pair(larger.evidence,'f0',{'v0'},observed)
        # Strong complete-graph control: with q unobserved and a proper nonempty
        # target set, observing all other fields determines the leftover value;
        # leaving a peer unobserved permits a query-changing swap.
        analytic='determines_in_model' if observed_count==11 else 'opposite_pair'
        assert answer['status']==analytic
        large.append(dict(observed_count=observed_count,oracle=answer,ordinary_structural_control=analytic))
    report=dict(date='2026-10-21',scipy=scipy.__version__,conditional_plan=conditional,
        conditional_unexpected_observation=conditional_actual,
        conditional_undistinguished_pair=opposite_pair(planner.evidence,'f0',{'v0'},['f1']),
        robust_plan=robust,exhaustive_control=control,all_six_world_observations=outcomes,
        twelve_field_fixed_set_checks=large,hypothetical_complete_graph_worlds=math.factorial(12),
        limits=['All guarantees restricted to complete supplied matching domains and exact observations',
                'Ordinary MILP feasibility encoding, not a new solver or formal infeasibility proof checker',
                'Timeout/unknown never establishes sufficiency; planner solver-call cap can leave search incomplete',
                'Generic subset/partition and simple structural controls share the demonstrated outcomes',
                'No OCR, source supports, physical crops, mobile runtime or memory measurement in R14',
                'No production changes or patentability finding'])
    root=Path(__file__).resolve().parents[2]
    (root/'results/patent-r14-robust-region.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(dict(conditional_pixels=conditional['pixels'],conditional_unexpected=conditional_actual['status'],
        robust_pixels=robust['pixels'],all_world_decisions=[o['decision'] for o in outcomes],
        large_checks=[dict(observed_count=r['observed_count'],status=r['oracle']['status']) for r in large]),indent=2))


if __name__=='__main__':run()
