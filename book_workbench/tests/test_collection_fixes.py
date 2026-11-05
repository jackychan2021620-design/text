import json
import shutil
import time
from pathlib import Path
from unittest.mock import patch
import pytest
from PySide6.QtWidgets import QDialog,QFileDialog
from workbench.ui import Editor,OCRReviewDialog
from workbench.ocr_fields import propose_fields,numeric_value
from workbench.services import ocr_document
from conftest import record

FIXTURE=Path(__file__).resolve().parents[1]/'resources'/'ocr-check.png'

def test_fresh_database_paste_link_inline_book_and_product(app,store):
    snapshot=Editor(store,'data_snapshots');product=snapshot.fields['product_id']
    assert product.isEditable();assert product.count()==1
    assert '暂无商品档案' in snapshot.relation_hints['product_id'].text()
    product.setEditText('https://example.org/new-book')
    snapshot.fields['creators'].setText('100');snapshot.fields['sellers'].setText('20');snapshot.fields['sales'].setText('12345');snapshot.fields['confirmed'].setChecked(True)
    def complete(dialog):
        if dialog.table=='product_links':
            assert dialog.fields['url'].text()=='https://example.org/new-book'
            assert dialog.create_related('book_id')
            dialog.save()
        elif dialog.table=='books':dialog.fields['name'].setText('当场新建的图书');dialog.save()
        else:raise AssertionError(dialog.table)
        assert hasattr(dialog,'saved_id'),dialog.notice.text()
        return QDialog.DialogCode.Accepted
    with patch.object(Editor,'exec',complete):snapshot.save()
    assert hasattr(snapshot,'saved_id'),snapshot.notice.text()
    assert len(store.rows('books'))==1;assert len(store.rows('product_links'))==1
    saved=store.get('data_snapshots',snapshot.saved_id);assert saved['creators']==100
    assert saved['product_id']==store.rows('product_links')[0]['id']

def test_paste_existing_url_does_not_duplicate(app,store,graph):
    d=Editor(store,'data_snapshots');d.fields['product_id'].setEditText('https://example.org/book');d.fields['confirmed'].setChecked(True)
    d.save();assert hasattr(d,'saved_id'),d.notice.text();assert len(store.rows('product_links'))==1

def test_pasted_url_survives_close_and_reopen(app,store):
    d=Editor(store,'data_snapshots');d.fields['product_id'].setEditText('https://example.org/not-yet-created');d.reject()
    restored=Editor(store,'data_snapshots');assert restored.fields['product_id'].currentText()=='https://example.org/not-yet-created';restored.reject()

def test_inline_creation_cancel_keeps_snapshot_fields(app,store):
    d=Editor(store,'data_snapshots');d.fields['product_id'].setEditText('https://example.org/cancel');d.fields['sales'].setText('30')
    with patch.object(Editor,'exec',lambda self:QDialog.DialogCode.Rejected):d.save()
    assert d.fields['sales'].text()=='30';assert not store.rows('data_snapshots');d.reject()

def test_legacy_external_attachment_draft_recovers_and_archives(app,store,graph,tmp_path):
    image=tmp_path/'original.png';shutil.copyfile(FIXTURE,image)
    store.settings({'draft:data_snapshots:new':json.dumps({'product_id':graph[1],'screenshot':str(image),'sales':'10','notes':'保留其他草稿'})})
    d=Editor(store,'data_snapshots');archived=d.fields['screenshot'].text();assert archived.startswith('assets/')
    d.reject();image.unlink()
    for _ in range(2):
        d=Editor(store,'data_snapshots');assert d.fields['sales'].text()=='10';assert d.fields['notes'].toPlainText()=='保留其他草稿'
        assert store.asset(d.fields['screenshot'].text()).is_file();d.reject()

@pytest.mark.parametrize('value',['missing.png','assets/missing.png','assets/../../secret.png'])
def test_invalid_draft_attachment_never_blocks_new_dialog(app,store,graph,tmp_path,value):
    if value=='missing.png':value=str(tmp_path/value)
    store.settings({'draft:data_snapshots:new':json.dumps({'product_id':graph[1],'screenshot':value,'sales':'25','notes':'必须保留'})})
    for _ in range(2):
        d=Editor(store,'data_snapshots');assert d.fields['sales'].text()=='25'
        assert '重新选择' in d.notice.text() or '重选' in d.notice.text();d.reject()
    d=Editor(store,'data_snapshots');d.remove_attachment('screenshot');d.fields['confirmed'].setChecked(True);d.save()
    assert hasattr(d,'saved_id'),d.notice.text();assert store.get('data_snapshots',d.saved_id)['screenshot'] is None

