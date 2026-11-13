"""Rebind only the clearly marked packaged synthetic demo's source paths."""
from pathlib import Path
import sqlite3
from contextlib import closing
ROOT=Path(__file__).resolve().parents[1]
demo=ROOT/'data/demo-invoices'
if not (demo/'SYNTHETIC-DEMO.txt').is_file():raise SystemExit('The synthetic demo is not installed in this bundle.')
with closing(sqlite3.connect(demo/'library.sqlite3')) as db:
    with db:db.execute('UPDATE documents SET original_path=? || managed_path',(str(demo)+'/',))
