"""UI for public account checks. Keeps cached data visible during network work."""
from PySide6.QtCore import QObject,Signal,QTimer,Qt,QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QLineEdit,QCheckBox,QComboBox,QTableWidgetItem,QLabel,QSystemTrayIcon
from .experience import FeedbackButton,DataTable,selectable,toast,confirm
from .monitoring import MonitorStore,MonitorWorker,THRESHOLD,is_hot
import sys
from datetime import datetime,timezone,timedelta

def display_time(value):
    if not value:return '尚无记录'
    try:return datetime.fromisoformat(value).astimezone().strftime('%Y-%m-%d %H:%M')
    except (ValueError,TypeError):return str(value)

class MonitorController(QObject):
    updated=Signal()
    def __init__(self,store,parent=None):
        super().__init__(parent);self.storage=MonitorStore(store);self.storage.seed();self.worker=None;self.browser=None
        self.timer=QTimer(self);self.timer.setInterval(30*60*1000);self.timer.timeout.connect(lambda:self.start(interactive=False))
        if self.storage.load().get('enabled'):self.timer.start();QTimer.singleShot(1500,lambda:self.start(interactive=False))
    def busy(self):return bool((self.browser and self.browser.busy) or (self.worker and self.worker.isRunning()))
    def ensure_browser(self):
        if not self.browser:
            from .system_browser import SystemBrowserMonitor
            if sys.platform=='win32':self.browser=SystemBrowserMonitor(self.storage.store.root,self.parent())
            else:
                from .browser_monitor import BrowserMonitor
                self.browser=BrowserMonitor(self.storage.store.root,self.parent())
            self.browser.result.connect(self.receive);self.browser.changed.connect(self.updated)
        return self.browser
    def open_account(self,account):self.ensure_browser().open_account(account)
    def open_video(self,account,video):self.ensure_browser().inspect_video(account,video)
    def read_current(self):
        if self.browser:self.browser.read_current()
        elif self.parent():toast(self.parent(),'请先选中账号，点击“打开抖音并登录”。')
    def load_recent(self,account):
        b=self.ensure_browser()
        b.start([account],interactive=True);b.show()
    def stop(self):
        if self.browser:self.browser.cancel()
        if self.worker and self.worker.isRunning():self.worker.requestInterruption()
    def shutdown(self):
        self.timer.stop();self.stop()
        if self.browser:self.browser.shutdown()
    def enable(self,enabled):
        value=self.storage.load();value['enabled']=enabled;self.storage.save(value)
        if enabled:self.timer.start();self.start()
        else:self.timer.stop()
        self.updated.emit()
    def start(self,checked=False,interactive=True):
        if self.busy():return
        accounts=self.storage.load()['accounts']
        if not accounts:return
        try:self.ensure_browser().start(accounts,interactive=interactive)
        except (RuntimeError,OSError,ValueError) as exc:
            for account in accounts:self.storage.apply(account['id'],{'error':'浏览器未能启动，请完整安装新版程序后重试。'+str(exc),'error_code':'browser_start'})
            self.updated.emit()
    def receive(self,id,result):
        try:
            events=self.storage.apply(id,result)
            if events and self.parent():
                names='、'.join(v['products'][0] if v['products'] else '书名待确认' for v in events[:3])
                toast(self.parent(),f'{len(events)} 条视频达到 {THRESHOLD} 赞：{names}')
                tray=getattr(self.parent(),'tray',None)
                if tray and tray.isVisible() and QSystemTrayIcon.supportsMessages():tray.showMessage('抖音100赞提醒',f'{len(events)} 条视频：{names}',QSystemTrayIcon.MessageIcon.Information,10000)
        except (ValueError,TypeError,KeyError) as exc:
            self.storage.apply(id,{'error':str(exc)})
            if self.parent():toast(self.parent(),str(exc),error=True)
        self.updated.emit()

