"""Measure source-field extraction on the frozen synthetic invoice pack."""
from pathlib import Path
import json
import sys
import datetime as dt
import uuid
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from knowledge_library.library import Library
from knowledge_library.embedding import EmbeddingGemma
from knowledge_library.pdf import PdfOptions
from knowledge_library.chunking import ChunkingConfig
from knowledge_library.bills import suggestions,normalized
from knowledge_library.server import offline_guard


def main():
    offline_guard();fixture=ROOT/'tests/fixtures/invoice-pack';truth=json.loads((fixture/'ground-truth.json').read_text())
    root=ROOT/'data/invoice-validation'/uuid.uuid4().hex;model=EmbeddingGemma();rows=[]
    with Library(root,model) as lib:
        folder=lib.create_folder('Synthetic invoice audit')['id']
        for case in truth['cases']:
            imported=lib.import_pdf(fixture/case['file'],folder,chunking=ChunkingConfig(256,64),pdf_options=PdfOptions(ocr=True,tessdata=str(ROOT/'models/tessdata')))
            actual=suggestions(lib,imported['document']['id']);checks={}
            for field,expected in case['expected'].items():
                value=actual[field]
                checks[field]=normalized(str(value or ''))==normalized(str(expected or ''))
            rows.append(dict(file=case['file'],sha256=case['sha256'],supported=case['supported'],expected=case['expected'],actual=actual,field_correct=checks,document_id=imported['document']['id']))
            print(case['file'],sum(checks.values()),'/',len(checks),'supported',case['supported'],flush=True)
        integrity=lib.verify()
    supported=[r for r in rows if r['supported']]
    metrics={field:dict(correct=sum(r['field_correct'][field] for r in supported),total=len(supported),accuracy=sum(r['field_correct'][field] for r in supported)/len(supported),missing=sum(not r['actual'][field] for r in supported)) for field in supported[0]['field_correct']}
    record=dict(recorded_at=dt.datetime.now(dt.timezone.utc).isoformat(),library=str(root),provenance=truth['provenance'],
                limitations='Synthetic layouts authored by the coding agent. Not independent real-world accuracy. Unsupported cases excluded from supported metrics and retained in details.',
                supported_documents=len(supported),unsupported_documents=len(rows)-len(supported),fields=metrics,
                complete_record_accuracy=sum(all(r['field_correct'].values()) for r in supported)/len(supported),rows=rows,integrity=integrity)
    (ROOT/'results/invoice-pack-validation.json').write_text(json.dumps(record,indent=2));print(json.dumps(metrics,indent=2))
    assert integrity['passed']


if __name__=='__main__':main()
