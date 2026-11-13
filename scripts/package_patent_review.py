"""Curated confidential review bundle; excludes private experimental databases."""
from pathlib import Path
import hashlib
import json
import zipfile

ROOT=Path(__file__).resolve().parents[1]


def main():
    names=[f'patent/{name}' for name in (
        'README.md','INVENTION_DISCLOSURE.md','DRAFT_CLAIMS.md','PRIOR_ART.md',
        'EXPERIMENTS.md','CONTRIBUTIONS.md','INDIA_HANDOFF.md','RED_TEAM_ASSESSMENT.md',
        'DISCOVERY_R2.md')]
    names += [f'research/patent_candidate/{name}' for name in (
        '__init__.py','engine.py','test_engine.py','run_experiments.py',
        'exact_view_baseline.py','test_exact_view.py','compare_exact_view.py',
        'query_crop.py','test_query_crop.py','measure_crop_ocr.py','audit_model_envelope.py')]
    names += [f'results/{name}' for name in (
        'patent-candidate-tests.log','patent-candidate-tests.xml',
        'patent-experiments.json','patent-memory-dense.json',
        'patent-memory-stream.json','patent-memory-candidate.json',
        'patent-redteam-tests.log','patent-redteam-tests.xml',
        'patent-exact-view-comparison.json','patent-exact-view-comparison.log',
        'patent-r2-combined-tests.log','patent-r2-combined-tests.xml',
        'patent-r2-crop-ocr.json','patent-r2-crop-ocr.log',
        'patent-r2-value_only.png','patent-r2-label_and_value.png',
        'patent-8gb-envelope.json')]
    names += ['knowledge_library/bill_amounts.py','scripts/package_patent_review.py',
              'requirements.in','requirements.lock.txt']
    hashes={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in names}
    target=ROOT/'output/Confidential-Patent-Discovery-R2.zip'
    target.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('REVIEW-NOTICE.txt',
            'Confidential attorney-review material for India. Not filed or professionally cleared. '
            'Second-pass finding: R1 is NOT recommended for filing solely on this record. '
            'R2 discovery also has close prior art and no declared high-confidence patent candidate. '
            'Read patent/DISCOVERY_R2.md for the latest 8 GB target investigation. '
            'Read patent/RED_TEAM_ASSESSMENT.md before the original claims. '
            'Human inventorship and inventive step remain unresolved. Read patent/README.md first. '
            'No original invoices, PPTs, model weights or research databases are included. '
            'Only PNG crops of the clearly marked synthetic test fixture are included. '
            'Reproducing OCR requires classic.pdf from the original project test fixtures; no PDFs are included. '
            'Local paths can appear in test/aggregate logs. Do not publish this bundle.\n')
        archive.writestr('MANIFEST.json',json.dumps(hashes,indent=2))
        for name in names:
            archive.write(ROOT/name,name)
    with zipfile.ZipFile(target) as archive:
        assert archive.testzip() is None
        assert set(archive.namelist())==set(names)|{'MANIFEST.json','REVIEW-NOTICE.txt'}
        for name,expected in hashes.items():
            assert hashlib.sha256(archive.read(name)).hexdigest()==expected
        assert not any(name.startswith(('data/','models/','.cache/')) for name in archive.namelist())
    result=dict(archive=str(target),files=len(names),bytes=target.stat().st_size,
                sha256=hashlib.sha256(target.read_bytes()).hexdigest(),verified=True,
                note='Local bundle only; no external transmission, filing or inventorship determination.')
    (ROOT/'results/patent-discovery-r2-package.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
