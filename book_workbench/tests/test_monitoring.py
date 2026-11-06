"""Synthetic protocol fixtures; these tests do not claim live Douyin access."""
import json
from urllib.parse import quote
from unittest.mock import patch
import pytest
from PySide6.QtTest import QTest
from workbench.monitoring import (parse_page,public_url,MonitorStore,MonitorWorker,fetch_page)
from workbench.monitor_ui import MonitorController,MonitorPanel
from workbench.store import Store

OWNER='TEST-OWNER'
URL='https://www.douyin.com/user/'+OWNER

def html(likes=99,products=True,other_author=False):
    item={'aweme_id':'1234567890123456','desc':'介绍《测试书》，并非销量数据','author':{'sec_uid':'OTHER' if other_author else OWNER,'nickname':'测试账号'},'statistics':{'digg_count':likes},'create_time':1762000000}
    if products:item['promotions']=[{'title':'测试书·第2版','product_id':'test'}]
    data={'userInfo':{'user':{'secUid':OWNER,'nickname':'测试账号'}},'aweme_list':[item]}
    return '<script id="RENDER_DATA" type="application/json">'+quote(json.dumps(data))+'</script>'

def result(likes=99):return parse_page(html(likes),URL)

@pytest.mark.parametrize('url',['https://example.org/a','http://www.douyin.com/user/test','https://www.douyin.com.evil.org/user/test','https://a:b@www.douyin.com/user/test','https://127.0.0.1/a','https://www.douyin.com:8443/user/test'])
def test_only_official_public_urls(url):
    with pytest.raises(ValueError):public_url(url)

def test_share_noise_and_cart_evidence_are_separate():
    assert public_url('分享 https://v.douyin.com/zZoup5HEVkM/ 1@7.com :0pm')=='https://v.douyin.com/zZoup5HEVkM/'
    v=parse_page(html(),URL)['videos'][0];assert v['products']==['测试书·第2版'];assert v['likes']==99
    v=parse_page(html(products=False),URL)['videos'][0];assert v['products']==[];assert v['book_hints']==['测试书'];assert v['book_status']=='文案书名，挂车未确认'

@pytest.mark.parametrize('value',[None,'1.2万',True,-1])
def test_hidden_or_rounded_likes_not_treated_as_exact(value):
    with pytest.raises(ValueError):parse_page(html(value),URL)

def test_other_account_and_empty_login_page_are_not_success():
    with pytest.raises(ValueError):parse_page(html(other_author=True),URL)
    with pytest.raises(ValueError):parse_page('<html>请登录后查看</html>',URL)


def test_threshold_crossing_is_durable_and_once_even_after_drop(store,tmp_path):
    m=MonitorStore(store);m.add(URL);id=m.load()['accounts'][0]['id']
    assert not m.apply(id,result(99));assert len(m.apply(id,result(100)))==1
    assert not m.apply(id,result(101));m.mark_read(id);assert not m.apply(id,result(20));assert not m.apply(id,result(150))
    a=m.load()['accounts'][0];assert not a['unread'];assert len(a['alerted'])==1
    success=a['last_success'];m.apply(id,{'error':'连接失败'});a=m.load()['accounts'][0]
    assert a['last_success']==success;assert a['videos']['1234567890123456']['likes']==150;assert a['error']=='连接失败'
    archive=tmp_path/'monitor.zip';store.backup(archive);restored=Store(tmp_path/'restored')
    try:
        restored.restore(archive);other=MonitorStore(restored);assert not other.apply(id,result(200));assert other.load()['accounts'][0]['error']==''
    finally:restored.close()


def test_worker_updates_and_errors_keep_real_check_status(app,store):
    m=MonitorStore(store);m.add(URL);account=m.load()['accounts'][0];worker=MonitorWorker([account]);events=[];worker.result.connect(lambda id,value:events.append((id,value)))
    with patch('workbench.monitoring.fetch_page',return_value=(html(100),URL)):worker.run()
    assert len(events)==1;assert events[0][1]['videos'][0]['likes']==100
    with patch('workbench.monitoring.fetch_page',return_value=('<html>登录</html>',URL)):worker.run()
    assert events[-1][1].get('error');assert 'videos' not in events[-1][1]


def test_monitoring_opt_in_and_existing_data_visible(app,store):
    controller=MonitorController(store);assert len(controller.storage.load()['accounts'])==3;assert not controller.timer.isActive();assert controller.worker is None
    panel=MonitorPanel(controller);panel.show();QTest.qWait(20);assert panel.accounts.rowCount()==3;assert panel.works.rowCount()==0
    id=controller.storage.load()['accounts'][0]['id'];controller.receive(id,result(100));QTest.qWait(20)
    assert panel.works.rowCount()==1;assert panel.works.item(0,2).text()=='100'
    controller.receive(id,{'error':'测试网络失败'});assert panel.works.rowCount()==1;assert panel.accounts.item(0,3).text()=='测试网络失败'
    panel.close()


