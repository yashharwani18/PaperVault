"""Acquire 80 additional distinct public RFC PDFs for genuine 100-file scaling."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import urllib.request
import pymupdf

ROOT=Path(__file__).resolve().parents[1]


def fetch(number):
    url=f"https://www.rfc-editor.org/rfc/rfc{number}.pdf"
    dest=ROOT/f"corpus/pdfs/rfc-{number}.pdf"
    try:
        if not dest.exists():
            req=urllib.request.Request(url,headers={"User-Agent":"LocalKnowledge-PCValidation/0.4"})
            with urllib.request.urlopen(req,timeout=25) as response:
                data=response.read(30*1024*1024+1)
            if len(data)>30*1024*1024 or not data.startswith(b"%PDF-"):
                raise ValueError("Not a bounded PDF")
            temp=dest.with_suffix('.download')
            temp.write_bytes(data)
            with pymupdf.open(temp,filetype='pdf') as pdf:
                if not len(pdf):raise ValueError('No pages')
            temp.replace(dest)
        with pymupdf.open(dest) as pdf:
            title=(pdf.metadata.get('title') or f'RFC {number}').strip()
            pages=len(pdf)
        return dict(id=f'rfc-{number}',title=title,folder='Standards',kind='performance_only',source_url=url,
                    rights='RFC Editor / IETF Trust; preserve publication notices. Local evaluation only.',
                    sha256=hashlib.sha256(dest.read_bytes()).hexdigest(),pages=pages,bytes=dest.stat().st_size)
    except Exception as exc:
        return dict(source_url=url,error=str(exc))


def main():
    base=json.loads((ROOT/'evaluation/phase3-corpus.json').read_text())['documents']
    seen={hashlib.sha256((ROOT/f"corpus/pdfs/{e['id']}.pdf").read_bytes()).hexdigest() for e in base}
    added=[];failed=[]
    with ThreadPoolExecutor(max_workers=4) as pool:
        # Slightly overfetch to tolerate missing historical PDF renditions.
        for entry in pool.map(fetch,range(9000,9090)):
            if 'error' in entry:failed.append(entry)
            elif entry['sha256'] not in seen and len(added)<80:
                seen.add(entry['sha256']);added.append(entry)
                print(f"{len(base)+len(added)}/100: {entry['id']} ({entry['pages']} pages)",flush=True)
    record=dict(scope='100 genuinely distinct real PDFs; no duplicate-based scaling',documents=base+added,download_failures=failed)
    (ROOT/'evaluation/phase4-corpus.json').write_text(json.dumps(record,indent=2)+'\n')
    assert len(record['documents'])==100,f"Only {len(record['documents'])} real documents available"


if __name__=='__main__':main()
