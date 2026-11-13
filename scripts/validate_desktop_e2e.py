"""Real Chromium flows against an isolated persistent library and real CUDA inference.

Only the explicitly marked invoice/reliability fixtures are synthetic. The TOC
and DSP documents are actual MIT PDFs. All browser requests are loopback-only.
"""
from contextlib import contextmanager
import datetime as dt
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import traceback
import uuid
from urllib.parse import urlsplit
import httpx
import psutil
import pymupdf
from playwright.sync_api import sync_playwright,expect
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tests.test_embedding_model import write_json
from knowledge_library.library import Library


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    os.environ['PLAYWRIGHT_BROWSERS_PATH']=str(ROOT/'.cache/playwright')
    run=dt.datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:4]
    root=ROOT/'data/e2e'/run;shots=ROOT/'results/e2e-qa'/run;shots.mkdir(parents=True)
    url='http://127.0.0.1:8769'
    report=dict(status='running',library=str(root),screenshots=str(shots),steps=[],browser_errors=[],external_requests=[],server_starts=[])
    output=ROOT/'results/phase6-e2e.json';process=None;log=None;page=None
    http=httpx.Client(base_url=url,timeout=15)
    @contextmanager
    def step(name):
        t=time.perf_counter()
        try:yield
        except Exception:
            if page:
                try:page.screenshot(path=str(shots/'failure.png'),full_page=True)
                except Exception:pass
            report['steps'].append(dict(name=name,passed=False,elapsed_s=time.perf_counter()-t));raise
        else:
            report['steps'].append(dict(name=name,passed=True,elapsed_s=time.perf_counter()-t));print('PASS '+name,flush=True)
        finally:write_json(output,report)
    def start():
        nonlocal process,log
        log=(shots/f'server-{len(report["server_starts"])+1}.log').open('w',encoding='utf-8')
        process=subprocess.Popen([sys.executable,'-u','-m','knowledge_library.server','--library',str(root),'--port','8769'],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        report['server_starts'].append(dict(launcher_pid=process.pid,at=dt.datetime.now(dt.timezone.utc).isoformat()))
        deadline=time.monotonic()+45
        while time.monotonic()<deadline:
            if process.poll() is not None:raise RuntimeError('Server stopped during startup; inspect '+str(log.name))
            try:
                response=http.get('/api/state')
                if response.status_code==200:return
            except httpx.HTTPError:pass
            time.sleep(.2)
        raise RuntimeError('Local server not ready in 45 seconds')
    def stop():
        nonlocal process,log
        if process and process.poll() is None:
            # The venv launcher spawns the real interpreter on Windows. Terminate
            # only this Popen-owned process tree, leaving other app processes alone.
            parent=psutil.Process(process.pid)
            for child in reversed(parent.children(recursive=True)):
                try:child.terminate()
                except psutil.NoSuchProcess:pass
            try:parent.terminate()
            except psutil.NoSuchProcess:pass
            process.wait(timeout=15)
        if log:log.close()
        process=None;log=None
    def state():return http.get('/api/state').json()
    def api(path,body=None,method='POST'):
        return http.request(method,'/api'+path,json=body,headers={'X-Library-Token':state()['token']})
    def mainnav(name):return page.get_by_role('navigation',name='Main navigation').get_by_role('button',name=name)
    def folder(name):return next(f for f in state()['folders'] if f['name']==name)
    def create_folder(name):
        page.locator('.heading-actions').get_by_role('button',name='New folder',exact=True).click()
        dialog=page.get_by_role('dialog',name='A home for your ideas');dialog.get_by_label('Folder name',exact=True).fill(name)
        dialog.get_by_role('button',name='Create folder',exact=True).click();expect(dialog).not_to_be_visible();return folder(name)
    def wait_jobs(ids):
        deadline=time.monotonic()+180
        while time.monotonic()<deadline:
            jobs={t['id']:t for t in state()['tasks']}
            if all(jobs[i]['status'] not in ('queued','running') for i in ids):return [jobs[i] for i in ids]
            time.sleep(.2)
        raise AssertionError('Indexing tasks exceeded 180 seconds')
    def upload_ui(collection,paths,ocr=False,replace=None):
        before={t['id'] for t in state()['tasks']}
        if replace:
            page.get_by_role('button',name='Manage document '+replace['filename'],exact=True).click()
            page.get_by_role('button',name='Replace PDF',exact=True).click()
        else:page.locator('.heading-actions').get_by_role('button',name='Add documents',exact=True).click()
        dialog=page.get_by_role('dialog',name='Replace document' if replace else 'Add to your library')
        if not replace:dialog.get_by_label('Upload collection').select_option(collection)
        dialog.get_by_label('Choose documents').set_input_files([str(p) for p in paths])
        if ocr:dialog.get_by_role('checkbox',name=re.compile('Use OCR')).check()
        with page.expect_response(lambda r:r.url.endswith('/api/uploads') and r.request.method=='POST') as submitted:
            dialog.get_by_role('button',name='Replace & index' if replace else 'Add documents',exact=True).click()
        expect(dialog.get_by_role('button',name='Done',exact=True)).to_be_visible(timeout=20000)
        dialog.get_by_role('button',name='Done',exact=True).click()
        expect(dialog).not_to_be_visible(timeout=20000)
        ids=submitted.value.json()['task_ids']
        assert len(ids)==len(paths)
        jobs=wait_jobs(ids)
        page.reload(wait_until='networkidle')
        return jobs
    def run_search(query,bills=False):
        locator=page.get_by_role('textbox',name='Search bills' if bills else 'Search this folder' if page.get_by_role('textbox',name='Search this folder').count() else 'Search your library',exact=True)
        locator.fill(query)
        with page.expect_response(lambda r:r.url.endswith('/api/search') and r.request.method=='POST',timeout=90000) as response:
            page.get_by_role('button',name='Run search',exact=True).click()
        result=response.value.json()
        expect(page.locator('.search-loading')).not_to_be_visible(timeout=90000)
        return result
    def clear_search():page.get_by_role('button',name='Clear search',exact=True).click()
    try:
        start()
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True)
            def context():
                ctx=browser.new_context(viewport={'width':1440,'height':1000},device_scale_factor=1,accept_downloads=True,service_workers='block')
                def route(route):
                    if urlsplit(route.request.url).hostname not in ('127.0.0.1','localhost'):
                        report['external_requests'].append(route.request.url);route.abort()
                    else:route.continue_()
                ctx.route('**/*',route)
                return ctx
            ctx=context();page=ctx.new_page();page.on('pageerror',lambda e:report['browser_errors'].append(str(e)));page.goto(url,wait_until='networkidle')
            with step('A — create folders and bulk-upload three real MIT PDFs'):
                toc=create_folder('TOC');dsp=create_folder('DSP');projects=create_folder('Projects');bills_folder=create_folder('Bills');empty=create_folder('Empty')
                jobs=upload_ui(toc['id'],[ROOT/f'corpus/pdfs/{i}.pdf' for i in ['mit-dfa-nfa','mit-pumping-lemma','mit-nfa-regex']])
                assert all(t['status']=='completed' for t in jobs),jobs
                assert folder('TOC')['document_count']==3
                upload_ui(dsp['id'],[ROOT/'corpus/pdfs/mit-fourier.pdf'])
            with step('A/D — restart the app and use a fresh browser context with external requests blocked'):
                prior={d['id'] for d in state()['documents']};ctx.close();stop();start();ctx=context();page=ctx.new_page();page.on('pageerror',lambda e:report['browser_errors'].append(str(e)));page.goto(url,wait_until='networkidle')
                assert {d['id'] for d in state()['documents']}==prior and folder('TOC')['document_count']==3
            with step('B — semantic retrieval and actual PDF navigation to the matching page'):
                page.get_by_role('button',name='Open folder TOC',exact=True).click()
                result=run_search('How can I prove a language is not regular?')
                assert result['results'] and all(h['folder_id']==toc['id'] for h in result['results'])
                hit=next(h for h in result['results'] if h['filename']=='mit-pumping-lemma.pdf')
                card=page.locator('.result-card').filter(has=page.locator('.result-bottom',has_text=hit['filename'])).first
                card.get_by_role('button',name=f"Open at page {hit['page_number']}",exact=True).click()
                expect(page.locator(f'[data-testid="pdf-canvas"][data-pdf-page="{hit["page_number"]}"]')).to_be_visible(timeout=45000)
                assert page.locator('.matched-context p').inner_text()==hit['passage']
                assert 'regular' in page.get_by_test_id('pdf-page-text').inner_text().casefold()
                page.screenshot(path=str(shots/'matching-pdf-page.png'))
                report['page_navigation']=dict(filename=hit['filename'],physical_page=hit['page_number'],passage=hit['passage'])
                page.get_by_role('button',name='Close document viewer').click()
            with step('C — folder isolation and global search across both real collections'):
                scoped=run_search('Which rule turns convolution in time into multiplication of frequency spectra?')
                assert all(h['folder_id']==toc['id'] for h in scoped['results'])
                mainnav('My library').click()
                global_result=run_search('Which rule turns convolution in time into multiplication of frequency spectra?')
                assert any(h['folder_id']==dsp['id'] for h in global_result['results'])
                mainnav('My library').click();global_toc=run_search('Where is the pumping lemma explained?')
                assert any(h['folder_id']==toc['id'] for h in global_toc['results'])
            with step('D — unrelated-query rejection and empty-folder no-inference behavior'):
                rejected=run_search('Find my confirmed flight booking to Osaka next week.')
                assert rejected['results']==[] and rejected['reliability']=='no_confident_match'
                expect(page.get_by_role('button',name='Show closest passages anyway')).to_be_visible()
                mainnav('My library').click();page.get_by_role('button',name='Open folder Empty',exact=True).click()
                before=state()['stats']['embedding_runtime'];result=run_search('Anything')
                assert not result['results'] and result['empty_reason']=='empty_scope' and before==state()['stats']['embedding_runtime']
            with step('Bills — upload native and scanned synthetic invoices through the UI'):
                mainnav('Bills & invoices').click()
                jobs=upload_ui(bills_folder['id'],[ROOT/f'tests/fixtures/bills/{name}.pdf' for name in ['sale-bhagwanti-2026-09-25','purchase-bhagwanti-2026-09-25','scanned-sale-bhagwanti']],ocr=True)
                assert all(t['status']=='completed' for t in jobs)
                assert len(state()['bills'])==3
                mainnav('Bills & invoices').click()
            with step('Bills — exact party/date/sale matching, with no neural inference'):
                before=state()['stats']['embedding_runtime']
                result=run_search('What did I sell to Bhagwanti Trading on Sept 25 2026?',bills=True)
                assert result['mode']=='bill_fields' and len(result['results'])==2
                assert all(h['bill']['direction']=='sale' and h['bill']['bill_date']=='2026-09-25' for h in result['results'])
                assert before==state()['stats']['embedding_runtime']
                page.screenshot(path=str(shots/'bill-party-date-search.png'),full_page=True)
                report['bill_example']=dict(query=result['query'],matched_sale_bills=len(result['results']),physical_pages=[h['page_number'] for h in result['results']],synthetic_fixtures=True)
                wrong=run_search('sold to Bhagwanti Trading on Sept 26 2026',bills=True)
                assert not wrong['results'];clear_search()
            with step('Bills — review source-linked extracted details and filter the bill list'):
                doc=next(d for d in state()['documents'] if d['filename']=='sale-bhagwanti-2026-09-25.pdf')
                page.get_by_role('button',name='Review bill '+doc['filename'],exact=True).click()
                dialog=page.get_by_role('dialog',name='Review bill details')
                expect(dialog.get_by_label('Bill party',exact=True)).to_have_value('Bhagwanti Trading');expect(dialog.get_by_label('Bill date',exact=True)).to_have_value('2026-09-25')
                expect(dialog.locator('canvas')).to_be_visible(timeout=30000)
                expect(dialog.locator('.evidence-box').first).to_be_visible(timeout=10000)
                page.screenshot(path=str(shots/'bill-evidence-review.png'),full_page=False)
                dialog.get_by_role('checkbox',name=re.compile('I checked these details')).check();dialog.get_by_role('button',name='Save bill details',exact=True).click();expect(dialog).not_to_be_visible()
                assert next(b for b in state()['bills'] if b['document_id']==doc['id'])['reviewed']==1
                page.get_by_label('Filter bill type').select_option('sale');expect(page.locator('.document-row')).to_have_count(2)
                page.get_by_label('Filter bills by date').fill('2026-09-26');expect(page.locator('.document-row')).to_have_count(0)
                page.get_by_role('button',name='Clear filters').click();expect(page.locator('.document-row')).to_have_count(3)
            with step('Upgrade — aliases, date ranges, item matching and explicit local feedback'):
                assert api('/party-aliases',{'alias':'BT','party':'Bhagwanti Trading'},method='PUT').status_code==200
                result=run_search('all sales to BT in September 2026',bills=True)
                assert result['bill_matches']==2
                result=run_search('Which bill contained A4 paper?',bills=True)
                assert result['bill_matches']==3
                page.locator('.feedback-panel summary').click()
                page.get_by_label('Search feedback outcome').select_option('useful')
                page.get_by_label('Search feedback note').fill('Synthetic browser test: source invoice found')
                page.get_by_role('button',name='Save feedback locally',exact=True).click()
                expect(page.get_by_role('status')).to_contain_text('Feedback saved')
                assert api('/feedback',method='GET').json()[0]['kind']=='useful'
                clear_search()
                page.get_by_label('Filter bills by party').fill('BT')
                page.get_by_label('Filter bills by date').fill('2026-09-01')
                page.get_by_label('Filter bills end date').fill('2026-09-30')
                page.get_by_label('Filter bill type').select_option('sale')
                page.get_by_role('button',name='Search with filters',exact=True).click()
                expect(page.locator('.result-card')).to_have_count(2)
                page.screenshot(path=str(shots/'bill-range-alias-results.png'),full_page=True)
                clear_search();page.get_by_role('button',name='Clear filters').click()
            with step('Export — source-only PDF downloaded from selected browser results'):
                result=run_search('sold to Bhagwanti Trading on Sept 25 2026',bills=True)
                page.get_by_role('checkbox',name='Select passage 1').check()
                with page.expect_download(timeout=30000) as download:page.get_by_role('button',name='Export context',exact=True).click()
                exported=shots/'context.pdf';download.value.save_as(exported)
                with pymupdf.open(exported) as pdf:
                    text=' '.join(p.get_text() for p in pdf)
                    assert result['query'] in text and 'PDF page 1' in text and 'SYNTHETIC' in text
                report['context_pdf']=str(exported)
                clear_search()
            with step('E — PDF replacement invalidates reviewed bill fields and removes old search matches'):
                doc=next(d for d in state()['documents'] if d['filename']=='sale-bhagwanti-2026-09-25.pdf')
                upload_ui(bills_folder['id'],[ROOT/'tests/fixtures/bills/sale-asha-2026-09-25.pdf'],replace=doc)
                mainnav('Bills & invoices').click()
                changed=next(b for b in state()['bills'] if b['document_id']==doc['id']);assert changed['party']=='Asha Stationers' and changed['reviewed']==0
                result=run_search('sold to Bhagwanti Trading on Sept 25 2026',bills=True);assert len(result['results'])==1 and result['results'][0]['filename']=='scanned-sale-bhagwanti.pdf';clear_search()
                scan=next(d for d in state()['documents'] if d['filename']=='scanned-sale-bhagwanti.pdf')
                page.get_by_role('button',name='Manage document '+scan['filename'],exact=True).click();page.get_by_role('button',name='Remove from library',exact=True).click()
                page.get_by_role('dialog',name='Remove document?').get_by_role('button',name='Remove document',exact=True).click()
                expect(page.get_by_role('dialog')).not_to_be_visible()
                assert not run_search('sold to Bhagwanti Trading on Sept 25 2026',bills=True)['results'];clear_search()
            with step('Organization — move documents, rename/color a folder, delete an empty folder'):
                doc=next(d for d in state()['documents'] if d['filename']=='sale-asha-2026-09-25.pdf')
                page.get_by_role('button',name='Manage document '+doc['filename'],exact=True).click();page.get_by_role('button',name='Move to folder',exact=True).click()
                dialog=page.get_by_role('dialog',name='Move document');dialog.get_by_label('Destination folder').select_option(projects['id']);dialog.get_by_role('button',name='Move document',exact=True).click();expect(dialog).not_to_be_visible()
                assert next(d for d in state()['documents'] if d['id']==doc['id'])['folder_id']==projects['id']
                mainnav('My library').click();page.get_by_role('button',name='Manage folder Projects',exact=True).click();page.get_by_role('button',name='Rename & color').click()
                dialog=page.get_by_role('dialog',name='Edit folder');dialog.get_by_label('Folder name').fill('Project archive');dialog.get_by_role('button',name='Choose color #54C8A4').click();dialog.get_by_role('button',name='Save changes').click();expect(dialog).not_to_be_visible()
                assert folder('Project archive')['color']=='#54C8A4'
                page.get_by_role('button',name='Manage folder Empty',exact=True).click();page.get_by_role('button',name='Delete folder',exact=True).click();page.get_by_role('dialog',name='Delete folder?').get_by_role('button',name='Delete folder',exact=True).click();expect(page.get_by_role('dialog')).not_to_be_visible()
                assert not any(f['name']=='Empty' for f in state()['folders'])
            with step('F — malformed, encrypted, empty, and scanned-without-OCR files report explicit statuses'):
                jobs=upload_ui(projects['id'],[ROOT/f'tests/fixtures/pdfs/{name}.pdf' for name in ['malformed','encrypted','empty','scanned']])
                assert [j['status'] for j in jobs]==['failed','failed','completed','completed']
                assert jobs[2]['result']['document']['status']=='empty' and jobs[3]['result']['document']['status']=='needs_ocr'
            with step('F — actual process interruption during indexing, persisted recovery, and retry'):
                before_count=len(state()['documents']);before_ids={t['id'] for t in state()['tasks']}
                with (ROOT/'corpus/pdfs/think-python.pdf').open('rb') as stream:
                    response=http.post('/api/uploads',data={'folder_id':projects['id']},files={'files':('think-python.pdf',stream,'application/pdf')},headers={'X-Library-Token':state()['token']});assert response.status_code==200
                interrupted_id=response.json()['task_ids'][0]
                deadline=time.monotonic()+30
                while time.monotonic()<deadline:
                    task=next(t for t in state()['tasks'] if t['id']==interrupted_id)
                    if task['status']=='running' and task['progress']:break
                    time.sleep(.05)
                else:raise AssertionError('No actual in-progress page observed before interruption')
                stop();start();recovered=next(t for t in state()['tasks'] if t['id']==interrupted_id)
                assert recovered['status']=='interrupted' and len(state()['documents'])==before_count
                retry=api('/tasks/'+interrupted_id+'/retry');assert retry.status_code==200
                retried=wait_jobs([retry.json()['task_id']]);assert retried[0]['status']=='completed'
                assert len(state()['documents'])==before_count+1
                report['actual_interruption']=dict(task_id=interrupted_id,observed_page=task['progress'],recovered_status=recovered['status'],retry_status=retried[0]['status'])
            with step('PowerPoint — direct slide upload, visible completion, Done, and matching slide navigation'):
                page.reload(wait_until='networkidle');mainnav('My library').click()
                college=create_folder('College slides')
                page.locator('.heading-actions').get_by_role('button',name='Add documents',exact=True).click()
                dialog=page.get_by_role('dialog',name='Add to your library');dialog.get_by_label('Upload collection').select_option(college['id'])
                dialog.get_by_label('Choose documents').set_input_files(str(ROOT/'tests/fixtures/presentations/college-toc-test.pptx'))
                expect(dialog.get_by_text('1 file selected',exact=True)).to_be_visible()
                with page.expect_response(lambda r:r.url.endswith('/api/uploads') and r.request.method=='POST') as submitted:
                    dialog.get_by_role('button',name='Add documents',exact=True).click()
                expect(dialog.get_by_role('button',name='Done',exact=True)).to_be_visible()
                jobs=wait_jobs(submitted.value.json()['task_ids']);assert jobs[0]['status']=='completed',jobs
                expect(dialog.get_by_role('heading',name='Your documents are ready')).to_be_visible(timeout=15000)
                page.screenshot(path=str(shots/'powerpoint-upload-done.png'),full_page=False)
                dialog.get_by_role('button',name='Done',exact=True).click();expect(dialog).not_to_be_visible()
                page.get_by_role('button',name='Open folder College slides',exact=True).click()
                result=run_search('How can I prove a language is not regular using the pumping lemma?')
                assert result['results'][0]['page_number']==3 and result['results'][0]['filename'].endswith('.pptx')
                page.get_by_role('button',name='Open at page 3',exact=True).first.click()
                expect(page.locator('[data-testid="pdf-canvas"][data-pdf-page="3"]')).to_be_visible(timeout=30000)
                expect(page.get_by_test_id('pdf-page-text')).to_contain_text('Pumping lemma')
                page.screenshot(path=str(shots/'powerpoint-matching-slide.png'),full_page=False)
                page.get_by_role('button',name='Close document viewer').click()
            with step('Upgrade — browser trash recovery, backup download, safe restore, and storage controls'):
                page.reload(wait_until='networkidle')
                page.get_by_role('button',name='Backup & storage',exact=True).click()
                expect(page.get_by_role('heading',name='Backup & storage',exact=True)).to_be_visible()
                expect(page.get_by_role('heading',name='Recover deleted documents')).to_be_visible()
                count=len(state()['documents']);calls=dict(state()['stats']['embedding_runtime'])
                page.get_by_role('button',name='Restore',exact=True).first.click()
                expect(page.locator('.maintenance-row').filter(has=page.get_by_role('button',name='Restore',exact=True))).to_have_count(0)
                assert len(state()['documents'])==count+1 and state()['stats']['embedding_runtime']==calls
                with page.expect_download(timeout=45000) as download:page.get_by_role('button',name='Download backup ZIP',exact=True).click()
                backup=shots/'library-backup.zip';download.value.save_as(backup)
                import zipfile
                with zipfile.ZipFile(backup) as archive:assert archive.testzip() is None and 'manifest.json' in archive.namelist()
                page.get_by_label('Restore backup ZIP').set_input_files(str(backup))
                expect(page.get_by_role('status')).to_contain_text('Verified restore:',timeout=60000)
                assert len(state()['documents'])==count+1
                page.screenshot(path=str(shots/'backup-and-storage.png'),full_page=True)
                page.set_viewport_size({'width':390,'height':844})
                assert page.evaluate('document.documentElement.scrollWidth<=window.innerWidth')
                page.screenshot(path=str(shots/'mobile-storage.png'),full_page=True)
                page.set_viewport_size({'width':1440,'height':1000})
                mainnav('My library').click()
            with step('Final integrity, responsive layout, and zero external browser requests'):
                page.reload(wait_until='networkidle');page.screenshot(path=str(shots/'final-library.png'),full_page=True)
                page.set_viewport_size({'width':390,'height':844});page.evaluate('window.scrollTo(0,0)');page.screenshot(path=str(shots/'mobile-library.png'),full_page=True)
                assert page.evaluate('document.documentElement.scrollWidth<=window.innerWidth')
                with Library(root) as lib:
                    report['integrity']=lib.verify();assert report['integrity']['passed']
                assert not report['browser_errors'] and not report['external_requests'],report
            report['offline']=dict(server_process_external_connections_blocked=True,browser_external_requests_blocked=True,physical_adapters_disconnected=False)
            report['status']='passed';browser.close()
    except Exception:
        report['status']='failed';report['error']=traceback.format_exc();print(report['error'],flush=True)
        if page:
            try:page.screenshot(path=str(shots/'failure.png'),full_page=True)
            except Exception:pass
    finally:
        stop();http.close();write_json(output,report)
    return 0 if report['status']=='passed' else 1


if __name__=='__main__':raise SystemExit(main())
