from __future__ import annotations
import json
import os
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

from PySide6.QtCore import Qt, QDate, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QColor, QDesktopServices, QIcon, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDateEdit, QDialog, QDialogButtonBox,
    QDoubleSpinBox, QFileDialog, QFormLayout, QFrame, QHBoxLayout, QHeaderView, QInputDialog,
    QLabel, QLineEdit, QListWidget, QMainWindow, QMenu, QMessageBox, QPushButton,
    QScrollArea, QSpinBox, QSplitter, QStyle, QSystemTrayIcon, QTabWidget,
    QTableWidget, QTableWidgetItem, QTextBrowser, QTextEdit, QVBoxLayout, QWidget,
)
from .ai import AIWorker, SYSTEM, api_key, save_api_key
from .schema import BUSINESSES, FLOWERS, SALON, SCHEMAS, REALIZED
from .store import fen, yuan

STYLE = '''
QWidget { font-family: "Microsoft YaHei UI", "Noto Sans CJK SC", sans-serif; font-size: 13px; color: #303a36; }
QMainWindow, QDialog { background: #f7f8f7; }
QListWidget#navigation { background: #edf0ee; border: none; padding: 12px 6px; outline: 0; }
QListWidget#navigation::item { padding: 12px 8px; margin: 2px; border-radius: 6px; }
QListWidget#navigation::item:selected { background: #dde9e1; color: #226444; font-weight: 600; }
QLabel#heading { font-size: 23px; font-weight: 600; padding: 8px 0; }
QLabel#muted { color: #6b7871; }
QFrame#card { background: white; border: 1px solid #e0e5e2; border-radius: 8px; padding: 14px; }
QPushButton { padding: 7px 12px; background: white; border: 1px solid #d4dcd6; border-radius: 5px; }
QPushButton:hover { background: #eaf2ed; }
QPushButton#primary { background: #327557; color: white; border: none; }
QPushButton:disabled { color: #a0aaa4; background: #eef0ef; }
QLineEdit, QComboBox, QDateEdit, QSpinBox, QDoubleSpinBox, QTextEdit { background: white; border: 1px solid #d6ded9; border-radius: 4px; padding: 5px; }
QTableWidget { background: white; border: 1px solid #e0e5e2; gridline-color: #edf0ee; selection-background-color: #dcebe1; selection-color: #24573b; }
QHeaderView::section { background: #eff3f0; padding: 9px; border: none; border-bottom: 1px solid #dce3de; font-weight: 600; }
QTabWidget::pane { border: none; }
QTabBar::tab { padding: 10px 14px; background: #edf0ee; }
QTabBar::tab:selected { background: white; color: #25724c; }
QTextBrowser { background: white; border: 1px solid #e0e5e2; padding: 10px; }
QSplitter::handle { background: #e5eae6; width: 3px; }
'''

def button(text, slot, primary=False):
    widget=QPushButton(text)
    if primary:
        widget.setObjectName('primary')
    widget.clicked.connect(slot)
    return widget

def info(parent, text):
    QMessageBox.information(parent,'造物手作',text)

def fail(parent, exc):
    QMessageBox.warning(parent,'操作未完成',str(exc))

def confirm(parent, text):
    return QMessageBox.question(parent,'请确认',text,QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)==QMessageBox.StandardButton.Yes

def browser(text=''):
    widget=QTextBrowser()
    widget.setOpenExternalLinks(False)
    widget.setOpenLinks(False)
    widget.setMarkdown(text)
    return widget

class RecordDialog(QDialog):
    def __init__(self, store, table, record=None, filters=None, parent=None):
        super().__init__(parent)
        self.store=store
        self.table=table
        self.record=record or {}
        self.filters=filters or {}
        self.inputs={}
        self.result_id=None
        self.setWindowTitle(('编辑' if record else '新增')+' · '+SCHEMAS[table][0])
        self.resize(600,760)
        outer=QVBoxLayout(self)
        scroll=QScrollArea()
        scroll.setWidgetResizable(True)
        content=QWidget()
        form=QFormLayout(content)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        for field in SCHEMAS[table][1]:
            value=self.record.get(field.key,self.filters.get(field.key))
            if field.kind=='choice':
                widget=QComboBox()
                options=field.options
                if table=='orders' and field.key=='status':
                    business=self.filters.get('business',self.record.get('business',BUSINESSES[0]))
                    options=FLOWERS if business=='花束业务' else SALON if business=='活动沙龙' else ('已付款','已完成','已取消')
                widget.addItems(options)
                if value in options:
                    widget.setCurrentText(value)
            elif field.kind in ('product','customer'):
                widget=QComboBox()
                widget.addItem('未关联',None)
                target='products' if field.kind=='product' else 'customers'
                rows=store.rows(target)
                for row in rows:
                    if target=='products' and self.filters.get('business') and row['business']!=self.filters['business']:
                        continue
                    label=row['name'] if target=='products' else row['code']
                    widget.addItem(f"#{row['id']} · {label}",row['id'])
                index=widget.findData(value)
                if index>=0:
                    widget.setCurrentIndex(index)
            elif field.kind=='bool':
                widget=QCheckBox('是')
                widget.setChecked(bool(value) if value is not None else table=='products' and field.key=='active')
            elif field.kind in ('money','number'):
                widget=QDoubleSpinBox()
                widget.setRange(0,999999999)
                widget.setDecimals(2)
                widget.setValue((value or 0)/100 if field.kind=='money' else value or 0)
                if field.kind=='money':
                    widget.setSuffix(' 元')
            elif field.kind=='int':
                widget=QSpinBox()
                widget.setRange(0,100000000)
                widget.setValue(value if value is not None else 1 if field.key in ('quantity','people') else 0)
            elif field.kind=='date':
                widget=QDateEdit()
                widget.setCalendarPopup(True)
                widget.setDisplayFormat('yyyy-MM-dd')
                widget.setDate(QDate.fromString(value,'yyyy-MM-dd') if value else QDate.currentDate())
            elif field.kind=='long':
                widget=QTextEdit()
                widget.setAcceptRichText(False)
                widget.setMinimumHeight(80)
                widget.setMaximumHeight(150)
                widget.setPlainText(value or '')
            else:
                widget=QLineEdit(str(value or ''))
                if field.kind=='optional_date':
                    widget.setPlaceholderText('YYYY-MM-DD，可留空')
            if field.key in self.filters:
                widget.setEnabled(False)
            self.inputs[field.key]=widget
            form.addRow(field.label+(' *' if field.required else ''),widget)
        scroll.setWidget(content)
        outer.addWidget(scroll)
        if table=='orders':
            outer.addWidget(QLabel('收入、成本填写整单金额；仅已成交 / 已付款阶段计入经营统计。'))
            outer.addWidget(button('按产品单价 × 件数填充收入及材料成本',self.fill_price))
        self.errors=QLabel()
        self.errors.setWordWrap(True)
        self.errors.setStyleSheet('color: #a04732')
        outer.addWidget(self.errors)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

    def fill_price(self):
        pid=self.inputs['product_id'].currentData()
        rows=self.store.rows('products',{'id':pid}) if pid else []
        if not rows:
            self.errors.setText('请先选择产品')
            return
        quantity=self.inputs['quantity'].value()
        self.inputs['revenue'].setValue(rows[0]['price']*quantity/100)
        self.inputs['expected'].setValue(rows[0]['price']*quantity/100)
        self.inputs['material'].setValue(rows[0]['material']*quantity/100)

    def values(self):
        result={}
        for field in SCHEMAS[self.table][1]:
            w=self.inputs[field.key]
            if field.kind=='choice': value=w.currentText()
            elif field.kind in ('product','customer'): value=w.currentData()
            elif field.kind=='bool': value=int(w.isChecked())
            elif field.kind in ('money','number','int'): value=fen(w.value()) if field.kind=='money' else w.value()
            elif field.kind=='date': value=w.date().toString('yyyy-MM-dd')
            elif field.kind=='long': value=w.toPlainText()
            else: value=w.text()
            result[field.key]=value
        return result

    def save(self):
        try:
            self.result_id=self.store.save(self.table,self.values(),self.record.get('id'))
            self.accept()
        except (ValueError,sqlite3.Error,ArithmeticError) as exc:
            self.errors.setText(str(exc))

