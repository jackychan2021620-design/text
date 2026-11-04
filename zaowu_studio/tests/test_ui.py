import json
import requests
from PySide6.QtCore import QDate
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDialog
from studio.ui import MainWindow
from studio.workspace import PieceDialog
from studio.ai_dialog import AIDialog
from conftest import record
from test_ai import Response

def test_four_entries_empty_home_and_responsive(app,store):
    window=MainWindow(store);window.show()
    assert len(window.nav_buttons)==4
    for size in ((980,650),(1280,840),(1600,1000)):
        window.resize(*size)
        for index,title in enumerate(window.TITLES):
            window.navigate(index);QTest.qWait(10);assert window.heading.text()==title
    window.business.setCurrentText('鲜花花束');assert store.setting('focus')=='鲜花花束'
    window.force_quit=True;window.close()

def test_piece_edit_save_and_real_stage_progression(app,store,monkeypatch):
    monkeypatch.setattr('studio.workspace.confirm',lambda *a:True)
    offer=record(store,'offers',name='真实项目')
    piece=record(store,'pieces',topic='初始选题')
    window=MainWindow(store);dialog=PieceDialog(window,piece);dialog.show()
    dialog.forms[0].inputs['audience'].setText('汕头周末顾客');dialog.forms[0].inputs['hypothesis'].setPlainText('测试成品先展示')
    dialog.advance();assert store.get('pieces',piece)['stage']=='素材'
    form=dialog.forms[1];form.inputs['offer_id'].setCurrentIndex(form.inputs['offer_id'].findData(offer));form.inputs['angle'].setPlainText('成品展示')
    dialog.advance();assert store.get('pieces',piece)['stage']=='草稿'
    form=dialog.forms[2];form.inputs['title'].setText('真实标题');form.inputs['body'].setPlainText('服务介绍');form.inputs['cta'].setText('咨询预约')
    dialog.advance();assert store.get('pieces',piece)['stage']=='待发布'
    dialog.forms[3].inputs['published_date'].setText('2026-11-04');dialog.advance();assert store.get('pieces',piece)['stage']=='已发布'
    def fill_feedback(self):
        self.form.inputs['views'].setText('100')
        self.form.inputs['facts'].setPlainText('阅读已有记录，本地需求尚不明确')
        self.form.inputs['next_action'].setPlainText('继续观察相关咨询')
        self.accept_values()
        return self.result()
    monkeypatch.setattr('studio.widgets.EditDialog.exec',fill_feedback)
    dialog.feedback();dialog.advance();assert store.get('pieces',piece)['stage']=='已复盘'
    assert store.latest_feedback(piece)['views']==100
    dialog.reject();window.force_quit=True;window.close()

def test_cancel_send_has_no_run_or_business_mutation(app,store,monkeypatch):
    window=MainWindow(store);window.runtime_key='test-key';store.set_setting('model','from-api')
    monkeypatch.setattr(QDialog,'exec',lambda self:QDialog.DialogCode.Rejected)
    dialog=AIDialog(window,'选题计划',store.context('DIY散客',task='选题计划'));dialog.generate()
    assert store.rows('ai_runs')==[] and store.rows('pieces')==[]
    dialog.reject();window.force_quit=True;window.close()

def test_stream_persists_without_auto_applying_business_data(app,store,monkeypatch):
    window=MainWindow(store);window.runtime_key='test-key';store.set_setting('model','from-api')
    monkeypatch.setattr(QDialog,'exec',lambda self:QDialog.DialogCode.Accepted)
    monkeypatch.setattr(requests,'post',lambda *a,**k:Response(['data: {"choices":[{"delta":{"content":"待验证建议"}}]}','data: [DONE]']))
    dialog=AIDialog(window,'效果复盘',store.context('DIY散客',task='效果复盘'));dialog.show();dialog.generate()
    for _ in range(100):
        QTest.qWait(10)
        if dialog.ok:break
    assert dialog.ok and store.rows('ai_runs')[0]['status']=='已完成'
    assert store.rows('ai_runs')[0]['output']=='待验证建议' and store.rows('pieces')==[] and store.rows('learnings')==[]
    dialog.buffer='长内容\n\n'*800;dialog.flush();QTest.qWait(80)
    before=dialog.input.geometry();dialog.view.verticalScrollBar().setValue(0);QTest.qWait(20)
    assert dialog.input.geometry()==before
    dialog.reject();window.force_quit=True;window.close()
