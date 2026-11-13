"""Bounded, passive text extraction with original section and row provenance."""
from __future__ import annotations
import csv
import threading
import datetime as dt
from html.parser import HTMLParser
import io
import json
from pathlib import Path, PurePosixPath
import posixpath
import re
import zipfile
import xml.etree.ElementTree as ET
from types import SimpleNamespace

JSON_EXTENSIONS=frozenset({'.json','.jsonl'})
TEXT_EXTENSIONS=frozenset({'.docx','.odt','.txt','.md','.markdown','.html','.htm'})|JSON_EXTENSIONS
SPREADSHEET_EXTENSIONS=frozenset({'.xlsx','.ods','.csv','.tsv'})
NATIVE_EXTENSIONS=TEXT_EXTENSIONS|SPREADSHEET_EXTENSIONS
SUPPORTED_EXTENSIONS=NATIVE_EXTENSIONS|{'.pdf','.ppt','.pptx'}
MIME_TYPES={'.pdf':'application/pdf','.ppt':'application/vnd.ms-powerpoint','.pptx':'application/vnd.openxmlformats-officedocument.presentationml.presentation',
 '.docx':'application/vnd.openxmlformats-officedocument.wordprocessingml.document','.odt':'application/vnd.oasis.opendocument.text',
 '.txt':'text/plain; charset=utf-8','.md':'text/markdown; charset=utf-8','.markdown':'text/markdown; charset=utf-8','.html':'text/html; charset=utf-8','.htm':'text/html; charset=utf-8',
 '.xlsx':'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet','.ods':'application/vnd.oasis.opendocument.spreadsheet',
 '.csv':'text/csv; charset=utf-8','.tsv':'text/tab-separated-values; charset=utf-8','.json':'application/json; charset=utf-8','.jsonl':'application/x-ndjson; charset=utf-8',
 '.py':'text/plain; charset=utf-8','.js':'text/javascript; charset=utf-8','.jsx':'text/javascript; charset=utf-8',
 '.ts':'text/typescript; charset=utf-8','.tsx':'text/typescript; charset=utf-8','.css':'text/css; charset=utf-8',
 '.yaml':'text/yaml; charset=utf-8','.yml':'text/yaml; charset=utf-8','.xml':'text/xml; charset=utf-8',
 '.sql':'text/plain; charset=utf-8','.sh':'text/plain; charset=utf-8','.ps1':'text/plain; charset=utf-8',
 '.cmd':'text/plain; charset=utf-8','.bat':'text/plain; charset=utf-8','.env':'text/plain; charset=utf-8','.log':'text/plain; charset=utf-8',
 '.png':'image/png','.jpg':'image/jpeg','.jpeg':'image/jpeg','.webp':'image/webp','.svg':'image/svg+xml','.gif':'image/gif','.bmp':'image/bmp','.ico':'image/x-icon',
 '.mp4':'video/mp4','.webm':'video/webm','.mov':'video/quicktime','.mkv':'video/x-matroska',
 '.mp3':'audio/mpeg','.wav':'audio/wav','.m4a':'audio/mp4','.ogg':'audio/ogg','.flac':'audio/flac'}
EXTRACTION_VERSION='native-source-text-v1'
MAX_SOURCE_BYTES=100*1024**2
MAX_EXPANDED_BYTES=128*1024**2
MAX_XML_BYTES=32*1024**2
MAX_TEXT_CHARS=20_000_000
MAX_UNITS=10_000
MAX_ZIP_ENTRIES=20_000
MAX_COORDINATE=1_048_576
_CSV_LOCK=threading.Lock()
NS={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main','s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main',
 'r':'http://schemas.openxmlformats.org/officeDocument/2006/relationships','o':'urn:oasis:names:tc:opendocument:xmlns:office:1.0',
 't':'urn:oasis:names:tc:opendocument:xmlns:text:1.0','tb':'urn:oasis:names:tc:opendocument:xmlns:table:1.0'}

def tag(prefix,name):return '{'+NS[prefix]+'}'+name

