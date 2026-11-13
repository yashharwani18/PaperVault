import json
import zipfile
from pathlib import Path
import pytest
from knowledge_library.text_documents import open_text_document, source_info, TEXT_EXTENSIONS, SPREADSHEET_EXTENSIONS, SUPPORTED_EXTENSIONS


def office(path, parts):
    with zipfile.ZipFile(path, 'w') as z:
        for name, value in parts.items(): z.writestr(name, value)
    return path


def units(path):
    with open_text_document(path) as doc:
        return doc, [u.extracted for u in doc]


def test_csv_large_fields_and_locations_survive_managed_rename(tmp_path):
    p=tmp_path/'original.csv';p.write_text('a'*140000+',second',encoding='utf-8')
    before=units(p)[1];renamed=p.rename(tmp_path/'managed-hash.csv')
    assert units(renamed)[1]==before
    assert 'a'*140000 in before[0]['text']


def test_odt_expansion_is_bounded_before_collecting_all_paragraphs(tmp_path,monkeypatch):
    from knowledge_library import text_documents as td
    monkeypatch.setattr(td,'MAX_TEXT_CHARS',1000)
    calls=[];original=td._odf_text
    def counted(node):
        if node.tag==td.tag('t','p'):calls.append(1)
        return original(node)
    monkeypatch.setattr(td,'_odf_text',counted)
    p=office(tmp_path/'repeat.odt',{'content.xml':'<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"><office:body><office:text>'+('<text:p><text:s text:c="999"/>A</text:p>'*100)+'</office:text></office:body></office:document-content>'})
    with pytest.raises(ValueError,match='limit'):units(p)
    assert len(calls)<=2


def test_json_records_and_jsonl_lines(tmp_path):
    p=tmp_path/'answers.json';p.write_text(json.dumps([{'Instruction':'Detect ransomware','Output':'Isolate the host'},{'Instruction':'Review logs'}]),encoding='utf-8')
    doc,rows=units(p)
    assert [r['evidence']['location']['label'] for r in rows]==['Record 1','Record 2']
    assert 'Detect ransomware' in rows[0]['text'] and 'Review logs' in rows[1]['text']
    assert source_info({'filename':'answers.json','page_count':doc.page_count})==dict(source_kind='text',source_format='json',preview_kind='text',unit_count=2)
    q=tmp_path/'stream.jsonl';q.write_text('{"a":1}\n\n{"b":2}\n',encoding='utf-8')
    _,rows=units(q)
    assert len(rows)==2 and rows[1]['evidence']['location']['line_start']==3 and '"b": 2' in rows[1]['text']


def test_invalid_json_is_reported(tmp_path):
    p=tmp_path/'broken.json';p.write_text('{',encoding='utf-8')
    with pytest.raises(ValueError,match='Malformed JSON'):units(p)
    p=tmp_path/'broken.jsonl';p.write_text('{"ok":1}\nnot json\n',encoding='utf-8')
    with pytest.raises(ValueError,match='line 2'):units(p)


def test_registry_and_source_info():
    assert {'.docx', '.odt', '.txt', '.markdown', '.html', '.json', '.jsonl'} <= TEXT_EXTENSIONS
    assert {'.xlsx', '.ods', '.csv', '.tsv'} <= SPREADSHEET_EXTENSIONS
    assert {'.pdf', '.ppt', '.pptx'} <= SUPPORTED_EXTENSIONS
    assert '.rtf' not in SUPPORTED_EXTENSIONS
    assert source_info({'filename':'data.xlsx','page_count':3,'recipe':'{}'}) == dict(source_kind='spreadsheet', source_format='xlsx', preview_kind='text', unit_count=3)
    assert source_info({'filename':'deck.pptx','page_count':3})['preview_kind']=='pdf'


