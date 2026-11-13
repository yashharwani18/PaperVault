"""Khoj search-first UI acceptance with generated documents and real embeddings."""
import json
from pathlib import Path
import socket
import threading
import time
import uuid
import pymupdf
import uvicorn
from playwright.sync_api import sync_playwright,expect
from knowledge_library.server import create_app
from knowledge_library.workspace_features import assign_subjects

ROOT=Path(__file__).resolve().parents[1]


def main():
    root=ROOT/'.cache/khoj-ui'/uuid.uuid4().hex;root.mkdir(parents=True)
    output=ROOT/'results/khoj-ui';output.mkdir(exist_ok=True)
    app=create_app(root/'library','cuda',preload=False)
    with app.state.desktop.lib() as lib:
        folder=lib.create_folder('Study notes')['id']
        source=root/'Private signal notes.pdf'
        with pymupdf.open() as pdf:
            pdf.new_page().insert_text((45,65),'Digital signal processing uses filters and convolution to study discrete signals. PRIVATE_DIAGNOSTIC_SENTINEL')
            pdf.new_page().insert_text((45,65),'A transmission line carries electromagnetic waves. Impedance matching reduces reflections.');pdf.save(source)
        doc=lib.import_pdf(source,folder,retain_source=False)['document'];assign_subjects(lib,doc['id'])
        with lib.db:lib.db.execute("INSERT OR REPLACE INTO workspace_settings VALUES('computer_scan_choice','skip')")
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=port,log_level='error'))
    thread=threading.Thread(target=server.run);thread.start()
    report={'checks':[],'errors':[]}
    try:
        for _ in range(100):
            if server.started:break
            time.sleep(.1)
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True,executable_path='C:/Program Files/BraveSoftware/Brave-Browser/Application/brave.exe')
            page=browser.new_page(viewport={'width':1440,'height':1050},accept_downloads=True);page.set_default_timeout(60000)
            page.on('pageerror',lambda e:report['errors'].append(str(e)))
            page.goto(f'http://127.0.0.1:{port}')
            expect(page.get_by_role('heading',name='Search your files',exact=True)).to_be_visible()
            expect(page.get_by_role('button',name='Khoj home',exact=True)).to_be_visible()
            expect(page.get_by_role('button',name='AI model settings',exact=True)).to_have_count(0)
            page.screenshot(path=str(output/'desktop-home.png'))
            page.set_viewport_size({'width':390,'height':844});page.screenshot(path=str(output/'narrow-home.png'))
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            page.get_by_role('textbox',name='Search your files',exact=True).fill('signal processing')
            page.locator('.search-submit').click()
            expect(page.locator('.search-page-preview img').first).to_be_visible()
            expect(page.locator('.similarity').first).not_to_be_visible()
            expect(page.get_by_text('Matched passage highlighted',exact=True).first).to_be_visible()
            page.set_viewport_size({'width':1440,'height':1050});page.screenshot(path=str(output/'desktop-results.png'))
            page.set_viewport_size({'width':390,'height':844});page.screenshot(path=str(output/'narrow-results.png'))
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            report['checks'].append('Search and highlighted original pages lead; scores stay hidden on desktop and narrow screens')
            page.set_viewport_size({'width':1440,'height':1050})
            page.get_by_role('button',name='Settings',exact=True).click()
            expect(page.get_by_role('button',name='AI model settings',exact=True)).not_to_be_visible()
            page.get_by_text('Get a support report',exact=True).click()
            with page.expect_download() as event:page.get_by_role('button',name='Save support report',exact=True).click()
            download=event.value;data=json.loads(Path(download.path()).read_text())
            assert data['product']['name']=='Khoj' and data['product']['version']=='0.5.0'
            content=json.dumps(data)
            assert all(value not in content for value in ['PRIVATE_DIAGNOSTIC_SENTINEL','Private signal notes.pdf',str(root),'signal processing'])
            page.screenshot(path=str(output/'desktop-settings.png'))
            page.set_viewport_size({'width':390,'height':844});page.screenshot(path=str(output/'narrow-settings.png'))
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            page.get_by_text('Advanced settings',exact=True).click()
            expect(page.get_by_role('button',name='AI model settings',exact=True)).to_be_visible()
            report['checks'].append('Advanced controls are closed by default; support download excludes generated document contents, names, paths and search')
            browser.close()
        assert not report['errors'],report
        (ROOT/'results/khoj-ui-validation.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
    finally:server.should_exit=True;thread.join(timeout=30)


if __name__=='__main__':main()
