"""Explicit online setup; normal searches never download models."""
import hashlib
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import urllib.request
import zipfile

ROOT=Path(__file__).resolve().parents[1]
LOCK=json.loads((ROOT/'qwen-lock.json').read_text())


def download(url,path,sha,size=None):
    if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest()==sha:return
    path.parent.mkdir(parents=True,exist_ok=True)
    partial=path.with_suffix(path.suffix+'.partial')
    print('Downloading',path.name,flush=True)
    # Bounded ranges avoid long stalled streams and can resume interrupted setup.
    offset=partial.stat().st_size if partial.exists() else 0
    if size is None:
        with urllib.request.urlopen(urllib.request.Request(url,headers={'Range':'bytes=0-0'}),timeout=30) as response:
            size=int(response.headers['Content-Range'].split('/')[-1])
    def fetch_range(start,end):
        for attempt in range(5):
            try:
                request=urllib.request.Request(url,headers={'Range':f'bytes={start}-{end}'})
                with urllib.request.urlopen(request,timeout=30) as response:
                    if response.status!=206 or response.headers.get('Content-Range')!=f'bytes {start}-{end}/{size}':raise ValueError('Server did not honor download range')
                    block=response.read()
                if len(block)!=end-start+1:raise OSError('Incomplete download range')
                return block
            except (OSError,TimeoutError):
                if attempt==4:raise
    with ThreadPoolExecutor(max_workers=4) as pool:
        while offset<size:
            ranges=[(start,min(start+2*1024*1024,size)-1) for start in range(offset,min(offset+8*1024*1024,size),2*1024*1024)]
            futures=[pool.submit(fetch_range,start,end) for start,end in ranges]
            for future in futures:
                block=future.result()
                with partial.open('ab') as target:target.write(block)
                offset+=len(block)
            print(f'{path.name}: {offset}/{size} bytes',flush=True)
    if hashlib.sha256(partial.read_bytes()).hexdigest()!=sha:raise ValueError('Download checksum mismatch')
    partial.replace(path)


def main():
    model=ROOT/'models/qwen3-0.6b'/LOCK['filename']
    download(f"https://huggingface.co/{LOCK['repository']}/resolve/{LOCK['revision']}/{LOCK['filename']}",model,LOCK['sha256'],LOCK['size_bytes'])
    archive=ROOT/'.cache/qwen-runtime'/f"{LOCK['runtime_tag']}.zip"
    download(LOCK['runtime_url'],archive,LOCK['runtime_sha256'])
    runtime=ROOT/'models/qwen-runtime'/LOCK['runtime_tag']
    runtime.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(archive) as bundle:
        for member in bundle.infolist():
            destination=(runtime/member.filename).resolve()
            if not destination.is_relative_to(runtime.resolve()):raise ValueError('Unsafe archive entry')
        bundle.extractall(runtime)
    print('Qwen model and official Windows CPU runtime ready; all checksums verified.',flush=True)


if __name__=='__main__':main()
