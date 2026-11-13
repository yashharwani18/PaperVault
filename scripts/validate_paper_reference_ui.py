"""Real Chromium check of references on a snapshot of the public-paper benchmark.

Does not open or modify the personal library. Run after the paper benchmark and
frontend build. The browser blocks non-loopback requests to verify offline use.
"""
from pathlib import Path
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
import uuid
from urllib.parse import urlsplit

import httpx
import psutil
from playwright.sync_api import sync_playwright, expect

ROOT=Path(__file__).resolve().parents[1]


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    source=ROOT/'.cache/research-paper-evaluation/library'
    root=ROOT/'.cache/research-reference-ui'/uuid.uuid4().hex
    root.mkdir(parents=True)
    out=ROOT/'results/research-paper-reference';out.mkdir(parents=True,exist_ok=True)
    with sqlite3.connect(source/'library.sqlite3') as src,sqlite3.connect(root/'library.sqlite3') as dst:src.backup(dst)
    shutil.copytree(source/'files',root/'files')
    report=dict(library=str(root),passed=False,browser_errors=[],external_requests=[],checks=[])
    log=(out/'server.log').open('w',encoding='utf-8')
    process=subprocess.Popen([sys.executable,'-u','-m','knowledge_library.server','--library',str(root),'--port','8774','--no-preload'],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    url='http://127.0.0.1:8774'
    try:
        with httpx.Client(base_url=url,timeout=15) as client:
            deadline=time.monotonic()+90
            while True:
                if process.poll() is not None:raise RuntimeError('QA server stopped; inspect server.log')
                try:
                    response=client.get('/api/state')
                    if response.status_code==200:break
                except httpx.HTTPError:pass
                if time.monotonic()>deadline:raise TimeoutError('QA server did not start')
                time.sleep(.25)
            state=response.json()
            with sync_playwright() as p:
                browser=p.chromium.launch(headless=True,executable_path=str(Path(os.environ['LOCALAPPDATA'])/'ms-playwright/chromium-1217/chrome-win64/chrome.exe'))
                context=browser.new_context(viewport={'width':1440,'height':1000},permissions=['clipboard-read','clipboard-write'],accept_downloads=True)
                def route(request):
                    if urlsplit(request.request.url).hostname not in ('127.0.0.1','localhost'):
                        report['external_requests'].append(request.request.url);request.abort()
                    else:request.continue_()
                context.route('**/*',route)
                page=context.new_page();page.on('pageerror',lambda e:report['browser_errors'].append(str(e)))
                page.goto(url,wait_until='networkidle')
                page.get_by_role('button',name='All files',exact=True).click()
                page.locator('.document-main').filter(has_text='Attention Is All You Need').click()
                panel=page.get_by_role('region',name='Document reference')
                # Section's aria-label is exposed as a region in the accessibility tree.
                panel=page.locator('.paper-reference')
                expect(panel.get_by_text('Paper reference',exact=True)).to_be_visible(timeout=30000)
                expect(panel.get_by_label('Formatted reference')).to_contain_text('Attention Is All You Need')
                report['checks'].append('Automatic paper detection and APA preview on a real PDF')
                panel.get_by_role('button',name='Copy',exact=True).click()
                expect(panel.get_by_role('status')).to_have_text('Reference copied.')
                assert 'Attention Is All You Need' in page.evaluate('navigator.clipboard.readText()')
                for style in ['ieee','mla','chicago','harvard','vancouver','bibtex','ris','json']:
                    panel.get_by_label('Reference format',exact=True).select_option(style)
                    expect(panel.get_by_label('Formatted reference')).not_to_be_empty()
                    assert not panel.locator('[role=alert]').count(),style
                report['checks'].append('All bundled formats render; clipboard contains actual reference')
                with page.expect_download() as download:
                    panel.get_by_role('button',name='Download',exact=True).click()
                assert download.value.suggested_filename=='reference.json'
                downloaded=json.loads(Path(download.value.path()).read_text(encoding='utf-8'))
                assert downloaded
                report['checks'].append('CSL-JSON download is valid JSON')
                panel.get_by_role('button',name='Edit details').click()
                panel.get_by_label('Title',exact=True).fill('Attention Is All You Need — checked')
                panel.get_by_label('Publication year',exact=True).fill('2017')
                panel.get_by_role('button',name='Save checked details').click()
                expect(panel.get_by_text('Reviewed',exact=True)).to_be_visible()
                expect(panel.get_by_label('Formatted reference')).to_contain_text('checked')
                panel.get_by_label('Reference format',exact=True).select_option('apa')
                panel.scroll_into_view_if_needed()
                page.screenshot(path=str(out/'reference-desktop.png'))
                page.reload(wait_until='networkidle')
                page.get_by_role('button',name='All files',exact=True).click()
                page.locator('.document-main').filter(has_text='Attention Is All You Need').click()
                panel=page.locator('.paper-reference')
                expect(panel.get_by_text('Reviewed',exact=True)).to_be_visible(timeout=30000)
                expect(panel.get_by_label('Formatted reference')).to_contain_text('checked')
                expect(panel.get_by_label('Reference format',exact=True)).to_have_value('apa')
                report['checks'].append('Edited metadata and selected style survive a reload')
                panel.get_by_label('Reference format',exact=True).select_option('custom')
                panel.get_by_label('Custom citation style').set_input_files(ROOT/'frontend/citation-styles/ieee.csl')
                expect(panel.get_by_label('Formatted reference')).to_contain_text('checked')
                assert not panel.locator('[role=alert]').count()
                report['checks'].append('Custom independent CSL file formats offline')
                page.set_viewport_size({'width':390,'height':844})
                panel.scroll_into_view_if_needed()
                page.screenshot(path=str(out/'reference-narrow.png'))
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                assert panel.evaluate('(e)=>e.scrollWidth<=e.clientWidth+1')
                report['checks'].append('Narrow viewport has no reference-panel horizontal overflow')
                browser.close()
        report['passed']=not report['browser_errors'] and not report['external_requests']
        assert report['passed'],report
    finally:
        if process.poll() is None:
            try:
                parent=psutil.Process(process.pid)
                for child in reversed(parent.children(recursive=True)):
                    try:child.terminate()
                    except psutil.NoSuchProcess:pass
                parent.terminate();process.wait(timeout=15)
            except psutil.NoSuchProcess:pass
        log.close()
        (out/'ui-report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        print(json.dumps(report,indent=2))


if __name__=='__main__':main()
