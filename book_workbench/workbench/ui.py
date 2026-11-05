import json
import math
import os
import sys
from datetime import date
from pathlib import Path
from PySide6.QtCore import Qt,QTimer,QUrl,QPropertyAnimation,QSignalBlocker
from PySide6.QtGui import QPixmap,QDesktopServices,QIcon,QPainter,QColor
from PySide6.QtWidgets import (QApplication,QMainWindow,QWidget,QVBoxLayout,QHBoxLayout,QFormLayout,QLabel,QPushButton,
 QLineEdit,QTextEdit,QComboBox,QCompleter,QCheckBox,QDialog,QDialogButtonBox,QScrollArea,QTableWidget,QTableWidgetItem,
 QHeaderView,QListWidget,QStackedWidget,QFileDialog,QMessageBox,QInputDialog,QSplitter,QSystemTrayIcon,QMenu,QGraphicsOpacityEffect)
from .experience import (Dialog as QDialog,FeedbackButton,DataTable,selectable,toast,confirm,install_policy,reduced_motion,readable,DURATION,clean_markdown,SmoothComboBox as QComboBox,SmoothMenu as QMenu)
from .monitor_ui import MonitorController,MonitorPanel
from .model import SCHEMA
from . import APP_VERSION
from .provenance import split_notes,combine_notes,scope_unknown,curve_source,UNKNOWN,CONFIRMED
from .curve_field import CurveField
from .grading import render as render_grades,rules_text,validate_rules,DEFAULTS
from .store import today,encode
from .services import AIWorker,OCRWorker,BackupWorker,api_key,save_key,endpoint,autorun,SYSTEM

STYLE="""QWidget{font-family:"Microsoft YaHei UI","Noto Sans CJK SC",sans-serif;font-size:14px;color:#242a35;background:#f7f8fa;}
QMainWindow{background:#f7f8fa;} QLabel#heading{font-size:22px;font-weight:600;} QLabel#muted{color:#707888;}
QPushButton,QToolButton{background:#fff;border:1px solid #dce0e6;border-radius:6px;padding:7px 12px;min-height:18px;}
QPushButton:hover,QToolButton:hover{background:#edf2fc;border-color:#9bb7ef;} QPushButton:pressed,QToolButton:pressed{background:#cdddfb;border-color:#4479e2;}
QPushButton:focus,QToolButton:focus{border:2px solid #4479e2;padding:6px 11px;} QPushButton:disabled{color:#a0a6af;background:#f0f1f3;}
QPushButton[role="primary"]{background:#3370ff;color:white;border-color:#3370ff;} QPushButton[role="primary"]:hover{background:#5085ff;} QPushButton[role="primary"]:pressed{background:#245bdb;}
QPushButton[role="danger"]{color:#c33434;border-color:#efc5c5;} QPushButton[role="danger"]:hover{background:#fff0f0;} QPushButton[role="danger"]:pressed{background:#fbdada;}
QLineEdit,QTextEdit,QPlainTextEdit,QComboBox,QTableWidget,QTableView,QListWidget{background:#fff;border:1px solid #e0e3e9;border-radius:6px;padding:5px;selection-background-color:#dce8ff;selection-color:#1d3d7a;}
QLineEdit:hover,QComboBox:hover{border-color:#a8bde3;} QLineEdit:focus,QTextEdit:focus,QPlainTextEdit:focus,QComboBox:focus{border-color:#3370ff;}
QLineEdit[invalid="true"],QComboBox[invalid="true"]{border-color:#d74444;background:#fff7f7;}
QHeaderView::section{background:#f1f3f6;padding:8px;border:0;border-bottom:1px solid #e3e6ec;color:#677080;}
QTableView{gridline-color:#edf0f4;alternate-background-color:#fafbfc;} QTableView::item:hover{background:#f0f5ff;} QTableView::item:focus{border:1px solid #6697ed;}
QListWidget::item{padding:11px 12px;margin:2px 4px;border-radius:6px;} QListWidget::item:hover{background:#edf1f8;} QListWidget::item:selected{background:#e3edff;color:#245bdb;} QListWidget::item:pressed{background:#cddfff;}
QTabBar::tab{padding:9px 14px;} QTabBar::tab:hover{background:#eef3ff;} QTabBar::tab:selected{color:#245bdb;border-bottom:2px solid #3370ff;} QTabBar::tab:focus{background:#e3edff;}
QMenu{background:white;border:1px solid #dce0e6;padding:4px;} QMenu::item{padding:8px 18px;} QMenu::item:selected{background:#e8f0ff;} QMenu::item:pressed{background:#d4e3ff;}
QComboBox QAbstractItemView::item:hover{background:#edf3ff;} QComboBox QAbstractItemView::item:selected{background:#dce8ff;}
QScrollArea{border:0;} QScrollBar:vertical{width:10px;background:transparent;} QScrollBar::handle:vertical{background:#c9cfd9;border-radius:4px;min-height:26px;} QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0;}
QCheckBox{padding:4px;} QCheckBox:hover{color:#245bdb;} QCheckBox:focus{outline:1px solid #7da4ee;} QWidget#toast{background:#fff;border:1px solid #d7dfea;border-radius:8px;} QWidget#toast[error="true"]{border-color:#e5aaaa;}
QLabel[error="true"]{color:#c33434;}"""

def label(text,heading=False):
    w=selectable(text)
    if heading:w.setObjectName('heading')
    return w

def button(text,fn):
    b=FeedbackButton(text);b.setObjectName('action:'+text);b.clicked.connect(fn)
    if text in ('新增','保存','保存设置','按三档规则推荐','保存修订版'):b.setProperty('role','primary')
    elif text in ('删除','清空曲线'):b.setProperty('role','danger')
    return b

def message(parent,text):toast(parent,str(text))

def document(parent,title,value):
    d=QDialog(parent);d.setWindowTitle(title);d.resize(900,740);layout=QVBoxLayout(d)
    t=QTextEdit();t.setReadOnly(True);t.setMarkdown(value) if isinstance(value,str) else t.setPlainText(readable(value));layout.addWidget(t)
    layout.addWidget(button('关闭',d.accept));d.exec()

def encode_pretty(value):return json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)

def cell(value):
    if value is None:return '未知'
    if isinstance(value,float):return f'{value:,.3f}'.rstrip('0').rstrip('.')
    return str(value)

def make_table(headers,rows):
    table=DataTable(len(rows),len(headers));table.setHorizontalHeaderLabels(headers)
    for i,row in enumerate(rows):
        for j,v in enumerate(row):table.setItem(i,j,QTableWidgetItem(cell(v)))
    return table

