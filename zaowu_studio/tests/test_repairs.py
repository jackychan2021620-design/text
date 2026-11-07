import json
import sys
import time
from pathlib import Path
from PySide6.QtCore import QTimer,Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QPushButton,QDialog
from studio.ui import MainWindow
from studio.settings import SettingsDialog
from studio.widgets import EditDialog
from studio.import_job import ImportJob,write_json,read_result
from conftest import record
from test_ai import Response

def wait_until(predicate,seconds=5):
    end=time.monotonic()+seconds
    while not predicate() and time.monotonic()<end:QTest.qWait(20)
    assert predicate()

def test_second_and_third_product_can_be_added_from_home(app,store,monkeypatch):
    names=iter(['饮品蜡烛','植物微景观','新体验项目'])
    def save_product(dialog):
        dialog.form.inputs['name'].setText(next(names));dialog.accept_values();return dialog.result()
    monkeypatch.setattr(EditDialog,'exec',save_product)
    window=MainWindow(store);window.show()
    for count in range(1,4):
        buttons=[b for b in window.content.findChildren(QPushButton) if b.text()=='新增产品 / 服务']
        assert len(buttons)==1
        buttons[0].click();app.processEvents()
        assert len(store.rows('offers','DIY散客'))==count
    [b for b in window.content.findChildren(QPushButton) if b.text()=='管理已录项目'][0].click()
    assert window.heading.text()=='资料库'
    window.force_quit=True;window.close()

def test_original_deepseek_key_save_connects_and_saves_real_model(app,store,monkeypatch):
    calls=[]
    def get(url,**kwargs):calls.append(kwargs);return Response(data={'data':[{'id':'returned-current-model'}]})
    monkeypatch.setattr('studio.ai.requests.get',get)
    window=MainWindow(store);dialog=SettingsDialog(window);dialog.persist.setChecked(False)
    dialog.key.setText('test-original-deepseek-key');assert '已输入' in dialog.ai_status.text()
    dialog.save()
    wait_until(lambda:store.setting('model')=='returned-current-model')
    assert window.runtime_key=='test-original-deepseek-key'
    assert '连接成功' in dialog.ai_status.text()
    assert calls[0]['headers']['Authorization']=='Bearer test-original-deepseek-key'
    assert sum(calls[0]['timeout'])<=20
    assert 'test-original-deepseek-key' not in str(list(store.db.execute('SELECT value FROM settings')))
    wait_until(lambda:not dialog.worker.isRunning());dialog.reject();window.force_quit=True;window.close()

def test_key_error_is_visible_and_retry_available(app,store,monkeypatch):
    monkeypatch.setattr('studio.ai.requests.get',lambda *a,**k:Response(status=401))
    window=MainWindow(store);dialog=SettingsDialog(window);dialog.persist.setChecked(False);dialog.key.setText('test-invalid-key');dialog.save()
    wait_until(lambda:'401' in dialog.notice.text() and dialog.test_button.isEnabled())
    assert '401' in dialog.notice.text() and dialog.test_button.isEnabled()
    dialog.reject();window.force_quit=True;window.close()

def test_settings_close_immediately_during_slow_test(app,store,monkeypatch):
    def get(*a,**k):time.sleep(.6);return Response(data={'data':[{'id':'late-model'}]})
    monkeypatch.setattr('studio.ai.requests.get',get)
    window=MainWindow(store);window.settings();dialog=window.settings_dialog
    assert dialog.windowModality()==Qt.WindowModality.NonModal
    dialog.key.setText('test-key');dialog.test();dialog.reject()
    assert not dialog.isVisible()
    record(store,'offers',name='测试期间录入')
    wait_until(lambda:not dialog.worker.isRunning())
    assert store.setting('model')=='' and len(store.rows('offers'))==1
    window.force_quit=True;window.close()

