from PySide6.QtCore import Qt,QRect,Signal,QTimer
from PySide6.QtGui import QPainter,QColor,QPen,QPolygonF
from PySide6.QtCore import QPointF
from .curve_field import CurvePlot
from PySide6.QtWidgets import QDialog,QWidget,QVBoxLayout,QHBoxLayout,QFormLayout,QScrollArea,QLabel,QLineEdit,QPushButton,QCheckBox,QDialogButtonBox
from .image_io import read_image
from .curve import locate_curve,trace_curve

from .experience import Dialog as QDialog

class PlotSelector(QWidget):
    changed=Signal(object)
    def __init__(self,image,rect=None):
        super().__init__();self.image=image;self.scale=min(1.5,740/image.width());self.setFixedSize(round(image.width()*self.scale),round(image.height()*self.scale))
        self.rect=list(rect) if rect else [0,0,image.width(),image.height()];self.start=None;self.overlay=[]
    def point(self,event):
        return (max(0,min(self.image.width()-1,round(event.position().x()/self.scale))),max(0,min(self.image.height()-1,round(event.position().y()/self.scale))))
    def paintEvent(self,event):
        p=QPainter(self);p.drawImage(self.rect_to_display([0,0,self.image.width(),self.image.height()]),self.image)
        p.setPen(QPen(QColor('#08764f'),2));p.drawRect(self.rect_to_display(self.rect))
        if self.overlay:p.setPen(QPen(QColor('#d85b47'),2));p.drawPolyline(QPolygonF([QPointF(x*self.scale,y*self.scale) for x,y in self.overlay]))
        p.end()
    def rect_to_display(self,rect):return QRect(*(round(v*self.scale) for v in rect))
    def mousePressEvent(self,event):
        if event.button()==Qt.MouseButton.LeftButton:self.start=self.point(event)
    def mouseMoveEvent(self,event):
        if self.start:
            px,py=self.point(event);sx,sy=self.start;self.rect=[min(px,sx),min(py,sy),abs(px-sx)+1,abs(py-sy)+1];self.overlay=[];self.update()
    def mouseReleaseEvent(self,event):
        if self.start:self.mouseMoveEvent(event);self.start=None;self.changed.emit(self.rect)

class CurveDialog(QDialog):
    def __init__(self,path,words=(),count=90,parent=None):
        super().__init__(parent);self.setWindowTitle('销量曲线读图估算 · 请校准坐标');self.resize(850,min(900,self.screen().availableGeometry().height()-60))
        self.image=read_image(path);self.result_data=None
        try:hint=locate_curve(self.image,words)
        except ValueError:hint=None
        layout=QVBoxLayout(self);intro=QLabel('拖动绿色框，只圈住销量折线绘图区。四边应对齐坐标边界，而非最高／最低曲线点；不要圈入下方受众柱状图。');intro.setWordWrap(True);layout.addWidget(intro)
        scroll=QScrollArea();self.selector=PlotSelector(self.image,hint['rect'] if hint else None);scroll.setWidget(self.selector);layout.addWidget(scroll,1)
        if hint:
            x,y,w,h=hint['rect'];QTimer.singleShot(0,lambda:scroll.ensureVisible(round((x+w/2)*self.selector.scale),round((y+h/2)*self.selector.scale),50,100))
        form=QFormLayout();self.upper=QLineEdit('' if not hint or hint['upper'] is None else str(hint['upper']));self.upper.setPlaceholderText('填写绘图区顶部刻度，例如40')
        self.lower=QLineEdit(str(hint['lower']) if hint and hint['lower'] is not None else '0');self.count=QLineEdit(str(count))
        form.addRow('纵轴上界（必须核对）',self.upper);form.addRow('纵轴下界（必须核对）',self.lower);form.addRow('等距趋势采样点数',self.count);layout.addLayout(form)
        self.notice=QLabel('自动框仅用于定位，不能保证坐标精确。原始截图始终保留；本功能不恢复精确日期或逐日交易数据。');self.notice.setWordWrap(True);layout.addWidget(self.notice)
        self.preview=CurvePlot();self.preview.setFixedHeight(165);layout.addWidget(self.preview)
        preview=QPushButton('预览提取结果');preview.clicked.connect(self.extract);layout.addWidget(preview)
        self.confirmed=QCheckBox('已核对绘图区和上下刻度，接受曲线是读图估算');layout.addWidget(self.confirmed)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel);buttons.button(QDialogButtonBox.StandardButton.Ok).setText('填入趋势估算点');buttons.accepted.connect(self.apply);buttons.rejected.connect(self.reject);layout.addWidget(buttons)
        for field in (self.upper,self.lower,self.count):field.textChanged.connect(self.invalidate)
        self.selector.changed.connect(self.invalidate)
    def invalidate(self,*args):self.result_data=None;self.confirmed.setChecked(False);self.preview.show_values([]);self.selector.overlay=[];self.selector.update()
    def extract(self):
        try:
            self.result_data=trace_curve(self.image,self.selector.rect,float(self.upper.text()),float(self.lower.text()),int(self.count.text()))
            values=self.result_data['values'];self.preview.show_values(values,'读图估算')
            x,y,w,h=self.selector.rect;upper=float(self.upper.text());lower=float(self.lower.text())
            self.selector.overlay=[(x+i*(w-1)/(len(values)-1),y+(upper-v)/(upper-lower)*(h-1)) for i,v in enumerate(values)];self.selector.update()
            self.notice.setText('红线是提取预览，绿色框是绘图区。请对照原始蓝线和下方曲线图核对，再确认。')
        except Exception as exc:self.result_data=None;self.notice.setText(str(exc))
    def apply(self):
        if self.result_data is None:self.extract()
        if not self.result_data:return
        if not self.confirmed.isChecked():self.notice.setText('请先核对绿色框及坐标刻度，再勾选估算确认。');return
        self.accept()
