"""Offline Chromium check used by source tests and the packaged diagnostics."""
import json
import sys
import time
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QCoreApplication,QEvent,QEventLoop,QTimer,QUrl,Qt

def browser_smoke(root,parent=None):
    if sys.platform=='win32':
        from .system_browser_checks import system_browser_smoke
        return system_browser_smoke(root,parent)
    return qt_browser_smoke(root,parent)

def qt_browser_smoke(root,parent=None):
    from PySide6.QtWebEngineCore import QWebEngineUrlRequestInterceptor
    from .browser_monitor import BrowserMonitor,capture_script
    class OfflineOnly(QWebEngineUrlRequestInterceptor):
        def interceptRequest(self,info):
            if info.requestUrl().scheme() not in ('data','about','blob'):info.block(True)
    browser=BrowserMonitor(root,parent);blocker=OfflineOnly(browser.profile);browser.profile.setUrlRequestInterceptor(blocker)
    browser.manual_account={'id':'offline-check','url':'https://www.douyin.com/user/OFFLINE-OWNER','owner':'OFFLINE-OWNER','name':'offline check','videos':{}}
    browser.page.allow_inline=True;loop=QEventLoop();results=[]
    browser.result.connect(lambda id,value:(results.append(value),loop.quit()))
    timer=QTimer();timer.setSingleShot(True);timer.timeout.connect(loop.quit);timer.start(15000)
    video={'aweme_id':'1234567890123456','author':{'sec_uid':'OFFLINE-OWNER','nickname':'offline check'},'desc':'offline browser check','statistics':{'digg_count':123},'promotions':[{'title':'offline book'}]}
    fixture='''<!doctype html><html><body><p id="status">Offline browser fixture</p><script>
    window.injectedBeforeDocument=!!window.__bookWorkbenchPublic;
    </script></body></html>'''
    phase=['login']
    def loaded(ok):
        if not ok:loop.quit();return
        if phase[0]=='login':QTimer.singleShot(100,browser.read_current);return
        # A mock response verifies the fetch observer in a real renderer. All
        # network is blocked by OfflineOnly; this never contacts Douyin.
        setup='''window.__bookWorkbenchPublic=undefined;
        window.fetch=()=>Promise.resolve(new Response(JSON.stringify(PAYLOAD),{status:200,headers:{"content-type":"application/json"}}));
        '''.replace('PAYLOAD',json.dumps({'aweme_list':[video]}))+capture_script()+''';
        fetch('https://www.douyin.com/aweme/v1/web/aweme/post/').then(()=>setTimeout(()=>document.getElementById('status').textContent='ready',20));'''
        def injected(ready):
            if ready is not True:results.append({'error':'DocumentCreation hook missing'});loop.quit();return
            browser.page.runJavaScript(setup,lambda _:QTimer.singleShot(150,browser.read_current))
        browser.page.runJavaScript('window.injectedBeforeDocument === true',injected)
    browser.view.loadFinished.disconnect(browser.load_finished);browser.view.loadFinished.connect(loaded)
    try:
        browser.show()
        if browser.window.windowModality()!=Qt.WindowModality.NonModal:raise ValueError('Browser must remain nonmodal')
        if parent is not None and not parent.isEnabled():raise ValueError('Browser disabled parent navigation')
        browser.busy=True;browser._deadline=time.monotonic()+5
        browser.view.setHtml('<html><body>扫码登录 · 登录后查看作品</body></html>',QUrl('https://www.douyin.com/user/OFFLINE-OWNER'));loop.exec()
        if not results or results[-1].get('error_code')!='login_required' or browser.busy:raise ValueError('Browser login pause did not release the workbench')
        if QApplication.activeModalWidget():raise ValueError('Browser login unexpectedly blocked navigation')
        results.clear();phase[0]='public';browser.view.setHtml(fixture,QUrl('https://www.douyin.com/user/OFFLINE-OWNER'));loop.exec()
        if not results or results[0].get('error'):raise ValueError('Browser renderer did not read the offline public-post fixture')
        data=results[0]
        if data['videos'][0]['likes']!=123 or data['videos'][0]['products']!=['offline book']:raise ValueError('Browser public-response extraction failed')
        return {'renderer':True,'public_response':True,'login_pause':True,'network':'blocked_offline_fixture'}
    finally:
        timer.stop();browser.shutdown();QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
