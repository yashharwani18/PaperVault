"""Isolated native text browser acceptance; never touches the personal library."""
import json
from pathlib import Path
import socket
import threading
import time
import uuid
import pymupdf
import uvicorn
from playwright.sync_api import sync_playwright,expect
from knowledge_library import server as module
from tests.test_text_document_api import Encoder,xlsx

ROOT=Path(__file__).resolve().parents[1]

def main():
    root=ROOT/'.cache/text-browser'/uuid.uuid4().hex;root.mkdir(parents=True)
    output=ROOT/'results/text-expansion';output.mkdir(exist_ok=True)
    module.EmbeddingGemma=Encoder
    app=module.create_app(root/'library',device='cpu');desktop=app.state.desktop
    with desktop.lib() as lib:
        folder=lib.create_folder('Text acceptance')['id']
        p=root/'Revenue.xlsx';p.write_bytes(xlsx());sheet=lib.import_document(p,folder)['document']
        p=root/'Notes.txt';p.write_text('Digital signal processing uses filters and convolution for discrete signals.');lib.import_document(p,folder)
        p=root/'Original.pdf'
        with pymupdf.open() as pdf:
            pdf.new_page().insert_text((45,65),'Impedance matching reduces reflections in a transmission line.');pdf.save(p)
        lib.import_pdf(p,folder)
        with lib.db:lib.db.execute("INSERT OR REPLACE INTO workspace_settings VALUES('computer_scan_choice','skip')")
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=port,log_level='error'))
    thread=threading.Thread(target=server.run,daemon=True);thread.start()
    report={'checks':[],'errors':[]};release=threading.Event()
    try:
        for _ in range(100):
            if server.started:break
            time.sleep(.1)
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True,executable_path='C:/Program Files/BraveSoftware/Brave-Browser/Application/brave.exe')
            page=browser.new_page(viewport={'width':1440,'height':1050});page.set_default_timeout(20000)
            page.on('pageerror',lambda e:report['errors'].append(str(e)))
            requests=[];page.on('request',lambda r:requests.append(r.url))
            page.goto(f'http://127.0.0.1:{port}')
            page.get_by_role('textbox',name='Search your files',exact=True).fill('Acme retained revenue')
            page.locator('.search-submit').click()
            card=page.locator('.result-card').filter(has_text='Revenue.xlsx').first
            expect(card.locator('.search-text-preview')).to_be_visible()
            card.locator('.result-title button').click()
            dialog=page.get_by_role('dialog',name='Document viewer: Revenue.xlsx')
            expect(dialog.get_by_role('heading',name='Revenue · Row 7',exact=True)).to_be_visible()
            expect(dialog.locator('.source-text')).to_contain_text('C7: 13600')
            assert not any(f'/documents/{sheet["id"]}/' in u and any(x in u for x in ('preview','tables','highlight','evidence')) for u in requests)
            page.screenshot(path=str(output/'spreadsheet-viewer.png'))
            page.set_viewport_size({'width':390,'height':844})
            page.screenshot(path=str(output/'spreadsheet-viewer-narrow.png'))
            overflow=page.evaluate("Array.from(document.querySelectorAll('.viewer-backdrop *')).filter(e=>e.getBoundingClientRect().right>innerWidth+1).map(e=>({tag:e.tagName,cls:e.className,width:e.getBoundingClientRect().width})).slice(0,15)")
            assert not overflow,overflow
            dialog.get_by_role('button',name='Close document viewer').click()
            report['checks'].append('Spreadsheet search opens original sheet/row text with no PDF-only requests, on desktop and narrow screen')
            page.set_viewport_size({'width':1440,'height':1050})
            page.get_by_role('textbox',name='Search your files',exact=True).fill('Impedance matching')
            page.locator('.search-submit').click()
            card=page.locator('.result-card').filter(has_text='Original.pdf').first
            expect(card.locator('.search-page-preview img')).to_be_visible()
            card.locator('.result-title button').click()
            expect(page.locator('.viewer-backdrop .pdfViewer canvas').first).to_be_visible()
            page.get_by_role('button',name='Close document viewer').click()
            report['checks'].append('PDF search still renders original page preview and PDF canvas')
            started=threading.Event()
            def occupy():started.set();release.wait(30)
            desktop.index_pool.submit(occupy);assert started.wait(2)
            source=root/'Skip queued.txt';source.write_text('This file should be skipped before indexing.')
            task=desktop.queue(folder,source,source.name)
            page.reload()
            page.locator('.indexing-pill').click()
            row=page.locator('.task-row').filter(has_text=source.name)
            row.get_by_role('button',name='Skip this file').click()
            expect(row.locator('.status')).to_have_text('skipped')
            expect(row.get_by_role('button',name='Retry',exact=True)).to_be_visible()
            page.screenshot(path=str(output/'skip-indexing.png'))
            release.set();desktop.futures[task].result(timeout=10)
            assert desktop.tasks([task])[0]['status']=='skipped'
            report['checks'].append('Per-file Skip button cancels queued work, leaves source intact and offers Retry')
            assert not report['errors'],report['errors']
            browser.close()
    finally:
        release.set();server.should_exit=True;thread.join(20)
        (output/'browser-report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2))

if __name__=='__main__':main()
