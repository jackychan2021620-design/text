from pathlib import Path
from unittest.mock import patch
import json
import math
import shutil
import subprocess
import pytest
from PySide6.QtGui import QImage,QPainter,QPen,QColor
from PySide6.QtCore import QPointF
from workbench.services import ocr_document,ocr_model_folder,ocr_executable
from workbench.image_io import read_image
from workbench.ocr_fields import propose_fields
from workbench.curve import locate_curve,trace_curve
from workbench.curve_ui import CurveDialog
from workbench.ui import OCRReviewDialog
FIXTURE=Path(__file__).resolve().parents[1]/'resources'/'ocr-check.png'
MOBILE=FIXTURE.with_name('mobile-layout-test.png')

@pytest.mark.parametrize('format',['PNG','JPG','WEBP'])
def test_image_formats_and_chinese_paths_do_not_reach_native_argv(app,tmp_path,format):
    root=tmp_path/'中文目录'/'手机截图';root.mkdir(parents=True)
    path=root/('微信转发图片.'+format.lower());assert read_image(FIXTURE).save(str(path),format)
    models=root/'中文模型目录';models.mkdir()
    installed=ocr_model_folder(ocr_executable())
    for lang in ('chi_sim','eng'):shutil.copyfile(installed/(lang+'.traineddata'),models/(lang+'.traineddata'))
    native=subprocess.run
    with patch('workbench.services.ocr_model_folder',return_value=models),patch('workbench.services.subprocess.run',wraps=native) as run:
        doc=ocr_document(path)
    result=propose_fields(doc,'data_snapshots');assert result['sales']['value']==12345
    calls=run.call_args_list
    assert any(c.args[0][1:3]==['stdin','stdout'] and c.kwargs.get('input',b'').startswith(b'\x89PNG') for c in calls)
    for c in calls:
        assert c.kwargs['cwd']==str(models)
        assert '--tessdata-dir' in c.args[0] and c.args[0][c.args[0].index('--tessdata-dir')+1]=='.'
        assert all('中文' not in arg for arg in c.args[0][1:])

def test_long_mobile_layout_is_tiled_and_periods_are_not_mixed():
    doc=ocr_document(MOBILE);assert doc['tile_count']>=3;assert doc['image_size']==[450,2050]
    values=propose_fields(doc,'data_snapshots')
    assert values['sales']['value']==1194;assert values['sellers']['value']==32
    assert values['period_days']['value']==90
    assert values['creators']['value']==105;assert values['creators']['warning']
    assert '受众' in doc['text'].replace(' ','')

def test_outside_period_candidate_is_not_checked_by_default(app):
    proposals={'creators':{'value':105,'source':'带货人数105','warning':'周期未标明'},'sales':{'value':1194,'source':'90天销量'}}
    d=OCRReviewDialog('data_snapshots',proposals,{},FIXTURE)
    assert not d.checks['creators'].isChecked();assert d.checks['sales'].isChecked();d.apply();assert 'creators' not in d.approved

def chart_image():
    image=QImage(500,300,QImage.Format.Format_RGB32);image.fill(QColor('white'))
    p=QPainter(image);p.setPen(QPen(QColor('#16a6f4'),2));last=None
    for i in range(380):
        value=20+15*math.sin(i/35);point=QPointF(60+i,60+(40-value)/40*159)
        if last:p.drawLine(last,point)
        last=point
    p.end();return image

def test_curve_trace_pixel_estimate_requires_calibration():
    image=chart_image();hint=locate_curve(image);assert hint
    result=trace_curve(image,[60,60,380,160],40,0,90)
    assert len(result['values'])==90
    for i,value in enumerate(result['values']):assert abs(value-(20+15*math.sin(i*379/89/35)))<.8
    assert '不是精确逐日销量' in result['note'];assert '不能用估算点求和' in result['note']
    with pytest.raises(ValueError):trace_curve(image,[60,60,380,160],0,0,90)

def test_audience_bars_are_not_a_sales_curve():
    image=QImage(500,300,QImage.Format.Format_RGB32);image.fill(QColor('white'));p=QPainter(image)
    for x in (60,150,280,360):p.fillRect(x,80,20,150,QColor('#16a6f4'))
    p.end();assert locate_curve(image) is None
    with pytest.raises(ValueError):trace_curve(image,[40,50,420,210],100,0,90)

def test_curve_dialog_explicit_confirmation_and_note(app,tmp_path):
    path=tmp_path/'chart.png';chart_image().save(str(path));d=CurveDialog(path)
    d.selector.rect=[60,60,380,160];d.upper.setText('40');d.lower.setText('0');d.count.setText('90')
    d.apply();assert d.result()!=d.DialogCode.Accepted
    d.confirmed.setChecked(True);d.apply();assert d.result()==d.DialogCode.Accepted;assert len(d.result_data['values'])==90

def test_confirmed_curve_is_saved_with_estimate_provenance(app,store,graph,tmp_path):
    from workbench.ui import Editor
    path=tmp_path/'曲线截图.png';chart_image().save(str(path));asset=store.attach(path)
    d=Editor(store,'data_snapshots');d.fields['product_id'].setCurrentIndex(d.fields['product_id'].findData(graph[1]));d.fields['screenshot'].setText(asset)
    curve=trace_curve(read_image(path),[60,60,380,160],40,0,90)
    def approve(review):review.curve_result=curve;review.apply();return review.DialogCode.Accepted
    with patch.object(OCRReviewDialog,'exec',approve):d.got_ocr({'text':'销量曲线','words':[]})
    assert len(json.loads(d.fields['curve'].toPlainText()))==90
    assert '【曲线读图估算】' in d.fields['notes'].toPlainText()
    d.fields['confirmed'].setChecked(True);d.save();assert hasattr(d,'saved_id'),d.notice.text()
    assert store.analyze(graph[1])['曲线来源']=='读图估算，仅趋势参考'