def source_info(doc):
    try:recipe=json.loads(doc.get('recipe') or '{}') if isinstance(doc.get('recipe'),str) else doc.get('recipe') or {}
    except (ValueError,TypeError):recipe={}
    ext=Path(doc.get('filename','')).suffix.lower()
    fmt=recipe.get('source_format') or ext.lstrip('.') or 'pdf'
    kind=recipe.get('source_kind') or ('spreadsheet' if '.'+fmt in SPREADSHEET_EXTENSIONS else 'text' if '.'+fmt in TEXT_EXTENSIONS else 'presentation' if fmt in ('ppt','pptx') else 'pdf')
    return dict(source_kind=kind,source_format=fmt,preview_kind='text' if kind in ('text','spreadsheet') else 'pdf',unit_count=doc.get('page_count',0))

class TextDocument:
    def __init__(self,path):
        self.path=Path(path);self.metadata={'title':self.path.stem};self.units=[];self.characters=0
        self.ext=self.path.suffix.lower();self.method='spreadsheet' if self.ext in SPREADSHEET_EXTENSIONS else 'text'
    @property
    def page_count(self):return len(self.units)
    def __enter__(self):return self
    def __exit__(self,*args):return False
    def __iter__(self):return iter(self.units)
    def add(self,text,location,warnings=()):
        if not text.strip():return
        self.characters+=len(text)
        if self.characters>MAX_TEXT_CHARS:raise ValueError('Extracted text limit exceeded (20 million characters)')
        if len(self.units)>=MAX_UNITS:raise ValueError('Source unit limit exceeded (10,000)')
        n=len(self.units)+1
        extracted=dict(page_number=n,page_label=location['label'],text=text,method=self.method,status='ok',warnings=list(warnings),ocr_confidence=None,
            evidence=dict(version=1,frame='source_text',words=[],tables=[],bounds=[],location=location))
        self.units.append(SimpleNamespace(number=n-1,extracted=extracted))

class Package:
    def __init__(self,path):
        try:self.zip=zipfile.ZipFile(path)
        except zipfile.BadZipFile as exc:raise ValueError('Cannot read Office document; damaged or encrypted container') from exc
        try:
            infos=self.zip.infolist();names=[i.filename for i in infos]
            if len(infos)>MAX_ZIP_ENTRIES or len(set(names))!=len(names):raise ValueError('Duplicate or excessive Office ZIP entries')
            if sum(i.file_size for i in infos)>MAX_EXPANDED_BYTES:raise ValueError('Office expanded data limit exceeded (128 MiB)')
            if any(i.flag_bits&1 for i in infos):raise ValueError('Encrypted Office documents are unsupported')
            if any('vbaproject' in n.lower() or n.lower().endswith('vbaData.xml'.lower()) for n in names):raise ValueError('Macro-containing documents are unsupported')
            if any(n.startswith('/') or '\\' in n or '..' in PurePosixPath(n).parts for n in names):raise ValueError('Unsafe Office ZIP member path')
        except BaseException:self.zip.close();raise
    def close(self):self.zip.close()
    def xml(self,name,optional=False):
        try:info=self.zip.getinfo(name)
        except KeyError:
            if optional:return None
            raise ValueError('Missing Office document part: '+name)
        if info.file_size>MAX_XML_BYTES:raise ValueError('Office XML part limit exceeded (32 MiB)')
        raw=self.zip.read(info)
        # XML declarations may use UTF-16. Check decoded syntax before ElementTree.
        if raw.startswith((b'\xff\xfe',b'\xfe\xff')):scan=raw.decode('utf-16')
        else:scan=raw.replace(b'\x00',b'').decode('latin1')
        if '<!DOCTYPE' in scan.upper() or '<!ENTITY' in scan.upper():raise ValueError('DTD and XML entities are unsupported')
        try:return ET.fromstring(raw)
        except ET.ParseError as exc:raise ValueError('Malformed Office XML: '+name) from exc
    def related(self,part,rid):
        rel=posixpath.join(posixpath.dirname(part),'_rels',posixpath.basename(part)+'.rels')
        tree=self.xml(rel)
        for node in tree:
            if node.get('Id')==rid:
                if node.get('TargetMode','').lower()=='external':raise ValueError('External Office source relationships are unsupported')
                target=node.get('Target','')
                result=posixpath.normpath(target.lstrip('/') if target.startswith('/') else posixpath.join(posixpath.dirname(part),target))
                if result.startswith('../') or ':' in result or '\\' in result:raise ValueError('Unsafe Office relationship')
                return result
        raise ValueError('Missing Office relationship: '+str(rid))

