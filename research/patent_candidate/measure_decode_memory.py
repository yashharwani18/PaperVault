"""R23 isolated Windows process measurements of actual MuPDF rendering.

Conventional lossless source tiling, not a streaming importer, mobile result,
hard allocation bound, representative scan corpus or novel decoder.
"""
import hashlib
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time
import uuid

import psutil
import pymupdf


def memory():
    info=psutil.Process().memory_info()
    if not hasattr(info,'peak_wset'):raise RuntimeError('This experiment requires Windows peak working-set reporting')
    return dict(rss=info.rss,peak_working_set=info.peak_wset)


def worker(path,clip):
    with pymupdf.open(path) as doc:
        page=doc[0];before=memory();start=time.perf_counter()
        pix=page.get_pixmap(matrix=pymupdf.Matrix(8,8),
            clip=None if clip is None else pymupdf.Rect(clip),colorspace=pymupdf.csRGB,alpha=False)
        render_s=time.perf_counter()-start
        digest=hashlib.sha256(pix.samples_mv).hexdigest()
        after=memory()
        return dict(before=before,after=after,
            historical_peak_increase=max(0,after['peak_working_set']-before['peak_working_set']),
            width=pix.width,height=pix.height,output_bytes=pix.width*pix.height*pix.n,
            output_sha256=digest,render_s=render_s)


def fixtures(work):
    from PIL import Image,ImageDraw
    source=Image.new('RGB',(4096,4096),'white');draw=ImageDraw.Draw(source)
    for y in range(0,4096,512):
        for x in range(0,4096,512):
            draw.rectangle((x,y,x+511,y+511),outline=(40,40,40),width=2)
            draw.text((x+12,y+12),f'SYNTHETIC SOURCE TILE {x//512},{y//512}',fill=(0,0,0))
            draw.line((x+10,y+70,x+490,y+70),fill=(160,160,160),width=1)
    import io
    raw=io.BytesIO();source.save(raw,format='PNG')
    with pymupdf.open() as doc:
        page=doc.new_page(width=512,height=512);page.insert_image(page.rect,stream=raw.getvalue())
        doc.save(work/'monolithic.pdf',deflate=True)
    with pymupdf.open() as doc:
        page=doc.new_page(width=512,height=512)
        for y in range(0,4096,512):
            for x in range(0,4096,512):
                raw=io.BytesIO();source.crop((x,y,x+512,y+512)).save(raw,format='PNG')
                page.insert_image(pymupdf.Rect(x/8,y/8,(x+512)/8,(y+512)/8),stream=raw.getvalue())
        doc.save(work/'tiled.pdf',deflate=True)
    for name,progressive in (('jpeg',False),('progressive',True)):
        raw=io.BytesIO();source.save(raw,format='JPEG',quality=92,progressive=progressive)
        with pymupdf.open() as doc:
            page=doc.new_page(width=512,height=512);page.insert_image(page.rect,stream=raw.getvalue())
            doc.save(work/(name+'.pdf'),deflate=True)
        if progressive:
            # Conventional derived cache, built only after full JPEG decoding.
            # Its preprocessing/ingestion memory is explicitly outside render measurements.
            with Image.open(io.BytesIO(raw.getvalue())) as encoded:
                decoded=encoded.convert('RGB')
            with pymupdf.open() as doc:
                page=doc.new_page(width=512,height=512)
                for y in range(0,4096,512):
                    for x in range(0,4096,512):
                        tile=io.BytesIO();decoded.crop((x,y,x+512,y+512)).save(tile,format='PNG')
                        page.insert_image(pymupdf.Rect(x/8,y/8,(x+512)/8,(y+512)/8),stream=tile.getvalue())
                doc.save(work/'progressive_tiled.pdf',deflate=True)
            decoded.close()
    source.close()


