import json
import hashlib
from pathlib import Path
import pytest
from PySide6.QtGui import QImage,QColor
from PySide6.QtQml import QJSEngine
from studio.xhs import shared_url,media_url,parse_note,EXTRACT_JS,ImageWorker
from studio.vision import prepare_images,redact_images
from studio.store import Store

ID='a'*24
URL='https://www.xiaohongshu.com/explore/'+ID+'?xsec_token=public-test-share'

def payload():
    return {'note':{'noteId':ID,'title':'Synthetic micro-landscape fixture','desc':'Offline test text, not fetched platform content.','type':'normal',
        'imageList':[{'urlDefault':'http://sns-webpic-qc.xhscdn.com/first'},
                     {'infoList':[{'imageScene':'WB_DFT','url':'https://sns-webpic-qc.xhscdn.com/second'}]}]}}

def saved_images(store,tmp_path,app):
    note=parse_note(payload(),URL);results=[]
    for i,url in enumerate(note.images,1):
        path=tmp_path/f'{i}.png';image=QImage(60,80,QImage.Format.Format_RGB32);image.fill(QColor('green'));assert image.save(str(path),'PNG')
        results.append({'position':i,'url':url,'path':str(path),'error':''})
    return store.save_imported_note(note,results,'DIY散客')

def test_user_shared_text_and_signed_urls_preserved():
    text='😍姐妹们：“这种苔藓微景观自己能做！ 答案是：完全... https://xhslink.cn/o/4G6n41RTrkP 拷走文字，去【小红书】探索这篇笔记~'
    assert shared_url(text)=='https://xhslink.cn/o/4G6n41RTrkP'
    assert shared_url('link '+URL+'#fragment')==URL

@pytest.mark.parametrize('url',['https://xiaohongshu.com.evil.example/explore/'+ID,'http://127.0.0.1/','file:///tmp/a','https://xhslink.cn@evil.example/note','https://www.xiaohongshu.com/user/profile/'+ID])
def test_unrelated_urls_rejected(url):
    with pytest.raises(ValueError):shared_url(url)

def test_note_parser_keeps_all_images_order_and_exact_text():
    note=parse_note(json.dumps(payload()),URL)
    assert note.text==payload()['note']['desc']
    assert note.images==['https://sns-webpic-qc.xhscdn.com/first','https://sns-webpic-qc.xhscdn.com/second']
    assert len(note.images)==2
    bad=payload();bad['note']['noteId']='b'*24
    with pytest.raises(ValueError,match='不一致'):parse_note(bad,URL)
    with pytest.raises(ValueError,match='登录'):parse_note({'error':'login'},URL)
    bad=payload();bad['note']['imageList'].append({})
    with pytest.raises(ValueError,match='第3张'):parse_note(bad,URL)

def test_media_hosts_do_not_allow_private_urls():
    for url in ('https://127.0.0.1/image','https://xhscdn.com.evil.example/image','file:///image','https://user:pass@sns-webpic-qc.xhscdn.com/image'):
        with pytest.raises(ValueError):media_url(url)

def test_fixed_browser_script_exports_only_target_note(app):
    engine=QJSEngine()
    state={'account':{'private':'ACCOUNT_NOT_FOR_EXPORT'},'note':{'noteDetailMap':{ID:{'note':payload()['note']},'b'*24:{'note':{'desc':'other note'}}}}}
    setup='var location={pathname:"/explore/'+ID+'"}; var window={__INITIAL_STATE__:'+json.dumps(state)+'};'
    assert not engine.evaluate(setup).isError()
    output=engine.evaluate(EXTRACT_JS).toString()
    assert parse_note(output,URL).title==payload()['note']['title']
    assert 'ACCOUNT_NOT_FOR_EXPORT' not in output and 'other note' not in output

class Response:
    def __init__(self,content=b'',status=200,headers=None):self.content=content;self.status_code=status;self.headers=headers or {'Content-Type':'image/png'};self.closed=False
    def __enter__(self):return self
    def __exit__(self,*args):self.close()
    def close(self):self.closed=True
    def iter_content(self,*args):yield self.content

def test_image_download_decodes_and_marks_partial_failure(app,tmp_path,monkeypatch):
    source=tmp_path/'image.png';image=QImage(50,40,QImage.Format.Format_RGB32);image.fill(QColor('green'));assert image.save(str(source),'PNG')
    calls=[]
    def get(url,**kwargs):calls.append(kwargs);return Response(source.read_bytes()) if len(calls)==1 else Response(status=403)
    monkeypatch.setattr('studio.xhs.requests.get',get)
    worker=ImageWorker(parse_note(payload(),URL));result=[];worker.ready.connect(result.append);worker.run()
    try:
        assert len(result[0])==2
        assert result[0][0]['path'] is not None,result[0][0]['error']
        assert Path(result[0][0]['path']).exists()
        assert result[0][1]['path'] is None and '403' in result[0][1]['error']
        assert all(c['allow_redirects'] is False for c in calls)
    finally:worker.cleanup()

def test_unsafe_image_redirect_is_not_followed(app,monkeypatch):
    calls=[];response=Response(status=302,headers={'Location':'http://127.0.0.1/private'})
    def get(*args,**kwargs):calls.append(args);return response
    monkeypatch.setattr('studio.xhs.requests.get',get)
    note=parse_note(payload(),URL);note.images=note.images[:1]
    worker=ImageWorker(note);results=[];worker.ready.connect(results.append);worker.run()
    try:assert len(calls)==1 and response.closed and results[0][0]['path'] is None
    finally:worker.cleanup()

