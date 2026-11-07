from pathlib import Path
from PySide6.QtCore import Qt,QTimer,QSize
from PySide6.QtGui import QIcon,QPixmap
from PySide6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QTabWidget,QListWidget,QListWidgetItem,QPlainTextEdit
from .widgets import label,button

class Gallery(QDialog):
    def __init__(self,images,parent=None):
        super().__init__(parent);self.images=images;self.index=0
        self.setWindowTitle('参考笔记图片 · 仅供分析');self.resize(900,800)
        layout=QVBoxLayout(self);self.position=label('','muted');layout.addWidget(self.position)
        self.image=label('');self.image.setAlignment(Qt.AlignmentFlag.AlignCenter);layout.addWidget(self.image,1)
        actions=QHBoxLayout();actions.addWidget(button('上一张',lambda:self.show_index(self.index-1)));actions.addWidget(button('下一张',lambda:self.show_index(self.index+1)));actions.addStretch();actions.addWidget(button('关闭',self.accept));layout.addLayout(actions)
        self.show_index(0)

    def show_index(self,index):
        if not self.images:return
        self.index=max(0,min(index,len(self.images)-1));row=self.images[self.index]
        self.position.setText(f"第 {row['position']} / {len(self.images)} 张 · 原笔记顺序")
        path=row.get('path')
        if path and Path(path).is_file():
            pixmap=QPixmap(path)
            self.image.setPixmap(pixmap.scaled(max(300,self.width()-40),max(300,self.height()-110),Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation))
        else:self.image.clear();self.image.setText('此图片未读到：'+row.get('error','文件缺失'))

    def resizeEvent(self,event):super().resizeEvent(event);self.show_index(self.index)

def image_items(widget,images):
    widget.clear();widget.setIconSize(QSize(150,150))
    for row in images:
        item=QListWidgetItem(f"第 {row['position']} 张"+(' · 未读到' if not row.get('path') else ''))
        if row.get('path'):item.setIcon(QIcon(row['path']))
        item.setToolTip(row.get('error','') or '双击查看大图')
        item.setData(Qt.ItemDataRole.UserRole,row['position']-1);widget.addItem(item)

class ReferenceDialog(QDialog):
    def __init__(self,window,reference_id):
        super().__init__(window);self.window=window;self.reference_id=reference_id
        ref=window.store.get('references',reference_id);images=window.store.reference_images(reference_id)
        self.setWindowTitle('已收藏的小红书笔记');self.resize(1000,800)
        layout=QVBoxLayout(self);layout.addWidget(label(ref['title'],'heading',True))
        source=window.store.reference_source(reference_id)
        count=sum(bool(i['path']) and Path(i['path']).is_file() for i in images)
        layout.addWidget(label(f"图片 {count} / {len(images)} 张 · 保留原笔记顺序"+(' · 视频仅保存封面' if source and source['kind']=='video' else ''),'muted',True))
        tabs=QTabWidget();text=QPlainTextEdit();text.setReadOnly(True);text.setPlainText(ref['excerpt']);tabs.addTab(text,'原文案')
        pictures=QListWidget();pictures.setViewMode(QListWidget.ViewMode.IconMode);pictures.setResizeMode(QListWidget.ResizeMode.Adjust);image_items(pictures,images)
        def open_image(item):
            dialog=Gallery(images,self);dialog.show_index(item.data(Qt.ItemDataRole.UserRole));dialog.exec()
        pictures.itemDoubleClicked.connect(open_image);tabs.addTab(pictures,'全部图片');layout.addWidget(tabs,1)
        actions=QHBoxLayout();actions.addWidget(button('文案拆解与拍摄建议',self.analyze))
        actions.addWidget(button('让 AI 看图后给拍摄方案',self.vision,True));actions.addStretch();actions.addWidget(button('用这个案例建选题',self.use));actions.addWidget(button('关闭',self.accept));layout.addLayout(actions)
        if source:
            def retry():
                self.accept();QTimer.singleShot(0,lambda:window.import_xhs(source['source_url']))
            layout.addWidget(button('重新读取 / 补齐图片',retry))

    def analyze(self):self.window.ask('拍摄与发布方案',reference_id=self.reference_id)
    def vision(self):self.window.ask('看图拍摄方案',reference_id=self.reference_id)
    def use(self):
        ref=self.window.store.get('references',self.reference_id);self.window.new_piece(reference=ref)