def test_video_share_resolves_only_its_author_not_recommended_account():
    from workbench.monitoring import parse_documents
    target={'aweme_id':'1234567890123456','author':{'sec_uid':OWNER,'nickname':'目标账号'},'statistics':{'digg_count':123},'desc':'目标作品'}
    other=target|{'aweme_id':'1234567890123457','author':{'sec_uid':'OTHER','nickname':'推荐账号'}}
    r=parse_documents([{'aweme_list':[target,other]}],'https://www.douyin.com/video/1234567890123456')
    assert r['owner']==OWNER;assert r['profile_url']==URL;assert len(r['videos'])==1
    with pytest.raises(ValueError):parse_documents([{'aweme_list':[other]}],'https://www.douyin.com/video/1234567890123456')


def test_new_november_posts_keep_string_millisecond_dates_and_missing_counts():
    from datetime import datetime,timezone
    from workbench.monitoring import parse_documents
    def v(id,stamp,likes):return {'aweme_id':str(id),'author':{'sec_uid':OWNER},'desc':'《新书》','create_time':stamp,'statistics':{'digg_count':likes}}
    october=datetime(2026,10,30,tzinfo=timezone.utc).timestamp();november=datetime(2026,11,4,tzinfo=timezone.utc).timestamp()
    docs=[{'aweme_list':[v(1234567890123456,october,100),v(1234567890123457,str(int(november*1000)),None),v(1234567890123458,'2026-11-05T08:00:00+08:00','123')]}]
    rows=parse_documents(docs,URL,partial=True)['videos'];by_id={r['id']:r for r in rows}
    assert len(rows)==3;assert by_id['1234567890123457']['published'].startswith('2026-11-04');assert by_id['1234567890123457']['likes'] is None
    assert by_id['1234567890123458']['published'].startswith('2026-11-05');assert by_id['1234567890123458']['likes']==123


def test_rounded_counts_use_conservative_threshold_and_do_not_invent_exact_likes():
    from workbench.monitoring import visible_likes,is_hot
    assert visible_likes('点赞100')['likes_exact'];assert is_hot(visible_likes('1.2万'))
    assert not visible_likes('1.2万')['likes_exact'];assert not is_hot(visible_likes('0.01万'));assert visible_likes('未知') is None


def test_nested_cart_names_and_unrelated_anchors():
    from workbench.monitoring import product_names
    assert product_names({'anchor_info':{'title':'购物','extra':json.dumps({'product_id':'p','product_title':'图解机器学习 第2版'})}})==['图解机器学习 第2版']
    assert product_names({'anchors':[{'title':'背景音乐','extra':{'music_id':'m'}}]})==[]


def test_partial_refresh_preserves_book_and_date_and_does_not_notify_stale_counts(store):
    from workbench.monitoring import MonitorStore,parse_documents
    m=MonitorStore(store);m.add(URL);id=m.load()['accounts'][0]['id'];m.apply(id,result(99))
    old=m.load()['accounts'][0]['videos']['1234567890123456'];fresh=old|{'likes':None,'likes_lower_bound':None,'products':[],'published':'','book_hints':[]}
    m.apply(id,result(99)|{'videos':[fresh]});v=m.load()['accounts'][0]['videos'][old['id']]
    assert v['likes']==99;assert v['products']==old['products'];assert v['published']==old['published'];assert not m.load()['accounts'][0]['unread']


def test_shared_video_does_not_bind_the_logged_in_viewer():
    from workbench.monitoring import parse_documents
    doc={'userInfo':{'user':{'sec_uid':'VIEWER'}},'aweme_detail':{'aweme_id':'1234567890123456','author':{'sec_uid':OWNER},'statistics':{'digg_count':100}}}
    assert parse_documents([doc],'https://www.douyin.com/video/1234567890123456')['owner']==OWNER
    with pytest.raises(ValueError):parse_documents([doc],'https://www.douyin.com/recommend')


def test_old_unverified_binding_is_archived_only_after_original_link_verification(store):
    from workbench.monitoring import MonitorStore
    m=MonitorStore(store);m.add(URL);id=m.load()['accounts'][0]['id']
    wrong=result(99)|{'owner':'WRONG','owner_aliases':['WRONG']};m.apply(id,wrong)
    assert m.load()['accounts'][0]['owner']=='WRONG'
    m.apply(id,result(100)|{'identity_verified':True});a=m.load()['accounts'][0]
    assert a['owner']==OWNER and a['identity_version']=='target-v2';assert a['archived_unverified'][0]['owner']=='WRONG';assert a['archived_unverified'][0]['videos']
    with pytest.raises(ValueError):m.apply(id,wrong|{'identity_verified':True})
