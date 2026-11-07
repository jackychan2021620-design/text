import json
import sys
from datetime import date,timedelta
from pathlib import Path
from PySide6.QtCore import Qt,QSize,QTimer,QUrl
from PySide6.QtGui import QIcon,QDesktopServices,QPixmap
from PySide6.QtWidgets import (QApplication,QMainWindow,QWidget,QVBoxLayout,QHBoxLayout,QFrame,
    QComboBox,QListWidget,QListWidgetItem,QSplitter,QLineEdit,QTabWidget,QDialog,QMenu,QSystemTrayIcon,
    QFileDialog,QDialogButtonBox,QTextEdit)
from .model import BUSINESSES,STAGES,TABLES,PIECE_FIELDS
from .store import display_money
from .widgets import STYLE,label,button,frame,document,scroll,EditDialog,confirm,error,info,fit_window
from .workspace import PieceDialog,edit_asset
from .ai_dialog import AIDialog
from .settings import SettingsDialog

ROOT=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parents[1]))
ICON=ROOT/'resources'/'brand.ico'

class MainWindow(QMainWindow):
    TITLES=('今日工作','内容工作室','资料库','效果复盘')
    def __init__(self,store):
        super().__init__();self.store=store;self.runtime_key='';self.runtime_vision_key='';self.current=0;self.force_quit=False
        self.import_job=None;self.settings_dialog=None
        self.setWindowTitle('造物手作 · AI 获客与内容运营工作台');self.setWindowIcon(QIcon(str(ICON)))
        self.setMinimumSize(840,500);fit_window(self,1280,840);self.setStyleSheet(STYLE)
        root=QWidget();layout=QHBoxLayout(root);layout.setContentsMargins(0,0,0,0);layout.setSpacing(0)
        sidebar=QFrame();sidebar.setObjectName('sidebar');sidebar.setFixedWidth(195)
        nav=QVBoxLayout(sidebar);nav.setContentsMargins(18,28,18,20);nav.setSpacing(10)
        mark=label('');mark.setPixmap(QIcon(str(ICON)).pixmap(44,44));nav.addWidget(mark)
        nav.addWidget(label('造物手作','brand'));nav.addWidget(label('CONTENT STUDIO','eyebrow'));nav.addSpacing(34)
        self.nav_buttons=[]
        for index,title in enumerate(self.TITLES):
            b=button(title,lambda checked=False,i=index:self.navigate(i));b.setObjectName('nav');b.setCheckable(True)
            nav.addWidget(b);self.nav_buttons.append(b)
        nav.addStretch();nav.addWidget(label('把好内容，变成日常。','muted',True));nav.addSpacing(14)
        nav.addWidget(button('门店与设置',self.settings));nav.addWidget(label('资料保存在本机','muted'))
        layout.addWidget(sidebar)
        center=QWidget();self.center=QVBoxLayout(center);self.center.setContentsMargins(36,28,36,24);self.center.setSpacing(22)
        top=QHBoxLayout();self.heading=label('','heading');top.addWidget(self.heading,1)
        top.addWidget(label('当前业务','muted'));self.business=QComboBox();self.business.addItems(BUSINESSES);self.business.setMinimumWidth(130)
        focus=store.setting('focus',BUSINESSES[0]);self.business.setCurrentText(focus if focus in BUSINESSES else BUSINESSES[0]);self.business.currentTextChanged.connect(self.change_business)
        top.addWidget(self.business);self.center.addLayout(top)
        self.content=None;layout.addWidget(center,1);self.setCentralWidget(root)
        self.tray=None
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray=QSystemTrayIcon(self.windowIcon(),self);self.tray.setToolTip('造物手作 · 内容工作台')
            menu=QMenu(self);menu.addAction('打开工作台',self.showNormal);menu.addAction('退出',self.quit_app);self.tray.setContextMenu(menu)
            self.tray.activated.connect(lambda reason:self.showNormal() if reason==QSystemTrayIcon.ActivationReason.DoubleClick else None);self.tray.show()
        self.timer=QTimer(self);self.timer.setInterval(3600000);self.timer.timeout.connect(self.maintain);self.timer.start()
        self.refresh()

    @property
    def focus(self):return self.business.currentText()

    def change_business(self,business):self.store.set_setting('focus',business);self.refresh()

    def navigate(self,index):self.current=index;self.refresh()

    def refresh(self):
        self.heading.setText(self.TITLES[self.current])
        for index,b in enumerate(self.nav_buttons):b.setChecked(index==self.current)
        if self.content:self.center.removeWidget(self.content);self.content.deleteLater()
        self.content=(self.home,self.studio,self.library,self.review)[self.current]()
        self.center.addWidget(self.content,1)

    def home(self):
        body=QWidget();layout=QVBoxLayout(body);layout.setContentsMargins(0,0,0,0);layout.setSpacing(22)
        eyebrow=QHBoxLayout();eyebrow.addWidget(label(date.today().strftime('%Y.%m.%d')+'  /  今天只推进一步','eyebrow'));eyebrow.addStretch();layout.addLayout(eyebrow)
        quick=QHBoxLayout();link=QLineEdit();link.setPlaceholderText('发现好笔记？粘贴小红书分享文字或链接…')
        quick.addWidget(link,1);quick.addWidget(button('读取并收藏',lambda:self.import_xhs(link.text()),True));layout.addLayout(quick)
        product_bar=QHBoxLayout();product_bar.addWidget(label(f'产品与服务 · {len(self.store.rows("offers",self.focus))} 项','muted'),1)
        product_bar.addWidget(button('新增产品 / 服务',lambda:self.edit_entity('offers')))
        product_bar.addWidget(button('管理已录项目',lambda:self.navigate(2)));layout.addLayout(product_bar)
        hero,inside=frame('hero');inside.setContentsMargins(30,28,30,28)
        piece=self.store.next_piece(self.focus);offers=self.store.rows('offers',self.focus);refs=self.store.rows('references',self.focus)
        if piece:
            next_text={'选题':'先确定这条内容，为什么值得做。','素材':'复用手边素材，再补最少的画面。','草稿':'把方向，变成一份可发布的草稿。','待发布':'检查事实与承诺，准备好再发布。','已发布':'看看它带来了什么，再决定下一步。'}[piece['stage']]
            inside.addWidget(label(piece['stage']+' · '+piece['platform'],'muted'))
            inside.addWidget(label(next_text,'heroTitle',True));inside.addWidget(label(piece['topic'],'',True))
            inside.addWidget(label(piece['hypothesis'] or '写清楚希望吸引谁，以及本次准备验证什么。','muted',True))
            action=button('继续这条内容  →',lambda:self.open_piece(piece['id']),True)
        elif not offers:
            inside.addWidget(label('从你已有的产品和服务开始','muted'))
            inside.addWidget(label('先让工作台，了解你的生意。','heroTitle',True))
            inside.addWidget(label('写一次真实产品、价格和服务范围。以后选题和文案反复使用，不用每次重新介绍。','muted',True))
            action=button('录入第一个产品 / 服务  →',lambda:self.edit_entity('offers'),True)
        elif not refs:
            inside.addWidget(label('下一步 · 找到可以借鉴的表达','muted'))
            inside.addWidget(label('收藏一个案例，把灵感变成依据。','heroTitle',True))
            inside.addWidget(label('粘贴你实际看到的笔记内容或视频描述。链接留作来源，不会假装已读网页。','muted',True))
            action=button('整理第一个参考案例  →',lambda:self.edit_entity('references'),True)
        else:
            inside.addWidget(label('资料已准备 · 可以开始','muted'))
            inside.addWidget(label('选好接下来两周要做的内容。','heroTitle',True))
            inside.addWidget(label('结合案例、真实服务和时间预算，先提出少量待验证选题。','muted',True))
            action=button('AI 帮我准备两周选题  →',self.plan,True)
        actions=QHBoxLayout();actions.addWidget(action);actions.addStretch();inside.addLayout(actions);layout.addWidget(hero)
        row=QHBoxLayout();row.addWidget(label('接下来','brand'),1);row.addWidget(button('手动新建选题',self.new_piece));layout.addLayout(row)
        pending=sorted([p for p in self.store.rows('pieces',self.focus) if p['stage']!='已复盘' and (not piece or p['id']!=piece['id'])],key=lambda p:p['plan_date'])[:3]
        if pending:
            for p in pending:layout.addWidget(self.piece_card(p))
        else:
            card,cl=frame();cl.addWidget(label('保持少量、持续推进。'))
            cl.addWidget(label('目前没有其他待处理内容。完成眼前这一条，再安排下一条。','muted',True));layout.addWidget(card)
        start=date.today()-timedelta(days=date.today().weekday());end=start+timedelta(days=6)
        recorded=[r for r in self.store.review(self.focus)['items'] if start.isoformat()<=r['feedback']['observed_date']<=end.isoformat() and r['feedback']['minutes'] is not None]
        minutes=sum(r['feedback']['minutes'] for r in recorded)
        budget=self.store.setting('weekly_minutes','120')
        layout.addWidget(label(f'时间提醒：每周内容预算 {budget} 分钟。本周采集反馈中已记录 {minutes} 分钟（{len(recorded)} 条内容；按采集日归集，尚未记录的工作不包含在内）。','muted',True))
        layout.addStretch();return scroll(body)

    def piece_card(self,piece):
        card=QFrame();card.setObjectName('card');row=QHBoxLayout(card);row.setContentsMargins(18,16,18,16)
        text=QVBoxLayout();text.addWidget(label(piece['topic'],'',True));text.addWidget(label(f"{piece['platform']} · {piece['plan_date']} · {piece['stage']}",'muted'));row.addLayout(text,1)
        row.addWidget(button('打开',lambda:self.open_piece(piece['id'])));return card

    def studio(self):
        root=QWidget();layout=QVBoxLayout(root);layout.setContentsMargins(0,0,0,0)
        top=QHBoxLayout();top.addWidget(label('从一个选题，走到一次可学习的结果。','muted',True),1)
        top.addWidget(button('AI 安排两周选题',self.plan));top.addWidget(button('新建选题',self.new_piece,True));layout.addLayout(top)
        filters=QHBoxLayout();search=QLineEdit();search.setPlaceholderText('搜索选题或标题…');stage=QComboBox();stage.addItems(('全部进度',)+STAGES)
        filters.addWidget(search,1);filters.addWidget(stage);layout.addLayout(filters)
        area=QWidget();cards=QVBoxLayout(area);cards.setContentsMargins(0,8,0,0);cards.setSpacing(12)
        def load():
            while cards.count():
                item=cards.takeAt(0)
                if item.widget():item.widget().deleteLater()
            rows=[p for p in self.store.rows('pieces',self.focus) if (stage.currentIndex()==0 or p['stage']==stage.currentText()) and search.text().lower() in (p['topic']+' '+p['title']).lower()]
            for p in sorted(rows,key=lambda r:(r['plan_date'],r['id'])):cards.addWidget(self.piece_card(p))
            if not rows:
                card,cl=frame();cl.addWidget(label('暂无内容。可以先手动创建一个选题，或让 AI 根据已有资料提出计划。','muted',True));cards.addWidget(card)
            cards.addStretch()
        search.textChanged.connect(load);stage.currentIndexChanged.connect(load);load();layout.addWidget(scroll(area),1);return root

    def library(self):
        root=QWidget();layout=QVBoxLayout(root);layout.setContentsMargins(0,0,0,0)
        tabs=QTabWidget()
        for name,table in [('产品服务','offers'),('参考案例','references'),('照片与视频','assets'),('经验记忆','learnings'),('AI 记录','ai_runs')]:tabs.addTab(self.library_tab(table),name)
        layout.addWidget(tabs);return root

    def library_tab(self,table):
        root=QWidget();layout=QVBoxLayout(root);layout.setContentsMargins(10,18,10,10)
        tools=QHBoxLayout();search=QLineEdit();search.setPlaceholderText('搜索资料…');tools.addWidget(search,1)
        if table=='assets':tools.addWidget(button('导入图片 / 视频',self.import_assets,True))
        elif table=='references':
            tools.addWidget(button('粘贴小红书链接',lambda:self.import_xhs(),True));tools.addWidget(button('手动新增',lambda:self.edit_entity(table)))
        elif table!='ai_runs':tools.addWidget(button('新增',lambda:self.edit_entity(table),True))
        layout.addLayout(tools)
        split=QSplitter();items=QListWidget();details=document();split.addWidget(items);split.addWidget(details);split.setSizes([310,540]);layout.addWidget(split,1)
        records={}
        def load():
            records.clear();items.clear()
            for row in self.store.rows(table,self.focus):
                title=row.get('name') or row.get('title') or row.get('task')
                summary=row.get('platform') or row.get('kind') or row.get('level') or row.get('status') or row.get('audience') or '产品与服务'
                if search.text().lower() not in json.dumps(row,ensure_ascii=False).lower():continue
                item=QListWidgetItem(title+'\n'+summary);item.setData(Qt.ItemDataRole.UserRole,row['id']);items.addItem(item);records[row['id']]=row
            if items.count():items.setCurrentRow(0)
            else:details.setMarkdown('### 从少量真实资料开始\n\n保存后可以反复调用，不需要一次填完整。')
        def show():
            selected=items.currentItem()
            if not selected:return
            row=records[selected.data(Qt.ItemDataRole.UserRole)]
            if table in TABLES:
                # Render values as text via Markdown only in display; no HTML or external links execute.
                text='\n\n'.join('### '+field.label+'\n\n'+( ('允许' if row[field.key] else '不分享') if field.kind=='bool' else str(row[field.key] or '尚未填写')) for field in TABLES[table][1] if field.key!='business')
                if table=='references':
                    images=self.store.reference_images(row['id'])
                    if images:
                        count=sum(bool(i['path']) and Path(i['path']).is_file() for i in images)
                        text=f'**已收藏图文：{count} / {len(images)} 张图片。点击“查看图文”按原顺序浏览。**\n\n'+text
            elif table=='assets':text=f"## {row['name']}\n\n{row['kind']}\n\n{row['description'] or '尚未补充描述。'}\n\n文件保存在本地，AI 只使用你填写的描述。"
            else:text=f"## {row['task']} · {row['status']}\n\n{row['output'] or '没有收到完整内容。'}"
            details.setMarkdown(text)
        items.currentItemChanged.connect(lambda *_:show());search.textChanged.connect(load)
        actions=QHBoxLayout()
        def selected():return items.currentItem().data(Qt.ItemDataRole.UserRole) if items.currentItem() else None
        def edit():
            row_id=selected()
            if row_id is None:return
            if table=='assets':edit_asset(self,row_id);self.refresh()
            elif table=='ai_runs':
                row=self.store.get(table,row_id);AIDialog(self,row['task'],{'business':self.focus},history_run=row).exec()
            else:self.edit_entity(table,row_id)
        actions.addWidget(button('查看记录' if table=='ai_runs' else '编辑资料',edit))
        items.itemDoubleClicked.connect(lambda _:edit())
        if table=='references':
            def view_note():
                row_id=selected()
                if row_id:
                    from .reference_view import ReferenceDialog
                    ReferenceDialog(self,row_id).exec()
            actions.addWidget(button('查看图文',view_note))
            def analyze():
                row_id=selected()
                if row_id:self.ask('案例拆解',reference_id=row_id)
            def use():
                row_id=selected()
                if row_id:self.new_piece(reference=self.store.get('references',row_id))
            actions.addWidget(button('AI 拆解案例',analyze));actions.addWidget(button('用这个案例建选题',use))
            def open_source():
                row_id=selected()
                if not row_id:return
                url=QUrl(self.store.get('references',row_id)['url'])
                if url.scheme() not in ('http','https'):info(self,'请先填写有效的公开网页链接。');return
                QDesktopServices.openUrl(url)
            actions.addWidget(button('在浏览器看原文',open_source))
        if table=='offers':actions.addWidget(button('AI 咨询回复',lambda:self.ask('咨询辅助')))
        actions.addStretch()
        def remove():
            row_id=selected()
            if row_id is not None and confirm(self,'删除所选资料？已用于内容的素材受关联保护；删除案例或产品会解除关联，原有草稿保留。'):
                try:self.store.delete(table,row_id);self.refresh()
                except Exception as exc:error(self,exc)
        actions.addWidget(button('删除',remove));layout.addLayout(actions);load();return root

    def review(self):
        root=QWidget();layout=QVBoxLayout(root);layout.setContentsMargins(0,0,0,0)
        top=QHBoxLayout();top.addWidget(label('传播、本地相关需求和制作负担，分别判断。','muted',True),1)
        top.addWidget(button('导出反馈 CSV',self.export_review));top.addWidget(button('AI 帮我复盘',lambda:self.ask('效果复盘'),True));layout.addLayout(top)
        report=self.store.review(self.focus)
        body=QWidget();content=QVBoxLayout(body);content.setContentsMargins(0,8,0,0);content.setSpacing(16)
        cards=QHBoxLayout()
        for key,title in [('views','已记录阅读 / 播放'),('local_inquiries','已确认本地咨询'),('orders','已归因订单')]:
            metric=report['totals'][key];card,cl=frame();cl.addWidget(label(title,'muted'));cl.addWidget(label(str(metric['value']) if metric['value'] is not None else '未记录','heroTitle'))
            cl.addWidget(label(f"{metric['recorded']} / {metric['total']} 条反馈有此数据",'muted'));cards.addWidget(card)
        content.addLayout(cards)
        notice,inside=frame();inside.addWidget(label('先看事实，再提出解释。'))
        inside.addWidget(label('每条内容只汇总最新采集日的累计反馈。缺失保持未知；没有地域数据时，不根据播放量推断汕头覆盖。少量内容的差异只作为继续测试的线索。','muted',True));content.addWidget(notice)
        if not report['items']:
            content.addWidget(label('实际发布一条内容后，在内容工作室记录反馈，这里就会出现真实结果。','muted',True))
        for item in report['items']:
            card,cl=frame();cl.addWidget(label(item['topic'],'brand',True));feedback=item['feedback']
            cl.addWidget(label(item['platform']+' · 采集于 '+feedback['observed_date'],'muted'))
            cl.addWidget(label('观察事实：'+(feedback['facts'] or '未记录'),'',True));cl.addWidget(label('待验证解释：'+(feedback['explanation'] or '未记录'),'muted',True))
            cl.addWidget(label('下一步：'+(feedback['next_action'] or '未记录'),'',True));content.addWidget(card)
        content.addStretch();layout.addWidget(scroll(body),1);return root

    def new_piece(self,reference=None):
        keys=('topic','platform','plan_date','audience','hypothesis','offer_id','reference_id')
        fields=[f for f in PIECE_FIELDS if f.key in keys]
        initial={'reference_id':reference['id'],'audience':reference['audience'],'hypothesis':reference['mechanism']} if reference else {}
        new_id=[]
        def save(values):new_id.append(self.store.save('pieces',values|{'business':self.focus,'angle':reference['mechanism'] if reference else ''}))
        dialog=EditDialog(self.store,'新建一个待验证选题',fields,initial,self.focus,self,save)
        if dialog.exec():self.refresh();self.open_piece(new_id[0])

    def edit_entity(self,table,row_id=None):
        values=self.store.get(table,row_id) if row_id else {}
        dialog=EditDialog(self.store,('编辑' if row_id else '新增')+TABLES[table][0],TABLES[table][1],values,self.focus,self,lambda v:self.store.save(table,v,row_id))
        if dialog.exec():self.refresh()

    def open_piece(self,piece_id):
        PieceDialog(self,piece_id).exec();self.refresh()

    def import_assets(self):
        files,_=QFileDialog.getOpenFileNames(self,'选择本地素材','','图片与视频 (*.jpg *.jpeg *.png *.webp *.bmp *.mp4 *.mov *.mkv *.webm)')
        for file in files:
            try:self.store.add_asset(file,self.focus)
            except Exception as exc:error(self,exc)
        if files:self.refresh()

    def plan(self):
        def apply(items):
            preview='\n'.join(f"{i+1}. {p['plan_date']} · {p['platform']} · {p['topic']}" for i,p in enumerate(items))
            if not confirm(self,'将下列建议加入为“选题”阶段？尚未确认选题，也不会发布。\n\n'+preview):return False
            with self.store.transaction():
                for item in items:self.store.save('pieces',item|{'business':self.focus})
            self.refresh();return True
        self.ask('选题计划',apply=apply)

    def ask(self,task,reference_id=None,apply=None):
        try:
            context=self.store.context(self.focus,reference_id=reference_id,task=task)
            dialog=AIDialog(self,task,context,apply=apply)
            if task=='看图拍摄方案':QTimer.singleShot(0,dialog.generate)
            dialog.exec();self.refresh()
        except Exception as exc:error(self,exc)

    def import_xhs(self,text=''):
        try:
            from .import_job import ImportJob,SaveNoteWorker
            from .xhs import shared_url
            if self.import_job and (self.import_job.running() or (getattr(self.import_job,'save_worker',None) and self.import_job.save_worker.isRunning())):
                self.import_notice.show();self.import_notice.raise_();return
            if not text:
                from PySide6.QtWidgets import QInputDialog
                text,ok=QInputDialog.getText(self,'收藏小红书笔记','粘贴分享文字或链接')
                if not ok:return
            shared_url(text)
            business=self.focus
            job=ImportJob(self);self.import_job=job
            notice=QDialog(self);notice.setWindowModality(Qt.WindowModality.NonModal);notice.setWindowTitle('小红书读取 · 独立运行')
            fit_window(notice,570,230);body=QVBoxLayout(notice)
            status=label('正在启动独立网页窗口…','',True);body.addWidget(status)
            body.addWidget(label('工作台可以继续使用。网页卡住时可取消，不会关闭主工作台。','muted',True))
            row=QHBoxLayout();cancel_button=button('取消本次读取',job.cancel);row.addWidget(cancel_button);row.addWidget(button('收起',notice.hide));body.addLayout(row)
            self.import_notice=notice
            job.status.connect(status.setText)
            def failed(message):status.setText(message);self.statusBar().showMessage(message,15000)
            job.failed.connect(failed)
            def received(note,images):
                try:
                    existing=self.store.existing_note(note.note_id,business)
                    if existing and not confirm(self,'这篇笔记已收藏。是否更新原文及图片，并保留人工拆解？'):return
                    worker=SaveNoteWorker(self.store.root,note,images,business,update=bool(existing),parent=self)
                    job.save_worker=worker
                    cancel_button.setEnabled(False)
                    status.setText('正在后台保存文案和图片，工作台可以继续使用。')
                    def saved(ref):
                        notice.hide();self.refresh()
                        from .reference_view import ReferenceDialog
                        viewer=ReferenceDialog(self,ref);viewer.setWindowModality(Qt.WindowModality.NonModal);viewer.show()
                    worker.saved.connect(saved);worker.failed.connect(failed);worker.finished.connect(job.cleanup);worker.start()
                except Exception as exc:failed(str(exc))
            job.result.connect(received)
            def stopped():
                if job.cancelled:status.setText(job.error_message or '本次读取已取消，可继续使用工作台。')
                if not getattr(job,'save_worker',None):job.cleanup()
            job.stopped.connect(stopped);notice.show();job.start(text)
        except Exception as exc:error(self,'无法打开笔记读取窗口：'+str(exc))

    def export_review(self):
        path,_=QFileDialog.getSaveFileName(self,'导出反馈','内容反馈.csv','CSV (*.csv)')
        if path:
            try:self.store.export_review(path,self.focus);info(self,'已导出。金额单位为元，未知指标保留为空。')
            except Exception as exc:error(self,exc)

    def settings(self):
        if self.settings_dialog and self.settings_dialog.isVisible():self.settings_dialog.raise_();self.settings_dialog.activateWindow();return
        self.settings_dialog=SettingsDialog(self);self.settings_dialog.setWindowModality(Qt.WindowModality.NonModal);self.settings_dialog.show()

    def maintain(self):
        try:self.store.maintain()
        except Exception:self.statusBar().showMessage('自动备份未完成，请到设置检查资料目录和磁盘空间。')

    def quit_app(self):self.force_quit=True;self.close()

    def closeEvent(self,event):
        if self.import_job and self.import_job.running():
            self.import_job.cancel();event.ignore();QTimer.singleShot(500,self.close);return
        from PySide6.QtCore import QThread
        workers=[w for w in self.findChildren(QThread) if w.isRunning() and hasattr(w,'cancel')]
        if workers:
            for worker in workers:worker.cancel()
            self.statusBar().showMessage('正在完成后台保存或结束连接请求，请稍候；窗口仍可移动。')
            event.ignore();QTimer.singleShot(500,self.close);return
        if not self.force_quit and self.tray and self.store.setting('background','0')=='1':self.hide();event.ignore();return
        if self.tray:self.tray.hide()
        event.accept()