def test_unicode_markdown_html_and_decoding(tmp_path):
    p=tmp_path/'notes.md';p.write_text('# नमस्ते\n\nRésumé text\n\n## Next\n\nEnd', encoding='utf-8')
    doc, rows=units(p)
    assert doc.metadata['title']=='notes' and doc.page_count==len(rows)
    assert any(r['evidence']['location'].get('heading')=='नमस्ते' and 'Résumé' in r['text'] for r in rows)
    assert all(r['evidence']['frame']=='source_text' and r['page_number']==i+1 for i,r in enumerate(rows))
    h=tmp_path/'x.html';h.write_text('<title>Title</title><h1>Heading</h1><p>Hello <b>world</b></p><script>BAD</script><style>WORSE</style><img src="https://example.invalid/x">', encoding='utf-8')
    d, rows=units(h)
    assert d.metadata['title']=='Title'
    assert 'Hello world' in '\n'.join(r['text'] for r in rows)
    assert not any('BAD' in r['text'] or 'WORSE' in r['text'] for r in rows)
    p=tmp_path/'u.txt';p.write_bytes('hello Ω'.encode('utf-16'))
    assert units(p)[1][0]['text']=='hello Ω'
    p.write_bytes(b'caf\xe9')
    assert units(p)[1][0]['text']=='café'
    assert 'legacy_windows_1252_decoding' in units(p)[1][0]['warnings']


def test_csv_multiline_sparse_rows_and_formula_safety(tmp_path):
    p=tmp_path/'rows.csv';p.write_text('Name,Note\nA,"hello\nworld"\n\nB,=WEBSERVICE("remote")\n',encoding='utf-8')
    _,rows=units(p)
    assert len(rows)==3
    assert rows[1]['evidence']['location']['row_start']==2
    assert rows[1]['evidence']['location']['line_end']==3
    assert 'hello\nworld' in rows[1]['text']
    assert '=WEBSERVICE' in rows[2]['text']
    assert rows[2]['evidence']['location']['row_start']==4


def test_docx_order_deletions_and_odt(tmp_path):
    p=office(tmp_path/'a.docx',{'word/document.xml':'''<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Heading</w:t></w:r></w:p><w:p><w:r><w:t>Before</w:t></w:r><w:del><w:r><w:delText>DELETED</w:delText></w:r></w:del></w:p><w:tbl><w:tr><w:tc><w:p><w:r><w:t>Cell</w:t></w:r></w:p></w:tc></w:tr></w:tbl><w:p><w:r><w:t>After</w:t></w:r></w:p></w:body></w:document>'''})
    _,rows=units(p);text='\n'.join(r['text'] for r in rows)
    assert text.index('Before')<text.index('Cell')<text.index('After') and 'DELETED' not in text
    assert any(r['evidence']['location'].get('heading')=='Heading' for r in rows)
    p=office(tmp_path/'a.odt',{'content.xml':'''<o:document-content xmlns:o="urn:oasis:names:tc:opendocument:xmlns:office:1.0" xmlns:t="urn:oasis:names:tc:opendocument:xmlns:text:1.0"><o:body><o:text><t:h>H</t:h><t:p>A<t:s t:c="2"/>B<t:tab/>C</t:p></o:text></o:body></o:document-content>'''})
    assert 'A  B\tC' in '\n'.join(r['text'] for r in units(p)[1])


def test_xlsx_relationships_sparse_cells_cached_formulas_and_dates(tmp_path):
    p=office(tmp_path/'a.xlsx',{
      'xl/workbook.xml':'<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Income" sheetId="7" r:id="rId9"/></sheets></workbook>',
      'xl/_rels/workbook.xml.rels':'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId9" Target="worksheets/sheet7.xml" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"/></Relationships>',
      'xl/styles.xml':'<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><cellXfs><xf numFmtId="0"/><xf numFmtId="14"/></cellXfs></styleSheet>',
      'xl/worksheets/sheet7.xml':'<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="8"><c r="A8" t="inlineStr"><is><t>Revenue</t></is></c><c r="C8"><f>1+1</f><v>2</v></c><c r="D8"><f>WEBSERVICE("x")</f></c><c r="E8" s="1"><v>45292</v></c></row></sheetData></worksheet>'})
    _,rows=units(p);row=rows[0]
    assert row['evidence']['location']['sheet']=='Income' and row['evidence']['location']['row_start']==8
    assert 'A8: Revenue' in row['text'] and 'C8: 2' in row['text'] and 'E8: 2024-01-01' in row['text']
    assert 'cached value unavailable' in row['text'] and 'formula_cached_value_missing' in row['warnings']


