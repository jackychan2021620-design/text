import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import pytest
from workbench.store import Store
from workbench.model import SCHEMA
@pytest.fixture
def store(tmp_path):
    s=Store(tmp_path/'data');yield s;s.close()
@pytest.fixture(scope='session')
def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])
def record(s,table,**kw):
    defaults={'books':{'name':'数学手册','category':'科普'},'product_links':{'url':'https://example.org/book','status':'待分析'},'data_snapshots':{'collected':'2026-10-01','period_days':90,'confirmed':1},'video_tests':{'account':'账号A','code':'V1','name':'数学视频','published':'2026-10-01','status':'已提交'},'advertising_records':{'collected':'2026-10-05'}}
    values=defaults[table]|kw
    return s.save(table,values)
@pytest.fixture
def graph(store):
    b=record(store,'books');p=record(store,'product_links',book_id=b);return b,p