class OCRReviewDialog(QDialog):
    """Suggestions are shown beside evidence; existing values are opt-in to overwrite."""
    def __init__(self,table,proposals,current,image,parent=None,ocr_text=''):
        super().__init__(parent);self.setWindowTitle('截图数据核对 · 确认后填入');self.resize(760,min(820,QApplication.primaryScreen().availableGeometry().height()-70))
        self.inputs={};self.checks={};self.curve_result=None;self.image_path=image;self.words=[];layout=QVBoxLayout(self)
        layout.addWidget(label('识别值是待核对建议。千／万单位已换算；未可靠识别的字段留空，不以0代替。已有填写值默认不覆盖。'))
        preview=QLabel();pix=QPixmap(str(image))
        if not pix.isNull():preview.setPixmap(pix.scaled(650,min(240,QApplication.primaryScreen().availableGeometry().height()//4),Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation))
        preview.setAlignment(Qt.AlignmentFlag.AlignCenter);layout.addWidget(preview)
        layout.addWidget(button('打开原图核对',lambda:QDesktopServices.openUrl(QUrl.fromLocalFile(str(image)))))
        scroll=QScrollArea();scroll.setWidgetResizable(True);body=QWidget();form=QFormLayout(body);scroll.setWidget(body);layout.addWidget(scroll,1)
        from .ocr_fields import LABELS
        for key,title,_,_ in SCHEMA[table][1]:
            if key not in LABELS.get(table,{}) and not (key=='period_days' and key in proposals):continue
            suggestion=proposals.get(key);check=QCheckBox('填入');check.setChecked(bool(suggestion) and not current.get(key) )
            value=QLineEdit(str(suggestion['value']) if suggestion else '')
            value.textEdited.connect(lambda _,c=check:c.setChecked(True))
            row=QWidget();l=QHBoxLayout(row);l.setContentsMargins(0,0,0,0);l.addWidget(check);l.addWidget(value)
            form.addRow(title,row)
            evidence=suggestion['source'] if suggestion else '未可靠识别，请对照截图手动填写或留空'
            if suggestion and suggestion.get('warning'):evidence+='；'+suggestion['warning']
            if current.get(key):evidence+='；当前填写：'+str(current[key])
            form.addRow('',label(evidence));self.inputs[key]=value;self.checks[key]=check
        if table=='advertising_records':layout.addWidget(label('实际成交GMV必须对照截图左上角金额；不能把广告GMV或后台ROI填入该字段。位置不明的成交金额不会自动填入。'))
        if table=='data_snapshots':
            self.curve_info=label('销量曲线需要读图和坐标校准，不能由文字OCR自动恢复精确日销量。');layout.addWidget(self.curve_info)
            layout.addWidget(button('提取销量曲线（需核对坐标）',self.open_curve))
        self.notice=label('');layout.addWidget(self.notice)
        self.buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText('确认填入待核对字段')
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('暂不填入')
        self.buttons.accepted.connect(self.apply);self.buttons.rejected.connect(self.reject);layout.addWidget(self.buttons)
    def open_curve(self):
        from .curve_ui import CurveDialog
        dialog=CurveDialog(self.image_path,self.words,parent=self)
        if dialog.exec():
            self.curve_result=dialog.result_data;self.curve_info.setText(f'已准备{len(self.curve_result["values"])}个读图估算趋势点；确认后写入曲线并在备注标明来源。')
    def apply(self):
        from .ocr_fields import numeric_value
        self.approved={}
        for key,field in self.inputs.items():
            if not self.checks[key].isChecked():continue
            value=numeric_value(field.text(),key)
            if value is None:self.notice.setText('请填写有效非负数，人数、销量和订单必须是整数；无需填写的字段请取消勾选。');return
            self.approved[key]=value
        self.accept()

class Editor(QDialog):
    def __init__(self,store,table,record=None,parent=None,initial=None):
        super().__init__(parent);self.store=store;self.table=table;self.record=dict(record or {});self.fields={};self.worker=None
        self.errors={};self.kinds={key:kind for key,_,kind,_ in SCHEMA[table][1]};self.relation_hints={};self.attachment_labels={};self.restore_notices=[]
        self.revision_of=record['id'] if record and table in ('data_snapshots','advertising_records') else None
        self.read_only=False
        self.draft_key='draft:'+table+':'+str(self.record.get('id','new'))
        if not self.read_only:
            try:
                draft=json.loads(store.setting(self.draft_key,'{}'))
                if isinstance(draft,dict):self.record.update(draft)
            except (TypeError,ValueError):self.restore_notices.append('旧草稿无法读取，已打开可编辑表单。')
        if initial:self.record.update(initial)
        self.raw_ocr=self.record.get('ocr_text') or ''
        note_key='notes' if table=='data_snapshots' else 'other_metrics' if table=='advertising_records' else None
        self.note_key=note_key
        self.business_notes,self.audit_notes=split_notes(self.record.get(note_key)) if note_key else ('',[])
        self.setWindowTitle(('编辑快照 · 另存修订版' if self.revision_of else '编辑')+' · '+SCHEMA[table][0]);self.resize(820,min(120+sum(260 if f[2]=='curve' else 138 if f[2]=='long' else 60 for f in SCHEMA[table][1] if f[0]!='ocr_text'),900,QApplication.primaryScreen().availableGeometry().height()-70))
        outer=QVBoxLayout(self);scroll=QScrollArea();scroll.setWidgetResizable(True);body=QWidget();self.form=QFormLayout(body);self.form.setAlignment(Qt.AlignmentFlag.AlignTop);self.form.setVerticalSpacing(5);scroll.setWidget(body);outer.addWidget(scroll)
        for key,title,kind,required in SCHEMA[table][1]:
            if key=='ocr_text':continue
            value=self.record.get(key)
            if value is None and not record:
                if kind=='date' and required:value=today()
                elif key=='period_days':value=90
                elif kind=='bool':value=0
            if key==self.note_key:value=self.business_notes
            if isinstance(kind,list):
                w=QComboBox();w.addItems(kind)
                if value is not None:w.setCurrentText(str(value))
            elif kind in SCHEMA:
                w=QComboBox();w.setMinimumContentsLength(24);w.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
                if kind=='product_links':
                    w.setEditable(True);w.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
                    w.lineEdit().setPlaceholderText('选择已有商品，或直接粘贴商品链接')
                    w.completer().setFilterMode(Qt.MatchFlag.MatchContains);w.completer().setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
                self.fields[key]=w;self.reload_relation(key,value)
                draft_text=self.record.get('_relation_text',{})
                raw=draft_text.get(key) if isinstance(draft_text,dict) else None
                if kind=='product_links' and raw and w.currentData() is None:w.setEditText(raw)
            elif kind=='bool':w=QCheckBox('已核对录入数据，允许保存');w.setChecked(bool(value))
            elif kind=='curve':w=CurveField(value,curve_source(self.record.get('notes')));w.extractRequested.connect(self.extract_curve);w.provenanceChanged.connect(self.add_provenance)
            elif kind=='long':
                w=QTextEdit();w.setMaximumHeight(110);w.setPlainText(str(value or ''))
            else:w=QLineEdit('' if value is None else str(value))
            self.fields[key]=w
            if isinstance(kind,str) and kind in SCHEMA:
                wrapper=QWidget();row=QHBoxLayout(wrapper);row.setContentsMargins(0,0,0,0);row.addWidget(w,1)
                row.addWidget(button({'books':'新建图书','product_links':'新增商品链接','video_tests':'新增视频'}[kind],lambda checked=False,k=key:self.create_related(k)))
                self.form.addRow(title+('（必填）' if required else ''),wrapper)
                hint=label('');self.relation_hints[key]=hint;self.form.addRow('',hint);self.update_relation_hint(key)
            elif kind in ('image','file'):
                wrapper=QWidget();row=QHBoxLayout(wrapper);row.setContentsMargins(0,0,0,0)
                w.setParent(self);w.hide();caption=label('已选择附件' if value else '尚未选择附件');row.addWidget(caption,1);self.attachment_labels[key]=caption
                w.textChanged.connect(lambda text,c=caption:c.setText('已保存附件，可查看或重新选择' if text else '尚未选择附件'))
                row.addWidget(button('选择附件',lambda checked=False,k=key:self.pick(k)))
                if kind=='image':row.addWidget(button('查看原图',lambda checked=False,k=key:self.open_attachment(k)))
                row.addWidget(button('移除',lambda checked=False,k=key:self.remove_attachment(k)));self.form.addRow(title,wrapper)
            else:self.form.addRow(('销量走势图' if kind=='curve' else title)+('（必填）' if required else ''),w)
            error=label('');error.setProperty('error',True);error.setFixedHeight(16);error.setStyleSheet('font-size:12px');self.errors[key]=error;self.form.addRow('',error)
            if isinstance(w,QLineEdit):w.returnPressed.connect(self.save)
            if key=='creators':
                self.creator_scope=QComboBox();self.creator_scope.addItems(['已确认与本次统计周期一致','页面概览，统计周期待确认'])
                self.creator_scope.setCurrentIndex(int(scope_unknown(self.record.get('notes'))));self.form.addRow('带货人数统计范围',self.creator_scope)
        self.preview=QLabel();self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter);self.form.addRow(self.preview)
        if 'ocr_text' in self.kinds:
            self.ocr_button=button('重新识别截图并核对指标',self.recognize);self.form.addRow(self.ocr_button)
            self.form.addRow(label('选择截图后会自动识别并打开指标核对。人工确认填入后，还需勾选“已核对”再保存。曲线可手工录入，或读图提取并校准；估算来源会写入备注。'))
        self.notice=label('修改后点击“保存修订版”，原快照会保留。' if self.revision_of else '表单草稿自动保存；点击保存后进入正式档案。');outer.addWidget(self.notice)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText('保存修订版' if self.revision_of else '保存');buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('取消')
        buttons.accepted.connect(self.save);buttons.rejected.connect(self.reject);outer.addWidget(buttons);self.buttons=buttons
        self.draft_timer=QTimer(self);self.draft_timer.setSingleShot(True);self.draft_timer.timeout.connect(self.save_draft)
        for w in self.fields.values():
            signal=(w.editTextChanged if w.isEditable() else w.currentIndexChanged) if isinstance(w,QComboBox) else w.toggled if isinstance(w,QCheckBox) else w.textChanged
            signal.connect(lambda *args:self.draft_timer.start(500))
            signal.connect(lambda *args,field=w:self.clear_field_error(field))
        if hasattr(self,'creator_scope'):self.creator_scope.currentIndexChanged.connect(lambda *args:self.draft_timer.start(500))
        buttons.button(QDialogButtonBox.StandardButton.Save).setEnabled(True);buttons.button(QDialogButtonBox.StandardButton.Save).setProperty('role','primary')
        for b in self.findChildren(QPushButton):b.setAutoDefault(False);b.setDefault(False)
        for key in ('cover','screenshot','media'):
            if key in self.fields and self.fields[key].text():self.restore_attachment(key)
        if self.restore_notices:self.notice.setText('\n'.join(self.restore_notices))
    def add_provenance(self,note):
        if not self.audit_notes or self.audit_notes[-1]!=note:self.audit_notes.append(note)
        self.draft_timer.start(500)
    def extract_curve(self):
        from .curve_ui import CurveDialog
        try:
            value=self.fields['screenshot'].text()
            if not value:raise ValueError('请先选择包含销量走势图的截图')
            path=self.store.asset(value) if value.startswith('assets/') else Path(value)
            dialog=CurveDialog(path,getattr(self,'last_ocr_words',[]),parent=self)
            if dialog.exec():
                result=dialog.result_data;self.fields['curve'].set_curve(result['values'],'读图估算',result['note'])
                self.fields['confirmed'].setChecked(False)
                self.notice.setText('销量走势图已更新，请核对后保存。')
        except (ValueError,OSError) as exc:self.notice.setText(str(exc))
    def describe(self,table,r):
        if table=='product_links':return f'#{r["id"]} '+self.store.get('books',r['book_id'])['name']+' · '+r['url']
        return f'#{r["id"]} '+str(r.get('name') or r.get('code') or '')
    def reload_relation(self,key,id=None):
        w=self.fields[key];kind=self.kinds[key];w.clear();w.addItem('' if w.isEditable() else '请选择',None)
        for r in self.store.rows(kind):w.addItem(self.describe(kind,r),r['id'])
        w.setCurrentIndex(max(0,w.findData(id)))
    def update_relation_hint(self,key):
        kind=self.kinds[key];empty=self.fields[key].count()==1
        if kind=='product_links':text='暂无商品档案：可粘贴链接并保存，按提示补充图书；也可点击“新增商品链接”，在同一流程中新建图书。' if empty else '可选择已有商品或直接粘贴链接；新链接保存时会提示补充所属图书。'
        else:text='暂无记录，请点击右侧按钮新建后继续。' if empty else '选择已有记录，或点击右侧按钮新增。'
        self.relation_hints[key].setText(text)
    def pasted_url(self,key):
        import re
        match=re.search(r'https?://[^\s<>"\u201c\u201d]+',self.fields[key].currentText())
        return match[0].rstrip('，。；）)') if match else ''
    def relation_value(self,key):
        w=self.fields[key]
        if not w.isEditable() or w.currentText()==w.itemText(w.currentIndex()):return w.currentData()
        url=self.pasted_url(key)
        matches=[r['id'] for r in self.store.rows('product_links') if r['url']==url] if url else []
        return matches[0] if len(matches)==1 else None
    def create_related(self,key):
        kind=self.kinds[key];initial={}
        if kind=='product_links' and self.fields[key].currentData() is None:
            url=self.pasted_url(key)
            if url:initial['url']=url
        dialog=Editor(self.store,kind,parent=self,initial=initial)
        if dialog.exec():
            self.reload_relation(key,dialog.saved_id);self.update_relation_hint(key)
            return True
        return False
    def open_attachment(self,key):
        try:
            value=self.fields[key].text();path=self.store.asset(value) if value.startswith('assets/') else Path(value)
            if not value or not path.is_file():raise ValueError('请先选择图片，或重新选择已丢失的附件')
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.resolve())))
        except (ValueError,OSError) as exc:self.notice.setText(str(exc))
    def remove_attachment(self,key):
        self.fields[key].clear();self.preview.clear();self.notice.setText('已从当前表单移除附件；其他草稿内容保留，可重新选择。')
    def restore_attachment(self,key):
        value=self.fields[key].text()
        try:
            if value.startswith('assets/'):
                path=self.store.asset(value)
            else:
                # Recover old versions' external-path drafts without treating them as assets.
                path=Path(value)
                if not path.is_absolute() or not path.is_file():raise ValueError('旧草稿的原图片已移动或删除')
                if self.kinds[key]=='image' and QPixmap(str(path)).isNull():raise ValueError('旧草稿附件不是可读取的图片')
                archived=self.store.attach(path);self.fields[key].setText(archived);path=self.store.asset(archived)
            self.show_preview(path)
        except (ValueError,OSError) as exc:
            self.restore_notices.append(str(exc)+'。表单仍可编辑，请移除或重新选择附件；其他草稿内容已保留。')
            self.preview.setText('附件无法预览，请移除或重选')
    def pick(self,key):
        if self.worker and self.worker.isRunning():self.notice.setText('请等待当前识别结束后再更换截图。');return
        p,_=QFileDialog.getOpenFileName(self,'选择本地附件')
        if not p:return
        try:
            if self.kinds[key]=='image' and QPixmap(p).isNull():raise ValueError('无法读取这张图片，请选择PNG、JPG等图片文件')
            archived=self.store.attach(p);self.fields[key].setText(archived);self.show_preview(self.store.asset(archived))
            self.notice.setText('附件已复制到本地资料目录，原文件移动或删除不会影响草稿。')
            if key=='screenshot':self.recognize()
        except (ValueError,OSError) as exc:self.notice.setText(str(exc))
    def show_preview(self,path):
        pix=QPixmap(str(path));self.preview.clear()
        if not pix.isNull():self.preview.setPixmap(pix.scaled(500,230,Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation))
        else:self.preview.setText('附件已归档（非图片文件）')
    def recognize(self):
        if self.worker and self.worker.isRunning():self.notice.setText('正在识别，请等待当前识别结束。');return
        try:
            path=self.fields['screenshot'].text()
            if not path:raise ValueError('请先选择截图')
            if not path.startswith('assets/'):
                path=self.store.attach(path);self.fields['screenshot'].setText(path)
            path=self.store.asset(path)
            if 'confirmed' in self.fields:self.fields['confirmed'].setChecked(False)
            self.ocr_source=self.fields['screenshot'].text()
            self.worker=OCRWorker(str(path),self);self.worker.result.connect(self.got_ocr);self.worker.failed.connect(self.ocr_failed)
            self.worker.finished.connect(lambda:self.ocr_button.setEnabled(True));self.ocr_button.setEnabled(False)
            self.buttons.button(QDialogButtonBox.StandardButton.Save).setEnabled(False)
            self.worker.finished.connect(lambda:self.buttons.button(QDialogButtonBox.StandardButton.Save).setEnabled(True))
            self.notice.setText('正在本地识别截图，完成后将打开数据核对；不会上传图片。');self.worker.start()
        except (ValueError,OSError) as exc:self.notice.setText(str(exc))
    def ocr_failed(self,text):self.notice.setText('截图识别未完成：'+text+'。可重新识别或手动填写；附件和草稿已保留。')
    def got_ocr(self,document):
        from .ocr_fields import propose_fields
        if getattr(self,'ocr_source',self.fields['screenshot'].text())!=self.fields['screenshot'].text():
            self.notice.setText('截图已更换或移除，未应用旧截图的识别结果。');return
        if isinstance(document,str):document={'text':document}
        self.raw_ocr=document['text'];self.draft_timer.start(500);self.last_ocr_words=document.get('words',[]);proposals=propose_fields(document,self.table)
        review=OCRReviewDialog(self.table,proposals,self.values(),self.store.asset(self.fields['screenshot'].text()),self,ocr_text=document['text'])
        review.words=document.get('words',[])
        if review.exec():
            for key,value in review.approved.items():self.fields[key].setText(str(value))
            if review.curve_result and 'curve' in self.fields:
                self.fields['curve'].set_curve(review.curve_result['values'],'读图估算',review.curve_result['note'])
            if 'creators' in review.approved and proposals.get('creators',{}).get('warning') and hasattr(self,'creator_scope'):self.creator_scope.setCurrentIndex(1)
            if 'confirmed' in self.fields:self.fields['confirmed'].setChecked(False)
            self.notice.setText(f'已填入 {len(review.approved)} 项待核对指标。请对照原图检查，勾选“已核对”后保存；未识别字段可手动填写。')
        else:self.notice.setText('原始识别文字已保留，未改变数值。可重新识别或手动填写。')
    def values(self):
        out={}
        for key,_,kind,_ in SCHEMA[self.table][1]:
            if key=='ocr_text':out[key]=self.raw_ocr;continue
            w=self.fields[key]
            if isinstance(kind,list):v=w.currentText()
            elif kind in SCHEMA:v=self.relation_value(key)
            elif kind=='bool':v=int(w.isChecked())
            elif kind in ('long','curve'):v=w.toPlainText()
            else:v=w.text()
            out[key]=v
        if self.note_key:
            notes=combine_notes(out[self.note_key],self.audit_notes)
            if hasattr(self,'creator_scope'):
                unknown=self.creator_scope.currentIndex()==1
                if unknown!=scope_unknown(notes):notes=combine_notes(notes,[UNKNOWN if unknown else CONFIRMED])
            out[self.note_key]=notes
        return out
    def save_draft(self):
        if not self.read_only:
            values=self.values();values['_relation_text']={key:w.currentText() for key,w in self.fields.items() if isinstance(w,QComboBox) and w.isEditable() and self.relation_value(key) is None}
            self.store.settings({self.draft_key:encode(values)})
    def clear_field_error(self,field):
        field.setProperty('invalid',False);field.style().unpolish(field);field.style().polish(field)
        for key,w in self.fields.items():
            if w is field and key in self.errors:self.errors[key].setText('')
    def form_errors(self):
        errors={};values=self.values()
        for key,title,kind,required in SCHEMA[self.table][1]:
            if key=='ocr_text':continue
            value=values.get(key)
            if required and (value is None or value==''):
                if kind=='product_links' and self.pasted_url(key):continue
                errors[key]='请填写'+title;continue
            if value is None or value=='':continue
            if kind in ('number','percent','integer'):
                try:
                    n=float(value)
                    if not math.isfinite(n) or n<0 or (kind=='integer' and not n.is_integer()) or (kind=='percent' and n>100):raise ValueError()
                except (ValueError,TypeError):errors[key]='请填写有效非负'+('整数' if kind=='integer' else '数值')
            elif kind=='date':
                try:date.fromisoformat(value)
                except (ValueError,TypeError):errors[key]='日期格式为 YYYY-MM-DD'
        if self.table=='data_snapshots':
            if not values.get('confirmed'):errors['confirmed']='核对数据后请勾选确认'
            try:
                if values.get('creators') not in ('',None) and values.get('sellers') not in ('',None) and float(values['sellers'])>float(values['creators']):errors['sellers']='出单人数不能超过带货人数'
            except (ValueError,TypeError):pass
        for key,w in self.fields.items():
            invalid=key in errors;w.setProperty('invalid',invalid);w.style().unpolish(w);w.style().polish(w)
            if key in self.errors:self.errors[key].setText(errors.get(key,''))
        if errors:
            first=self.fields[next(iter(errors))];first.setFocus();self.notice.setText('请修正标记处，已填写内容和草稿均保留。')
        return errors
    def save(self):
        if hasattr(self,'saved_id'):return
        if self.form_errors():self.save_draft();return
        if self.worker and self.worker.isRunning():self.notice.setText('识别进行中，请先核对识别结果再保存。');return
        try:
            for key,kind in self.kinds.items():
                if kind=='product_links' and self.relation_value(key) is None:
                    url=self.pasted_url(key)
                    if not url:raise ValueError('请选择已有商品，或粘贴完整商品链接；没有商品时可点击“新增商品链接”当场建档。')
                    matches=[r for r in self.store.rows('product_links') if r['url']==url]
                    if len(matches)>1:raise ValueError('这个链接有多个商品档案，请从列表选择所属图书对应的商品。')
                    if not self.create_related(key):self.notice.setText('已保留采集草稿，请先补充该链接的所属图书再保存。');return
            values=self.values()
            if self.revision_of:
                key=self.note_key;values[key]=combine_notes(values.get(key),[f'【快照修订】修订自记录#{self.revision_of}，原记录保留。'])
            self.saved_id=self.store.save(self.table,values,None if self.revision_of else self.record.get('id'));self.draft_timer.stop()
            self.store.settings({self.draft_key:'{}'});self.buttons.button(QDialogButtonBox.StandardButton.Save).setEnabled(False);self.accept()
        except Exception as exc:self.notice.setText(str(exc))
    def reject(self):
        if hasattr(self,'saved_id'):return
        if self.worker and self.worker.isRunning():self.notice.setText('识别进行中，请等待结束后关闭');return
        self.draft_timer.stop();self.save_draft();super().reject()
    def closeEvent(self,event):
        if self.worker and self.worker.isRunning():event.ignore()
        else:self.reject();event.ignore()

