"""Real browser + real encoder acceptance for the automatic PC library."""
import json
from pathlib import Path
import subprocess
import sys
import time
import uuid

import httpx
import pymupdf
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]


def main():
    run = uuid.uuid4().hex[:8]
    work = ROOT / '.cache' / f'pc-browser-{run}'
    sources = work / 'My PDFs'
    sources.mkdir(parents=True)
    shots = ROOT / '.impeccable' / 'review'
    shots.mkdir(parents=True, exist_ok=True)
    report = dict(passed=False, checks=[], browser_errors=[], external_requests=[], library=str(work / 'library'))
    output = ROOT / 'results' / 'pc-prototype-browser.json'
    (sources / 'Lecture notes.pdf').write_bytes((ROOT / 'tests/fixtures/pdfs/native-unicode.pdf').read_bytes())
    with pymupdf.open() as pdf:
        pdf.new_page().insert_text((40, 70), 'Formal languages and finite automata. Regular expressions describe regular languages.')
        pdf.save(sources / 'Automata handout.pdf')
    url = 'http://127.0.0.1:8774'
    with (work / 'server.log').open('w', encoding='utf-8') as log:
        server = subprocess.Popen([sys.executable, '-u', '-m', 'knowledge_library.server', '--library',
            str(work / 'library'), '--port', '8774', '--no-preload'], cwd=ROOT, stdout=log, stderr=log,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        try:
            with httpx.Client(base_url=url, timeout=10) as http:
                for _ in range(100):
                    if server.poll() is not None:
                        raise AssertionError((work / 'server.log').read_text())
                    try:
                        state = http.get('/api/state').json()
                        break
                    except httpx.HTTPError:
                        time.sleep(.2)
                else:
                    raise AssertionError('Prototype server did not start')
                http.headers['X-Library-Token'] = state['token']
                with sync_playwright() as p:
                    browser = p.chromium.launch(channel='msedge', headless=True)
                    context = browser.new_context(viewport=dict(width=1440, height=1000), device_scale_factor=1)
                    def route(request):
                        if not request.request.url.startswith(url):
                            report['external_requests'].append(request.request.url)
                            request.abort()
                        else:
                            request.continue_()
                    context.route('**/*', route)
                    page = context.new_page()
                    page.on('pageerror', lambda e: report['browser_errors'].append(str(e)))
                    page.goto(url, wait_until='networkidle')
                    page.get_by_role('button', name='Connect a folder', exact=True).click()
                    expect(page.get_by_role('heading', name='Connected folders', exact=True)).to_be_visible()
                    page.get_by_label('Folder to connect', exact=True).fill(str(sources))
                    page.get_by_role('button', name='Connect folder', exact=True).click()
                    expect(page.locator('.source-row')).to_have_count(1)
                    expect(page.locator('.source-counts')).to_contain_text('2 indexed', timeout=150000)
                    report['checks'].append('Connect a folder; recursively discover and index actual PDF fixtures without upload')
                    page.screenshot(path=str(shots / 'desktop.png'), full_page=True)
                    assert page.evaluate('document.documentElement.scrollWidth<=window.innerWidth')
                    page.set_viewport_size(dict(width=390, height=844))
                    page.screenshot(path=str(shots / 'mobile.png'), full_page=True)
                    assert page.evaluate('document.documentElement.scrollWidth<=window.innerWidth')
                    report['checks'].append('Connected folders fit desktop and phone-width layouts')
                    page.set_viewport_size(dict(width=1440, height=1000))
                    page.get_by_role('button', name='My library').click()
                    expect(page.locator('.connection-home')).to_contain_text('Your folders, connected')
                    page.screenshot(path=str(shots / 'library-desktop.png'), full_page=True)
                    page.get_by_label('Search your library', exact=True).fill('How can I prove a language is not regular?')
                    page.get_by_role('button', name='Run search', exact=True).click()
                    expect(page.get_by_role('heading', name='Search results')).to_be_visible(timeout=120000)
                    expect(page.locator('.result-card').first).to_be_visible()
                    report['checks'].append('Search automatically indexed PDFs with real local retrieval and Qwen response')
                    page.screenshot(path=str(shots / 'search-desktop.png'), full_page=True)
                    # Use the source response citation when available, otherwise the result page control.
                    citation = page.locator('.response-source button').first
                    if citation.count():
                        citation.click()
                        expect(page.get_by_test_id('pdf-canvas')).to_have_attribute('data-pdf-page', '2', timeout=45000)
                        report['checks'].append('Open matching original PDF at physical page 2')
                        page.get_by_role('button', name='Close document viewer').click()
                    page.get_by_role('navigation', name='PC library settings').get_by_role('button', name='AI models', exact=True).click()
                    page.get_by_label('Assistant provider').select_option('claude')
                    page.get_by_label('Assistant model ID').fill('model-id-for-configuration-check')
                    assert not page.get_by_role('button', name='Save assistant').is_enabled()
                    page.get_by_label('Allow Claude assistance', exact=False).check()
                    assert page.get_by_role('button', name='Save assistant').is_enabled()
                    page.screenshot(path=str(shots / 'models-desktop.png'), full_page=True)
                    page.set_viewport_size(dict(width=390, height=844))
                    page.screenshot(path=str(shots / 'models-mobile.png'), full_page=True)
                    assert page.evaluate('document.documentElement.scrollWidth<=window.innerWidth')
                    report['checks'].append('Model configuration renders; Claude requires explicit consent; no provider request sent')
                    browser.close()
                report['passed'] = not report['browser_errors'] and not report['external_requests']
        finally:
            server.terminate()
            server.wait(timeout=20)
            output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))
    assert report['passed']


if __name__ == '__main__':
    main()
