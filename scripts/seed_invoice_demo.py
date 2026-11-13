"""Copy verified synthetic invoice vectors into a clearly separate demo library."""
import json
import shutil
import sqlite3
import sys
from pathlib import Path
from contextlib import closing
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from knowledge_library.library import Library
from knowledge_library.bills import auto_extract


def main():
    report=json.loads((ROOT/'results/invoice-pack-validation.json').read_text());source=Path(report['library']);target=ROOT/'data/demo-invoices'
    if (target/'library.sqlite3').exists():raise SystemExit('Demo already exists; it was preserved')
    target.mkdir(parents=True,exist_ok=True)
    with closing(sqlite3.connect(source/'library.sqlite3')) as src,closing(sqlite3.connect(target/'library.sqlite3')) as dst:src.backup(dst)
    shutil.copytree(source/'files',target/'files',dirs_exist_ok=True)
    with Library(target) as lib:
        for doc in lib.documents():auto_extract(lib,doc['id'],force=True)
        result=lib.verify();assert result['passed']
        print('Separate synthetic demo ready:',target,'documents:',len(lib.documents()))
    (target/'SYNTHETIC-DEMO.txt').write_text('Every invoice in this library is a software test fixture. No transaction is real. Your normal data/desktop library is separate.\n')


if __name__=='__main__':main()
