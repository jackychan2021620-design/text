import sys
from PySide6.QtCore import QLockFile,QTimer,QCoreApplication,Qt,QUrl,QEvent
from PySide6.QtWidgets import QApplication,QMessageBox
from .store import Store,data_dir
from .ui import MainWindow

def main():
    if '--hang-test-helper' in sys.argv:
        import time
        time.sleep(60)
        return 0
    if '--note-import-helper' in sys.argv:
        from .import_job import run_browser_helper
        index=sys.argv.index('--note-import-helper')
        return run_browser_helper(sys.argv[index+1]) if len(sys.argv)>index+1 else 1
    browser_smoke='--browser-smoke-test' in sys.argv
    isolation_smoke='--import-isolation-smoke-test' in sys.argv
    smoke='--smoke-test' in sys.argv or browser_smoke or isolation_smoke
    QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
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
        if isolation_smoke:
            from .import_job import ImportJob
            args=[sys.executable]+([] if getattr(sys,'frozen',False) else [str(__import__('pathlib').Path(__file__).resolve().parents[1]/'launch.py')])+['--hang-test-helper']
            job=ImportJob(window,command=args,startup_seconds=1.5);window._isolation_job=job
            ticks=[0];heartbeat=QTimer(window);heartbeat.setInterval(50);heartbeat.timeout.connect(lambda:ticks.__setitem__(0,ticks[0]+1));heartbeat.start()
            def stopped():
                job.cleanup();app.exit(0 if ticks[0]>=8 else 1)
            job.stopped.connect(stopped);QTimer.singleShot(300,lambda:job.start('fixture'));QTimer.singleShot(10000,lambda:app.exit(1))
        elif browser_smoke:
            import json
            from PySide6.QtWebEngineCore import QWebEngineProfile,QWebEnginePage
            from .xhs import EXTRACT_JS,parse_note
            profile=QWebEngineProfile(window);page=QWebEnginePage(profile,window)
            window._smoke_profile=profile;window._smoke_page=page
            url='https://www.xiaohongshu.com/explore/'+'a'*24
            note={'noteId':'a'*24,'title':'Browser smoke fixture','desc':'Synthetic local fixture; no live requests.','imageList':[{'urlDefault':'https://sns-webpic-qc.xhscdn.com/fixture'}]}
            state={'note':{'noteDetailMap':{'a'*24:{'note':note}}}}
            def verify(payload):
                try:
                    result=parse_note(payload,url)
                    ok=result.title=='Browser smoke fixture' and len(result.images)==1
                    (root/'browser-smoke-result.json').write_text(json.dumps({'success':ok,'images':len(result.images)}))
                    app.exit(0 if ok else 1)
                except Exception as exc:
                    (root/'browser-smoke-result.json').write_text(json.dumps({'success':False,'error':str(exc),'page_url':page.url().toString()}))
                    app.exit(1)
            page.loadFinished.connect(lambda ok:page.runJavaScript(EXTRACT_JS,verify) if ok else app.exit(1))
            page.setHtml('<html><script>window.__INITIAL_STATE__='+json.dumps(state)+'</script></html>',QUrl(url))
            def timeout():
                (root/'browser-smoke-result.json').write_text(json.dumps({'success':False,'error':'renderer timeout'}));app.exit(1)
            QTimer.singleShot(20000,timeout)
        elif smoke:QTimer.singleShot(400,app.quit)
        return app.exec()
    except Exception as exc:
        if smoke:
            import traceback
            traceback.print_exc()
            return 1
        QMessageBox.critical(None,'工作台启动未完成','无法加载本地资料，请检查数据目录和磁盘空间。\n\n'+str(exc));return 1
    finally:
        if browser_smoke and 'window' in locals() and hasattr(window,'_smoke_page'):
            window._smoke_page.deleteLater()
            QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
            window._smoke_profile.deleteLater()
            QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
        if store:store.close()
        lock.unlock()

if __name__=='__main__':raise SystemExit(main())
