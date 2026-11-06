import json,time,sys
from datetime import datetime,timezone
from PySide6.QtCore import QUrl
from workbench.system_browser import SystemTransport,find_browser
from workbench.monitor_session import MonitorSession
from test_monitoring import OWNER,URL


def test_loopback_transport_construction_and_owned_profile(app,tmp_path):
    t=SystemTransport(tmp_path);assert t.root==tmp_path/'browser'/'system-douyin';assert not t._ready
    assert t.url().toString()=='about:blank';t.shutdown()


def test_browser_discovery_uses_regular_installed_browser(monkeypatch,tmp_path):
    monkeypatch.setenv('ProgramFiles(x86)',str(tmp_path));monkeypatch.delenv('ProgramFiles',raising=False);monkeypatch.delenv('LOCALAPPDATA',raising=False)
    assert find_browser() is None
    edge=tmp_path/'Microsoft/Edge/Application/msedge.exe';edge.parent.mkdir(parents=True);edge.touch()
    assert find_browser()==edge

class Page:
    def __init__(self):self.scripts=[];self.urls=[]
    def load(self,url):self.urls.append(url.toString())
    def url(self):return QUrl(URL)
    def evaluate(self,script,callback):self.scripts.append(script);callback(True)
    def show(self):pass
    def stop(self):pass
    def shutdown(self):pass


def test_first_old_pinned_batch_does_not_end_recent_collection(app):
    s=MonitorSession();s.transport=Page();a={'id':'a','name':'account','owner':OWNER,'url':URL,'videos':{}};rows=[];s.result.connect(lambda id,r:rows.extend(r.get('videos',[])))
    s.start([a]);old={'aweme_id':'1234567890123455','author':{'sec_uid':OWNER},'desc':'old pinned','create_time':'2026-10-30T00:00:00Z','statistics':{'digg_count':200},'promotions':[{'title':'old book'}]}
    new=old|{'aweme_id':'1234567890123456','desc':'new November','create_time':'2026-11-05T00:00:00Z'}
    for i in range(4):
        s.snapshot_ready(s._generation,json.dumps({'url':URL,'documents':[{'aweme_list':[old] if i==0 else [old,new]}],'hasMore':True}))
        assert s.busy
    assert sum('loadMore' in text for text in s.transport.scripts)==4
    assert any(v['published'].startswith('2026-11') for v in rows);s.shutdown()
