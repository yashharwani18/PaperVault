"""Real CPU inference benchmark; no mock or embedding substitutes."""
import json
from pathlib import Path
import statistics
import sys
import threading
import time

import psutil

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from knowledge_library.query_interpreter import QueryInterpreter

CASES=[
 ('hello mere bhai kaisa hai, muje wo wala invoice dikha na jaha pe 13800 ka invoice ban raha tha','total','13800.00',''),
 ('bhai 14280 ka invoice dikha de','total','14280.00',''),
 ('mujhe 13600 subtotal wala invoice chahiye','subtotal','13600.00',''),
 ('yaar jis bill ka subtotal 29280 tha wo dikhao','subtotal','29280.00',''),
 ('mereko 30744 wala bill chahiye','total','30744.00',''),
 ('13600 rupaye ka subtotal kis invoice me hai','subtotal','13600.00',''),
 ('dikha na wo invoice jiska total 64890 hai','total','64890.00',''),
 ('wo 91470 ke subtotal ka invoice dhoondh','subtotal','91470.00',''),
 ('mujhe 96043.50 ka bill dikhao','total','96043.50',''),
 ('13800 wala bill mil sakta hai kya','total','13800.00',''),
 ('13,600 ka invoice dikha','total','13600.00',''),
 ('hello bhai 1,04,580 ka bill dikha de','total','104580.00',''),
 ('can you find bill worth 17451','total','17451.00',''),
 ('invoice 27200 ka bana tha wo chahiye','total','27200.00',''),
 ('BHAVNA HANDLOOM HOUSE ka 14280 wala invoice dikhao','total','14280.00','BHAVNA HANDLOOM HOUSE'),
 ('Missing Trading ka 14280 wala invoice dikhao','total','14280.00','Missing Trading'),
 ('13600 se zyada ka bill dikhao',None,None,''),
 ('13600 ya 13800 ka invoice dikha',None,None,''),
 ('Bhagwanti Trading ko 25 September 2026 pe 13600 ka maal becha tha invoice dikhao','total','13600.00','Bhagwanti Trading'),
 ('Bhagwanti Trading se 25 September 2026 pe 13600 ka maal kharida invoice dikhao','total','13600.00','Bhagwanti Trading'),
 # Additional variants added after the first 20-case diagnostic run.
 ('arre bhai please wo 23310 ka invoice nikal do','total','23310.00',''),
 ('kya 23100 wala bill milega mujhe','total','23100.00',''),
 ('mujhe us invoice ka pata karna hai jo 15246 ka tha','total','15246.00',''),
 ('bhai 29074 ke amount wala invoice chahiye','total','29074.00',''),
 ('find that invoice jisme subtotal 61800 hai please','subtotal','61800.00',''),
 ('hello mujhe 1,04,580.00 ka invoice chaiye','total','104580.00',''),
 ('please 34000 se kam wala bill batao',None,None,''),
 ('bhai invoice 5310 USD ka chahiye','total','5310.00',''),
 ('Asha Stationers ka 5310 wala invoice chahiye','total','5310.00','Asha Stationers'),
 ('mujhe 4500 tax se pehle wala invoice dikhao','subtotal','4500.00',''),
]


def main():
    model=QueryInterpreter();results=[];peaks=[];stop=threading.Event()
    def sample():
        while not stop.wait(.02):
            try:peaks.append(sum(p.memory_info().rss for p in psutil.Process().children(recursive=True) if p.is_running()))
            except psutil.Error:pass
    monitor=threading.Thread(target=sample,daemon=True);monitor.start()
    try:
        for query,field,value,party in CASES:
            start=time.perf_counter();row=dict(query=query,expected_field=field,expected_amount=value,expected_party=party)
            try:
                actual=model.interpret(query);row['actual']=actual
                row['passed']=field is not None and actual['amount']['field']==field and actual['amount']['value']==value and actual['filters'].get('party','').casefold()==party.casefold()
                if 'becha' in query:row['passed']=row['passed'] and actual['filters'].get('direction')=='sale' and actual['filters'].get('date_from')=='2026-09-25'
                if 'kharida' in query:row['passed']=row['passed'] and actual['filters'].get('direction')=='purchase' and actual['filters'].get('date_from')=='2026-09-25'
            except ValueError as error:row.update(passed=field is None,error=str(error))
            row['elapsed_s']=round(time.perf_counter()-start,3);results.append(row)
            print(('PASS' if row['passed'] else 'FAIL'),query,row.get('error',''),flush=True)
    finally:stop.set();monitor.join()
    elapsed=[r['elapsed_s'] for r in results]
    report=dict(model=model.status(),device='Windows PC CPU, four threads; not a phone benchmark',
        load_policy='Fresh native process per request; no resident interpreter after completion',
        model_bytes=model.model_path.stat().st_size,peak_child_rss_bytes=max(peaks,default=0),
        mean_s=statistics.mean(elapsed),max_s=max(elapsed),passed=sum(r['passed'] for r in results),total=len(results),tests=results)
    path=ROOT/'results/qwen-hinglish-benchmark.json';path.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(f"{report['passed']}/{report['total']} passed; mean {report['mean_s']:.2f}s, peak child RSS {report['peak_child_rss_bytes']/1024**2:.1f} MiB",flush=True)
    assert report['passed']==report['total']


if __name__=='__main__':main()
