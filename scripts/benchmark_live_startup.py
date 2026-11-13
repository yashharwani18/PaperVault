"""Restart the idle launcher-owned app and measure visible/readiness/search time."""
import json
from pathlib import Path
import subprocess
import time
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
BASE='http://127.0.0.1:8766'


def state():return json.load(urllib.request.urlopen(BASE+'/api/state',timeout=15))


def search(query,folder,token):
    started=time.perf_counter()
    request=urllib.request.Request(BASE+'/api/search',data=json.dumps(dict(query=query,folder_id=folder)).encode(),headers={'Content-Type':'application/json','X-Library-Token':token})
    result=json.load(urllib.request.urlopen(request,timeout=120))
    return time.perf_counter()-started,result


def main():
    before=state()
    assert not any(t['status'] in ('queued','running') for t in before['tasks']),'Indexing active; no restart performed'
    library=ROOT/'data/demo-invoices'
    def launcher(name,*args):
        # Windows background children may inherit PIPE handles after PowerShell
        # exits; log to a regular file so communicate() cannot wait for server EOF.
        with (ROOT/'results/startup-launcher.log').open('a',encoding='utf-8') as output:
            subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-File',str(ROOT/'scripts'/name),'-LibraryPath',str(library),*args],check=True,stdout=output,stderr=subprocess.STDOUT,timeout=60)
    launcher('stop_desktop.ps1')
    started=time.perf_counter();launcher('start_desktop.ps1','-Port','8766','-NoBrowser')
    current=state();visible=time.perf_counter()-started
    folders={f['name']:f['id'] for f in current['folders']}
    bills=next((f['id'] for f in current['folders'] if f['name'] in ('Bills','Pawan Bills')),None)
    during,matched=search('which invoice had 13600 subtotal?',bills,current['token'])
    assert any(h['filename']=='INV-39bhavnahandloom.pdf' for h in matched['results'])
    assert matched['response']['citations'] and matched['query_embedding_s']==0
    bill_status=state()['semantic_status']['state']
    while True:
        current=state()
        if current['semantic_status']['state']=='ready':break
        if current['semantic_status']['state']=='error':raise ValueError(current['semantic_status']['error'])
        if time.perf_counter()-started>180:raise TimeoutError('Search preparation took over three minutes')
        time.sleep(.3)
    ready=time.perf_counter()-started
    first,one=search('bhai pumping lemma kis PPT mein hai',folders['TOC'],current['token'])
    second,two=search('Explain pumping lemma for context-free languages',folders['TOC'],current['token'])
    assert one['response']['citations'] and two['response']['citations']
    assert all(c['location'].startswith('Slide ') for c in one['response']['citations'])
    result=dict(ui_available_s=visible,exact_bill_during_preparation_s=during,semantic_state_after_bill=bill_status,
        semantic_ready_from_launch_s=ready,first_semantic_after_ready_s=first,next_semantic_s=second,
        stats=state()['stats']['embedding_runtime'],document_count=len(current['documents']),
        note='One fresh app process on the same PC, with existing OS cache. UI time includes PowerShell launcher overhead. Not a reboot-cold or phone benchmark.')
    (ROOT/'results/startup-live-app.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result),flush=True)


if __name__=='__main__':main()
