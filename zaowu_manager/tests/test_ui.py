from PySide6.QtCore import QDate
from PySide6.QtWidgets import QDialog
from zaowu.ui import MainWindow, RecordDialog, RecordsPage
from conftest import record

def test_all_modules_resize_and_navigation(app,store,tmp_path):
    window=MainWindow(store)
    window.show()
    for index in range(len(window.MODULES)):
        window.nav.setCurrentRow(index)
        app.processEvents()
        assert window.heading.text()==window.MODULES[index]
    for width,height in [(1000,640),(1500,940),(1920,1080)]:
        window.resize(width,height)
        app.processEvents()
        assert window.chat.input.height()==100
    window.grab().save(str(tmp_path/'desktop.png'))
    window.force_quit=True
    window.close()

def test_real_order_form_to_summary(app,store):
    pid=record(store,'products',name='饮品蜡烛',price=12800,material=3200,active=1)
    dialog=RecordDialog(store,'orders',filters={'business':'DIY散客'})
    dialog.inputs['product_id'].setCurrentIndex(dialog.inputs['product_id'].findData(pid))
    dialog.inputs['quantity'].setValue(2)
    dialog.inputs['date'].setDate(QDate(2026,11,4))
    dialog.fill_price()
    dialog.inputs['source'].setText('小红书')
    dialog.inputs['channel'].setText('美团')
    dialog.save()
    assert dialog.result()==QDialog.DialogCode.Accepted
    summary=store.summary('2026-11-01','2026-11-30')
    assert (summary['revenue'],summary['contribution'])==(25600,19200)
    page=RecordsPage(store,'orders',{'business':'DIY散客'})
    page.search.setText('小红书')
    assert page.table_widget.rowCount()==1
    page.search.setText('不存在')
    assert page.table_widget.rowCount()==0

def test_chat_long_markdown_persistence_and_fixed_input(app,store):
    window=MainWindow(store)
    window.show()
    sid=window.chat.sessions.currentData()
    store.add_message(sid,'user','经营复盘')
    text='## 经营建议\n\n| 项目 | 金额 |\n|---|---|\n| DIY | 128 |\n\n'+('长回复内容\n\n'*500)
    store.add_message(sid,'assistant',text)
    window.chat.render()
    from PySide6.QtTest import QTest
    QTest.qWait(80)
    app.processEvents()
    bar=window.chat.view.verticalScrollBar()
    assert bar.maximum()>0
    before=window.chat.input.geometry()
    bar.setValue(0); app.processEvents()
    assert window.chat.input.geometry()==before
    assert '长回复内容' in window.chat.view.toPlainText()
    window.chat.new_session()
    window.chat.refresh_sessions(sid)
    assert store.messages(sid)[-1]['content']==text
    window.force_quit=True
    window.close()
