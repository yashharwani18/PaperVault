import math
import random

import pymupdf
import pytest

from research.patent_candidate.raster_cost import raster_cost
from research.patent_candidate.assignment_evidence import AssignmentEvidence
from research.patent_candidate.query_region import QueryRegion
from research.patent_candidate.query_crop import Cell,Reading,CropQuery
from research.patent_candidate.relation_support import make_connector_pdf,vector_relations,closure_plan


@pytest.mark.parametrize('seed',range(24))
def test_grid_cost_equals_actual_renderer_for_fractional_scaled_clips(seed):
    rng=random.Random(seed)
    x,y=rng.uniform(-10,140),rng.uniform(-10,140)
    rect=(x,y,x+rng.uniform(1,70),y+rng.uniform(1,70));scale=rng.choice((.5,1,1.25,200/72,3))
    with pymupdf.open() as doc:
        page=doc.new_page(width=200,height=200)
        cost=raster_cost(rect,scale,page_rect=page.rect)
        pix=page.get_pixmap(matrix=pymupdf.Matrix(scale,scale),clip=pymupdf.Rect(rect),alpha=False)
        assert (cost['width'],cost['height']) == (pix.width,pix.height)
        assert cost['pixels']==pix.width*pix.height


def fractional_evidence():
    return AssignmentEvidence({'f0':{'v0','v1'},'f1':{'v0','v1'}},
        {'f0':(.4,.4,4.4,4.4),'f1':(.4,6.4,4.4,10.4)},
        {'v0':(6.4,.4,10.4,4.4),'v1':(6.4,6.4,10.4,10.4)},revision='fractional-source')


def test_fractional_origin_exposes_old_undercharge_and_blocks_assignment_plan():
    evidence=fractional_evidence()
    assert math.ceil(10)*math.ceil(10)==100
    assert evidence.plan('f0',{'v0'},scale=1,pixel_budget=100) is None
    assert evidence.plan('f0',{'v0'},scale=1,pixel_budget=121)['pixels']==121


def test_conditional_region_plan_uses_grid_cost_before_admission():
    planner=QueryRegion(fractional_evidence(),{'f0':'v0','f1':'v1'}, {'f0':(.4,.4,10.4,10.4)})
    assert planner.plan('f0',{'v0'},pixel_budget=100)['status']=='no_admitted_plan'
    assert planner.plan('f0',{'v0'},pixel_budget=121)['pixels']==121


def test_explicit_hypothesis_crop_uses_grid_cost():
    cells=[Cell('label',(.4,.4,4.4,10.4)),Cell('amount',(6.4,.4,10.4,10.4))]
    readings=[Reading('a',(('label','total'),('amount','29000')),'label','amount'),
              Reading('b',(('label','total'),('amount','29074')),'label','amount')]
    q=CropQuery(cells,readings,'total','29000',revision='fractional-source')
    assert q.plan(scale=1,pixel_budget=100) is None
    assert q.plan(scale=1,pixel_budget=121)['pixels']==121
    assert q.plan(scale=1e-6) is None  # No zero-cost observation or division by zero.


def test_connector_support_cost_matches_actual_render(tmp_path):
    path=tmp_path/'connectors.pdf';make_connector_pdf(path)
    with pymupdf.open(path) as doc:
        page=doc[0];plan=closure_plan(page,vector_relations(page))
        pix=page.get_pixmap(clip=pymupdf.Rect(plan['support_crop']))
        assert plan['estimated_pixels']==pix.width*pix.height


def test_grid_collapse_is_not_available_source_support(tmp_path):
    path=tmp_path/'connectors.pdf';make_connector_pdf(path)
    with pymupdf.open(path) as doc:
        plan=closure_plan(doc[0],vector_relations(doc[0]),scale=1e-9)
        assert not plan['admitted'] and plan['outcome']=='unknown_empty_raster'


@pytest.mark.parametrize('rotation',[0,90,180,270])
def test_page_coordinate_clip_with_rotated_page(rotation):
    with pymupdf.open() as doc:
        page=doc.new_page(width=200,height=100);page.set_rotation(rotation)
        rect=(-3.4,.4,30.4,110.4);scale=1.25
        cost=raster_cost(rect,scale,page_rect=page.rect)
        pix=page.get_pixmap(matrix=pymupdf.Matrix(scale,scale),clip=pymupdf.Rect(rect))
        assert (cost['width'],cost['height'])==(pix.width,pix.height)


@pytest.mark.parametrize('scale',[0,-1,float('nan'),float('inf')])
def test_invalid_scale(scale):
    with pytest.raises(ValueError):raster_cost((0,0,10,10),scale)
