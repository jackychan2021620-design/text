from PySide6.QtCore import Qt,QRect,Signal,QTimer,QSignalBlocker
from PySide6.QtGui import QPainter,QColor,QPen,QPolygonF
from PySide6.QtCore import QPointF
from .curve_field import CurvePlot
from PySide6.QtWidgets import QDialog,QWidget,QVBoxLayout,QHBoxLayout,QFormLayout,QScrollArea,QLabel,QLineEdit,QPushButton,QCheckBox,QDialogButtonBox,QApplication
from .image_io import read_image
from .curve import locate_curve,trace_curve,trace_manual
from .curve_worker import CurveWorker

from .experience import Dialog as QDialog

class PlotSelector(QWidget):
    changed=Signal(object)
    drawn=Signal()
    def __init__(self,image,rect=None):
        super().__init__();self.image=image;self.scale=min(1.5,740/image.width());self.setFixedSize(round(image.width()*self.scale),round(image.height()*self.scale))
        self.rect=list(rect) if rect else [0,0,image.width(),image.height()];self.start=None;self.overlay=[];self.draw_mode=False;self.manual_points=[]
    def point(self,event):
        return (max(0,min(self.image.width()-1,round(event.position().x()/self.scale))),max(0,min(self.image.height()-1,round(event.position().y()/self.scale))))
    def paintEvent(self,event):
        p=QPainter(self);p.drawImage(self.rect_to_display([0,0,self.image.width(),self.image.height()]),self.image)
        p.setPen(QPen(QColor('#08764f'),2));p.drawRect(self.rect_to_display(self.rect))
        if self.overlay:p.setPen(QPen(QColor('#d85b47'),2));p.drawPolyline(QPolygonF([QPointF(x*self.scale,y*self.scale) for x,y in self.overlay]))
        p.end()
    def rect_to_display(self,rect):return QRect(*(round(v*self.scale) for v in rect))
    def mousePressEvent(self,event):
        if event.button()==Qt.MouseButton.LeftButton:
            self.start=self.point(event)
            if self.draw_mode:self.manual_points=[self.start];self.overlay=list(self.manual_points)
    def mouseMoveEvent(self,event):
        if self.start:
            px,py=self.point(event);sx,sy=self.start
            if self.draw_mode:self.manual_points.append((px,py));self.overlay=list(self.manual_points)
            else:self.rect=[min(px,sx),min(py,sy),abs(px-sx)+1,abs(py-sy)+1];self.overlay=[];self.manual_points=[]
            self.update()
    def mouseReleaseEvent(self,event):
        if self.start:
            self.mouseMoveEvent(event);self.start=None
            if self.draw_mode:self.drawn.emit()
            else:self.changed.emit(self.rect)

