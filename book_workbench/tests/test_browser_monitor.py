"""Actual browser renderer, entirely offline; no live-account claim."""
import os
import subprocess
import sys
from pathlib import Path


def browser_test_env():
    env=dict(os.environ,QT_QPA_PLATFORM='offscreen',QTWEBENGINE_CHROMIUM_FLAGS='--disable-gpu --disable-dev-shm-usage')
    # Root container cannot create Chromium's namespace sandbox. This exception
    # is scoped to this network-blocked test subprocess, never normal app startup.
    if hasattr(os,'geteuid') and os.geteuid()==0:env['QTWEBENGINE_DISABLE_SANDBOX']='1'
    return env


def test_real_browser_engine_reads_loaded_public_responses_offline(tmp_path):
    code='''
import json,sys
from workbench.browser_checks import browser_smoke
from PySide6.QtWidgets import QApplication
app=QApplication([])
print(json.dumps(browser_smoke(sys.argv[1])))
'''
    p=subprocess.run([sys.executable,'-c',code,str(tmp_path/'browser')],cwd=Path(__file__).resolve().parents[1],env=browser_test_env(),capture_output=True,text=True,timeout=50)
    assert p.returncode==0,p.stderr+'\n'+p.stdout
    assert '"renderer": true' in p.stdout;assert '"public_response": true' in p.stdout


def test_browser_only_navigates_official_pages():
    from workbench.browser_runtime import browser_url
    assert browser_url('https://passport.douyin.com/login/')
    assert browser_url('https://www.douyin.com/user/owner')
    for url in ('http://www.douyin.com/user/owner','file:///etc/passwd','https://douyin.com.evil.org/','https://u:p@www.douyin.com/'):
        assert not browser_url(url)
