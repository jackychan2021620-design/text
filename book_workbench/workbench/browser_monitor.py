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

from .browser_runtime import SNAPSHOT,capture_script,browser_url
from .monitor_session import MonitorSession

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

class QtTransport:
    def __init__(self,owner):self.owner=owner
    def load(self,url):self.owner.view.load(url)
    def url(self):return self.owner.view.url()
    def stop(self):self.owner.view.stop()
    def evaluate(self,script,callback):self.owner.page.runJavaScript(script,callback)
    def show(self):self.owner.window.show();self.owner.window.raise_();self.owner.window.activateWindow()
    def shutdown(self):
        o=self.owner;o.window.hide();o.page.deleteLater();o.window.deleteLater();o.profile.deleteLater()

class BrowserMonitor(MonitorSession):
    def __init__(self,root,parent=None):
        super().__init__(parent)
        folder=Path(root)/'browser'/'douyin';folder.mkdir(parents=True,exist_ok=True)
        self.profile=QWebEngineProfile('BookWorkbenchDouyin',self);self.profile.setPersistentStoragePath(str(folder/'profile'));self.profile.setCachePath(str(folder/'cache'));self.profile.setHttpCacheMaximumSize(64*1024**2)
        self.profile.setPersistentCookiesPolicy(QWebEngineProfile.PersistentCookiesPolicy.AllowPersistentCookies)
        self.window=BrowserWindow(self,parent if isinstance(parent,QWidget) else None);self.view=self.window.view
        self.page=PublicPage(self.profile,self.view);self.view.setPage(self.page);self.page.notice.connect(self.set_message);self.page.user_navigation.connect(lambda:self.cancel(stop_loading=False))
        script=QWebEngineScript();script.setName('BookWorkbenchPublicPosts');script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation);script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld);script.setRunsOnSubFrames(False);script.setSourceCode(capture_script());self.page.scripts().insert(script)
        self.page.newWindowRequested.connect(self.new_window)
        self.view.loadStarted.connect(self.load_started);self.view.loadFinished.connect(self.load_finished)
        self.page.renderProcessTerminated.connect(lambda *args:self.fail('browser_crashed','浏览器进程已结束，请重新打开浏览器后重试。'))
        self.transport=QtTransport(self);self.changed.connect(lambda:self.window.notice.setText(self.message) if not self._closed else None)
