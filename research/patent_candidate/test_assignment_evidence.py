from itertools import permutations
import random

import pytest

from research.patent_candidate.assignment_evidence import AssignmentEvidence


def evidence(domains):
    n=len(domains)
    fields={f:(0,i*20,20,i*20+10) for i,f in enumerate(sorted(domains))}
    values={f'v{i}':(40,i*20,60,i*20+10) for i in range(n)}
    return AssignmentEvidence(domains,fields,values,revision='fixture-r1')


def worlds(domains):
    fields=sorted(domains)
    return [dict(zip(fields,p)) for p in permutations([f'v{i}' for i in range(len(fields))])
            if all(v in domains[f] for f,v in zip(fields,p))]


@pytest.mark.parametrize('seed',range(24))
def test_symbolic_decision_and_cycle_witness_equal_exhaustive_oracle(seed):
    rng=random.Random(seed);n=rng.randrange(2,7)
    domains={f'f{i}':{f'v{j}' for j in range(n) if rng.random()<.55} for i in range(n)}
    q=evidence(domains);target={f'v{j}' for j in range(n) if rng.random()<.5}
    possible=worlds(domains)
    outcomes={w['f0'] in target for w in possible}
    expected='conflicting_evidence' if not outcomes else 'ambiguous' if len(outcomes)==2 else 'candidate_match' if True in outcomes else 'candidate_nonmatch'
    assert q.decide('f0',target)['status']==expected
    plan=q.plan('f0',target)
    if expected!='ambiguous':assert plan is None;return
    assert plan['yes']['f0'] in target and plan['no']['f0'] not in target
    for witness in ('yes','no'):
        assert plan[witness] in possible
    assert all(plan['yes'][f]==plan['no'][f] for f in domains if f not in plan['fields'])


def test_32_fields_implicitly_cover_65536_independent_assignments():
    # Sixteen independent swaps. No 65,536-world list is constructed.
    domains={f'f{i}':{f'v{i-i%2}',f'v{i-i%2+1}'} for i in range(32)}
    q=evidence(domains)
    assert q.decide('f0',{'v0'})['status']=='ambiguous'
    plan=q.plan('f0',{'v0'})
    assert set(plan['fields'])=={'f0','f1'} and set(plan['values'])=={'v0','v1'}
    q.observe_relations(plan,{'f0':{'v0'},'f1':{'v1'}},revision='fixture-r1')
    assert q.decide('f0',{'v0'})['status']=='candidate_match'
    assert q.decide('f2',{'v2'})['status']=='ambiguous'


def test_equal_numeric_values_may_make_query_certain_despite_partner_ambiguity():
    q=evidence({'f0':{'v0','v1'},'f1':{'v0','v1'}})
    # The caller mapped BOTH distinct physical value nodes to the queried number.
    assert q.decide('f0',{'v0','v1'})['status']=='candidate_match'
    assert q.plan('f0',{'v0','v1'}) is None


def test_empty_target_and_infeasible_graph_do_not_conflate_nonmatch_with_conflict():
    q=evidence({'f0':{'v0'},'f1':{'v1'}})
    assert q.decide('f0',set())['status']=='candidate_nonmatch'
    q=evidence({'f0':{'v0'},'f1':{'v0'}})
    assert q.decide('f0',set())['status']=='conflicting_evidence'


def test_text_rereading_alone_cannot_disambiguate_relations():
    q=evidence({'f0':{'v0','v1'},'f1':{'v0','v1'}});plan=q.plan('f0',{'v0'})
    before=q.fingerprint()
    with pytest.raises(ValueError,match='value anchors'):
        q.observe_relations(plan,{'f0':{'total'},'f1':{'subtotal'}},revision='fixture-r1')
    assert q.fingerprint()==before and q.decide('f0',{'v0'})['status']=='ambiguous'


def test_contradictory_relation_evidence_is_not_vacuously_certain():
    q=evidence({'f0':{'v0','v1'},'f1':{'v0','v1'}});plan=q.plan('f0',{'v0'})
    assert q.observe_relations(plan,{'f0':{'v0'},'f1':{'v0'}},revision='fixture-r1')=='conflicting_evidence'
    assert q.decide('f0',{'v0'})['status']=='conflicting_evidence'


def test_stale_partial_and_over_budget_observations():
    q=evidence({'f0':{'v0','v1'},'f1':{'v0','v1'}});plan=q.plan('f0',{'v0'})
    with pytest.raises(ValueError,match='Stale'):q.observe_relations(plan,{'f0':{'v0'},'f1':{'v1'}},revision='different')
    with pytest.raises(ValueError,match='Incomplete'):q.observe_relations(plan,{'f0':{'v0'}},revision='fixture-r1')
    assert q.plan('f0',{'v0'},pixel_budget=1) is None
    assert q.decide('f0',{'v0'})['status']=='ambiguous'
    q.observe_relations(plan,{'f0':{'v0'},'f1':{'v1'}},revision='fixture-r1')
    with pytest.raises(ValueError,match='Stale'):q.observe_relations(plan,{'f0':{'v0'},'f1':{'v1'}},revision='fixture-r1')


def test_missing_true_relation_makes_graph_certainty_weaker_than_source_truth():
    q=evidence({'f0':{'v0'},'f1':{'v1'}})
    result=q.decide('f0',{'v0'})
    assert result['status']=='candidate_match'
    assert result['scope']=='Only assignments admitted by the supplied graph'
    # A source reading f0->v1 is excluded upstream. This solver cannot know it.
    assert 'v1' not in q.domains['f0']


def test_measured_enumeration_control_shares_ids_and_covers_pair_worlds():
    from research.patent_candidate.measure_assignment import explicit_independent_swaps
    fields=[f'f{i}' for i in range(4)];values=[f'v{i}' for i in range(4)]
    domains={fields[i]:{values[i-i%2],values[i-i%2+1]} for i in range(4)}
    explicit=explicit_independent_swaps(4,fields,values)
    assert len(explicit)==4
    assert all(w in worlds(domains) for w in explicit)
    assert len({tuple(w.items()) for w in explicit})==4
    assert next(iter(explicit[0])) is fields[0]