def test_ods_repeated_rows_and_columns(tmp_path):
    p=office(tmp_path/'a.ods',{'content.xml':'''<o:document-content xmlns:o="urn:oasis:names:tc:opendocument:xmlns:office:1.0" xmlns:t="urn:oasis:names:tc:opendocument:xmlns:table:1.0" xmlns:x="urn:oasis:names:tc:opendocument:xmlns:text:1.0"><o:body><o:spreadsheet><t:table t:name="Sheet"><t:table-row t:number-rows-repeated="7"/><t:table-row><t:table-cell t:number-columns-repeated="2"/><t:table-cell o:value-type="string"><x:p>Actual</x:p></t:table-cell></t:table-row></t:table></o:spreadsheet></o:body></o:document-content>'''})
    row=units(p)[1][0]
    assert row['evidence']['location']['row_start']==8 and 'C8: Actual' in row['text']


def test_reject_unsafe_containers_and_limits(tmp_path,monkeypatch):
    import knowledge_library.text_documents as m
    p=office(tmp_path/'a.docx',{'word/document.xml':'<!DOCTYPE x [<!ENTITY a "boom">]><x>&a;</x>'})
    with pytest.raises(ValueError,match='DTD|entities'):units(p)
    p=office(tmp_path/'a.docx',{'word/document.xml':'<x/>','word/vbaProject.bin':'macro'})
    with pytest.raises(ValueError,match='[Mm]acro'):units(p)
    p=tmp_path/'a.txt';p.write_text('hello')
    monkeypatch.setattr(m,'MAX_TEXT_CHARS',4)
    with pytest.raises(ValueError,match='text limit'):units(p)
    p=tmp_path/'a.rtf';p.write_text('hello')
    with pytest.raises(ValueError,match='[Uu]nsupported'):units(p)


def test_limits_unit_count_xml_and_zip(tmp_path,monkeypatch):
    import knowledge_library.text_documents as m
    p=tmp_path/'a.txt';p.write_text('one\n\ntwo',encoding='utf-8')
    monkeypatch.setattr(m,'MAX_UNITS',1)
    with pytest.raises(ValueError,match='unit limit'):units(p)
    monkeypatch.setattr(m,'MAX_UNITS',10_000)
    monkeypatch.setattr(m,'MAX_XML_BYTES',3)
    p=office(tmp_path/'a.odt',{'content.xml':'<hello/>'})
    with pytest.raises(ValueError,match='XML part limit'):units(p)
    p=office(tmp_path/'a.xlsx',{'../escape.xml':'x'})
    with pytest.raises(ValueError,match='Unsafe'):units(p)


def test_external_sheet_relationship_refused(tmp_path):
    p=office(tmp_path/'a.xlsx',{
      'xl/workbook.xml':'<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="External" r:id="r1"/></sheets></workbook>',
      'xl/_rels/workbook.xml.rels':'<Relationships><Relationship Id="r1" Target="https://example.invalid/data.xml" TargetMode="External"/></Relationships>'})
    with pytest.raises(ValueError,match='External'):units(p)


def test_deleted_whole_paragraph_and_ods_formula_cache(tmp_path):
    p=office(tmp_path/'a.docx',{'word/document.xml':'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:del><w:p><w:r><w:t>Deleted</w:t></w:r></w:p></w:del><w:p><w:r><w:t>Current</w:t></w:r></w:p></w:body></w:document>'})
    assert [r['text'] for r in units(p)[1]]==['Current']
    p=office(tmp_path/'a.ods',{'content.xml':'''<o:document-content xmlns:o="urn:oasis:names:tc:opendocument:xmlns:office:1.0" xmlns:t="urn:oasis:names:tc:opendocument:xmlns:table:1.0"><o:body><o:spreadsheet><t:table t:name="S"><t:table-row><t:table-cell t:formula="of:=1+1" o:value="2"/><t:table-cell t:formula="of:=1/0"/></t:table-row></t:table></o:spreadsheet></o:body></o:document-content>'''})
    row=units(p)[1][0]
    assert 'A1: 2' in row['text'] and 'B1: [formula cached value unavailable]' in row['text']