def test_real_screenshot_selection_archives_recognizes_and_offers_fields(app,store,graph,tmp_path):
    image=tmp_path/'screen.png';shutil.copyfile(FIXTURE,image);d=Editor(store,'data_snapshots')
    d.fields['product_id'].setCurrentIndex(d.fields['product_id'].findData(graph[1]));seen=[]
    def approve(review):
        seen.append(True)
        assert review.inputs['creators'].text()=='100';assert review.inputs['sales'].text()=='12345'
        assert review.checks['creators'].isChecked();review.apply();return QDialog.DialogCode.Accepted
    with patch.object(QFileDialog,'getOpenFileName',return_value=(str(image),'')),patch.object(OCRReviewDialog,'exec',approve):
        d.pick('screenshot');assert d.fields['screenshot'].text().startswith('assets/')
        image.unlink() # The selected original can disappear while OCR is running.
        deadline=time.monotonic()+15
        while (d.worker.isRunning() or not seen) and time.monotonic()<deadline:
            app.processEvents();time.sleep(.01)
        app.processEvents()
    assert seen;assert d.fields['sales'].text()=='12345';assert d.fields['creators'].text()=='100'
    assert not d.fields['confirmed'].isChecked()
    d.fields['confirmed'].setChecked(True);d.save();assert hasattr(d,'saved_id'),d.notice.text()
    again=Editor(store,'data_snapshots');again.reject() # no poisoned path left in the new draft

def test_ocr_review_preserves_existing_values_until_explicit_overwrite(app):
    review=OCRReviewDialog('data_snapshots',{'sales':{'value':100,'source':'总销量100'}},{'sales':'999'},FIXTURE)
    assert not review.checks['sales'].isChecked();review.apply();assert 'sales' not in review.approved
    review=OCRReviewDialog('data_snapshots',{'sales':{'value':100,'source':'总销量100'}},{'sales':'999'},FIXTURE)
    review.checks['sales'].setChecked(True);review.apply();assert review.approved['sales']==100

def test_real_ocr_proposes_named_metrics():
    doc=ocr_document(FIXTURE);assert doc['words']
    proposed=propose_fields(doc,'data_snapshots');assert proposed['creators']['value']==100;assert proposed['sales']['value']==12345

@pytest.mark.parametrize('text,expected',[
 ('带货人数：1.2万\n出单人数：2,345\n总销量：3.5万',{'creators':12000,'sellers':2345,'sales':35000}),
 ('带 货 人 数 100\n出 单 人 数 20\n总 销 量 1,234',{'creators':100,'sellers':20,'sales':1234}),
 ('总销量 1万-2万',{}),('总销量 100+ ',{}),('带货人数 10%',{}),
 ('总销量 100\n总销量 200',{}),('带货人数 0\n出单人数 0\n总销量 0',{'creators':0,'sellers':0,'sales':0}),
])
def test_ocr_metric_text_mapping(text,expected):
    result=propose_fields(text,'data_snapshots');assert {k:v['value'] for k,v in result.items()}==expected

def test_advertising_never_guesses_actual_gmv_from_generic_amount():
    result=propose_fields('成交金额 999\n后台广告GMV 1200\n后台ROI 4.5\n广告消耗 100','advertising_records')
    assert 'actual_gmv' not in result;assert result['backend_gmv']['value']==1200;assert result['backend_roi']['value']==4.5


def test_ocr_card_numbers_above_labels_use_coordinates():
    words=[]
    for col,(number,label) in enumerate([('100','带货人数'),('20','出单人数'),('1.2万','总销量')]):
        x=col*300
        words.append({'text':number,'left':x+25,'top':0,'width':90,'height':40,'conf':90,'line_num':1})
        words.append({'text':label,'left':x,'top':55,'width':140,'height':30,'conf':90,'line_num':2})
    result=propose_fields({'text':'100 20 1.2万\n带货人数 出单人数 总销量','words':words},'data_snapshots')
    assert {k:v['value'] for k,v in result.items()}=={'creators':100,'sellers':20,'sales':12000}
