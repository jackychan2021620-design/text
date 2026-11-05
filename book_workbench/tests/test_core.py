import json
import sqlite3
import zipfile
import pytest
from workbench import analysis
from workbench.store import Store
from conftest import record

def test_book_multiple_links_and_crud(store,graph):
    b,p=graph;p2=record(store,'product_links',book_id=b,url='https://example.org/2')
    store.save('books',{'name':'数学手册新版','category':'科普'},b)
    assert len(store.rows('product_links'))==2
    assert store.get('books',b)['name']=='数学手册新版'
    with pytest.raises(sqlite3.IntegrityError):store.delete('books',b)
    store.delete('product_links',p2);assert len(store.rows('product_links'))==1

def test_metrics_snapshots_independent_dates(store,graph):
    b,p=graph;p2=record(store,'product_links',book_id=b,url='https://example.org/2')
    record(store,'data_snapshots',product_id=p,creators=100,sellers=20,sales=1000,curve='1,2,3,4,5,6,7')
    record(store,'data_snapshots',product_id=p2,collected='2026-10-02')
    a=store.analyze(p);assert a['达人出单率']==.2;assert a['出单达人人均销量']==50;assert a['参与达人人均销量']==10
    r=store.reminders('2026-10-16')['商品15天'];assert [x['分组'] for x in r]==['今日','即将到期']
    record(store,'data_snapshots',product_id=p,collected='2026-10-16',creators=110,sellers=25,sales=1200)
    assert store.db.execute('SELECT due FROM snapshot_reminders WHERE product_id=?',(p,)).fetchone()[0]=='2026-10-31'
    assert store.snapshot_diff(p)['滚动指标差值']['sales']==200
    assert '不等于15天' in store.snapshot_diff(p)['说明']
    # Backfilled historical data cannot move the reminder backwards.
    record(store,'data_snapshots',product_id=p,collected='2026-09-01')
    assert store.db.execute('SELECT due FROM snapshot_reminders WHERE product_id=?',(p,)).fetchone()[0]=='2026-10-31'

@pytest.mark.parametrize('changes',[{'creators':0,'sellers':0,'sales':0},{'creators':None,'sellers':None,'sales':None}])
def test_zero_denominator_unknown(store,graph,changes):
    record(store,'data_snapshots',product_id=graph[1],**changes)
    a=store.analyze(graph[1]);assert a['达人出单率'] is None

@pytest.mark.parametrize('values',[{'creators':2,'sellers':3},{'confirmed':0},{'sales':-1},{'sales':'nan'},{'sales':1.5},{'curve':'[1, -1]'}])
def test_reject_bad_snapshot(store,graph,values):
    with pytest.raises(ValueError):record(store,'data_snapshots',product_id=graph[1],**values)
    assert store.rows('data_snapshots')==[]

def test_video_clocks_defer_early_review(store,graph):
    p=graph[1];v1=record(store,'video_tests',product_id=p,ad_started='2026-10-03',submitted='2026-10-02');v2=record(store,'video_tests',product_id=p,code='V2')
    tasks=store.reminders('2026-10-06')['视频5天'];assert [r['due'] for r in tasks]==['2026-10-06','2026-10-08']
    report=store.complete_review(v1,'提前复盘');assert report['当前视频处理建议']=='暂不能判断'
    assert len(store.reminders('2026-10-06')['视频5天'])==1
    before=store.db.execute('SELECT original_due FROM video_review_tasks WHERE video_id=?',(v1,)).fetchone()[0]
    store.defer(v1,2);store.defer(v1,3)
    assert store.db.execute('SELECT original_due FROM video_review_tasks WHERE video_id=?',(v1,)).fetchone()[0]==before
    assert len(store.rows('video_review_reports'))==3
    assert len(store.reminders('2026-10-06')['视频5天'])==2
    assert store.reminders()['商品15天']==[]

def test_video_manual_date_and_snapshot_separation(store,graph):
    p=graph[1];v=record(store,'video_tests',product_id=p,review_override='2026-11-20')
    old=store.get('video_tests',v);store.save('video_tests',old|{'review_override':'2026-11-21'},v)
    task=store.db.execute('SELECT * FROM video_review_tasks').fetchone();assert task['due']=='2026-11-21';assert task['original_due']=='2026-11-20'
    record(store,'data_snapshots',product_id=p);assert store.db.execute('SELECT due FROM video_review_tasks').fetchone()[0]=='2026-11-21'

@pytest.mark.parametrize('ad,expected',[
({},'暂不能判断'),({'spend':0,'actual_gmv':0},'暂不能判断'),({'spend':10,'orders':0},'继续观察'),
({'spend':200,'orders':0,'actual_gmv':0},'暂缓投入'),({'spend':200,'orders':8,'actual_gmv':400},'继续投入'),
({'spend':200,'orders':8,'actual_gmv':100},'优化后再测'),({'spend':200,'orders':None,'actual_gmv':100},'继续观察')])
def test_five_review_conclusions(ad,expected):
    report=analysis.review(ad,[],{});assert report['当前视频处理建议']==expected
    if not ad.get('spend'):assert report['实际GMV/广告消耗'] is None

