"""Synthetic browser checks; exercises the built UI, not device or indexing performance."""
from http.server import SimpleHTTPRequestHandler,ThreadingHTTPServer
from threading import Thread
from pathlib import Path
import json
import re
from playwright.sync_api import sync_playwright,expect

ROOT=Path(__file__).resolve().parents[1]
DOCS=[dict(id=f'd{i}',filename=f'Lecture {i}.pdf',title=f'Lecture {i}',folder_id='f',folder_name='Classes',sha256=f'h{i}',page_count=1,chunk_count=1,status='indexed',created_at='2026-01-01T00:00:00Z',updated_at='2026-01-02T00:00:00Z',size_bytes=i+1) for i in range(2000)]
DOCS[0].update(filename='Lecture 0.txt',source_kind='text',preview_kind='text',source_format='txt')
DOCS.extend([dict(DOCS[0],id='dup1',filename='Shared.pdf',title='Shared',folder_name='Classes'),dict(DOCS[1],id='dup2',filename='Shared.pdf',title='Shared',folder_name='Other')])
STATE=dict(folders=[dict(id='f',name='Classes',color='#A78BFA',document_count=2002,updated_at='2026-01-01')],documents=DOCS,tasks=[],stats=dict(documents=len(DOCS),pages=len(DOCS),database_bytes=0,embedding_runtime=dict(model_loads=0)),bills=[],aliases=[],trash=[],token='test',ocr_available=False,powerpoint_available=False,linked_folders=[],library_page=dict(sorts=['added_new','added_old','name','name_desc','size_large','size_small','type'],filters=['folder','extension','status','added','size','favorites','recent','name'],candidates=True))
def natural(name):
 return [(1,len(token.lstrip('0') or '0'),token.lstrip('0') or '0') if token.isdigit() else (0,token) for token in re.findall(r'\d+|\D+',name.casefold())]
shrunk=False
def library_page(body):
 """Mirror the SQLite page semantics for the synthetic catalog."""
 global shrunk
 docs=[d for d in DOCS if (not body.get('folder_id') or d['folder_id']==body['folder_id'])
  and (not body.get('extension') or d['filename'].lower().endswith('.'+body['extension']))
  and (body.get('status','all')=='all' or (d['status']=='indexed')==(body['status']=='indexed'))
  and (not body.get('min_size') or d['size_bytes']>=body['min_size']) and (not body.get('max_size') or d['size_bytes']<=body['max_size'])]
 name=body.get('name','').casefold()
 if name:docs=[d for d in docs if name in (d['title']+' '+d['filename']).casefold()]
 offset,limit=body.get('offset',0),body.get('limit',100)
 # Simulates a library that shrank after the saved page moved past the end.
 if body.get('sort')=='added_new' and offset>0:shrunk=True
 if shrunk and body.get('sort')=='added_new':docs=docs[:5]
 ordered=sorted(docs,key=lambda d:(natural(d['filename']),d['id']))
 letters=[];seen=set()
 for position,doc in enumerate(ordered):
  letter=doc['filename'].strip()[:1].upper()
  letter=letter if 'A'<=letter<='Z' else '#'
  if letter not in seen:seen.add(letter);letters.append(dict(letter=letter,offset=position))
 types=sorted({d['filename'].rsplit('.',1)[-1].lower() for d in docs if '.' in d['filename']})
 sort=body.get('sort')
 docs=sorted(docs,key=lambda d:d['id'])
 if sort=='added_new':docs.sort(key=lambda d:d.get('created_at') or '',reverse=True)
 elif sort=='added_old':docs.sort(key=lambda d:d.get('created_at') or '')
 elif sort=='size_large':docs.sort(key=lambda d:d['size_bytes'],reverse=True)
 elif sort=='size_small':docs.sort(key=lambda d:d['size_bytes'])
 elif sort=='name':docs=ordered
 elif sort=='name_desc':docs=list(reversed(ordered))
 elif sort=='type':docs=sorted(ordered,key=lambda d:d['filename'].rsplit('.',1)[-1].lower() if '.' in d['filename'] else '')
 return dict(documents=docs[offset:offset+limit],total=len(docs),offset=offset,limit=limit,letters=letters,types=types)
class Handler(SimpleHTTPRequestHandler):
 def __init__(self,*args,**kwargs):super().__init__(*args,directory=str(ROOT/'frontend/dist'),**kwargs)
 def log_message(self,*args):pass
