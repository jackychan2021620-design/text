from pathlib import Path
from PySide6.QtCore import Qt,QDate,QUrl
from PySide6.QtGui import QDesktopServices,QPixmap
from PySide6.QtWidgets import (QWidget,QDialog,QVBoxLayout,QHBoxLayout,QTabWidget,QLabel,
    QListWidget,QListWidgetItem,QFileDialog,QDialogButtonBox,QApplication,QTextEdit)
from .model import PIECE_FIELDS,FEEDBACK_FIELDS,STAGES
from .store import display_money
from .widgets import label,button,Fields,scroll,document,confirm,error,info,EditDialog,frame
from .ai_dialog import AIDialog

STEP_KEYS=[
 ('topic','platform','plan_date','audience','hypothesis','reference_id'),
 ('offer_id','angle','missing'),('title','cover','body','script','cta'),
 ('published_date','published_url'),(),
]
STEP_TITLES=('选好方向','准备素材','完成草稿','发布记录','效果与调整')
ADVANCE=('确认选题，准备素材','素材已准备，开始写稿','草稿已检查，准备发布','确认已经发布','完成本次复盘')

class AssetPicker(QDialog):
    def __init__(self,window,business,selected):
        super().__init__(window);self.window=window;self.business=business;self.selected=selected
        self.setWindowTitle('从素材库选择');self.resize(620,600)
        layout=QVBoxLayout(self);layout.addWidget(label('使用现有素材','heading'))
        layout.addWidget(label('图片和视频只保存在本地。AI 目前使用你填写的文字描述。','muted',True))
        layout.addWidget(button('导入新素材',self.import_asset))
        self.items=QListWidget();layout.addWidget(self.items,1)
        self.items.itemDoubleClicked.connect(self.describe)
        actions=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
        actions.accepted.connect(self.accept);actions.rejected.connect(self.reject);layout.addWidget(actions)
        self.load()

    def load(self):
        self.items.clear()
        for asset in self.window.store.rows('assets',self.business):
            item=QListWidgetItem(f"{asset['name']} · {asset['kind']}\n{asset['description'] or '双击补充素材描述'}")
            item.setData(Qt.ItemDataRole.UserRole,asset['id'])
            item.setFlags(item.flags()|Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if asset['id'] in self.selected else Qt.CheckState.Unchecked)
            self.items.addItem(item)

    def chosen(self):return [self.items.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.items.count()) if self.items.item(i).checkState()==Qt.CheckState.Checked]

    def import_asset(self):
        files,_=QFileDialog.getOpenFileNames(self,'选择图片或视频','','图片与视频 (*.jpg *.jpeg *.png *.webp *.bmp *.mp4 *.mov *.mkv *.webm)')
        if not files:return
        self.selected=self.chosen()
        for file in files:
            try:self.selected.append(self.window.store.add_asset(file,self.business))
            except Exception as exc:error(self,exc)
        self.load()

    def describe(self,item):
        self.selected=self.chosen();asset_id=item.data(Qt.ItemDataRole.UserRole)
        edit_asset(self.window,asset_id,self)
        self.load()

def edit_asset(window,asset_id,parent=None):
    from .model import f
    store=window.store;asset=store.get('assets',asset_id)
    def save(values):
        if not values['name'].strip():raise ValueError('请填写素材名称')
        with store.db:store.db.execute('UPDATE assets SET name=?,description=? WHERE id=?',(values['name'].strip(),values['description'],asset_id))
    dialog=EditDialog(store,'整理素材',[f('name','名称',required=True),f('description','画面内容与可使用角度','long',hint='只填写真实画面；这段描述可以在确认后提供给 AI')],asset,parent=parent or window,save=save)
    open_button=button('打开本地文件',lambda:QDesktopServices.openUrl(QUrl.fromLocalFile(asset['path'])))
    dialog.layout().insertWidget(1,open_button)
    if asset['kind']=='图片':
        pixmap=QPixmap(asset['path'])
        if not pixmap.isNull():
            preview=QLabel();preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
            preview.setPixmap(pixmap.scaled(480,200,Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation))
            dialog.layout().insertWidget(1,preview)
    return dialog.exec()