class RecordsPage(QWidget):
    changed=Signal()

    def __init__(self, store, table, filters=None):
        super().__init__()
        self.store=store
        self.table=table
        self.filters=filters or {}
        self.records=[]
        layout=QVBoxLayout(self)
        tools=QHBoxLayout()
        self.search=QLineEdit()
        self.search.setPlaceholderText('搜索当前列表…')
        self.search.textChanged.connect(self.refresh)
        tools.addWidget(self.search,1)
        tools.addWidget(button('新增',self.add,True))
        tools.addWidget(button('编辑',self.edit))
        tools.addWidget(button('删除',self.remove))
        tools.addWidget(button('详情',self.details))
        layout.addLayout(tools)
        files=QHBoxLayout()
        files.addWidget(button('导出 CSV / Excel',self.export))
        files.addWidget(button('导出导入模板',lambda:self.export(template=True)))
        files.addWidget(button('导入 CSV / Excel',self.import_data))
        if table=='assets':
            files.addWidget(button('导入照片',self.photo))
            files.addWidget(button('查看照片',self.view_photo))
        if table=='orders' and self.filters.get('business')=='活动沙龙':
            files.addWidget(button('导出报价单',self.quote))
        files.addStretch()
        layout.addLayout(files)
        self.table_widget=QTableWidget()
        self.table_widget.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table_widget.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table_widget.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table_widget.setAlternatingRowColors(True)
        self.table_widget.cellDoubleClicked.connect(self.edit)
        self.table_widget.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table_widget.horizontalHeader().setDefaultSectionSize(140)
        layout.addWidget(self.table_widget,1)
        self.footer=QLabel()
        self.footer.setWordWrap(True)
        self.footer.setObjectName('muted')
        layout.addWidget(self.footer)
        self.refresh()

    def refresh(self):
        rows=self.store.rows(self.table,self.filters)
        query=self.search.text().casefold()
        self.records=[r for r in rows if not query or query in ' '.join(str(v) for v in r.values()).casefold()]
        fields=SCHEMAS[self.table][1]
        extra='单件材料毛利' if self.table=='products' else '贡献毛利' if self.table=='orders' else '消费统计' if self.table=='customers' else None
        headers=['编号']+[f.label for f in fields]+([extra] if extra else [])
        self.table_widget.setColumnCount(len(headers))
        self.table_widget.setHorizontalHeaderLabels(headers)
        self.table_widget.setRowCount(len(self.records))
        for index,row in enumerate(self.records):
            values=[str(row['id'])]
            for field in fields:
                v=row[field.key]
                if field.kind=='money': v='¥ '+yuan(v)
                elif field.kind=='bool': v='是' if v else '否'
                elif field.kind in ('product','customer') and v:
                    target='products' if field.kind=='product' else 'customers'
                    linked=self.store.rows(target,{'id':v})
                    v=linked[0]['name' if target=='products' else 'code'] if linked else '关联已失效'
                values.append(str(v) if v is not None else '未关联')
            if self.table=='products': values.append('¥ '+yuan(row['price']-row['material']))
            if self.table=='orders': values.append('¥ '+yuan(row['revenue']-row['material']-row['labor']-row['other']))
            if self.table=='customers': values.append(json.dumps(self.store.customer_stats(row['id']),ensure_ascii=False))
            for col,value in enumerate(values):
                item=QTableWidgetItem(value.replace('\n',' ')[:220])
                item.setToolTip(value)
                self.table_widget.setItem(index,col,item)
        footer=f'共 {len(self.records)} 条记录。双击编辑；完整长文本请打开详情。'
        if not rows: footer+=' 暂无数据，请新增或导入；系统不填充示例经营数据。'
        if self.table=='inventory': footer+=' 当前库存：'+json.dumps(self.store.inventory_balance(),ensure_ascii=False)+'；负数表示缺少入库或录入不一致，请核对。'
        if self.table=='assets': footer+=' 图片仅本地保存；当前 AI 使用经确认的文字描述，不上传图像、不声称具备视觉识别。'
        if self.table=='orders': footer+=' 日期为经营归属日；未成交阶段不计营业额，已取消不计统计。'
        self.footer.setText(footer)

    def selected(self):
        row=self.table_widget.currentRow()
        if 0<=row<len(self.records): return self.records[row]
        info(self,'请先选择一条记录')
        return None

    def add(self):
        if self.table=='assets':
            self.photo()
            return
        dialog=RecordDialog(self.store,self.table,filters=self.filters,parent=self)
        if dialog.exec(): self.updated()

    def edit(self,*_):
        row=self.selected()
        if row:
            dialog=RecordDialog(self.store,self.table,row,self.filters,self)
            if dialog.exec(): self.updated()

    def remove(self):
        row=self.selected()
        if row and confirm(self,'永久删除所选记录？关联产品 / 客户被订单引用时会阻止删除，建议下架产品。'):
            try:
                self.store.delete(self.table,row['id'])
                self.updated()
            except Exception as exc: fail(self,exc)

    def updated(self):
        self.refresh()
        self.changed.emit()

    def details(self):
        row=self.selected()
        if not row: return
        dialog=QDialog(self)
        dialog.setWindowTitle('记录详情')
        dialog.resize(650,650)
        layout=QVBoxLayout(dialog)
        text=[]
        for f in SCHEMAS[self.table][1]:
            value=yuan(row[f.key])+' 元' if f.kind=='money' else row[f.key]
            text.append(f'### {f.label}\n\n{value}\n')
        layout.addWidget(browser('\n'.join(text)))
        layout.addWidget(button('关闭',dialog.accept))
        dialog.exec()

    def export(self,template=False):
        target,_=QFileDialog.getSaveFileName(self,'导出模板' if template else '导出数据',self.table+('-template' if template else '')+'.xlsx','Excel (*.xlsx);;CSV (*.csv)')
        if target:
            try:
                count=self.store.export_file(self.table,target,self.filters,template)
                info(self,f'已导出 {count} 条记录。导入字段采用英文列名；金额单位为元，关联客户和产品使用本库编号。')
            except Exception as exc: fail(self,exc)

    def import_data(self):
        source,_=QFileDialog.getOpenFileName(self,'导入（请先导出模板）','','Excel / CSV (*.xlsx *.csv)')
        if source and confirm(self,'按模板字段新增记录，不覆盖已有记录。重复导入会新增重复记录；客户编号重复或任一行错误会整批回滚。是否继续？'):
            try:
                self.store.backup()
                count=self.store.import_file(self.table,source,self.filters)
                self.updated()
                info(self,f'成功导入 {count} 条记录')
            except Exception as exc: fail(self,exc)

    def photo(self):
        source,_=QFileDialog.getOpenFileName(self,'选择照片','','图片 (*.png *.jpg *.jpeg *.webp *.bmp)')
        if source:
            try:
                from PySide6.QtGui import QImageReader
                if not QImageReader(source).canRead(): raise ValueError('文件不是受支持的有效图片')
                self.store.import_photo(source,Path(source).stem,self.filters.get('business',BUSINESSES[0]))
                self.updated()
            except Exception as exc: fail(self,exc)

    def view_photo(self):
        row=self.selected()
        if not row: return
        from PySide6.QtGui import QPixmap
        pixmap=QPixmap(row['path'])
        if pixmap.isNull():
            fail(self,'照片不存在或格式损坏')
            return
        dialog=QDialog(self)
        dialog.resize(800,650)
        layout=QVBoxLayout(dialog)
        label=QLabel()
        label.setPixmap(pixmap.scaled(760,560,Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation))
        layout.addWidget(label)
        layout.addWidget(button('关闭',dialog.accept))
        dialog.exec()

    def quote(self):
        row=self.selected()
        if not row: return
        target,_=QFileDialog.getSaveFileName(self,'导出报价单','造物活动报价单.md','Markdown (*.md)')
        if target:
            text=f"# 造物手作 · 活动报价单\n\n订单编号：{row['id']}\n\n活动：{row['activity']}\n\n时间：{row['delivery']}\n\n地点：{row['location']}\n\n人数：{row['people']}\n\n预计报价：¥{yuan(row['expected'])}\n\n本报价不代表收款或成交，请双方确认。\n"
            try: Path(target).write_text(text,encoding='utf-8')
            except OSError as exc: fail(self,exc)

