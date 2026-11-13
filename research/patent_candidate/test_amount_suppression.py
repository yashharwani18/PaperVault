import pytest

from research.patent_candidate.amount_suppression import scenarios,evaluate


@pytest.mark.parametrize('case',scenarios(),ids=lambda c:c['name'])
def test_real_search_against_bounded_candidate_reference(case):
    result=evaluate(case)
    assert not result['reference']['missed']
    assert result['reference']['evidence_preserved'] and result['production']['evidence_preserved']
    failing=case['name'] in ('injected_ocr_error','injected_native_error','genuine_exact_and_nearby')
    assert bool(result['production']['missed']) == failing
    if case['name'].startswith('injected_'):
        # Retaining alternatives restores candidate recall, not correctness/precision.
        assert result['reference']['extra']==['apparent-exact']
        assert result['reference']['values']['apparent-exact']=='29000.00'
        assert result['reference']['values']['near']=='29074.00'
    else:
        assert not result['reference']['extra']
    if case['name']=='explicit_exact':
        assert result['production']['ids']==result['reference']['ids']==['exact']
