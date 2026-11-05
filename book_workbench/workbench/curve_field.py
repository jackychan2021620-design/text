"""A curve is presented as a chart; JSON is only its internal storage format."""
import json
import math
from PySide6.QtCore import Signal,QPointF,Qt
from PySide6.QtGui import QPainter,QColor,QPen
from PySide6.QtCharts import QChart,QChartView,QLineSeries,QValueAxis
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QDialog,QDialogButtonBox,QPlainTextEdit

from .experience import Dialog as QDialog

class CurvePlot(QWidget):
    def __init__(self,parent=None):
        super().__init__(parent);layout=QVBoxLayout(self);layout.setContentsMargins(0,0,0,0)
        self.status=QLabel('暂无销量曲线');self.status.setWordWrap(True);layout.addWidget(self.status)
        self.series=QLineSeries();self.series.setPen(QPen(QColor('#24866b'),2))
        self.chart=QChart();self.chart.addSeries(self.series);self.chart.legend().hide();self.chart.setBackgroundRoundness(12);self.chart.setDropShadowEnabled(False)
        self.x_axis=QValueAxis();self.x_axis.setTitleText('趋势采样点');self.x_axis.setLabelFormat('%.0f');self.x_axis.setRange(1,2)
        self.y_axis=QValueAxis();self.y_axis.setTitleText('销量');self.y_axis.setLabelFormat('%.0f');self.y_axis.setRange(0,1)
        self.chart.addAxis(self.x_axis,Qt.AlignmentFlag.AlignBottom);self.chart.addAxis(self.y_axis,Qt.AlignmentFlag.AlignLeft);self.series.attachAxis(self.x_axis);self.series.attachAxis(self.y_axis)
        self.view=QChartView(self.chart);self.view.setRenderHint(QPainter.RenderHint.Antialiasing);self.view.setMinimumHeight(100);layout.addWidget(self.view,1)
    def show_values(self,values,source='手工录入'):
        self.series.replace([QPointF(i+1,v) for i,v in enumerate(values)])
        self.x_axis.setRange(1,max(2,len(values)));self.x_axis.setTickCount(min(6,max(2,len(values))))
        self.y_axis.setRange(0,max(1,max(values,default=0)*1.1));self.y_axis.setLabelFormat('%.1f' if max(values,default=0)<5 else '%.0f')
        self.x_axis.setTitleText('等距趋势采样点' if source=='读图估算' else '录入顺序')
        self.status.setText(f'{source} · {len(values)}个曲线点'+(' · 仅供趋势参考，不是精确日销量' if source=='读图估算' else '') if values else '暂无曲线：选择截图后点击“从截图提取曲线”，或手动录入。')

class CurveField(QWidget):
    textChanged=Signal()
    extractRequested=Signal()
    provenanceChanged=Signal(str)
    def __init__(self,value='',source='手工录入',parent=None):
        super().__init__(parent);self.raw='';self.source=source;self.plot=CurvePlot();layout=QVBoxLayout(self);layout.setContentsMargins(0,0,0,0);layout.addWidget(self.plot);self.plot.setMinimumHeight(220)
        buttons=QHBoxLayout()
        for title,fn in [('从截图提取曲线',self.extractRequested.emit),('手动录入销量',self.manual),('清空曲线',lambda:self.setPlainText(''))]:
            b=QPushButton(title);b.clicked.connect(lambda checked=False,f=fn:f());buttons.addWidget(b)
        layout.addLayout(buttons);self.setPlainText(value or '')
    def toPlainText(self):return self.raw
    def setText(self,value):self.setPlainText(value)
    def setPlainText(self,value):
        self.raw=str(value or '')
        try:
            values=json.loads(self.raw) if self.raw.strip().startswith('[') else [float(x.strip()) for x in self.raw.replace('，',',').split(',')] if self.raw.strip() else []
            if not isinstance(values,list) or any(not isinstance(v,(int,float)) or not math.isfinite(v) or v<0 for v in values):raise ValueError()
            self.plot.show_values(values,self.source)
        except (ValueError,TypeError):self.plot.show_values([]);self.plot.status.setText('已有曲线无法绘制，请重新提取或清空后录入。')
        self.textChanged.emit()
    def set_curve(self,values,source='手工录入',note=None):
        self.source=source;self.setPlainText(json.dumps(values,ensure_ascii=False,allow_nan=False))
        if note:self.provenanceChanged.emit(note)
    def manual(self):
        d=QDialog(self);d.setWindowTitle('手动录入销量曲线');d.resize(460,480);layout=QVBoxLayout(d)
        note=QLabel('每行一个销量，可从Excel粘贴一列；按时间先后排列。这里填写实际日销量，不必使用程序格式。');note.setWordWrap(True);layout.addWidget(note)
        field=QPlainTextEdit();field.setPlaceholderText('例如：\n12\n18\n9');layout.addWidget(field,1)
        notice=QLabel('');notice.setWordWrap(True);layout.addWidget(notice)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel);buttons.button(QDialogButtonBox.StandardButton.Ok).setText('绘制曲线');layout.addWidget(buttons)
        def apply():
            try:
                lines=field.toPlainText().strip().splitlines();values=[float(line.strip()) for line in lines]
                if not values or any(not math.isfinite(v) or v<0 for v in values):raise ValueError()
                self.set_curve(values,'手工录入','【曲线手工录入】经营者按顺序录入的销量值。');d.accept()
            except ValueError:notice.setText('请每行填写一个非负数；中间不要空行，未知日值不能填成0。')
        buttons.accepted.connect(apply);buttons.rejected.connect(d.reject);d.exec()