class TrendChart(QWidget):
    def __init__(self, trend):
        super().__init__()
        self.trend=trend
        self.setMinimumHeight(190)

    def paintEvent(self,event):
        painter=QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(),QColor('white'))
        painter.setPen(QColor('#718076'))
        painter.drawText(16,22,'营业额趋势 · 元（所选日期范围，空白日按 0 元绘图）')
        if not self.trend:
            painter.drawText(25,100,'暂无已成交订单，请先录入真实数据')
            return
        values=list(self.trend.values())
        peak=max(values) or 1
        left,bottom,width,height=65,self.height()-35,self.width()-90,self.height()-85
        painter.setPen(QPen(QColor('#dce4de'),1))
        painter.drawLine(left,bottom,left+width,bottom)
        painter.drawText(5,55,f'{peak/100:,.0f}')
        points=[]
        for i,value in enumerate(values):
            x=left+width*i/max(1,len(values)-1)
            y=bottom-height*value/peak
            points.append((int(x),int(y)))
        painter.setPen(QPen(QColor('#367654'),2))
        for a,b in zip(points,points[1:]): painter.drawLine(*a,*b)
        for x,y in points: painter.drawEllipse(x-2,y-2,4,4)
        painter.setPen(QColor('#718076'))
        painter.drawText(left,bottom+24,list(self.trend)[0])
        painter.drawText(max(left,self.width()-100),bottom+24,list(self.trend)[-1])

