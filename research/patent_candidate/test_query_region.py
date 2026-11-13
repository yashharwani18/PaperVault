from itertools import combinations,permutations
import random

import pytest

from research.patent_candidate.assignment_evidence import AssignmentEvidence
from research.patent_candidate.query_region import QueryRegion,union_box,pixels


def problem(domains,actions):
    n=len(domains)
    fields={f:(i*10,0,i*10+5,5) for i,f in enumerate(domains)}
    values={f'v{i}':(i*10,10,i*10+5,15) for i in range(n)}
    evidence=AssignmentEvidence(domains,fields,values,revision='r11-source')
    return QueryRegion(evidence,{f'f{i}':f'v{i}' for i in range(n)},actions)


@pytest.mark.parametrize('seed',range(16))
def test_minimum_region_against_independent_world_and_action_subset_oracle(seed):
    rng=random.Random(seed);n=rng.randrange(2,6)
    domains={f'f{i}':{f'v{i}'}|{f'v{j}' for j in range(n) if rng.random()<.5} for i in range(n)}
    actions={f'f{i}':(x:=rng.randrange(0,15),y:=rng.randrange(0,15),x+rng.randrange(1,8),y+rng.randrange(1,8)) for i in range(n)}
    planner=problem(domains,actions);fields=list(domains)
    worlds=[dict(zip(fields,vs)) for vs in permutations(planner.evidence.value_boxes)
            if all(v in domains[f] for f,v in zip(fields,vs))]
    possible={w['f0']=='v0' for w in worlds}
    plan=planner.plan('f0',{'v0'})
    if len(possible)==1:
        assert plan['status']=='no_observation_plan';return
    costs=[]
    for k in range(1,n+1):
        for chosen in combinations(fields,k):
            remaining=[w for w in worlds if all(w[f]==planner.nominal[f] for f in chosen)]
            if remaining and all(w['f0']=='v0' for w in remaining):
                costs.append(pixels(union_box(actions[f] for f in chosen),1))
    assert plan['status']=='conditional_plan' and plan['pixels']==min(costs)
    assert planner.observe(plan,plan['expected'],revision='r11-source')['status']=='candidate_match'


def branching():
    return problem({'f0':{'v0','v1','v2'},'f1':{'v0','v1'},'f2':{'v0','v2'}},
                   {'f0':(0,0,100,100),'f1':(110,10,120,20),'f2':(125,10,135,20)})


def test_one_alternative_removed_does_not_certify_the_query():
    planner=branching()
    assert planner.after('f0',{'v0'},{'f1':'v1'})['status']=='ambiguous'
    plan=planner.plan('f0',{'v0'})
    assert set(plan['fields'])=={'f1','f2'} and plan['pixels']==250
    assert planner.observe(plan,{'f1':'v1','f2':'v2'},revision='r11-source')['status']=='candidate_match'


def test_disagreement_is_recomputed_not_treated_as_expected_confirmation():
    planner=branching();plan=planner.plan('f0',{'v0'})
    result=planner.observe(plan,{'f1':'v0','f2':'v2'},revision='r11-source')
    assert result['status']=='candidate_nonmatch' and not result['nominal_agreement']
    assert planner.observe(plan,{'f1':'v0','f2':'v0'},revision='r11-source')['status']=='conflicting_evidence'


def test_partial_stale_geometry_and_budget_checks():
    planner=branching();plan=planner.plan('f0',{'v0'})
    assert planner.plan('f0',{'v0'},pixel_budget=249)['status']=='no_admitted_plan'
    with pytest.raises(ValueError,match='Incomplete'):planner.observe(plan,{'f1':'v1'},revision='r11-source')
    with pytest.raises(ValueError,match='Stale'):planner.observe(plan,plan['expected'],revision='old')
    planner.actions['f1']=(111,10,120,20)
    with pytest.raises(ValueError,match='Stale'):planner.observe(plan,plan['expected'],revision='r11-source')


def test_nominal_and_action_validation():
    planner=branching()
    with pytest.raises(ValueError,match='perfect matching'):
        QueryRegion(planner.evidence,{'f0':'v0','f1':'v0','f2':'v2'},planner.actions)
    with pytest.raises(ValueError,match='Invalid action'):problem({'f0':{'v0'}},{'f0':(1,0,0,1)})


def test_distinct_values_with_same_predicate_need_not_be_disambiguated():
    planner=branching()
    plan=planner.plan('f0',{'v0','v1'})
    assert plan['fields']==('f2',) and plan['pixels']==100
    assert planner.observe(plan,{'f2':'v2'},revision='r11-source')['status']=='candidate_match'


def test_available_observations_may_never_determine_the_predicate():
    planner=branching();planner.actions={'f1':planner.actions['f1']}
    assert planner.plan('f0',{'v0'})['status']=='no_admitted_plan'
    assert planner.after('f0',{'v0'},{'f1':'v1'})['status']=='ambiguous'