class MonitorPanel(QWidget):
    def __init__(self,controller,parent=None):
        super().__init__(parent);self.controller=controller;self.page=0;layout=QVBoxLayout(self);layout.setContentsMargins(0,0,0,0);layout.setSpacing(12)
        layout.addWidget(selectable('使用系统 Edge／Chrome 的监测专用窗口。正常登录后读取公开作品；“加载近期作品”会继续加载后续批次。'))
        line=QHBoxLayout();self.link=QLineEdit();self.link.setPlaceholderText('粘贴抖音账号分享链接，可包含分享口令');line.addWidget(self.link,1)
        add=FeedbackButton('添加账号');add.clicked.connect(self.add);line.addWidget(add)
        self.check=FeedbackButton('立即检查');self.check.setProperty('role','primary');self.check.clicked.connect(controller.start);line.addWidget(self.check);layout.addLayout(line)
        self.auto=QCheckBox('工作台运行时，每30分钟检查');self.auto.setChecked(controller.storage.load().get('enabled',False));self.auto.toggled.connect(controller.enable);layout.addWidget(self.auto)
        self.status=selectable('');layout.addWidget(self.status)
        self.accounts=DataTable(0,5);self.accounts.setHorizontalHeaderLabels(['账号','最近尝试','最近成功','读取状态','100赞未读提醒']);self.accounts.setMaximumHeight(200);self.accounts.itemSelectionChanged.connect(self.choose);layout.addWidget(self.accounts)
        commands=QHBoxLayout()
        for title,fn in [('打开抖音并登录',self.open_account),('读取当前页面',controller.read_current),('加载近期作品',self.load_recent),('标为已读',self.mark_read),('补查书名',self.inspect_selected),('移除监测',self.remove)]:
            button=FeedbackButton(title);button.clicked.connect(fn);commands.addWidget(button)
        commands.addStretch();self.hot=QCheckBox('只看100赞及以上');self.hot.toggled.connect(self.reset_page);commands.addWidget(self.hot);layout.addLayout(commands)
        self.period=QComboBox();self.period.setObjectName('monitorPeriod');self.period.addItems(['全部已发现作品','最近30天','最近7天','日期未显示']);self.period.currentIndexChanged.connect(self.reset_page);layout.addWidget(self.period)
        self.works=DataTable(0,6);self.works.setHorizontalHeaderLabels(['挂车商品／书名','视频文案','点赞数','发布时间','书名依据','最近读取']);self.works.cellDoubleClicked.connect(self.open_video);layout.addWidget(self.works,1)
        pagination=QHBoxLayout();self.count=selectable('');pagination.addWidget(self.count);pagination.addStretch()
        self.previous=FeedbackButton('上一页');self.previous.clicked.connect(lambda:self.move_page(-1));pagination.addWidget(self.previous)
        self.following=FeedbackButton('下一页');self.following.clicked.connect(lambda:self.move_page(1));pagination.addWidget(self.following);layout.addLayout(pagination)
        controller.updated.connect(self.reload);self.reload()
    def selected(self):
        i=self.accounts.currentRow()
        if not 0<=i<len(self.rows):raise ValueError('请先选择一个账号')
        return self.rows[i]
    def add(self):
        try:self.controller.storage.add(self.link.text());self.link.clear();self.reload();toast(self,'账号已添加，点击“立即检查”读取公开数据')
        except ValueError as exc:toast(self,str(exc),True)
    def reload(self):
        selected=self.rows[self.accounts.currentRow()]['id'] if hasattr(self,'rows') and 0<=self.accounts.currentRow()<len(self.rows) else None
        self.rows=self.controller.storage.load()['accounts'];self.accounts.blockSignals(True);self.accounts.setRowCount(len(self.rows))
        for i,a in enumerate(self.rows):
            for j,v in enumerate((a['name'],display_time(a['last_attempt']),display_time(a['last_success']),a['error'] or '部分公开作品已读取',len(a['unread']))):self.accounts.setItem(i,j,QTableWidgetItem(str(v)))
        index=next((i for i,a in enumerate(self.rows) if a['id']==selected),0)
        if self.rows:self.accounts.selectRow(index)
        self.accounts.blockSignals(False);self.check.setEnabled(not self.controller.busy());self.check.setText('正在检查…' if self.controller.busy() else '立即检查')
        self.status.setText(self.controller.browser.message if self.controller.browser else '首次使用：选中账号 → 打开抖音并登录 → 加载作品后读取当前页面。达到100赞只提醒一次；无法确认的书名会标待确认。')
        self.choose()
    def choose(self):
        try:a=self.selected()
        except ValueError:a={'videos':{}}
        self.videos=sorted((v for v in a['videos'].values() if (not self.hot.isChecked() or is_hot(v)) and self.in_period(v)),key=lambda v:(v.get('published',''),v['id']),reverse=True)
        self.page=min(self.page,max(0,(len(self.videos)-1)//50));self.visible=self.videos[self.page*50:(self.page+1)*50];self.works.setRowCount(len(self.visible))
        for i,v in enumerate(self.visible):
            book='、'.join(v['products']) or ('文案提及：'+'、'.join(v['book_hints']) if v['book_hints'] else '待确认')
            for j,value in enumerate((book,v['title'],(v.get('likes_display') or ('未显示' if v.get('likes') is None else str(v['likes'])))+('（上次）' if v.get('likes_checked') and v['likes_checked']!=v['checked'] else ''),display_time(v['published']) if v['published'] else '未知',v['book_status'],display_time(v['checked']))):self.works.setItem(i,j,QTableWidgetItem(str(value)))
        self.count.setText(f'已发现 {len(self.videos)} 条作品 · 第 {self.page+1} 页'+(' · 暂无可显示作品' if not self.videos else ''))
        self.previous.setEnabled(self.page>0);self.following.setEnabled((self.page+1)*50<len(self.videos))
    def in_period(self,video):
        if self.period.currentIndex()==3:return not video.get('published')
        days={1:30,2:7}.get(self.period.currentIndex())
        if days is None:return True
        try:return datetime.now(timezone.utc)-datetime.fromisoformat(video.get('published',''))<=timedelta(days=days)
        except (ValueError,TypeError):return False
    def load_recent(self):
        try:self.controller.load_recent(self.selected())
        except (ValueError,RuntimeError,OSError) as exc:toast(self,str(exc),True)
    def reset_page(self):self.page=0;self.choose()
    def move_page(self,n):self.page+=n;self.choose()
    def open_account(self):
        try:self.controller.open_account(self.selected())
        except ValueError as exc:toast(self,str(exc))
    def open_video(self,row,column):
        if 0<=row<len(self.visible):self.controller.open_video(self.selected(),self.visible[row])
    def inspect_selected(self):
        i=self.works.currentRow()
        if i<0:toast(self,'请先选择下方的一条作品');return
        self.open_video(i,0)
    def mark_read(self):
        try:self.controller.storage.mark_read(self.selected()['id']);self.reload();toast(self,'已标为已读，同一视频不再重复提醒')
        except ValueError as exc:toast(self,str(exc))
    def remove(self):
        try:
            a=self.selected()
            if confirm(self,'移除账号','将停止该账号的监测，并移除本地缓存和提醒。抖音上的内容不会改变。','移除监测'):
                self.controller.storage.remove(a['id']);self.reload();toast(self,'已移除账号监测')
        except ValueError as exc:toast(self,str(exc))
