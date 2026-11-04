import requests
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDialog
from zaowu.ui import MainWindow
from test_ai import Response

def test_confirmed_send_stream_and_restart_history(app,store,monkeypatch):
    window=MainWindow(store)
    window.show()
    window.chat.runtime_key='test-key-not-a-real-secret'
    store.set_setting('model','model-from-service')
    monkeypatch.setattr(QDialog,'exec',lambda self:QDialog.DialogCode.Accepted)
    captured=[]
    def post(url,**kwargs):
        captured.append(kwargs['json'])
        return Response(['data: {"choices":[{"delta":{"content":"No orders yet."}}]}','data: [DONE]'])
    monkeypatch.setattr(requests,'post',post)
    window.chat.input.setPlainText('分析当前业务')
    window.chat.send()
    for _ in range(100):
        QTest.qWait(10)
        if window.chat.message_id is None: break
    messages=store.messages(window.chat.sessions.currentData())
    assert len(messages)==2 and messages[-1]['status']=='complete'
    assert messages[-1]['content']=='No orders yet.'
    assert len(captured)==1 and captured[0]['stream'] is True
    assert 'test-key-not-a-real-secret' not in str(messages)
    assert store.setting('model')=='model-from-service'
    window.force_quit=True
    window.close()

def test_cancel_privacy_preview_writes_nothing(app,store,monkeypatch):
    window=MainWindow(store)
    window.chat.runtime_key='test-key'
    store.set_setting('model','model-from-service')
    monkeypatch.setattr(QDialog,'exec',lambda self:QDialog.DialogCode.Rejected)
    window.chat.input.setPlainText('暂不发送')
    window.chat.send()
    assert store.messages(window.chat.sessions.currentData())==[]
    assert window.chat.worker is None
    window.force_quit=True
    window.close()
