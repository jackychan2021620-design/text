import json
import pytest
import requests
from studio.ai import AIWorker,endpoint
from studio.ai_dialog import parse_draft,parse_plan

class Response:
    def __init__(self,lines=(),status=200,data=None):self.lines=lines;self.status_code=status;self.data=data
    def __enter__(self):return self
    def __exit__(self,*args):return False
    def iter_lines(self,**kwargs):yield from self.lines
    def json(self):return self.data

def test_stream_and_dynamic_models(monkeypatch):
    monkeypatch.setattr(requests,'get',lambda *a,**k:Response(data={'data':[{'id':'from-service'}]}))
    worker=AIWorker('https://api.deepseek.com','test-key');models=[];worker.models.connect(models.append);worker.run();assert models==[['from-service']]
    captured=[]
    def post(*a,**kwargs):captured.append(kwargs);return Response(['data: {"choices":[{"delta":{"content":"真实草稿"}}]}','data: [DONE]'])
    monkeypatch.setattr(requests,'post',post)
    worker=AIWorker('https://api.deepseek.com','test-key','from-service',[]);chunks=[];finished=[]
    worker.delta.connect(chunks.append);worker.completed.connect(finished.append);worker.run()
    assert chunks==['真实草稿'] and finished==[True]
    assert captured[0]['allow_redirects'] is False

@pytest.mark.parametrize('failure',['401','timeout','incomplete','empty','cancel'])
def test_failures_mark_incomplete_and_redact_key(monkeypatch,failure):
    def post(*a,**kwargs):
        if failure=='timeout':raise requests.exceptions.Timeout()
        if failure=='401':return Response(status=401)
        return Response(['data: [DONE]'] if failure=='empty' else ['data: {"choices":[{"delta":{"content":"partial"}}]}'])
    monkeypatch.setattr(requests,'post',post)
    worker=AIWorker('https://api.deepseek.com','never-display-this','model',[])
    if failure=='cancel':worker.cancel()
    errors=[];finished=[];worker.failed.connect(errors.append);worker.completed.connect(finished.append);worker.run()
    assert errors and finished==[False] and 'never-display-this' not in str(errors)

def test_no_key_and_official_host_boundary():
    with pytest.raises(ValueError):endpoint('https://api.deepseek.com@evil.example')
    with pytest.raises(ValueError):endpoint('http://api.deepseek.com')
    worker=AIWorker('https://api.deepseek.com','');errors=[];worker.failed.connect(errors.append);worker.run();assert errors

def test_generated_structures_only_allow_expected_fields():
    draft={k:'草稿' for k in ('title','cover','body','script','cta')};draft['sql']='not allowed'
    assert 'sql' not in parse_draft('```json\n'+json.dumps(draft)+'\n```')
    with pytest.raises(ValueError):parse_draft('{"title":"incomplete"}')
    item={k:'test' for k in ('topic','audience','hypothesis','angle','missing','platform','plan_date')}
    assert len(parse_plan(json.dumps({'items':[item]})))==1
    with pytest.raises(ValueError):parse_plan(json.dumps({'items':[item]*5}))
    with pytest.raises(ValueError):parse_plan(json.dumps({'items':[item|{'offer_id':'not an id'}]}))
