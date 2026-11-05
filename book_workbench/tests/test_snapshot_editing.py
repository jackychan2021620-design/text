from pathlib import Path
from unittest.mock import patch
import json
import pytest
from PySide6.QtWidgets import QDialogButtonBox,QTextEdit,QPlainTextEdit,QLabel
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from workbench.ui import Editor,OCRReviewDialog
from workbench.curve_field import CurveField
from workbench.services import ocr_document
from workbench.provenance import UNKNOWN,scope_unknown
from conftest import record
FIXTURE=Path(__file__).resolve().parents[1]/'resources'/'mobile-layout-test.png'

def test_existing_snapshot_save_button_commits_revision_and_retains_original(app,store,graph):
    original=record(store,'data_snapshots',product_id=graph[1],sales=500,creators=105,sellers=20,ocr_text='保留识别证据')
    d=Editor(store,'data_snapshots',store.get('data_snapshots',original));d.show();app.processEvents()
    save=d.buttons.button(QDialogButtonBox.StandardButton.Save)
    assert save.isEnabled();assert save.text()=='保存修订版';assert '查看快照' not in d.windowTitle()
    d.fields['sales'].setText('1194');d.fields['sellers'].setText('32');d.fields['confirmed'].setChecked(True)
    QTest.mouseClick(save,Qt.MouseButton.LeftButton);app.processEvents()
    assert d.result()==d.DialogCode.Accepted,d.notice.text();assert d.saved_id!=original
    assert store.get('data_snapshots',original)['sales']==500
    revised=store.latest('data_snapshots','product_id',graph[1]);assert revised['sales']==1194;assert revised['sellers']==32
    assert revised['ocr_text']=='保留识别证据';assert f'修订自记录#{original}' in revised['notes']
    assert len(store.rows('data_snapshots'))==2

def test_advertising_snapshot_can_also_save_revision(app,store,graph):
    v=record(store,'video_tests',product_id=graph[1]);old=record(store,'advertising_records',video_id=v,actual_gmv=100,backend_gmv=999)
    d=Editor(store,'advertising_records',store.get('advertising_records',old));assert d.buttons.button(QDialogButtonBox.StandardButton.Save).isEnabled()
    d.fields['actual_gmv'].setText('200');d.save();assert hasattr(d,'saved_id'),d.notice.text()
    assert store.get('advertising_records',old)['actual_gmv']==100
    assert store.get('advertising_records',d.saved_id)['actual_gmv']==200;assert store.get('advertising_records',d.saved_id)['backend_gmv']==999

def test_no_raw_ocr_editor_or_review_text_area(app,store,graph):
    id=record(store,'data_snapshots',product_id=graph[1],ocr_text='不能丢失的OCR证据')
    d=Editor(store,'data_snapshots',store.get('data_snapshots',id))
    assert 'ocr_text' not in d.fields;assert d.values()['ocr_text']=='不能丢失的OCR证据'
    assert not any('原始识别' in w.text() for w in d.findChildren(QLabel))
    review=OCRReviewDialog('data_snapshots',{}, {},FIXTURE,ocr_text='不显示原始文本')
    assert not review.findChildren(QTextEdit);assert not review.findChildren(QPlainTextEdit);d.reject();review.reject()

def test_saved_and_drafted_curves_render_chart_without_raw_numbers(app,store,graph):
    values=[2,9,4,12,5,3,8];id=record(store,'data_snapshots',product_id=graph[1],curve=json.dumps(values))
    d=Editor(store,'data_snapshots',store.get('data_snapshots',id));field=d.fields['curve']
    assert isinstance(field,CurveField);assert field.plot.series.count()==len(values)
    assert [p.y() for p in field.plot.series.points()]==values
    assert not field.findChildren(QTextEdit);assert not field.findChildren(QPlainTextEdit)
    field.set_curve([10,20,15],'手工录入','【曲线手工录入】核对后的日销量。');d.reject()
    reopened=Editor(store,'data_snapshots',store.get('data_snapshots',id))
    assert [p.y() for p in reopened.fields['curve'].plot.series.points()]==[10,20,15];reopened.reject()

