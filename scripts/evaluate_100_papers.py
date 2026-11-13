"""Resumable 100-paper stress test; automatic source-derived probes are not human judgments."""
from pathlib import Path
import argparse,collections,datetime as dt,difflib,hashlib,json,re,shutil,sys,time,urllib.request,urllib.parse,xml.etree.ElementTree as ET
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
BASE=ROOT/'corpus/research-papers-100';OUT=ROOT/'results/research-papers-100';LABELS=BASE/'labels.json'
CATEGORIES=['cs.CL','cs.CV','math.NA','physics.bio-ph','astro-ph.GA']
def write(p,x):
 p.parent.mkdir(parents=True,exist_ok=True);tmp=p.with_suffix('.tmp');tmp.write_text(json.dumps(x,ensure_ascii=False,indent=2),encoding='utf-8');tmp.replace(p)
def norm(s):return ' '.join(re.findall(r"[^\W_]+",s.casefold()))
def fetch(url):
 for attempt in range(3):
  try:
   with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'Khoj local research evaluation'}),timeout=60) as r:return r.read(40*1024*1024+1)
  except Exception:
   if attempt==2:raise
   time.sleep(5*(attempt+1))
def download():
 import pymupdf
 BASE.mkdir(parents=True,exist_ok=True)
 old=json.loads((ROOT/'corpus/research-papers-2026-10-30/manifest.json').read_text())['documents']
 selected=[]
 for entry in old:
  dest=BASE/(entry['id']+'.pdf')
  if not dest.exists():shutil.copy2(ROOT/entry['file'],dest)
  selected.append({**entry,'category':'original-ML','file':dest.relative_to(ROOT).as_posix()})
 ns={'a':'http://www.w3.org/2005/Atom'}
 for cat in CATEGORIES:
  cache=BASE/(cat+'.atom')
  if not cache.exists():
   url='https://export.arxiv.org/api/query?'+urllib.parse.urlencode(dict(search_query='cat:'+cat,start=0,max_results=25,sortBy='submittedDate',sortOrder='descending'))
   cache.write_bytes(fetch(url));time.sleep(3.2)
  entries=ET.fromstring(cache.read_bytes()).findall('a:entry',ns);added=0
  limit=18 if cat==CATEGORIES[-1] else 19
  for entry in entries:
   arxiv=entry.findtext('a:id','',ns).split('/abs/')[-1]
   if not re.match(r'^\d{4}\.\d{4,5}(v\d+)?$',arxiv):continue
   if any(re.sub(r'v\d+$','',e['arxiv'])==re.sub(r'v\d+$','',arxiv) for e in selected):continue
   key=arxiv.replace('.','_');path=BASE/(key+'.pdf');url='https://arxiv.org/pdf/'+arxiv
   try:
    if not path.exists():
     data=fetch(url)
     if len(data)>40*1024*1024 or not data.startswith(b'%PDF'):raise ValueError('Not a bounded PDF')
     with pymupdf.open(stream=data,filetype='pdf') as pdf:assert len(pdf)
     path.write_bytes(data);time.sleep(3.2)
    with pymupdf.open(path) as pdf:
     pages=len(pdf)
    selected.append(dict(id=key,arxiv=arxiv,title=' '.join(entry.findtext('a:title','',ns).split()),abstract=' '.join(entry.findtext('a:summary','',ns).split()),authors=[a.findtext('a:name','',ns) for a in entry.findall('a:author',ns)],published=entry.findtext('a:published','',ns),category=cat,url=url,file=path.relative_to(ROOT).as_posix(),sha256=hashlib.sha256(path.read_bytes()).hexdigest(),pages=pages))
    added+=1;write(BASE/'manifest.json',{'documents':selected,'complete':False});print('DOWNLOAD',len(selected),cat,key,pages,flush=True)
    if added==limit:break
   except Exception as e:print('DOWNLOAD FAILED',arxiv,str(e),flush=True)
  if added<limit:raise RuntimeError('Not enough downloads for '+cat)
 assert len(selected)==100
 write(BASE/'manifest.json',{'documents':selected,'complete':True,'recorded_at':dt.datetime.now(dt.timezone.utc).isoformat()})
