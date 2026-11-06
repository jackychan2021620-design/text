"""Shared collection queue for the system browser and optional Qt backend."""
import json,re,time
from datetime import datetime,timezone,timedelta
from urllib.parse import urlparse
from PySide6.QtCore import QObject,Signal,QTimer,QUrl
from .browser_runtime import SNAPSHOT,browser_url
from .monitoring import parse_documents,public_url,identity,is_hot

class MonitorSession(QObject):
    result=Signal(str,object)
    changed=Signal()
    def __init__(self,parent=None):
        super().__init__(parent)
        self.busy=False;self.interactive=False;self._closed=False;self._generation=0;self._reading=False;self._advancing=False;self._queue=[];self._task=None;self.manual_account=None;self.message='浏览器尚未连接'
        self.poll=QTimer(self);self.poll.setInterval(1500);self.poll.timeout.connect(self.read_current)
    def set_message(self,message):self.message=message;self.changed.emit()
    def new_window(self,request):
        if browser_url(request.requestedUrl().toString()):self.cancel(stop_loading=False);request.openIn(self.page)
    def show(self):self.transport.show()
    def account_copy(self,account):
        value=dict(account)
        if value.get('identity_version')!='target-v2':value['_old_owner']=value.get('owner');value['owner']='';value.pop('resolved_owner',None);value.pop('resolved_url',None)
        return value
    def open_account(self,account,url=None):
        self.cancel();self.manual_account=self.account_copy(account);self.transport.load(QUrl(public_url(url or self.manual_account.get('resolved_url') or account['url'])));self.show()
    def go_home(self):
        if self.manual_account:self.cancel();self.transport.load(QUrl(public_url(self.manual_account.get('resolved_url') or self.manual_account['url'])))
    def start(self,accounts,interactive=True):
        if self.busy or self._closed:return
        self.interactive=interactive;self._queue=[(self.account_copy(a),(a.get('resolved_url') if a.get('identity_version')=='target-v2' else None) or a['url'],None) for a in accounts];self.busy=True;self.changed.emit();self.next_task()
    def next_task(self):
        self._advancing=False
        if not self.busy:return
        if not self._queue:
            self.busy=False;self._task=None;self.poll.stop();self.changed.emit();return
        account,url,video_id=self._queue.pop(0);self._task=(account,url,video_id);self.manual_account=account;self._deadline=time.monotonic()+40;self._rounds=0;self._stable=0;self._profile_count=-1;self._detail_rounds=0
        self.set_message('正在浏览器中加载 '+account['name']+'，已有数据会保留。');self.transport.load(QUrl(public_url(url)));self.poll.start()
    def load_started(self):self._generation+=1;self._reading=False
    def load_finished(self,ok):
        if self._closed:return
        if not ok:
            if self.busy:self.fail('network','网页加载失败，请在浏览器中确认是否能正常打开抖音；已有数据保留。')
            else:self.set_message('网页未能加载，可重新打开账号主页。')
        else:
            if self.manual_account and not self.manual_account.get('resolved_owner'):
                self.manual_account['resolved_owner']=identity(self.transport.url().toString())
            generation=self._generation
            QTimer.singleShot(500,lambda:self.read_current() if generation==self._generation and not self._closed else None)
    def read_current(self):
        if self._closed or self._reading or self._advancing or not self.manual_account:return
        generation=self._generation;self._reading=True
        self.transport.evaluate(SNAPSHOT,lambda value:self.snapshot_ready(generation,value))
    def snapshot_ready(self,generation,value):
        if self._closed or generation!=self._generation:return
        self._reading=False
        try:
            if not isinstance(value,str) or len(value)>6*1024**2:raise ValueError('页面数据尚未准备好')
            snapshot=json.loads(value);url=snapshot.get('url','');account=self.manual_account
            if not browser_url(url):raise ValueError('请先打开抖音账号主页')
            data=parse_documents(snapshot.get('documents',[]),url,account.get('owner') or account.get('resolved_owner',''),partial=True)
            data['identity_verified']=True
            if account.get('_old_owner') and account['_old_owner'] not in data.get('owner_aliases',[]):account['videos']={}
            data['source']='本机浏览器公开页面';data['coverage']='仅已加载的公开作品；读取过程会继续加载后续批次，不把置顶旧视频视为最新作品边界'
            task=self._task
            if task and task[2]:data['videos']=[v for v in data['videos'] if v['id']==task[2]]
            if not data['videos']:raise ValueError('当前作品数据尚未显示')
            if task and task[2]:data['source_kind']='detail'
            self.result.emit(account['id'],data);account['owner']=data['owner'];account['identity_version']='target-v2';self.set_message('已读取 '+str(account['name'])+' 的 '+str(len(data['videos']))+' 条公开作品。可向下滚动加载更多，再点击“读取当前页面”。')
            if self.busy:
                if task and task[2] and not data['videos'][0].get('products') and self._detail_rounds<3 and time.monotonic()<self._deadline-2:
                    self._detail_rounds+=1;self.set_message('正在等候视频详情的挂车信息；未显示时会保留文案书名线索。');return
                if task and not task[2]:
                    count=len(data['videos']);self._stable=self._stable+1 if count==self._profile_count else 0;self._profile_count=count
                    if self._rounds<4 and time.monotonic()<self._deadline-2 and (snapshot.get('hasMore') is not False or self._stable<1):
                        self._rounds+=1;self.set_message(f"已读取{count}条，正在加载后续作品（{self._rounds}/4），旧置顶作品不会阻止读取近期视频。")
                        self.transport.evaluate('window.__bookWorkbenchPublic && window.__bookWorkbenchPublic.loadMore()',lambda _:None);return
                    seen={v['id'] for v in data['videos']};cached=account['videos'];now=datetime.now(timezone.utc)
                    def needs_detail(v):
                        old=cached.get(v['id'],{})
                        if not is_hot(v) or v.get('products') or old.get('products'):return False
                        try:return now-datetime.fromisoformat(old.get('details_checked',''))>timedelta(days=1)
                        except ValueError:return True
                    hot=sorted((v for v in data['videos'] if needs_detail(v)),key=lambda v:v.get('published',''),reverse=True)[:3]
                    old=sorted((v for v in cached.values() if not is_hot(v) and v['id'] not in seen),key=lambda v:v.get('checked',''))[:3]
                    extra=[(account,v['url'],v['id']) for v in hot+old]
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
    def inspect_video(self,account,video):
        if self.busy:self.cancel()
        self.interactive=True;self.busy=True;self._queue=[(dict(account),video['url'],video['id'])];self.changed.emit();self.next_task();self.show()
    def collect_current(self):
        if self.busy or not self.manual_account:return
        self.busy=True;self._task=(self.manual_account,self.transport.url().toString(),None);self._queue=[];self._deadline=time.monotonic()+35;self._rounds=0;self._stable=0;self._profile_count=-1;self._detail_rounds=0
        self.poll.start();self.read_current();self.changed.emit()
    def advance(self):
        self._advancing=True;generation=self._generation
        QTimer.singleShot(0,lambda:self.next_task() if not self._closed and generation==self._generation and self.busy else None)
    def cancel(self,stop_loading=True):
        if self._closed:return
        self._generation+=1;self._reading=False;self._advancing=False;self._queue=[];self._task=None;self.busy=False;self.poll.stop()
        if stop_loading:self.transport.stop()
        self.changed.emit()
    def shutdown(self):
        if self._closed:return
        self.cancel();self._closed=True;self.transport.shutdown()
