"""Normal local browser sessions for dynamic Douyin pages; no login automation."""
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlparse
from PySide6.QtCore import QObject,Signal,QTimer,QUrl,Qt,QCoreApplication
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout
from PySide6.QtWebEngineCore import QWebEnginePage,QWebEngineProfile,QWebEngineScript
from PySide6.QtWebEngineWidgets import QWebEngineView
from .experience import FeedbackButton,selectable,configure_controls
from .monitoring import parse_documents,public_url,identity

if not QCoreApplication.instance():QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)

SNAPSHOT="JSON.stringify(window.__bookWorkbenchPublic ? window.__bookWorkbenchPublic.snapshot() : {url:location.href,documents:[],ready:document.readyState})"

def capture_script():
    root=Path(sys._MEIPASS) if getattr(sys,'frozen',False) else Path(__file__).resolve().parents[1]
    return (root/'resources'/'douyin-public-capture.js').read_text(encoding='utf-8')

def browser_url(url):
    u=urlparse(url)
    return u.scheme=='https' and (u.hostname=='douyin.com' or (u.hostname or '').endswith('.douyin.com') or u.hostname=='www.iesdouyin.com') and not u.username and not u.password

class PublicPage(QWebEnginePage):
    notice=Signal(str)
    user_navigation=Signal()
    def __init__(self,profile,parent=None):super().__init__(profile,parent);self.allow_inline=False
    def acceptNavigationRequest(self,url,kind,main_frame):
        if not main_frame:return True
        if browser_url(url.toString()) or url.toString()=='about:blank' or (self.allow_inline and url.scheme()=='data'):
            if kind==QWebEnginePage.NavigationType.NavigationTypeLinkClicked:self.user_navigation.emit()
            return True
        self.notice.emit('请留在抖音官方网页中查看账号和作品。');return False

class BrowserWindow(QWidget):
    def __init__(self,owner,parent=None):
        super().__init__(parent,Qt.WindowType.Window);self.owner=owner;self.setWindowModality(Qt.WindowModality.NonModal)
        self.setWindowTitle('抖音浏览器 · 登录与读取作品');self.resize(1100,800)
        layout=QVBoxLayout(self);layout.setContentsMargins(12,12,12,12)
        self.notice=selectable('在此正常登录抖音。登录、验证码由你在网页中完成；工作台只读取该账号已公开的作品、赞数与挂车商品。');layout.addWidget(self.notice)
        row=QHBoxLayout()
        for title,fn in [('返回账号主页',owner.go_home),('读取当前页面',owner.read_current),('停止本轮检查',owner.cancel)]:
            b=FeedbackButton(title);b.clicked.connect(fn);row.addWidget(b)
        row.addStretch();layout.addLayout(row)
        self.view=QWebEngineView(self);layout.addWidget(self.view,1);configure_controls(self)
    def closeEvent(self,event):self.owner.interactive=False;event.accept()