def freeze(entries):
 import pymupdf
 rows=[]
 for e in entries:
  path=ROOT/e['file'];assert hashlib.sha256(path.read_bytes()).hexdigest()==e['sha256']
  with pymupdf.open(path) as pdf:pages=[norm(p.get_text()) for p in pdf]
  rows.append(dict(id=e['id']+'-title',kind='title',document=e['id'],query=e['title'],relevant=[]))
  if not e.get('abstract'):continue
  sentences=re.split(r'(?<=[.!?])\s+',e['abstract'])
  query='Find the paper about: '+' '.join(sentences[:2]);anchors=[]
  for sentence in sentences[:2]:
   words=norm(sentence).split()
   for start in range(0,max(1,len(words)-9),5):
    anchor=' '.join(words[start:start+10])
    if len(anchor.split())<8:continue
    for page,source in enumerate(pages[:4],1):
     if anchor in source:anchors.append({'page':page,'anchor':anchor})
  rows.append(dict(id=e['id']+'-abstract',kind='abstract',document=e['id'],query=query,relevant=anchors))
 from scripts.evaluate_research_papers import CASES,NEGATIVES
 for key,doc,query,gold in CASES:
  rows.append(dict(id=key,kind='original-depth',document=doc,query=query,relevant=[dict(page=p,anchor=norm(a)) for p,a in gold]))
 extra=json.loads((ROOT/'evaluation/research-paper-100-manual.json').read_text(encoding='utf-8'))
 for q in extra:
  entry=next(e for e in entries if e['id']==q['document'])
  with pymupdf.open(ROOT/entry['file']) as pdf:
   for r in q['relevant']:
    r['anchor']=norm(r['anchor']);assert r['anchor'] in norm(pdf[r['page']-1].get_text()),q['id']
 rows.extend(extra)
 rows.extend(dict(id=key,kind='negative-control',document=None,query=query,relevant=[]) for key,query in NEGATIVES)
 value=dict(provenance='Title and abstract probes automatically derived from official arXiv metadata, verified against PDF pages before scoring; lexical overlap makes these easier than independent human questions. Original 24 depth questions unchanged.',queries=rows)
 if LABELS.exists():assert json.loads(LABELS.read_text(encoding='utf-8'))==value,'Labels changed'
 else:write(LABELS,value)
 return value