class CurveDialog(QDialog):
    wordsReady=Signal(object)
    def __init__(self,path,words=(),count=90,parent=None):
        super().__init__(parent);self.setWindowTitle('销量曲线读图估算 · 请校准坐标');self.resize(850,min(900,self.screen().availableGeometry().height()-60))
        self.image=read_image(path);self.result_data=None;self.detected_words=list(words);self.worker=None;self._initialized=False;self._cancelled=False;self._user_changed=False;hint=None
        layout=QVBoxLayout(self);intro=QLabel('拖动绿色框，只圈住销量折线绘图区。四边应对齐坐标边界，而非最高／最低曲线点；不要圈入下方受众柱状图。');intro.setWordWrap(True);layout.addWidget(intro)
        scroll=QScrollArea();self.scroll=scroll;self.selector=PlotSelector(self.image,hint['rect'] if hint else None);scroll.setWidget(self.selector);layout.addWidget(scroll,1)
        if hint:
            x,y,w,h=hint['rect'];QTimer.singleShot(0,lambda:scroll.ensureVisible(round((x+w/2)*self.selector.scale),round((y+h/2)*self.selector.scale),50,100))
        form=QFormLayout();self.axis_form=form;self._absolute_axes=None;self.upper=QLineEdit('' if not hint or hint['upper'] is None else str(hint['upper']));self.upper.setPlaceholderText('填写绘图区顶部刻度，例如40')
        self.lower=QLineEdit(str(hint['lower']) if hint and hint['lower'] is not None else '0');self.count=QLineEdit(str(count))
        form.addRow('纵轴上界（必须核对）',self.upper);form.addRow('纵轴下界（必须核对）',self.lower);form.addRow('等距趋势采样点数',self.count);layout.addLayout(form)
        self.notice=QLabel('自动框仅用于定位，不能保证坐标精确。原始截图始终保留；本功能不恢复精确日期或逐日交易数据。');self.notice.setWordWrap(True);layout.addWidget(self.notice)
        self.preview=CurvePlot();self.preview.setFixedHeight(165);layout.addWidget(self.preview)
        self.auto_button=QPushButton('自动定位并预览');self.auto_button.clicked.connect(self.start_auto);layout.addWidget(self.auto_button)
        preview=QPushButton('按当前选框预览');preview.clicked.connect(self.extract);layout.addWidget(preview)
        self.relative=QCheckBox('只保存相对走势（0–100，不作为实际销量）');self.relative.toggled.connect(self.set_relative);layout.addWidget(self.relative)
        self.manual=QCheckBox('手动描绘走势：沿原图折线从左向右拖动');self.manual.toggled.connect(self.set_manual);layout.addWidget(self.manual)
        self.confirmed=QCheckBox('已核对绘图区和上下刻度，接受曲线是读图估算');layout.addWidget(self.confirmed)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel);buttons.button(QDialogButtonBox.StandardButton.Ok).setText('填入趋势估算点');self.buttons=buttons;buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('取消');buttons.accepted.connect(self.apply);buttons.rejected.connect(self.reject);layout.addWidget(buttons)
        for field in (self.upper,self.lower,self.count):field.textChanged.connect(self.invalidate)
        self.selector.changed.connect(self.selection_changed);self.selector.drawn.connect(self.manual_done)
    def showEvent(self,event):
        super().showEvent(event)
        if not self._initialized:self._initialized=True;QTimer.singleShot(0,self.start_auto)
    def start_auto(self):
        if self.worker and self.worker.isRunning():return
        self._user_changed=False;self.notice.setText('正在本地定位曲线并识别坐标，可继续操作或取消。');self.auto_button.setEnabled(False)
        app=QApplication.instance()
        if not hasattr(app,'_curve_workers'):app._curve_workers=set()
        worker=CurveWorker(self.image,self.detected_words,app);self.worker=worker;app._curve_workers.add(worker)
        worker.result.connect(self.auto_ready);worker.failed.connect(self.auto_failed)
        def finished():
            app._curve_workers.discard(worker);worker.deleteLater()
        worker.finished.connect(self.auto_finished);worker.finished.connect(finished)
        root=self.parentWidget()
        while root is not None:
            if hasattr(root,'finish_pending_close'):worker.finished.connect(root.finish_pending_close);break
            root=root.parentWidget()
        worker.start()
    def auto_finished(self):
        self.worker=None
        if not self._cancelled:self.auto_button.setEnabled(True)
    def auto_failed(self,message):
        if self._cancelled:return
        self.auto_button.setEnabled(True);self.notice.setText(message)
    def auto_ready(self,data):
        if self._cancelled:return
        self.auto_button.setEnabled(True);self.detected_words=data['words'];self.wordsReady.emit(self.detected_words);hint=data['hint']
        if not hint:self.notice.setText('未能自动定位。请拖框选中折线绘图区，填写上下刻度后预览；线条太浅时可勾选手动描绘。');return
        if self._user_changed:self.notice.setText('已完成自动分析，保留你手动调整的选框。按当前选框预览即可。');return
        self.selector.rect=hint['rect'];self.selector.update()
        if hint['upper'] is not None:
            self.relative.setChecked(False)
            with QSignalBlocker(self.upper):self.upper.setText(f"{hint['upper']:g}")
            with QSignalBlocker(self.lower):self.lower.setText(f"{hint['lower']:g}")
            self.extract()
        else:
            self.relative.setChecked(True);self.extract()
            self.notice.setText('已提取相对走势，可核对后保存。0–100只表示高低变化，不是销量；如需销量单位，取消相对走势并填写原图纵轴刻度。')
        x,y,w,h=self.selector.rect;self.scroll.ensureVisible(round((x+w/2)*self.selector.scale),round((y+h/2)*self.selector.scale),50,80)
    def selection_changed(self,*args):self._user_changed=True;self.invalidate()
    def set_relative(self,enabled):
        self.upper.setEnabled(not enabled);self.lower.setEnabled(not enabled)
        if enabled:self._absolute_axes=(self.upper.text(),self.lower.text())
        values=('100','0') if enabled else (self._absolute_axes or ('','0'))
        with QSignalBlocker(self.upper):self.upper.setText(values[0])
        with QSignalBlocker(self.lower):self.lower.setText(values[1])
        self.axis_form.labelForField(self.upper).setText('相对走势上界（固定100）' if enabled else '纵轴上界（必须核对）')
        self.axis_form.labelForField(self.lower).setText('相对走势下界（固定0）' if enabled else '纵轴下界（必须核对）')
        self.invalidate()
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText('保存相对走势' if enabled else '填入趋势估算点')
        self.confirmed.setText('已核对走势，理解0–100不代表实际销量' if enabled else '已核对绘图区和上下刻度，接受曲线是读图估算')
    def manual_done(self):self.invalidate();self.extract()
    def set_manual(self,enabled):
        self.selector.draw_mode=enabled;self.selector.manual_points=[];self.invalidate()
        self.notice.setText('沿原图曲线从左到右描绘；完成后会自动预览。仍需核对上下刻度。' if enabled else '拖动绿色框选择绘图区，再点预览。')
    def reject(self):
        self._cancelled=True
        if self.worker and self.worker.isRunning():self.worker.requestInterruption()
        super().reject()
    def invalidate(self,*args):self.result_data=None;self.confirmed.setChecked(False);self.preview.show_values([]);self.selector.overlay=[];self.selector.update()
    def extract(self):
        try:
            if not self.relative.isChecked() and not self.upper.text().strip():raise ValueError('请对照原图填写顶部刻度，例如40；下界通常为0。')
            try:upper,lower=(100,0) if self.relative.isChecked() else (float(self.upper.text()),float(self.lower.text()))
            except ValueError:raise ValueError('纵轴刻度请填数字，例如上界40、下界0。')
            try:count=int(self.count.text())
            except ValueError:raise ValueError('采样点数请填写7～366的整数，默认90即可。')
            args=(self.image,self.selector.rect,upper,lower,count)
            self.result_data=trace_manual(args[0],args[1],self.selector.manual_points,*args[2:]) if self.manual.isChecked() else trace_curve(*args)
            if self.relative.isChecked():self.result_data.update(source='相对走势',note='【曲线相对走势】'+('手动描绘估算；' if self.manual.isChecked() else '自动读图估算；')+'0–100只表示图中走势高低，不是实际销量或精确日值；不能求和替代90天总销量。')
            values=self.result_data['values'];self.preview.show_values(values,self.result_data.get('source','读图估算'))
            x,y,w,h=self.selector.rect
            self.selector.overlay=[(x+i*(w-1)/(len(values)-1),y+(upper-v)/(upper-lower)*(h-1)) for i,v in enumerate(values)];self.selector.update()
            self.notice.setText('红线是提取预览，绿色框是绘图区。请对照原始蓝线和下方曲线图核对，再确认。')
        except Exception as exc:self.result_data=None;self.notice.setText(str(exc))
    def apply(self):
        if self.result_data is None:self.extract()
        if not self.result_data:return
        if not self.confirmed.isChecked():self.notice.setText('请先核对绿色框及坐标刻度，再勾选估算确认。');return
        self.accept()
