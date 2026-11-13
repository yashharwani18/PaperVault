"""Compile production Java helpers and score the frozen multilingual corpus suite."""
from pathlib import Path
from collections import defaultdict
import json,os,argparse,subprocess
ROOT=Path(__file__).resolve().parents[1]

def evaluate(export,suite,output):
 output.mkdir(parents=True,exist_ok=True);config=json.loads((ROOT/'.cache/android-tools/toolchain.json').read_text());java=Path(config['java_home'])/'bin'
 jar=next((ROOT/'.cache/android-gradle/caches/modules-2/files-2.1/org.json/json').rglob('json-20240303.jar'))
 classes=output/'classes';classes.mkdir(exist_ok=True);source=ROOT/'android/app/src/main/java/org/localknowledge/library'
 subprocess.run([str(java/'javac.exe'),'-encoding','UTF-8','-cp',str(jar),'-d',str(classes),*[str(source/(n+'.java')) for n in ('InvoiceNumbers','Money','Json')],str(ROOT/'scripts/MultilingualCorpusProbe.java')],check=True)
 with (output/'actual.jsonl').open('w',encoding='utf-8') as out:
  subprocess.run([str(java/'java.exe'),'-Xmx768m','-cp',os.pathsep.join([str(classes),str(jar)]),'org.localknowledge.library.MultilingualCorpusProbe',str(export/'pages.jsonl'),str(suite/'cases.jsonl')],stdout=out,check=True)
 cases=[json.loads(l) for l in (suite/'cases.jsonl').read_text(encoding='utf-8').splitlines()];actual=[json.loads(l) for l in (output/'actual.jsonl').read_text(encoding='utf-8').splitlines()];assert len(cases)==len(actual)
 groups=defaultdict(lambda:dict(total=0,passed=0));failures=[]
 for c,a in zip(cases,actual,strict=True):
  assert c['id']==a['id'];expected=set(c['expected']);found=set(a.get('pages',[]))
  if c['kind']=='unsafe':ok=a.get('invoice') is None and a.get('amount') is None and (not a.get('error') or a['error'].startswith('java.lang.IllegalArgumentException:'))
  elif c['kind']=='invoice':ok=a.get('invoice') is not None and not a.get('error') and found==expected
  else:ok=a.get('amount') is not None and not a.get('error') and a['amount']['field']==c['field'] and a['amount']['value']==c['value'] and expected<=found
  for key in (c['language']+':'+c['kind'],c['split'], 'all'):
   groups[key]['total']+=1;groups[key]['passed']+=ok
  if not ok:failures.append(dict(case=c,actual=a,missing=sorted(expected-found),extra=sorted(found-expected)))
 report=dict(groups=dict(groups),failures=len(failures));(output/'report.json').write_text(json.dumps(report,indent=2)+'\n');(output/'failures.json').write_text(json.dumps(failures,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(report,indent=2));return report
if __name__=='__main__':
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('export',type=Path);parser.add_argument('suite',type=Path);parser.add_argument('--output',type=Path,required=True);parser.add_argument('--check',action='store_true');args=parser.parse_args();report=evaluate(args.export,args.suite,args.output)
 if args.check and report['failures']:raise SystemExit(1)