def evaluate():
 from knowledge_library.library import Library
 from knowledge_library.embedding import EmbeddingGemma
 from knowledge_library import papers
 entries=json.loads((BASE/'manifest.json').read_text(encoding='utf-8'))['documents'];assert len(entries)==100
 labels=freeze(entries);print('FROZEN',len(labels['queries']),'probes',flush=True)
 report=dict(status='running',documents=[],queries=[],summaries={},labels_sha256=hashlib.sha256(LABELS.read_bytes()).hexdigest(),label_provenance=labels['provenance'])
 import importlib.util
 spec=importlib.util.spec_from_file_location('knowledge_library.papers_before',ROOT/'.cache/research-papers-100/papers-before.py');before=importlib.util.module_from_spec(spec);spec.loader.exec_module(before)
 started=time.perf_counter();model=EmbeddingGemma(device='cuda',batch_size=8)
 with Library(ROOT/'.cache/research-papers-100/library',model) as lib:
  folder=next((f['id'] for f in lib.folders() if f['name']=='100 research papers'),None) or lib.create_folder('100 research papers')['id'];mapping={}
  for e in entries:
   t=time.perf_counter();r=lib.import_pdf(ROOT/e['file'],folder,title=e['title']);doc=r['document'];mapping[doc['id']]=e['id']
   baseline=before.extract(ROOT/e['file'],document_id=e['id'],filename=Path(e['file']).name)
   ref=papers.reference(lib,doc['id']);item=ref['item'];author_names=[' '.join([a.get('given',''),a.get('family','')]).strip() if not a.get('literal') else a['literal'] for a in item.get('author',[])]
   row=dict(id=e['id'],category=e['category'],status=doc['status'],pages=doc['page_count'],chunks=doc['chunk_count'],seconds=time.perf_counter()-t,detected=ref['detected'],baseline_detected=baseline['detected'],item=item,warnings=ref['warnings'],title_similarity=difflib.SequenceMatcher(None,norm(item.get('title','')),norm(e['title'])).ratio())
   if 'authors' in e:row.update(expected_authors=e['authors'],exact_author_list=[norm(a) for a in author_names]==[norm(a) for a in e['authors']],expected_title=e['title'])
   report['documents'].append(row);write(OUT/'report.json',report);print('INDEX',len(report['documents']),e['id'],doc['status'],flush=True)
  report['index_seconds']=time.perf_counter()-started;report['integrity']=lib.verify()
  for mode in ['semantic','hybrid']:
   for q in labels['queries']:
    result=lib.search(q['query'],mode=mode,top_k=5)
    hits=[dict(document=mapping[h['document_id']],page=h['page_number'],text=h['passage'],score=h['score']) for h in result['results']]
    row={**q,'mode':mode,'hits':hits,'seconds':result['elapsed_s'],'returned_candidates':len(hits)}
    row['paper_hit1']=bool(hits and hits[0]['document']==q['document']);row['paper_hit5']=any(h['document']==q['document'] for h in hits)
    if q['relevant']:
     matches=[i for i,h in enumerate(hits,1) if h['document']==q['document'] and any(h['page']==r['page'] for r in q['relevant'])];row['page_hit1']=bool(matches and matches[0]==1);row['page_hit5']=bool(matches)
     row['anchor_hit5']=any(h['document']==q['document'] and any(h['page']==r['page'] and r['anchor'] in norm(h['text']) for r in q['relevant']) for h in hits)
    report['queries'].append(row)
   for kind in ['title','abstract','original-depth','new-manual','negative-control']:
    group=[r for r in report['queries'] if r['mode']==mode and r['kind']==kind];s={'queries':len(group)}
    for metric in ['paper_hit1','paper_hit5','page_hit1','page_hit5','anchor_hit5']:
     eligible=[r for r in group if metric in r];s[metric]={'passed':sum(r[metric] for r in eligible),'total':len(eligible)}
    report['summaries'][mode+'-'+kind]=s
   write(OUT/'report.json',report);print('SCORED',mode,flush=True)
 report.update(status='complete',total_seconds=time.perf_counter()-started,model_signature=model.signature)
 write(OUT/'report.json',report)
 lines=['# 100-paper evaluation','',f"Documents: {len(entries)}. Pages: {sum(e['pages'] for e in entries)}.",'','Automatic title/abstract probes have lexical overlap and are NOT independent semantic accuracy judgments. The unchanged 24 original depth questions are evaluated separately against 94 extra distractor papers.','', '| Mode / probe | Paper @1 | Paper @5 | Page @1 | Page @5 | Anchor @5 |','|---|---|---|---|---|---|']
 for key,s in report['summaries'].items():
  if key.endswith('negative-control'):continue
  lines.append('| '+key+' | '+' | '.join(str(s[m]['passed'])+'/'+str(s[m]['total']) for m in ['paper_hit1','paper_hit5','page_hit1','page_hit5','anchor_hit5'])+' |')
 negatives=[r for r in report['queries'] if r['kind']=='negative-control']
 lines.extend(['',f'Unrelated controls returning candidates: {sum(bool(r["returned_candidates"]) for r in negatives)}/{len(negatives)} across both modes. Candidates do not establish that an answer exists.'])
 docs=report['documents'];known=[d for d in docs if 'exact_author_list' in d]
 lines.extend(['',f"Detected papers before fix: {sum(d['baseline_detected'] for d in docs)}/100; after fix: {sum(d['detected'] for d in docs)}/100. Titles with normalized similarity >=0.95: {sum(d['title_similarity']>=.95 for d in docs)}/100. Exact extracted author lists vs arXiv metadata: {sum(d['exact_author_list'] for d in known)}/{len(known)}.",'','Reference metadata remains draft: preprint and publication metadata can differ. No claim that detection or approximate titles establish correct citations. All PDFs are native-text arXiv sources, not scans. No production parameters were tuned on this set.','', 'Reproduce: `.venv/Scripts/python.exe scripts/evaluate_100_papers.py --download` then the same command without --download. Downloads and indexed documents are reused.'])
 (OUT/'REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8');print('COMPLETE',json.dumps(report['summaries']),flush=True)
def prepare():
 from knowledge_library.library import Library
 from knowledge_library.embedding import EmbeddingGemma
 done=set();deadline=time.monotonic()+2400
 with Library(ROOT/'.cache/research-papers-100/library',EmbeddingGemma(device='cuda',batch_size=8)) as lib:
  folder=next((f['id'] for f in lib.folders() if f['name']=='100 research papers'),None) or lib.create_folder('100 research papers')['id']
  while time.monotonic()<deadline:
   path=BASE/'manifest.json'
   if not path.exists():time.sleep(3);continue
   manifest=json.loads(path.read_text(encoding='utf-8'))
   for e in manifest['documents']:
    if e['id'] in done:continue
    r=lib.import_pdf(ROOT/e['file'],folder,title=e['title']);done.add(e['id']);print('PREPARE',len(done),e['id'],r['document']['status'],flush=True)
   if manifest.get('complete'):
    assert len(done)==100;return
   time.sleep(3)
 raise TimeoutError('Download/index preparation timed out; resume command to continue.')

if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('--download',action='store_true');parser.add_argument('--prepare',action='store_true');args=parser.parse_args()
 if args.download:download()
 elif args.prepare:prepare()
 else:evaluate()
