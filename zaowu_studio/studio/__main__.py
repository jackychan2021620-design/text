import sys
from PySide6.QtCore import QLockFile,QTimer
from PySide6.QtWidgets import QApplication,QMessageBox
from .store import Store,data_dir
from .ui import MainWindow

def main():
    smoke='--smoke-test' in sys.argv
    app=QApplication(sys.argv);app.setApplicationName('造物手作内容工作台');app.setOrganizationName('Zaowu')
    root=data_dir();root.mkdir(parents=True,exist_ok=True)
    lock=QLockFile(str(root/'studio.lock'));lock.setStaleLockTime(0)
    if not lock.tryLock(100):QMessageBox.information(None,'工作台已运行','请从任务栏或托盘打开现有窗口。');return 1
    store=None
    try:
        store=Store(root)
        with store.db:store.db.execute("UPDATE ai_runs SET status='未完成' WHERE status='生成中'")
        store.maintain()
        window=MainWindow(store);window.show()
        if smoke:QTimer.singleShot(400,app.quit)
        return app.exec()
    except Exception as exc:
        if smoke:
            import traceback
            traceback.print_exc()
            return 1
        QMessageBox.critical(None,'工作台启动未完成','无法加载本地资料，请检查数据目录和磁盘空间。\n\n'+str(exc));return 1
    finally:
        if store:store.close()
        lock.unlock()

if __name__=='__main__':raise SystemExit(main())
