"""Read-only interaction checks against the native WebView2 test session."""
import json
import re
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]


def main():
    ready = json.loads(max((ROOT / 'data/pc-prototype/native').glob('session-*.json'), key=lambda p:p.stat().st_mtime).read_text())
    output = ROOT / 'results/simplified-ui'
    output.mkdir(exist_ok=True)
    report = {'errors': [], 'checks': []}
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp('http://127.0.0.1:9238')
        page = next(p for c in browser.contexts for p in c.pages if p.url.startswith(ready['url']))
        page.on('pageerror', lambda e: report['errors'].append(str(e)))
        page.set_viewport_size({'width':1280,'height':850})
        page.get_by_role('button', name='Library home', exact=True).click()
        expect(page.get_by_role('heading', name='My Library', exact=True)).to_be_visible()
        expect(page.get_by_role('navigation', name='Main navigation').get_by_role('button')).to_have_count(3)
        expect(page.get_by_role('region', name='Scan progress')).to_contain_text('Scan paused', timeout=15000)
        expect(page.get_by_role('heading', name='Topics', exact=True)).to_be_visible()
        expect(page.get_by_role('button', name='AI models', exact=True)).not_to_be_visible()
        expect(page.locator('.search-hint')).to_have_count(0)
        page.screenshot(path=str(output / 'desktop.png'), full_page=True)
        report['checks'].append('Home shows search, compact folders/topics, and live paused-scan status; three main navigation choices')
        page.locator('.topic-list').get_by_role('button', name='DSP 13', exact=True).click()
        expect(page.get_by_role('heading', name='DSP', exact=True)).to_be_visible()
        expect(page.locator('.document-row')).to_have_count(13)
        report['checks'].append('DSP topic opens its 13 documents')
        page.get_by_role('navigation', name='Main navigation').get_by_role('button', name='Scan & folders', exact=True).click()
        expect(page.locator('.source-row')).to_have_count(1)
        expect(page.get_by_label('Folder to connect', exact=True)).not_to_be_visible()
        expect(page.get_by_role('button', name='Resume discovery', exact=True)).to_be_visible()
        page.locator('.source-options > summary').first.click()
        expect(page.get_by_role('button', name='Scan now', exact=True)).to_be_visible()
        expect(page.get_by_role('button', name='Disconnect', exact=True)).to_be_visible()
        page.locator('.source-options > summary').first.click()
        page.locator('.connect-disclosure > summary').click()
        expect(page.get_by_label('Folder to connect', exact=True)).to_be_visible()
        page.locator('.connect-disclosure > summary').click()
        page.screenshot(path=str(output / 'scan.png'), full_page=True)
        report['checks'].append('Scan counts and resume stay visible; folder setup and advanced source actions expand on demand')
        page.locator('.sidebar-settings > summary').click()
        page.get_by_role('button', name='AI models', exact=True).click()
        expect(page.get_by_role('heading', name='AI models', exact=True)).to_be_visible()
        page.get_by_role('button', name='Backup & storage', exact=True).click()
        expect(page.get_by_role('heading', name='Backup & storage', exact=True)).to_be_visible()
        report['checks'].append('Settings retains AI models and backup navigation')
        page.get_by_role('button', name='Library home', exact=True).click()
        search = page.get_by_label('Search your library', exact=True)
        search.fill('digital signal processing')
        page.get_by_role('button', name='Run search', exact=True).click()
        expect(page.get_by_role('heading', name=re.compile(r'^Search results'))).to_be_visible(timeout=120000)
        expect(page.locator('.response-source,.result-card').first).to_be_visible(timeout=120000)
        report['checks'].append('Semantic search still returns cited PDF sources')
        page.get_by_role('button', name='Library home', exact=True).click()
        page.set_viewport_size({'width':390,'height':844})
        expect(page.get_by_role('navigation', name='Mobile navigation')).to_be_visible()
        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'), 'Mobile layout overflows'
        page.screenshot(path=str(output / 'mobile.png'), full_page=True)
        page.get_by_role('button', name='More navigation', exact=True).click()
        expect(page.get_by_role('dialog', name='Library navigation')).to_be_visible()
        page.get_by_role('button', name='Close library navigation', exact=True).click()
        expect(page.get_by_role('dialog', name='Library navigation')).not_to_be_visible()
        report['checks'].append('Narrow layout has no horizontal overflow; More navigation opens and closes')
        page.set_viewport_size({'width':1280,'height':850})
        assert not report['errors'], report
        browser.close()
    (ROOT / 'results/simplified-ui-validation.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
