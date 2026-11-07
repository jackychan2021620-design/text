from pathlib import Path
from PySide6.QtCore import Qt,QUrl,QTimer,QSize,Signal
from PySide6.QtGui import QIcon,QPixmap,QDesktopServices
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QLineEdit,QSplitter,QWidget,
    QTabWidget,QListWidget,QListWidgetItem,QPlainTextEdit,QProgressBar,QMessageBox)
from PySide6.QtWebEngineCore import QWebEnginePage,QWebEngineProfile
from PySide6.QtWebEngineWidgets import QWebEngineView
from .widgets import label,button,error,info,confirm,fit_window
from .xhs import shared_url,parse_note,EXTRACT_JS,ImageWorker

class NotePage(QWebEnginePage):
    blocked=Signal(str)

    def acceptNavigationRequest(self,url,kind,is_main):
        if not is_main:return True
        host=url.host().lower()
        allowed=host in ('xhslink.cn','xhslink.com','xiaohongshu.com') or host.endswith('.xiaohongshu.com')
        if url.scheme() in ('about','data'):return True
        if url.scheme()=='https' and allowed:return True
        self.blocked.emit('此窗口只打开小红书网页；不跳转到其他网站或外部应用。')
        return False

    def javaScriptConsoleMessage(self,*args):
        # Third-party pages can log account details. Never forward them to app logs.
        pass

from .reference_view import Gallery,image_items