def _decode(path):
    data=path.read_bytes()
    try:
        if data.startswith((b'\xff\xfe',b'\xfe\xff')):return data.decode('utf-16').replace('\r\n','\n').replace('\r','\n'),[]
        return data.decode('utf-8-sig').replace('\r\n','\n').replace('\r','\n'),[]
    except UnicodeDecodeError:
        try:return data.decode('cp1252').replace('\r\n','\n').replace('\r','\n'),['legacy_windows_1252_decoding']
        except UnicodeDecodeError as exc:raise ValueError('Unsupported text encoding; save as UTF-8 or UTF-16 with a BOM') from exc

def _sections(doc,records,warnings=()):
    heading='';paragraph=0
    for text,is_heading,extra in records:
        if not text.strip():continue
        paragraph+=1
        if is_heading:heading=text.strip()
        label=(heading+' · ' if heading else '')+f'Paragraph {paragraph}'
        doc.add(text,dict(kind='section',label=label,heading=heading,paragraph_start=paragraph,paragraph_end=paragraph,**extra),warnings)

def _plain(doc,text,warnings):
    records=[];block=[];start=1;fenced=False
    for line_no,line in enumerate(text.splitlines(),1):
        stripped=line.strip();is_heading=doc.ext in ('.md','.markdown') and not fenced and re.match(r'^#{1,6}\s+',stripped)
        if stripped.startswith(('```','~~~')):fenced=not fenced
        if not stripped or is_heading:
            if block:records.append(('\n'.join(block),False,dict(line_start=start,line_end=line_no-1)));block=[]
            if is_heading:records.append((re.sub(r'^#{1,6}\s+','',stripped).rstrip('#').strip(),True,dict(line_start=line_no,line_end=line_no)));continue
        if stripped:
            if not block:start=line_no
            block.append(line)
    if block:records.append(('\n'.join(block),False,dict(line_start=start,line_end=len(text.splitlines()))))
    _sections(doc,records,warnings)

class PassiveHTML(HTMLParser):
    BLOCKS={'p','div','li','tr','pre','blockquote','section','article','h1','h2','h3','h4','h5','h6'}
    def __init__(self):
        super().__init__(convert_charrefs=True);self.skip=[];self.title=[];self.in_title=False;self.buf=[];self.heading=False;self.records=[]
    def flush(self):
        text=''.join(self.buf).strip()
        if text:self.records.append((text,self.heading,{}))
        self.buf=[]
    def handle_starttag(self,name,attrs):
        if self.skip:
            if name in ('script','style','template','noscript'):self.skip.append(name)
            return
        if name in ('script','style','template','noscript'):self.skip.append(name);return
        if name=='title':self.in_title=True;return
        if name in self.BLOCKS:self.flush();self.heading=name.startswith('h') and len(name)==2 and name[1].isdigit()
        if name=='br':self.buf.append('\n')
        if name in ('td','th') and self.buf:self.buf.append(' | ')
    def handle_endtag(self,name):
        if self.skip:
            if name==self.skip[-1]:self.skip.pop()
            return
        if name=='title':self.in_title=False;return
        if name in self.BLOCKS:self.flush();self.heading=False
    def handle_data(self,data):
        if self.skip:return
        if self.in_title:self.title.append(data)
        else:self.buf.append(data)

def _word_text(node):
    if node.tag in (tag('w','del'),tag('w','moveFrom')):return ''
    if node.tag==tag('w','t'):return node.text or ''
    if node.tag==tag('w','tab'):return '\t'
    if node.tag in (tag('w','br'),tag('w','cr')):return '\n'
    return ''.join(_word_text(c) for c in node)

def _docx(doc,pkg):
    part='word/document.xml'
    if '_rels/.rels' in pkg.zip.namelist():
        rel=pkg.xml('_rels/.rels')
        for r in rel:
            if r.get('Type','').endswith('/officeDocument'):
                if r.get('TargetMode','').lower()=='external':raise ValueError('External document relationship unsupported')
                part=posixpath.normpath(r.get('Target','').lstrip('/'))
                if part.startswith('../') or '\\' in part or ':' in part:raise ValueError('Unsafe Office relationship')
                break
    root=pkg.xml(part);body=root.find('w:body',NS)
    if body is None:raise ValueError('DOCX body missing')
    records=[]
    def walk(node):
        if node.tag in (tag('w','del'),tag('w','moveFrom')):return
        if node.tag==tag('w','p'):
            text=_word_text(node)
            style=node.find('w:pPr/w:pStyle',NS);value=style.get(tag('w','val'),'') if style is not None else ''
            records.append((text,value.lower().startswith('heading'),{}));return
        for child in node:walk(child)
    walk(body)
    _sections(doc,records)

