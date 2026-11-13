from itertools import permutations,combinations
from types import SimpleNamespace
import random

import pytest

from research.patent_candidate.assignment_evidence import AssignmentEvidence
from research.patent_candidate.query_region import QueryRegion,union_box,pixels
from research.patent_candidate import robust_region as robust


def problem(n=3):
    domains={f'f{i}':{f'v{j}' for j in range(n)} for i in range(n)}
    boxes={f'f{i}':(i*10,0,i*10+5,5) for i in range(n)}
    values={f'v{i}':(i*10,10,i*10+5,15) for i in range(n)}
    evidence=AssignmentEvidence(domains,boxes,values,revision='r14-source')
    nominal={f'f{i}':f'v{i}' for i in range(n)}
    nominal['f0'],nominal['f1']='v1','v0'
    actions={'f0':(0,0,100,100),'f1':(110,10,120,20),'f2':(125,10,135,20)}
    return QueryRegion(evidence,nominal,actions)


def worlds(evidence):
    fields=sorted(evidence.domains)
    return [dict(zip(fields,p)) for p in permutations(evidence.value_boxes)
            if all(v in evidence.domains[f] for f,v in zip(fields,p))]


def determines(possible,observed,targets):
    groups={}
    for w in possible:groups.setdefault(tuple(w[f] for f in observed),set()).add(w['f0'] in targets)
    return bool(groups) and all(len(g)==1 for g in groups.values())


@pytest.mark.parametrize('seed',range(12))
def test_paired_milp_equals_independent_world_partition_oracle(seed):
    rng=random.Random(seed);planner=problem();evidence=planner.evidence
    for i in range(3):
        evidence.domains[f'f{i}']={f'v{i}'}|{f'v{j}' for j in range(3) if rng.random()<.6}
    # The mutated domains need not contain the initial nominal matching; this
    # test invokes only the nominal-independent paired-world oracle.
    possible=worlds(evidence);targets={v for v in evidence.value_boxes if rng.random()<.5}
    observed=[f for f in evidence.domains if rng.random()<.5]
    answer=robust.opposite_pair(evidence,'f0',targets,observed)
    assert (answer['status']=='determines_in_model')==determines(possible,observed,targets)
    if answer['status']=='opposite_pair':
        assert answer['yes'] in possible and answer['no'] in possible
        assert all(answer['yes'][f]==answer['no'][f] for f in observed)


def test_conditional_plan_can_leave_an_unexpected_observation_ambiguous():
    planner=problem();conditional=planner.plan('f0',{'v0'})
    assert conditional['fields']==('f1',) and conditional['pixels']==100
    assert planner.observe(conditional,{'f1':'v1'},revision='r14-source')['status']=='ambiguous'
    plan=robust.plan_region(planner,'f0',{'v0'})
    assert plan['fields']==('f1','f2') and plan['pixels']==250 and plan['minimum_established']
    for w in worlds(planner.evidence):
        observations={f:w[f] for f in plan['fields']}
        assert robust.observe_plan(planner,plan,observations,revision='r14-source')['status'] in ('candidate_match','candidate_nonmatch')


def test_standard_subset_partition_control_reaches_same_minimum():
    planner=problem();possible=worlds(planner.evidence);costs=[]
    for size in range(1,4):
        for subset in combinations(planner.actions,size):
            if determines(possible,subset,{'v0'}):costs.append(pixels(union_box(planner.actions[f] for f in subset),1))
    assert min(costs)==robust.plan_region(planner,'f0',{'v0'})['pixels']


def test_solver_unknown_and_call_limit_never_become_sufficiency(monkeypatch):
    planner=problem()
    monkeypatch.setattr(robust,'milp',lambda *a,**k:SimpleNamespace(status=1,x=None))
    assert robust.opposite_pair(planner.evidence,'f0',{'v0'},['f1'])['status']=='unknown_solver'
    assert robust.plan_region(planner,'f0',{'v0'})['status']=='search_incomplete'
    assert robust.plan_region(planner,'f0',{'v0'},max_solver_calls=1)['status']=='search_incomplete'


def test_conflict_stale_partial_and_hard_pixel_allowance():
    planner=problem()
    assert robust.plan_region(planner,'f0',{'v0'},pixel_budget=249)['status']=='no_admitted_plan'
    plan=robust.plan_region(planner,'f0',{'v0'})
    with pytest.raises(ValueError,match='Incomplete'):robust.observe_plan(planner,plan,{'f1':'v0'},revision='r14-source')
    with pytest.raises(ValueError,match='Stale'):robust.observe_plan(planner,plan,{'f1':'v0','f2':'v2'},revision='old')
    assert robust.observe_plan(planner,plan,{'f1':'v0','f2':'v0'},revision='r14-source')['status']=='conflicting_evidence'
    planner.evidence.conflict=True
    assert robust.opposite_pair(planner.evidence,'f0',{'v0'},['f1'])['status']=='conflicting_evidence'


@pytest.mark.parametrize('count,expected',[(10,'opposite_pair'),(11,'determines_in_model')])
def test_twelve_field_control_without_materializing_worlds(count,expected):
    planner=problem(12)
    result=robust.opposite_pair(planner.evidence,'f0',{'v0'},[f'f{i}' for i in range(1,count+1)])
    assert result['status']==expected and result['variables']==288


@pytest.mark.parametrize('seed',range(4))
def test_robust_minimum_against_world_subset_control_on_varied_layouts(seed):
    rng=random.Random(seed);planner=problem()
    planner.actions={f:(x:=rng.randrange(0,25),y:=rng.randrange(0,25),x+5,y+5) for f in planner.actions}
    for f in planner.evidence.domains:
        planner.evidence.domains[f]={planner.nominal[f]}|{v for v in planner.evidence.value_boxes if rng.random()<.7}
    possible=worlds(planner.evidence);outcomes={w['f0']=='v0' for w in possible}
    plan=robust.plan_region(planner,'f0',{'v0'})
    if len(outcomes)==1:
        assert plan['status']=='no_observation_plan';return
    costs=[]
    for size in range(1,4):
        for subset in combinations(planner.actions,size):
            if determines(possible,subset,{'v0'}):costs.append(pixels(union_box(planner.actions[f] for f in subset),1))
    assert plan['pixels']==min(costs) and plan['minimum_established']
