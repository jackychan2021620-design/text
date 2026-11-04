import csv
import json
import sqlite3
from datetime import date
import pytest
from zaowu.store import Store, fen
from conftest import record

def test_three_businesses_financial_boundaries(store):
    for business,status in [('DIY散客','已完成'),('花束业务','制作中'),('活动沙龙','成交')]:
        record(store,'orders',business=business,status=status,revenue=10000,material=3000,labor=1000,other=500,source='小红书',channel='美团')
    record(store,'orders',business='花束业务',status='已取消',revenue=100000)
    record(store,'orders',business='活动沙龙',status='报价',expected=500000,revenue=500000)
    record(store,'expenses',amount=2000)
    s=store.summary('2026-11-01','2026-11-30')
    assert (s['orders'],s['revenue'],s['contribution'],s['net_after_recorded_expenses'])==(3,30000,16500,14500)
    assert sum(s['by_business'].values())==s['revenue']
    assert s['sources']=={'小红书':3} and s['channels']=={'美团':3}
    assert store.summary('2026-11-01','2026-11-30','DIY散客')['fixed'] is None

def test_restart_persists_business_chat_memory(store):
    root=store.root
    record(store,'products',name='饮品蜡烛',price=12800,material=3200,active=1)
    record(store,'memories',title='门店背景',body='周末手作',share_ai=1)
    sid=store.new_session('营销诊断')
    store.add_message(sid,'user','分析经营数据')
    store.add_message(sid,'assistant','暂无经营订单')
    with Store(root).db as reopened:
        assert reopened.execute('SELECT price FROM products').fetchone()[0]==12800
        assert reopened.execute('SELECT count(*) FROM messages').fetchone()[0]==2
        assert reopened.execute('SELECT body FROM memories').fetchone()[0]=='周末手作'

def test_customer_stats_and_new_customer_cohort(store):
    cid=record(store,'customers',code='C0001')
    record(store,'orders',customer_id=cid,date='2026-10-01',revenue=10000)
    record(store,'orders',customer_id=cid,date='2026-11-04',revenue=20000,customer_kind='复购')
    record(store,'orders',revenue=1000)
    s=store.summary('2026-11-01','2026-11-30')
    assert (s['customers'],s['new_customers'],s['repeat_orders'],s['unlinked_orders'])==(1,0,1,1)
    assert store.customer_stats(cid)['累计消费']=='300.00'

def test_foreign_keys_and_business_consistency(store):
    pid=record(store,'products',name='花束',business='花束业务')
    with pytest.raises(ValueError,match='不属于'):
        record(store,'orders',product_id=pid)
    record(store,'orders',product_id=pid,business='花束业务')
    with pytest.raises(sqlite3.IntegrityError): store.delete('products',pid)
    with pytest.raises(ValueError): record(store,'orders',business='DIY散客',status='潜在客户')

@pytest.mark.parametrize('suffix',['.csv','.xlsx'])
def test_interchange_money_and_formula_safety(store,tmp_path,suffix):
    record(store,'products',name='=malicious()',price=12345,material=200)
    path=tmp_path/('products'+suffix)
    store.export_file('products',path)
    store.import_file('products',path)
    rows=store.rows('products')
    assert len(rows)==2 and all(r['price']==12345 and r['name']=='=malicious()' for r in rows)

def test_import_is_atomic(store,tmp_path):
    record(store,'customers',code='UNIQUE')
    path=tmp_path/'customers.csv'
    store.export_file('customers',path)
    with path.open(encoding='utf-8-sig',newline='') as f: rows=list(csv.DictReader(f))
    first=dict(rows[0],code='NEW')
    with path.open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows([first,rows[0]])
    with pytest.raises(ValueError,match='全部回滚'): store.import_file('customers',path)
    assert len(store.rows('customers'))==1

def test_backup_restore_and_corrupt_rejection(store,tmp_path):
    record(store,'products',name='原始项目')
    sid=store.new_session()
    store.add_message(sid,'user','保留历史')
    backup=store.backup()
    record(store,'products',name='后加项目')
    safety=store.restore(backup)
    assert safety.exists() and len(store.rows('products'))==1
    assert store.messages(sid)[0]['content']=='保留历史'
    invalid=tmp_path/'invalid.sqlite3'
    with sqlite3.connect(invalid) as db:
        db.execute('PRAGMA user_version=1')
    with pytest.raises(ValueError): store.restore(invalid)
    assert store.rows('products')[0]['name']=='原始项目'

def test_ai_context_privacy_and_comparison(store):
    cid=record(store,'customers',code='SECRET-CUSTOMER',notes='13800000000',preferences='微信号 private')
    record(store,'orders',customer_id=cid,notes='绝不外发',revenue=20000)
    record(store,'memories',title='不分享',body='隐藏资料',share_ai=0)
    record(store,'memories',title='已授权',body='公开背景',share_ai=1)
    context=store.context('客户经营助手','2026-11-01','2026-11-30')
    text=json.dumps(context,ensure_ascii=False)
    for secret in ('SECRET-CUSTOMER','13800000000','private','绝不外发','隐藏资料'): assert secret not in text
    assert '公开背景' in text and context['previous']['end']=='2026-10-31'

def test_inventory_reports_and_backup_repeatability(store):
    record(store,'inventory',item='玫瑰',unit='枝',movement='采购入库',quantity=20)
    record(store,'inventory',item='玫瑰',unit='枝',movement='制作领用',quantity=5)
    record(store,'inventory',item='玫瑰',unit='枝',movement='损耗',quantity=2)
    assert store.inventory_balance()=={'玫瑰（枝）':13}
    store.reports_due(date(2026,11,4))
    store.reports_due(date(2026,11,4))
    assert store.db.execute('SELECT count(*) FROM reports').fetchone()[0]==2
    store.auto_backup(); store.auto_backup()
    assert len(list((store.root/'backups').glob('*.sqlite3')))==1

def test_input_validation(store):
    assert fen('0.105')==11
    for value in ('-1','NaN','Infinity','abc'):
        with pytest.raises(ValueError): fen(value)
    with pytest.raises(ValueError): record(store,'orders',date='2026-13-01')
    with pytest.raises(ValueError): record(store,'products',price=-1)
    with pytest.raises(ValueError): record(store,'orders',quantity=0)
