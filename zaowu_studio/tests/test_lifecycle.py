import os
import subprocess
import sys
import struct
from pathlib import Path
from studio.store import Store
from conftest import record

def test_app_entrypoint_restarts_and_keeps_data(tmp_path):
    root=tmp_path/'lifecycle';store=Store(root);record(store,'offers',name='重启保留');store.close()
    cwd=Path(__file__).resolve().parents[1]
    for _ in range(2):
        env=dict(os.environ,ZAOWU_STUDIO_DATA_DIR=str(root),QT_QPA_PLATFORM='offscreen')
        run=subprocess.run([sys.executable,'launch.py','--smoke-test'],cwd=cwd,env=env,capture_output=True,text=True,timeout=20)
        assert run.returncode==0,run.stderr
    store=Store(root)
    try:
        assert store.rows('offers')[0]['name']=='重启保留'
        assert len(list((root/'backups').glob('*.sqlite3')))==1
    finally:store.close()

def test_icon_has_seven_sizes():
    raw=(Path(__file__).resolve().parents[1]/'resources'/'brand.ico').read_bytes()
    assert struct.unpack('<HHH',raw[:6])==(0,1,7)
    sizes=[raw[6+16*i] or 256 for i in range(7)]
    assert sizes==[16,24,32,48,64,128,256]

def test_entrypoint_import_process_isolation_smoke(tmp_path):
    cwd=Path(__file__).resolve().parents[1]
    env=dict(os.environ,ZAOWU_STUDIO_DATA_DIR=str(tmp_path/'isolated'),QT_QPA_PLATFORM='offscreen')
    result=subprocess.run([sys.executable,'launch.py','--import-isolation-smoke-test'],cwd=cwd,env=env,capture_output=True,text=True,timeout=15)
    assert result.returncode==0,result.stderr

def test_main_ui_does_not_load_embedded_chromium():
    cwd=Path(__file__).resolve().parents[1]
    script='import sys; import studio.ui; assert "PySide6.QtWebEngineWidgets" not in sys.modules; from studio.reference_view import ReferenceDialog; assert "PySide6.QtWebEngineWidgets" not in sys.modules'
    result=subprocess.run([sys.executable,'-c',script],cwd=cwd,capture_output=True,text=True,timeout=10)
    assert result.returncode==0,result.stderr
