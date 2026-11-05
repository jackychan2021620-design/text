import sys
from PySide6.QtCore import QLockFile,QTimer
from PySide6.QtWidgets import QApplication,QMessageBox,QDialogButtonBox
from .store import Store,data_dir
from .ui import MainWindow,Editor,OCRReviewDialog
from . import APP_VERSION

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
            from .services import ocr_document,ocr_executable
            from .ocr_fields import propose_fields
            resources=(Path(sys._MEIPASS) if getattr(sys,'frozen',False) else Path(__file__).resolve().parents[1])/'resources'
            sample=root/'packaged-ocr.png';shutil.copyfile(resources/'ocr-check.png',sample);doc=ocr_document(sample);text=doc['text']
            if '12345' not in text:raise ValueError('Packaged OCR failed functional check')
            proposals=propose_fields(doc,'data_snapshots')
            if proposals.get('creators',{}).get('value')!=100 or proposals.get('sales',{}).get('value')!=12345:
                raise ValueError('Packaged OCR field extraction failed')
            previous=store.setting('draft:data_snapshots:new','{}')
            try:
                store.settings({'draft:data_snapshots:new':json.dumps({'screenshot':str(sample),'notes':'diagnostic draft'})})
                editor=Editor(store,'data_snapshots',parent=window)
                if not editor.fields['product_id'].isEditable():raise ValueError('Product URL entry unavailable')
                if not editor.fields['screenshot'].text().startswith('assets/'):raise ValueError('Legacy draft attachment was not recovered')
                editor.reject()
                reopened=Editor(store,'data_snapshots',parent=window);reopened.reject()
                review=OCRReviewDialog('data_snapshots',proposals,{},sample,window,ocr_text=text)
                review.apply()
                if review.approved.get('sales')!=12345:raise ValueError('OCR review failed')
            finally:store.settings({'draft:data_snapshots:new':previous})
            from .curve_ui import CurveDialog
            curve_probe=CurveDialog(resources/'mobile-layout-test.png',parent=window);curve_probe.reject()
            # Exercise the exact saved-snapshot edit/save path in a throwaway DB.
            import tempfile
            from .store import today
            with tempfile.TemporaryDirectory(prefix='book-revision-check-') as probe_root:
                probe_store=Store(probe_root)
                try:
                    book_id=probe_store.save('books',{'name':'diagnostic book'})
                    product_id=probe_store.save('product_links',{'book_id':book_id,'url':'https://example.invalid/diagnostic','status':'待分析'})
                    original=probe_store.save('data_snapshots',{'product_id':product_id,'collected':today(),'period_days':90,'confirmed':1,'sales':500,'curve':'[1,2,3,4,5,6,7]'})
                    edit=Editor(probe_store,'data_snapshots',probe_store.get('data_snapshots',original),window)
                    if 'ocr_text' in edit.fields:raise ValueError('Raw OCR editor still visible')
                    if edit.fields['curve'].plot.series.count()!=7:raise ValueError('Saved curve chart failed to render')
                    edit.fields['sales'].setText('1194');save=edit.buttons.button(QDialogButtonBox.StandardButton.Save)
                    if not save.isEnabled():raise ValueError('Saved-snapshot Save button disabled')
                    save.click()
                    if not hasattr(edit,'saved_id') or edit.saved_id==original:raise ValueError('Snapshot revision save failed')
                    if probe_store.get('data_snapshots',original)['sales']!=500 or probe_store.get('data_snapshots',edit.saved_id)['sales']!=1194:raise ValueError('Revision did not preserve original data')
                    probe_store.delete('data_snapshots',original)
                    if [r['id'] for r in probe_store.rows('data_snapshots')]!=[edit.saved_id]:raise ValueError('Trash did not hide only the selected snapshot')
                    if probe_store.latest('data_snapshots','product_id',product_id)['id']!=edit.saved_id:raise ValueError('Trash changed the good latest snapshot')
                    probe_store.restore_deleted('data_snapshots',original)
                    if len(probe_store.rows('data_snapshots'))!=2:raise ValueError('Trash restore failed')
                    from .grading import grade,render
                    peers=[{'creators':100,'sellers':10*(i+1),'sales':100*(i+1)**2,'period_days':90,'confirmed':1,'notes':''} for i in range(5)]
                    decision=grade(peers[-1],peers,'稳定销售型')
                    if decision['等级']!='非常适合':raise ValueError('Three-tier grading failed')
                    brief=render([{'商品ID':product_id,'图书':'diagnostic','分析':decision}])
                    if len(brief.splitlines())!=3 or '档次：非常适合' not in brief:raise ValueError('Brief grading response failed')
                finally:probe_store.close()
            report={'trash_recovery':True,'three_tiers':True,'revision_save':True,'curve_chart':True,'raw_ocr_hidden':True,'curve_dialog':True,'version':APP_VERSION,'collection_recovery':True,'ocr_fields':{k:v['value'] for k,v in proposals.items()},'frozen':bool(getattr(sys,'frozen',False)),'platform':app.platformName(),
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
