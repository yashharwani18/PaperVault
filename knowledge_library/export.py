"""Source-only context PDFs. Passages are read from the index, never supplied by clients."""
from pathlib import Path
import re
from xml.sax.saxutils import escape
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, KeepTogether
from reportlab.lib.pagesizes import A4


def context_pdf(library,query,chunk_ids,destination):
    if not query.strip() or len(query)>4096 or not 1<=len(chunk_ids)<=25:
        raise ValueError('Select 1-25 passages and provide a query of at most 4096 characters')
    font=Path('C:/Windows/Fonts/arial.ttf')
    if not font.is_file():
        raise ValueError('Export requires a local Unicode TrueType font; configure it for this OS')
    if 'LibraryUnicode' not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont('LibraryUnicode',str(font)))
    body=ParagraphStyle('Body',fontName='LibraryUnicode',fontSize=10,leading=15,textColor=colors.HexColor('#27272d'),spaceAfter=10,wordWrap='CJK')
    title=ParagraphStyle('Title',parent=body,fontSize=24,leading=30,spaceAfter=16)
    sub=ParagraphStyle('Source',parent=body,fontSize=10,leading=15,textColor=colors.HexColor('#6d44ba'),spaceAfter=8,keepWithNext=True)
    def safe(text):
        return escape(re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]','',text)).replace('\n','<br/>')
    story=[Paragraph('Library context',title),Paragraph('QUERY',sub),Paragraph(safe(query),body),Spacer(1,12)]
    references=[]
    for ordinal,chunk_id in enumerate(dict.fromkeys(chunk_ids),1):
        row=library.db.execute('SELECT c.*,d.filename,f.name folder FROM chunks c JOIN documents d ON d.id=c.document_id JOIN folders f ON f.id=d.folder_id WHERE c.id=?',(chunk_id,)).fetchone()
        if row is None:raise ValueError('A selected passage was removed or re-indexed. Search again before exporting.')
        references.append(dict(chunk_id=chunk_id,filename=row['filename'],page=row['page_number'],text=row['text']))
        unit=library.page(row['document_id'],row['page_number'])
        references[-1].update(location=unit['location'],location_label=unit['location_label'])
        heading=f"{ordinal}. {row['filename']} | {row['folder']} | {unit['location_label']}"
        story.extend([Paragraph(safe(heading),sub),Paragraph(safe(row['text']),body)])
        story.append(Spacer(1,16))
    story += [Spacer(1,12),Paragraph('Source excerpts only. No generated answers. References identify physical PDF pages or labeled native source locations. Non-printing control characters are omitted for rendering.',sub)]
    def footer(canvas,doc):
        canvas.setFont('LibraryUnicode',8);canvas.setFillColor(colors.HexColor('#71717a'))
        canvas.drawString(42,26,'LOCAL KNOWLEDGE LIBRARY');canvas.drawRightString(A4[0]-42,26,str(doc.page))
    SimpleDocTemplate(str(destination),pagesize=A4,leftMargin=42,rightMargin=42,topMargin=44,bottomMargin=46,title='Library context',author='Local Knowledge Library').build(story,onFirstPage=footer,onLaterPages=footer)
    return references
