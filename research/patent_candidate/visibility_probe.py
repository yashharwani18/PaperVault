"""Conventional PDF paint-state triage. Research, not a visibility proof.

Does not OCR, reject search results, infer fraud or modify any document.
Hidden text can be a completely legitimate searchable scan layer.
"""
import pymupdf


def inspect_occurrences(page, literal):
    if not literal:
        raise ValueError('A nonempty literal is required')
    paint=page.get_bboxlog()
    hits=[]
    for span in page.get_texttrace():
        chars=span['chars']
        text=''.join(chr(c[0]) for c in chars)
        start=0
        while (index:=text.find(literal,start))>=0:
            selected=chars[index:index+len(literal)]
            box=pymupdf.Rect(selected[0][3])
            for char in selected[1:]:box|=pymupdf.Rect(char[3])
            display_box=box*page.rotation_matrix
            reasons=[]
            if span['type']==3:reasons.append('not_painted_render_mode')
            if span['opacity']==0:reasons.append('zero_opacity')
            if not display_box.intersects(page.rect):reasons.append('outside_display_page')
            later=[]
            for seq,(kind,rect,*_) in enumerate(paint):
                # Intersection is only a possible occluder. Bounding boxes do
                # not prove opaque coverage or actual glyph visibility.
                if seq>span['seqno'] and kind in ('fill-path','fill-image') and box.intersects(pymupdf.Rect(rect)):
                    later.append(dict(sequence=seq,kind=kind))
            if later:reasons.append('possible_later_paint_overlap')
            hits.append(dict(literal=literal,bbox=list(box),sequence=span['seqno'],
                rendering_type=span['type'],opacity=span['opacity'],reasons=reasons,
                possible_occluders=later,
                outcome='needs_visual_check' if reasons else 'no_simple_visibility_flag',
                limitation='Neither outcome establishes visible agreement, OCR correctness or fraud.'))
            start=index+len(literal)
    return hits
