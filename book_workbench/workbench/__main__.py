import sys
from PySide6.QtCore import QLockFile,QTimer
from PySide6.QtWidgets import QApplication,QMessageBox
from .store import Store,data_dir
from .ui import MainWindow

def main():
    app=QApplication(sys.argv);app.setApplicationName('图书带货智能选品工作台');app.setOrganizationName('BookWorkbench')
    root=data_dir();root.mkdir(parents=True,exist_ok=True);lock=QLockFile(str(root/'workbench.lock'));lock.setStaleLockTime(0)
    if not lock.tryLock(100):
        if '--smoke-test' not in sys.argv:QMessageBox.information(None,'工作台已运行','请从任务栏或托盘打开当前实例')
        return 1
    store=None
    try:
        store=Store(root)
        with store.db:store.db.execute("UPDATE ai_analysis_history SET status='中断' WHERE status='请求中'")
        window=MainWindow(store);window.show()
        if '--smoke-test' in sys.argv:QTimer.singleShot(500,app.quit)
        return app.exec()
    except Exception:
        import traceback;traceback.print_exc();return 1
    finally:
        if store:store.close()
        lock.unlock()
if __name__=='__main__':raise SystemExit(main())
