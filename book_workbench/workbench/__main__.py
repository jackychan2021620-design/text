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
        if '--smoke-test' in sys.argv:
            # Exercise bundled OCR inside the actual frozen process, not system Python.
            import json
            import shutil
            from pathlib import Path
            from .services import ocr,ocr_executable
            resources=(Path(sys._MEIPASS) if getattr(sys,'frozen',False) else Path(__file__).resolve().parents[1])/'resources'
            sample=root/'packaged-ocr.png';shutil.copyfile(resources/'ocr-check.png',sample);text=ocr(sample)
            if '12345' not in text:raise ValueError('Packaged OCR failed functional check')
            report={'frozen':bool(getattr(sys,'frozen',False)),'platform':app.platformName(),
                    'ocr_12345':True,'ocr_executable':ocr_executable(),'python_executable':sys.executable}
            (root/'packaged-smoke.json').write_text(json.dumps(report),encoding='utf-8')
            QTimer.singleShot(500,app.quit)
        return app.exec()
    except Exception:
        import traceback;traceback.print_exc();return 1
    finally:
        if store:store.close()
        lock.unlock()
if __name__=='__main__':raise SystemExit(main())
