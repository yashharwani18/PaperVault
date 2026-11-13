"""Real CUDA semantic retrieval across isolated PDF, text and Office originals."""
import json
from pathlib import Path
import uuid
import zipfile
import pymupdf
from knowledge_library.library import Library
from knowledge_library.embedding import EmbeddingGemma
from tests.test_text_document_api import xlsx

def main():
    base=Path(__file__).resolve().parents[1]
    root=base/'.cache/text-real-model'/uuid.uuid4().hex;root.mkdir(parents=True)
    fixtures={
        'notes.txt':('Impedance matching reduces reflections on a transmission line.','How do you reduce reflected waves in a transmission line?'),
        'budget.csv':('Category,Amount\nAnnual maintenance budget,13600\n','What is the yearly maintenance budget?'),
        'report.docx':(None,'What reduces electromagnetic interference in cables?'),
        'revenue.xlsx':(None,'What retained revenue is recorded for Acme?'),
        'original.pdf':(None,'Which process allows plants to convert sunlight into chemical energy?')}
    for name,(text,_) in fixtures.items():
        p=root/name
        if text:p.write_text(text,encoding='utf-8')
        elif name.endswith('xlsx'):p.write_bytes(xlsx())
        elif name.endswith('docx'):
            with zipfile.ZipFile(p,'w') as z:
                z.writestr('word/document.xml','<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Shielded twisted-pair cables reduce electromagnetic interference and protect transmitted signals.</w:t></w:r></w:p></w:body></w:document>')
        else:
            with pymupdf.open() as pdf:
                pdf.new_page().insert_text((40,60),'Photosynthesis converts sunlight into chemical energy in plants.');pdf.save(p)
    model=EmbeddingGemma(device='cuda');report={'checks':[]}
    with Library(root/'library',model) as lib:
        folder=lib.create_folder('Mixed original formats')['id']
        for name in fixtures:lib.import_document(root/name,folder)
        for name,(_,query) in fixtures.items():
            result=lib.search(query,top_k=5,min_score=None,mode='semantic')
            hits=result['results'];assert hits and hits[0]['filename']==name,(name,[(h['filename'],h['score']) for h in hits])
            report['checks'].append(dict(query=query,first_source=hits[0]['filename'],location=hits[0]['location_label'],score=hits[0]['score']))
        assert lib.verify()['passed']
        report['model']=model.signature;report['stats']=model.stats
    output=base/'results/text-expansion';output.mkdir(exist_ok=True)
    (output/'real-model-report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2))

if __name__=='__main__':main()
