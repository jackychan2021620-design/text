import json
import threading
import time
import pytest
import requests
from PySide6.QtCore import QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDialog
from studio.ai import configured_vision_key
from studio.ai_dialog import AIDialog
from studio.settings import SettingsDialog
from studio.shooting_plan import ShootingPlanWorker
from studio.ui import MainWindow
from test_ai import Response
from test_xhs import saved_images
from test_repairs import wait_until
from conftest import record

VISION='https://dashscope.aliyuncs.com/compatible-mode/v1'
DEEPSEEK='https://api.deepseek.com'

def stream(text='Synthetic reply'):
    return Response(['data: '+json.dumps({'choices':[{'delta':{'content':text}}]}),'data: [DONE]'])

def configured_window(store):
    store.set_setting('model','synthetic-text-model');store.set_setting('vision_model','synthetic-vision-model')
    window=MainWindow(store);window.runtime_key='synthetic-original-key';window.runtime_vision_key='synthetic-vision-key'
    return window

def pipeline(store,ref,**overrides):
    args={'root':store.root,'images':store.reference_images(ref),'context':store.context('DIY散客',reference_id=ref),
        'text':'请按最少补拍整理方案','history':[],
        'vision_connection':{'base':VISION,'key':'synthetic-vision-key','model':'synthetic-vision-model'},
        'text_connection':{'base':DEEPSEEK,'key':'synthetic-original-key','model':'synthetic-text-model'}}
    return ShootingPlanWorker(**(args|overrides))

def finish_dialog(dialog):
    wait_until(lambda:not dialog.worker.isRunning())
    QTest.qWait(20)

def test_one_action_routes_pixels_and_credentials_to_their_own_providers(app,store,tmp_path,monkeypatch):
    ref=saved_images(store,tmp_path,app);record(store,'offers',name='本店真实体验',price='128元')
    calls=[]
    def post(url,**kwargs):
        calls.append((url,kwargs))
        return stream('第1张：绿色植物。第2张：制作过程。' if len(calls)==1 else '先拍成品，再补拍制作动作。')
    monkeypatch.setattr('studio.ai.requests.post',post)
    worker=pipeline(store,ref);outputs=[];events=[];done=[]
    worker.delta.connect(outputs.append);worker.audit.connect(events.append);worker.completed.connect(done.append);worker.run()
    assert done==[True] and outputs==['先拍成品，再补拍制作动作。']
    assert [c[0] for c in calls]==[VISION+'/chat/completions',DEEPSEEK+'/chat/completions']
    assert calls[0][1]['headers']['Authorization']=='Bearer synthetic-vision-key'
    assert calls[1][1]['headers']['Authorization']=='Bearer synthetic-original-key'
    first=json.dumps(calls[0][1]['json'],ensure_ascii=False);second=json.dumps(calls[1][1]['json'],ensure_ascii=False)
    assert first.count('data:image/png;base64,')==2 and '本店真实体验' not in first
    assert 'data:image' not in second and '本店真实体验' in second and '第1张：绿色植物' in second
    assert all(c[1]['allow_redirects'] is False for c in calls)
    assert not any(secret in json.dumps(events) for secret in ('data:image','synthetic-vision-key','synthetic-original-key'))

@pytest.mark.parametrize('failure',['401','timeout','incomplete','truncated','blank'])
def test_vision_failure_never_starts_text_phase(app,store,tmp_path,monkeypatch,failure):
    ref=saved_images(store,tmp_path,app);calls=[]
    def post(url,**kwargs):
        calls.append(url)
        if failure=='timeout':raise requests.exceptions.Timeout()
        if failure=='401':return Response(status=401)
        if failure=='blank':return stream('   ')
        if failure=='truncated':return Response(['data: {"choices":[{"delta":{"content":"partial"},"finish_reason":"length"}]}','data: [DONE]'])
        return Response(['data: {"choices":[{"delta":{"content":"partial"}}]}'])
    monkeypatch.setattr('studio.ai.requests.post',post)
    worker=pipeline(store,ref);done=[];errors=[];observed=[]
    worker.completed.connect(done.append);worker.failed.connect(errors.append);worker.observed.connect(observed.append);worker.run()
    assert done==[False] and len(calls)==1 and errors and not observed

def test_missing_image_blocks_requests_instead_of_silently_omitting_it(app,store,tmp_path,monkeypatch):
    ref=saved_images(store,tmp_path,app);images=store.reference_images(ref);images[1]['path']=None
    monkeypatch.setattr('studio.ai.requests.post',lambda *a,**k:pytest.fail('No provider should be contacted'))
    worker=pipeline(store,ref,images=images);errors=[];worker.failed.connect(errors.append);worker.run()
    assert errors and '第2张' in errors[0]

def test_cancelled_vision_stream_does_not_proceed_to_deepseek(app,store,tmp_path,monkeypatch):
    ref=saved_images(store,tmp_path,app);worker=pipeline(store,ref);calls=[]
    class CancelledResponse(Response):
        def iter_lines(self,**kwargs):
            yield 'data: {"choices":[{"delta":{"content":"partial"}}]}'
            worker.cancel()
            yield 'data: [DONE]'
    def post(url,**kwargs):calls.append(url);return CancelledResponse()
    monkeypatch.setattr('studio.ai.requests.post',post)
    done=[];worker.completed.connect(done.append);worker.run()
    assert done==[False] and len(calls)==1 and worker.observation is None

