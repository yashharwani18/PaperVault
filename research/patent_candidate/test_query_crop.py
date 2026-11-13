import pytest
from research.patent_candidate.query_crop import Cell,Reading,CropQuery


def query():
    cells=[Cell('label',(10,10,70,30)),Cell('amount',(130,10,200,30)),
           Cell('note',(10,200,200,220))]
    readings=[Reading('match',(('label','subtotal'),('amount','13600'),('note','hello')),'label','amount'),
              Reading('wrong-field',(('label','total'),('amount','13600'),('note','hello')),'label','amount')]
    return CropQuery(cells,readings,'subtotal','13600',revision='source-1')


def test_same_digits_do_not_resolve_wrong_field():
    q=query()
    assert q.status()=='ambiguous'
    plan=q.plan()
    assert set(plan['cells'])=={'label','amount'}
    assert q.observe(plan,{'label':{'subtotal','total'},'amount':{'13600'}},revision='source-1')=='ambiguous'


@pytest.mark.parametrize('label,expected',[('subtotal','candidate_match'),('total','candidate_nonmatch')])
def test_joint_reading_resolves_query(label,expected):
    q=query();plan=q.plan()
    assert q.observe(plan,{'label':{label},'amount':{'13600'}},revision='source-1')==expected


def test_conflicting_ocr_does_not_create_false_nonmatch():
    q=query();plan=q.plan()
    assert q.observe(plan,{'label':{'subtotal'},'amount':{'13800'}},revision='source-1')=='conflicting_evidence'
    assert len(q.readings)==2


def test_budget_and_stale_source():
    q=query()
    assert q.plan(pixel_budget=1) is None
    with pytest.raises(ValueError,match='Stale'):
        q.observe(q.plan(),{'label':{'subtotal'},'amount':{'13600'}},revision='source-2')


def test_partial_crop_not_accepted_as_joint_verification():
    q=query()
    with pytest.raises(ValueError,match='Incomplete'):
        q.observe(q.plan(),{'amount':{'13600'}},revision='source-1')


@pytest.mark.parametrize('scale',[0,-1,float('nan')])
def test_invalid_raster_scale(scale):
    with pytest.raises(ValueError,match='raster budget'):
        query().plan(scale=scale)


def test_fixed_joint_crop_has_same_effect_in_simple_case():
    q=query()
    # A deliberately strong control: ordinary joint label/value cropping is
    # enough for this simple layout. Query planning is not needed to win here.
    fixed={'revision':'source-1','cells':('label','amount')}
    assert q.observe(fixed,{'label':{'subtotal'},'amount':{'13600'}},revision='source-1')=='candidate_match'


@pytest.mark.parametrize('truth',range(8))
def test_planner_preserves_enumerated_truth(truth):
    cells=[Cell('label',(10,10,80,25)),Cell('amount',(120,10,220,25)),Cell('other',(10,80,220,100))]
    readings=[]
    for i in range(8):
        values=(('label','subtotal' if i&1 else 'total'),('amount','13600' if i&2 else '13800'),
                ('other','foo' if i&4 else 'bar'))
        readings.append(Reading(str(i),values,'label','amount'))
    q=CropQuery(cells,readings,'subtotal','13600',revision='v1')
    plan=q.plan();chosen=readings[truth]
    q.observe(plan,{key:{chosen.values()[key]} for key in plan['cells']},revision='v1')
    assert any(r.id==chosen.id for r in q.readings)
    expected='candidate_match' if chosen.matches('subtotal','13600') else 'candidate_nonmatch'
    assert q.status()==expected
