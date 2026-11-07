from datetime import date
from PySide6.QtCore import Qt,QDate
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QFormLayout,QLineEdit,QTextEdit,
    QComboBox,QCheckBox,QDateEdit,QPushButton,QDialog,QDialogButtonBox,QScrollArea,QLabel,QFrame,
    QTextBrowser,QMessageBox,QToolButton,QSizePolicy,QApplication)
from .store import money

STYLE='''
QWidget {font-family: "Microsoft YaHei UI", "Noto Sans CJK SC", sans-serif; font-size:13px; color:#2b3932;}
QMainWindow,QDialog {background:#f5f6f2;}
QFrame#sidebar {background:#fcfcf9;border-right:1px solid #e3e7df;}
QLabel#brand {font-size:20px;font-weight:700;color:#255b46;}
QLabel#heading {font-size:25px;font-weight:650;}
QLabel#heroTitle {font-size:25px;font-weight:650;line-height:1.5;}
QLabel#muted {color:#748174;}
QLabel#eyebrow {font-size:11px;letter-spacing:2px;color:#748174;}
QLabel#badge {background:#e7eee3;color:#416447;padding:5px 9px;border-radius:5px;}
QFrame#hero {background:#e9efe3;border:1px solid #dde6d6;border-radius:14px;}
QFrame#card {background:#fff;border:1px solid #e3e7df;border-radius:10px;}
QPushButton {background:white;border:1px solid #dce2d7;border-radius:6px;padding:9px 14px;}
QPushButton:hover {background:#edf2e9;border-color:#b6c9b8;}
QPushButton#primary {background:#285f49;color:white;border:1px solid #285f49;}
QPushButton#primary:hover {background:#347256;}
QPushButton#nav {text-align:left;padding:13px 17px;border:none;background:transparent;color:#667565;}
QPushButton#nav:checked {background:#e8eee1;color:#295c44;font-weight:600;}
QPushButton:disabled {color:#a7afa3;background:#edf0e9;border-color:#e2e7df;}
QLineEdit,QComboBox,QDateEdit,QTextEdit,QPlainTextEdit {background:#fff;border:1px solid #dce2d7;border-radius:5px;padding:7px;selection-background-color:#d9e8d6;}
QLineEdit:focus,QTextEdit:focus {border:1px solid #77a184;}
QTextBrowser {background:transparent;border:none;padding:4px;}
QListWidget {background:#fff;border:1px solid #e3e7df;border-radius:8px;padding:5px;outline:none;}
QListWidget::item {padding:13px 10px;border-bottom:1px solid #f0f2ec;}
QListWidget::item:selected {background:#eaf0e4;color:#285d44;border-radius:5px;}
QTabWidget::pane {border:none;}
QTabBar::tab {padding:11px 15px;background:#eef1e9;color:#73806d;}
QTabBar::tab:selected {background:#fff;color:#2c6248;}
QScrollArea {border:none;background:transparent;}
QWidget#scrollBody {background:#f5f6f2;}
QToolButton {padding:7px;border:none;color:#557451;}
QDialogButtonBox QPushButton {min-width:75px;}
'''

def label(text,kind='',wrap=False):
    widget=QLabel(text)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    if kind: widget.setObjectName(kind)
    widget.setWordWrap(wrap)
    return widget

def button(text,slot=None,primary=False):
    widget=QPushButton(text)
    if slot: widget.clicked.connect(slot)
    if primary: widget.setObjectName('primary')
    return widget

def frame(kind='card'):
    widget=QFrame()
    widget.setObjectName(kind)
    layout=QVBoxLayout(widget)
    layout.setContentsMargins(24,22,24,22)
    layout.setSpacing(12)
    return widget,layout

def document(text=''):
    widget=QTextBrowser()
    widget.setOpenExternalLinks(False)
    widget.setOpenLinks(False)
    widget.setMarkdown(text)
    return widget

def confirm(parent,text):
    return QMessageBox.question(parent,'请确认',text,QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)==QMessageBox.StandardButton.Yes

def error(parent,exc): QMessageBox.warning(parent,'暂时无法完成',str(exc))
def info(parent,text): QMessageBox.information(parent,'造物手作',text)

def fit_window(widget,width,height):
    screen=widget.screen() or QApplication.primaryScreen()
    if screen:
        available=screen.availableGeometry()
        width=min(width,max(360,available.width()-32));height=min(height,max(360,available.height()-48))
    widget.resize(width,height)

