"""R19 conventional digit-DP over supplied deterministic acyclic automata.

No OCR alternatives are extracted here. Counts describe paths/strings in the
supplied fixed-width model, not probabilities or correctness of source pixels.
"""
from functools import lru_cache
import json
from pathlib import Path
import random


def trie(strings):
    strings=sorted(set(strings))
    if not strings or len({len(s) for s in strings})!=1 or not all(s.isascii() and s.isdigit() for s in strings):
        raise ValueError('Supply nonempty equal-width ASCII digit strings')
    edges={0:{}};terminal=set()
    for string in strings:
        node=0
        for digit in string:
            if digit not in edges[node]:
                child=len(edges);edges[node][digit]=child;edges[child]={}
            node=edges[node][digit]
        terminal.add(node)
    return edges,terminal,len(strings[0])


def independent(domains):
    return ({i:{d:i+1 for d in sorted(set(domain))} for i,domain in enumerate(domains)}|
            {len(domains):{}},{len(domains)},len(domains))


def classify(model,low,high):
    edges,terminal,width=model
    if type(low) is not int or type(high) is not int or not 0<=low<=high:
        raise ValueError('Supply a nonnegative inclusive integer-cent interval')
    calls=0
    @lru_cache(None)
    def count(node):
        nonlocal calls
        calls+=1
        return (1 if node in terminal else 0)+sum(count(child) for child in edges[node].values())
    def at_most(bound):
        if bound<0:return 0
        if bound>=10**width:return count(0)
        digits=str(bound).zfill(width)
        @lru_cache(None)
        def visit(node,pos,tight):
            nonlocal calls
            calls+=1
            if pos==width:return int(node in terminal)
            limit=digits[pos] if tight else '9'
            return sum(visit(child,pos+1,tight and digit==limit)
                       for digit,child in edges[node].items() if digit<=limit)
        return visit(0,0,True)
    total=count(0);inside=at_most(high)-at_most(low-1)
    assert 0<=inside<=total
    status='conflicting_evidence' if not total else ('candidate_nonmatch' if not inside else
            'candidate_match' if inside==total else 'ambiguous')
    return dict(status=status,represented_strings=total,inside_strings=inside,memo_states_evaluated=calls)


def run():
    # Exhaustive independent controls on small correlated subsets.
    checks=[]
    for seed in range(24):
        rng=random.Random(seed)
        strings={str(rng.randrange(10000)).zfill(4) for _ in range(18)}
        low=rng.randrange(10000);high=rng.randrange(low,10000)
        result=classify(trie(strings),low,high)
        actual=sum(low<=int(s)<=high for s in strings)
        assert result['inside_strings']==actual and result['represented_strings']==len(strings)
        checks.append(dict(seed=seed,low=low,high=high,result=result))
    correlated=['2900000','3107400']
    exact=classify(trie(correlated),2907400,2907400)
    product_model=independent([set(chars) for chars in zip(*correlated)])
    flattened=classify(product_model,2907400,2907400)
    assert exact['status']=='candidate_nonmatch' and flattened['status']=='ambiguous'
    # All these supplied readings satisfy the user's approximate-amount example.
    nearby=classify(trie(['2901400','2907400']),2871000,2929000)
    assert nearby['status']=='candidate_match'
    uncertain=classify(trie(['2907400','2987400']),2871000,2929000)
    assert uncertain['status']=='ambiguous'
    # A min/max envelope retains safe ambiguity but cannot exclude holes.
    envelope=dict(minimum=min(map(int,correlated)),maximum=max(map(int,correlated)),
                  decision='ambiguous')
    assert envelope['minimum']<=2907400<=envelope['maximum']
    large=independent([{'0','1'} for _ in range(32)])
    stress=classify(large,0,10**32-1)
    assert stress['represented_strings']==2**32 and stress['status']=='candidate_match'
    # Strong ordinary interval control answers this stress case directly.
    structural=dict(minimum=0,maximum=int('1'*32),decision='candidate_match')
    report=dict(date='2026-10-21',small_exhaustive_checks=checks,
        correlated_strings=correlated,exact_lattice=exact,independent_digit_control=flattened,
        minmax_control=envelope,nearby_all=nearby,nearby_mixed=uncertain,
        stress=stress,stress_structural_control=structural,
        limits=['Known automata intersection/digit dynamic programming, not a novel algorithm',
                'Inputs are synthetic, fixed-width canonical integer cents, with field/currency already supplied',
                'Only constructors here supply well-formed acyclic automata; no general OCR lattice parser',
                'Unweighted support, not probabilities, confidence, source completeness or a best reading',
                'Stress amounts are artificial and not representative invoices or a mobile performance test',
                'No OCR engine alternative output, neural model call or production change'])
    root=Path(__file__).resolve().parents[2]
    (root/'results/patent-r19-digit-lattice.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(dict(exhaustive_checks=len(checks),correlated_exact=exact['status'],
        independent_digits=flattened['status'],nearby_all=nearby['status'],nearby_mixed=uncertain['status'],
        stress_strings=stress['represented_strings'],stress_memo_states=stress['memo_states_evaluated']),indent=2))


if __name__=='__main__':run()