def test_creator_105_is_filled_and_saved_without_faking_period_rate(app,store,graph):
    doc=ocr_document(FIXTURE);d=Editor(store,'data_snapshots')
    d.fields['product_id'].setCurrentIndex(d.fields['product_id'].findData(graph[1]));d.fields['screenshot'].setText(store.attach(FIXTURE))
    def approve(review):
        assert review.inputs['creators'].text()=='105';assert review.checks['creators'].isChecked();review.apply();return review.DialogCode.Accepted
    with patch.object(OCRReviewDialog,'exec',approve):d.got_ocr(doc)
    assert d.fields['creators'].text()=='105';assert d.creator_scope.currentIndex()==1
    assert d.buttons.button(QDialogButtonBox.StandardButton.Save).isEnabled()
    d.fields['confirmed'].setChecked(True);d.save();assert hasattr(d,'saved_id'),d.notice.text()
    saved=store.get('data_snapshots',d.saved_id);assert saved['creators']==105 and scope_unknown(saved['notes'])
    result=store.analyze(graph[1]);assert result['达人出单率'] is None;assert result['出单达人人均销量']==pytest.approx(1194/32)
    revised=Editor(store,'data_snapshots',saved);revised.creator_scope.setCurrentIndex(0);revised.save()
    assert hasattr(revised,'saved_id'),revised.notice.text();assert store.analyze(graph[1])['达人出单率']==pytest.approx(32/105)

def test_curve_estimate_metadata_is_hidden_but_retained_on_edit(app,store,graph):
    notes='我的业务备注\n【曲线读图估算】等距采样7点，非精确日销量。\n'+UNKNOWN
    id=record(store,'data_snapshots',product_id=graph[1],creators=105,curve='[1,3,2,5,3,8,2]',notes=notes)
    d=Editor(store,'data_snapshots',store.get('data_snapshots',id));assert d.fields['notes'].toPlainText()=='我的业务备注'
    assert d.fields['curve'].source=='读图估算';assert d.creator_scope.currentIndex()==1
    d.fields['notes'].setPlainText('改过的业务备注');d.save()
    saved=store.get('data_snapshots',d.saved_id);assert '【曲线读图估算】' in saved['notes'];assert UNKNOWN in saved['notes'];assert '改过的业务备注' in saved['notes']

def test_main_curve_button_fills_a_visible_chart(app,store,graph,tmp_path):
    from PySide6.QtWidgets import QPushButton
    from workbench.curve_ui import CurveDialog
    from test_mobile_ocr_curve import chart_image
    path=tmp_path/'chart.png';chart_image().save(str(path));d=Editor(store,'data_snapshots')
    d.fields['product_id'].setCurrentIndex(d.fields['product_id'].findData(graph[1]));d.fields['screenshot'].setText(store.attach(path));d.show();app.processEvents()
    def approve(dialog):
        dialog.selector.rect=[60,60,380,160];dialog.upper.setText('40');dialog.lower.setText('0');dialog.extract();dialog.confirmed.setChecked(True);dialog.apply()
        assert dialog.preview.series.count()==90;assert dialog.selector.overlay
        return dialog.DialogCode.Accepted
    button=next(b for b in d.fields['curve'].findChildren(QPushButton) if b.text()=='从截图提取曲线')
    with patch.object(CurveDialog,'exec',approve):QTest.mouseClick(button,Qt.MouseButton.LeftButton)
    assert d.fields['curve'].plot.series.count()==90
    assert not d.fields['curve'].findChildren(QTextEdit)
    assert '【曲线读图估算】' in d.values()['notes'];d.reject()

def test_curve_source_tracks_manual_estimate_then_manual_again(app,store,graph):
    from workbench.provenance import curve_source
    d=Editor(store,'data_snapshots');field=d.fields['curve']
    manual='【曲线手工录入】经营者按顺序录入的销量值。'
    field.set_curve([1,2,3],'手工录入',manual)
    field.set_curve([2,3,4],'读图估算','【曲线读图估算】趋势点，非精确日值。')
    field.set_curve([5,6,7],'手工录入',manual)
    assert curve_source(d.values()['notes'])=='手工录入';d.reject()