def run():
    if os.name!='nt':raise RuntimeError('R23 measurement is scoped to Windows')
    root=Path(__file__).resolve().parents[2]
    work=root/'data/patent-research'/('r23-decode-'+uuid.uuid4().hex);work.mkdir(parents=True)
    fixtures(work)
    specs=[('monolithic_small','monolithic.pdf',[0,0,8,8]),
           ('tiled_small','tiled.pdf',[0,0,8,8]),
           ('monolithic_seam','monolithic.pdf',[62.5,62.5,70.5,70.5]),
           ('tiled_seam','tiled.pdf',[62.5,62.5,70.5,70.5]),
           ('monolithic_full','monolithic.pdf',None),
           ('jpeg_small','jpeg.pdf',[0,0,8,8]),
           ('progressive_small','progressive.pdf',[0,0,8,8]),
           ('progressive_tiled_small','progressive_tiled.pdf',[0,0,8,8]),
           ('jpeg_seam','jpeg.pdf',[62.5,62.5,70.5,70.5]),
           ('progressive_seam','progressive.pdf',[62.5,62.5,70.5,70.5]),
           ('progressive_tiled_seam','progressive_tiled.pdf',[62.5,62.5,70.5,70.5])]
    rows=[]
    for round_number in range(3):
        # Alternate ordering; every render is in a separate fresh child process.
        for name,file,clip in (specs if round_number%2==0 else list(reversed(specs))):
            completed=subprocess.run([sys.executable,'-m','research.patent_candidate.measure_decode_memory',
                '--worker',str(work/file),json.dumps(clip)],cwd=root,capture_output=True,text=True,
                encoding='utf-8',timeout=30,creationflags=subprocess.CREATE_NO_WINDOW)
            if completed.returncode:raise RuntimeError(completed.stderr)
            rows.append(dict(case=name,round=round_number,**json.loads(completed.stdout)))
    for round_number in range(3):
        by_name={r['case']:r for r in rows if r['round']==round_number}
        for where in ('small','seam'):
            mono,tile=(by_name[f'{prefix}_{where}'] for prefix in ('monolithic','tiled'))
            assert mono['output_sha256']==tile['output_sha256']
            assert (mono['width'],mono['height'],mono['output_bytes'])==(64,64,12288)
            jpeg,progressive,cache=(by_name[f'{prefix}_{where}'] for prefix in ('jpeg','progressive','progressive_tiled'))
            assert jpeg['output_sha256']==progressive['output_sha256']==cache['output_sha256']
    summary={name:dict(median_peak_increase=statistics.median(r['historical_peak_increase'] for r in rows if r['case']==name),
        median_peak_working_set=statistics.median(r['after']['peak_working_set'] for r in rows if r['case']==name),
        median_render_s=statistics.median(r['render_s'] for r in rows if r['case']==name),
        output_bytes=next(r['output_bytes'] for r in rows if r['case']==name)) for name,_,_ in specs}
    report=dict(date='2026-10-21',fixtures=str(work),pymupdf=pymupdf.VersionBind,
        windows_memory_metric='psutil peak_wset: OS historical peak working set',runs=rows,summary=summary,
        files={name:dict(bytes=(work/name).stat().st_size) for name in
               ('monolithic.pdf','tiled.pdf','jpeg.pdf','progressive.pdf','progressive_tiled.pdf')},
        source_uncompressed_rgb_bytes=4096*4096*3,
        limits=['Synthetic RGB scans, fixed 8x rendering; no alpha/mask/rotation or custom color-profile variants; inspected JPEG images use ICCBased metadata',
                'Parent creates both representations with a whole decoded image; conversion cost is excluded',
                'Hash equality covers two requested 64x64 regions, not all rendering conditions',
                'OS historical peak changes are observed measurements, not exact allocations or hard bounds',
                'Fresh processes do not imply a cold OS file cache; timing is exploratory desktop evidence',
                'No OCR, neural model, Android, battery or production-library execution',
                'Conventional source tiling, not a new decoding algorithm or patentability finding'])
    (root/'results/patent-r23-decode-memory.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(dict(fixtures=str(work),summary=summary,files=report['files']),indent=2))


if __name__=='__main__':
    if len(sys.argv)>1 and sys.argv[1]=='--worker':print(json.dumps(worker(Path(sys.argv[2]),json.loads(sys.argv[3]))))
    else:run()
