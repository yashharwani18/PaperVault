"""Build a source-and-interface Windows setup ZIP; exclude every user document."""
from pathlib import Path
import hashlib
import json
import zipfile
import sqlite3
from contextlib import closing
ROOT=Path(__file__).resolve().parents[1]


def main():
    out=ROOT/'output';out.mkdir(exist_ok=True)
    target=out/'Local-Library-0.6.1-Windows-Setup.zip'
    roots=['knowledge_library','frontend/dist']
    files=[]
    for directory in roots:
        files.extend(p for p in (ROOT/directory).rglob('*') if p.is_file() and '__pycache__' not in p.parts)
    for name in ['model-lock.json','qwen-lock.json','requirements.lock.txt','requirements.in','README.md','BILLS_GUIDE.md','USAGE_PILOT.md','results/UPGRADE_REPORT.md','Setup-Library.cmd','Start-Library.cmd','Stop-Library.cmd','Start-Demo.cmd','Stop-Demo.cmd','Test-Offline.cmd','evaluation/confidence-policy.json',
                 'scripts/prepare_demo_paths.py','scripts/convert_presentation.ps1','scripts/setup_qwen.py','scripts/prime_encoder_cache.py',
                 'scripts/setup_desktop.ps1','scripts/setup.ps1','scripts/prepare_model.py','scripts/start_desktop.ps1','scripts/stop_desktop.ps1','scripts/test_physical_offline.ps1']:
        files.append(ROOT/name)
    demo=ROOT/'data/demo-invoices'
    if not (demo/'SYNTHETIC-DEMO.txt').is_file():raise ValueError('Only the marked synthetic demo may be packaged')
    expected_hashes={c['sha256'] for c in json.loads((ROOT/'tests/fixtures/invoice-pack/ground-truth.json').read_text())['cases']}
    with closing(sqlite3.connect(demo/'library.sqlite3')) as db:
        actual_hashes={r[0] for r in db.execute('SELECT sha256 FROM documents')}
        if actual_hashes!=expected_hashes:raise ValueError('Demo contents differ from the synthetic fixture pack; no data was packaged')
        for table in ('feedback','trash','app_tasks'):
            if db.execute('SELECT 1 FROM sqlite_master WHERE name=?',(table,)).fetchone() and db.execute(f'SELECT count(*) FROM {table}').fetchone()[0]:raise ValueError('Demo contains user activity or deleted documents; package a pristine demo only')
    files.extend((demo/'files').glob('*.pdf'));files.append(demo/'SYNTHETIC-DEMO.txt')
    staging=ROOT/'.cache/package';staging.mkdir(exist_ok=True);snapshot=staging/'demo.sqlite3'
    with closing(sqlite3.connect(demo/'library.sqlite3')) as src,closing(sqlite3.connect(snapshot)) as dst:src.backup(dst)
    files=sorted(set(files));entries={p.relative_to(ROOT).as_posix():p for p in files};entries['data/demo-invoices/library.sqlite3']=snapshot
    manifest={name:hashlib.sha256(p.read_bytes()).hexdigest() for name,p in entries.items()}
    instructions='Extract this ZIP into a permanent folder. Install uv and Python 3.12 (or allow uv to acquire Python), then double-click Setup-Library.cmd. Initial setup downloads pinned Python dependencies, the approximately 1.53 GB model and English OCR data. A built interface is included; Node is not needed for this package. Start-Library.cmd opens an empty real workspace. Start-Demo.cmd opens the separate, clearly marked 16-invoice SYNTHETIC demo. No real user documents, model weights, Python environment, credentials or benchmark corpus are included. Daily use is local. Windows GPU setup targets the validated NVIDIA CUDA configuration. This is an unsigned setup bundle, not a self-contained MSIX/EXE installer. Validation logs referenced in the developer README are retained in the original development workspace.\n'
    with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('INSTALL.txt',instructions)
        archive.writestr('release-manifest.json',json.dumps(manifest,indent=2))
        for name,p in entries.items():archive.write(p,name)
    with zipfile.ZipFile(target) as archive:
        assert archive.testzip() is None
        for name,digest in manifest.items():assert hashlib.sha256(archive.read(name)).hexdigest()==digest
        assert not any(n.startswith(('models/','.cache/','.venv/')) or (n.startswith('data/') and not n.startswith('data/demo-invoices/')) for n in archive.namelist())
    snapshot.unlink()
    record=dict(archive=str(target),bytes=target.stat().st_size,files=len(entries),sha256=hashlib.sha256(target.read_bytes()).hexdigest(),verified=True,
                limitation='Unsigned Windows setup bundle. Clean-machine installation has not been executed. Internet required on first setup. No user files included.')
    (ROOT/'results/desktop-package.json').write_text(json.dumps(record,indent=2));print(json.dumps(record,indent=2))


if __name__=='__main__':main()
