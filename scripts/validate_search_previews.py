"""Read-only acceptance against the installed desktop engine, in a test browser."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright,expect

ROOT=Path(__file__).resolve().parents[1]


def main():
    ready=json.loads(max((ROOT/'data/pc-prototype/native').glob('session-*.json'),key=lambda p:p.stat().st_mtime).read_text())
    output=ROOT/'results/search-page-previews';output.mkdir(exist_ok=True)
    report={'previews':[],'errors':[]}
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,executable_path='C:/Program Files/BraveSoftware/Brave-Browser/Application/brave.exe')
        page=browser.new_page(viewport={'width':1440,'height':1050})
        page.on('pageerror',lambda error:report['errors'].append(str(error)))
        responses=[]
        def preview_response(response):
            if '/preview?' in response.url:
                responses.append(dict(status=response.status,highlights=response.headers.get('x-highlight-count'),url=response.url))
        page.on('response',preview_response)
        page.goto(ready['url'])
        search=page.get_by_role('textbox',name='Search your library',exact=True)
        expect(search).to_be_visible(timeout=30000)
        search.fill('digital signal processing')
        with page.expect_response(lambda r:r.url.endswith('/api/search') and r.request.method=='POST',timeout=90000) as captured:
            search.press('Enter')
        result=captured.value.json()
        report['retrieval_elapsed_s']=result['elapsed_s']
        assert len(result['results'])==5,result
        cards=page.locator('.result-card')
        expect(cards).to_have_count(5)
        for i in range(5):
            card=cards.nth(i)
            card.locator('.search-page-preview').scroll_into_view_if_needed()
            img=card.locator('.search-page-preview img')
            expect(img).to_be_visible(timeout=45000)
            expect(img).to_have_js_property('complete',True)
            assert img.evaluate('(image)=>image.naturalWidth')>=1000
            assert not card.locator('.matched-text').evaluate('(details)=>details.open')
            report['previews'].append({'page':result['results'][i]['page_number'],'width':img.bounding_box()['width'],
                                       'caption':card.locator('.search-page-caption').inner_text()})
        assert all(r['status']==200 and int(r['highlights'])>0 for r in responses),responses
        cards.first.locator('.result-top').scroll_into_view_if_needed()
        page.evaluate('window.scrollBy(0,-110)')
        page.screenshot(path=str(output/'desktop.png'))
        cards.first.locator('.matched-text summary').click()
        expect(cards.first.locator('.matched-text .passage')).to_be_visible()
        cards.first.locator('.matched-text summary').click()
        cards.first.get_by_role('button',name='Open at page',exact=False).click()
        expect(page.get_by_role('button',name='Close document viewer',exact=True)).to_be_visible()
        expect(page.get_by_test_id('pdf-canvas').first).to_be_visible(timeout=30000)
        page.get_by_role('button',name='Close document viewer',exact=True).click()
        page.set_viewport_size({'width':390,'height':844})
        cards.first.locator('.search-page-preview').scroll_into_view_if_needed()
        page.screenshot(path=str(output/'narrow.png'))
        assert cards.first.locator('.search-page-preview img').bounding_box()['width']<=390
        # Missing originals need a useful fallback, and retry must recover.
        page.set_viewport_size({'width':1440,'height':1050})
        page.route('**/preview?*',lambda route:route.fulfill(status=404,content_type='application/json',body=json.dumps({'detail':'Original PDF is unavailable. Reconnect its folder to preview it.'})))
        search.fill('convolution')
        with page.expect_response(lambda r:r.url.endswith('/api/search') and r.request.method=='POST'):
            search.press('Enter')
        first=page.locator('.result-card').first
        first.locator('.search-page-preview').scroll_into_view_if_needed()
        expect(first.get_by_text('Original PDF is unavailable.',exact=False)).to_be_visible(timeout=15000)
        page.unroute('**/preview?*')
        first.get_by_role('button',name='Retry preview',exact=True).click()
        expect(first.locator('.search-page-preview img')).to_be_visible(timeout=15000)
        report['missing_source_retry']='passed'
        report['responses']=responses
        assert not report['errors'],report['errors']
        browser.close()
    (ROOT/'results/search-page-preview-validation.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
