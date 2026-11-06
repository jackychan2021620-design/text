import math
import pytest
from PySide6.QtCore import QPointF,QEventLoop,QTimer
from PySide6.QtGui import QImage,QPainter,QPen,QColor
from workbench.curve import locate_curve,trace_curve,trace_manual
from workbench.curve_ui import CurveDialog
from conftest import record


def chart(color='#8cc5ee',gaps=False):
    image=QImage(500,300,QImage.Format.Format_RGB32);image.fill(QColor('white'));p=QPainter(image);p.setRenderHint(QPainter.RenderHint.Antialiasing);p.setPen(QPen(QColor(color),2));last=None
    for i in range(380):
        point=QPointF(60+i,60+(40-(20+15*math.sin(i/35)))/40*159)
        if last and not(gaps and i%85 in (1,2,3)):p.drawLine(last,point)
        last=point
    p.end();return image

@pytest.mark.parametrize('color',['#16a6f4','#3b66bb','#8cc5ee'])
def test_light_dark_jpeg_curve_lines(color,tmp_path):
    path=tmp_path/'curve.jpg';chart(color).save(str(path),'JPG',70);image=QImage(str(path));hint=locate_curve(image);assert hint
    values=trace_curve(image,[60,60,380,160],40,0,90)['values'];assert len(values)==90
    assert max(abs(value-(20+15*math.sin(i*379/89/35))) for i,value in enumerate(values))<2


def test_small_gaps_and_axis_words():
    words=[{'text':str(value),'left':20,'top':y-5,'width':20,'height':10} for value,y in [(40,60),(30,100),(20,140),(10,180),(0,220)]]
    image=chart(gaps=True);hint=locate_curve(image,words);assert hint and hint['upper']==40 and hint['lower']==0
    assert trace_curve(image,hint['rect'],40,0,90)['values']


def test_manual_trace_is_estimate_and_requires_valid_span():
    image=chart();points=[(60+i,140+30*math.sin(i/35)) for i in range(380)]
    result=trace_manual(image,[60,60,380,160],points,40,0,90);assert len(result['values'])==90;assert '手动描绘' in result['note']
    with pytest.raises(ValueError):trace_manual(image,[60,60,380,160],points[:3],40,0,90)


def test_curve_layout_cache_survives_snapshot_edit_and_backup(store,graph,tmp_path):
    words=[{'text':'40','left':20,'top':55,'width':20,'height':10}];path=tmp_path/'curve.png';chart().save(str(path));asset=store.attach(path)
    store.save_ocr_layout(asset,words);snapshot=record(store,'data_snapshots',product_id=graph[1],screenshot=asset)
    assert store.ocr_layout(store.get('data_snapshots',snapshot)['screenshot'])==words
    archive=tmp_path/'curve-cache.zip';store.backup(archive);store.restore(archive);assert store.ocr_layout(asset)==words


def test_automatic_preview_and_manual_fallback_controls(app,tmp_path):
    path=tmp_path/'curve.png';chart().save(str(path));d=CurveDialog(path)
    words=[{'text':str(v),'left':20,'top':y-5,'width':20,'height':10} for v,y in [(40,60),(30,100),(20,140),(10,180),(0,220)]]
    d.auto_ready({'hint':locate_curve(d.image,words),'words':words})
    assert d.upper.text()=='40';assert d.preview.series.count()==90;assert d.result_data
    d.manual.setChecked(True);d.selector.manual_points=[(60+i,140) for i in range(380)];d.extract();assert d.result_data and '手动描绘' in d.result_data['note'];d.reject()


def test_relative_curve_is_explicit_and_is_not_treated_as_absolute_sales(app,store,graph,tmp_path):
    from workbench.provenance import curve_source
    from workbench.ui import Editor
    path=tmp_path/'curve.png';chart().save(str(path));d=CurveDialog(path)
    hint=locate_curve(d.image);d.auto_ready({'hint':hint,'words':[]})
    assert d.relative.isChecked();assert d.result_data['source']=='相对走势';assert d.preview.series.count()==90
    d.confirmed.setChecked(True);d.apply();result=d.result_data
    notes=result['note'];id=record(store,'data_snapshots',product_id=graph[1],creators=100,sellers=30,sales=1200,curve=__import__('json').dumps(result['values']),notes=notes)
    assert curve_source(notes)=='相对走势';assert '不代表销量' in store.analyze(graph[1])['曲线来源']
    e=Editor(store,'data_snapshots',store.get('data_snapshots',id));assert e.fields['curve'].source=='相对走势'
    assert '无销量单位' in e.fields['curve'].plot.y_axis.titleText();e.reject()
