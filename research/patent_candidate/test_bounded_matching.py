from itertools import permutations
import random

import pytest

from research.patent_candidate.assignment_evidence import AssignmentEvidence
from research.patent_candidate.bounded_matching import opposite_pair
from research.patent_candidate.robust_region import opposite_pair as milp_pair,plan_region
from research.patent_candidate.query_region import QueryRegion


def instance(domains):
    n=len(domains)
    return AssignmentEvidence(domains,{f:(0,i*10,5,i*10+5) for i,f in enumerate(domains)},
        {f'v{i}':(10,i*10,15,i*10+5) for i in range(n)},revision='r15-source')


@pytest.mark.parametrize('seed',range(24))
def test_bounded_matching_against_world_partition_and_milp(seed):
    rng=random.Random(seed);n=rng.randrange(3,6)
    domains={f'f{i}':{f'v{i}'}|{f'v{j}' for j in range(n) if rng.random()<.5} for i in range(n)}
    evidence=instance(domains);fields=sorted(domains)
    possible=[dict(zip(fields,p)) for p in permutations(evidence.value_boxes)
              if all(v in domains[f] for f,v in zip(fields,p))]
    observed=sorted(f for f in fields if rng.random()<.5)
    targets={v for v in evidence.value_boxes if rng.random()<.5}
    groups={}
    for w in possible:groups.setdefault(tuple(w[f] for f in observed),set()).add(w['f0'] in targets)
    expected='opposite_pair' if any(len(g)==2 for g in groups.values()) else 'determines_in_model'
    result=opposite_pair(evidence,'f0',targets,observed,max_states=1000)
    assert result['status']==expected==milp_pair(evidence,'f0',targets,observed)['status']
    if expected=='opposite_pair':
        assert result['yes'] in possible and result['no'] in possible
        assert all(result['yes'][f]==result['no'][f] for f in observed)
        assert result['yes']['f0'] in targets and result['no']['f0'] not in targets


def test_independent_components_and_structural_leftover_shortcuts():
    evidence=instance({f'f{i}':{f'v{i-i%2}',f'v{i-i%2+1}'} for i in range(32)})
    outside=[f'f{i}' for i in range(2,32)]
    result=opposite_pair(evidence,'f0',{'v0'},outside)
    assert result['status']=='opposite_pair' and result['component_fields']==2 and result['states']==0
    assert opposite_pair(evidence,'f0',{'v0'},outside+['f1'])['status']=='determines_in_model'


def test_complete_component_swap_with_shared_observations():
    evidence=instance({f'f{i}':{f'v{j}' for j in range(12)} for i in range(12)})
    observed=[f'f{i}' for i in range(1,11)]
    result=opposite_pair(evidence,'f0',{'v0'},observed)
    assert result['method']=='complete_component_swap' and result['states']==0
    assert all(result['yes'][f]==result['no'][f] for f in observed)
    assert opposite_pair(evidence,'f0',{'v0'},observed+['f11'])['method']=='leftover_value'


def test_branch_exhaustion_remains_unknown_and_plan_does_not_certify(monkeypatch):
    evidence=instance({'f0':{'v0','v1','v2'},'f1':{'v0','v1'},'f2':{'v0','v2'}})
    assert opposite_pair(evidence,'f0',{'v0'},['f1'],max_states=1)['status']=='unknown_work_limit'
    planner=QueryRegion(evidence,{'f0':'v0','f1':'v1','f2':'v2'}, {'f1':(0,0,10,10)})
    oracle=lambda *args:opposite_pair(*args,max_states=1)
    assert plan_region(planner,'f0',{'v0'},oracle=oracle)['status']=='search_incomplete'


def test_conflicts_and_limits_are_explicit():
    evidence=instance({'f0':{'v0'},'f1':{'v0'}})
    assert opposite_pair(evidence,'f0',{'v0'},[])['status']=='conflicting_evidence'
    with pytest.raises(ValueError):opposite_pair(evidence,'f0',{'v0'},[],max_states=0)
