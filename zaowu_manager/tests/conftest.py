import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import pytest
from zaowu.store import Store

@pytest.fixture
def store(tmp_path):
    instance=Store(tmp_path/'data')
    yield instance
    instance.close()

@pytest.fixture(scope='session')
def app():
    from PySide6.QtWidgets import QApplication
    app=QApplication.instance() or QApplication([])
    yield app

def record(store,table,**overrides):
    from zaowu.schema import SCHEMAS
    values={}
    for field in SCHEMAS[table][1]:
        if field.kind=='choice': value=field.options[0]
        elif field.kind=='date': value='2026-11-04'
        elif field.kind in ('product','customer'): value=None
        elif field.kind in ('int','money','number','bool'): value=0
        else: value='测试' if field.required else ''
        values[field.key]=value
    if table=='orders': values.update(quantity=1,status='已付款')
    values.update(overrides)
    return store.save(table,values)