class AnalysisPage(QWidget):
    def __init__(self,store,today=False):
        super().__init__()
        self.store=store
        self.today=today
        outer=QVBoxLayout(self)
        controls=QHBoxLayout()
        self.start=QDateEdit(QDate.currentDate().addDays(1-QDate.currentDate().day()))
        self.end=QDateEdit(QDate.currentDate())
        for w in (self.start,self.end): w.setCalendarPopup(True); w.setDisplayFormat('yyyy-MM-dd')
        self.business=QComboBox()
        self.business.addItems(('全部业务',)+BUSINESSES)
        self.period=QComboBox()
        self.period.addItems(('本月','今日','本周','今年','最近7天','最近30天'))
        self.period.currentTextChanged.connect(self.choose_period)
        controls.addWidget(self.period)
        controls.addWidget(self.start)
        controls.addWidget(QLabel('至'))
        controls.addWidget(self.end)
        controls.addWidget(self.business)
        controls.addWidget(button('分析',self.refresh,True))
        outer.addLayout(controls)
        self.scroll=QScrollArea()
        self.scroll.setWidgetResizable(True)
        outer.addWidget(self.scroll,1)
        self.refresh()

    def choose_period(self,period):
        today=QDate.currentDate()
        start={'本月':today.addDays(1-today.day()),'今日':today,'本周':today.addDays(1-today.dayOfWeek()),'今年':QDate(today.year(),1,1),'最近7天':today.addDays(-6),'最近30天':today.addDays(-29)}[period]
        self.start.setDate(start)
        self.end.setDate(today)
        self.refresh()

    def refresh(self):
        start=self.start.date().toString('yyyy-MM-dd')
        end=self.end.date().toString('yyyy-MM-dd')
        business=self.business.currentText()
        try:
            s=self.store.summary(start,end,None if business=='全部业务' else business)
        except ValueError as exc:
            fail(self,exc)
            return
        old=self.scroll.takeWidget()
        if old: old.deleteLater()
        body=QWidget()
        layout=QVBoxLayout(body)
        cards=QHBoxLayout()
        for title,value in [('营业额','¥ '+yuan(s['revenue'])),('成交订单',str(s['orders'])),('贡献毛利','¥ '+yuan(s['contribution'])),('毛利率',f"{s['margin']}%" if s['margin'] is not None else '暂无数据')]:
            card=QFrame()
            card.setObjectName('card')
            cl=QVBoxLayout(card)
            cl.addWidget(QLabel(title))
            label=QLabel(value)
            label.setStyleSheet('font-size: 22px; font-weight: 600; color: #2b6246')
            cl.addWidget(label)
            cards.addWidget(card)
        layout.addLayout(cards)
        dates={}
        current=date.fromisoformat(start)
        while current<=date.fromisoformat(end):
            dates[str(current)]=s['trend'].get(str(current),0)
            current+=timedelta(days=1)
            if len(dates)>3660: break
        layout.addWidget(TrendChart(dates if s['orders'] else {}))
        days=(date.fromisoformat(end)-date.fromisoformat(start)).days+1
        prev_end=date.fromisoformat(start)-timedelta(days=1)
        prev=self.store.summary(str(prev_end-timedelta(days=days-1)),str(prev_end),None if business=='全部业务' else business)
        change=f"{(s['revenue']-prev['revenue'])/prev['revenue']*100:+.1f}%" if prev['revenue'] else '上期为零，不计算增长率'
        details=f"## 经营口径\n\n- 与前一等长周期比较：营业额 {change}；上期 ¥{yuan(prev['revenue'])}\n- 材料成本 ¥{yuan(s['material'])}；直接人工及其他成本 ¥{yuan(s['direct'])}\n- 客单价 ¥{yuan(s['aov'])}；已关联成交客户 {s['customers']} 位；首次成交客户 {s['new_customers']} 位；复购订单 {s['repeat_orders']} 笔\n- 未关联客户的成交订单 {s['unlinked_orders']} 笔，不推断客户人数\n"
        if s['fixed'] is not None:
            details+=f"- 已录固定费用 ¥{yuan(s['fixed'])}；扣除已录费用后结余 ¥{yuan(s['net_after_recorded_expenses'])}（费用不完整时不能视为最终净利润）\n"
        details+='\n## 三项业务收入\n\n| 业务 | 收入 | 占比 |\n|---|---:|---:|\n'
        for b,value in s['by_business'].items(): details+=f"| {b} | ¥{yuan(value)} | {value/s['revenue']*100 if s['revenue'] else 0:.1f}% |\n"
        details+='\n## 产品销售与贡献毛利\n\n| 产品 | 件数 / 组数 | 营业额 | 贡献毛利 |\n|---|---:|---:|---:|\n'
        products={str(r['id']):r['name'] for r in self.store.rows('products')}
        for pid,v in s['products'].items(): details+=f"| {products.get(pid,pid)} | {v['quantity']} | ¥{yuan(v['revenue'])} | ¥{yuan(v['contribution'])} |\n"
        details+='\n## 来源与渠道（分别统计，不混为一谈）\n\n首次获客来源：'+json.dumps(s['sources'],ensure_ascii=False)+'\n\n最终下单渠道：'+json.dumps(s['channels'],ensure_ascii=False)
        campaigns=[r for r in self.store.rows('campaigns') if start<=r['date']<=end and (business=='全部业务' or r['business']==business)]
        details+='\n\n## 营销漏斗\n\n| 实验 | 曝光 | 访问 | 咨询 | 订单 | 获客订单成本 |\n|---|---:|---:|---:|---:|---:|\n'
        for r in campaigns:
            cac='¥ '+yuan(round(r['spent']/r['conversions'])) if r['conversions'] else '暂无成交，不计算'
            details+=f"| {r['title']} | {r['exposures']} | {r['visits']} | {r['inquiries']} | {r['conversions']} | {cac} |\n"
        salon=[r for r in self.store.rows('orders') if r['business']=='活动沙龙' and start<=r['date']<=end and r['status']!='已取消']
        details+='\n## 活动销售漏斗（当前阶段）\n\n'+ '\n'.join(f'- {stage}：{sum(r["status"]==stage for r in salon)}' for stage in SALON if stage!='已取消')
        closed=sum(r['status'] in REALIZED for r in salon)
        details+=f'\n\n成交 / 全部非取消活动线索：{closed} / {len(salon)}（这是录入线索的阶段转化比例，不代表完整获客转化率）。'
        if self.today:
            yesterday=date.today()-timedelta(days=1)
            y=self.store.summary(str(yesterday),str(yesterday))
            tasks=[r for r in self.store.rows('tasks') if r['status'] not in ('已完成','已取消')]
            details=f"## 今日工作 · 30～50 分钟\n\n昨日营业额 ¥{yuan(y['revenue'])}，成交 {y['orders']} 单。\n\n1. 核对昨日订单和成本（10 分钟）\n2. 查看经营对比并请求 AI 诊断（10 分钟）\n3. 从营销实验选择一个行动，完成内容或客户维护计划（15 分钟）\n4. 记录执行结果与每日复盘（10 分钟）\n\n待处理任务 {len(tasks)} 项；请在下方任务标签管理。没有足够数据时不推断经营问题。\n\n"+details
            reminders=[]
            if not s['orders']:
                reminders.append('本期尚无已成交订单：先核对是否录入完整，不能据此认定门店没有营业。')
            elif prev['revenue'] and s['revenue']<prev['revenue']:
                reminders.append('本期营业额低于前一等长周期：先检查曝光、访问、咨询、成交的记录是否齐全，再选择下降环节设计实验。')
            if s['unlinked_orders']:
                reminders.append(f"有 {s['unlinked_orders']} 笔订单未关联匿名客户，客户增长和复购分析可能不完整。")
            for campaign in campaigns:
                if campaign['spent'] and not campaign['conversions']:
                    reminders.append(f"实验「{campaign['title']}」已记录花费但暂无获客订单：先检查咨询、成交归因和观察周期，不直接断定实验失败。")
            overdue=[t for t in tasks if t['deadline']<str(date.today())]
            if overdue: reminders.append(f'有 {len(overdue)} 项未完成任务已超过截止日期，请更新执行结果。')
            details='## 本地规则提醒（非 AI 生成）\n\n'+('\n'.join('- '+r for r in reminders[:3]) if reminders else '当前未命中提醒规则，不代表不存在经营问题。可在右侧请求基于数据的 DeepSeek 诊断。')+'\n\n'+details
        view=browser(details)
        view.setMinimumHeight(650)
        layout.addWidget(view)
        layout.addStretch()
        self.scroll.setWidget(body)