def test_import_storage_not_mixed_with_own_assets_and_survives_restart(store,tmp_path,app):
    ref=saved_images(store,tmp_path,app)
    assert store.rows('assets')==[] and len(store.reference_images(ref))==2
    assert store.reference_source(ref)['expected_images']==2
    assert all(Path(row['path']).is_file() for row in store.reference_images(ref))
    with pytest.raises(ValueError,match='已经收藏'):saved_images(store,tmp_path,app)
    assert len(store.rows('references'))==1
    other=Store(store.root)
    try:assert len(other.reference_images(ref))==2
    finally:other.close()

def test_full_bundle_contains_and_rebases_reference_images(store,tmp_path,app):
    ref=saved_images(store,tmp_path,app);bundle=tmp_path/'bundle.zip';store.export_bundle(bundle)
    target=Store(tmp_path/'restored')
    try:
        target.restore_bundle(bundle)
        assert all(Path(r['path']).parent==target.root/'assets' and Path(r['path']).exists() for r in target.reference_images(ref))
        assert target.get('references',ref)['excerpt']==payload()['note']['desc']
    finally:target.close()

def test_partial_import_never_reports_all_pixels_sent(store):
    note=parse_note(payload(),URL)
    images=[{'position':i+1,'url':u,'path':None,'error':'not fetched'} for i,u in enumerate(note.images)]
    ref=store.save_imported_note(note,images,'DIY散客')
    context=store.context('DIY散客',reference_id=ref,task='拍摄与发布方案')
    assert context['reference_media']['saved_images']==0 and context['reference_media']['pixel_input'] is False
    with pytest.raises(ValueError,match='未读到'):prepare_images(store,ref)

def test_visual_payload_contains_actual_ordered_pixels_but_audit_does_not(store,tmp_path,app):
    ref=saved_images(store,tmp_path,app);parts,manifest=prepare_images(store,ref)
    assert len(manifest)==2 and len(parts)==4
    assert parts[1]['image_url']['url'].startswith('data:image/png;base64,')
    messages=[{'role':'user','content':parts}]
    assert 'data:image' not in json.dumps(redact_images(messages))
    assert [x['position'] for x in manifest]==[1,2]

def test_upgrade_and_restore_version_one_without_losing_data(store,tmp_path):
    from conftest import record
    record(store,'offers',name='Version one existing data')
    with store.db:
        store.db.execute('DROP TABLE reference_images');store.db.execute('DROP TABLE reference_sources');store.db.execute('PRAGMA user_version=1')
    old=store.backup(tmp_path/'version1.sqlite3')
    store.migrate()
    assert store.db.execute('PRAGMA user_version').fetchone()[0]==2
    store.restore(old)
    assert store.db.execute('PRAGMA user_version').fetchone()[0]==2
    assert store.rows('offers')[0]['name']=='Version one existing data'

def test_update_import_preserves_manual_analysis(store,tmp_path,app):
    ref=saved_images(store,tmp_path,app);row=store.get('references',ref);row['mechanism']='My manual observation';store.save('references',row,ref)
    note=parse_note(payload(),URL);note.title='Updated source title'
    images=[dict(row) for row in store.reference_images(ref)]
    assert store.save_imported_note(note,images,'DIY散客',update=True)==ref
    assert store.get('references',ref)['mechanism']=='My manual observation'
    assert store.get('references',ref)['title']=='Updated source title'

def test_confirmed_visual_analysis_sends_pixels_but_does_not_store_base64(store,tmp_path,app,monkeypatch):
    from PySide6.QtWidgets import QDialog
    from PySide6.QtTest import QTest
    from studio.ui import MainWindow
    from studio.ai_dialog import AIDialog
    from test_ai import Response as AIResponse
    ref=saved_images(store,tmp_path,app);window=MainWindow(store);window.runtime_vision_key='not-a-real-key';window.runtime_key='synthetic-deepseek-key'
    store.set_setting('vision_model','configured-vision-model')
    store.set_setting('model','configured-text-model')
    monkeypatch.setattr(QDialog,'exec',lambda self:QDialog.DialogCode.Accepted)
    requests=[]
    def post(url,**kwargs):requests.append(kwargs['json']);return AIResponse(['data: {"choices":[{"delta":{"content":"Synthetic visual reply"}}]}','data: [DONE]'])
    monkeypatch.setattr('studio.ai.requests.post',post)
    context=store.context('DIY散客',reference_id=ref,task='看图拍摄方案')
    dialog=AIDialog(window,'看图拍摄方案',context);dialog.generate()
    for _ in range(100):
        QTest.qWait(10)
        if dialog.ok:break
    assert dialog.ok
    sent=requests[0]['messages'][-1]['content']
    assert sum(item['type']=='image_url' for item in sent)==2
    assert 'data:image/png;base64,' in json.dumps(sent)
    assert len(requests)==2 and 'data:image/png;base64,' not in json.dumps(requests[1])
    persisted=store.rows('ai_runs')[0]['context']
    assert 'data:image/png;base64,' not in persisted and 'not-a-real-key' not in persisted
    dialog.reject();window.force_quit=True;window.close()
