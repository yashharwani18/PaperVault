"""Read-only checks on the current college PPT collection and local responses."""
import json
from pathlib import Path
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
BASE='http://127.0.0.1:8766'


def main():
    state=json.load(urllib.request.urlopen(BASE+'/api/state'))
    folder=next(f['id'] for f in state['folders'] if f['name']=='TOC')
    cases=['bhai pumping lemma kis PPT mein hai','Explain pumping lemma for context-free languages']
    reports=[]
    for query in cases:
        request=urllib.request.Request(BASE+'/api/search',data=json.dumps(dict(query=query,folder_id=folder)).encode(),headers={'Content-Type':'application/json','X-Library-Token':state['token']})
        data=json.load(urllib.request.urlopen(request,timeout=60));response=data['response']
        assert response['method']=='qwen_source_selection' and response['citations'],response
        for citation in response['citations']:
            hit=next(h for h in data['results'] if h['chunk_id']==citation['chunk_id'])
            assert hit['folder_id']==folder and citation['location'].startswith('Slide ')
            assert citation['excerpt'] in hit['passage'] and citation['source_identity']==hit['source_identity']
        reports.append(dict(query=query,response=response,passed=True,elapsed_s=data['elapsed_s']))
        print(query,':',response['text'],response['citations'][0]['location'],flush=True)
    path=ROOT/'results/automatic-qwen-ppt-live.json'
    path.write_text(json.dumps(dict(passed=len(reports),total=len(cases),tests=reports),indent=2,ensure_ascii=False),encoding='utf-8')
    print(f'{len(reports)}/{len(cases)} real PPT response checks passed')


if __name__=='__main__':main()