class ReportsPage(QWidget):
    def __init__(self,store):
        super().__init__()
        self.store=store
        layout=QVBoxLayout(self)
        layout.addWidget(QLabel('自动保存上个完整周 / 月的统计快照；AI 解读需主动发起并确认发送数据。'))
        self.list=QComboBox()
        self.view=browser()
        layout.addWidget(self.list)
        layout.addWidget(self.view,1)
        self.list.currentIndexChanged.connect(self.show_report)
        layout.addWidget(button('刷新快照',self.refresh))
        layout.addWidget(button('导出当前报告',self.export))
        self.refresh()

    def refresh(self):
        self.store.reports_due()
        self.list.clear()
        for r in self.store.db.execute('SELECT * FROM reports ORDER BY end DESC'):
            self.list.addItem(f"{r['period']} · {r['start']} — {r['end']}",r['body'])
        self.show_report()

    def show_report(self,*_):
        text=self.list.currentData() or '{}'
        self.view.setMarkdown('## 本地经营统计快照\n\n金额单位：分。没有交易时为 0，不能解释为漏录或没有营业。\n\n```json\n'+text+'\n```')

    def export(self):
        target,_=QFileDialog.getSaveFileName(self,'导出报告','经营统计报告.md','Markdown (*.md)')
        if target:
            try: Path(target).write_text(self.view.toMarkdown(),encoding='utf-8')
            except OSError as exc: fail(self,exc)