server=ThreadingHTTPServer(('127.0.0.1',0),Handler);Thread(target=server.serve_forever,daemon=True).start()
seen=[];payloads=[];requests=[];preferences=dict(saved=False,sort="added_new",search_history=[])
def api(route):
 request=route.request;path=request.url.split('/api/',1)[1].split('?',1)[0];seen.append(path);requests.append((request.method,path))
 if request.method in ('POST','PATCH'):payloads.append((path,json.loads(request.post_data or '{}')))
 if path=='state':body={**STATE,'documents':STATE['documents'] if 'include_documents=false' not in request.url else None}
 elif path=='reading-state':body=dict(documents={},recent_ids=[])
 elif path=='library-preferences':
  if request.method=='PATCH':preferences.update(json.loads(request.post_data or '{}'));preferences['saved']=True
  body=preferences
 elif path=='library-page':body=library_page(json.loads(request.post_data or '{}'))
 elif path=='computer-scan':body=dict(choice='yes',drives=[])
 elif path=='filename-matches':
  payload=json.loads(request.post_data or '{}');q=payload.get('query','').strip().lower();ids=payload.get('document_ids');name=(payload.get('library_filters') or {}).get('name','').casefold()
  matches=[d for d in DOCS if d['filename'].lower().removesuffix('.pdf')==q.removesuffix('.pdf') and (ids is None or d['id'] in ids) and (not name or name in (d['title']+' '+d['filename']).casefold())]
  body=dict(matches=[dict(document_id=d['id'],filename=d['filename'],folder_id=d['folder_id'],folder=d['folder_name'],available=True) for d in matches])
 elif path.endswith('/reading-state'):body=dict(favorite=False,page=1,last_opened='2026-01-01T00:00:00Z',sha256='h0')
 elif path=='documents/d0':body=dict(document=DOCS[0],pages=[dict(page_number=1,unit_number=1)],original=None)
 elif path=='documents/d0/units/1':body=dict(page_number=1,unit_number=1,text='The zephyr switch controls the fan.',warnings=[])
 elif path=='search':
  submitted=json.loads(request.post_data or '{}');q=submitted.get('query','')
  hits=[] if q!='zephyr switch' else [dict(chunk_id=1,document_id='d0',filename='Lecture 0.txt',folder='Classes',folder_id='f',page_number=1,page_label='1',passage='zephyr switch',score=1,score_type='exact_text',source_identity='d0:h0:1:0:1',source_sha256='h0',extraction_method='text',preview_kind='text',source_kind='text',unit_number=1)]
  body=dict(query=q,mode='semantic',results=hits,elapsed_s=0,reliability='uncalibrated_candidates',empty_reason=None if hits else 'no_candidates',closest_available=False,below_cutoff=False)
 else:body={}
 route.fulfill(status=200,content_type='application/json',body=json.dumps(body))