class ImportDialog(QDialog):
    def __init__(self,window,initial_text='',session_dir=None):
        super().__init__(window);self.window=window;self.store=window.store;self.worker=None;self.note=None;self.images=[];self.reference_id=None;self.closed=False
        self.session_dir=Path(session_dir) if session_dir else None
        self.setWindowTitle('收藏小红书笔记');fit_window(self,1250,850)
        layout=QVBoxLayout(self);layout.setContentsMargins(22,20,22,18)
        layout.addWidget(label('粘贴链接，收藏文案和图片','heading'))
        row=QHBoxLayout();self.link=QLineEdit();self.link.setPlaceholderText('粘贴小红书复制链接的整段文字，也支持 xhslink.cn 短链接')
        self.open_button=button('打开笔记',self.open_note,True);row.addWidget(self.link,1);row.addWidget(self.open_button);layout.addLayout(row)
        layout.addWidget(label('需要登录时，在左侧正常登录或完成平台验证，再点“读取当前笔记”。账号会话仅在本次工作台运行中保留，不导出登录信息。','muted',True))
        split=QSplitter();self.web=QWebEngineView()
        if not getattr(window,'xhs_profile',None):window.xhs_profile=QWebEngineProfile(window)
        self.page=NotePage(window.xhs_profile,self.web);self.web.setPage(self.page)
        self.page.blocked.connect(self.set_status)
        self.page.certificateError.connect(self.reject_certificate)
        split.addWidget(self.web)
        preview=QWidget();right=QVBoxLayout(preview);right.setContentsMargins(16,0,0,0)
        self.title=label('等待读取','brand',True);right.addWidget(self.title)
        self.tabs=QTabWidget();self.text=QPlainTextEdit();self.text.setReadOnly(True);self.text.setPlaceholderText('成功读取后显示原始文案，不会根据分享标题猜测正文。')
        self.pictures=QListWidget();self.pictures.setViewMode(QListWidget.ViewMode.IconMode);self.pictures.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.pictures.itemDoubleClicked.connect(self.show_image)
        self.tabs.addTab(self.text,'文案');self.tabs.addTab(self.pictures,'图片');right.addWidget(self.tabs,1)
        split.addWidget(preview);split.setSizes([780,410]);layout.addWidget(split,1)
        self.status=label('未读取任何笔记。','muted',True);layout.addWidget(self.status)
        self.progress=QProgressBar();self.progress.hide();layout.addWidget(self.progress)
        actions=QHBoxLayout();self.read_button=button('读取当前笔记',self.extract);self.read_button.setEnabled(False)
        actions.addWidget(self.read_button);actions.addStretch();actions.addWidget(button('取消',self.reject))
        self.save_button=button('确认收藏到资料库',self.save,True);self.save_button.setEnabled(False);actions.addWidget(self.save_button);layout.addLayout(actions)
        self.web.loadFinished.connect(self.loaded)
        self.finished.connect(self.finish)
        if initial_text:self.link.setText(initial_text);QTimer.singleShot(0,self.open_note)

    def set_status(self,text):self.status.setText(text)

    def reject_certificate(self,certificate):
        certificate.rejectCertificate();self.set_status('网页证书验证失败，未继续访问；请检查系统时间和网络证书。')

    def open_note(self):
        if self.worker and self.worker.isRunning():return
        try:url=shared_url(self.link.text())
        except ValueError as exc:error(self,exc);return
        self.note=None;self.images=[];self.save_button.setEnabled(False);self.read_button.setEnabled(False);self.text.clear();self.pictures.clear();self.title.setText('正在打开笔记…')
        self.web.load(QUrl(url));self.set_status('正在打开分享页；如有登录或验证提示，请在网页中自行完成。')

    def loaded(self,ok):
        self.read_button.setEnabled(True)
        if ok:QTimer.singleShot(900,self.extract)
        else:self.set_status('页面未能完整加载。请检查网络，或等待网页显示后重新读取。')

    def extract(self):
        if self.closed or (self.worker and self.worker.isRunning()):return
        self.read_button.setEnabled(False);self.page.runJavaScript(EXTRACT_JS,self.extracted)

    def extracted(self,payload):
        self.read_button.setEnabled(True)
        if self.closed:return
        try:self.note=parse_note(payload,self.web.url().toString())
        except ValueError as exc:self.set_status(str(exc));return
        self.title.setText(self.note.title);self.text.setPlainText(self.note.text)
        self.images=[];self.save_button.setEnabled(False);self.open_button.setEnabled(False);self.read_button.setEnabled(False)
        if self.worker:self.worker.cleanup()
        self.worker=ImageWorker(self.note,self);self.worker.progress.connect(self.image_progress);self.worker.ready.connect(self.images_ready);self.worker.failed.connect(self.set_status)
        self.worker.finished.connect(self.worker_finished);self.worker.start()
        self.progress.setRange(0,len(self.note.images));self.progress.setValue(0);self.progress.show();self.set_status('已读取文案，正在按笔记顺序保存图片…')

    def image_progress(self,current,total):self.progress.setValue(current);self.set_status(f'正在读取图片 {current} / {total}')

    def images_ready(self,images):
        self.images=images;image_items(self.pictures,images);count=sum(bool(i['path']) for i in images)
        self.tabs.setTabText(1,f'图片 {count} / {len(images)}')
        message=f'文案已读取；图片 {count} / {len(images)} 张已下载。'
        if count<len(images):message+=' 有图片未读到，保存后仍会标明缺失。'
        if self.note.kind=='video':message+=' 这是视频笔记，目前只读取封面，不读取视频画面。'
        self.set_status(message);self.save_button.setEnabled(True)

    def worker_finished(self):
        self.open_button.setEnabled(True);self.read_button.setEnabled(True)
        if self.closed:self.worker.cleanup()

    def show_image(self,item):
        dialog=Gallery(self.images,self);dialog.show_index(item.data(Qt.ItemDataRole.UserRole));dialog.exec()

    def save(self):
        if not self.note or not self.images:return
        count=sum(bool(i['path']) for i in self.images)
        if count<len(self.images) and not confirm(self,f'目前只读到 {count} / {len(self.images)} 张图片。是否先收藏并保留缺失标记？'):return
        if self.session_dir:
            import shutil
            from .import_job import write_json
            exported=[]
            for image in self.images:
                row=dict(image)
                if row['path']:
                    target=self.session_dir/f"{row['position']}.png";shutil.copy2(row['path'],target);row['path']=str(target)
                exported.append(row)
            payload={'note':{'noteId':self.note.note_id,'title':self.note.title,'desc':self.note.text,'type':self.note.kind,
                'imageList':[{'urlDefault':u} for u in self.note.images]}}
            write_json(self.session_dir/'result.json',{'url':self.note.url,'payload':payload,'images':exported})
            self.accept();return
        existing=self.store.existing_note(self.note.note_id,self.window.focus)
        if existing and not confirm(self,'这篇笔记已收藏。是否更新原文、标题和图片，并保留你填写的拆解与观察？'):return
        try:self.reference_id=self.store.save_imported_note(self.note,self.images,self.window.focus,update=bool(existing))
        except Exception as exc:error(self,exc);return
        self.accept()

    def finish(self,*_):
        self.closed=True;self.web.stop()
        if self.worker:
            if self.worker.isRunning():self.worker.cancel()
            else:self.worker.cleanup()
        self.page.deleteLater()

    def reject(self):
        if self.worker and self.worker.isRunning():self.worker.cancel();self.set_status('正在停止读取…');QTimer.singleShot(300,self.reject);return
        super().reject()

    def closeEvent(self,event):
        if self.worker and self.worker.isRunning():self.worker.cancel();event.ignore();QTimer.singleShot(300,self.reject)
        else:super().closeEvent(event)
