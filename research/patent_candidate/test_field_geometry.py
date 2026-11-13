from research.patent_candidate.field_geometry import relations,candidate_pairs,header_pairs
from research.patent_candidate.measure_field_reader import make_fixture,text_pairs
from research.patent_candidate.relation_support import crop_hash
import pymupdf
import pytest


@pytest.mark.parametrize('case',['row','values_first_stream','interleaved_stream','tax_next_row'])
def test_geometry_reassembles_supported_rows_independently_of_stream_order(tmp_path,case):
    path=tmp_path/'fixture.pdf';truth=make_fixture(path,case)
    with pymupdf.open(path) as doc:
        rows=relations(doc[0].get_text('words'))
        assert candidate_pairs(rows)==truth
        if case=='interleaved_stream':assert text_pairs(doc[0].get_text())!=truth


def test_header_context_can_make_nearest_amount_wrong(tmp_path):
    path=tmp_path/'fixture.pdf';truth=make_fixture(path,'header_disambiguation')
    with pymupdf.open(path) as doc:
        rows=relations(doc[0].get_text('words'))
    assert truth.issubset(candidate_pairs(rows))
    assert candidate_pairs(rows,nearest=True)=={('total','250.00')}
    assert rows[0]['state']=='ambiguous'


def test_side_by_side_candidates_are_not_claimed_as_verified_links(tmp_path):
    path=tmp_path/'fixture.pdf';make_fixture(path,'side_by_side')
    with pymupdf.open(path) as doc:rows=relations(doc[0].get_text('words'))
    assert sorted(len(r['candidates']) for r in rows)==[1,2]
    assert any(r['state']=='ambiguous' for r in rows)


def test_vertical_layout_remains_unresolved_for_row_only_control(tmp_path):
    path=tmp_path/'fixture.pdf';make_fixture(path,'vertical')
    with pymupdf.open(path) as doc:rows=relations(doc[0].get_text('words'))
    assert rows[0]['state']=='unresolved' and not candidate_pairs(rows)


@pytest.mark.parametrize('case',['header_disambiguation','header_swapped'])
def test_contextual_header_control_for_explicit_fixture_semantics(tmp_path,case):
    path=tmp_path/'fixture.pdf';truth=make_fixture(path,case)
    with pymupdf.open(path) as doc:
        words=doc[0].get_text('words');rows=relations(words)
        assert header_pairs(rows,words)==truth


def test_identical_field_value_row_can_have_opposite_header_defined_total(tmp_path):
    crops=[];truths=[]
    for case in ('header_disambiguation','header_swapped'):
        path=tmp_path/(case+'.pdf');truths.append(make_fixture(path,case))
        with pymupdf.open(path) as doc:crops.append(crop_hash(doc[0],(50,125,535,160)))
    assert crops[0]==crops[1] and truths[0]!=truths[1]
