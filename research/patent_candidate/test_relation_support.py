import pymupdf
import pytest

from research.patent_candidate.relation_support import (
    make_connector_pdf,vector_relations,closure_plan,crop_hash,NODE_CROP,
)


def test_identical_node_crop_cannot_determine_opposite_full_page_relations(tmp_path):
    hashes=[];mappings=[];texts=[]
    for swapped in (False,True):
        path=tmp_path/f'connector-{swapped}.pdf';make_connector_pdf(path,swapped)
        with pymupdf.open(path) as doc:
            page=doc[0]
            hashes.append(crop_hash(page,NODE_CROP))
            texts.append(page.get_text('text'))
            mappings.append({r['field']:r['value'] for r in vector_relations(page)})
    assert hashes[0]==hashes[1] and texts[0]==texts[1]
    assert mappings==[{'total':'13600','subtotal':'13900'},{'total':'13900','subtotal':'13600'}]


@pytest.mark.parametrize('swapped',[False,True])
def test_ordinary_path_bbox_closure_recovers_visible_support(tmp_path,swapped):
    path=tmp_path/'fixture.pdf';make_connector_pdf(path,swapped)
    with pymupdf.open(path) as doc:
        page=doc[0];relations=vector_relations(page)
        plan=closure_plan(page,relations)
        assert len(relations)==2 and len(plan['connector_support_clipped'])==2
        assert plan['admitted']
        support=pymupdf.Rect(plan['support_crop'])
        assert all(pymupdf.Point(point) in support for r in relations for point in r['points'])


def test_expanding_crop_changes_hard_budget_decision(tmp_path):
    path=tmp_path/'fixture.pdf';make_connector_pdf(path,True)
    with pymupdf.open(path) as doc:
        page=doc[0];relations=vector_relations(page)
        # Node-only pixel cost is 32,400. Whole path support is much larger.
        plan=closure_plan(page,relations,pixel_budget=40_000)
        assert not plan['admitted'] and plan['outcome']=='unknown_budget_exhausted'
        assert plan['estimated_pixels']>40_000


def test_native_paths_already_supply_fixture_relationships_without_model(tmp_path):
    path=tmp_path/'fixture.pdf';make_connector_pdf(path,True)
    with pymupdf.open(path) as doc:
        relations=vector_relations(doc[0])
        # This direct conventional baseline is stronger than crop-only guessing.
        assert next(r['value'] for r in relations if r['field']=='total')=='13900'


def test_bad_allowance_rejected(tmp_path):
    path=tmp_path/'fixture.pdf';make_connector_pdf(path)
    with pymupdf.open(path) as doc:
        with pytest.raises(ValueError):closure_plan(doc[0],[],scale=0)