def test_text_failure_preserves_observations_and_retry_does_not_resend_images(app,store,tmp_path,monkeypatch):
    ref=saved_images(store,tmp_path,app);window=configured_window(store);calls=[]
    def post(url,**kwargs):
        calls.append((url,kwargs))
        return Response(status=402) if len(calls)==2 else stream('Synthetic observations' if len(calls)==1 else 'Synthetic final plan')
    monkeypatch.setattr('studio.ai.requests.post',post);monkeypatch.setattr(QDialog,'exec',lambda self:QDialog.DialogCode.Accepted)
    dialog=AIDialog(window,'看图拍摄方案',store.context('DIY散客',reference_id=ref));dialog.generate();finish_dialog(dialog)
    assert not dialog.ok and dialog.visual_observation and 'Synthetic observations' in dialog.buffer
    assert '402' in dialog.status.text() and '本窗口内不重复识图' in dialog.status.text()
    assert store.rows('ai_runs')[0]['status']=='未完成' and store.latest_reference_plan(ref) is None
    dialog.generate();finish_dialog(dialog)
    assert dialog.ok and [c[0] for c in calls]==[VISION+'/chat/completions',DEEPSEEK+'/chat/completions',DEEPSEEK+'/chat/completions']
    assert store.latest_reference_plan(ref)['output']==dialog.buffer
    assert len(store.rows('ai_runs'))==2 and store.rows('pieces')==[]
    persisted=json.dumps(store.rows('ai_runs'))
    assert not any(secret in persisted for secret in ('data:image','synthetic-vision-key','synthetic-original-key'))
    dialog.copy.click();assert 'Synthetic final plan' in app.clipboard().text()
    dialog.reject();window.force_quit=True;window.close()

def test_followup_reuses_observations_and_passes_user_changes(app,store,tmp_path,monkeypatch):
    ref=saved_images(store,tmp_path,app);window=configured_window(store);calls=[]
    def post(url,**kwargs):calls.append((url,kwargs));return stream('observations' if len(calls)==1 else 'plan')
    monkeypatch.setattr('studio.ai.requests.post',post);monkeypatch.setattr(QDialog,'exec',lambda self:QDialog.DialogCode.Accepted)
    dialog=AIDialog(window,'看图拍摄方案',store.context('DIY散客',reference_id=ref));dialog.generate();finish_dialog(dialog)
    dialog.input.setPlainText('改成只拍3张');dialog.generate();finish_dialog(dialog)
    assert dialog.ok and len(calls)==3
    assert calls[-1][1]['json']['messages'][-1]['content']=='改成只拍3张'
    assert 'data:image' not in json.dumps(calls[-1][1]['json'])
    assert dialog.send.text()=='修改方案'
    dialog.reject();window.force_quit=True;window.close()

def test_encoding_and_requests_run_off_gui_thread(app,store,tmp_path,monkeypatch):
    import studio.shooting_plan as plans
    ref=saved_images(store,tmp_path,app);window=configured_window(store);main_thread=threading.get_ident();threads=[]
    original=plans.encode_images
    def slow_encode(*args):threads.append(threading.get_ident());time.sleep(.3);return original(*args)
    def post(*a,**k):threads.append(threading.get_ident());time.sleep(.15);return stream()
    monkeypatch.setattr(plans,'encode_images',slow_encode);monkeypatch.setattr('studio.ai.requests.post',post)
    monkeypatch.setattr(QDialog,'exec',lambda self:QDialog.DialogCode.Accepted)
    dialog=AIDialog(window,'看图拍摄方案',store.context('DIY散客',reference_id=ref))
    ticks=[];timer=QTimer();timer.setInterval(20);timer.timeout.connect(lambda:ticks.append(1));timer.start()
    dialog.generate();finish_dialog(dialog);timer.stop()
    assert dialog.ok and len(ticks)>=10 and all(t!=main_thread for t in threads)
    dialog.reject();window.force_quit=True;window.close()

def test_cancel_confirmation_does_not_call_or_save(app,store,tmp_path,monkeypatch):
    ref=saved_images(store,tmp_path,app);window=configured_window(store)
    monkeypatch.setattr(QDialog,'exec',lambda self:QDialog.DialogCode.Rejected)
    monkeypatch.setattr('studio.ai.requests.post',lambda *a,**k:pytest.fail('Not authorized to send'))
    dialog=AIDialog(window,'看图拍摄方案',store.context('DIY散客',reference_id=ref));dialog.generate()
    assert dialog.worker is None and not store.rows('ai_runs')
    dialog.reject();window.force_quit=True;window.close()