try:
 with sync_playwright() as p:
  browser=p.chromium.launch(executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe',headless=True,args=['--disable-gpu'])
  page=browser.new_page(viewport={'width':1280,'height':850});errors=[];page.on('pageerror',lambda error:errors.append(str(error.stack)));page.route('**/api/**',api)
  page.goto(f'http://127.0.0.1:{server.server_port}/',wait_until='networkidle')
  page.screenshot(path=str(ROOT/'.cache/library-ui-initial.png'),full_page=True)
  page.get_by_role('button',name='All files',exact=True).click(timeout=5000)
  expect(page.locator('.document-row')).to_have_count(100)
  page.get_by_label('Sort documents').select_option('name')
  assert page.locator('.document-main strong').nth(0).inner_text()=='Lecture 0'
  assert page.locator('.document-main strong').nth(2).inner_text()=='Lecture 2'
  expect(page.get_by_label('Document pages',exact=True)).to_contain_text('Showing 1–100 of 2002')
  page.get_by_label('Document pages',exact=True).get_by_role('button',name='Next',exact=True).click();expect(page.get_by_label('Document pages',exact=True)).to_contain_text('Showing 101–200')
  page.get_by_role('button',name='Jump to S',exact=True).click();assert page.locator('.document-main strong').last.inner_text()=='Shared'
  page.screenshot(path=str(ROOT/'.cache/library-ui-list-desktop.png'),full_page=True)
  page.get_by_label('Search your files').fill('Shared');page.get_by_role('button',name='Search',exact=True).click()
  expect(page.get_by_role('region',name='Exact document matches')).to_contain_text('Choose the file you want to open')
  assert page.get_by_role('region',name='Exact document matches').get_by_role('button',name='Open',exact=True).count()==2
  assert 'search' not in seen
  page.get_by_label('Search your files').fill('Lecture 22')
  page.get_by_role('button',name='Search',exact=True).click()
  expect(page.get_by_role('dialog',name='Document viewer: Lecture 22.pdf')).to_be_visible()
  assert 'search' not in seen
  page.get_by_role('button',name='Close document viewer').click()
  page.get_by_label('Search your files').fill('Shared')
  page.get_by_role('button',name='Search',exact=True).click()
  expect(page.get_by_role('region',name='Exact document matches')).to_be_visible()
  page.screenshot(path=str(ROOT/'.cache/library-ui-desktop.png'),full_page=True)
  page.get_by_role('button',name='Search document contents too').click()
  expect(page.get_by_role('region',name='Exact document matches')).to_be_visible()
  expect(page.get_by_role('heading',name='No additional content matches')).to_be_visible()
  page.get_by_role('region',name='Exact document matches').get_by_role('button',name='Back to library').click()
  page.get_by_label('Search your files').fill('zephyr switch')
  page.get_by_role('button',name='Search',exact=True).click()
  page.get_by_role('button',name='Open Section 1').click()
  text_viewer=page.get_by_role('dialog',name='Document viewer: Lecture 0.txt')
  expect(text_viewer.locator('mark')).to_have_text('zephyr switch')
  text_viewer.get_by_role('button',name='Close document viewer').click()
  page.get_by_role('button',name='Back to library',exact=True).click()
  page.get_by_label('Filter documents by name').fill('Lecture 1999')
  page.get_by_label('Search your files').fill('Shared')
  page.get_by_role('button',name='Search',exact=True).click()
  expect(page.get_by_role('heading',name='No strong source match found')).to_be_visible()
  sent=[body for path,body in payloads if path=='search'][-1]
  assert sent['library_filters']['name']=='Lecture 1999' and sent['document_ids'] is None,sent
  page.get_by_role('button',name='Back to library',exact=True).click()
  page.get_by_label('Select document Lecture 1999.pdf').check()
  page.get_by_role('button',name='Remove selected',exact=True).click()
  dialog=page.get_by_role('dialog',name='Remove selected documents?')
  expect(dialog).to_contain_text('Original files are not deleted')
  dialog.get_by_role('button',name='Remove selected',exact=True).click()
  expect(page.get_by_role('button',name='Undo',exact=True)).to_be_visible()
  assert ('DELETE','documents/d1999') in requests
  page.get_by_role('button',name='Undo',exact=True).click()
  expect(page.get_by_text('Documents restored',exact=True)).to_be_visible()
  assert ('POST','trash/d1999/restore') in requests
  page.get_by_role('button',name='All files',exact=True).click()
  page.get_by_label('Sort documents').select_option('added_new')
  expect(page.locator('.document-row')).to_have_count(100)
  expect(page.get_by_label('Document pages',exact=True)).to_contain_text('Showing 1–100 of 2002')
  assert [page.locator('.document-main strong').nth(i).inner_text() for i in range(3)]==['Lecture 0','Lecture 1','Lecture 10']
  first_request=[body for path,body in payloads if path=='library-page'][-1]
  assert first_request['sort']=='added_new' and first_request['offset']==0 and first_request['limit']==100,first_request
  page.get_by_label('Document pages',exact=True).get_by_role('button',name='Next',exact=True).click()
  # The mock shrinks the library once offset 100 is requested, so the UI must
  # clamp the saved page and show rows matching the clamped page.
  expect(page.locator('.document-row')).to_have_count(5)
  assert page.get_by_label('Document pages',exact=True).count()==0
  assert any(body.get('offset')==100 for path,body in payloads if path=='library-page')
  assert [body for path,body in payloads if path=='library-page'][-1]['offset']==0
  page.get_by_label('Sort documents').select_option('name')
  page.wait_for_timeout(700)
  assert preferences['sort']=='name' and 'Shared' in preferences['search_history'],preferences
  reopened=browser.new_page(viewport={'width':1280,'height':850});reopened.route('**/api/**',api)
  reopened.goto(f'http://localhost:{server.server_port}/',wait_until='networkidle')
  expect(reopened.get_by_role('region',name='Recent searches')).to_contain_text('Shared')
  reopened.get_by_role('button',name='Clear history').click();reopened.wait_for_timeout(700)
  assert preferences['search_history']==[]
  reopened.get_by_role('button',name='All files',exact=True).click()
  assert reopened.get_by_label('Sort documents').input_value()=='name'


  mobile=browser.new_page(viewport={'width':390,'height':844},device_scale_factor=1);mobile.route('**/api/**',api)
  mobile.goto(f'http://127.0.0.1:{server.server_port}/',wait_until='networkidle')
  mobile.get_by_role('button',name='Documents',exact=True).click()
  expect(mobile.locator('.document-row')).to_have_count(100)
  mobile.screenshot(path=str(ROOT/'.cache/library-ui-mobile.png'),full_page=False)
  assert mobile.evaluate('document.documentElement.scrollWidth <= innerWidth')
  assert not errors,errors
  browser.close()
 print('PASS: synthetic 2,002-document desktop paging, natural sort, alphabet jump and duplicate filename selection; narrow viewport overflow check.')
finally:server.shutdown();server.server_close()
