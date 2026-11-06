"""Visible, clickable browser verification using only intercepted offline data."""
import base64,json,time
from PySide6.QtCore import QEventLoop,QTimer,QUrl
from PySide6.QtGui import QImage
from .system_browser import SystemBrowserMonitor,find_browser
from .browser_runtime import capture_script


def system_browser_smoke(root,parent=None):
    if not find_browser():raise ValueError('Windows browser validation requires installed Edge or Chrome')
    session=SystemBrowserMonitor(root,parent);t=session.transport;loop=QEventLoop();errors=[];passed={};phase=['page']
    account={'id':'offline-browser','url':'https://www.douyin.com/user/OFFLINE-OWNER','owner':'OFFLINE-OWNER','name':'offline browser','videos':{}}
    session.manual_account=account
    timer=QTimer();timer.setSingleShot(True);timer.setInterval(35000);timer.timeout.connect(loop.quit)
    def fail(text):errors.append(text);loop.quit()
    fixture='''<!doctype html><html><head><style>body{margin:0;background:#f5f7ff}button{position:absolute;left:20px;top:20px;width:160px;height:80px;background:#22aa55;border:0}#blue{position:absolute;left:240px;top:20px;width:160px;height:80px;background:#2266dd}</style></head><body><button onclick="window.clicked=(window.clicked||0)+1;fetch('https://www.douyin.com/aweme/v1/web/aweme/post/')">Click check</button><div id="blue"></div><script>window.createdHook=!!window.__bookWorkbenchPublic;</script></body></html>'''
    def paused(method,params):
        if method!='Fetch.requestPaused':return
        url=params.get('request',{}).get('url','')
        body=fixture if url==account['url'] else 'offline fixture: external request blocked'
        t.command('Fetch.fulfillRequest',{'requestId':params['requestId'],'responseCode':200 if url==account['url'] else 403,'responseHeaders':[{'name':'Content-Type','value':'text/html; charset=utf-8'}],'body':base64.b64encode(body.encode()).decode()})
    t.event.connect(paused)
    def ready():
        t.command('Emulation.setDeviceMetricsOverride',{'width':800,'height':600,'deviceScaleFactor':1,'mobile':False})
        t.command('Fetch.enable',{'patterns':[{'urlPattern':'*','requestStage':'Request'}]},lambda _:t.load(QUrl(account['url'])))
    t.ready.connect(ready)
    video={'aweme_id':'1234567890123456','author':{'sec_uid':'OFFLINE-OWNER'},'desc':'《offline book》','statistics':{'digg_count':123},'create_time':'1793836800000','product_info':{'product_title':'offline book'}}
    def loaded(ok):
        if not ok or t.url().toString()!=account['url'] or phase[0]!='page':return
        phase[0]='capture'
        old=video|{'aweme_id':'1234567890123455','create_time':1793318400,'is_top':True}
        setup="window.fetch=()=>Promise.resolve(new Response(JSON.stringify(window.clicked?"+json.dumps({'aweme_list':[video]})+":"+json.dumps({'aweme_list':[old]})+"),{status:200}));window.__bookWorkbenchPublic=undefined;"+capture_script()+";fetch('https://www.douyin.com/aweme/v1/web/aweme/post/');new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(()=>r(true))))"
        def injection_ok(value):
            if value is not True:fail('DocumentCreation capture hook was not installed before the page');return
            t.evaluate(setup,lambda _:QTimer.singleShot(200,lambda:t.command('Page.captureScreenshot',{'format':'png'},screenshot)))
        t.evaluate('window.createdHook === true',injection_ok)
    t.loadFinished.disconnect(session.load_finished);t.loadFinished.connect(loaded)
    def screenshot(result):
        try:
            image=QImage.fromData(base64.b64decode(result['data']));green=image.pixelColor(40,40);blue=image.pixelColor(260,40)
            if image.isNull() or not (green.green()>120 and green.red()<70 and blue.blue()>150 and blue.red()<70):fail('Browser pixels are blank/black or not the expected page');return
            passed['pixels']=True
        except (KeyError,TypeError,ValueError) as exc:fail('Browser screenshot failed: '+str(exc));return
        t.command('Input.dispatchMouseEvent',{'type':'mousePressed','x':50,'y':50,'button':'left','buttons':1,'clickCount':1},lambda _:t.command('Input.dispatchMouseEvent',{'type':'mouseReleased','x':50,'y':50,'button':'left','buttons':0,'clickCount':1},lambda _:QTimer.singleShot(100,clicked)))
    def clicked():
        t.evaluate('window.clicked === 1',lambda value:finish_click(value))
    def finish_click(value):
        if value is not True:fail('Browser page did not respond to a real click');return
        passed['click']=True;session.read_current()
    def result(id,value):
        if phase[0]=='capture':
            latest=next((v for v in value.get('videos',[]) if v['id']==video['aweme_id']),None)
            if not latest or latest['likes']!=123 or latest['products']!=['offline book'] or not latest['published'].startswith('2026-11'):fail('System browser did not extract public-response data');return
            passed['public_response']=True;passed['recent_posts']=True;phase[0]='login';session.busy=True;session._deadline=time.monotonic()+5
            code="document.body.innerHTML='<p>登录后查看作品，请先登录</p>';window.__bookWorkbenchPublic=undefined;"+capture_script()
            t.evaluate(code,lambda _:session.read_current())
        elif phase[0]=='login' and value.get('error_code')=='login_required':
            QTimer.singleShot(0,loop.quit);passed['login_pause']=True
    session.result.connect(result);t.failed.connect(fail)
    try:
        timer.start();t.start();loop.exec()
        if errors:raise ValueError('; '.join(errors)+'; '+t.socket.errorString())
        if not all(passed.get(k) for k in ('pixels','click','public_response','login_pause')):raise ValueError('System browser visual check timed out: '+str(passed))
        if session.busy:raise ValueError('Login prompt did not release the monitor queue')
        return {'renderer':True,**passed,'system_browser':True,'network':'offline_intercepted_fixture'}
    finally:
        timer.stop()
        closing=QEventLoop();wait=QTimer();wait.setSingleShot(True);wait.setInterval(3000);wait.timeout.connect(closing.quit);t.socket.disconnected.connect(closing.quit);wait.start();t.command('Browser.close',{},browser=True)
        if t.socket.isValid():closing.exec()
        wait.stop();session.shutdown()
