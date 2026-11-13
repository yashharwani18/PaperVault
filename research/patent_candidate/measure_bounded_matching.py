"""R15 synthetic ordinary matching controls; not a device benchmark."""
import json
from pathlib import Path

from research.patent_candidate.assignment_evidence import AssignmentEvidence
from research.patent_candidate.bounded_matching import opposite_pair
from research.patent_candidate.robust_region import opposite_pair as milp_pair, plan_region
from research.patent_candidate.measure_robust_region import instance as region_instance


def evidence(domains):
    n=len(domains)
    return AssignmentEvidence(domains,
        {f:(0,i*10,5,i*10+5) for i,f in enumerate(domains)},
        {f'v{i}':(10,i*10,15,i*10+5) for i in range(n)},revision='r15-synthetic')


def validate_pair(model,result,observed):
    if result['status']!='opposite_pair':return
    for key in ('yes','no'):
        world=result[key]
        assert set(world)==set(model.domains)
        assert len(set(world.values()))==len(world)
        assert all(v in model.domains[f] for f,v in world.items())
    assert result['yes']['f0']=='v0' and result['no']['f0']!='v0'
    assert all(result['yes'][f]==result['no'][f] for f in observed)


def run():
    rows=[]
    complete=evidence({f'f{i}':{f'v{j}' for j in range(12)} for i in range(12)})
    for count in (10,11):
        observed=[f'f{i}' for i in range(1,count+1)]
        answer=opposite_pair(complete,'f0',{'v0'},observed)
        reference=milp_pair(complete,'f0',{'v0'},observed)
        structural='opposite_pair' if count==10 else 'determines_in_model'
        assert answer['status']==reference['status']==structural
        validate_pair(complete,answer,observed)
        rows.append(dict(case=f'complete_12_observed_{count}',bounded=answer,
                         milp=reference,ordinary_structural_control=structural))
    pairs=evidence({f'f{i}':{f'v{i-i%2}',f'v{i-i%2+1}'} for i in range(32)})
    outside=[f'f{i}' for i in range(2,32)]
    for peer in (False,True):
        observed=outside+(['f1'] if peer else [])
        answer=opposite_pair(pairs,'f0',{'v0'},observed)
        structural='determines_in_model' if peer else 'opposite_pair'
        assert answer['status']==structural
        validate_pair(pairs,answer,observed)
        rows.append(dict(case=f'independent_32_peer_observed_{peer}',bounded=answer,
            milp=None,milp_reason='Outside the R14 sixteen-field research cap',
            ordinary_two_field_component_control=structural))
    for n in (4,5,6):
        model=evidence({f'f{i}':{f'v{(i+j)%n}' for j in range(3)} for i in range(n)})
        observed=['f1','f2']
        answer=opposite_pair(model,'f0',{'v0'},observed)
        reference=milp_pair(model,'f0',{'v0'},observed)
        limited=opposite_pair(model,'f0',{'v0'},observed,max_states=1)
        assert answer['status']==reference['status']=='opposite_pair'
        assert limited['status']=='unknown_work_limit'
        validate_pair(model,answer,observed)
        rows.append(dict(case=f'cyclic_{n}',bounded=answer,milp=reference,one_state_limit=limited))
    planner=region_instance(3)
    plans=dict(milp=plan_region(planner,'f0',{'v0'}),
               bounded=plan_region(planner,'f0',{'v0'},oracle=opposite_pair))
    assert all(p['pixels']==250 and p['minimum_established'] for p in plans.values())
    report=dict(date='2026-10-21',data='synthetic only',cases=rows,region_plans=plans,
        limits=['Ordinary decomposition, structural shortcuts and bounded backtracking, not a new matching algorithm',
                'State count excludes matching work and is not a time or memory bound',
                'No OCR, Android execution, production change or patentability conclusion',
                'Exact conclusions concern complete supplied domains and exact observations only'])
    root=Path(__file__).resolve().parents[2]
    (root/'results/patent-r15-bounded-matching.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(dict(cases=[dict(case=r['case'],status=r['bounded']['status'],
        method=r['bounded']['method'],states=r['bounded']['states']) for r in rows],
        plan_pixels={k:v['pixels'] for k,v in plans.items()}),indent=2))


if __name__=='__main__':run()
