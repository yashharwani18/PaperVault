"""Read-only live-app checks for Qwen and the unchanged numeric search route."""
import json
from pathlib import Path
import urllib.error
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
BASE='http://127.0.0.1:8766'


def main():
    state=json.load(urllib.request.urlopen(BASE+'/api/state'))
    folder=next(f['id'] for f in state['folders'] if f['name']=='Pawan Bills')
    cases=[
        ('hello mere bhai kaisa hai, muje wo wala invoice dikha na jaha pe 13800 ka invoice ban raha tha',[],None,'qwen3_0.6b_q4_k_m',{}),
        ('bhai 14280 ka invoice dikha de',['INV-39bhavnahandloom.pdf'],2,'qwen3_0.6b_q4_k_m',{}),
        ('13600 rupaye ka subtotal kis invoice me hai',['INV-39bhavnahandloom.pdf'],1,'qwen3_0.6b_q4_k_m',{}),
        ('14280 wala bill dikhao',['INV-39bhavnahandloom.pdf'],2,'qwen3_0.6b_q4_k_m',{}),
        ('Missing Trading ka 14280 wala invoice dikhao',[],None,'qwen3_0.6b_q4_k_m',{}),
        ('13600 se zyada ka invoice dikhao',None,None,None,{}),
        ('hello bhai 14280 ka invoice dikhao na',['INV-39bhavnahandloom.pdf'],2,'qwen3_0.6b_q4_k_m',{'use_local_interpreter':False}),
        ('which invoice had 13600 subtotal?',['INV-39bhavnahandloom.pdf'],1,None,{}),
    ];results=[]
    for query,expected,page,method,extra in cases:
        request=urllib.request.Request(BASE+'/api/search',data=json.dumps(dict(query=query,folder_id=folder,**extra)).encode(),headers={'Content-Type':'application/json','X-Library-Token':state['token']})
        try:
            response=urllib.request.urlopen(request,timeout=40);data=json.load(response)
            assert expected is not None and sorted(h['filename'] for h in data['results'])==expected,data
            assert data.get('interpretation',{}).get('method')==method,data
            assert data['mode']=='bill_fields' and data['query_embedding_s']==0
            assert data['response']['method']=='qwen_source_selection' and data['response']['text']
            for citation in data['response']['citations']:
                assert citation['excerpt'] in next(h['passage'] for h in data['results'] if h['chunk_id']==citation['chunk_id'])
            for hit in data['results']:
                assert hit['page_number']==page and hit['source_identity'] and hit['amount_match']['evidence'] in hit['passage']
            results.append(dict(query=query,passed=True,method=method,files=expected,page=page))
        except urllib.error.HTTPError as error:
            assert expected is None and error.code==400,error.read().decode()
            results.append(dict(query=query,passed=True,clarification=json.load(error)['detail']))
    path=ROOT/'results/qwen-live-app-tests.json'
    path.write_text(json.dumps(dict(passed=len(results),total=len(cases),tests=results),indent=2),encoding='utf-8')
    print(f'{len(results)}/{len(cases)} live app checks passed')


if __name__=='__main__':main()
