"""Accept a running native test window over its opt-in test-only CDP port."""
import json
from pathlib import Path
import sys

import httpx
import psutil
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]


def main():
    native = ROOT / '.cache/native-window-test/native'
    ready = json.loads(next(native.glob('session-*.json')).read_text())
    backend = psutil.Process(ready['pid'])
    assert Path(backend.exe()).resolve() == (ROOT / 'output/Local-Library-Desktop/runtime/pythonw.exe').resolve()
    sources = ROOT / '.cache/native-test-pdfs'
    sources.mkdir(exist_ok=True)
    fixture = sources / 'Lecture notes.pdf'
    fixture.write_bytes((ROOT / 'tests/fixtures/pdfs/native-unicode.pdf').read_bytes())
    report = dict(passed=False, backend_executable=backend.exe(), checks=[], browser_errors=[], external_requests=[])
    screenshots = ROOT / 'results/standalone-qa'
    screenshots.mkdir(exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp('http://127.0.0.1:9238')
        page = next(page for context in browser.contexts for page in context.pages if page.url.startswith(ready['url']))
        page.on('pageerror', lambda e: report['browser_errors'].append(str(e)))
        page.on('request', lambda r: report['external_requests'].append(r.url) if not r.url.startswith(ready['url']) else None)
        page.get_by_role('button', name='Library home', exact=True).click()
        expect(page.get_by_role('heading', name='My Library', exact=True)).to_be_visible()
        report['checks'].append('Native executable owns its bundled pythonw backend; existing interface loads in WebView2')
        page.get_by_role('navigation', name='PC library settings').get_by_role('button', name='Connected folders').click()
        if not page.locator('.source-row').count():
            page.get_by_label('Folder to connect', exact=True).fill(str(sources))
            page.get_by_role('button', name='Connect folder', exact=True).click()
        expect(page.locator('.source-counts')).to_contain_text('1 indexed', timeout=150000)
        report['checks'].append('Bundled encoder indexes discovered PDFs without a browser upload')
        page.screenshot(path=str(screenshots / 'connected-folders.png'), full_page=True)
        page.get_by_role('button', name='My library').click()
        page.get_by_label('Search your library', exact=True).fill('How can I prove a language is not regular?')
        page.get_by_role('button', name='Run search', exact=True).click()
        expect(page.get_by_role('heading', name='Search results')).to_be_visible(timeout=120000)
        expect(page.locator('.response-source').first).to_contain_text('Page 2')
        page.screenshot(path=str(screenshots / 'search.png'), full_page=True)
        report['checks'].append('Bundled embedding model and Qwen answer generation retrieve the correct physical page 2')
        page.locator('.response-source button').first.click()
        expect(page.get_by_test_id('pdf-canvas')).to_have_attribute('data-pdf-page', '2', timeout=45000)
        report['checks'].append('Embedded source viewer renders the matching PDF page')
        page.screenshot(path=str(screenshots / 'source-page.png'), full_page=True)
        page.get_by_role('button', name='Close document viewer').click()
        with httpx.Client(base_url=ready['url'], timeout=10) as http:
            assert http.post('/api/desktop/shutdown').status_code == 403
            assert http.post('/api/desktop/shutdown', headers={'X-Library-Token': ready['token'], 'Origin': 'https://example.com'}).status_code == 403
        report['checks'].append('Native shutdown endpoint rejects missing tokens and cross-origin requests')
        report['passed'] = not report['browser_errors'] and not report['external_requests']
        browser.close()
    (ROOT / 'results/standalone-acceptance.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))
    assert report['passed']


if __name__ == '__main__':
    main()
