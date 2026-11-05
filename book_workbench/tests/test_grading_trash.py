import json
from pathlib import Path
from unittest.mock import patch
import pytest
from PySide6.QtCore import Qt,QTimer
from PySide6.QtWidgets import QApplication,QMessageBox,QPushButton,QTableWidget
from PySide6.QtTest import QTest
from workbench.grading import grade,render,LEVELS,percentile,validate_rules
from workbench.provenance import UNKNOWN
from workbench.store import Store
from workbench.ui import MainWindow
from workbench.services import SYSTEM
from conftest import record

def samples():
    return [{'creators':100,'sellers':10*(i+1),'sales':100*(i+1)**2,'period_days':90,'confirmed':1,'curve':'[10,10,10,10,10,10,10]','notes':''} for i in range(5)]

@pytest.mark.parametrize('snapshot,shape,expected',[
    ({'creators':100,'sellers':30,'sales':1200},'稳定销售型','非常适合'),
    ({'creators':100,'sellers':20,'sales':1000},'持续增长型','非常适合'),
    ({'creators':100,'sellers':10,'sales':500},'单次爆发型','适合'),
    ({'creators':100,'sellers':1,'sales':2},'持续衰退型','直接放弃'),
    ({'creators':100,'sellers':1,'sales':2},'稳定销售型','适合'),
])
def test_single_book_uses_absolute_rules_independent_of_peers(snapshot,shape,expected):
    p=samples()[0]|snapshot
    for peers in ([],[p],samples(),list(reversed(samples()))):
        r=grade(p,peers,shape);assert r['等级']==expected;assert r['等级'] in LEVELS;assert len(r['理由'])<100

@pytest.mark.parametrize('change',[{'sales':None},{'creators':None},{'period_days':30},{'notes':UNKNOWN},{'confirmed':0},{'creators':0}])
def test_missing_or_mismatched_data_is_not_abandon(change):
    peers=samples();r=grade(peers[0]|change,peers,'持续衰退型');assert r['等级'] is None;assert r['状态']=='待补数据'

def test_insufficient_peers_and_curve_do_not_block_single_book():
    p=samples()[-1]
    assert grade(p,[],'稳定销售型')['等级']=='非常适合'
    assert grade(p,[p],'数据不足')['等级']=='适合'
    assert '曲线不足' in grade(p,[p],'数据不足')['理由']
    assert grade(p,[],'稳定销售型',{'high_sales':3000})['等级']=='适合'
    assert '同类百分位' not in grade(p,[p],'稳定销售型')
    assert '同类百分位' in grade(p,samples(),'稳定销售型')
    assert grade(p,[],'稳定销售型')['等级']==grade(p,samples(),'稳定销售型')['等级']

def test_zero_outcomes_ties_and_inconsistent_counts():
    p=samples()[0]|{'sellers':0,'sales':0};assert grade(p,[],'低销量型')['等级']=='直接放弃'
    assert percentile(100,[100]*5)==50
    assert grade(samples()[0]|{'sellers':0},[],'稳定销售型')['等级'] is None
    assert grade(samples()[0]|{'sales':5},[],'稳定销售型')['等级'] is None

@pytest.mark.parametrize('rules',[{'min_peers':1},{'high_rate':5,'low_rate':20},{'high_sales':'nan'},{'low_sales':-1},{'high_sellers':1.5},{'high_rate':101}])
def test_invalid_grading_configuration_rejected(rules):
    with pytest.raises(ValueError):validate_rules(rules)

def test_default_recommendation_is_two_line_fixed_rule_output_without_api(app,store,graph):
    b,p=graph
    for i in range(5):
        product=p if i==0 else record(store,'product_links',book_id=b,url=f'https://example.org/{i}')
        record(store,'data_snapshots',product_id=product,creators=100,sellers=(i+1)*10,sales=(i+1)**2*100,curve='10,10,10,10,10,10,10')
    window=MainWindow(store)
    assert window.ai_task.currentText()=='三档选品推荐'
    assert not window.question.isEnabled()
    with patch('workbench.services.requests.post') as network:window.send_ai();network.assert_not_called()
    text=window.ai_output.toPlainText();assert '非常适合' in text;assert '档次：适合' in text
    assert '数据事实' not in text and '下一步建议' not in text
    for block in text.split('\n\n'):assert len(block.splitlines())==3 # book title + exactly two answer lines
    assert store.rows('ai_analysis_history')[0]['status']=='固定规则推荐'
    window.quitting=True;window.close()

def test_system_and_free_question_display_are_brief_but_full_reply_retrievable(app,store):
    assert '两行' in SYSTEM;assert '不强制五段报告' in SYSTEM
    window=MainWindow(store);window.ai_task.setCurrentText('简短问答');assert window.question.isEnabled()
    text='结论：适合。\n理由：数据可供测试。\n'+'补充说明。'*100
    window.show_ai_answer(text);assert len(window.ai_output.toPlainText())<240
    assert window.ai_full_answer==text;window.toggle_ai_answer();assert window.ai_output.toPlainText()==text
    window.quitting=True;window.close()