def test_ad_gmv_separation_comparison_history(store,graph):
    b,p=graph;v=record(store,'video_tests',product_id=p);v2=record(store,'video_tests',product_id=p,code='V2')
    record(store,'advertising_records',video_id=v,spend=200,orders=10,actual_gmv=400,backend_gmv=900,backend_roi=4.5)
    record(store,'advertising_records',video_id=v2,spend=100,orders=0,actual_gmv=0)
    report=store.review(v);assert report['实际GMV/广告消耗']==2;assert report['同书其他视频样本数']==1
    assert store.review(v2)['当前视频处理建议']=='暂缓投入';assert '同书存在' in store.review(v2)['同一本书是否继续更新视频']
    store.complete_review(v);store.complete_review(v)
    assert len(store.rows('video_review_reports'))==2
    assert store.video_comparison(b)[1]['广告']['backend_gmv']==900
    record(store,'advertising_records',video_id=v,collected='2026-10-06',spend=300,orders=12,actual_gmv=600)
    assert store.latest('advertising_records','video_id',v)['spend']==300 # not 500
    ctx=store.context();assert len(ctx['快照'])==0;assert len(ctx['广告'])==3;assert ctx['复盘']

def test_immutable_snapshots(store,graph):
    id=record(store,'data_snapshots',product_id=graph[1])
    with pytest.raises(ValueError):store.save('data_snapshots',store.get('data_snapshots',id),id)
    with pytest.raises(ValueError):store.delete('data_snapshots',id)

def test_compare_relative_category_and_limits(store,graph):
    b,p=graph;ids=[p]
    for i in range(5):
        if i:ids.append(record(store,'product_links',book_id=b,url=f'https://example.org/{i}'))
        record(store,'data_snapshots',product_id=ids[i],creators=100,sellers=10+i,sales=100+i*100)
    assert '百分位' in store.analyze(ids[-1])['市场需求']
    result=store.compare(ids);assert result[0]['商品']['id']==ids[-1];assert all(r['理由'] for r in result)
    with pytest.raises(ValueError):store.compare([p])

@pytest.mark.parametrize('values,expected',[([0]*7,'低销量型'),([10]*7,'稳定销售型'),([10,10,10,20,20,20,20],'持续增长型'),([20,20,20,10,10,10,10],'持续衰退型'),([1,1,30,1,1,1,1],'单次爆发型'),([1,30,1,1,30,1,1],'多次高峰型'),([1],'数据不足')])
def test_curve_rules(values,expected):assert analysis.trend(values)==expected

def test_restart_migrate_backup_restore_with_attachment(store,graph,tmp_path,app):
    from PySide6.QtGui import QImage,QColor
    source=tmp_path/'screen.png';image=QImage(30,30,QImage.Format.Format_RGB32);image.fill(QColor('white'));image.save(str(source))
    p=graph[1];record(store,'data_snapshots',product_id=p,screenshot=str(source),ocr_text='人工核对原文',sales=10)
    record(store,'video_tests',product_id=p)
    archive=tmp_path/'backup.zip';store.backup(archive)
    record(store,'books',name='备份之后')
    safety=store.restore(archive);assert safety.is_file();assert len(store.rows('books'))==1
    asset=store.rows('data_snapshots')[0]['screenshot'];assert store.asset(asset).is_file()
    root=store.root;store.close();store.connect();store.migrate();assert len(store.rows('video_tests'))==1
    assert store.reminders()['商品15天'];assert store.reminders()['视频5天']
    other=Store(tmp_path/'restored');other.restore(archive);assert other.asset(asset).read_bytes()==source.read_bytes();other.close()
    store.daily_backup();store.daily_backup();assert len(list((root/'backups').glob('auto-*.zip')))==1

@pytest.mark.parametrize('corruption',['path','hash','missing'])
def test_reject_corrupt_backups(store,graph,tmp_path,corruption):
    archive=tmp_path/'backup.zip';store.backup(archive)
    with zipfile.ZipFile(archive) as z:files={n:z.read(n) for n in z.namelist()}
    if corruption=='path':files['../evil']=b'x'
    elif corruption=='hash':files['books.sqlite3']=b'corrupt'
    else:del files['books.sqlite3']
    with zipfile.ZipFile(archive,'w') as z:
        for n,raw in files.items():z.writestr(n,raw)
    with pytest.raises(ValueError):store.restore(archive)
    assert store.get('books',graph[0])['name']=='数学手册'

def test_ad_screenshot_independent_nullable_metrics(store,graph,tmp_path,app):
    from PySide6.QtGui import QImage,QColor
    source=tmp_path/'ad.png';image=QImage(10,10,QImage.Format.Format_RGB32);image.fill(QColor('white'));image.save(str(source))
    v=record(store,'video_tests',product_id=graph[1])
    with pytest.raises(ValueError):record(store,'advertising_records',video_id=v,screenshot=str(source),confirmed=0)
    id=record(store,'advertising_records',video_id=v,screenshot=str(source),confirmed=1,actual_gmv=128,backend_gmv=300)
    row=store.get('advertising_records',id);assert row['spend'] is None;assert row['orders'] is None
    assert row['actual_gmv']==128;assert row['backend_gmv']==300;assert row['backend_roi'] is None
    assert store.review(v)['实际GMV/广告消耗'] is None

def test_ai_scoped_context(store,graph):
    b,p=graph;b2=record(store,'books',name='其他图书');record(store,'product_links',book_id=b2)
    assert len(store.context()['图书'])==2
    ctx=store.context(b);assert len(ctx['图书'])==1;assert ctx['商品'][0]['档案']['id']==p
    assert '不包含其他图书' in ctx['范围说明']