def _odf_text(node):
    if node.tag in (tag('t','tracked-changes'),tag('t','deletion')):return ''
    if node.tag==tag('t','s'):
        count=_positive(node.get(tag('t','c'),'1'))
        if count>MAX_TEXT_CHARS:raise ValueError('Extracted text limit exceeded')
        return ' '*count
    if node.tag==tag('t','tab'):return '\t'
    if node.tag==tag('t','line-break'):return '\n'
    pieces=[node.text or ''];size=len(pieces[0])
    for child in node:
        piece=_odf_text(child)+(child.tail or '');size+=len(piece)
        if size>MAX_TEXT_CHARS:raise ValueError('Extracted text limit exceeded')
        pieces.append(piece)
    return ''.join(pieces)

def _odt(doc,pkg):
    root=pkg.xml('content.xml');body=root.find('o:body/o:text',NS)
    if body is None:raise ValueError('ODT text body missing')
    records=[];total=0
    def walk(node):
        nonlocal total
        if node.tag==tag('t','tracked-changes'):return
        if node.tag in (tag('t','p'),tag('t','h')):
            text=_odf_text(node);total+=len(text)
            if total>MAX_TEXT_CHARS:raise ValueError('Extracted text limit exceeded')
            records.append((text,node.tag==tag('t','h'),{}));return
        for child in node:walk(child)
    walk(body);_sections(doc,records)

def _positive(value):
    try:n=int(value)
    except (TypeError,ValueError) as exc:raise ValueError('Invalid spreadsheet coordinate/repeat') from exc
    if n<1 or n>MAX_COORDINATE:raise ValueError('Spreadsheet coordinate/repeat limit exceeded')
    return n

def _column(n):
    result=''
    while n:n,r=divmod(n-1,26);result=chr(65+r)+result
    return result

def _row(doc,sheet,n,cells,warnings=(),**extra):
    if cells:doc.add('\n'.join(cells),dict(kind='sheet_rows',label=f'{sheet} · Row {n}',sheet=sheet,row_start=n,row_end=n,**extra),warnings)

def _json(doc,text,warnings):
    def malformed(detail,line=None):
        where=f' on line {line}' if line else ''
        raise ValueError(f'Malformed JSON{where}: {detail}')
    def value_text(value):
        try:return json.dumps(value,ensure_ascii=False,indent=2)
        except RecursionError as exc:raise ValueError('JSON nesting is too deep to extract') from exc
    if doc.ext=='.jsonl':
        record=0
        for line_no,line in enumerate(text.splitlines(),1):
            if not line.strip():continue
            record+=1
            try:value=json.loads(line)
            except (ValueError,RecursionError) as exc:malformed(str(exc),line_no)
            doc.add(value_text(value),dict(kind='section',label=f'Record {record} · Line {line_no}',
                line_start=line_no,line_end=line_no,record=record),warnings)
        return
    try:value=json.loads(text)
    except (ValueError,RecursionError) as exc:malformed(str(exc))
    records=value if isinstance(value,list) else [value]
    for record,item in enumerate(records,1):
        doc.add(value_text(item),dict(kind='section',label=f'Record {record}',record=record),warnings)

def _csv(doc,text,warnings):
    with _CSV_LOCK:
        previous_limit=csv.field_size_limit(MAX_TEXT_CHARS)
        try:_csv_rows(doc,text,warnings)
        finally:csv.field_size_limit(previous_limit)


def _csv_rows(doc,text,warnings):
    reader=csv.reader(io.StringIO(text,newline=''),delimiter='\t' if doc.ext=='.tsv' else ',',strict=True)
    previous=0
    try:
        for record_no,values in enumerate(reader,1):
            line_start=previous+1;previous=reader.line_num
            _row(doc,'TSV data' if doc.ext=='.tsv' else 'CSV data',record_no,[f'{_column(i)}{record_no}: {v}' for i,v in enumerate(values,1) if v.strip()],warnings,line_start=line_start,line_end=previous)
    except csv.Error as exc:raise ValueError('Malformed delimited text: '+str(exc)) from exc

