"""Focused feature checks, not the deferred permanent quality benchmark."""
import sqlite3
from types import SimpleNamespace
import pytest
from knowledge_library import workspace_features as features
from knowledge_library.bill_amounts import query_amount,search_amount
from knowledge_library.query_interpreter import expand_amount_shorthand
from tests.test_nearby_amounts import library


def test_subject_suggestions_require_evidence_and_can_overlap():
    assert features.subject_matches('DSP notes.pdf', '')[0][0] == 'DSP'
    assert 'DSP' not in {name for name,_ in features.subject_matches('Travel receipt', 'A signal and some processing fees')}
    assert not features.subject_matches('Untitled', 'The discrete fourier transform')
    assert {name for name, _ in features.subject_matches('DSP and Operating Systems', '')} == {'DSP', 'Operating Systems'}
    assert features.subject_matches('Untitled', 'The discrete fourier transform and finite impulse response')[0][0] == 'DSP'


def test_100_documents_form_overlapping_linked_folders_without_moves():
    db=sqlite3.connect(':memory:');db.row_factory=sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    db.executescript('''CREATE TABLE documents(id TEXT PRIMARY KEY,sha256 TEXT);
        CREATE TABLE pages(document_id,page_number,text,status);
        CREATE TABLE bill_records(document_id,party,party_normalized,source_sha256);''')
    docs=[]
    topics=['automata grammar','quantum physics','organic chemistry','linear algebra','network protocols']
    for i in range(100):
        key=str(i);topic=topics[i//20]
        docs.append(dict(id=key,title=topic))
        db.execute('INSERT INTO documents VALUES (?,?)',(key,key))
        db.execute('INSERT INTO pages VALUES (?,1,?,?)',(key,topic+' worked examples '*3,'ok'))
    lib=SimpleNamespace(db=db,documents=lambda:docs)
    features.initialize(lib);before=[tuple(r) for r in db.execute('SELECT * FROM documents')]
    report=features.rebuild_links(lib)
    memberships=[set(g['document_ids']) for g in report['folders']]
    assert all(set(str(i) for i in range(start,start+20)) in memberships for start in range(0,100,20))
    assert [tuple(r) for r in db.execute('SELECT * FROM documents')]==before
    old={g['id'] for g in report['folders']}
    assert {g['id'] for g in features.rebuild_links(lib)['folders']}==old
    assert len(features.scope(lib,report['folders'][0]['id']))==20
    with pytest.raises(ValueError):features.scope(lib,'missing')


@pytest.mark.parametrize('mode,value,expected',[('exact','0',False),('absolute','50',False),('absolute','100',True),('percent','.2',False),('percent','1',True)])
def test_custom_tolerance(mode,value,expected):
    lib=library([('29074','INR','Total')]);intent=dict.fromkeys(['direction','party','invoice_number','date_from','date_to','item'])
    r=search_amount(lib,'total 29000',intent,query_amount('total 29000'),[],None,None,matching=dict(mode=mode,value=value))
    assert bool(r['results'])==expected


@pytest.mark.parametrize('query,expected',[('Noorani invoice total 29k','Noorani invoice total 29000'),('bill of 1.2 lakh','bill of 120000.0'),('explain 29k vectors','explain 29k vectors'),('invoice INV-29k','invoice INV-29k')])
def test_amount_shorthand(query,expected):assert expand_amount_shorthand(query)==expected


def test_arithmetic_checks_actual_tax_values_not_percentages():
    db=sqlite3.connect(':memory:');db.row_factory=sqlite3.Row
    db.execute('CREATE TABLE pages(document_id,page_number,text)')
    text='Invoice\nSubtotal: 1000\nSGST (2.5%)\n25\nCGST (2.5%)\n25\nGrand Total: 1050\n'
    db.execute('INSERT INTO pages VALUES (?,1,?)',('a',text))
    report=features.arithmetic(SimpleNamespace(db=db),'a')
    assert report['checks'][0]['status']=='consistent' and report['checks'][0]['tax']=='50.00'
    db.execute('UPDATE pages SET text=?',(text.replace('1050','1075'),))
    assert features.arithmetic(SimpleNamespace(db=db),'a')['checks'][0]['status']=='review'
    db.execute('UPDATE pages SET text=?',(text+'Discount: 10',))
    assert not features.arithmetic(SimpleNamespace(db=db),'a')['checks']


def test_table_cells_keep_header_relationships_in_indexed_text():
    import pymupdf
    from knowledge_library.pdf import extract_page,PdfOptions
    with pymupdf.open() as pdf:
        page=pdf.new_page()
        xs=[50,180,300,430];ys=[80,110,140,170]
        for x in xs:page.draw_line((x,ys[0]),(x,ys[-1]))
        for y in ys:page.draw_line((xs[0],y),(xs[-1],y))
        for row,values in enumerate([['Product','Quantity','Rate'],['Tea','2','20'],['Coffee','3','30']]):
            for col,value in enumerate(values):page.insert_text((xs[col]+5,ys[row]+20),value)
        extracted=extract_page(page,PdfOptions())
        assert 'Product: Tea | Quantity: 2 | Rate: 20' in extracted['text']
        assert 'Product: Coffee | Quantity: 3 | Rate: 30' in extracted['text']


def test_text_rich_page_also_recognizes_embedded_image():
    import pymupdf
    from knowledge_library.pdf import extract_page,PdfOptions
    from tests.test_desktop import ROOT,FIX
    with pymupdf.open(FIX/'pdfs/scanned.pdf') as scanned, pymupdf.open() as pdf:
        pix=scanned[0].get_pixmap(matrix=pymupdf.Matrix(1.5,1.5))
        page=pdf.new_page()
        title='Native slide title with enough readable words to preserve the original text layer.'
        page.insert_text((40,40),title,fontsize=10)
        page.insert_image(pymupdf.Rect(30,80,560,800),pixmap=pix)
        extracted=extract_page(page,PdfOptions(ocr=True,tessdata=str(ROOT/'models/tessdata'),tables=False))
        assert extracted['method']=='ocr' and 'Native slide title' in extracted['text']
        assert 'embedded_images_ocr_with_native_text' in extracted['warnings']
        assert len(extracted['text'])>len(title)+20
