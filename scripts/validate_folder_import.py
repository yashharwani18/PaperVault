"""Real browser directory selection, recursive filtering and resumable batches."""
from pathlib import Path
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
import traceback
import httpx
import psutil
from playwright.sync_api import sync_playwright,expect
ROOT=Path(__file__).resolve().parents[1]


def main():
    os.environ['PLAYWRIGHT_BROWSERS_PATH']=str(ROOT/'.cache/playwright')
    run=dt.datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:4]
    root=ROOT/'data/folder-e2e'/run;shots=ROOT/'results/folder-e2e'/run;shots.mkdir(parents=True)
    folder=ROOT/'.cache/folder-picker-tests'/run/'CollegeImport';(folder/'Week2').mkdir(parents=True)
    pdf=ROOT/'tests/fixtures/pdfs/native-unicode.pdf'
    shutil.copyfile(pdf,folder/'Notes.pdf')
    shutil.copyfile(ROOT/'tests/fixtures/presentations/college-toc-test.pptx',folder/'Slides.pptx')
    for i in range(120):shutil.copyfile(pdf,folder/'Week2'/f'notes-{i:03d}.pdf')
    (folder/'readme.txt').write_text('Ignored document');(folder/'photo.png').write_bytes(b'Ignored image');(folder/'~$Slides.pptx').write_bytes(b'Ignored temporary Office file')
    url='http://127.0.0.1:8773';report=dict(status='running',library=str(root),screenshots=str(shots),errors=[],external_requests=[],accepted_batch_sizes=[],requests=0,
        fixture_scope='122 file selections: 121 byte-identical PDF copies plus one real PPTX fixture. This verifies batching/dedup/progress, not distinct-document scale.')
    log=(shots/'server.log').open('w',encoding='utf-8');process=None
    try:
        process=subprocess.Popen([sys.executable,'-u','-m','knowledge_library.server','--library',str(root),'--port','8773'],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        with httpx.Client(base_url=url,timeout=20) as client:
            deadline=time.monotonic()+45
            while time.monotonic()<deadline:
                try:
                    state=client.get('/api/state').json();break
                except Exception:time.sleep(.2)
            else:raise AssertionError('Server startup timed out')
            token={'X-Library-Token':state['token']}
            collection=client.post('/api/folders',json={'name':'College documents'},headers=token).json()['id']
            with sync_playwright() as playwright:
                browser=playwright.chromium.launch(headless=True)
                context=browser.new_context(viewport={'width':1440,'height':1000})
                def network(route):
                    if route.request.url.startswith(url+'/'):route.continue_()
                    else:report['external_requests'].append(route.request.url);route.abort()
                context.route('**/*',network)
                page=context.new_page();page.on('pageerror',lambda e:report['errors'].append(str(e)))
                def uploads(route):
                    report['requests']+=1
                    count=len(re.findall(rb'filename="',route.request.post_data_buffer or b''))
                    if report['requests']==2:route.fulfill(status=503,content_type='application/json',body=json.dumps({'detail':'Deliberate second-batch test failure'}))
                    else:report['accepted_batch_sizes'].append(count);route.continue_()
                page.route('**/api/uploads',uploads)
                page.goto(url,wait_until='networkidle')
                page.get_by_role('button',name='Add documents',exact=True).first.click()
                dialog=page.get_by_role('dialog',name='Add to your library')
                dialog.get_by_label('Upload collection').select_option(collection)
                dialog.get_by_label('Choose document folder').set_input_files(str(folder))
                expect(dialog.get_by_text('122 files selected',exact=True)).to_be_visible()
                expect(dialog.locator('.folder-scan-summary')).to_contain_text('3 other or temporary files skipped')
                expect(dialog.locator('.file-picks')).to_contain_text('CollegeImport/Week2/notes-000.pdf')
                dialog.get_by_role('checkbox',name='Include subfolders',exact=True).uncheck()
                expect(dialog.get_by_text('2 files selected',exact=True)).to_be_visible()
                dialog.get_by_role('checkbox',name='Include subfolders',exact=True).check()
                expect(dialog.get_by_text('122 files selected',exact=True)).to_be_visible()
                expect(dialog.get_by_role('button',name='Add documents',exact=True)).to_be_in_viewport()
                page.screenshot(path=str(shots/'folder-review.png'),full_page=False)
                dialog.get_by_role('button',name='Add documents',exact=True).click()
                expect(dialog.get_by_role('button',name='Retry remaining files')).to_be_visible(timeout=30000)
                expect(dialog.get_by_text('Some files still need uploading',exact=True)).to_be_visible()
                expect(dialog.locator('.form-error')).to_contain_text('92 files have not been confirmed uploaded')
                page.screenshot(path=str(shots/'partial-batch-retry.png'),full_page=False)
                dialog.get_by_role('button',name='Retry remaining files').click()
                expect(dialog.get_by_role('heading',name='Your documents are ready')).to_be_visible(timeout=180000)
                expect(dialog.get_by_text('122 of 122 uploaded - 122 indexed.',exact=False)).to_be_visible()
                page.screenshot(path=str(shots/'folder-import-done.png'),full_page=False)
                jobs=client.get('/api/state').json()['tasks'];assert len(jobs)==100
                assert report['accepted_batch_sizes']==[30,30,30,30,2],report
                assert report['requests']==6
                dialog.get_by_role('button',name='Done',exact=True).click();expect(dialog).not_to_be_visible()
                state=client.get('/api/state').json();assert len(state['documents'])==2,state['documents']
                assert any(d['filename']=='Slides.pptx' and d['page_count']==3 for d in state['documents'])
                report['documents_after_dedup']=len(state['documents']);report['files_imported']=122
                # All jobs complete even though the generic activity window is 100.
                report['all_122_jobs_shown_complete']=True
                page.set_viewport_size({'width':390,'height':844})
                page.get_by_role('button',name='Add documents',exact=True).first.click()
                dialog=page.get_by_role('dialog',name='Add to your library')
                expect(dialog.get_by_role('button',name='Choose folder',exact=True)).to_be_visible()
                assert page.evaluate('document.documentElement.scrollWidth<=window.innerWidth')
                page.screenshot(path=str(shots/'mobile-folder-picker.png'),full_page=False)
                assert not report['errors'] and not report['external_requests']
                report['status']='passed';browser.close()
    except Exception:
        report['status']='failed';report['error']=traceback.format_exc();print(report['error'])
        try:page.screenshot(path=str(shots/'failure.png'),full_page=True)
        except Exception:pass
    finally:
        if process and process.poll() is None:
            parent=psutil.Process(process.pid)
            for child in reversed(parent.children(recursive=True)):
                try:child.terminate()
                except psutil.NoSuchProcess:pass
            parent.terminate();process.wait(timeout=15)
        log.close();(ROOT/'results/folder-import-e2e.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
    return 0 if report['status']=='passed' else 1


if __name__=='__main__':raise SystemExit(main())
