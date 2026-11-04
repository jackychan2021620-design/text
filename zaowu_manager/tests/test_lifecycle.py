import os
import subprocess
import sys
from pathlib import Path
from zaowu.store import Store
from conftest import record

def test_entrypoint_start_shutdown_restart_and_automatic_backup(tmp_path):
    root=tmp_path/'lifecycle'
    store=Store(root)
    record(store,'products',name='持久化验收项目',price=12800)
    store.close()
    script='''
from PySide6.QtCore import QTimer
import zaowu.__main__ as entry
original = entry.QApplication
def timed_app(argv):
    app = original(argv)
    QTimer.singleShot(350, app.quit)
    return app
entry.QApplication = timed_app
raise SystemExit(entry.main())
'''
    environment=dict(os.environ,ZAOWU_DATA_DIR=str(root),QT_QPA_PLATFORM='offscreen')
    for _ in range(2):
        result=subprocess.run([sys.executable,'-c',script],cwd=Path(__file__).resolve().parents[1],env=environment,capture_output=True,text=True,timeout=20)
        assert result.returncode==0,result.stderr
    reopened=Store(root)
    assert reopened.rows('products')[0]['name']=='持久化验收项目'
    assert reopened.db.execute('SELECT count(*) FROM reports').fetchone()[0]==2
    assert len(list((root/'backups').glob('*.sqlite3')))==1
    reopened.close()
