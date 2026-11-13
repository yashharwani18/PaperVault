"""Local PowerPoint-to-PDF import retaining slide numbers and source bytes."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import zipfile
import pymupdf
from .embedding import PROJECT


def available():
    """PPTX files are always supported via direct XML conversion; PPT check uses PowerPoint."""
    return True


def _powerpoint_com_available():
    if os.name!='nt':return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT,r'PowerPoint.Application\CLSID'):return True
    except OSError:return False


def _convert_pptx_direct(source,output):
    """Directly convert a PPTX into a slide-per-page PDF without Microsoft PowerPoint."""
    import re
    import xml.etree.ElementTree as ET
    source=Path(source)
    with zipfile.ZipFile(source) as archive:
        rels={}
        if 'ppt/_rels/presentation.xml.rels' in archive.namelist():
            try:
                tree=ET.fromstring(archive.read('ppt/_rels/presentation.xml.rels'))
                for rel in tree:
                    rid=rel.attrib.get('Id')
                    target=rel.attrib.get('Target')
                    if rid and target:rels[rid]=target
            except Exception:pass
        slides=[]
        if 'ppt/presentation.xml' in archive.namelist():
            try:
                pres_tree=ET.fromstring(archive.read('ppt/presentation.xml'))
                for el in pres_tree.iter():
                    if el.tag.endswith('sldId'):
                        for attr,val in el.attrib.items():
                            if attr.endswith('id') and val in rels:
                                target=rels[val]
                                path='ppt/'+target if not target.startswith('ppt/') else target
                                if path in archive.namelist():slides.append(path)
            except Exception:pass
        if not slides:
            slides=sorted([n for n in archive.namelist() if re.match(r'ppt/slides/slide\d+\.xml',n)],
                          key=lambda x:int(re.search(r'\d+',x).group()) if re.search(r'\d+',x) else 0)
        if not slides:
            raise ValueError('No presentation slides found in this PPTX archive.')

        doc=pymupdf.open()
        for idx,slide_name in enumerate(slides,1):
            slide_bytes=archive.read(slide_name)
            slide_tree=ET.fromstring(slide_bytes)
            paragraphs=[]
            for p_el in slide_tree.iter():
                if p_el.tag.endswith('p'):
                    p_text=''.join([t_el.text or '' for t_el in p_el.iter() if t_el.tag.endswith('t')]).strip()
                    if p_text:paragraphs.append(p_text)
            if not paragraphs:
                all_text=''.join(slide_tree.itertext()).strip()
                paragraphs=[l.strip() for l in all_text.splitlines() if l.strip()]

            # Notes check
            notes_name=f'ppt/notesSlides/notesSlide{idx}.xml'
            notes_text=''
            if notes_name in archive.namelist():
                try:
                    notes_tree=ET.fromstring(archive.read(notes_name))
                    notes_text=' '.join(''.join(notes_tree.itertext()).split()).strip()
                except Exception:pass

            page=doc.new_page(width=960,height=540)
            # Subtle slide header/footer frame
            page.draw_rect(pymupdf.Rect(30,24,930,516),color=(0.3,0.3,0.35),width=0.75)
            y=60
            title=paragraphs[0] if paragraphs else f'Slide {idx}'
            body=paragraphs[1:] if len(paragraphs)>1 else []
            page.insert_textbox(pymupdf.Rect(50,y,910,y+70),title,fontsize=22,fontname='helv',color=(0.1,0.1,0.15))
            y+=80
            if body:
                body_content='\n\n'.join(f'• {p}' for p in body)
                page.insert_textbox(pymupdf.Rect(50,y,910,480),body_content,fontsize=15,fontname='helv',color=(0.2,0.2,0.25))
            if notes_text:
                page.insert_textbox(pymupdf.Rect(50,490,910,510),f'Speaker note: {notes_text[:200]}',fontsize=10,fontname='helv',color=(0.5,0.5,0.55))

        doc.save(str(output))
        doc.close()
        return len(slides)


def convert(source,root):
    source=Path(source).resolve();root=Path(root).resolve()
    if source.suffix.lower() not in ('.ppt','.pptx'):raise ValueError('Choose .ppt or .pptx; macro-enabled presentations are unsupported')
    ext=source.suffix.lower()
    if ext=='.ppt' and not _powerpoint_com_available():
        raise ValueError('Direct .ppt import needs Microsoft PowerPoint on this Windows PC. Save as .pptx or export as PDF.')
    with source.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
    if ext=='.pptx':
        try:
            with zipfile.ZipFile(source) as archive:
                names=archive.namelist()
                if '[Content_Types].xml' not in names or 'ppt/presentation.xml' not in names:raise ValueError('This file is not a valid PPTX presentation')
                if any(n.lower().endswith('vbaproject.bin') for n in names):raise ValueError('Macro-containing presentations are unsupported; export a PDF')
                if sum(i.file_size for i in archive.infolist())>1024**3:raise ValueError('The expanded presentation exceeds 1 GiB')
        except zipfile.BadZipFile as exc:raise ValueError('Cannot read this PPTX. It may be damaged or password-protected.') from exc
    directory=root/'conversions'/digest;directory.mkdir(parents=True,exist_ok=True)
    output=directory/'slides.pdf';record=directory/'conversion.json'
    if output.is_file() and record.is_file():
        metadata=json.loads(record.read_text(encoding='utf-8-sig'))
        with pymupdf.open(output) as pdf:
            if pdf.page_count!=metadata['slides']:raise ValueError('Cached slide conversion is incomplete; retry with the original file')
    else:
        temporary=directory/'rendering.pdf';result=directory/'rendering.json'
        converted_via_pp=False
        if ext in ('.ppt','.pptx') and _powerpoint_com_available() and (PROJECT/'scripts/convert_presentation.ps1').is_file():
            try:
                completed=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-STA','-ExecutionPolicy','Bypass','-File',str(PROJECT/'scripts/convert_presentation.ps1'),'-Source',str(source),'-Output',str(temporary),'-Result',str(result)],
                                         capture_output=True,text=True,timeout=120,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                if completed.returncode==0 and temporary.is_file() and result.is_file():
                    metadata=json.loads(result.read_text(encoding='utf-8-sig'))
                    with pymupdf.open(temporary) as pdf:
                        if not pdf.needs_pass and pdf.page_count==metadata['slides'] and pdf.page_count>0:
                            temporary.replace(output);result.replace(record)
                            converted_via_pp=True
            except (subprocess.TimeoutExpired,Exception):
                converted_via_pp=False
            finally:
                temporary.unlink(missing_ok=True);result.unlink(missing_ok=True)

        if not converted_via_pp:
            if ext=='.pptx':
                # Direct standalone XML conversion (no PowerPoint required)
                slides_count=_convert_pptx_direct(source,temporary)
                with pymupdf.open(temporary) as pdf:
                    if pdf.needs_pass or pdf.page_count!=slides_count or pdf.page_count==0:
                        raise ValueError('Direct PPTX conversion could not read presentation slides.')
                metadata=dict(slides=slides_count,converter='direct_pptx_xml',source=source.name)
                record.write_text(json.dumps(metadata,ensure_ascii=False),encoding='utf-8')
                temporary.replace(output)
            else:
                raise ValueError('PowerPoint could not convert this presentation. Check that it opens normally, or export it as PDF.')

    originals=root/'originals';originals.mkdir(exist_ok=True)
    original=originals/(digest+source.suffix.lower())
    if not original.exists():shutil.copyfile(source,original)
    return output,dict(original_name=source.name,source_path=str(original.relative_to(root)),source_sha256=digest,
                       format=source.suffix.lower()[1:],slides=metadata['slides'],converter=metadata.get('converter','direct_pptx_xml'))