class ChatPanel(QWidget):
    def __init__(self,window):
        super().__init__()
        self.window=window
        self.store=window.store
        self.worker=None
        self.message_id=None
        self.buffer=''
        self.runtime_key=''
        self.context={}
        self.setMinimumWidth(290)
        layout=QVBoxLayout(self)
        title=QLabel('DeepSeek · 经营助手')
        title.setStyleSheet('font-size:17px;font-weight:600')
        layout.addWidget(title)
        bar=QHBoxLayout()
        self.sessions=QComboBox()
        self.sessions.currentIndexChanged.connect(self.render)
        bar.addWidget(self.sessions,1)
        self.new_button=button('新会话',self.new_session)
        self.delete_button=button('删除',self.delete_session)
        bar.addWidget(self.new_button)
        bar.addWidget(self.delete_button)
        layout.addLayout(bar)
        extra=QHBoxLayout()
        extra.addWidget(button('重命名会话',self.rename_session))
        save_menu=QMenu(self)
        for title,table,field in [('保存为内容草稿','contents','body'),('保存为复盘草稿','reviews','findings'),('保存为经营记忆','memories','body')]:
            action=save_menu.addAction(title)
            action.triggered.connect(lambda checked=False,t=table,f=field:self.save_reply(t,f))
        save_button=QPushButton('保存回复…')
        save_button.setMenu(save_menu)
        extra.addWidget(save_button)
        layout.addLayout(extra)
        self.scope=QLabel()
        self.scope.setObjectName('muted')
        self.scope.setWordWrap(True)
        layout.addWidget(self.scope)
        self.view=browser()
        layout.addWidget(self.view,1)
        self.status=QLabel('先在系统设置获取模型；未接入时本地业务功能可正常使用。')
        self.status.setWordWrap(True)
        self.status.setObjectName('muted')
        layout.addWidget(self.status)
        self.input=QTextEdit()
        self.input.setAcceptRichText(False)
        self.input.setFixedHeight(100)
        self.input.setPlaceholderText('结合当前模块提问…（勿输入个人联系方式）')
        layout.addWidget(self.input)
        actions=QHBoxLayout()
        self.send_button=button('发送',self.send,True)
        self.stop_button=button('停止',self.stop)
        self.stop_button.setEnabled(False)
        actions.addWidget(self.send_button)
        actions.addWidget(self.stop_button)
        actions.addWidget(button('建议转任务',self.propose_task))
        layout.addLayout(actions)
        self.timer=QTimer(self)
        self.timer.setInterval(180)
        self.timer.timeout.connect(self.flush)
        self.refresh_sessions()

    def refresh_sessions(self,selected=None):
        self.sessions.blockSignals(True)
        self.sessions.clear()
        for r in self.store.db.execute('SELECT * FROM sessions ORDER BY id DESC'):
            self.sessions.addItem(r['title'],r['id'])
        if not self.sessions.count():
            sid=self.store.new_session()
            self.sessions.addItem('新经营会话',sid)
        if selected:
            self.sessions.setCurrentIndex(self.sessions.findData(selected))
        self.sessions.blockSignals(False)
        self.render()

    def new_session(self):
        self.refresh_sessions(self.store.new_session())

    def rename_session(self):
        if self.worker and self.worker.isRunning(): return
        title,ok=QInputDialog.getText(self,'重命名会话','会话名称',text=self.sessions.currentText())
        if ok and title.strip():
            sid=self.sessions.currentData()
            with self.store.db: self.store.db.execute('UPDATE sessions SET title=? WHERE id=?',(title.strip()[:100],sid))
            self.refresh_sessions(sid)

    def last_reply(self):
        selected=self.view.textCursor().selectedText().replace('\u2029','\n')
        if selected: return selected
        for message in reversed(self.store.messages(self.sessions.currentData())):
            if message['role']=='assistant' and message['status']=='complete': return message['content']
        return ''

    def save_reply(self,table,field):
        text=self.last_reply()
        if not text:
            info(self,'请先生成完整回复，或在聊天记录中选中需要保存的内容。')
            return
        dialog=RecordDialog(self.store,table,parent=self)
        dialog.inputs['title'].setText(self.window.module+' · 请核对标题')
        dialog.inputs[field].setPlainText(text)
        if dialog.exec(): self.window.refresh_pages()

    def delete_session(self):
        sid=self.sessions.currentData()
        if sid and confirm(self,'删除此会话及全部聊天记录？'):
            with self.store.db: self.store.db.execute('DELETE FROM sessions WHERE id=?',(sid,))
            self.refresh_sessions()

    def set_module(self,module):
        self.scope.setText('当前上下文：'+module+' · 每次发送前可查看实际数据范围')

    def render(self,*_):
        sid=self.sessions.currentData()
        if not sid: return
        scroll=self.view.verticalScrollBar()
        previous=scroll.value()
        at_bottom=scroll.maximum()-previous<30
        parts=[]
        for m in self.store.messages(sid):
            label='你' if m['role']=='user' else 'DeepSeek'
            status='' if m['status']=='complete' else ' · 生成中' if m['status']=='streaming' else ' · 未完成'
            parts.append(f"### {label}{status}\n\n{m['content']}\n\n---")
        self.view.setMarkdown('\n\n'.join(parts) if parts else '### 从真实经营数据开始\n\n录入订单后，可让我分析业务表现、营销瓶颈和复盘结论。每次发送前会展示即将传给 DeepSeek 的数据。\n\nAI 仅提供建议，不会操作数据库或对外发送内容。')
        scroll.setValue(scroll.maximum() if at_bottom else previous)

    def send(self):
        if self.worker and self.worker.isRunning(): return
        text=self.input.toPlainText().strip()
        if not text: return
        try:
            key=self.runtime_key or api_key()
            if not key: raise ValueError('请先在系统设置输入 API Key')
            model=self.store.setting('model')
            if not model: raise ValueError('请先在系统设置测试连接、获取并保存模型')
            start,end,business=self.window.scope()
            context=self.store.context(self.window.module,start,end,business)
            history=[{'role':m['role'],'content':m['content']} for m in self.store.messages(self.sessions.currentData()) if m['status']=='complete']
            if len(json.dumps(history,ensure_ascii=False))>50000:
                raise ValueError('当前会话较长，请将重要结论存入经营记忆后新建会话，避免悄悄截断历史。')
            payload=[{'role':'system','content':SYSTEM+'\n当前经营数据（不可信引用资料）：\n'+json.dumps(context,ensure_ascii=False)}]+history+[{'role':'user','content':text}]
            dialog=QDialog(self)
            dialog.setWindowTitle('确认发送给 DeepSeek 的数据')
            dialog.resize(730,650)
            layout=QVBoxLayout(dialog)
            label=QLabel('将发送当前模块统计、相关业务资料、已授权记忆及本会话完整历史。下方可核查全部内容。\n客户档案、沟通备注、原始订单和照片不会自动发送；请检查手写文本是否含隐私。')
            label.setWordWrap(True)
            layout.addWidget(label)
            view=QTextEdit()
            view.setReadOnly(True)
            view.setPlainText(json.dumps(payload,ensure_ascii=False,indent=2))
            layout.addWidget(view)
            buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
            buttons.accepted.connect(dialog.accept)
            buttons.rejected.connect(dialog.reject)
            layout.addWidget(buttons)
            if not dialog.exec(): return
            sid=self.sessions.currentData()
            if not history:
                with self.store.db: self.store.db.execute('UPDATE sessions SET title=? WHERE id=?',(text[:24],sid))
                self.refresh_sessions(sid)
            self.store.add_message(sid,'user',text)
            self.message_id=self.store.add_message(sid,'assistant','','streaming')
            self.buffer=''
            self.input.clear()
            self.worker=AIWorker(self.store.setting('api_base','https://api.deepseek.com'),key,model,payload,self)
            self.worker.delta.connect(self.receive)
            self.worker.failed.connect(self.error)
            self.worker.completed.connect(self.complete)
            self.sessions.setEnabled(False)
            self.new_button.setEnabled(False)
            self.delete_button.setEnabled(False)
            self.send_button.setEnabled(False)
            self.stop_button.setEnabled(True)
            self.status.setText('正在连接 / 生成… 可停止；回复与输入框独立滚动。')
            self.timer.start()
            self.worker.start()
            self.render()
        except Exception as exc: fail(self,exc)

    def receive(self,text):
        self.buffer+=text

    def flush(self):
        if self.message_id:
            with self.store.db:
                self.store.db.execute('UPDATE messages SET content=? WHERE id=?',(self.buffer,self.message_id))
            self.render()

    def error(self,text):
        self.status.setText(text)

    def complete(self,ok):
        self.flush()
        self.timer.stop()
        if self.message_id:
            with self.store.db:
                self.store.db.execute('UPDATE messages SET status=? WHERE id=?',('complete' if ok else 'incomplete',self.message_id))
        self.message_id=None
        self.sessions.setEnabled(True)
        self.new_button.setEnabled(True)
        self.delete_button.setEnabled(True)
        self.send_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        if ok: self.status.setText('回复已保存。AI 建议需由你确认后执行。')
        self.render()

    def stop(self):
        if self.worker: self.worker.cancel()
        self.status.setText('正在停止；网络读取最迟在超时后结束，部分回复会保存。')

    def propose_task(self):
        dialog=RecordDialog(self.store,'tasks',parent=self)
        dialog.inputs['status'].setCurrentText('待确认')
        dialog.inputs['title'].setText('经营助手建议 · 请编辑任务标题')
        dialog.inputs['result'].setPlainText(self.last_reply() or self.input.toPlainText() or '请从 AI 建议中选择具体行动，并填写成功指标。')
        if dialog.exec():
            self.window.refresh_pages()
            info(self,'任务已保存为待确认，不会自动执行。')

