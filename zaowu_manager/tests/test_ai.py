import json
import requests
import pytest
from zaowu.ai import AIWorker, endpoint

class Response:
    def __init__(self,lines=(),status=200,data=None):
        self.lines=lines; self.status_code=status; self.data=data
    def __enter__(self): return self
    def __exit__(self,*args): return False
    def iter_lines(self,**kwargs): yield from self.lines
    def json(self): return self.data

def test_endpoint_prevents_credential_redirect():
    assert endpoint('https://api.deepseek.com/v1/')=='https://api.deepseek.com/v1'
    for url in ('http://api.deepseek.com','https://evil.example','https://api.deepseek.com@evil.example','https://api.deepseek.com/path','https://api.deepseek.com?redirect=x'):
        with pytest.raises(ValueError): endpoint(url)

def test_streaming_content_and_done(monkeypatch):
    lines=[': keepalive','data: '+json.dumps({'choices':[{'delta':{'content':'经营建议'}}]},ensure_ascii=False),'data: [DONE]']
    captured={}
    def post(url,**kwargs): captured.update(kwargs); return Response(lines)
    monkeypatch.setattr(requests,'post',post)
    worker=AIWorker('https://api.deepseek.com','secret','returned-model',[{'role':'user','content':'问题'}])
    chunks=[]; done=[]
    worker.delta.connect(chunks.append); worker.completed.connect(done.append)
    worker.run()
    assert chunks==['经营建议'] and done==[True]
    assert captured['json']['stream'] is True and captured['allow_redirects'] is False

@pytest.mark.parametrize('kind',['auth','timeout','truncated','empty'])
def test_api_failure_never_claims_success(monkeypatch,kind):
    def post(*args,**kwargs):
        if kind=='timeout': raise requests.exceptions.Timeout()
        if kind=='auth': return Response(status=401)
        return Response(['data: [DONE]'] if kind=='empty' else ['data: {"choices":[{"delta":{"content":"部分"}}]}'])
    monkeypatch.setattr(requests,'post',post)
    worker=AIWorker('https://api.deepseek.com','secret','model',[])
    errors=[]; done=[]
    worker.failed.connect(errors.append); worker.completed.connect(done.append)
    worker.run()
    assert errors and done==[False] and all('secret' not in e for e in errors)

def test_live_model_discovery_protocol(monkeypatch):
    monkeypatch.setattr(requests,'get',lambda *args,**kwargs:Response(data={'data':[{'id':'model-from-service'}]}))
    worker=AIWorker('https://api.deepseek.com','key')
    models=[]
    worker.models.connect(models.append)
    worker.run()
    assert models==[['model-from-service']]
