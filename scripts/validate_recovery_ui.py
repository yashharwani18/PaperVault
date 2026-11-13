"""Recovery acceptance with generated originals and an isolated library."""
import json
from pathlib import Path
import socket
import threading
import time
import uuid
import httpx
import pymupdf
import uvicorn
from playwright.sync_api import sync_playwright,expect
from knowledge_library.server import create_app
from knowledge_library.library import Library
from tests.test_research_implementation import CountingEncoder

ROOT=Path(__file__).resolve().parents[1]


def main():
    root=ROOT/'.cache/recovery-ui'/uuid.uuid4().hex;root.mkdir(parents=True)
    output=ROOT/'results/recovery-ui';output.mkdir(exist_ok=True)
    with Library(root,CountingEncoder()) as lib:
        folder=lib.create_folder('Recovery fixtures')['id']
        source=root/'Moved original.pdf'
        with pymupdf.open() as pdf:
            pdf.new_page().insert_text((40,60),'Digital signal processing source evidence.');pdf.save(source)
        doc=lib.import_pdf(source,folder,retain_source=False)['document']
        moved=root/'Found original.pdf';source.rename(moved)
        blank=root/'Scanned notes.pdf'
        with pymupdf.open() as pdf:pdf.new_page();pdf.save(blank)
        lib.import_pdf(blank,folder,retain_source=False)
    app=create_app(root,'cpu')
    with app.state.desktop.lib() as lib,lib.db:
        lib.db.execute("INSERT INTO app_tasks(id,folder_id,source,filename,ocr,status,created_at,error) VALUES('missing-task',?,?,?,0,'failed','2026-10-24','FileNotFoundError: Original disappeared')",(folder,str(root/'Lost upload.pdf'),'Lost upload.pdf'))
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=port,log_level='error'))
    thread=threading.Thread(target=server.run);thread.start()
    url=f'http://127.0.0.1:{port}'
    report={'checks':[],'errors':[]}
    try:
        for _ in range(100):
            if server.started:break
            time.sleep(.1)
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True,executable_path='C:/Program Files/BraveSoftware/Brave-Browser/Application/brave.exe')
            page=browser.new_page(viewport={'width':1440,'height':1050});page.on('pageerror',lambda e:report['errors'].append(str(e)))
            page.goto(url)
            # Fixture libraries must never start whole-computer scans.
            skip=page.get_by_role('button',name='Not now',exact=True)
            if skip.is_visible():skip.click()
            page.get_by_role('button',name='All documents',exact=True).click()
            page.get_by_role('button',name='Manage document Moved original.pdf',exact=True).click()
            page.get_by_role('button',name='Fix source or extraction',exact=True).click()
            dialog=page.get_by_role('dialog',name='Fix source or extraction',exact=True)
            expect(dialog.get_by_text('The original PDF was moved',exact=False)).to_be_visible()
            page.screenshot(path=str(output/'desktop-missing.png'))
            page.set_viewport_size({'width':390,'height':844});page.screenshot(path=str(output/'narrow-missing.png'))
            dialog.get_by_role('textbox',name='Locate the same PDF').fill(str(moved))
            dialog.get_by_role('button',name='Reconnect original',exact=True).click()
            expect(dialog.get_by_text('Original reconnected.',exact=False)).to_be_visible()
            expect(dialog.get_by_text('The matching original PDF is available.',exact=True)).to_be_visible()
            report['checks'].append('Missing original explained and matching PDF reconnected without copying')
            page.keyboard.press('Escape');expect(dialog).to_have_count(0)
            page.set_viewport_size({'width':1440,'height':1050})
            page.get_by_role('button',name='Fix extraction for Scanned notes.pdf',exact=True).click()
            dialog=page.get_by_role('dialog',name='Fix source or extraction',exact=True)
            expect(dialog.get_by_text('Text extraction needs attention',exact=True)).to_be_visible()
            expect(dialog.get_by_role('button',name='Retry extraction',exact=True)).to_be_visible()
            page.screenshot(path=str(output/'desktop-extraction.png'))
            report['checks'].append('Empty/extraction status exposes an immediate repair action')
            page.keyboard.press('Escape');expect(dialog).to_have_count(0)
            page.get_by_role('button',name='Some files need attention',exact=False).click()
            expect(page.get_by_text('Reconnect its drive or restore it',exact=False)).to_be_visible()
            page.get_by_role('button',name='Retry indexing',exact=True).click()
            expect(page.get_by_role('alert').filter(has_text='source is still unavailable')).to_be_visible()
            page.screenshot(path=str(output/'desktop-task-error.png'))
            report['checks'].append('Failed job gives plain explanation and keeps failed retry feedback beside the action')
            browser.close()
        assert not report['errors'],report
        (ROOT/'results/recovery-ui-validation.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
    finally:
        server.should_exit=True;thread.join(timeout=30)


if __name__=='__main__':main()
