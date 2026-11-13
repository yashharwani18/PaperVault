"""R15 ordinary decomposition, structural shortcuts and bounded backtracking.

No integer solver dependency. Exact on completed searches inside the supplied
matching model; work exhaustion remains unknown. No new algorithm, universal
polynomial bound, source-correctness or phone-performance claim.
"""
from research.patent_candidate.assignment_evidence import AssignmentEvidence,matching


def opposite_pair(evidence,field,targets,observed,*,max_states=256):
    targets=set(targets);observed=set(observed)
    if field not in evidence.domains or not targets.issubset(evidence.value_boxes) or not observed.issubset(evidence.domains):
        raise ValueError('Unknown query or observed field')
    if type(max_states) is not int or max_states<1:raise ValueError('Invalid branch-state limit')
    base=matching(evidence.domains)
    if evidence.conflict or base is None:return dict(status='conflicting_evidence')
    if field in observed:return dict(status='determines_in_model',method='query_observed',states=0)
    # Connected components are independent because every global perfect matching
    # restricts to a perfect matching in each component. No probabilistic assumption.
    fields={field};values=set()
    while True:
        new_values=set().union(*(evidence.domains[f] for f in fields))
        new_fields={f for f,d in evidence.domains.items() if d&new_values}
        if new_fields==fields and new_values==values:break
        fields,values=new_fields,new_values
    domains={f:set(evidence.domains[f]) for f in fields}
    fboxes={f:evidence.field_boxes[f] for f in fields};vboxes={v:evidence.value_boxes[v] for v in values}
    targets &= values;observed &= fields
    def probe(forced):
        reduced={f:({forced[f]} if f in forced else d) for f,d in domains.items()}
        return AssignmentEvidence(reduced,fboxes,vboxes,revision=evidence.revision).decide(field,targets)
    def pair(yes,no,method,states):
        outside={f:v for f,v in base.items() if f not in fields}
        return dict(status='opposite_pair',yes={**outside,**yes},no={**outside,**no},
                    method=method,states=states,component_fields=len(fields))
    initial=probe({})
    if initial['status']!='ambiguous':
        return dict(status='determines_in_model',method='predicate_agreement',states=0,component_fields=len(fields))
    if not observed:return pair(initial['yes'],initial['no'],'independent_component',0)
    if fields-{field} <= observed:
        return dict(status='determines_in_model',method='leftover_value',states=0,component_fields=len(fields))
    if all(d==values for d in domains.values()):
        peer=sorted(fields-observed-{field})[0]
        yes_value=sorted(targets)[0];no_value=sorted(values-targets)[0]
        common=dict(zip(sorted(fields-{field,peer}),sorted(values-{yes_value,no_value})))
        return pair({**common,field:yes_value,peer:no_value},
                    {**common,field:no_value,peer:yes_value},'complete_component_swap',0)
    states=0
    def search(forced):
        nonlocal states
        if states>=max_states:return dict(status='unknown_work_limit',states=states,method='branch_matching')
        states+=1;decision=probe(forced)
        if decision['status']!='ambiguous':return None
        remaining=observed-set(forced)
        if not remaining:return pair(decision['yes'],decision['no'],'branch_matching',states)
        used=set(forced.values())
        next_field=min(remaining,key=lambda f:(len(domains[f]-used),f))
        for value in sorted(domains[next_field]-used):
            result=search({**forced,next_field:value})
            if result is not None:return result
        return None
    result=search({})
    return result or dict(status='determines_in_model',method='exhausted_branch_matching',
                          states=states,component_fields=len(fields))