def test_delete_bad_row_in_screenshot_keeps_good_latest_and_reminder(store,graph):
    p=graph[1];bad=record(store,'data_snapshots',product_id=p,collected='2026-11-05')
    good=record(store,'data_snapshots',product_id=p,collected='2026-11-05',creators=105,sellers=32,sales=1194,curve='1,2,3,4,5,6,7')
    before=store.reminders('2026-11-05')['商品15天']
    store.delete('data_snapshots',bad)
    assert [r['id'] for r in store.rows('data_snapshots')]==[good]
    assert store.latest('data_snapshots','product_id',p)['sales']==1194
    assert store.reminders('2026-11-05')['商品15天']==before
    assert '至少两次' in store.snapshot_diff(p)['说明']
    assert [s['id'] for s in store.context()['快照']]==[good]
    assert all(r['snapshot_id']!=bad for r in store.rows('product_analyses'))
    assert store.deleted_rows('data_snapshots')[0]['id']==bad;assert store.get('data_snapshots',bad)['creators'] is None
    assert store.db.execute('PRAGMA foreign_key_check').fetchall()==[]

def test_delete_latest_last_and_restore_recalculates_only_target_product(store,graph):
    p=graph[1];p2=record(store,'product_links',book_id=graph[0],url='https://example.org/p2')
    old=record(store,'data_snapshots',product_id=p,collected='2026-10-01',sales=10)
    new=record(store,'data_snapshots',product_id=p,collected='2026-10-16',sales=20)
    other=record(store,'data_snapshots',product_id=p2,collected='2026-10-20')
    v=record(store,'video_tests',product_id=p);video=store.reminders()['视频5天']
    store.delete('data_snapshots',new);assert store.latest('data_snapshots','product_id',p)['id']==old
    assert store.db.execute('SELECT due FROM snapshot_reminders WHERE product_id=?',(p,)).fetchone()[0]=='2026-10-16'
    store.delete('data_snapshots',old);assert store.latest('data_snapshots','product_id',p) is None
    assert store.db.execute('SELECT 1 FROM snapshot_reminders WHERE product_id=?',(p,)).fetchone() is None
    assert store.latest('data_snapshots','product_id',p2)['id']==other;assert store.reminders()['视频5天']==video
    store.restore_deleted('data_snapshots',new)
    assert store.latest('data_snapshots','product_id',p)['sales']==20
    assert store.db.execute('SELECT due FROM snapshot_reminders WHERE product_id=?',(p,)).fetchone()[0]=='2026-10-31'

def test_deleted_ad_with_report_preserves_evidence_but_not_current_review(store,graph):
    b,p=graph;v=record(store,'video_tests',product_id=p);ad=record(store,'advertising_records',video_id=v,spend=200,orders=10,actual_gmv=400)
    store.complete_review(v);assert store.video_comparison(b)[0]['复盘']
    store.delete('advertising_records',ad)
    assert not store.rows('advertising_records');assert store.latest('advertising_records','video_id',v) is None
    assert store.video_comparison(b)[0]['复盘'] is None;assert store.reminders()['视频5天']
    assert store.get('advertising_records',ad)['actual_gmv']==400
    assert store.rows('video_review_reports',include_deleted=True)
    assert not store.context()['复盘'];assert store.db.execute('PRAGMA foreign_key_check').fetchall()==[]
    store.restore_deleted('advertising_records',ad);assert store.video_comparison(b)[0]['复盘'];assert not store.reminders()['视频5天']

def test_deleted_state_survives_restart_and_backup_restore(store,graph,tmp_path):
    id=record(store,'data_snapshots',product_id=graph[1]);store.delete('data_snapshots',id)
    store.close();store.connect();store.migrate();assert not store.rows('data_snapshots')
    package=tmp_path/'deleted-state.zip';store.backup(package)
    other=Store(tmp_path/'restored')
    try:
        other.restore(package);assert not other.rows('data_snapshots');assert other.deleted_rows('data_snapshots')[0]['id']==id
        other.restore_deleted('data_snapshots',id);assert other.rows('data_snapshots')[0]['id']==id
    finally:other.close()

def test_ui_delete_and_recycle_restore_real_row(app,store,graph):
    bad=record(store,'data_snapshots',product_id=graph[1]);good=record(store,'data_snapshots',product_id=graph[1],sales=1194)
    window=MainWindow(store);window.nav.setCurrentRow(2);window.show();app.processEvents();window.table.selectRow(1)
    delete=next(b for b in window.center.findChildren(QPushButton) if b.text()=='删除')
    def confirm_delete():
        dialog=QApplication.activeModalWidget();dialog.findChild(QPushButton,'confirmAction').click()
    QTimer.singleShot(0,confirm_delete);QTest.mouseClick(delete,Qt.MouseButton.LeftButton)
    assert [r['id'] for r in window.visible]==[good]
    def restore():
        dialog=QApplication.activeModalWidget();table=dialog.findChild(QTableWidget);table.selectRow(0)
        b=next(x for x in dialog.findChildren(QPushButton) if x.text()=='恢复选中记录');QTest.mouseClick(b,Qt.MouseButton.LeftButton);dialog.accept()
    QTimer.singleShot(0,restore);window.recycle_bin('data_snapshots')
    assert {r['id'] for r in window.visible}=={bad,good};window.quitting=True;window.close()


def test_analysis_cache_invalidates_on_snapshot_delete_restore_and_rule_change(store,graph):
    p=graph[1];id=record(store,'data_snapshots',product_id=p,creators=100,sellers=30,sales=1200,curve='20,20,20,20,20,20,20')
    assert store.analyze(p)['等级']=='非常适合'
    store.settings({'grade_high_sales':'1500'});assert store.analyze(p)['等级']=='适合'
    store.delete('data_snapshots',id);assert store.analyze(p)['等级'] is None
    store.restore_deleted('data_snapshots',id);assert store.analyze(p)['等级']=='适合'
