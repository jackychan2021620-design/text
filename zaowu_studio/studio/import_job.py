"""Browser isolation: untrusted webpages cannot block the workbench event loop."""
import json
import os
import signal
import sys
import tempfile
import time
from pathlib import Path
from PySide6.QtCore import QObject,QProcess,QTimer,Signal,QThread
from .xhs import parse_note

def write_json(path,value):
    path=Path(path);temporary=path.with_suffix('.new')
    temporary.write_text(json.dumps(value,ensure_ascii=False),encoding='utf-8')
    temporary.replace(path)

def read_result(directory):
    root=Path(directory).resolve();path=root/'result.json'
    if not path.is_file() or path.stat().st_size>2*1024*1024:raise ValueError('浏览器尚未返回有效笔记')
    result=json.loads(path.read_text(encoding='utf-8'))
    note=parse_note(result['payload'],result['url'])
    images=result.get('images')
    if not isinstance(images,list) or len(images)!=len(note.images):raise ValueError('返回的图片清单不完整')
    for index,row in enumerate(images,1):
        if row.get('position')!=index or row.get('url')!=note.images[index-1]:raise ValueError('返回的图片与原笔记不一致')
        if row.get('path'):
            image=Path(row['path']).resolve()
            if image.parent!=root or image.name!=f'{index}.png' or not image.is_file():raise ValueError('返回图片路径无效')
            if image.stat().st_size>60*1024*1024:raise ValueError('返回图片过大')
    return note,images

class SaveNoteWorker(QThread):
    saved=Signal(int)
    failed=Signal(str)
    def __init__(self,root,note,images,business,update=False,parent=None):
        super().__init__(parent);self.root=root;self.note=note;self.images=images;self.business=business;self.update=update;self.cancelled=False
    def cancel(self):self.cancelled=True
    def run(self):
        if self.cancelled:return
        from .store import Store
        store=None
        try:
            store=Store(self.root)
            row_id=store.save_imported_note(self.note,self.images,self.business,update=self.update)
            self.saved.emit(row_id)
        except Exception as exc:self.failed.emit(str(exc))
        finally:
            if store:store.close()

