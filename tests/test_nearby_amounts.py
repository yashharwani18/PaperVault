"""Exercise actual source lookup with synthetic in-memory indexed invoices."""
from decimal import Decimal
import sqlite3
from types import SimpleNamespace
import pytest
from knowledge_library.bill_amounts import search_amount,query_amount,amount_tolerance
from knowledge_library.search_response import respond


def library(rows):
    db=sqlite3.connect(':memory:');db.row_factory=sqlite3.Row
    db.executescript('''CREATE TABLE documents(id,folder_id,filename,managed_path,status);
        CREATE TABLE folders(id,name); INSERT INTO folders VALUES ('bills','Bills');
        CREATE TABLE pages(document_id,page_number,text,page_label,method,warnings);
        CREATE TABLE chunks(id,document_id,page_number,char_start,char_end);
        CREATE TABLE document_sources(document_id,format);''')
    for i,(value,currency,label) in enumerate(rows):
        text=f'Invoice\n{label}: {currency} {value}\n'
        db.execute('INSERT INTO documents VALUES (?,?,?,?,?)',(str(i),'bills',f'{i}.pdf','unused','ready'))
        db.execute('INSERT INTO pages VALUES (?,1,?,1,?,?)',(str(i),text,'native','[]'))
        db.execute('INSERT INTO chunks VALUES (?,?,1,0,?)',(i,str(i),len(text)))
        db.execute('INSERT INTO document_sources VALUES (?,?)',(str(i),'pdf'))
    def result(row,*args):
        return dict(document_id=row['document_id'],chunk_id=row['id'],page_number=1,
                    filename=row['filename'],source_identity='test',passage=db.execute(
                    'SELECT text FROM pages WHERE document_id=?',(row['document_id'],)).fetchone()[0])
    return SimpleNamespace(db=db,_result=result)


def lookup(rows,query='total 29000',**scope):
    lib=library(rows)
    intent=dict.fromkeys(['direction','party','invoice_number','date_from','date_to','item'])
    return lib,search_amount(lib,query,intent,query_amount(query),[],scope.get('folder_id'),scope.get('document_id'))


def test_remembered_amount_retains_actual_and_cites_difference():
    lib,r=lookup([('29074','INR','Grand Total')])
    hit=r['results'][0];match=hit['amount_match']
    assert r['reliability']=='nearby_source_amount'
    assert match['value']=='29074.00' and match['difference']=='74.00' and match['requested_value']=='29000.00'
    assert match['evidence'] in hit['passage']
    model=SimpleNamespace(generate=lambda *a,**k:({'choice':1},0))
    for query in ['total 29000','bhai total 29000']:
        response=respond(lib,model,query,r)
        assert all(x in response['text'] for x in ['29074.00','29000.00','74.00'])
        assert response['citations'][0]['excerpt']==match['evidence']


def test_unreviewed_exact_retains_nearby_and_nearest_is_sorted():
    _,r=lookup([('29074','INR','Total'),('29000','INR','Total')])
    assert [h['amount_match']['value'] for h in r['results']]==['29000.00','29074.00']
    _,r=lookup([('29200','INR','Total'),('28990','INR','Total'),('29074','INR','Total')])
    assert [h['amount_match']['difference'] for h in r['results']]==['-10.00','74.00','200.00']


def test_nearby_alternative_survives_result_limit():
    _,r=lookup([('29000','INR','Total')]*105+[('29074','INR','Total')])
    assert len(r['results'])==100 and r['bill_matches']==106
    assert r['results'][-1]['amount_match']['value']=='29074.00'


@pytest.mark.parametrize('query',['total exactly 29000','total equals 29000','total = 29000','exact total 29000'])
def test_explicit_exact_never_broadens(query):
    _,r=lookup([('29074','INR','Total')],query)
    assert not r['results'] and r['amount_tolerance']=='0.00'


@pytest.mark.parametrize('value,expected',[('29290',True),('29290.01',False),('28710',True),('28709.99',False)])
def test_one_percent_boundary(value,expected):
    _,r=lookup([(value,'INR','Total')])
    assert bool(r['results'])==expected


def test_cap_field_currency_scope_and_no_arbitrary_nearest():
    assert amount_tolerance('total 100000','100000')==Decimal('500')
    assert amount_tolerance('total 0','0')==0
    rows=[('29074','USD','Total'),('29075','INR','Subtotal'),('31000','INR','Total')]
    _,r=lookup(rows,'total INR 29000');assert not r['results']
    _,r=lookup(rows,'subtotal INR 29000');assert r['results'][0]['document_id']=='1'
    _,r=lookup([('29074','INR','Total')],folder_id='other');assert not r['results']
    _,r=lookup([('29074','INR','Total')],document_id='missing');assert not r['results']


@pytest.mark.parametrize('query',['show me the bill where its 29000','invoice of 29,000','bill worth INR 29000','total about 29000'])
def test_conversational_english_amount(query):
    assert query_amount(query)['value']=='29000.00'


def test_bare_identifiers_and_comparisons_not_nearby():
    assert query_amount('invoice INV-29000') is None
    assert query_amount('invoice of 29000 on 25/09/2026') is None
    for query in ['total under 29000','total at most 29000','total over 29000']:
        with pytest.raises(ValueError):query_amount(query)


@pytest.mark.parametrize('query',['total around 29000','total lagbhag 29000','bill for around 29000','invoice worth approximately INR 29000'])
def test_approximate_wording_keeps_literal_and_does_not_invent_party(query):
    from knowledge_library.bills import parse_query
    assert query_amount(query)['value']=='29000.00'
    assert parse_query(query,[])['party'] is None


@pytest.mark.parametrize('query',['total 29000 se kam','total 29000 se zyada','bill for 29000 at most','total INR 29000 USD','bill of USD 29000 INR'])
def test_constraints_cannot_be_silently_relaxed(query):
    with pytest.raises(ValueError):query_amount(query)
