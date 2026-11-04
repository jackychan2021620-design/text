import sys
from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtCore import QLockFile
from .store import Store, data_dir
from .ui import MainWindow

def main():
    app=QApplication(sys.argv)
    app.setApplicationName('造物手作 AI 经营管理系统')
    app.setOrganizationName('Zaowu')
    root=data_dir()
    root.mkdir(parents=True,exist_ok=True)
    lock=QLockFile(str(root/'application.lock'))
    lock.setStaleLockTime(0)
    if not lock.tryLock(100):
        QMessageBox.warning(None,'程序已运行','当前数据目录已有程序运行，请从任务栏或系统托盘打开。')
        return 1
    store=Store(root)
    with store.db:
        store.db.execute("UPDATE messages SET status='incomplete' WHERE status='streaming'")
    store.auto_backup()
    store.reports_due()
    window=MainWindow(store)
    window.show()
    result=app.exec()
    store.close()
    lock.unlock()
    return result

if __name__=='__main__':
    sys.exit(main())
