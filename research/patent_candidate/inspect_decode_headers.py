"""R24 inspect synthetic R23 JPEG headers without producing pixels.

Marker scan is bounded, but PyMuPDF supplies the complete compressed stream.
Not a general JPEG validator, streaming reader or whole-process memory bound.
"""
import json
from pathlib import Path

import pymupdf


def frame_header(data,*,scan_limit=65536):
    if data[:2]!=b'\xff\xd8':return dict(status='unknown',reason='not_jpeg_soi')
    pos=2;limit=min(len(data),scan_limit)
    frames={0xc0,0xc1,0xc2,0xc3,0xc5,0xc6,0xc7,0xc9,0xca,0xcb,0xcd,0xce,0xcf}
    while pos<limit:
        if data[pos]!=0xff:return dict(status='unknown',reason='malformed_marker')
        while pos<limit and data[pos]==0xff:pos+=1
        if pos>=limit:break
        marker=data[pos];pos+=1
        if marker in (0xda,0xd9):return dict(status='unknown',reason='no_frame_before_scan_or_end')
        if marker==1 or 0xd0<=marker<=0xd8:continue
        if pos+2>limit:break
        length=int.from_bytes(data[pos:pos+2],'big')
        if length<2 or pos+length>len(data):return dict(status='unknown',reason='invalid_segment_length')
        if pos+length>limit:break
        if marker in frames:
            if length<8:return dict(status='unknown',reason='short_frame')
            components=data[pos+7]
            if length!=8+3*components:return dict(status='unknown',reason='frame_component_length')
            return dict(status='frame_header_observed',marker=f'FF{marker:02X}',
                encoding={0xc0:'baseline_dct',0xc2:'progressive_dct'}.get(marker,'other_frame'),
                precision=data[pos+2],height=int.from_bytes(data[pos+3:pos+5],'big'),
                width=int.from_bytes(data[pos+5:pos+7],'big'),components=components,
                inspected_through_offset=pos+length)
        pos+=length
    return dict(status='unknown',reason='header_scan_allowance_or_input_exhausted')


def run():
    root=Path(__file__).resolve().parents[2]
    previous=json.loads((root/'results/patent-r23-decode-memory.json').read_text(encoding='utf-8'))
    work=Path(previous['fixtures']);rows=[]
    for file,expected in (('jpeg.pdf','baseline_dct'),('progressive.pdf','progressive_dct')):
        with pymupdf.open(work/file) as doc:
            images=doc[0].get_images(full=True);assert len(images)==1
            xref,smask,width,height,bits,colorspace,alternate,name,filter_name,referencer=images[0]
            assert filter_name=='DCTDecode'
            data=doc.xref_stream_raw(xref)
            header=frame_header(data);short=frame_header(data,scan_limit=32)
            assert header['encoding']==expected and header['width']==width and header['height']==height
            assert short['status']=='unknown'
            rows.append(dict(file=file,pdf_metadata=dict(width=width,height=height,bits=bits,
                colorspace=colorspace,filter=filter_name,smask=smask),compressed_stream_bytes=len(data),
                frame=header,limited_scan=short))
    assert rows[0]['pdf_metadata']==rows[1]['pdf_metadata']
    report=dict(date='2026-10-22',fixtures=str(work),cases=rows,
        limits=['Only two generated R23 streams inspected; no arbitrary/untrusted JPEG validation',
                'Header recognition is not pixel verification, decode resource estimation or a memory bound',
                'Complete compressed streams loaded before the bounded marker scan; not bounded I/O/memory',
                'No pixel generation, OCR, model execution, production changes or new invention'])
    (root/'results/patent-r24-decode-headers.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2))


if __name__=='__main__':run()
