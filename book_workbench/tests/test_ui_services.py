import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch
import pytest
from conftest import record
from workbench.ui import MainWindow,Editor
from workbench.model import SCHEMA
from workbench.services import AIWorker,endpoint

def test_every_page_forms_and_edit_persist(app,store,graph):
    b,p=graph;v=record(store,'video_tests',product_id=p)
    record(store,'data_snapshots',product_id=p,creators=20,sellers=5,sales=100)
    record(store,'advertising_records',video_id=v,spend=100,orders=5,actual_gmv=200)
    window=MainWindow(store);window.show();app.processEvents()
    for index in range(9):
        window.nav.setCurrentRow(index);app.processEvents();assert window.last_error is None
        labels=[x.text() for x in window.center.findChildren(__import__('PySide6.QtWidgets',fromlist=['QLabel']).QLabel)]
        assert not any('unhashable' in x or 'Traceback' in x for x in labels)
    for table in SCHEMA:
        dialog=Editor(store,table,parent=window)
        assert len(dialog.fields)==len(SCHEMA[table][1]);dialog.reject()
        dialog=Editor(store,table,store.rows(table)[0],window);assert dialog.values();dialog.reject()
    editor=Editor(store,'books',parent=window);editor.fields['name'].setText('新增测试图书');editor.save()
    assert store.get('books',editor.saved_id)['name']=='新增测试图书'
    window.quitting=True;window.close();app.processEvents()

def test_real_entrypoint_restart_preserves_pending_tasks(tmp_path):
    from workbench.store import Store
    root=tmp_path/'lifecycle';s=Store(root);b=record(s,'books');p=record(s,'product_links',book_id=b)
    record(s,'data_snapshots',product_id=p);record(s,'video_tests',product_id=p);s.close()
    for _ in range(2):
        result=subprocess.run([sys.executable,'launch.py','--smoke-test'],cwd=Path(__file__).resolve().parents[1],env=dict(os.environ,QT_QPA_PLATFORM='offscreen',BOOK_WORKBENCH_DATA_DIR=str(root)),capture_output=True,text=True,timeout=20)
        assert result.returncode==0,result.stderr
    s=Store(root);assert len(s.reminders()['商品15天'])==1;assert len(s.reminders()['视频5天'])==1;s.close()

class Response:
    def __init__(self,data,status=200):self.data=data;self.status_code=status
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def json(self):return self.data

def test_ai_protocol_and_five_sections(app):
    output=[];errors=[]
    worker=AIWorker('https://api.deepseek.com','test-only','model-from-service',[{'role':'user','content':'测试上下文'}])
    worker.result.connect(output.append);worker.failed.connect(errors.append)
    text='数据事实：待核对\n计算结果：GMV/消耗=2\n合理推测：值得验证\n不确定因素：样本小\n下一步建议：补充测试'
    with patch('workbench.services.requests.post',return_value=Response({'choices':[{'message':{'content':text}}]})) as post:
        worker.run();assert output==[text];assert not errors
        assert post.call_args.kwargs['json']['messages'][0]['content']=='测试上下文'
        assert post.call_args.kwargs['allow_redirects'] is False
    with patch('workbench.services.requests.post',return_value=Response({},401)):
        worker.run();assert '401' in errors[-1]
    worker.key='';worker.run();assert 'API Key' in errors[-1]

def test_models_not_hardcoded(app):
    output=[];worker=AIWorker('https://api.deepseek.com','test-only');worker.result.connect(output.append)
    with patch('workbench.services.requests.get',return_value=Response({'data':[{'id':'returned-model'}]})):
        worker.run();assert output==[['returned-model']]

@pytest.mark.parametrize('url',['http://api.deepseek.com','https://example.org','https://api.deepseek.com.evil.org','https://u:p@api.deepseek.com','https://api.deepseek.com/?key=x'])
def test_reject_unsafe_api_endpoint(url):
    with pytest.raises(ValueError):endpoint(url)

