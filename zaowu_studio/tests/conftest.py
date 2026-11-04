import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import pytest
from studio.store import Store
from studio.model import TABLES,PIECE_FIELDS,FEEDBACK_FIELDS

@pytest.fixture
def store(tmp_path):
    store=Store(tmp_path/'studio')
    yield store
    store.close()

@pytest.fixture(scope='session')
def app():
    from PySide6.QtWidgets import QApplication
    app=QApplication.instance() or QApplication([])
    yield app

def values(fields,**overrides):
    result={}
    for f in fields:
        if f.kind=='choice':result[f.key]=f.options[0]
        elif f.kind=='date':result[f.key]='2026-11-04'
        elif f.kind in ('metric','money_optional','offer','reference'):result[f.key]=None
        elif f.kind=='bool':result[f.key]=0
        else:result[f.key]='测试记录' if f.required else ''
    result.update(overrides);return result

def record(store,table,**overrides):
    return store.save(table,values(PIECE_FIELDS if table=='pieces' else TABLES[table][1],**overrides))

def published(store):
    offer=record(store,'offers',name='饮品蜡烛',price='128元 / 人',booking='到店前预约')
    piece=record(store,'pieces',topic='体验如何完成',audience='汕头周末体验顾客',hypothesis='验证成品先展示的表达',offer_id=offer,angle='成品和制作过程',title='第一次做手作可以做出什么',body='真实服务介绍',cta='咨询预约',published_date='2026-11-04')
    for _ in range(4):store.advance(piece)
    return piece