def test_original_deepseek_key_is_never_sent_to_vision_even_if_pasted_there(app,store,tmp_path,monkeypatch):
    ref=saved_images(store,tmp_path,app);worker=pipeline(store,ref,vision_connection={'base':VISION,'key':'synthetic-original-key','model':'vision'})
    monkeypatch.setattr('studio.ai.requests.post',lambda *a,**k:pytest.fail('Wrong-provider key'))
    errors=[];worker.failed.connect(errors.append);worker.run();assert errors and '不能使用 DeepSeek' in errors[0]
    window=MainWindow(store);dialog=SettingsDialog(window)
    monkeypatch.setattr('studio.settings.api_key',lambda *a,**k:'synthetic-original-key')
    dialog.vision_key.setText('synthetic-original-key');dialog.vision_model.setText('vision');dialog.test_vision()
    assert dialog.vision_worker is None and 'DeepSeek Key' in dialog.vision_status.text()
    dialog.save();assert '对应服务的 Key' in dialog.notice.text()
    dialog.reject();window.force_quit=True;window.close()

def test_changing_vision_provider_does_not_reuse_other_provider_key(app,store,monkeypatch):
    store.set_setting('vision_base',VISION)
    window=MainWindow(store);window.runtime_vision_key='synthetic-qwen-key'
    dialog=SettingsDialog(window);dialog.vision_provider.setCurrentIndex(1);dialog.vision_model.setText('synthetic-openai-vision')
    monkeypatch.setattr('studio.ai.requests.post',lambda *a,**k:pytest.fail('Do not send Qwen credential to OpenAI'))
    dialog.test_vision();assert '新服务商的 Key' in dialog.vision_status.text()
    dialog.save();assert store.setting('vision_base')==VISION
    dialog.vision_key.setText('synthetic-openai-key');dialog.vision_persist.setChecked(False);dialog.save()
    assert store.setting('vision_key_base')==VISION
    window.runtime_vision_key=''
    monkeypatch.setattr('studio.ai.api_key',lambda *a,**k:'synthetic-qwen-key')
    assert configured_vision_key(window)==''
    dialog.reject();window.force_quit=True;window.close()

def test_plan_lookup_stays_with_reference_and_survives_backup(app,store,tmp_path):
    from studio.store import Store
    ref=saved_images(store,tmp_path,app);other=record(store,'references',title='Different reference')
    run=store.start_run('看图拍摄方案','DIY散客',{'context':{'reference':{'id':ref}}});store.update_run(run,'Saved plan','已完成')
    assert store.latest_reference_plan(ref)['id']==run and store.latest_reference_plan(other) is None
    target=Store(tmp_path/'restored-plan')
    try:
        bundle=tmp_path/'plan.zip';store.export_bundle(bundle);target.restore_bundle(bundle)
        assert target.latest_reference_plan(ref)['output']=='Saved plan'
    finally:target.close()

def test_missing_deepseek_configuration_prevents_billable_vision_request(app,store,tmp_path,monkeypatch):
    ref=saved_images(store,tmp_path,app)
    worker=pipeline(store,ref,text_connection={'base':DEEPSEEK,'key':'','model':''})
    monkeypatch.setattr('studio.ai.requests.post',lambda *a,**k:pytest.fail('Configure both steps first'))
    errors=[];worker.failed.connect(errors.append);worker.run()
    assert errors and '原来的 DeepSeek Key' in errors[0]

def test_cancel_between_phases_keeps_completed_observations(app,store,tmp_path,monkeypatch):
    ref=saved_images(store,tmp_path,app);worker=pipeline(store,ref);calls=[];observed=[]
    def post(url,**kwargs):calls.append(url);return stream('Completed observations')
    monkeypatch.setattr('studio.ai.requests.post',post)
    worker.observed.connect(lambda result:(observed.append(result),worker.cancel()))
    done=[];worker.completed.connect(done.append);worker.run()
    assert done==[False] and len(calls)==1 and observed[0]['text']=='Completed observations'

def test_saving_vision_keeps_original_deepseek_credential_untouched(app,store,monkeypatch):
    calls=[];monkeypatch.setattr('studio.settings.save_api_key',lambda value,vision=False:calls.append((value,vision)))
    monkeypatch.setattr('studio.settings.api_key',lambda *a,**k:'synthetic-original-key')
    window=MainWindow(store);dialog=SettingsDialog(window)
    dialog.vision_key.setText('synthetic-vision-key');dialog.vision_model.setText('synthetic-vision-model');dialog.vision_persist.setChecked(True)
    dialog.save()
    assert calls==[('synthetic-vision-key',True)]
    assert store.setting('vision_key_base')==VISION and 'synthetic-vision-key' not in str(list(store.db.execute('SELECT * FROM settings')))
    dialog.reject();window.force_quit=True;window.close()

def test_reference_generate_entry_starts_without_an_extra_generate_click(app,store,tmp_path,monkeypatch):
    from studio.reference_view import ReferenceDialog
    ref=saved_images(store,tmp_path,app);window=MainWindow(store);calls=[]
    def generate(dialog):calls.append(dialog.task);dialog.reject()
    monkeypatch.setattr(AIDialog,'generate',generate)
    reference=ReferenceDialog(window,ref);reference.vision()
    assert calls==['看图拍摄方案']
    reference.reject();window.force_quit=True;window.close()