class BrowserMonitor(QObject):
    result=Signal(str,object)
    changed=Signal()
    def __init__(self,root,parent=None):
        super().__init__(parent);self.busy=False;self.interactive=False;self._closed=False;self._generation=0;self._reading=False;self._advancing=False;self._queue=[];self._task=None;self.manual_account=None;self.message='浏览器尚未连接'
        folder=Path(root)/'browser'/'douyin';folder.mkdir(parents=True,exist_ok=True)
        self.profile=QWebEngineProfile('BookWorkbenchDouyin',self);self.profile.setPersistentStoragePath(str(folder/'profile'));self.profile.setCachePath(str(folder/'cache'));self.profile.setHttpCacheMaximumSize(64*1024**2)
        self.profile.setPersistentCookiesPolicy(QWebEngineProfile.PersistentCookiesPolicy.AllowPersistentCookies)
        self.window=BrowserWindow(self,parent if isinstance(parent,QWidget) else None);self.view=self.window.view
        self.page=PublicPage(self.profile,self.view);self.view.setPage(self.page);self.page.notice.connect(self.set_message);self.page.user_navigation.connect(lambda:self.cancel(stop_loading=False))
        script=QWebEngineScript();script.setName('BookWorkbenchPublicPosts');script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation);script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld);script.setRunsOnSubFrames(False);script.setSourceCode(capture_script());self.page.scripts().insert(script)
        self.page.newWindowRequested.connect(self.new_window)
        self.view.loadStarted.connect(self.load_started);self.view.loadFinished.connect(self.load_finished)
        self.page.renderProcessTerminated.connect(lambda *args:self.fail('browser_crashed','浏览器进程已结束，请重新打开浏览器后重试。'))
        self.poll=QTimer(self);self.poll.setInterval(1500);self.poll.timeout.connect(self.read_current)
    def set_message(self,message):self.message=message;self.window.notice.setText(message);self.changed.emit()
    def new_window(self,request):
        if browser_url(request.requestedUrl().toString()):self.cancel(stop_loading=False);request.openIn(self.page)
    def show(self):self.window.show();self.window.raise_();self.window.activateWindow()
    def open_account(self,account,url=None):
        self.cancel();self.manual_account=dict(account);self.view.load(QUrl(public_url(url or account.get('resolved_url') or account['url'])));self.show()
    def go_home(self):
        if self.manual_account:self.cancel();self.view.load(QUrl(public_url(self.manual_account.get('resolved_url') or self.manual_account['url'])))
    def start(self,accounts,interactive=True):
        if self.busy or self._closed:return
        self.interactive=interactive;self._queue=[(dict(a),a.get('resolved_url') or a['url'],None) for a in accounts];self.busy=True;self.changed.emit();self.next_task()
    def next_task(self):
        self._advancing=False
        if not self.busy:return
        if not self._queue:
            self.busy=False;self._task=None;self.poll.stop();self.changed.emit();return
        account,url,video_id=self._queue.pop(0);self._task=(account,url,video_id);self.manual_account=account;self._deadline=time.monotonic()+35;self._last_parse_error=''
        self.set_message('正在浏览器中加载 '+account['name']+'，已有数据会保留。');self.view.load(QUrl(public_url(url)));self.poll.start()
    def load_started(self):self._generation+=1;self._reading=False
    def load_finished(self,ok):
        if self._closed:return
        if not ok:
            if self.busy:self.fail('network','网页加载失败，请在浏览器中确认是否能正常打开抖音；已有数据保留。')
            else:self.set_message('网页未能加载，可重新打开账号主页。')
        else:
            if self.manual_account and not self.manual_account.get('resolved_owner'):
                self.manual_account['resolved_owner']=identity(self.view.url().toString())
            QTimer.singleShot(500,self.read_current)
    def read_current(self):
        if self._closed or self._reading or self._advancing or not self.manual_account:return
        generation=self._generation;self._reading=True
        self.page.runJavaScript(SNAPSHOT,lambda value:self.snapshot_ready(generation,value))
    def snapshot_ready(self,generation,value):
        if self._closed or generation!=self._generation:return
        self._reading=False
        try:
            if not isinstance(value,str) or len(value)>6*1024**2:raise ValueError('页面数据尚未准备好')
            snapshot=json.loads(value);url=snapshot.get('url','');account=self.manual_account
            if not browser_url(url):raise ValueError('请先打开抖音账号主页')
            data=parse_documents(snapshot.get('documents',[]),url,account.get('owner') or account.get('resolved_owner',''))
            data['source']='本机浏览器公开页面';data['coverage']='仅已加载的公开作品；可在浏览器滚动加载更多，再读取当前页面'
            task=self._task
            if task and task[2]:data['videos']=[v for v in data['videos'] if v['id']==task[2]]
            if not data['videos']:raise ValueError('当前作品数据尚未显示')
            self.result.emit(account['id'],data);account['owner']=data['owner'];self.set_message('已读取 '+str(account['name'])+' 的 '+str(len(data['videos']))+' 条公开作品。可向下滚动加载更多，再点击“读取当前页面”。')
            if self.busy:
                if task and not task[2]:
                    seen={v['id'] for v in data['videos']}
                    old=sorted((v for v in account['videos'].values() if v['likes']<100 and v['id'] not in seen),key=lambda v:v.get('checked',''))[:3]
                    extra=[(account,v['url'],v['id']) for v in old]
                    if re.search(r'/(?:share/)?video/',urlparse(url).path) and data.get('profile_url') and task[1]!=data['profile_url']:extra.insert(0,(account,data['profile_url'],None))
                    self._queue=extra+self._queue
                self.poll.stop();self._task=None;self.advance()
        except (ValueError,TypeError,KeyError) as exc:
            blocker=snapshot.get('blocker','') if isinstance(locals().get('snapshot'),dict) else ''
            if blocker in ('login_required','verification_required'):
                self.fail(blocker,'请在浏览器内完成'+('安全验证' if blocker=='verification_required' else '登录')+'，随后点击“读取当前页面”。',pause=True)
            elif self.busy and time.monotonic()>=self._deadline:self.fail('page_not_ready','网页已打开，但未读取到该账号作品的明确赞数。请登录或滚动加载作品后，再读取当前页面。',pause=True)
            elif not self.busy:self.set_message('尚未读取到带明确赞数的作品。请确认登录并滚动加载后重试；书名缺失会标待确认。')
    def fail(self,code,message,pause=False):
        if self._closed:return
        account=self.manual_account
        if account:self.result.emit(account['id'],{'error':message,'error_code':code})
        self.poll.stop();self.set_message(message)
        if pause:
            self._queue=[];self._task=None;self.busy=False
            if self.interactive:self.show()
            self.changed.emit()
        elif self.busy:self.advance()
    def advance(self):
        self._advancing=True;generation=self._generation
        QTimer.singleShot(0,lambda:self.next_task() if not self._closed and generation==self._generation and self.busy else None)
    def cancel(self,stop_loading=True):
        if self._closed:return
        self._generation+=1;self._reading=False;self._advancing=False;self._queue=[];self._task=None;self.busy=False;self.poll.stop()
        if stop_loading:self.view.stop()
        self.changed.emit()
    def shutdown(self):
        if self._closed:return
        self.cancel();self._closed=True;self.window.hide();self.page.deleteLater();self.window.deleteLater();self.profile.deleteLater()