def test_hung_browser_never_blocks_main_ui_and_is_cancelled(app,store,monkeypatch):
    window=MainWindow(store);window.show()
    QTest.qWait(100)
    monkeypatch.setattr('studio.import_job.ImportJob',lambda parent:ImportJob(parent,command=[sys.executable,'-c','import time; time.sleep(60)'],startup_seconds=1.2))
    ticks=[];timer=QTimer();timer.setInterval(25);timer.timeout.connect(lambda:ticks.append(1));timer.start()
    window.import_xhs('https://xhslink.cn/o/fixture');job=window.import_job
    assert window.import_notice.windowModality()==Qt.WindowModality.NonModal
    errors=[];job.failed.connect(errors.append)
    QTest.qWait(150)
    window.settings();assert window.settings_dialog.isVisible()
    record(store,'offers',name='浏览器无响应时仍能保存')
    window.settings_dialog.reject()
    wait_until(lambda:job.ended,seconds=6)
    timer.stop()
    assert len(ticks)>=8 and errors and len(store.rows('offers'))==1
    assert not job.running()
    job.cleanup();window.force_quit=True;window.close()

def test_settings_footer_remains_visible_on_small_screen(app,store):
    window=MainWindow(store);dialog=SettingsDialog(window);dialog.resize(640,500);dialog.show()
    dialog.tabs.setCurrentIndex(1);QTest.qWait(60)
    assert dialog.height()<=500
    assert dialog.save_button.geometry().bottom()<dialog.height()
    assert dialog.save_button.isVisible()
    dialog.reject();window.force_quit=True;window.close()

def test_browser_crash_is_reported_without_closing_main(app,store):
    window=MainWindow(store);job=ImportJob(window,command=[sys.executable,'-c','raise SystemExit(7)'])
    errors=[];job.failed.connect(errors.append);job.start('fixture');wait_until(lambda:job.ended)
    assert errors and window.store is store
    job.cleanup();window.force_quit=True;window.close()

def test_slow_windows_process_creation_does_not_block_gui(app,monkeypatch):
    import threading
    import subprocess
    original=subprocess.Popen;entered=threading.Event();release=threading.Event()
    def slow_create(*args,**kwargs):
        entered.set();release.wait(timeout=2);return original(*args,**kwargs)
    monkeypatch.setattr('studio.import_job.subprocess.Popen',slow_create)
    job=ImportJob(command=[sys.executable,'-c','import time; time.sleep(60)'],startup_seconds=5)
    job.start('fixture');wait_until(entered.is_set)
    responsive=[];QTimer.singleShot(0,lambda:responsive.append(True));QTest.qWait(80)
    assert responsive and job.running()
    release.set();job.cancel();wait_until(lambda:job.ended,seconds=6);job.cleanup()

def test_ipc_rejects_image_paths_outside_session(tmp_path):
    import pytest
    from test_xhs import payload,URL
    root=tmp_path/'session';root.mkdir();external=tmp_path/'outside.png';external.write_bytes(b'not a valid image')
    note=payload()['note'];images=[{'position':i+1,'url':u['urlDefault'] if 'urlDefault' in u else u['infoList'][0]['url'],'path':str(external),'error':''} for i,u in enumerate(note['imageList'])]
    images[0]['url']='https://sns-webpic-qc.xhscdn.com/first'
    write_json(root/'result.json',{'url':URL,'payload':{'note':note},'images':images})
    with pytest.raises(ValueError,match='路径'):read_result(root)

def test_image_persistence_runs_off_main_thread(app,store,tmp_path,monkeypatch):
    from studio.store import Store
    from studio.import_job import SaveNoteWorker
    from studio.xhs import parse_note
    from test_xhs import payload,URL
    from PySide6.QtGui import QImage,QColor
    note=parse_note(payload(),URL);images=[]
    for i,url in enumerate(note.images,1):
        path=tmp_path/f'{i}.png';picture=QImage(20,20,QImage.Format.Format_RGB32);picture.fill(QColor('green'));assert picture.save(str(path),'PNG')
        images.append({'position':i,'url':url,'path':str(path),'error':''})
    original=Store.save_imported_note
    def slow_save(self,*args,**kwargs):time.sleep(.4);return original(self,*args,**kwargs)
    monkeypatch.setattr(Store,'save_imported_note',slow_save)
    worker=SaveNoteWorker(store.root,note,images,'DIY散客');results=[];worker.saved.connect(results.append)
    ticks=[];timer=QTimer();timer.setInterval(20);timer.timeout.connect(lambda:ticks.append(1));timer.start();worker.start()
    wait_until(lambda:bool(results) and not worker.isRunning());timer.stop()
    assert len(ticks)>=8 and len(store.reference_images(results[0]))==2