class Fields(QWidget):
    def __init__(self,store,fields,values=None,business=None):
        super().__init__()
        self.fields=fields
        self.values_initial=values or {}
        self.inputs={}
        self.business=business
        form=QFormLayout(self)
        form.setContentsMargins(0,0,0,0)
        form.setVerticalSpacing(14)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        for f in fields:
            if f.key=='business' and business: continue
            value=self.values_initial.get(f.key)
            if f.kind=='choice':
                w=QComboBox(); w.addItems(f.options)
                if value in f.options: w.setCurrentText(value)
            elif f.kind in ('offer','reference'):
                w=QComboBox();w.addItem('暂不关联',None)
                table='offers' if f.kind=='offer' else 'references'
                for row in store.rows(table,business): w.addItem(row['name' if table=='offers' else 'title'],row['id'])
                index=w.findData(value)
                if index>=0:w.setCurrentIndex(index)
            elif f.kind=='bool':
                w=QCheckBox('允许'); w.setChecked(bool(value))
            elif f.kind=='date':
                w=QDateEdit();w.setCalendarPopup(True);w.setDisplayFormat('yyyy-MM-dd')
                w.setDate(QDate.fromString(value,'yyyy-MM-dd') if value else QDate.currentDate())
            elif f.kind=='long':
                w=QTextEdit();w.setAcceptRichText(False);w.setPlainText(str(value or ''))
                w.setMinimumHeight(86);w.setMaximumHeight(150)
                w.setPlaceholderText(f.hint)
            else:
                if f.kind=='money_optional' and value is not None:value=f'{value/100:.2f}'
                w=QLineEdit('' if value is None else str(value))
                w.setPlaceholderText(f.hint or ('未提供则留空' if f.kind in ('metric','money_optional') else 'YYYY-MM-DD，可留空' if f.kind=='optional_date' else ''))
            if f.hint: w.setToolTip(f.hint)
            self.inputs[f.key]=w
            form.addRow(f.label+(' *' if f.required else ''),w)

    def values(self):
        out={}
        for f in self.fields:
            if f.key=='business' and self.business: out[f.key]=self.business;continue
            w=self.inputs[f.key]
            if f.kind=='choice': v=w.currentText()
            elif f.kind in ('offer','reference'):v=w.currentData()
            elif f.kind=='bool':v=int(w.isChecked())
            elif f.kind=='date':v=w.date().toString('yyyy-MM-dd')
            elif f.kind=='long':v=w.toPlainText()
            else:v=w.text().strip()
            if f.kind=='money_optional': v=money(v) if v else None
            out[f.key]=v
        return out

def scroll(widget):
    widget.setObjectName('scrollBody')
    area=QScrollArea();area.setWidgetResizable(True);area.setWidget(widget)
    return area

class EditDialog(QDialog):
    def __init__(self,store,title,fields,values=None,business=None,parent=None,save=None,core_keys=None):
        super().__init__(parent)
        self.setWindowTitle(title);fit_window(self,640,700)
        self.save_callback=save
        self.result_values=None
        layout=QVBoxLayout(self);layout.setContentsMargins(24,22,24,20)
        layout.addWidget(label(title,'heading'))
        body=QWidget();content=QVBoxLayout(body)
        core=[f for f in fields if f.key in core_keys] if core_keys else fields[:4]+[f for f in fields[4:] if f.required]
        advanced=[f for f in fields if f not in core]
        self.form=Fields(store,core,values,business)
        self.extra=Fields(store,advanced,values,business)
        content.addWidget(self.form)
        if advanced:
            toggle=QToolButton();toggle.setText('展开补充资料');toggle.setCheckable(True)
            toggle.toggled.connect(self.extra.setVisible)
            toggle.toggled.connect(lambda checked:toggle.setText('收起补充资料' if checked else '展开补充资料'))
            content.addWidget(toggle);content.addWidget(self.extra);self.extra.hide()
        content.addStretch()
        layout.addWidget(scroll(body),1)
        self.notice=label('','muted',True);layout.addWidget(self.notice)
        actions=QHBoxLayout();actions.addStretch();actions.addWidget(button('取消',self.reject));actions.addWidget(button('保存',self.accept_values,True));layout.addLayout(actions)

    def accept_values(self):
        try:
            self.result_values=self.form.values()|self.extra.values()
            if self.save_callback:self.save_callback(self.result_values)
            self.accept()
        except Exception as exc:self.notice.setText(str(exc))
