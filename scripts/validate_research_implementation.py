"""Real local API/OCR/Qwen and responsive browser check, synthetic documents only."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

import httpx
import psutil
import pymupdf
from playwright.sync_api import sync_playwright,expect

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from research.patent_candidate.measure_ocr_search_chain import make_scan


def main():
    root=ROOT/'.cache'/('implementation-browser-'+uuid.uuid4().hex)
    root.mkdir();shots=ROOT/'results/implementation-browser';shots.mkdir(exist_ok=True)
    report=dict(passed=False,synthetic_only=True,library=str(root),browser_errors=[],screenshots=[])
    log=(root/'server.log').open('w',encoding='utf-8')
    process=subprocess.Popen([sys.executable,'-u','-m','knowledge_library.server','--library',str(root/'library'),
        '--port','8773','--no-preload'],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,
        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    try:
        with httpx.Client(base_url='http://127.0.0.1:8773',timeout=60) as http:
            deadline=time.monotonic()+45
            while True:
                if process.poll() is not None:raise RuntimeError('Validation server stopped')
                try:
                    r=http.get('/api/state')
                    if r.status_code==200:break
                except httpx.HTTPError:pass
                if time.monotonic()>deadline:raise TimeoutError('Validation server unavailable')
                time.sleep(.2)
            http.headers['X-Library-Token']=r.json()['token']
            folder=http.post('/api/folders',json={'name':'Synthetic research checks'}).json()['id']
            scan=root/'current-right.pdf';make_scan(scan,current_right=True)
            paths=[scan]
            for name,value in [('exact','29000'),('nearby','29074')]:
                path=root/(name+'.pdf')
                with pymupdf.open() as doc:
                    doc.new_page().insert_text((40,60),f'SYNTHETIC INVOICE - TEST ONLY\nGrand Total: INR {value}')
                    doc.save(path)
                paths.append(path)
            files=[('files',(p.name,p.read_bytes(),'application/pdf')) for p in paths]
            uploaded=http.post('/api/uploads',data=dict(folder_id=folder,ocr='true',bill='true'),files=files)
            uploaded.raise_for_status();ids=uploaded.json()['task_ids'];deadline=time.monotonic()+100
            while True:
                tasks=http.post('/api/tasks/status',json={'ids':ids}).json()
                if all(t['status'] not in ('queued','running') for t in tasks):break
                if time.monotonic()>deadline:raise TimeoutError('Synthetic import did not finish')
                time.sleep(.2)
            assert all(t['status']=='completed' for t in tasks),tasks
            def search(query):
                r=http.post('/api/search',json=dict(query=query,folder_id=folder));r.raise_for_status();return r.json()
            result=search('total about 29000')
            assert len(result['results'])==3 and result['reliability']=='mixed_source_amounts',result
            scanned=next(h for h in result['results'] if h['filename']=='current-right.pdf')
            assert scanned['amount_match']['value']=='29074.00' and scanned['amount_match']['association']=='current_column'
            exact=search('total exactly 29000')
            assert [h['filename'] for h in exact['results']]==['exact.pdf']
            key=exact['results'][0]['document_id']
            saved=http.put(f'/api/documents/{key}/bill',json=dict(party='Synthetic Trading',bill_date='2026-09-25',
                amount='29000',currency='INR',source_page=1,reviewed=True,amount_reviewed=True))
            saved.raise_for_status()
            reviewed=search('total 29000')
            assert len(reviewed['results'])==1 and reviewed['results'][0]['amount_match']['verified']
            # Clear the review so the browser shows both tiers and their qualifications.
            http.put(f'/api/documents/{key}/bill',json=dict(party='Synthetic Trading',bill_date='2026-09-25',amount='29000',reviewed=False)).raise_for_status()
            os.environ['PLAYWRIGHT_BROWSERS_PATH']=str(ROOT/'.cache/playwright')
            with sync_playwright() as p:
                system_edge=Path('C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe')
                browser=p.chromium.launch(headless=True,**({'executable_path':str(system_edge)} if system_edge.is_file() else {}))
                page=browser.new_page(viewport=dict(width=1440,height=1000))
                page.on('pageerror',lambda e:report['browser_errors'].append(str(e)))
                page.goto('http://127.0.0.1:8773',wait_until='networkidle')
                page.get_by_role('textbox',name='Search your library',exact=True).fill('total about 29000')
                page.get_by_role('button',name='Run search',exact=True).click()
                expect(page.locator('.result-card')).to_have_count(3,timeout=60000)
                expect(page.locator('.similarity').filter(has_text='Exact text match')).to_be_visible()
                for width,height,name in [(1440,1000,'desktop'),(390,844,'mobile')]:
                    page.set_viewport_size(dict(width=width,height=height))
                    assert page.evaluate('document.documentElement.scrollWidth<=window.innerWidth')
                    target=shots/f'{name}.png';page.screenshot(path=str(target),full_page=True)
                    report['screenshots'].append(str(target))
                page.locator('.result-title button').first.click()
                expect(page.get_by_test_id('pdf-canvas')).to_be_visible(timeout=45000)
                assert page.get_by_test_id('pdf-page-text').inner_text().strip()
                browser.close()
            report.update(passed=not report['browser_errors'],imported_documents=3,ocr_current_total='29074.00',
                approximate_results=3,explicit_exact_results=1,reviewed_exact_results=1,
                qwen_method=result['response']['method'],source_viewer=True)
    finally:
        if process.poll() is None:
            parent=psutil.Process(process.pid)
            for child in reversed(parent.children(recursive=True)):
                try:child.terminate()
                except psutil.NoSuchProcess:pass
            try:parent.terminate()
            except psutil.NoSuchProcess:pass
            process.wait(timeout=10)
        log.close()
        (ROOT/'results/implementation-browser.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2));assert report['passed']


if __name__=='__main__':main()
