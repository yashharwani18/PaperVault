import pytest
from knowledge_library.query_interpreter import candidate,validate,QueryInterpreter,simple_request,request_schema
from tests.test_desktop import session


def output(**overrides):
    return dict(action='search',field='total',amount='13600',party='',date='',direction='')|overrides


def test_invoice_gating_preserves_lecture_and_identifier_searches():
    assert candidate('hello mere bhai muje 13800 ka invoice dikha na')
    assert not candidate('Which bill contained A4 paper?')
    assert not candidate('Explain pumping lemma lecture 12')
    assert not candidate('Show invoice INV-13600')
    assert simple_request('13600 wala bill dikhao')['amount']['value']=='13600.00'
    assert simple_request('Bhagwanti Trading ka 13600 wala bill dikhao') is None
    assert request_schema('13600 ka invoice')['properties']['date']['enum']==['']
    assert request_schema('13600 ka invoice')['properties']['direction']['enum']==['']
    assert request_schema('13600 tax se pehle wala invoice')['properties']['field']['enum']==['subtotal']
    assert request_schema('13600 ka maal becha invoice 25 September 2026')['properties']['date']['enum']==['2026-09-25']


def test_source_literal_validation():
    amount,filters=validate('bhai 13,600 ka invoice dikha',output())
    assert amount['value']=='13600.00' and filters=={}
    assert validate('bhai 13600 ka invoice dikha',output(party='13600'))[1]=={}
    bad=[('bhai 13800 ka invoice dikha',output()),
         ('bhai 13600 ka invoice dikha',output(party='Invented Trading')),
         ('bhai subtotal 13600 dikha',output()),
         ('13600 ya 13800 ka bill dikha',output()),
         ('13600 se zyada ka bill dikha',output()),
         ('13600 ka maal becha invoice dikhao',output()),
         ('13600 ka bill 25 September 2026 ko bana',output())]
    for query,data in bad:
        with pytest.raises(ValueError):validate(query,data)
    amount,filters=validate('Bhagwanti Trading ko 25 September 2026 pe 13600 ka maal becha invoice dikhao',
        output(party='Bhagwanti Trading',date='2026-09-25',direction='sale'))
    assert filters==dict(party='Bhagwanti Trading',date_from='2026-09-25',date_to='2026-09-25',direction='sale')


def test_api_routes_interpretation_automatically(session,monkeypatch):
    client,desktop=session;calls=[]
    def interpret(query):
        calls.append(query)
        return dict(amount=dict(field='total',value='13800.00',currency=None),filters={},description='Searching total 13800.00',method='test',elapsed_s=0,assumed_field=True)
    monkeypatch.setattr(desktop.interpreter,'interpret',interpret)
    r=client.post('/api/search',json={'query':'hello mere bhai muje 13800 ka invoice dikha na'}).json()
    assert r['interpretation']['assumed_field'] and r['mode']=='bill_fields' and not r['results']
    assert len(calls)==1
    r=client.post('/api/search',json={'query':'invoice subtotal 13800'}).json()
    assert 'interpretation' not in r and len(calls)==1
    # Legacy opt-out flags cannot disable automatic interpretation.
    r=client.post('/api/search',json={'query':'hello bhai 13800 ka invoice dikhao na','bills_only':True,'use_local_interpreter':False})
    assert r.status_code==200 and r.json()['response']['method']=='qwen_source_selection'
    assert len(calls)==2


def test_missing_model_is_actionable(tmp_path):
    model=QueryInterpreter();model.model_path=tmp_path/'missing.gguf'
    assert not model.status()['available']
    with pytest.raises(ValueError,match='not installed'):model.interpret('13600 ka invoice')


@pytest.mark.parametrize('query',['lagbhag 13600 ka bill dikhao','bhai around 13600 wala invoice dikha','mujhe approximately 13600 ka invoice'])
def test_approximate_hinglish_keeps_amount(query):
    assert candidate(query)
    assert simple_request(query)['amount']['value']=='13600.00'
    amount,filters=validate(query,output())
    assert amount['value']=='13600.00' and not filters


def test_approximate_query_preserves_party_and_date():
    query='Bhagwanti Trading ko 25 September 2026 pe lagbhag 13600 ka maal becha invoice dikhao'
    assert simple_request(query) is None
    amount,filters=validate(query,output(party='Bhagwanti Trading',date='2026-09-25',direction='sale'))
    assert amount['value']=='13600.00'
    assert filters==dict(party='Bhagwanti Trading',date_from='2026-09-25',date_to='2026-09-25',direction='sale')
    with pytest.raises(ValueError):validate('bill of at most 13600',output())
