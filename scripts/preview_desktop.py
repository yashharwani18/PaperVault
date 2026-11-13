"""Read-only browser QA of the real seeded library and embedded source viewer."""
import json
import os
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright,expect
ROOT=Path(__file__).resolve().parents[1]
os.environ['PLAYWRIGHT_BROWSERS_PATH']=str(ROOT/'.cache/playwright')


def main():
    out=ROOT/'results/desktop-qa';out.mkdir(exist_ok=True)
    errors=[];external=[]
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True)
        context=browser.new_context(viewport={'width':1440,'height':1100},device_scale_factor=1)
        def route(request):
            if urlsplit(request.request.url).hostname not in ('127.0.0.1','localhost'):
                external.append(request.request.url);request.abort()
            else:request.continue_()
        context.route('**/*',route)
        page=context.new_page();page.on('pageerror',lambda e:errors.append(str(e)))
        page.goto('http://127.0.0.1:8767',wait_until='networkidle')
        expect(page.get_by_role('heading',name='My Library',exact=True)).to_be_visible()
        page.screenshot(path=str(out/'library-desktop.png'),full_page=True)
        page.get_by_role('navigation',name='Main navigation').get_by_role('button',name='Bills & invoices').click()
        expect(page.get_by_role('heading',name='Bills & invoices',exact=True)).to_be_visible()
        page.screenshot(path=str(out/'bills-empty.png'),full_page=True)
        page.get_by_role('button',name='My library').click()
        page.locator('.document-main').first.click()
        expect(page.locator('[data-testid="pdf-canvas"][data-pdf-page="1"]')).to_be_visible(timeout=45000)
        page.screenshot(path=str(out/'source-viewer.png'),full_page=False)
        assert page.get_by_test_id('pdf-page-text').inner_text().strip()
        page.get_by_role('button',name='Next page',exact=True).click()
        expect(page.locator('[data-testid="pdf-canvas"][data-pdf-page="2"]')).to_be_visible(timeout=30000)
        page.get_by_role('button',name='Close document viewer').click()
        page.set_viewport_size({'width':390,'height':844});page.evaluate('window.scrollTo(0,0)')
        page.screenshot(path=str(out/'library-mobile.png'),full_page=True)
        assert page.evaluate('document.documentElement.scrollWidth<=window.innerWidth')
        browser.close()
    result=dict(passed=not errors and not external,browser_errors=errors,external_requests=external,source_pages_rendered=[1,2],screenshots=str(out))
    (ROOT/'results/desktop-preview.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2));assert result['passed']


if __name__=='__main__':main()
