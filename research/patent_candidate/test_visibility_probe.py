import pymupdf
import pytest

from research.patent_candidate.visibility_probe import inspect_occurrences


def fixture(kind):
    doc=pymupdf.open();page=doc.new_page(width=360,height=240)
    text='Total 13600.00'
    if kind=='sandwich':
        with pymupdf.open() as visual:
            p=visual.new_page(width=360,height=240);p.insert_text((40,70),text,fontsize=20)
            image=p.get_pixmap(matrix=pymupdf.Matrix(2,2)).tobytes('png')
        page.insert_image(page.rect,stream=image)
        page.insert_text((40,70),text,fontsize=20,render_mode=3)
    else:
        page.insert_text((40,70),text,fontsize=20,
            render_mode=3 if kind=='invisible' else 0,
            fill_opacity=0 if kind=='transparent' else 1,
            color=(1,1,1) if kind=='white' else (0,0,0))
        if kind in ('covered','transparent_overlay'):
            page.draw_rect(pymupdf.Rect(30,40,270,85),fill=(1,1,1),color=None,
                           fill_opacity=0 if kind=='transparent_overlay' else 1,overlay=True)
    if kind=='rotated':page.set_rotation(90)
    return doc


@pytest.mark.parametrize('kind,reason',[
    ('normal',None),('rotated',None),('invisible','not_painted_render_mode'),
    ('transparent','zero_opacity'),('covered','possible_later_paint_overlap'),
    ('sandwich','not_painted_render_mode'),
    ('transparent_overlay','possible_later_paint_overlap'),('white',None),
])
def test_triage_is_an_observation_not_a_visibility_verdict(kind,reason):
    with fixture(kind) as doc:
        hits=inspect_occurrences(doc[0],'13600.00')
        assert len(hits)==1
        if reason:assert reason in hits[0]['reasons']
        else:assert hits[0]['reasons']==[]
        assert 'establishes' in hits[0]['limitation']


def test_all_duplicate_numeric_occurrences_remain_distinct():
    with pymupdf.open() as doc:
        page=doc.new_page()
        page.insert_text((40,60),'Subtotal 13600.00')
        page.insert_text((40,100),'Total 13600.00',render_mode=3)
        hits=inspect_occurrences(page,'13600.00')
        assert len(hits)==2
        assert hits[0]['sequence']!=hits[1]['sequence']
        assert hits[0]['outcome']=='no_simple_visibility_flag'
        assert hits[1]['outcome']=='needs_visual_check'


def test_no_match_and_empty_input_are_not_false_confirmations():
    with fixture('normal') as doc:
        assert inspect_occurrences(doc[0],'99999')==[]
        with pytest.raises(ValueError):inspect_occurrences(doc[0],'')