def _xlsx(doc,pkg):
    part='xl/workbook.xml'
    # Most workbooks use xl/workbook.xml; root relationship may relocate it.
    if '_rels/.rels' in pkg.zip.namelist():
        for rel in pkg.xml('_rels/.rels'):
            if rel.get('Type','').endswith('/officeDocument'):
                if rel.get('TargetMode','').lower()=='external':raise ValueError('External workbook unsupported')
                part=posixpath.normpath(rel.get('Target','').lstrip('/'))
    book=pkg.xml(part);base=posixpath.dirname(part)
    strings=[];styles=[];numfmts={}
    # Resolve related shared-string/styles parts, including nonstandard names.
    relpath=posixpath.join(base,'_rels',posixpath.basename(part)+'.rels');rels=pkg.xml(relpath)
    optional={'sharedStrings':posixpath.join(base,'sharedStrings.xml'),'styles':posixpath.join(base,'styles.xml')}
    for rel in rels:
        kind=rel.get('Type','').rsplit('/',1)[-1]
        if kind in optional:optional[kind]=pkg.related(part,rel.get('Id'))
    shared=pkg.xml(optional['sharedStrings'],True)
    if shared is not None:strings=[''.join(n.itertext()) for n in shared.findall('s:si',NS)]
    style=pkg.xml(optional['styles'],True)
    if style is not None:
        numfmts={int(n.get('numFmtId')):n.get('formatCode','') for n in style.findall('s:numFmts/s:numFmt',NS)}
        styles=[int(n.get('numFmtId','0')) for n in style.findall('s:cellXfs/s:xf',NS)]
    props=book.find('s:workbookPr',NS);epoch1904=props is not None and props.get('date1904') in ('1','true')
    sheets=book.find('s:sheets',NS)
    if sheets is None:raise ValueError('XLSX sheets missing')
    for sheet in sheets:
        name=sheet.get('name','Sheet');root=pkg.xml(pkg.related(part,sheet.get(tag('r','id'))));last=0
        for row in root.findall('s:sheetData/s:row',NS):
            n=_positive(row.get('r',str(last+1)));last=n;cells=[];warnings=[];col=0
            for c in row.findall('s:c',NS):
                ref=c.get('r');col+=1
                if ref:
                    match=re.fullmatch(r'([A-Z]+)([1-9][0-9]*)',ref)
                    if not match or int(match[2])!=n:raise ValueError('Invalid XLSX cell coordinate')
                    col=0
                    for letter in match[1]:col=col*26+ord(letter)-64
                    if col>16384:raise ValueError('Spreadsheet column limit exceeded')
                else:ref=f'{_column(col)}{n}'
                kind=c.get('t','n');value=c.find('s:v',NS);formula=c.find('s:f',NS)
                raw=value.text if value is not None and value.text is not None else ''
                if kind=='inlineStr':raw=''.join(t.text or '' for t in c.findall('s:is//s:t',NS))
                elif kind=='s':
                    try:
                        string_index=int(raw)
                        if string_index<0:raise ValueError('negative shared string index')
                        raw=strings[string_index]
                    except (ValueError,IndexError) as exc:raise ValueError('Invalid XLSX shared-string reference') from exc
                elif kind=='b' and raw:raw='TRUE' if raw=='1' else 'FALSE'
                elif raw and kind=='n':
                    try:
                        style_index=int(c.get('s','0'))
                        if style_index<0:raise ValueError('negative style index')
                        fmt=styles[style_index] if styles else 0
                    except (ValueError,IndexError) as exc:raise ValueError('Invalid XLSX style reference') from exc
                    code=numfmts.get(fmt,'');clean=re.sub(r'"[^"]*"|\\.|\[[^\]]*\]','',code).lower()
                    if fmt in {14,15,16,17,22,27,30,36,45,46,47,50,57} or ('y' in clean and ('d' in clean or 'm' in clean)):
                        try:
                            serial=float(raw);base_date=dt.datetime(1904,1,1) if epoch1904 else dt.datetime(1899,12,31)
                            if not epoch1904 and serial>=60:serial-=1
                            date=base_date+dt.timedelta(days=serial);raw=date.isoformat(sep=' ') if date.time()!=dt.time() else date.date().isoformat()
                        except (ValueError,OverflowError) as exc:raise ValueError('Invalid XLSX date value') from exc
                if formula is not None and not raw:raw='[formula cached value unavailable]';warnings.append('formula_cached_value_missing')
                if raw.strip():cells.append(f'{ref}: {raw}')
            _row(doc,name,n,cells,sorted(set(warnings)))