class SettingsPage(QWidget):
    def __init__(self,window):
        super().__init__()
        self.window=window
        self.store=window.store
        self.worker=None
        layout=QVBoxLayout(self)
        form=QFormLayout()
        self.base=QLineEdit(self.store.setting('api_base','https://api.deepseek.com'))
        self.key=QLineEdit()
        self.key.setEchoMode(QLineEdit.EchoMode.Password)
        self.key.setPlaceholderText('留空保留现有 Key；不会写入 SQLite')
        self.model=QComboBox()
        self.model.setEditable(False)
        if self.store.setting('model'): self.model.addItem(self.store.setting('model'))
        self.persist=QCheckBox('保存到操作系统安全凭据库（Windows Credential Manager）')
        self.persist.setChecked(sys.platform=='win32')
        self.background=QCheckBox('关闭窗口时最小化到托盘（托盘可用时生效）')
        self.background.setChecked(self.store.setting('background','0')=='1')
        self.autorun=QCheckBox('登录 Windows 时启动（默认关闭）')
        self.autorun.setEnabled(sys.platform=='win32')
        self.autorun.setChecked(self.autorun_enabled())
        form.addRow('官方 API 地址',self.base)
        form.addRow('API Key',self.key)
        form.addRow('',self.persist)
        form.addRow('可用模型（从 API 获取）',self.model)
        form.addRow('',self.background)
        form.addRow('',self.autorun)
        layout.addLayout(form)
        row=QHBoxLayout()
        self.test_button=button('测试连接并获取模型',self.test,True)
        row.addWidget(self.test_button)
        row.addWidget(button('保存设置',self.save))
        layout.addLayout(row)
        self.status=QLabel('尚未进行真实 API 验证；请使用你自己的 DeepSeek Key 测试。模型不预置。')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        layout.addWidget(QLabel('数据目录：'+str(self.store.root)))
        backup_bar=QHBoxLayout()
        backup_bar.addWidget(button('立即备份数据库',self.backup))
        backup_bar.addWidget(button('恢复数据库备份',self.restore))
        backup_bar.addWidget(button('打开数据目录',lambda:QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.store.root)))))
        layout.addLayout(backup_bar)
        notes=browser('''## 数据与隐私

- 数据只保存在本机用户目录；升级程序不会覆盖数据库。
- 自动备份在启动时及运行中每小时检查，每天保留一个备份，自动保留最近 30 个；手工外部备份自行保管。
- **数据库备份仅包含 SQLite，不包含照片或系统凭据。** 完整迁移请同时复制整个数据目录，Key 在新机器重新输入。
- 数据库及备份没有加密；建议使用 Windows 账户权限与 BitLocker 保护电脑。
- 恢复前会验证数据库结构与完整性，并为当前数据库创建安全备份；恢复后建议重启应用。
- AI 只有只读分析能力。不会群发、自动发布、投放广告或自动修改业务数据。
- 照片存储及预览可用。当前没有确认支持图像输入的 DeepSeek 模型，因此仅发送人工填写的照片描述，不上传图片。
- 官方文档：https://api-docs.deepseek.com/ 。当前云网络未允许该站，最新参数兼容性及真实 API 调用仍需用有效 Key 验证。
''')
        layout.addWidget(notes,1)

    @staticmethod
    def autorun_enabled():
        if sys.platform!='win32': return False
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,r'Software\Microsoft\Windows\CurrentVersion\Run') as key:
                winreg.QueryValueEx(key,'ZaowuGrowthManager')
            return True
        except OSError: return False

    def set_autorun(self):
        if sys.platform!='win32': return
        import winreg
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER,r'Software\Microsoft\Windows\CurrentVersion\Run') as key:
            if self.autorun.isChecked():
                if getattr(sys,'frozen',False): command='"'+sys.executable+'"'
                else:
                    # Absolute script launcher makes startup independent of the login cwd.
                    command=f'"{sys.executable}" "{Path(__file__).resolve().parents[1] / "launch.py"}"'
                winreg.SetValueEx(key,'ZaowuGrowthManager',0,winreg.REG_SZ,command)
            else:
                try: winreg.DeleteValue(key,'ZaowuGrowthManager')
                except FileNotFoundError: pass

    def test(self):
        if self.worker and self.worker.isRunning(): return
        key=self.key.text().strip() or self.window.chat.runtime_key or api_key()
        self.worker=AIWorker(self.base.text().strip(),key,parent=self)
        self.worker.models.connect(self.got_models)
        self.worker.failed.connect(self.status.setText)
        self.worker.completed.connect(lambda _:self.test_button.setEnabled(True))
        self.test_button.setEnabled(False)
        self.status.setText('连接测试中… 不产生聊天内容。')
        self.worker.start()

    def got_models(self,models):
        current=self.model.currentText()
        self.model.clear()
        self.model.addItems(models)
        if current in models: self.model.setCurrentText(current)
        self.status.setText('已通过真实 API 获取模型；请选择模型并保存。此检查不代表流式聊天已经通过。')

    def save(self):
        try:
            from .ai import endpoint
            base=endpoint(self.base.text().strip())
            key=self.key.text().strip()
            if key:
                if self.persist.isChecked(): save_api_key(key)
                self.window.chat.runtime_key=key
            self.set_autorun()
            self.store.set_setting('api_base',base)
            self.store.set_setting('model',self.model.currentText())
            self.store.set_setting('background','1' if self.background.isChecked() else '0')
            self.key.clear()
            self.status.setText('设置已保存。Key '+('已保存到系统凭据库' if key and self.persist.isChecked() else '仅本次运行使用' if key else '保持原有来源')+'。')
        except Exception as exc: fail(self,exc)

    def backup(self):
        target,_=QFileDialog.getSaveFileName(self,'保存数据库备份','造物手作备份.sqlite3','SQLite (*.sqlite3)')
        if target:
            try:
                self.store.backup(target)
                info(self,'数据库备份已保存。照片请单独备份 assets 目录。')
            except Exception as exc: fail(self,exc)

    def restore(self):
        if self.window.busy():
            fail(self,'请等待 AI 请求结束后恢复')
            return
        source,_=QFileDialog.getOpenFileName(self,'选择备份','','SQLite (*.sqlite3)')
        if source and confirm(self,'恢复将替换当前数据库。当前数据库会先备份，照片与系统 Key 不受此恢复管理。是否继续？'):
            try:
                safety=self.store.restore(source)
                self.window.chat.refresh_sessions()
                self.window.refresh_pages()
                info(self,'恢复成功。恢复前安全备份：'+str(safety)+'\n请重新启动应用以加载全部设置。')
            except Exception as exc: fail(self,exc)

