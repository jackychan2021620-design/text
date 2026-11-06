"""Nonblocking curve positioning and axis OCR; no screenshot upload."""
import tempfile
from pathlib import Path
from PySide6.QtCore import QThread,Signal
from .curve import locate_curve
from .services import ocr_document

class CurveWorker(QThread):
    result=Signal(object);failed=Signal(str)
    def __init__(self,image,words=(),parent=None):super().__init__(parent);self.image=image.copy();self.words=list(words)
    def run(self):
        try:
            hint=locate_curve(self.image,self.words)
            if self.isInterruptionRequested():return
            if hint and hint['upper'] is None:
                x,y,w,h=hint['rect'];left=max(0,x-90);top=max(0,y-80);width=min(self.image.width()-left,w+110);height=min(self.image.height()-top,h+160)
                with tempfile.TemporaryDirectory(prefix='curve-axis-') as folder:
                    path=Path(folder)/'plot.png';self.image.copy(left,top,width,height).save(str(path))
                    doc=ocr_document(path)
                for word in doc['words']:
                    word=dict(word);word['left']+=left;word['top']+=top;self.words.append(word)
                if self.isInterruptionRequested():return
                hint=locate_curve(self.image,self.words)
            self.result.emit({'hint':hint,'words':self.words})
        except Exception as exc:self.failed.emit('自动定位未完成：'+str(exc)+'。可手动框选绘图区、填写刻度后预览，或选择手动描绘。')
