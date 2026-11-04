import csv
import json
import sqlite3
from pathlib import Path
import pytest
from studio.store import Store,money
from studio.model import FEEDBACK_FIELDS
from conftest import record,values,published

def test_new_database_is_empty_and_separate(store):
    for table in ('offers','references','pieces','assets','learnings','ai_runs'):assert store.rows(table)==[]
    assert store.path.name=='studio.sqlite3'
    assert store.db.execute('PRAGMA foreign_keys').fetchone()[0]==1

def test_stage_gates_and_complete_workflow(store):
    piece=record(store,'pieces',topic='测试选题')
    with pytest.raises(ValueError,match='希望谁'):store.advance(piece)
    p=store.get('pieces',piece);p.update(audience='本地顾客',hypothesis='待验证表达');store.save('pieces',p,piece,p['version'])
    assert store.advance(piece)=='素材'
    with pytest.raises(ValueError,match='真实产品'):store.advance(piece)
    offer=record(store,'offers',name='真实服务')
    p=store.get('pieces',piece);p.update(offer_id=offer,angle='文字解释');store.save('pieces',p,piece)
    assert store.advance(piece)=='草稿'
    with pytest.raises(ValueError,match='标题'):store.advance(piece)
    p=store.get('pieces',piece);p.update(title='标题',body='【待确认：价格】',cta='咨询');store.save('pieces',p,piece)
    with pytest.raises(ValueError,match='待确认'):store.advance(piece)
    p=store.get('pieces',piece);p.update(body='真实内容');store.save('pieces',p,piece)
    assert store.advance(piece)=='待发布'
    with pytest.raises(ValueError,match='发布日期'):store.advance(piece)
    p=store.get('pieces',piece);p.update(published_date='2026-11-04');store.save('pieces',p,piece)
    assert store.advance(piece)=='已发布'
    with pytest.raises(ValueError,match='反馈'):store.advance(piece)
    store.add_feedback(piece,values(FEEDBACK_FIELDS,facts='收到一次咨询',next_action='继续验证'))
    assert store.advance(piece)=='已复盘'

def test_latest_cumulative_snapshot_not_sum_and_missing_not_zero(store):
    piece=published(store)
    store.add_feedback(piece,values(FEEDBACK_FIELDS,observed_date='2026-11-05',views=100,orders=1))
    store.add_feedback(piece,values(FEEDBACK_FIELDS,observed_date='2026-11-06',views=200,orders=2,spend=0))
    store.add_feedback(piece,values(FEEDBACK_FIELDS,observed_date='2026-11-04',views=50,orders=0))
    report=store.review()
    assert report['totals']['views']['value']==200
    assert report['totals']['orders']['value']==2
    assert report['totals']['impressions']['value'] is None
    assert report['totals']['spend']['value']==0

def test_feedback_only_after_publish_and_valid_dates(store):
    piece=record(store,'pieces')
    with pytest.raises(ValueError,match='实际发布'):store.add_feedback(piece,values(FEEDBACK_FIELDS))
    piece=published(store)
    with pytest.raises(ValueError,match='不能早于'):store.add_feedback(piece,values(FEEDBACK_FIELDS,observed_date='2026-11-03'))
    with pytest.raises(ValueError):store.add_feedback(piece,values(FEEDBACK_FIELDS,views=-1))
    with pytest.raises(ValueError):store.add_feedback(piece,values(FEEDBACK_FIELDS,views='NaN'))

def test_optimistic_version_prevents_ai_overwrite(store):
    piece=record(store,'pieces',topic='原选题');old=store.get('pieces',piece)
    store.save('pieces',old|{'title':'人工先修改'},piece,old['version'])
    with pytest.raises(ValueError,match='已经更新'):store.save('pieces',old|{'title':'过期草稿'},piece,old['version'])
    assert store.get('pieces',piece)['title']=='人工先修改'

def test_business_scope_and_memory_authorization(store):
    flower=record(store,'offers',business='鲜花花束',name='不属于DIY')
    with pytest.raises(ValueError,match='不属于'):record(store,'pieces',offer_id=flower)
    record(store,'learnings',title='隐藏',body='不发送的资料',share_ai=0)
    record(store,'learnings',title='授权',body='待验证方向',share_ai=1)
    c=store.context('DIY散客',task='选题计划')
    text=json.dumps(c,ensure_ascii=False)
    assert '不发送的资料' not in text and '待验证方向' in text and '不属于DIY' not in text

def test_fact_memory_requires_evidence(store):
    with pytest.raises(ValueError,match='证据'):record(store,'learnings',level='本店已验证',body='有效')
    record(store,'learnings',level='观察事实',body='收到咨询',basis='11月4日记录')

def test_atomic_plan_rollback(store):
    with pytest.raises(ValueError):
        with store.transaction():
            record(store,'pieces',topic='第一条')
            record(store,'pieces',topic='第二条',plan_date='2026-13-01')
    assert store.rows('pieces')==[]

def test_asset_copy_deduplicate_and_link_protection(store,tmp_path):
    source=tmp_path/'source.png';source.write_bytes(b'fake-media-for-storage-test')
    asset=store.add_asset(source,'DIY散客','人工描述')
    assert store.add_asset(source,'DIY散客')==asset
    source.unlink()
    assert Path(store.get('assets',asset)['path']).exists()
    piece=record(store,'pieces');store.link_assets(piece,[asset])
    with pytest.raises(sqlite3.IntegrityError):store.delete('assets',asset)
    other=record(store,'pieces',business='鲜花花束')
    with pytest.raises(ValueError):store.link_assets(other,[asset])
    context=store.context('DIY散客',piece_id=piece)
    assert 'path' not in str(context['selected_assets'])
    assert context['selected_assets'][0]['description']=='人工描述'

def test_backup_restore_invalid_rejected_and_restart(store,tmp_path):
    record(store,'offers',name='保留记录');backup=store.backup()
    record(store,'offers',name='之后新增');safety=store.restore(backup)
    assert safety.exists() and len(store.rows('offers'))==1
    with Store(store.root).db as reopened:assert reopened.execute('SELECT name FROM offers').fetchone()[0]=='保留记录'
    invalid=tmp_path/'invalid.sqlite3'
    with sqlite3.connect(invalid) as db:db.execute('PRAGMA user_version=1')
    with pytest.raises(ValueError):store.restore(invalid)
    assert len(store.rows('offers'))==1

def test_next_action_and_backups_idempotent(store):
    late=record(store,'pieces',plan_date='2026-11-09')
    early=record(store,'pieces',plan_date='2026-11-04')
    assert store.next_piece()['id']==early
    assert store.next_piece('鲜花花束') is None
    store.maintain();store.maintain()
    assert len(list((store.root/'backups').glob('*.sqlite3')))==1

def test_csv_missing_and_formula_protection(store,tmp_path):
    piece=published(store);p=store.get('pieces',piece);store.save('pieces',p|{'topic':'=formula()'},piece)
    store.add_feedback(piece,values(FEEDBACK_FIELDS,views=0,contribution=-1050))
    path=tmp_path/'feedback.csv';store.export_review(path)
    with path.open(encoding='utf-8-sig') as file:r=next(csv.DictReader(file))
    assert r['topic']=="'=formula()" and r['views']=='0' and r['impressions']=='' and r['contribution']=='-10.50'
    assert money('10.105')==1011

@pytest.mark.parametrize('number',['NaN','Infinity','not a number'])
def test_money_invalid(number):
    with pytest.raises(ValueError):money(number)