class PieceDialog(QDialog):
    def __init__(self,window,piece_id):
        super().__init__(window)
        self.window=window;self.store=window.store;self.piece_id=piece_id
        self.piece=self.store.get('pieces',piece_id);self.dirty=False
        self.selected_assets=[a['id'] for a in self.store.assets_for(piece_id)]
        self.setWindowTitle('内容工作室 · '+self.piece['topic']);self.resize(980,850)
        layout=QVBoxLayout(self);layout.setContentsMargins(28,22,28,20)
        header=QHBoxLayout();header.addWidget(label('一条内容，一次推进','heading'),1);self.stage_label=label(self.piece['stage'],'badge');header.addWidget(self.stage_label);layout.addLayout(header)
        layout.addWidget(label(self.piece['business']+' / '+self.piece['platform'],'muted'))
        self.tabs=QTabWidget();self.forms=[];self.pages=[]
        for index,(title,keys) in enumerate(zip(STEP_TITLES,STEP_KEYS)):
            body=QWidget();content=QVBoxLayout(body);content.setContentsMargins(18,22,18,20);content.setSpacing(16)
            if index==0:
                content.addWidget(label('先确定这条内容希望吸引谁，以及准备验证什么。','muted',True))
                content.addWidget(button('AI 帮我梳理方向',lambda:self.ask('选题计划')))
            if index==1:
                content.addWidget(label('复用已有素材。只补拍这条内容真正需要的画面。','muted',True))
                row=QHBoxLayout();row.addWidget(button('从素材库选择',self.pick_assets,True));row.addWidget(button('AI 检查与补拍清单',lambda:self.ask('素材检查')));row.addStretch();content.addLayout(row)
                self.asset_summary=label('','muted',True);content.addWidget(self.asset_summary)
            if index==2:
                row=QHBoxLayout();row.addWidget(button('AI 生成 / 修改草稿',lambda:self.ask('内容草稿'),True));row.addWidget(button('复制发布稿',self.copy));row.addWidget(button('导出文稿',self.export));row.addStretch();content.addLayout(row)
                content.addWidget(label('AI 结果先检查再应用；价格、承诺与顾客案例需核实。','muted',True))
            fields=[f for f in PIECE_FIELDS if f.key in keys]
            form=Fields(self.store,fields,self.piece,self.piece['business']);self.forms.append(form);content.addWidget(form)
            if index==3:
                content.addWidget(label('请自行到平台发布。软件不会自动发布、发送消息或产生广告费用。','muted',True))
                content.addWidget(button('复制标题与正文',self.copy))
                self.preview=document();content.addWidget(self.preview,1)
            if index==4:
                row=QHBoxLayout();row.addWidget(button('记录一份最新反馈',self.feedback,True));row.addWidget(button('AI 复盘当前内容',lambda:self.ask('效果复盘')));row.addStretch();content.addLayout(row)
                self.feedback_view=document();content.addWidget(self.feedback_view,1)
            content.addStretch() if index not in (3,4) else None
            self.tabs.addTab(scroll(body),title);self.pages.append(body)
            for widget in form.inputs.values():
                for signal in ('textChanged','currentIndexChanged','dateChanged'):
                    if hasattr(widget,signal):getattr(widget,signal).connect(self.mark_dirty);break
        self.tabs.currentChanged.connect(self.refresh_previews)
        layout.addWidget(self.tabs,1)
        self.notice=label('更改会在点击保存时写入本地资料库。','muted',True);layout.addWidget(self.notice)
        footer=QHBoxLayout();footer.addWidget(button('关闭',self.reject));footer.addWidget(button('保存进度',self.save));footer.addStretch()
        self.next_button=button('',self.advance,True);footer.addWidget(self.next_button);layout.addLayout(footer)
        self.refresh_stage();self.refresh_previews()

    def mark_dirty(self,*_):self.dirty=True

    def values(self):
        result={'business':self.piece['business']}
        for form in self.forms:result.update(form.values())
        return result

    def save(self):
        try:
            with self.store.transaction():
                self.store.save('pieces',self.values(),self.piece_id,self.piece['version'])
                self.store.link_assets(self.piece_id,self.selected_assets)
            self.piece=self.store.get('pieces',self.piece_id);self.dirty=False
            self.notice.setText('进度已保存。');self.refresh_previews();return True
        except Exception as exc:self.notice.setText(str(exc));return False

    def refresh_stage(self):
        stage=self.piece['stage'];self.stage_label.setText(stage)
        index=min(STAGES.index(stage),4)
        self.tabs.setCurrentIndex(index)
        self.next_button.setText(ADVANCE[index] if stage!='已复盘' else '复盘已完成')
        self.next_button.setEnabled(stage!='已复盘')

    def advance(self):
        if not self.save():return
        if self.piece['stage']=='待发布' and not confirm(self,'确认已经在平台实际发布？此操作只记录发布状态，不会代你发布。'):return
        try:
            self.store.advance(self.piece_id);self.piece=self.store.get('pieces',self.piece_id)
            self.refresh_stage();self.notice.setText('已进入下一步。')
        except Exception as exc:self.notice.setText(str(exc))

    def pick_assets(self):
        picker=AssetPicker(self.window,self.piece['business'],self.selected_assets)
        if picker.exec():self.selected_assets=picker.chosen();self.dirty=True;self.refresh_previews()

    def refresh_previews(self,*_):
        if hasattr(self,'asset_summary'):
            assets=[self.store.get('assets',i) for i in self.selected_assets]
            self.asset_summary.setText('已选素材：'+'、'.join(a['name'] for a in assets) if assets else '尚未选择素材。可以先使用文字表达，再逐步补拍。')
        if hasattr(self,'preview'):self.preview.setMarkdown(self.markdown())
        if hasattr(self,'feedback_view'):
            history=self.store.feedback_history(self.piece_id)
            if not history:self.feedback_view.setMarkdown('### 等实际发布后再记录反馈\n\n平台没有提供的数据请留空。曝光、阅读、本地咨询和成交分别记录，不互相替代。')
            else:
                text='## 反馈记录\n\n每次记录为截至当日的累计数据，汇总使用最新采集日期的一份。\n\n'
                for r in reversed(history):
                    text+=f"### {r['observed_date']}\n\n"
                    for field in FEEDBACK_FIELDS:
                        if field.key=='observed_date':continue
                        value=r[field.key]
                        if field.kind=='money_optional':value=display_money(value)
                        elif value is None:value='未记录'
                        text+=f'**{field.label}**：{value}\n\n'
                self.feedback_view.setMarkdown(text)

    def markdown(self):
        p=self.values()
        return f"# {p['title'] or p['topic']}\n\n{p['body']}\n\n{p['cta']}\n\n"+(f"## 封面\n\n{p['cover']}\n\n" if p['cover'] else '')+(f"## 视频脚本\n\n{p['script']}" if p['script'] else '')

    def copy(self):
        QApplication.clipboard().setText(self.markdown());self.notice.setText('已复制。请检查后自行到平台发布。')

    def export(self):
        target,_=QFileDialog.getSaveFileName(self,'导出文稿','造物内容草稿.md','Markdown (*.md)')
        if target:
            try:Path(target).write_text(self.markdown(),encoding='utf-8');self.notice.setText('已导出文稿。')
            except Exception as exc:error(self,exc)

    def ask(self,task):
        if not self.save():return
        try:
            context=self.store.context(self.piece['business'],piece_id=self.piece_id,task=task)
            def apply(draft):
                if not confirm(self,'将这份 AI 草稿填入当前内容？原有标题、封面、正文、脚本和咨询引导会替换；尚不会自动发布。'):return False
                for key,value in draft.items():
                    widget=self.forms[2].inputs[key]
                    widget.setPlainText(value) if isinstance(widget,QTextEdit) else widget.setText(value)
                self.tabs.setCurrentIndex(2);self.dirty=True
                self.notice.setText('AI 草稿已填入编辑区，请检查后保存。');return True
            dialog=AIDialog(self.window,task,context,apply if task=='内容草稿' else None)
            dialog.exec()
        except Exception as exc:error(self,exc)

    def feedback(self):
        if not self.save():return
        if self.piece['stage'] not in ('已发布','已复盘'):info(self,'请先在发布记录中确认实际发布，再记录反馈。');return
        latest=self.store.latest_feedback(self.piece_id)
        initial={k:v for k,v in (latest or {}).items() if k not in ('id','created_at','piece_id')}
        initial['observed_date']=QDate.currentDate().toString('yyyy-MM-dd')
        def save(values):self.store.add_feedback(self.piece_id,values)
        dialog=EditDialog(self.store,'记录截至当日的累计反馈',FEEDBACK_FIELDS,initial,parent=self,save=save)
        if dialog.exec():self.refresh_previews()

    def reject(self):
        if self.dirty and not confirm(self,'当前有尚未保存的编辑，确认放弃并关闭？'):return
        super().reject()

    def closeEvent(self,event):
        if self.dirty and not confirm(self,'当前有尚未保存的编辑，确认放弃并关闭？'):event.ignore()
        else:event.accept()