class MainWindow(QMainWindow):
    MODULES=('今日工作','经营总览','DIY散客','花束业务','活动沙龙','经营数据分析','营销策略制定','内容创作助手','客户经营助手','市场竞争分析','经营复盘','AI经营助手','系统设置')

    def __init__(self,store):
        super().__init__()
        self.store=store
        self.module='今日工作'
        self.pages={}
        self.setWindowTitle('造物手作 AI 经营管理系统 · ZAOWU')
        self.resize(1500,940)
        self.setMinimumSize(1000,640)
        self.setStyleSheet(STYLE)
        self.setWindowIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon))
        container=QWidget()
        outer=QHBoxLayout(container)
        outer.setContentsMargins(0,0,0,0)
        self.nav=QListWidget()
        self.nav.setObjectName('navigation')
        self.nav.setFixedWidth(175)
        self.nav.addItems(self.MODULES)
        outer.addWidget(self.nav)
        self.split=QSplitter()
        center=QWidget()
        self.center_layout=QVBoxLayout(center)
        self.center_layout.setContentsMargins(20,12,20,14)
        header=QHBoxLayout()
        self.heading=QLabel()
        self.heading.setObjectName('heading')
        header.addWidget(self.heading,1)
        header.addWidget(button('刷新',self.refresh_pages))
        header.addWidget(button('收起 / 展开 AI',self.toggle_chat))
        self.center_layout.addLayout(header)
        self.subtitle=QLabel('ZAOWU / 真实记录 · 经营决策 · 持续复盘')
        self.subtitle.setObjectName('muted')
        self.center_layout.addWidget(self.subtitle)
        self.split.addWidget(center)
        self.chat=ChatPanel(self)
        self.split.addWidget(self.chat)
        self.split.setSizes([900,390])
        self.split.setCollapsible(0,False)
        self.split.setCollapsible(1,False)
        outer.addWidget(self.split,1)
        self.setCentralWidget(container)
        self.nav.currentRowChanged.connect(self.navigate)
        self.nav.setCurrentRow(0)
        self.tray=None
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray=QSystemTrayIcon(self.windowIcon(),self)
            self.tray.setToolTip('造物手作 AI 经营管理系统')
            menu=QMenu(self)
            show=menu.addAction('打开主窗口')
            show.triggered.connect(self.showNormal)
            quit_action=menu.addAction('退出程序')
            quit_action.triggered.connect(self.quit_app)
            self.tray.setContextMenu(menu)
            self.tray.activated.connect(lambda reason:self.showNormal() if reason==QSystemTrayIcon.ActivationReason.DoubleClick else None)
            self.tray.show()
        self.force_quit=False
        self.backup_timer=QTimer(self)
        self.backup_timer.setInterval(3600000)
        self.backup_timer.timeout.connect(self.maintenance)
        self.backup_timer.start()
        self.statusBar().showMessage('本地数据已加载 · 无自动外发 · 数据目录 '+str(store.root))

    def tabs(self,definitions):
        tabs=QTabWidget()
        for title,table,filters in definitions:
            page=RecordsPage(self.store,table,filters)
            page.changed.connect(self.data_changed)
            tabs.addTab(page,title)
        tabs.currentChanged.connect(lambda _:self.refresh_widget(tabs.currentWidget()))
        return tabs

    def make_page(self,module):
        if module in ('经营总览','经营数据分析'): return AnalysisPage(self.store)
        if module=='今日工作':
            tabs=QTabWidget()
            tabs.addTab(AnalysisPage(self.store,True),'今日经营与建议')
            tasks=RecordsPage(self.store,'tasks')
            tasks.changed.connect(self.data_changed)
            tabs.addTab(tasks,'今日任务与执行结果')
            return tabs
        if module in BUSINESSES:
            defs=[('订单 / 销售漏斗','orders',{'business':module}),('项目 / 产品','products',{'business':module})]
            if module=='花束业务': defs.append(('鲜花采购与库存','inventory',{}))
            if module=='活动沙龙': defs.extend([('企业与潜在客户','customers',{'business':module}),('客户跟进','followups',{})])
            return self.tabs(defs)
        definitions={
         '营销策略制定':[('营销实验与结果','campaigns',{}),('月度经营目标','goals',{}),('每周执行任务','tasks',{})],
         '内容创作助手':[('内容与发布日历','contents',{}),('本地照片素材','assets',{})],
         '客户经营助手':[('统一客户档案','customers',{}),('客户沟通跟进','followups',{})],
         '市场竞争分析':[('竞争对手与来源','competitors',{})],
         '经营复盘':[('日 / 周 / 月复盘','reviews',{}),('固定费用录入','expenses',{}),('建议执行追踪','tasks',{})],
         'AI经营助手':[('背景与长期经营记忆','memories',{}),('待确认建议','tasks',{})],
        }
        if module=='系统设置': return SettingsPage(self)
        tabs=self.tabs(definitions[module])
        if module=='经营复盘': tabs.addTab(ReportsPage(self.store),'自动周报 / 月报')
        return tabs

    def navigate(self,index):
        if index<0: return
        self.module=self.MODULES[index]
        self.heading.setText(self.module)
        for page in self.pages.values(): page.hide()
        if self.module not in self.pages:
            self.pages[self.module]=self.make_page(self.module)
            self.center_layout.addWidget(self.pages[self.module],1)
        self.pages[self.module].show()
        self.refresh_widget(self.pages[self.module])
        self.chat.set_module(self.module)

    def scope(self):
        page=self.pages.get(self.module)
        if isinstance(page,AnalysisPage):
            return page.start.date().toString('yyyy-MM-dd'),page.end.date().toString('yyyy-MM-dd'),None if page.business.currentIndex()==0 else page.business.currentText()
        today=date.today()
        return str(today.replace(day=1)),str(today),self.module if self.module in BUSINESSES else None

    def refresh_widget(self,page):
        if isinstance(page,(RecordsPage,AnalysisPage,ReportsPage)): page.refresh()
        elif isinstance(page,QTabWidget):
            for i in range(page.count()): self.refresh_widget(page.widget(i))

    def refresh_pages(self):
        for page in self.pages.values(): self.refresh_widget(page)

    def data_changed(self):
        # Refresh other loaded views so customer aggregates and product names stay consistent.
        self.refresh_pages()
        self.statusBar().showMessage('已保存到本地数据库 · '+str(date.today()),5000)

    def toggle_chat(self):
        self.chat.setVisible(not self.chat.isVisible())

    def maintenance(self):
        try:
            self.store.auto_backup()
            self.store.reports_due()
        except Exception as exc: self.statusBar().showMessage('自动备份未完成：'+str(exc))

    def busy(self):
        workers=[self.chat.worker]
        page=self.pages.get('系统设置')
        if page: workers.append(page.worker)
        return any(w and w.isRunning() for w in workers)

    def quit_app(self):
        self.force_quit=True
        self.close()

    def closeEvent(self,event):
        if not self.force_quit and self.tray and self.store.setting('background','0')=='1':
            self.hide()
            event.ignore()
            return
        if self.busy():
            self.chat.stop()
            settings=self.pages.get('系统设置')
            if settings and settings.worker: settings.worker.cancel()
            self.force_quit=True
            self.statusBar().showMessage('正在等待网络线程结束并保存聊天记录…')
            QTimer.singleShot(500,self.close)
            event.ignore()
            return
        self.chat.flush()
        if self.tray: self.tray.hide()
        event.accept()
