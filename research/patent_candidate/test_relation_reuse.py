from dataclasses import replace

import pytest
import pymupdf

from research.patent_candidate.measure_relation_reuse import fixture, CASES
from research.patent_candidate.relation_reuse import (
    extract_snapshot, sql_answer, cached_answer, positive_rows_reusable, partition_reusable,
)
from research.patent_candidate.relation_support import crop_hash, NODE_CROP


@pytest.mark.parametrize('case', CASES)
def test_pdf_mutations_against_fresh_sql(tmp_path, case):
    old_path, new_path = tmp_path/'old.pdf', tmp_path/'new.pdf'
    fixture(old_path,case,before=True); fixture(new_path,case)
    old,new = extract_snapshot(old_path),extract_snapshot(new_path)
    answer,reused = cached_answer(old,new,'total',partition_reusable)
    assert answer == sql_answer(new,'total')
    assert reused == (case in ('unchanged','unrelated_text','unrelated_subtotal_link'))
    weak,_ = cached_answer(old,new,'total',positive_rows_reusable)
    assert (weak != answer) == (case in ('insert_competing_total','insert_first_total'))


def test_profile_change_forces_recompute(tmp_path):
    path=tmp_path/'source.pdf'; fixture(path,'unchanged')
    old=extract_snapshot(path); new=extract_snapshot(path,recipe='changed-recipe')
    assert old.revision == new.revision
    assert not partition_reusable(old,new,'total')
    assert not positive_rows_reusable(old,new,'total')


def test_empty_result_is_not_source_absence(tmp_path):
    path=tmp_path/'source.pdf'; fixture(path,'insert_first_total',before=True)
    snap=extract_snapshot(path)
    assert sql_answer(snap,'total') == ('unresolved',())


def test_duplicate_relations_do_not_create_different_value_ambiguity(tmp_path):
    path=tmp_path/'source.pdf'; fixture(path,'unchanged')
    snap=extract_snapshot(path)
    total=next(r for r in snap.rows if r[1]=='total')
    duplicate=(total[0]+'different-path',total[1],total[2])
    assert sql_answer(replace(snap,rows=snap.rows+(duplicate,)),'total') == ('candidate',('13600',))


def test_same_node_pixels_do_not_authorize_answer_reuse(tmp_path):
    old_path,new_path=tmp_path/'old.pdf',tmp_path/'new.pdf'
    fixture(old_path,'reroute_both',before=True); fixture(new_path,'reroute_both')
    with pymupdf.open(old_path) as old_doc, pymupdf.open(new_path) as new_doc:
        assert crop_hash(old_doc[0],NODE_CROP) == crop_hash(new_doc[0],NODE_CROP)
    old,new=extract_snapshot(old_path),extract_snapshot(new_path)
    assert sql_answer(old,'total') != sql_answer(new,'total')
    assert not partition_reusable(old,new,'total')