def test_relocated_xlsx_parts_shared_strings_and_1904_epoch(tmp_path):
    p=office(tmp_path/'a.xlsx',{
      '_rels/.rels':'<Relationships><Relationship Type="office/officeDocument" Target="custom/book.xml"/></Relationships>',
      'custom/book.xml':'<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><workbookPr date1904="1"/><sheets><sheet name="S" r:id="r1"/></sheets></workbook>',
      'custom/_rels/book.xml.rels':'<Relationships><Relationship Id="r1" Type="office/worksheet" Target="tab.xml"/><Relationship Id="r2" Type="office/sharedStrings" Target="strings.xml"/><Relationship Id="r3" Type="office/styles" Target="format.xml"/></Relationships>',
      'custom/strings.xml':'<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><si><r><t>Hello </t></r><r><t>世界</t></r></si></sst>',
      'custom/format.xml':'<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><cellXfs><xf numFmtId="14"/></cellXfs></styleSheet>',
      'custom/tab.xml':'<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="3"><c r="A3" t="s"><v>0</v></c><c r="B3"><v>0</v></c></row></sheetData></worksheet>'})
    row=units(p)[1][0]
    assert 'A3: Hello 世界' in row['text'] and 'B3: 1904-01-01' in row['text']


def test_empty_and_invalid_text(tmp_path):
    p=tmp_path/'empty.txt';p.write_bytes(b'')
    assert units(p)[0].page_count==0
    p.write_bytes(b'bad\x00binary')
    with pytest.raises(ValueError,match='Binary'):units(p)
    p=tmp_path/'bad.docx';p.write_bytes(b'not a zip')
    with pytest.raises(ValueError,match='Cannot read Office'):units(p)


def test_odt_stops_expansion_before_collecting_all_paragraphs(tmp_path, monkeypatch):
    import knowledge_library.text_documents as m
    monkeypatch.setattr(m, 'MAX_TEXT_CHARS', 1000)
    p=office(tmp_path/'expanded.odt', {'content.xml': '<o:document-content xmlns:o="urn:oasis:names:tc:opendocument:xmlns:office:1.0" xmlns:t="urn:oasis:names:tc:opendocument:xmlns:text:1.0"><o:body><o:text>'+('<t:p>X<t:s t:c="999"/></t:p>'*100)+'</o:text></o:body></o:document-content>'})
    original=m._odf_text;expanded=[]
    def observed(node):
        if node.tag==m.tag('t','p'):expanded.append(node)
        return original(node)
    monkeypatch.setattr(m,'_odf_text',observed)
    with pytest.raises(ValueError,match='text limit'):units(p)
    assert len(expanded)<=2, 'Stop before expanding the rest of the document'


def test_large_csv_fields_and_managed_rename_have_stable_locations(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    original=tmp_path/'user-data.csv';managed=tmp_path/('a'*64+'.csv')
    original.write_text('"'+('x'*140_000)+'"\n',encoding='utf-8');managed.write_bytes(original.read_bytes())
    with ThreadPoolExecutor(max_workers=4) as pool:
        results=list(pool.map(lambda p:units(p)[1], [original,managed,original,managed]))
    assert all(rows==results[0] for rows in results)
    assert len(results[0][0]['text'])>140_000
    assert results[0][0]['evidence']['location']['sheet']=='CSV data'


@pytest.mark.parametrize('suffix', ['.csv','.tsv'])
def test_delimited_source_locations_do_not_depend_on_filename(tmp_path,suffix):
    p=tmp_path/('original'+suffix);q=tmp_path/('managed-sha256'+suffix)
    p.write_text('a,b\n',encoding='utf-8');q.write_bytes(p.read_bytes())
    assert units(p)[1]==units(q)[1]
