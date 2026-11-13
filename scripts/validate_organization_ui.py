"""Organization acceptance using generated PDFs in an isolated test library."""
import json
from pathlib import Path
import time
import uuid
import httpx
import pymupdf
from playwright.sync_api import sync_playwright,expect

ROOT=Path(__file__).resolve().parents[1]


def main():
    ready=json.loads((ROOT/'.cache/organization-ui-library/native/session-organization.json').read_text())
    output=ROOT/'results/organization-ui';output.mkdir(exist_ok=True)
    client=httpx.Client(base_url=ready['url'],headers={'X-Library-Token':ready['token']},timeout=60)
    def request(path,body=None,method='POST'):
        response=client.request(method,path,json=body);response.raise_for_status();return response.json()
    state=client.get('/api/state').json()
    if not state['documents']:
        first=request('/api/folders',{'name':'Imported'})['id'];second=request('/api/folders',{'name':'Courses'})['id']
        pdfs=[]
        for i in [1,2]:
            path=ROOT/f'.cache/organization-ui-library/DSP_notes_{i}.pdf'
            with pymupdf.open() as pdf:
                pdf.new_page().insert_text((40,60),f'Digital signal processing uses discrete filters and convolution. Source {i}.');pdf.save(path)
            pdfs.append(path)
        response=client.post('/api/uploads',data={'folder_id':first},files=[('files',(p.name,p.read_bytes(),'application/pdf')) for p in pdfs]);response.raise_for_status()
        ids=response.json()['task_ids'];deadline=time.monotonic()+240
        while True:
            state=client.get('/api/state').json();jobs=[t for t in state['tasks'] if t['id'] in ids]
            if jobs and all(t['status'] not in ('queued','running') for t in jobs):break
            assert time.monotonic()<deadline;time.sleep(.3)
        assert all(t['status']=='completed' for t in jobs),jobs
    else:
        first=next(f['id'] for f in state['folders'] if f['name']=='Imported');second=next(f['id'] for f in state['folders'] if f['name']=='Courses')
    report={'checks':[],'errors':[]}
    tag=uuid.uuid4().hex[:4];topic_name='Exam revision '+tag;renamed_topic='Exam preparation '+tag
    state=client.get('/api/state').json();document_ids=[d['id'] for d in state['documents']]
    request('/api/organization/topics/reset',{'document_ids':document_ids})
    request('/api/organization/move',{'document_ids':document_ids,'folder_id':first})
    for key in document_ids:request(f'/api/organization/documents/{key}/name',method='DELETE')
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,executable_path='C:/Program Files/BraveSoftware/Brave-Browser/Application/brave.exe')
        page=browser.new_page(viewport={'width':1440,'height':1050});page.on('pageerror',lambda error:report['errors'].append(str(error)))
        page.goto(ready['url'])
        page.get_by_role('button',name='All documents',exact=True).click()
        page.get_by_role('textbox',name='Filter documents by name').fill('DSP_notes')
        expect(page.locator('.document-row')).to_have_count(2)
        page.get_by_role('checkbox',name='Select all visible documents',exact=True).check()
        page.get_by_role('group',name='Selected document actions').get_by_role('button',name='Move',exact=True).click()
        page.get_by_role('combobox',name='Destination folder').select_option(second)
        page.get_by_role('button',name='Move documents',exact=True).click()
        expect(page.get_by_role('status').filter(has_text='Moved 2 documents')).to_be_visible()
        assert all(d['folder_id']==second for d in client.get('/api/state').json()['documents'])
        page.get_by_role('button',name='Undo',exact=True).click()
        expect(page.get_by_role('status').filter(has_text='Move undone')).to_be_visible()
        assert all(d['folder_id']==first for d in client.get('/api/state').json()['documents'])
        report['checks'].append('Filename filtering, bulk selection, atomic move and undo')
        page.get_by_role('button',name='Manage document DSP_notes_1.pdf',exact=True).click()
        page.get_by_role('button',name='Edit topics',exact=True).click()
        page.get_by_text('Create a new topic',exact=True).click()
        page.get_by_role('textbox',name='New topic name',exact=True).fill(topic_name)
        page.get_by_role('button',name='Create',exact=True).click()
        page.get_by_role('checkbox',name='DSP',exact=True).uncheck()
        page.screenshot(path=str(output/'desktop-topics.png'))
        page.set_viewport_size({'width':390,'height':844})
        expect(page.get_by_role('button',name='Save topics',exact=True)).to_be_in_viewport()
        page.screenshot(path=str(output/'narrow-topics.png'))
        assert page.get_by_role('dialog').bounding_box()['height']<=844
        page.get_by_role('button',name='Save topics',exact=True).click()
        expect(page.get_by_role('dialog')).to_have_count(0)
        page.set_viewport_size({'width':1440,'height':1050})
        page.get_by_role('button',name='My library').click()
        page.locator('.topic-list button').filter(has_text=topic_name).click()
        page.get_by_role('button',name='Rename topic',exact=True).click()
        page.get_by_role('textbox',name='Topic name',exact=True).fill(renamed_topic)
        page.get_by_role('button',name='Save name',exact=True).click()
        expect(page.get_by_role('heading',name=renamed_topic,exact=True)).to_be_visible()
        request('/api/linked-folders/rebuild')
        page.reload()
        expect(page.locator('.topic-list button').filter(has_text=renamed_topic)).to_be_visible()
        report['checks'].append('Create topic, correct classification and rename survive a full topic rebuild')
        page.get_by_role('button',name='All documents',exact=True).click()
        page.get_by_role('button',name='Manage document DSP_notes_1.pdf',exact=True).click()
        page.get_by_role('button',name='Rename display name',exact=True).click()
        page.get_by_role('textbox',name='Document display name',exact=True).fill('Signals exam notes')
        page.get_by_role('button',name='Save name',exact=True).click()
        expect(page.get_by_role('dialog')).to_have_count(0)
        page.get_by_role('textbox',name='Filter documents by name').fill('Signals exam')
        expect(page.locator('.document-row')).to_have_count(1)
        expect(page.locator('.document-main')).to_contain_text('Signals exam notes')
        page.screenshot(path=str(output/'desktop-renamed.png'))
        report['checks'].append('Rename display name and immediately filter using the saved name')
        assert not report['errors'],report
        browser.close()
    client.close()
    (ROOT/'results/organization-ui-validation.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))


if __name__=='__main__':main()
