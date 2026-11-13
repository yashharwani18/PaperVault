from decimal import Decimal
import pytest
from knowledge_library.bill_amounts import money,query_amount,source_amounts
from tests.test_desktop import session,upload,FIX


@pytest.mark.parametrize('query',[
    'which invoice had 13600 subtotal?', 'invoice subtotal of 13,600.00',
    'subtotal was 13600', 'find invoices with sub-total = 13600.0', 'invoice subtotal 13600.',
])
def test_exact_amount_intent(query):
    assert query_amount(query)==dict(field='subtotal',value='13600.00',currency=None)


def test_money_grouping_and_invalid_formats():
    assert money('1,36,000.00')==money('136,000')==Decimal('136000')
    for value in ['13,60','1,3600','13600.001','NaN','-13600']:
        with pytest.raises(ValueError):money(value)
    for query in ['subtotal over 13600','subtotal 13,60','subtotal 13600 and total 14280']:
        with pytest.raises(ValueError):query_amount(query)
    assert query_amount('which invoice INV-13600 was sold yesterday?') is None
    assert query_amount('explain subtotal') is None
    assert query_amount('Explain total ordering from lecture 2') is None
    assert query_amount('invoices for Traders subtotal 13600')['currency'] is None


def test_source_labels_and_numeric_boundaries():
    text='Invoice\nWidget 13600.00\nSubtotal\n29280.00\nSGST (2.5%)\n13600.00\nGrand Total: 30680.00\n'
    amounts=list(source_amounts(text))
    assert [(a['field'],a['value']) for a in amounts]==[('subtotal','29280.00'),('total','30680.00')]
    for a in amounts:assert text[a['start']:a['end']].strip()==a['evidence']
    assert list(source_amounts('Subtotal\n113600.00'))[0]['value']=='113600.00'
    assert not list(source_amounts('Subtotal\n13,60'))
    assert list(source_amounts('Sub Total (INR):\n13,600.00'))[0]['currency']=='INR'


def test_api_exact_amount_without_bill_record_and_no_semantic_fallback(session):
    client,desktop=session
    folder=client.post('/api/folders',json={'name':'Exact source amounts'}).json()['id']
    jobs=upload(client,folder,[FIX/'bills'/'sale-bhagwanti-2026-09-25.pdf'])
    assert jobs[0]['status']=='completed',jobs
    key=jobs[0]['result']['document']['id']
    # Existing imports without usable structured bill metadata must work too.
    import sqlite3
    with sqlite3.connect(desktop.root/'library.sqlite3') as db:db.execute('DELETE FROM bill_records WHERE document_id=?',(key,))
    before=dict(desktop.model.stats)
    def search(query,**extra):
        r=client.post('/api/search',json=dict(query=query,folder_id=folder,**extra))
        assert r.status_code==200,r.text
        return r.json()
    r=search('which invoice had 4500 subtotal?')
    assert r['bill_matches']==1 and r['reliability']=='exact_source_amount',r
    hit=r['results'][0]
    assert hit['document_id']==key and hit['source_identity']
    assert hit['amount_match']['evidence'] in hit['passage']
    assert hit['amount_match']['field']=='subtotal'
    assert search('subtotal 4,500.00')['bill_matches']==1
    assert search('subtotal 5310')['results']==[]  # Grand total is not subtotal.
    assert search('total 5310')['bill_matches']==1
    assert search('subtotal 45000')['empty_reason']=='no_matching_amount'
    assert search('subtotal 4500',bill_filters={'party':'Missing party'})['results']==[]
    assert client.post('/api/search',json={'query':'subtotal over 4500'}).status_code==400
    assert desktop.model.stats==before  # Exact amounts must never run embeddings.
