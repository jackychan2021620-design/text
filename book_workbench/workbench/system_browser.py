"""Control an isolated, visible Edge/Chrome window over loopback DevTools.
Only the monitor's own profile is used; no normal browser cookies are exported.
"""
import json,os,time
from pathlib import Path
from urllib.parse import urlparse
from PySide6.QtCore import QObject,Signal,QTimer,QProcess,QUrl
from PySide6.QtNetwork import QNetworkAccessManager,QNetworkProxy,QNetworkRequest
from PySide6.QtWebSockets import QWebSocket
from .monitor_session import MonitorSession
from .browser_runtime import capture_script,browser_url


def find_browser():
    candidates=[]
    for base in (os.environ.get('ProgramFiles(x86)'),os.environ.get('ProgramFiles'),os.environ.get('LOCALAPPDATA')):
        if base:
            candidates.extend((Path(base)/'Microsoft/Edge/Application/msedge.exe',Path(base)/'Google/Chrome/Application/chrome.exe'))
    return next((p for p in candidates if p.is_file()),None)

class SystemTransport(QObject):
    loadStarted=Signal();loadFinished=Signal(bool);ready=Signal();failed=Signal(str);userNavigation=Signal();event=Signal(str,object)
    def __init__(self,root,parent=None):
        super().__init__(parent);self.root=Path(root)/'browser'/'system-douyin';self.root.mkdir(parents=True,exist_ok=True)
        self.manager=QNetworkAccessManager(self);self.manager.setProxy(QNetworkProxy(QNetworkProxy.ProxyType.NoProxy)) # loopback only
        self.socket=QWebSocket('http://127.0.0.1',parent=self);self.socket.setProxy(QNetworkProxy(QNetworkProxy.ProxyType.NoProxy))
        self.socket.connected.connect(self.connected);self.socket.textMessageReceived.connect(self.message)
        self.socket.disconnected.connect(self.disconnected);self.socket.errorOccurred.connect(lambda _:self.connection_error())
        self.timer=QTimer(self);self.timer.setInterval(200);self.timer.timeout.connect(self.probe)
        self._pending={};self._serial=0;self._session='';self._target='';self._frame='';self._url=QUrl('about:blank');self._desired=None
        self._ready=False;self._connecting=False;self._closed=False;self._seen_targets=set();self._http_busy=False;self._show=False;self._launched=False;self._pid=0
    def url(self):return self._url
    def load(self,url):
        self._desired=url.toString();self._url=url
        if self._ready:self.navigate()
        else:self.start()
    def start(self):
        if self._connecting or self._ready or self._closed:return
        executable=find_browser()
        if not executable:raise ValueError('未找到 Edge 或 Chrome。请安装其中一个浏览器后重试，工作台其他功能仍可使用。')
        self._connecting=True;self._deadline=time.monotonic()+25;self.timer.start();self.probe()
        # Reuse only an already running monitor profile, if its loopback endpoint is live.
        QTimer.singleShot(500,lambda:self.launch(executable) if self._connecting and not self._launched else None)
    def launch(self,executable):
        self._launched=True
        process=QProcess(self);process.setProgram(str(executable));process.setArguments([
            '--user-data-dir='+str(self.root),'--remote-debugging-port=0','--remote-debugging-address=127.0.0.1',
            '--remote-allow-origins=http://127.0.0.1','--no-first-run','--no-default-browser-check','--new-window','about:blank'])
        ok,pid=process.startDetached();self._pid=pid
        if not ok:self.error('系统浏览器未能启动，请确认 Edge／Chrome 可以正常打开。')
    def probe(self):
        if self._closed or self._http_busy or not self._connecting:return
        if time.monotonic()>self._deadline:self.error('未能连接监测专用浏览器。请关闭这个专用窗口后重试，不必关闭日常浏览器。');return
        path=self.root/'DevToolsActivePort'
        try:
            lines=path.read_text().splitlines();port=int(lines[0]);browser_path=lines[1]
            if not 1<=port<=65535 or not browser_path.startswith('/devtools/browser/'):return
        except (OSError,ValueError,IndexError):return
        self._http_busy=True;request=QNetworkRequest(QUrl(f'http://127.0.0.1:{port}/json/version'));request.setTransferTimeout(1500);reply=self.manager.get(request)
        def finished():
            self._http_busy=False
            if self._closed:reply.deleteLater();return
            try:
                info=json.loads(bytes(reply.readAll()));url=info.get('webSocketDebuggerUrl','');parsed=urlparse(url)
                if parsed.scheme!='ws' or parsed.hostname not in ('127.0.0.1','localhost') or parsed.port!=port or parsed.path!=browser_path:return
                self.timer.stop();self.socket.open(QUrl(url))
            except (ValueError,TypeError):pass
            finally:reply.deleteLater()
        reply.finished.connect(finished)
    def connected(self):
        self.command('Target.getTargets',{},self.targets,browser=True)
    def targets(self,result):
        pages=[t for t in (result or {}).get('targetInfos',[]) if t.get('type')=='page' and (t.get('url')=='about:blank' or browser_url(t.get('url','')))]
        self._seen_targets.update(p['targetId'] for p in pages);self.command('Target.setDiscoverTargets',{'discover':True},browser=True)
        if pages:self.attach(pages[0]['targetId'])
        else:self.command('Target.createTarget',{'url':'about:blank'},lambda r:self.attach(r['targetId']) if r else self.error('无法创建监测页面'),browser=True)
    def attach(self,target):
        self._target=target;self._seen_targets.add(target);self.command('Target.attachToTarget',{'targetId':target,'flatten':True},self.attached,browser=True)
    def attached(self,result):
        if not result or not result.get('sessionId'):self.error('无法连接监测标签页');return
        self._session=result['sessionId'];self.command('Page.enable',{});self.command('Runtime.enable',{})
        self.command('Page.addScriptToEvaluateOnNewDocument',{'source':capture_script()},self.initialized)
    def initialized(self,result):
        if result is None:self.error('浏览器读取脚本未能初始化');return
        self._ready=True;self._connecting=False;self._launched=False;self.ready.emit()
        if self._desired:self.navigate()
        if self._show:self.show()
    def navigate(self):
        url=self._desired;self._desired=None
        if not url:return
        self.loadStarted.emit();self.command('Page.navigate',{'url':url},lambda r:self.loadFinished.emit(False) if not r or r.get('errorText') else None)
    def command(self,method,params=None,callback=None,browser=False):
        if self._closed or not self.socket.isValid():
            if callback:QTimer.singleShot(0,lambda:callback(None))
            return
        self._serial+=1;id=self._serial;message={'id':id,'method':method,'params':params or {}}
        if not browser and self._session:message['sessionId']=self._session
        if callback:
            timeout=QTimer(self);timeout.setSingleShot(True);timeout.setInterval(10000)
            def expired():
                item=self._pending.pop(id,None)
                if item:item[1].deleteLater();item[0](None)
            timeout.timeout.connect(expired);self._pending[id]=(callback,timeout);timeout.start()
        self.socket.sendTextMessage(json.dumps(message))
    def message(self,text):
        try:message=json.loads(text)
        except ValueError:return
        if 'id' in message:
            item=self._pending.pop(message['id'],None)
            if item:item[1].stop();item[1].deleteLater();item[0](None if message.get('error') else message.get('result',{}))
            return
        method=message.get('method');params=message.get('params',{})
        if (method=='Target.targetDestroyed' and params.get('targetId')==self._target) or (method=='Target.detachedFromTarget' and params.get('sessionId')==self._session):
            self._session='';self._target='';self._ready=False;self.socket.close();self.error('监测标签页已关闭，重新打开浏览器即可恢复，已有数据保留。');return
        if message.get('method') in ('Target.targetCreated','Target.targetInfoChanged'):
            info=message.get('params',{}).get('targetInfo',{});target=info.get('targetId');url=info.get('url','')
            if target and target!=self._target and target not in self._seen_targets and info.get('type')=='page' and browser_url(url):
                self._seen_targets.add(target);self.userNavigation.emit();self._desired=url;self._ready=False;self.attach(target)
            return
        if message.get('sessionId')!=self._session:return
        method=message.get('method');params=message.get('params',{});self.event.emit(method or '',params)
        if method=='Page.frameNavigated' and not params.get('frame',{}).get('parentId'):
            self._frame=params['frame']['id'];self._url=QUrl(params['frame']['url']);self.loadStarted.emit()
        elif method=='Page.loadEventFired':self.loadFinished.emit(True)
        elif method=='Page.frameRequestedNavigation' and params.get('reason') in ('anchorClick','formSubmissionGet','formSubmissionPost'):self.userNavigation.emit()
    def evaluate(self,script,callback):
        self.command('Runtime.evaluate',{'expression':script,'returnByValue':True,'awaitPromise':True},lambda result:callback((result or {}).get('result',{}).get('value')))
    def stop(self):
        self._desired=None
        if self._ready:self.command('Page.stopLoading',{})
    def show(self):
        self._show=True
        if self._ready:
            self._show=False
            self.command('Page.bringToFront',{});self.command('Browser.getWindowForTarget',{'targetId':self._target},self.restore_window,browser=True)
        else:self.start()
    def restore_window(self,result):
        if result:self.command('Browser.setWindowBounds',{'windowId':result['windowId'],'bounds':{'windowState':'normal'}},browser=True)
    def disconnected(self):
        self._ready=False
        if not self._closed:self.error('监测浏览器已关闭。点击“打开浏览器并登录”即可重新连接，已读取数据保留。')
    def connection_error(self):
        if self._ready and not self._closed:self.error('与监测浏览器的连接已中断，请重新打开浏览器。')
        elif self._connecting and not self._closed:self.timer.start()
    def error(self,text):
        self.timer.stop();self._connecting=False;self._ready=False;self._launched=False
        if not self._closed:self.failed.emit(text)
    def shutdown(self):
        if self._closed:return
        self._closed=True;self.timer.stop()
        for _,timer in self._pending.values():timer.stop();timer.deleteLater()
        self._pending.clear();self.socket.close()

class SystemBrowserMonitor(MonitorSession):
    def __init__(self,root,parent=None):
        super().__init__(parent);self.transport=SystemTransport(root,self)
        self.transport.loadStarted.connect(self.load_started);self.transport.loadFinished.connect(self.load_finished)
        self.transport.userNavigation.connect(lambda:self.cancel(stop_loading=False))
        self.transport.failed.connect(lambda text:self.fail('system_browser',text,pause=True))
    def set_message(self,message):super().set_message(message)