class MainWindow(QMainWindow):
    def __init__(self,store):
        super().__init__();install_policy();self.store=store;self.runtime_key='';self.worker=None;self.ai_id=None;self.quitting=False;self.view_states={};self.view_key=None;self._crud_update=None;self.backup_worker=None;self.pending_quit=False
        QApplication.instance().setProperty('reducedMotion',store.setting('reduced_motion','0')=='1');self.monitor=MonitorController(store,self);self.monitor.updated.connect(self.finish_pending_close)
        self.setWindowTitle('图书带货智能选品工作台 · V'+APP_VERSION);self.resize(1550,950);self.setMinimumSize(1100,700)
        self.setStyleSheet(STYLE);root=QSplitter();self.setCentralWidget(root)
        self.nav=QListWidget();self.nav.addItems(['工作台首页','01 图书数据库','02 数据采集中心','03 选品分析引擎','04 多商品对比','05 AI选品顾问','06 视频投放与复盘','07 历史复盘','设置与备份','08 抖音账号监测']);self.nav.setMinimumWidth(160);self.nav.setMaximumWidth(230);root.addWidget(self.nav)
        self.center=QWidget();self.layout=QVBoxLayout(self.center);self.layout.setContentsMargins(20,20,20,20);self.layout.setSpacing(12);root.addWidget(self.center)
        assistant=QWidget();ai=QVBoxLayout(assistant);ai.setContentsMargins(16,24,16,24);ai.addWidget(label('AI 选品顾问',True));ai.addWidget(label('三档推荐 · 简短理由'))
        self.ai_task=QComboBox();self.ai_task.addItems(['三档选品推荐','简短问答','视频五日复盘','同类商品比较','15天数据变化分析','历史成功与失败案例分析']);ai.addWidget(self.ai_task)
        self.ai_scope=QComboBox();self.ai_scope.addItem('全部图书历史',None);ai.addWidget(self.ai_scope)
        self.question=QTextEdit();self.question.setPlaceholderText('输入问题；发送前展示完整上下文。AI不能操作数据或投放。');self.question.setMaximumHeight(120);ai.addWidget(self.question)
        self.ai_send=button('核对上下文并发送',self.ask_ai);ai.addWidget(self.ai_send)
        self.ai_output=QTextEdit();self.ai_output.setReadOnly(True);self.ai_output.setPlaceholderText('选择图书后点击推荐，档次与简短理由会显示在这里。');ai.addWidget(self.ai_output,1)
        self.ai_expand=button('展开完整回答',self.toggle_ai_answer);self.ai_expand.hide();ai.addWidget(self.ai_expand)
        self.ai_task.currentTextChanged.connect(self.configure_ai_task);self.configure_ai_task();assistant.setMinimumWidth(260);root.addWidget(assistant);root.setStretchFactor(1,1);root.setSizes([205,1000,345])
        self.content_effect=QGraphicsOpacityEffect(self.center);self.center.setGraphicsEffect(self.content_effect);self.page_fade=QPropertyAnimation(self.content_effect,b'opacity',self);self.page_fade.setDuration(DURATION)
        self.nav.currentRowChanged.connect(self.refresh);self.nav.setCurrentRow(0)
        pix=QPixmap(64,64);pix.fill(QColor('#567e6a'));p=QPainter(pix);p.setPen(QColor('white'));p.drawText(pix.rect(),Qt.AlignmentFlag.AlignCenter,'书');p.end();self.setWindowIcon(QIcon(pix))
        self.tray=QSystemTrayIcon(self.windowIcon(),self);menu=QMenu();menu.addAction('打开工作台',self.showNormal);menu.addAction('退出',self.quit_app);self.tray.setContextMenu(menu)
        self.tray.activated.connect(lambda _:self.showNormal())
        if QSystemTrayIcon.isSystemTrayAvailable():self.tray.show()
        self.timer=QTimer(self);self.timer.timeout.connect(self.maintain);self.timer.start(60000);QTimer.singleShot(100,self.maintain)
    def guarded(self,fn):
        try:return fn()
        except Exception as exc:toast(self,exc,error=True)
    def remember_view(self):
        if self.view_key is None:return
        state={}
        for i,w in enumerate(self.center.findChildren(QWidget)):
            key=w.objectName() or f'{type(w).__name__}:{i}'
            if w is QApplication.focusWidget():state['_focus']=key
            if isinstance(w,QComboBox):state[key]=('combo',w.currentText())
            elif isinstance(w,QLineEdit) and not isinstance(w.parent(),QComboBox):state[key]=('text',w.text())
            elif isinstance(w,QTextEdit):state[key]=('long',w.toPlainText())
            elif isinstance(w,QCheckBox):state[key]=('check',w.isChecked())
            elif isinstance(w,QScrollArea):state[key]=('scroll',w.verticalScrollBar().value())
            elif isinstance(w,DataTable):state[key]=('table_view',(w.verticalScrollBar().value(),w.horizontalScrollBar().value(),w.currentRow()))
        if getattr(self,'table',None) and self.table.parent() and self.center.isAncestorOf(self.table):
            state['_table']={'vertical':self.table.verticalScrollBar().value(),'horizontal':self.table.horizontalScrollBar().value(),'selected':self.visible[self.table.currentRow()]['id'] if hasattr(self,'visible') and 0<=self.table.currentRow()<len(self.visible) else None,'page':getattr(self,'page_number',0)}
        if self.view_key=='7':state['_history_page']=getattr(self,'history_page_number',0)
        self.view_states[self.view_key]=state
    def restore_view(self):
        state=self.view_states.get(self.view_key,{});restore_focus=None
        for i,w in enumerate(self.center.findChildren(QWidget)):
            key=w.objectName() or f'{type(w).__name__}:{i}'
            if key==state.get('_focus'):restore_focus=w
            if key not in state:continue
            kind,value=state[key];block=QSignalBlocker(w)
            if kind=='combo' and isinstance(w,QComboBox):w.setCurrentText(value)
            elif kind=='text' and isinstance(w,QLineEdit):w.setText(value)
            elif kind=='long' and isinstance(w,QTextEdit):w.setPlainText(value)
            elif kind=='check' and isinstance(w,QCheckBox):w.setChecked(value)
            elif kind=='scroll' and isinstance(w,QScrollArea):w.verticalScrollBar().setValue(value)
            elif kind=='table_view' and isinstance(w,DataTable):
                def restore_table(widget=w,position=value):
                    try:widget.selectRow(position[2]);widget.verticalScrollBar().setValue(position[0]);widget.horizontalScrollBar().setValue(position[1])
                    except RuntimeError:pass
                QTimer.singleShot(0,restore_table)
            del block
        if self._crud_update:self._crud_update(reset=False)
        if restore_focus:restore_focus.setFocus(Qt.FocusReason.OtherFocusReason)
        table=getattr(self,'table',None);saved=state.get('_table',{});view_key=self.view_key
        def restore_scroll():
            if table and self.view_key==view_key and self.table is table:
                for i,r in enumerate(self.visible):
                    if r['id']==saved.get('selected'):table.selectRow(i);break
                table.verticalScrollBar().setValue(saved.get('vertical',0));table.horizontalScrollBar().setValue(saved.get('horizontal',0))
        QTimer.singleShot(0,restore_scroll)
    def clear(self,view_key=None):
        self.remember_view();self._crud_update=None
        if hasattr(self,'search_timer'):self.search_timer.stop()
        while self.layout.count():
            item=self.layout.takeAt(0)
            widget=item.widget()
            if widget:widget.setParent(None);widget.deleteLater()
        self.table=None;self.visible=[]
        if view_key is not None:self.view_key=view_key
    def refresh(self,*args):
        scope=self.ai_scope.currentData();self.ai_scope.clear();self.ai_scope.addItem('全部图书历史',None)
        for b in self.store.rows('books'):self.ai_scope.addItem(f'仅图书#{b["id"]} '+b['name'],b['id'])
        self.ai_scope.setCurrentIndex(max(0,self.ai_scope.findData(scope)))
        self.center.setUpdatesEnabled(False);index=self.nav.currentRow();self.clear(str(index));self.layout.addWidget(label(self.nav.currentItem().text() if self.nav.currentItem() else '工作台',True))
        self.last_error=None
        try:
            [self.home,self.books,self.collection,self.products,self.comparison,self.ai_page,self.videos,self.history,self.settings_page,self.monitor_page][max(0,index)]()
            self.restore_view()
        except Exception as exc:self.last_error=str(exc);self.layout.addWidget(label(str(exc)));self.toolbar([('重试',self.refresh)])
        finally:
            self.center.setUpdatesEnabled(True)
            self.page_fade.stop();self.content_effect.setOpacity(1)
            if not reduced_motion():self.page_fade.setStartValue(.92);self.page_fade.setEndValue(1);self.page_fade.start()
    def toolbar(self,actions):
        w=QWidget();row=QHBoxLayout(w);row.setContentsMargins(0,0,0,0)
        for title,fn in actions:row.addWidget(button(title,lambda checked=False,f=fn:self.guarded(f)))
        row.addStretch();self.layout.addWidget(w)
    def editor(self,table,record=None):
        d=Editor(self.store,table,record,self)
        if d.exec():self.refresh();toast(self,'已保存，资料已更新')
    def selected(self,table=None):
        i=self.table.currentRow()
        if i<0:raise ValueError('请先选择一行')
        return self.visible[i]
    def crud(self,table,extra=()):
        self.table_name=table
        recovery=[('回收站',lambda:self.recycle_bin(table))] if table in ('data_snapshots','advertising_records') else []
        self.toolbar([('新增',lambda:self.editor(table)),('查看／编辑',lambda:self.editor(table,self.selected())),('删除',lambda:self.remove(table)),('历史',lambda:document(self,'修改历史',[r for r in self.store.rows('entity_history') if r['table_name']==table and r['entity_id']==self.selected()['id']]))]+list(extra)+recovery)
        filters=QWidget();row=QHBoxLayout(filters);row.setContentsMargins(0,0,0,0)
        search=QLineEdit();search.setObjectName('recordSearch');search.setPlaceholderText('搜索名称、链接、编号、备注…');search.setClearButtonEnabled(True);row.addWidget(search);self.search=search
        category=QComboBox();category.setObjectName('recordCategory');category.addItem('全部分类');category.addItems(sorted({r['category'] for r in self.store.rows('books') if r['category']}));row.addWidget(category);self.category=category;self.layout.addWidget(filters)
        view=make_table([],[]);self.table=view;self.layout.addWidget(view,1)
        empty=label('');empty.setObjectName('tableStatus');self.layout.addWidget(empty)
        navigation=QWidget();line=QHBoxLayout(navigation);line.setContentsMargins(0,0,0,0)
        previous=button('上一页',lambda:change_page(-1));following=button('下一页',lambda:change_page(1));counter=label('');line.addWidget(counter);line.addStretch();line.addWidget(previous);line.addWidget(following);self.layout.addWidget(navigation)
        self.page_number=self.view_states.get(self.view_key,{}).get('_table',{}).get('page',0);self.visible=[]
        cols=[('id','ID'),*[(k,t) for k,t,kind,_ in SCHEMA[table][1] if kind not in ('long','curve','image','file')]]
        view.setColumnCount(len(cols)+1);view.setHorizontalHeaderLabels([x[1] for x in cols]+['']);view.setColumnWidth(0,70);view.horizontalHeader().setStretchLastSection(False);view.horizontalHeader().setSectionResizeMode(1,QHeaderView.ResizeMode.Stretch)
        def update(reset=True):
            if self.table is not view:return
            if reset:self.page_number=0
            old_id=self.visible[view.currentRow()]['id'] if 0<=view.currentRow()<len(self.visible) else None
            old_scroll=view.verticalScrollBar().value();old_horizontal=view.horizontalScrollBar().value()
            try:
                rows,total=self.store.page(table,search.text(),category.currentText() if category.currentIndex()>0 else '',self.page_number,50)
                if not rows and total and self.page_number:
                    self.page_number=(total-1)//50;rows,total=self.store.page(table,search.text(),category.currentText() if category.currentIndex()>0 else '',self.page_number,50)
            except Exception as exc:
                empty.setText('暂时无法加载，原有数据已保留。'+str(exc));return
            self.statusBar().clearMessage();self.visible=rows;view.setUpdatesEnabled(False);view.setRowCount(len(rows))
            for i,r in enumerate(rows):
                for j,(key,_) in enumerate(cols):view.setItem(i,j,QTableWidgetItem(cell(r.get(key))))
                view.setItem(i,len(cols),QTableWidgetItem(''))
            view.setUpdatesEnabled(True);view.verticalScrollBar().setValue(old_scroll);view.horizontalScrollBar().setValue(old_horizontal)
            for i,r in enumerate(rows):
                if r['id']==old_id:view.selectRow(i);break
            previous.setEnabled(self.page_number>0);following.setEnabled((self.page_number+1)*50<total)
            counter.setText(f'共 {total} 条 · 第 {self.page_number+1}/{max(1,(total+49)//50)} 页 · 每页 50 条')
            empty.setText('没有符合条件的记录，可调整搜索或筛选。' if not rows and (search.text() or category.currentIndex()) else '暂无记录，点击“新增”开始。' if not rows else '')
            empty.setVisible(not rows)
        def change_page(delta):self.page_number+=delta;update(reset=False);view.verticalScrollBar().setValue(0)
        timer=QTimer(view);timer.setSingleShot(True);timer.setInterval(200);timer.timeout.connect(update);self.search_timer=timer
        search.textChanged.connect(lambda _:(timer.start(),self.statusBar().showMessage('正在筛选，已有数据保留显示')));category.currentIndexChanged.connect(lambda _:(timer.start(),self.statusBar().showMessage('正在筛选，已有数据保留显示')))
        self._crud_update=update;update(reset=False);view.pin_actions(len(cols));view.editRequested.connect(lambda i:(view.selectRow(i),self.guarded(lambda:self.editor(table,self.selected()))))
        view.cellDoubleClicked.connect(lambda *_:self.guarded(lambda:self.editor(table,self.selected())))
    def remove(self,table):
        r=self.selected()
        prompt='删除这条快照？将移入回收站，不再参与最新数据、对比、分档和提醒；可从回收站恢复。' if table in ('data_snapshots','advertising_records') else '确认删除档案？仍有关联历史、投放或复盘记录的图书／商品档案不能直接删除。'
        if confirm(self,'删除记录',prompt,'移入回收站' if table in ('data_snapshots','advertising_records') else '删除'):
            self.store.delete(table,r['id']);self.refresh_crud(table);toast(self,'已移入回收站，可随时恢复' if table in ('data_snapshots','advertising_records') else '已删除')
    def refresh_crud(self,table):
        if table=='advertising_records' and self.nav.currentRow()==6:self.ad_records()
        elif table=='product_links' and self.nav.currentRow()==1:self.product_list()
        else:self.refresh()
    def recycle_bin(self,table):
        d=QDialog(self);d.setWindowTitle('已删除快照 · 可恢复');d.resize(850,500);layout=QVBoxLayout(d)
        layout.addWidget(label('这些记录已退出计算和提醒。选择一行点击恢复，可重新参与统计；原始图片和历史引用仍保留。'))
        view=make_table(['ID','所属商品／视频','采集日期','销量／实际GMV'],[]);layout.addWidget(view,1);deleted=[]
        def update():
            deleted[:]=self.store.deleted_rows(table);view.setRowCount(len(deleted))
            for i,r in enumerate(deleted):
                values=[r['id'],r.get('product_id',r.get('video_id')),r['collected'],r.get('sales') if table=='data_snapshots' else r.get('actual_gmv')]
                for j,value in enumerate(values):view.setItem(i,j,QTableWidgetItem(cell(value)))
        def restore():
            i=view.currentRow()
            if i<0:message(d,'请先选择需要恢复的记录');return
            self.store.restore_deleted(table,deleted[i]['id']);update();self.refresh_crud(table)
        layout.addWidget(button('恢复选中记录',lambda:self.guarded(restore)));layout.addWidget(button('关闭',d.accept));update();d.exec()
    def books(self):
        self.crud('books');self.toolbar([('管理商品链接',lambda:self.product_list())])
    def product_list(self):
        self.clear(str(self.nav.currentRow())+':products');self.layout.addWidget(label('商品链接 · 一本书可对应多个商品',True));self.crud('product_links');self.restore_view()
    def collection(self):
        self.layout.addWidget(label('90天滚动快照 · 每个商品链接独立15天更新。原图、OCR结果与人工核对数据一同保存。'))
        self.crud('data_snapshots',[('两次快照对比',lambda:document(self,'快照变化（不是15天销量）',self.store.snapshot_diff(self.selected()['product_id'])))])
    def products(self):
        self.layout.addWidget(label('单本书即可按固定门槛分为三档；同类比较只作参考。核心数据缺失先补齐，曲线不足可保守试测。'))
        self.crud('product_links',[('三档简明推荐',lambda:document(self,'三档选品推荐',render_grades(self.store.grading_results()))),('分档规则',lambda:document(self,'三档规则',rules_text(self.store.grading_rules()))),('分析结果与曲线',self.show_analysis)])
    def show_analysis(self):
        id=self.selected()['id'];p=self.store.get('product_links',id);document(self,'选品分析',render_grades([{'商品ID':id,'图书':self.store.get('books',p['book_id'])['name'],'分析':self.store.analyze(id)}]));s=self.store.latest('data_snapshots','product_id',id)
        if s and s['curve']:self.chart(json.loads(s['curve']),'每日销量（人工确认）')
    def chart(self,values,title):
        from PySide6.QtCharts import QChart,QChartView,QLineSeries
        d=QDialog(self);d.setWindowTitle(title);d.resize(850,480);layout=QVBoxLayout(d);series=QLineSeries()
        for i,v in enumerate(values):series.append(i+1,v)
        chart=QChart();chart.addSeries(series);chart.createDefaultAxes();chart.setTitle(title);chart.legend().hide();view=QChartView(chart);view.setRenderHint(QPainter.RenderHint.Antialiasing);layout.addWidget(view);d.exec()
    def comparison(self):
        self.layout.addWidget(label('勾选2～10个商品。排序值只描述历史代理指标，跨品类或周期的名次不能视作进入成功率。'))
        self.pick_products=QListWidget()
        for p in self.store.rows('product_links'):
            from PySide6.QtWidgets import QListWidgetItem
            item=QListWidgetItem(f'#{p["id"]} '+self.store.get('books',p['book_id'])['name']+' · '+p['url']);item.setData(Qt.ItemDataRole.UserRole,p['id']);item.setFlags(item.flags()|Qt.ItemFlag.ItemIsUserCheckable);item.setCheckState(Qt.CheckState.Unchecked);self.pick_products.addItem(item)
        self.layout.addWidget(self.pick_products,1);self.order=QComboBox();self.order.addItems(['稳定出单机会','爆单容量','新创作者进入机会']);self.layout.addWidget(self.order)
        self.toolbar([('横向对比并说明排名',self.compare_selected)])
    def compare_selected(self):
        ids=[self.pick_products.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.pick_products.count()) if self.pick_products.item(i).checkState()==Qt.CheckState.Checked]
        records=self.store.compare(ids,self.order.currentText());d=QDialog(self);d.setWindowTitle('多商品横向比较');d.resize(1250,740);l=QVBoxLayout(d)
        l.addWidget(make_table(['商品ID','图书','售价','佣金','带货','出单','销量','出单率','出单人均','参与人均','趋势','市场需求','进入风险'],[[r['商品']['id'],r['图书'],r['商品']['price'],r['商品']['commission'],(r['快照'] or {}).get('creators'),(r['快照'] or {}).get('sellers'),(r['快照'] or {}).get('sales'),r['分析'].get('达人出单率'),r['分析'].get('出单达人人均销量'),r['分析'].get('参与达人人均销量'),r['分析'].get('销量趋势'),r['分析'].get('市场需求'),r['分析'].get('新创作者进入风险')] for r in records]))
        text=QTextEdit();text.setReadOnly(True);text.setPlainText(encode_pretty(records));l.addWidget(text);d.exec()
    def ai_page(self):
        self.layout.addWidget(label('右侧默认按三档规则即时推荐，无需配置Key。需要追问时切换“简短问答”，默认只给结论和短理由；发送前可预览资料，图片不会上传。'))
        self.layout.addWidget(button('打开AI连接设置',lambda:self.nav.setCurrentRow(8)))
        self.layout.addWidget(make_table(['时间','任务','状态'],[[r['created'],r['task'],r['status']] for r in self.store.rows('ai_analysis_history')]),1)
    def videos(self):
        self.crud('video_tests',[('广告数据',self.ad_records),('五日复盘',self.video_review),('延后2天',lambda:self.defer_video(2)),('延后3天',lambda:self.defer_video(3)),('同书视频对比',self.compare_videos)])
        tasks={r['video_id']:r for r in self.store.db.execute('SELECT * FROM video_review_tasks')}
        self.layout.addWidget(make_table(['视频','发布日期','广告提交','实际开始','原五日日期','当前复盘日期','剩余天数','已复盘'],[[v['code'],v['published'],v['submitted'],v['ad_started'],tasks[v['id']]['original_due'],tasks[v['id']]['due'],(date.fromisoformat(tasks[v['id']]['due'])-date.today()).days,bool(tasks[v['id']]['completed'])] for v in self.store.rows('video_tests')]))
    def ad_records(self):
        self.clear(str(self.nav.currentRow())+':ads');self.layout.addWidget(label('广告数据采集 · 实际GMV与后台GMV独立',True));self.crud('advertising_records');self.restore_view()
    def defer_video(self,n):
        due=self.store.defer(self.selected()['id'],n);message(self,'下次提醒：'+due+'。原复盘历史保留。');self.refresh()
    def video_review(self):
        id=self.selected()['id'];report=self.store.review(id);document(self,'复盘预览（尚未保存）',report)
        notes,ok=QInputDialog.getMultiLineText(self,'确认完成复盘','人工判断／依据（可提前复盘，保留不确定性）：')
        if ok:self.store.complete_review(id,notes);self.refresh()
    def compare_videos(self):
        v=self.selected();p=self.store.get('product_links',v['product_id']);records=self.store.video_comparison(p['book_id']);d=QDialog(self);d.setWindowTitle('同一本书 · 视频横向比较');d.resize(1200,800);l=QVBoxLayout(d)
        l.addWidget(make_table(['视频','账号','开头','方向','消耗','实际GMV','订单','后台GMV','后台ROI','实际GMV/消耗','消耗状态','复盘结论'],[[r['视频']['code'],r['视频']['account'],r['视频']['opening'],r['视频']['direction'],r['广告'].get('spend'),r['广告'].get('actual_gmv'),r['广告'].get('orders'),r['广告'].get('backend_gmv'),r['广告'].get('backend_roi'),r['实际GMV/消耗'],r['消耗状态'],(r['复盘'] or {}).get('当前视频处理建议','未复盘')] for r in records]))
        metrics=[('最高消耗','spend'),('最多订单','orders'),('最佳实际GMV/消耗',None)];summary={}
        for title,key in metrics:
            usable=[r for r in records if (r['广告'].get(key) if key else r['实际GMV/消耗']) is not None]
            summary[title]=max(usable,key=lambda r:r['广告'][key] if key else r['实际GMV/消耗'])['视频']['code'] if usable else '数据不足'
        summary['有消耗无成交']=[r['视频']['code'] for r in records if r['广告'].get('spend') and r['广告'].get('orders')==0]
        summary['已提交无有效消耗']=[r['视频']['code'] for r in records if r['视频']['submitted'] and not r['广告'].get('spend')]
        l.addWidget(label(encode_pretty(summary)+'\n特征与成交的关联不构成因果；未知消耗不等于确定零消耗。'));d.exec()
    def history(self):
        self.layout.addWidget(label('按图书和视频保留每次复盘、快照与建议，双击记录查看详情。'))
        self.history_kind=QComboBox();self.history_kind.setObjectName('historyKind');self.history_kind.addItems(['视频复盘报告','商品分析历史','AI分析历史','图书／商品历史分组','视频素材历史分组']);self.layout.addWidget(self.history_kind)
        state=self.view_states.get(self.view_key,{})
        if state.get('historyKind'):self.history_kind.setCurrentText(state['historyKind'][1])
        self.history_page_number=state.get('_history_page',0)
        self.history_table=make_table(['时间','内容（双击查看全部）'],[]);self.layout.addWidget(self.history_table,1)
        footer=QWidget();row=QHBoxLayout(footer);row.setContentsMargins(0,0,0,0);count=label('');row.addWidget(count);row.addStretch()
        previous=button('上一页',lambda:change(-1));following=button('下一页',lambda:change(1));row.addWidget(previous);row.addWidget(following);self.layout.addWidget(footer)
        def update(reset=True):
            if reset:self.history_page_number=0
            index=self.history_kind.currentIndex()
            if index<3:self.history_rows,total=self.store.history_page(['video_review_reports','product_analyses','ai_analysis_history'][index],self.history_page_number)
            else:
                if index==3:all_rows=[{'图书':self.store.get('books',p['book_id']),'商品':p,'分析':self.store.analyze(p['id'])} for p in self.store.rows('product_links')]
                else:all_rows=[{'视频':v,'最近广告':self.store.latest('advertising_records','video_id',v['id'])} for v in self.store.rows('video_tests')]
                total=len(all_rows);self.history_rows=all_rows[self.history_page_number*50:(self.history_page_number+1)*50]
            self.history_table.setRowCount(len(self.history_rows))
            for i,r in enumerate(self.history_rows):
                self.history_table.setItem(i,0,QTableWidgetItem(str(r.get('created',r.get('id',i+1)))));self.history_table.setItem(i,1,QTableWidgetItem(clean_markdown(readable(r))[:300]))
            count.setText(f'共 {total} 条 · 第 {self.history_page_number+1}/{max(1,(total+49)//50)} 页'+(' · 暂无记录' if not total else ''));previous.setEnabled(self.history_page_number>0);following.setEnabled((self.history_page_number+1)*50<total)
        def change(n):self.history_page_number+=n;update(reset=False)
        self.history_kind.currentIndexChanged.connect(update);self.history_table.cellDoubleClicked.connect(lambda i,j:document(self,'历史详情',self.history_rows[i]));update(reset=False)
        self.toolbar([('历史特征分组统计',self.history_summary)])
    def history_summary(self):
        groups={}
        for v in self.store.rows('video_tests'):
            p=self.store.get('product_links',v['product_id']);b=self.store.get('books',p['book_id']);a=self.store.latest('advertising_records','video_id',v['id']) or {}
            key=(b['category'],v['account'],v['opening'],v['direction'],v['format'],v['history_tag'],a.get('period'))
            g=groups.setdefault(key,{'视频数':0,'有有效消耗的视频':0,'已知成交视频':0,'实际GMV/消耗样本':[]});g['视频数']+=1;g['有有效消耗的视频']+=int(bool(a.get('spend')));g['已知成交视频']+=int(bool(a.get('orders')))
            from .analysis import ratio
            r=ratio(a.get('actual_gmv'),a.get('spend'))
            if r is not None:g['实际GMV/消耗样本'].append(r)
        document(self,'按品类／账号／素材／标签／统计范围分组',{'统计':[{'分组':k,**v} for k,v in groups.items()],'限制':'仅最新广告快照；非随机样本，未控制预算与投放环境，不能归因。可让AI结合完整历史提出待验证规则。'})
    def home(self):
        products=self.store.rows('product_links');videos=self.store.rows('video_tests');reminders=self.store.reminders()
        stats={'商品总数':len(products),'待分析':sum(p['status']=='待分析' for p in products),'非常适合':sum(self.store.analyze(p['id']).get('等级')=='非常适合' for p in products),'测试中':sum(p['status']=='测试中' for p in products),'已人工标记爆单':sum(p['history_tag'] in ('大爆单','小爆单') for p in products)}
        self.layout.addWidget(label('    '.join(f'{k}  {v}' for k,v in stats.items())))
        for kind,items in reminders.items():
            self.layout.addWidget(label(kind+' · 今日／即将到期／逾期'))
            self.layout.addWidget(make_table(['任务','截止日期','剩余天数','状态'],[[r['名称'],r['due'],r['剩余天数'],r['分组']] for r in items if r['分组']!='待办']))
        recent=[{'类型':'视频复盘','日期':r['created'],'详情':str(r['video_id'])+' · '+r['action']} for r in self.store.rows('video_review_reports')[:5]]
        recent += [{'类型':'商品更新','日期':s['collected'],'详情':f'商品#{s["product_id"]} 快照#{s["id"]}'} for s in self.store.rows('data_snapshots')[:5]]
        self.toolbar([('最近完成任务',lambda:document(self,'最近完成任务',recent)),('销量趋势概览',self.trend_overview),('商品状态分布',lambda:document(self,'商品状态分布',{s:sum(p['status']==s for p in products) for s in {p['status'] for p in products}}))])
        ranked=sorted([{'商品':p['id'],'图书':self.store.get('books',p['book_id'])['name'],'等级':self.store.analyze(p['id']).get('等级'),'趋势':self.store.analyze(p['id']).get('销量趋势','数据不足')} for p in products],key=lambda r:{'非常适合':0,'适合':1,'直接放弃':2,None:3}.get(r['等级'],3))[:8]
        self.layout.addWidget(make_table(['选品概览','图书','建议等级','趋势'],[[r['商品'],r['图书'],r['等级'] or '待补数据',r['趋势']] for r in ranked]),1)
        self.toolbar([('最近新增商品',lambda:document(self,'最近新增商品',products[:10])),('最近投放结果',lambda:document(self,'最近投放快照',self.store.rows('advertising_records')[:10]))])
    def trend_overview(self):
        ss=[]
        for p in self.store.rows('product_links'):
            s=self.store.latest('data_snapshots','product_id',p['id'])
            ss.append({'商品':p['id'],'采集时间':s['collected'] if s else None,'趋势':self.store.analyze(p['id']).get('销量趋势'),'曲线':s['curve'] if s else None})
        document(self,'趋势概览；详细曲线见选品分析',ss)
    def monitor_page(self):self.layout.addWidget(MonitorPanel(self.monitor,self),1)
    def settings_page(self):
        form_widget=QWidget();form=QFormLayout(form_widget);self.config={}
        for k,title,default in [('api_base','DeepSeek官方API地址','https://api.deepseek.com'),('model','模型（获取后选择）',''),('min_spend','最低测试消耗（元，经营门槛）','100'),('min_orders','最低订单样本（经营门槛）','5'),('target_ratio','目标实际GMV/消耗（非利润率）','1'),('grade_high_rate','优先档：出单率至少（%）','20'),('grade_high_sales','优先档：90天总销量至少','1000'),('grade_high_per_seller','优先档：出单人均销量至少','20'),('grade_high_sellers','优先档：出单人数至少','5'),('grade_low_rate','放弃参考：出单率低于（%）','5'),('grade_low_sales','放弃参考：90天总销量低于','100'),('grade_low_per_seller','放弃参考：出单人均销量低于','5'),('grade_min_peers','仅参考排名：最少同类商品数','5')]:
            w=QComboBox() if k=='model' else QLineEdit()
            if k=='model':w.setEditable(True);w.addItem(self.store.setting(k,default))
            else:w.setText(self.store.setting(k,default))
            form.addRow(title,w);self.config[k]=w
        self.key_input=QLineEdit();self.key_input.setEchoMode(QLineEdit.EchoMode.Password);self.key_input.setPlaceholderText('留空保留已有Key');form.addRow('API Key',self.key_input)
        self.persist=QCheckBox('保存到系统安全凭据库');self.persist.setChecked(sys.platform=='win32');form.addRow(self.persist)
        self.reduce_motion=QCheckBox('减少动态效果');self.reduce_motion.setChecked(self.store.setting('reduced_motion','0')=='1');form.addRow(self.reduce_motion)
        self.background=QCheckBox('关闭后留在后台托盘');self.background.setChecked(self.store.setting('background','0')=='1');self.background.setEnabled(QSystemTrayIcon.isSystemTrayAvailable());form.addRow(self.background)
        self.autostart=QCheckBox('登录Windows后启动');self.autostart.setChecked(self.store.setting('autorun','0')=='1');self.autostart.setEnabled(sys.platform=='win32');form.addRow(self.autostart)
        scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setWidget(form_widget);self.layout.addWidget(scroll);self.toolbar([('获取模型',self.get_models),('保存设置',self.save_settings),('备份完整资料',self.backup),('恢复备份',self.restore)])
        self.layout.addWidget(label('数据目录：'+str(self.store.root)+'\n点击保存即写入数据库。每日自动备份含数据库与附件，保留30份；不含API Key。\n门槛是可调整的经营规则，不是统计显著性。\nOCR需要Tesseract及chi_sim、eng模型，截图仅本地识别。'));self.layout.addStretch()
    def save_settings(self):
        values={k:w.currentText() if isinstance(w,QComboBox) else w.text().strip() for k,w in self.config.items()};endpoint(values['api_base'])
        for k in ('min_spend','min_orders','target_ratio'):
            n=float(values[k])
            if not math.isfinite(n) or n<=0 or (k=='min_orders' and not n.is_integer()):raise ValueError('门槛必须是正数，订单应为整数')
            if k=='min_orders':values[k]=str(int(n))
        validate_rules({k:values['grade_'+k] for k in DEFAULTS})
        key=self.key_input.text().strip()
        if key:
            if self.persist.isChecked():save_key(key)
            self.runtime_key=key
        if sys.platform=='win32':autorun(self.autostart.isChecked())
        values.update(background=int(self.background.isChecked()),autorun=int(self.autostart.isChecked()),reduced_motion=int(self.reduce_motion.isChecked()));QApplication.instance().setProperty('reducedMotion',self.reduce_motion.isChecked());self.store.settings(values);self.key_input.clear();message(self,'设置已保存')
    def get_models(self):
        if self.worker and self.worker.isRunning():raise ValueError('请等待当前AI请求结束')
        self.worker=AIWorker(self.config['api_base'].text(),self.key_input.text().strip() or self.runtime_key or api_key(),parent=self)
        self.worker.finished.connect(self.finish_pending_close);self.worker.result.connect(self.got_models);self.worker.failed.connect(lambda t:message(self,t));self.worker.start()
    def got_models(self,models):
        if self.nav.currentRow()!=8:return
        self.config['model'].clear();self.config['model'].addItems(models);message(self,'请选择模型并保存设置')
    def configure_ai_task(self,*args):
        grading=self.ai_task.currentText()=='三档选品推荐'
        self.question.setEnabled(not grading)
        self.question.setPlaceholderText('选择图书后按规则推荐；如需追问，切换“简短问答”。' if grading else '输入一个具体问题，默认只回答结论与简短理由。')
        self.ai_send.setText('按三档规则推荐' if grading else '核对后发送给AI')
    def toggle_ai_answer(self):
        self.ai_expanded=not self.ai_expanded
        self.ai_output.setPlainText(clean_markdown(self.ai_full_answer if self.ai_expanded else self.ai_brief_answer))
        self.ai_expand.setText('收起回答' if self.ai_expanded else '展开完整回答')
        effect=QGraphicsOpacityEffect(self.ai_output);self.ai_output.setGraphicsEffect(effect);self.answer_fade=QPropertyAnimation(effect,b'opacity',self);self.answer_fade.setDuration(0 if reduced_motion() else DURATION);self.answer_fade.setStartValue(.94);self.answer_fade.setEndValue(1);self.answer_fade.start()
    def show_ai_answer(self,text,short=True):
        self.ai_full_answer=text;self.ai_expanded=False
        lines=[x.strip() for x in text.splitlines() if x.strip()]
        too_long=short and (len(text)>200 or len(lines)>4)
        self.ai_brief_answer=('\n'.join(lines[:2])[:180]+'\n（较长回复已折叠，可展开查看）') if too_long else text
        self.ai_output.setPlainText(clean_markdown(self.ai_brief_answer));self.ai_expand.setVisible(too_long);self.ai_expand.setText('展开完整回答')
    def ask_ai(self):self.guarded(self.send_ai)
    def send_ai(self):
        if self.worker and self.worker.isRunning():raise ValueError('请等待当前请求完成')
        if self.ai_task.currentText()=='三档选品推荐':
            results=self.store.grading_results(self.ai_scope.currentData())
            if len(results)>10:raise ValueError('请先选择具体图书，每次最多推荐10个商品，避免冗长回复。')
            reply=render_grades(results);self.show_ai_answer(reply,short=False)
            with self.store.db:self.store.db.execute('INSERT INTO ai_analysis_history(created,task,context,response,status) VALUES (?,?,?,?,?)',(today(),'三档选品推荐',encode({'rules':self.store.grading_rules(),'results':results}),reply,'固定规则推荐'))
            return
        key=self.runtime_key or api_key()
        if not key:raise ValueError('请在设置配置API Key；本地功能无需Key')
        context=encode_pretty(self.store.context(self.ai_scope.currentData()));question=self.ai_task.currentText()+'\n'+self.question.toPlainText()
        messages=[{'role':'system','content':SYSTEM},{'role':'user','content':question+'\n以下是本地资料引用：\n'+context}]
        if len(encode(messages))>300000:raise ValueError('历史上下文过大，未发送或截断资料')
        d=QDialog(self);d.setWindowTitle('确认发送给DeepSeek的完整文本');d.resize(900,700);layout=QVBoxLayout(d);t=QTextEdit();t.setReadOnly(True);t.setPlainText(encode_pretty(messages));layout.addWidget(t)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel);buttons.accepted.connect(d.accept);buttons.rejected.connect(d.reject);layout.addWidget(buttons)
        if not d.exec():return
        with self.store.db:self.ai_id=self.store.db.execute('INSERT INTO ai_analysis_history(created,task,context,response,status) VALUES (?,?,?,?,?)',(today(),question,context,'','请求中')).lastrowid
        self.worker=AIWorker(self.store.setting('api_base','https://api.deepseek.com'),key,self.store.setting('model'),messages,self)
        self.worker.finished.connect(self.finish_pending_close);self.worker.result.connect(self.ai_done);self.worker.failed.connect(self.ai_failed);self.worker.finished.connect(lambda:(self.ai_send.setEnabled(True),self.configure_ai_task()));self.ai_send.setEnabled(False);self.ai_send.setText('正在生成…');self.statusBar().showMessage('正在生成简短回答，当前内容已保留');self.worker.start()
    def ai_done(self,text):
        with self.store.db:self.store.db.execute('UPDATE ai_analysis_history SET response=?,status=? WHERE id=?',(text,'完成',self.ai_id))
        self.show_ai_answer(text,short=not any(word in self.question.toPlainText() for word in ('详细','展开','完整报告')))
    def ai_failed(self,text):
        with self.store.db:self.store.db.execute('UPDATE ai_analysis_history SET response=?,status=? WHERE id=?',(text,'失败',self.ai_id))
        self.ai_output.setPlainText(text)
    def backup(self):
        p,_=QFileDialog.getSaveFileName(self,'备份数据库与所有附件','图书工作台备份.zip','ZIP (*.zip)')
        if p:self.store.backup(p);message(self,'备份成功，不包含API Key')
    def restore(self):
        if self.worker and self.worker.isRunning():raise ValueError('请先等待AI请求结束')
        if self.monitor.busy():raise ValueError('请先等待账号检查结束再恢复资料')
        if self.backup_worker and self.backup_worker.isRunning():raise ValueError('自动备份正在进行，请稍后恢复资料')
        p,_=QFileDialog.getOpenFileName(self,'恢复完整资料包','','ZIP (*.zip)')
        if p and confirm(self,'恢复资料','将替换当前资料。恢复前会自动备份，便于撤回。','恢复资料'):
            safety=self.store.restore(p);self.refresh();message(self,'恢复前备份：'+str(safety))
    def maintain(self):
        if self.quitting:return
        try:
            if not (self.store.root/'backups'/('auto-'+today()+'.zip')).exists() and (not self.backup_worker or not self.backup_worker.isRunning()):
                self.backup_worker=BackupWorker(self.store.root,self);self.backup_worker.failed.connect(lambda text:self.statusBar().showMessage(text));self.backup_worker.finished.connect(self.finish_pending_close);self.backup_worker.start()
            for kind,items in self.store.reminders().items():
                for r in items:
                    if r['剩余天数']>0:continue
                    key='notice:'+kind+':'+str(r.get('product_id',r.get('video_id')));stamp=today()+':'+r['due']
                    if self.store.setting(key)==stamp:continue
                    if self.tray.isVisible() and QSystemTrayIcon.supportsMessages():
                        self.tray.showMessage(kind,r['名称']+' 已到期，请更新数据',QSystemTrayIcon.MessageIcon.Information,10000);self.store.settings({key:stamp})
        except Exception as exc:self.statusBar().showMessage('自动维护失败：'+str(exc))
    def workers_busy(self):
        return self.monitor.busy() or bool(self.worker and self.worker.isRunning()) or bool(self.backup_worker and self.backup_worker.isRunning())
    def finish_pending_close(self):
        if self.pending_quit and not self.workers_busy():QTimer.singleShot(0,self.close)
    def quit_app(self):
        self.quitting=True;self.close()
    def closeEvent(self,event):
        if not self.quitting and self.store.setting('background','0')=='1' and self.tray.isVisible():self.hide();event.ignore();return
        if self.workers_busy():
            self.pending_quit=True;self.quitting=True
            if self.monitor.busy():self.monitor.worker.requestInterruption()
            event.ignore();toast(self,'正在结束后台任务，完成后会自动退出。');return
        self.timer.stop();self.monitor.timer.stop();self.tray.hide();event.accept()
