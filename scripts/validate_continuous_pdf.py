"""Continuous-reader acceptance in the real native WebView2 session."""
import json
import re
from pathlib import Path
import urllib.request
from playwright.sync_api import sync_playwright, expect

ROOT=Path(__file__).resolve().parents[1]


def main():
    ready=json.loads(max((ROOT/'data/pc-prototype/native').glob('session-*.json'),key=lambda p:p.stat().st_mtime).read_text())
    state=json.load(urllib.request.urlopen(ready['url']+'/api/state',timeout=10))
    short=next(d for d in state['documents'] if 3<=d['page_count']<=10)
    book=max(state['documents'],key=lambda d:d['page_count'])
    output=ROOT/'results/continuous-pdf';output.mkdir(exist_ok=True)
    report={'checks':[],'errors':[],'external_requests':[]}
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,executable_path='C:/Program Files/BraveSoftware/Brave-Browser/Application/brave.exe')
        page=browser.new_page(viewport={'width':1280,'height':900})
        page.on('pageerror',lambda e:report['errors'].append(str(e)))
        page.on('request',lambda r:report['external_requests'].append(r.url) if not r.url.startswith((ready['url'],'blob:','data:')) else None)
        page.goto(ready['url'])
        page.set_viewport_size({'width':1280,'height':900})
        if page.get_by_role('button',name='Close document viewer',exact=True).is_visible():page.get_by_role('button',name='Close document viewer',exact=True).click()
        page.get_by_role('navigation',name='Main navigation').get_by_role('button',name='All documents',exact=True).click()
        def open_doc(doc):
            page.get_by_role('button',name='Manage document '+doc['filename'],exact=True).locator('xpath=ancestor::article').locator('.document-main').click()
            expect(page.locator('.pdfViewer .page[data-page-number="1"] canvas').first).to_be_visible(timeout=45000)
            expect(page.get_by_label('PDF page number',exact=True)).to_have_value('1')
        open_doc(short)
        scroller=page.get_by_role('region',name='Scrollable PDF pages',exact=True)
        expect(page.locator('.pdfViewer .page')).to_have_count(short['page_count'])
        scroller.hover();page.mouse.wheel(0,1500)
        expect(page.get_by_label('PDF page number',exact=True)).not_to_have_value('1',timeout=10000)
        current=int(page.get_by_label('PDF page number',exact=True).input_value())
        expect(page.locator(f'.pdfViewer .page[data-page-number="{current}"] canvas').first).to_be_visible(timeout=30000)
        report['checks'].append('Wheel scrolling advances naturally to later pages and updates the page counter')
        page.mouse.wheel(0,-5000)
        expect(page.get_by_label('PDF page number',exact=True)).to_have_value('1',timeout=10000)
        page.get_by_label('PDF page number',exact=True).fill('2')
        expect(page.locator('.pdfViewer .page[data-page-number="2"] canvas').first).to_be_visible(timeout=30000)
        page.get_by_role('button',name='Next page',exact=True).click()
        expect(page.get_by_label('PDF page number',exact=True)).to_have_value('3')
        page.get_by_label('PDF zoom',exact=True).select_option('1.25')
        expect(page.locator('.pdfViewer .page[data-page-number="3"] canvas').first).to_be_visible(timeout=30000)
        report['checks'].append('Scrolling backward, direct page jumps, optional next-page control and zoom work')
        page.screenshot(path=str(output/'short-document.png'))
        page.get_by_role('button',name='Close document viewer',exact=True).click()
        open_doc(book)
        target=min(500,book['page_count'])
        page.get_by_label('PDF page number',exact=True).fill(str(target))
        expect(page.locator(f'.pdfViewer .page[data-page-number="{target}"] canvas').first).to_be_visible(timeout=45000)
        assert page.locator('.pdfViewer canvas').count()<40,'Distant pages should not all have rendered canvases'
        expect(page.get_by_test_id('pdf-page-text')).not_to_have_text('',timeout=15000)
        report['large_document_pages']=book['page_count'];report['rendered_canvases_at_jump']=page.locator('.pdfViewer canvas').count()
        report['checks'].append(f'Large {book["page_count"]}-page PDF supports a distant jump with a bounded set of canvases and selectable text')
        page.screenshot(path=str(output/'large-document.png'))
        page.get_by_role('button',name='Close document viewer',exact=True).click()
        page.get_by_label('Search your library',exact=True).fill('digital signal processing')
        page.get_by_role('button',name='Run search',exact=True).click()
        source=page.locator('.result-bottom button').first
        expect(source).to_be_visible(timeout=45000)
        matched=int(re.search(r'page (\d+)',source.inner_text()).group(1))
        source.click()
        expect(page.locator(f'.pdfViewer .page[data-page-number="{matched}"] canvas').first).to_be_visible(timeout=45000)
        expect(page.locator('.source-highlight').first).to_be_visible(timeout=15000)
        report['checks'].append('Search-result deep links open the correct page and preserve matched-passage highlights')
        page.get_by_role('button',name='Close document viewer',exact=True).click()
        page.get_by_role('button',name='Back to library',exact=True).click()
        open_doc(short)
        report['checks'].append('Closing and reopening different PDFs cleans up the previous reader')
        page.set_viewport_size({'width':390,'height':844})
        scroller=page.get_by_role('region',name='Scrollable PDF pages',exact=True)
        scroller.hover();page.mouse.wheel(0,1000)
        expect(page.get_by_label('PDF page number',exact=True)).not_to_have_value('1',timeout=10000)
        page.screenshot(path=str(output/'narrow-reader.png'))
        report['checks'].append('Continuous scrolling also works in the narrow layout')
        page.get_by_role('button',name='Close document viewer',exact=True).click()
        page.set_viewport_size({'width':1280,'height':900})
        assert not report['errors'],report
        assert not report['external_requests'],report
        browser.close()
    (ROOT/'results/continuous-pdf-validation.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