def test_real_chinese_ocr_and_manual_confirmation(app,store,graph,tmp_path):
    from PySide6.QtGui import QImage,QPainter,QFont,QColor
    from workbench.services import ocr
    # Fixed, verified raster fixture avoids offscreen font differences across OSes.
    import shutil
    source=tmp_path/'ocr.png';shutil.copyfile(Path(__file__).resolve().parents[1]/'resources'/'ocr-check.png',source)
    text=ocr(source);assert '12345' in text and '100' in text
    assert '销量' in text.replace(' ','')
    values={'product_id':graph[1],'screenshot':str(source),'ocr_text':text,'sales':12345,'creators':100}
    with pytest.raises(ValueError):record(store,'data_snapshots',**values,confirmed=0)
    record(store,'data_snapshots',**values);assert store.rows('data_snapshots')[0]['sales']==12345
    assert store.rows('data_snapshots')[0]['ocr_text']==text

def test_draft_survives_editor_close(app,store):
    d=Editor(store,'books');d.fields['name'].setText('尚未确认的图书');d.reject()
    again=Editor(store,'books');assert again.fields['name'].text()=='尚未确认的图书';assert store.rows('books')==[]
    again.save();assert len(store.rows('books'))==1

def test_notifications_independent_and_daily_deduplicated(app,store,graph):
    record(store,'data_snapshots',product_id=graph[1]);record(store,'video_tests',product_id=graph[1])
    window=MainWindow(store)
    calls=[]
    class Tray:
        def isVisible(self):return True
        def showMessage(self,*args):calls.append(args)
        def hide(self):pass
    real=window.tray;window.tray=Tray()
    with patch('workbench.ui.QSystemTrayIcon.supportsMessages',return_value=True):
        window.maintain();window.maintain()
    assert len(calls)==2;assert {r[0] for r in calls}=={'商品15天','视频5天'}
    window.quitting=True;window.close();real.hide()

def test_edit_draft_and_scoped_ai_without_key(app,store,graph):
    row=store.get('books',graph[0]);d=Editor(store,'books',row);d.fields['author'].setText('编辑未确认');d.reject()
    d2=Editor(store,'books',row);assert d2.fields['author'].text()=='编辑未确认';d2.reject()
    assert store.get('books',graph[0])['author'] is None
    window=MainWindow(store)
    with patch('workbench.ui.api_key',return_value=''):
        with pytest.raises(ValueError,match='API Key'):window.send_ai()
    assert store.rows('ai_analysis_history')==[]
    window.quitting=True;window.close()

def test_full_editor_workflow(app,store,tmp_path):
    from PySide6.QtWidgets import QComboBox,QCheckBox,QTextEdit
    def submit(table,values):
        d=Editor(store,table)
        for key,value in values.items():
            w=d.fields[key]
            if isinstance(w,QComboBox):
                if isinstance(value,int):w.setCurrentIndex(w.findData(value))
                else:w.setCurrentText(value)
            elif isinstance(w,QCheckBox):w.setChecked(bool(value))
            elif isinstance(w,QTextEdit):w.setPlainText(str(value))
            else:w.setText(str(value))
        d.save();assert hasattr(d,'saved_id'),d.notice.text();return d.saved_id
    b=submit('books',{'name':'端到端测试书','category':'科普'})
    p=submit('product_links',{'book_id':b,'url':'https://example.org/e2e','price':50,'commission':10,'commission_rate':20})
    p2=submit('product_links',{'book_id':b,'url':'https://example.org/e2e2'})
    submit('data_snapshots',{'product_id':p,'collected':'2026-10-01','creators':50,'sellers':10,'sales':200,'curve':'2,3,4,5,6,7,8','confirmed':True})
    submit('data_snapshots',{'product_id':p,'collected':'2026-10-16','creators':60,'sellers':15,'sales':300,'confirmed':True})
    v=submit('video_tests',{'product_id':p,'account':'测试账号','code':'E2E1','name':'测试视频','published':'2026-10-01','ad_started':'2026-10-02'})
    v2=submit('video_tests',{'product_id':p,'account':'测试账号','code':'E2E2','name':'另一条视频','published':'2026-10-03'})
    submit('advertising_records',{'video_id':v,'collected':'2026-10-07','spend':200,'orders':8,'actual_gmv':400,'backend_gmv':600,'backend_roi':3})
    assert store.review(v)['实际GMV/广告消耗']==2
    store.complete_review(v,'核对后保存');store.defer(v2,2)
    assert len(store.video_comparison(b))==2
    assert len(store.compare([p,p2]))==2
    bundle=tmp_path/'e2e.zip';store.backup(bundle);store.restore(bundle)
    assert store.get('books',b)['name']=='端到端测试书';assert store.rows('video_review_reports')