def _ods(doc,pkg):
    root=pkg.xml('content.xml');body=root.find('o:body/o:spreadsheet',NS)
    if body is None:raise ValueError('ODS spreadsheet body missing')
    for sheet in body.findall('tb:table',NS):
        name=sheet.get(tag('tb','name'),'Sheet');row_number=1
        # Rows may be grouped or wrapped in header-rows.
        for row in sheet.iter(tag('tb','table-row')):
            repeat=_positive(row.get(tag('tb','number-rows-repeated'),'1'));cells=[];warnings=[];column=1
            for c in row:
                if c.tag not in (tag('tb','table-cell'),tag('tb','covered-table-cell')):continue
                count=_positive(c.get(tag('tb','number-columns-repeated'),'1'))
                paragraphs=c.findall('t:p',NS);pieces=[];size=0
                for paragraph in paragraphs:
                    value=_odf_text(paragraph);size+=len(value)+1
                    if size>MAX_TEXT_CHARS-doc.characters:raise ValueError('Extracted text limit exceeded')
                    pieces.append(value)
                value='\n'.join(pieces)
                if not value:
                    for key in ('date-value','time-value','boolean-value','value','string-value'):
                        if c.get(tag('o',key)) is not None:value=c.get(tag('o',key));break
                if c.get(tag('tb','formula')) is not None and not value:value='[formula cached value unavailable]';warnings.append('formula_cached_value_missing')
                if value.strip():
                    if count>MAX_UNITS:raise ValueError('Spreadsheet populated repeat limit exceeded')
                    if count*(len(value)+24)+sum(len(v)+24 for _,v in cells)>MAX_TEXT_CHARS-doc.characters:
                        raise ValueError('Extracted text limit exceeded')
                    for offset in range(count):cells.append((column+offset,value))
                column+=count
                if column>MAX_COORDINATE+1:raise ValueError('Spreadsheet column limit exceeded')
            if cells:
                if repeat>MAX_UNITS:raise ValueError('Source unit limit exceeded')
                for offset in range(repeat):
                    n=row_number+offset;_row(doc,name,n,[f'{_column(col)}{n}: {value}' for col,value in cells],sorted(set(warnings)))
            row_number+=repeat
            if row_number>MAX_COORDINATE+1:raise ValueError('Spreadsheet row limit exceeded')

def open_text_document(path):
    path=Path(path)
    if path.suffix.lower() not in NATIVE_EXTENSIONS:raise ValueError('Unsupported native text document format')
    if not path.is_file():raise ValueError('Text document source is unavailable')
    if path.stat().st_size>MAX_SOURCE_BYTES:raise ValueError('Source size limit exceeded (100 MiB)')
    doc=TextDocument(path)
    try:
        if doc.ext in ('.docx','.odt','.xlsx','.ods'):
            pkg=Package(path)
            try:{'.docx':_docx,'.odt':_odt,'.xlsx':_xlsx,'.ods':_ods}[doc.ext](doc,pkg)
            finally:pkg.close()
        else:
            text,warnings=_decode(path)
            if len(text)>MAX_TEXT_CHARS:raise ValueError('Extracted text limit exceeded (20 million characters)')
            if '\x00' in text:raise ValueError('Binary or unsupported text encoding; save as UTF-8')
            if doc.ext in ('.csv','.tsv'):_csv(doc,text,warnings)
            elif doc.ext in JSON_EXTENSIONS:_json(doc,text,warnings)
            elif doc.ext in ('.html','.htm'):
                parser=PassiveHTML();parser.feed(text);parser.close();parser.flush()
                title=''.join(parser.title).strip()
                if title:doc.metadata['title']=title
                _sections(doc,parser.records,warnings)
            else:_plain(doc,text,warnings)
    except (zipfile.BadZipFile,RuntimeError,KeyError,RecursionError) as exc:raise ValueError('Cannot extract this Office document: '+str(exc)) from exc
    return doc
