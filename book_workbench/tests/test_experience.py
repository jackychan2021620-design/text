import time
from unittest.mock import patch
import pytest
from PySide6.QtCore import Qt,QTimer,QPoint
from PySide6.QtGui import QKeySequence
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication,QLineEdit,QVBoxLayout,QPushButton,QLabel,QDialogButtonBox,QTextEdit
from conftest import record
from workbench.experience import (Dialog,FeedbackButton,DataTable,DURATION,clean_markdown,readable,reduced_motion)
from workbench.ui import MainWindow,Editor,label,message


def finish(window):window.quitting=True;window.close();QTest.qWait(220)

def test_press_feedback_selectable_text_and_table_copy(app,store):
    window=MainWindow(store);window.show();QTest.qWait(30)
    b=FeedbackButton('操作',window);b.show();start=time.perf_counter();QTest.mousePress(b,Qt.MouseButton.LeftButton)
    assert b.isDown();assert (time.perf_counter()-start)*1000<100;QTest.mouseRelease(b,Qt.MouseButton.LeftButton)
    text=label('可复制的说明文字');assert text.textInteractionFlags()&Qt.TextInteractionFlag.TextSelectableByMouse
    table=DataTable(1,2);from PySide6.QtWidgets import QTableWidgetItem
    table.setItem(0,0,QTableWidgetItem('书名'));table.setItem(0,1,QTableWidgetItem('1194'));table.selectRow(0);table.copy_cells()
    assert app.clipboard().text()=='书名\t1194';finish(window)

def test_toast_does_not_open_modal_or_steal_input(app,store):
    w=MainWindow(store);w.nav.setCurrentRow(1);w.show();w.search.setFocus();app.processEvents();focus=app.focusWidget()
    message(w,'已保存，可继续编辑');app.processEvents()
    assert QApplication.activeModalWidget() is None;assert w._toast.isVisible();assert app.focusWidget() is focus
    finish(w)

def test_dialog_transition_focus_and_reduced_motion(app,monkeypatch):
    app.setProperty('reducedMotion',False);monkeypatch.delenv('BOOK_WORKBENCH_REDUCED_MOTION',raising=False)
    with patch('workbench.experience.reduced_motion',return_value=False):
        d=Dialog();l=QVBoxLayout(d);first=QLineEdit();second=QLineEdit();l.addWidget(first);l.addWidget(second);d.show();QTest.qWait(30)
        assert app.focusWidget() is first;assert d._transition.duration()==DURATION
        assert {bytes(d._transition.animationAt(i).propertyName()) for i in range(2)}=={b'pos',b'windowOpacity'}
        QTest.qWait(200);QTest.keyClick(first,Qt.Key.Key_Tab);assert app.focusWidget() is second
        QTest.keyClick(second,Qt.Key.Key_Escape);QTest.qWait(220);assert not d.isVisible()
    monkeypatch.setenv('BOOK_WORKBENCH_REDUCED_MOTION','1');assert reduced_motion()
    d=Dialog();d.show();app.processEvents();assert d._transition is None;d.reject();assert not d.isVisible()


def test_form_inline_validation_and_escape_restores_draft(app,store):
    d=Editor(store,'books');d.show();QTest.qWait(220)
    assert app.focusWidget() is d.fields['name'];QTest.keyClick(d.fields['name'],Qt.Key.Key_Tab);assert app.focusWidget() is d.fields['author']
    d.fields['name'].clear();d.save()
    assert d.errors['name'].text();assert d.fields['name'].property('invalid');assert not store.rows('books')
    d.fields['name'].setText('保留草稿');assert not d.fields['name'].property('invalid')
    QTest.keyClick(d.fields['name'],Qt.Key.Key_Escape);QTest.qWait(220)
    reopened=Editor(store,'books');assert reopened.fields['name'].text()=='保留草稿';reopened.show();QTest.qWait(220)
    QTest.keyClick(reopened.fields['name'],Qt.Key.Key_Return);QTest.qWait(220)
    assert store.rows('books')[0]['name']=='保留草稿';assert reopened.result()==Dialog.DialogCode.Accepted


def test_search_debounce_paging_and_switch_state(app,store):
    for i in range(125):record(store,'books',name=f'测试书{i:03}',category='科普')
    w=MainWindow(store);w.nav.setCurrentRow(1);w.show();QTest.qWait(220)
    assert w.table.rowCount()==50;assert len(w.visible)==50;assert w.table.frozen is not None
    assert w.table.viewport().mapToGlobal(QPoint(0,0)).y()==w.table.frozen.viewport().mapToGlobal(QPoint(0,0)).y()
    w.search.setFocus()
    with patch.object(store,'page',wraps=store.page) as query:
        QTest.keyClicks(w.search,'123');assert query.call_count==0;assert w.table.rowCount()==50
        QTest.qWait(270);assert query.call_count==1;assert {r['name'] for r in w.visible}=={'测试书123','测试书122'} # title or numeric ID
    w.search.setText('测试书');QTest.qWait(270)
    next(b for b in w.center.findChildren(QPushButton) if b.text()=='下一页').click();assert w.page_number==1
    w.table.selectRow(10);selected=w.selected()['id'];w.table.verticalScrollBar().setValue(75);scroll=w.table.verticalScrollBar().value()
    w.nav.setCurrentRow(2);QTest.qWait(30);w.nav.setCurrentRow(1);QTest.qWait(220)
    assert w.search.text()=='测试书';assert w.page_number==1;assert w.selected()['id']==selected;assert w.table.verticalScrollBar().value()==scroll
    assert w.last_error is None;finish(w)


def test_settings_unsaved_state_and_clean_markdown(app,store):
    w=MainWindow(store);w.nav.setCurrentRow(8);w.config['grade_high_sales'].setText('1500');w.nav.setCurrentRow(0);w.nav.setCurrentRow(8)
    assert w.config['grade_high_sales'].text()=='1500'
    w.show_ai_answer('## 结论\n**适合**\n理由：小量测试。 #读书')
    assert w.ai_output.toPlainText()=='结论\n适合\n理由：小量测试。 #读书'
    assert readable({'结论':'适合','依据':['出单率达标','销量达标']})=='结论：适合\n依据：\n出单率达标\n\n销量达标'
    finish(w)


def test_history_pagination_and_state_restore(app,store):
    with store.db:
        store.db.executemany('INSERT INTO ai_analysis_history(created,task,context,response,status) VALUES (?,?,?,?,?)', [('2026-11-05','测试问题','{}','简短结论','完成') for _ in range(75)])
    w=MainWindow(store);w.nav.setCurrentRow(7);w.history_kind.setCurrentIndex(2);assert w.history_table.rowCount()==50
    next(b for b in w.center.findChildren(QPushButton) if b.text()=='下一页').click();assert w.history_table.rowCount()==25
    w.nav.setCurrentRow(1);w.nav.setCurrentRow(7);assert w.history_kind.currentIndex()==2;assert w.history_page_number==1;assert w.history_table.rowCount()==25
    finish(w)


def test_context_menu_transition_keeps_native_copy_action_and_does_not_block(app,store):
    from workbench.experience import SmoothMenu
    w=MainWindow(store);w.show();QTest.qWait(30)
    menu=SmoothMenu(w);called=[];action=menu.addAction('复制');action.triggered.connect(lambda:called.append(True));menu.popup(w.mapToGlobal(QPoint(30,30)));QTest.qWait(30)
    if not reduced_motion():assert menu._fade.duration()==DURATION
    action.trigger();menu.hide();assert called==[True];assert not menu.isVisible()
    QTest.qWait(220);assert not getattr(app,'_popup_ghosts',[]);finish(w)