class ImportJob(QObject):
    status=Signal(str)
    result=Signal(object,object)
    failed=Signal(str)
    stopped=Signal()

    def __init__(self,parent=None,command=None,startup_seconds=25,heartbeat_seconds=40):
        super().__init__(parent)
        self.directory=tempfile.TemporaryDirectory(prefix='zaowu-browser-session-')
        self.root=Path(self.directory.name);self.command=command
        self.process=QProcess(self)
        # Never forward Chromium console/account output to application logs.
        self.process.setStandardOutputFile(os.devnull);self.process.setStandardErrorFile(os.devnull)
        if os.name!='nt':
            params=QProcess.UnixProcessParameters();params.flags=QProcess.UnixProcessFlag.CreateNewSession
            self.process.setUnixProcessParameters(params)
        self.process.finished.connect(self.finished);self.process.errorOccurred.connect(self.process_error)
        self.timer=QTimer(self);self.timer.setInterval(250);self.timer.timeout.connect(self.check)
        self.startup_seconds=startup_seconds;self.heartbeat_seconds=heartbeat_seconds
        self.cancelled=False;self.ended=False;self.started_at=0;self.last_state='';self.kill_process=None;self.error_message=''

    def start(self,text):
        write_json(self.root/'request.json',{'text':text})
        if self.command:program,*args=self.command
        else:
            program=sys.executable
            args=[] if getattr(sys,'frozen',False) else [str(Path(__file__).resolve().parents[1]/'launch.py')]
            args+=['--note-import-helper',str(self.root)]
        self.started_at=time.monotonic();self.status.emit('正在启动独立网页窗口…主工作台可以继续使用。')
        self.process.start(program,args);self.timer.start()

    def running(self):return self.process.state()!=QProcess.ProcessState.NotRunning

    def check(self):
        if self.ended or self.cancelled:return
        heartbeat=self.root/'heartbeat.json'
        elapsed=time.monotonic()-self.started_at
        try:
            if heartbeat.is_file():
                age=time.time()-heartbeat.stat().st_mtime
                if age>self.heartbeat_seconds:self.fail_and_cancel('网页窗口已停止响应，正在关闭。主工作台仍可使用，可以稍后重试。');return
                if heartbeat.stat().st_size<10000:
                    state=json.loads(heartbeat.read_text(encoding='utf-8')).get('status','网页窗口已打开')
                    if state!=self.last_state:self.last_state=state;self.status.emit(state)
            elif elapsed>self.startup_seconds:
                self.fail_and_cancel('网页组件启动超时，正在关闭独立窗口。你可以继续录入产品、设置 Key，或稍后重试。')
        except (OSError,ValueError):pass # Atomic file replacement can race a read on Windows.

    def process_error(self,kind):
        if kind==QProcess.ProcessError.FailedToStart:
            self.timer.stop();self.ended=True;self.failed.emit('无法启动独立网页窗口，请检查安装完整性。');self.stopped.emit()

    def fail_and_cancel(self,message):
        self.error_message=message
        self.failed.emit(message);self.cancel()

    def cancel(self):
        if self.ended or self.cancelled:return
        self.cancelled=True;self.status.emit(self.error_message or '正在取消网页读取…')
        if self.running():self.process.terminate();QTimer.singleShot(1200,self.kill_owned_tree)
        else:self.finished(0,QProcess.ExitStatus.NormalExit)

    def kill_owned_tree(self):
        if not self.running():return
        pid=int(self.process.processId())
        if pid<=0:return
        if os.name=='nt':
            self.kill_process=QProcess(self)
            self.kill_process.setStandardOutputFile(os.devnull);self.kill_process.setStandardErrorFile(os.devnull)
            self.kill_process.start('taskkill',['/PID',str(pid),'/T','/F'])
            QTimer.singleShot(1500,lambda:self.process.kill() if self.running() else None)
        else:
            try:os.killpg(pid,signal.SIGKILL)
            except ProcessLookupError:pass
            except OSError:self.process.kill()

    def finished(self,code,*_):
        if self.ended:return
        self.ended=True;self.timer.stop()
        if not self.cancelled:
            if (self.root/'result.json').exists():
                try:note,images=read_result(self.root);self.result.emit(note,images)
                except Exception as exc:self.failed.emit(str(exc))
            elif code not in (0,2):self.failed.emit('网页进程意外退出；已隔离退出，主工作台未关闭。请重试或先手工收藏。')
            else:self.status.emit('网页窗口已关闭，本次未新增案例。')
        self.stopped.emit()

    def cleanup(self):
        if self.running():self.cancel();return
        self.directory.cleanup()

def run_browser_helper(directory):
    """Only this child process imports/initializes Chromium. No database or Keys."""
    from PySide6.QtCore import Qt,QCoreApplication
    from PySide6.QtWidgets import QApplication,QWidget
    from .widgets import STYLE
    from .xhs_dialog import ImportDialog
    root=Path(directory).resolve()
    request=root/'request.json'
    if not root.name.startswith('zaowu-browser-session-') or not request.is_file():return 1
    value=json.loads(request.read_text(encoding='utf-8'))
    QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    app=QApplication(sys.argv);app.setStyleSheet(STYLE)
    from PySide6.QtGui import QIcon
    resource=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parents[1]))/'resources'/'brand.ico'
    app.setWindowIcon(QIcon(str(resource)))
    shell=QWidget();shell.store=None
    dialog=ImportDialog(shell,value.get('text',''),session_dir=root)
    timer=QTimer();timer.setInterval(1000)
    def heartbeat():write_json(root/'heartbeat.json',{'status':dialog.status.text()[:800]})
    timer.timeout.connect(heartbeat);heartbeat();timer.start()
    dialog.show()
    dialog.finished.connect(lambda code:app.exit(0 if code else 2))
    result=app.exec()
    timer.stop()
    from PySide6.QtCore import QCoreApplication,QEvent
    QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
    if getattr(shell,'xhs_profile',None):
        shell.xhs_profile.deleteLater();QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
    return result
