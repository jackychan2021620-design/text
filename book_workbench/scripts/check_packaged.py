"""Verify actual packaged startup output and bundled OCR independent of system PATH."""
import json
import sqlite3
import subprocess
import sys
from pathlib import Path
root=Path(sys.argv[1]).resolve();data=Path(sys.argv[2]).resolve()
assert (root/'BookWorkbench.exe').is_file()
with sqlite3.connect(data/'books.sqlite3') as db:
    assert db.execute('PRAGMA user_version').fetchone()[0]==1
    assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
    assert db.execute("SELECT count(*) FROM sqlite_master WHERE name='video_review_tasks'").fetchone()[0]==1
report=json.loads((data/'packaged-smoke.json').read_text(encoding='utf-8'))
print('Actual packaged smoke report:',report,flush=True)
assert report['version']=='1.1.1',report
assert report['collection_recovery'] is True,report
assert report['ocr_fields']['creators']==100 and report['ocr_fields']['sales']==12345,report
assert report['frozen'] is True,report
assert report['platform']=='windows',report
assert report['ocr_12345'] is True,report
assert Path(report['ocr_executable']).resolve().is_relative_to(root), (root,report)
assert report['python_executable'].lower().endswith('bookworkbench.exe')
print('Verified packaged Windows UI, SQLite, bundled Tesseract and OCR functional request:',report)
