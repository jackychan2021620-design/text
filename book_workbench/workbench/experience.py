"""Shared desktop interactions. Animations never resize layout-managed content."""
import os
import re
import sys
from PySide6.QtCore import (Qt,QEvent,QObject,QTimer,QPoint,QPropertyAnimation,
                            QParallelAnimationGroup,QEasingCurve,Signal)
from PySide6.QtGui import QKeySequence,QShortcut,QPainter,QColor
from PySide6.QtWidgets import (QApplication,QWidget,QDialog as NativeDialog,QLabel,QVBoxLayout,
 QHBoxLayout,QPushButton,QLineEdit,QTextEdit,QPlainTextEdit,QComboBox,QAbstractButton,QGraphicsOpacityEffect,
 QAbstractItemView,QTableWidget,QTableView,QHeaderView,QStyledItemDelegate,QStyle,QStyleOptionButton)

DURATION=180

def reduced_motion():
    app=QApplication.instance()
    if os.environ.get('BOOK_WORKBENCH_REDUCED_MOTION')=='1' or (app and app.property('reducedMotion')):return True
    if sys.platform=='win32':
        try:
            import ctypes
            enabled=ctypes.c_int(1)
            if ctypes.windll.user32.SystemParametersInfoW(0x1042,0,ctypes.byref(enabled),0):return not enabled.value
        except (OSError,AttributeError):pass
    return False

def selectable(text,parent=None):
    w=QLabel(str(text),parent);w.setWordWrap(True);w.setTextFormat(Qt.TextFormat.PlainText)
    w.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse|Qt.TextInteractionFlag.TextSelectableByKeyboard)
    return w

class FeedbackButton(QPushButton):
    def mousePressEvent(self,event):
        super().mousePressEvent(event)
        # The press is painted before a release handler can start work.
        self.repaint()

class Dialog(NativeDialog):
    """One transition and focus policy for forms, confirmation and detail dialogs."""
    def __init__(self,parent=None):
        super().__init__(parent);self._closing=False;self._transition=None;self._previous_focus=QApplication.focusWidget()
        self.setWindowModality(Qt.WindowModality.WindowModal if parent else Qt.WindowModality.ApplicationModal)
    def showEvent(self,event):
        super().showEvent(event)
        QTimer.singleShot(0,self._enter)
    def _enter(self):
        if not self.isVisible() or self._closing:return
        candidates=[w for w in self.findChildren(QWidget) if isinstance(w,(QLineEdit,QTextEdit,QPlainTextEdit,QComboBox)) and w.isVisible() and w.isEnabled() and not (hasattr(w,'isReadOnly') and w.isReadOnly())]
        if candidates:candidates[0].setFocus(Qt.FocusReason.OtherFocusReason)
        if not reduced_motion():self._animate(True)
    def _animate(self,opening,finished=None):
        if self._transition:self._transition.stop()
        end=self.pos();start=end+QPoint(0,8) if opening else end
        self._transition=QParallelAnimationGroup(self)
        opacity=QPropertyAnimation(self,b'windowOpacity',self._transition);opacity.setStartValue(.1 if opening else self.windowOpacity());opacity.setEndValue(1 if opening else 0)
        move=QPropertyAnimation(self,b'pos',self._transition);move.setStartValue(start);move.setEndValue(end if opening else end+QPoint(0,6))
        for animation in (opacity,move):animation.setDuration(DURATION);animation.setEasingCurve(QEasingCurve.Type.OutCubic);self._transition.addAnimation(animation)
        if finished:self._transition.finished.connect(finished)
        self._transition.start()
    def done(self,result):
        if self._closing:return
        self.setResult(result)
        if self.isVisible() and not reduced_motion():
            self._closing=True
            def finish():
                NativeDialog.done(self,result);self._closing=False;self.setWindowOpacity(1)
                if self._previous_focus:
                    try:self._previous_focus.setFocus(Qt.FocusReason.OtherFocusReason)
                    except RuntimeError:pass
            self._animate(False,finish)
        else:super().done(result)

class ConfirmDialog(Dialog):
    def __init__(self,parent,title,text,action='确认',danger=True):
        super().__init__(parent);self.setWindowTitle(title);self.setMinimumWidth(400);self.setMaximumWidth(540)
        layout=QVBoxLayout(self);layout.setContentsMargins(24,22,24,20);layout.setSpacing(16)
        heading=selectable(title);heading.setProperty('heading',True);layout.addWidget(heading);layout.addWidget(selectable(text))
        row=QHBoxLayout();row.addStretch();cancel=FeedbackButton('取消');cancel.clicked.connect(self.reject);row.addWidget(cancel)
        self.action=FeedbackButton(action);self.action.setObjectName('confirmAction');self.action.setProperty('role','danger' if danger else 'primary');self.action.clicked.connect(self.accept);row.addWidget(self.action);layout.addLayout(row)
        cancel.setDefault(True);cancel.setFocus()

def confirm(parent,title,text,action='确认',danger=True):return ConfirmDialog(parent,title,text,action,danger).exec()==NativeDialog.DialogCode.Accepted

class Toast(QWidget):
    def __init__(self,parent,text,error=False):
        super().__init__(parent.window());self.setObjectName('toast');self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground);self.setProperty('error',error)
        row=QHBoxLayout(self);row.setContentsMargins(16,10,10,10);body=selectable(text);body.setMaximumWidth(560);row.addWidget(body)
        close=FeedbackButton('×');close.setAccessibleName('关闭提示');close.setFixedWidth(30);close.clicked.connect(self.dismiss);row.addWidget(close)
        self.adjustSize();self.move(max(16,(self.parentWidget().width()-self.width())//2),max(16,self.parentWidget().height()-self.height()-32))
        self.effect=QGraphicsOpacityEffect(self);self.setGraphicsEffect(self.effect);self.show();self.raise_()
        self.slide=QPropertyAnimation(self,b'pos',self);self.slide.setDuration(0 if reduced_motion() else DURATION);self.slide.setStartValue(self.pos()+QPoint(0,6));self.slide.setEndValue(self.pos());self.slide.start()
        self.animation=QPropertyAnimation(self.effect,b'opacity',self);self.animation.setDuration(0 if reduced_motion() else DURATION);self.animation.setStartValue(0);self.animation.setEndValue(1);self.animation.start()
        self.timer=QTimer(self);self.timer.setSingleShot(True);self.timer.timeout.connect(self.dismiss);self.timer.start(7000 if error else 4200)
    def dismiss(self):
        self.timer.stop();self.animation.stop();self.animation.setStartValue(self.effect.opacity());self.animation.setEndValue(0);self.animation.finished.connect(self.deleteLater);self.animation.start()

def toast(parent,text,error=False):
    root=parent.window();old=getattr(root,'_toast',None)
    if old:
        try:old.deleteLater()
        except RuntimeError:pass
    root._toast=Toast(root,str(text),error);return root._toast

class InteractionPolicy(QObject):
    def eventFilter(self,obj,event):
        if event.type()==QEvent.Type.MouseButtonPress and isinstance(obj,QAbstractButton) and obj.isEnabled() and event.button()==Qt.MouseButton.LeftButton:
            obj.setDown(True);obj.repaint()
        if event.type()==QEvent.Type.Polish:
            if isinstance(obj,QLabel) and obj.pixmap().isNull():
                obj.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse|Qt.TextInteractionFlag.TextSelectableByKeyboard)
            if isinstance(obj,(QLineEdit,QTextEdit,QPlainTextEdit)) and not obj.property('smoothContextMenu'):
                obj.setProperty('smoothContextMenu',True);obj.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu);obj.customContextMenuRequested.connect(lambda point,w=obj:text_context_menu(w,point))
            if isinstance(obj,QAbstractButton):obj.setCursor(Qt.CursorShape.PointingHandCursor)
        return False

def install_policy():
    app=QApplication.instance()
    if not hasattr(app,'_interaction_policy'):
        app._interaction_policy=InteractionPolicy(app);app.installEventFilter(app._interaction_policy)

def readable(value,depth=0):
    """Business detail view, without JSON punctuation or model Markdown markers."""
    if isinstance(value,dict):
        return '\n'.join((('  '*depth)+str(k)+'：'+(readable(v,depth+1) if not isinstance(v,(dict,list,tuple)) else '\n'+readable(v,depth+1))) for k,v in value.items())
    if isinstance(value,(list,tuple)):
        return '\n\n'.join(readable(v,depth) for v in value) if value else '暂无记录'
    if value is None:return '未知'
    if isinstance(value,bool):return '是' if value else '否'
    return str(value)

class ActionDelegate(QStyledItemDelegate):
    def paint(self,painter,option,index):
        hovered=bool(option.state&QStyle.StateFlag.State_MouseOver)
        pressed=self.parent().property('pressedRow')==index.row()
        rect=option.rect.adjusted(7,6,-7,-6);painter.save();painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QColor('#779fe8' if hovered or pressed else '#dce0e6'));painter.setBrush(QColor('#cdddfb' if pressed else '#edf2fc' if hovered else '#ffffff'));painter.drawRoundedRect(rect,5,5)
        painter.setPen(QColor('#245bdb' if hovered or pressed else '#303846'));painter.drawText(rect,Qt.AlignmentFlag.AlignCenter,'编辑');painter.restore()

class ActionHeader(QHeaderView):
    def paintSection(self,painter,rect,index):
        painter.save();painter.fillRect(rect,QColor('#f1f3f6'));painter.setPen(QColor('#677080'));painter.drawText(rect,Qt.AlignmentFlag.AlignCenter,'操作');painter.restore()

class DataTable(QTableWidget):
    editRequested=Signal(int)
    def __init__(self,rows=0,columns=0,parent=None):
        super().__init__(rows,columns,parent);self.frozen=None
        self.setAlternatingRowColors(True);self.setMouseTracking(True)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel);self.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.verticalHeader().hide();self.verticalHeader().setDefaultSectionSize(38);self.horizontalHeader().setMinimumSectionSize(60)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive);self.horizontalHeader().setDefaultSectionSize(150);self.horizontalHeader().setStretchLastSection(True)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows);self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        shortcut=QShortcut(QKeySequence.StandardKey.Copy,self);shortcut.activated.connect(self.copy_cells)
    def copy_cells(self):
        selected=self.selectedIndexes()
        if not selected:return
        rows=sorted({i.row() for i in selected});cols=sorted({i.column() for i in selected})
        QApplication.clipboard().setText('\n'.join('\t'.join(self.item(r,c).text() if self.item(r,c) else '' for c in cols) for r in rows))
    def pin_actions(self,column):
        self.action_column=column
        if self.frozen:self.frozen.deleteLater()
        view=QTableView(self);self.frozen=view;view.setStyleSheet('QTableView{padding:0;border:0;border-left:1px solid #e0e3e9;border-radius:0;}');view.setModel(self.model());view.setSelectionModel(self.selectionModel());view.setHorizontalHeader(ActionHeader(Qt.Orientation.Horizontal,view))
        view.setItemDelegate(ActionDelegate(view));view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows);view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        view.setFocusPolicy(Qt.FocusPolicy.StrongFocus);view.setMouseTracking(True);view.verticalHeader().hide();view.verticalHeader().setDefaultSectionSize(38)
        for c in range(self.columnCount()):view.setColumnHidden(c,c!=column)
        view.setColumnWidth(column,90);self.setColumnWidth(column,100);view.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff);view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        view.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel);view.setAlternatingRowColors(True)
        self.verticalScrollBar().valueChanged.connect(view.verticalScrollBar().setValue);view.verticalScrollBar().valueChanged.connect(self.verticalScrollBar().setValue)
        view.viewport().setCursor(Qt.CursorShape.PointingHandCursor);view.viewport().installEventFilter(self);view.setProperty('pressedRow',-1)
        view.clicked.connect(lambda i:self.editRequested.emit(i.row()));view.show();self._place_actions()
    def eventFilter(self,obj,event):
        if self.frozen and obj is self.frozen.viewport():
            if event.type()==QEvent.Type.MouseButtonPress:
                self.frozen.setProperty('pressedRow',self.frozen.indexAt(event.position().toPoint()).row());self.frozen.viewport().repaint()
            elif event.type()==QEvent.Type.MouseButtonRelease:
                self.frozen.setProperty('pressedRow',-1);self.frozen.viewport().update()
            elif event.type()==QEvent.Type.KeyPress and event.key() in (Qt.Key.Key_Return,Qt.Key.Key_Enter):
                self.editRequested.emit(self.frozen.currentIndex().row());return True
        return super().eventFilter(obj,event)
    def resizeEvent(self,event):
        super().resizeEvent(event);self._place_actions()
    def _place_actions(self):
        if self.frozen:
            rect=self.viewport().geometry();self.frozen.setGeometry(rect.right()-94,self.horizontalHeader().geometry().top(),95,rect.height()+self.horizontalHeader().height());self.frozen.raise_()

def clean_markdown(text):
    text=re.sub(r'(?m)^\s{0,3}#{1,6}\s+','',text)
    text=re.sub(r'\*\*(.*?)\*\*',r'\1',text,flags=re.S)
    text=re.sub(r'(?<!\w)__(.*?)__(?!\w)',r'\1',text,flags=re.S)
    text=re.sub(r'(?<![\w*])\*([^*\n]+)\*(?![\w*])',r'\1',text)
    text=re.sub(r'(?m)^([ \t]*)\* +',r'\1• ',text)
    text=re.sub(r'`([^`\n]+)`',r'\1',text)
    text=re.sub(r'(?m)^\s*```[^\n]*\n?|^\s*```\s*$','',text)
    return text

from PySide6.QtWidgets import QComboBox as NativeComboBox
class SmoothComboBox(NativeComboBox):
    def __init__(self,parent=None):
        super().__init__(parent);self._popup_animation=None;self._popup_closing=False
    def showPopup(self):
        if self._popup_animation:self._popup_animation.stop()
        self._popup_closing=False;super().showPopup();popup=self.view().window();popup.setWindowOpacity(1)
        if reduced_motion():return
        group=QParallelAnimationGroup(self);end=popup.pos()
        for name,start,finish in ((b'windowOpacity',0.,1.),(b'pos',end+QPoint(0,-4),end)):
            animation=QPropertyAnimation(popup,name,group);animation.setDuration(DURATION);animation.setStartValue(start);animation.setEndValue(finish);animation.setEasingCurve(QEasingCurve.Type.OutCubic);group.addAnimation(animation)
        self._popup_animation=group;group.start()
    def hidePopup(self):
        popup=self.view().window()
        if reduced_motion() or not popup.isVisible():super().hidePopup();return
        if self._popup_closing:return
        self._popup_closing=True
        if self._popup_animation:self._popup_animation.stop()
        animation=QPropertyAnimation(popup,b'windowOpacity',self);animation.setDuration(DURATION);animation.setStartValue(popup.windowOpacity());animation.setEndValue(0)
        def finish():
            NativeComboBox.hidePopup(self);popup.setWindowOpacity(1);self._popup_closing=False
        animation.finished.connect(finish);self._popup_animation=animation;animation.start()

from PySide6.QtWidgets import QMenu as NativeMenu

class PopupGhost(QWidget):
    """A fading, noninteractive snapshot lets native menu actions finish at once."""
    def __init__(self,pixmap,position):
        super().__init__(None,Qt.WindowType.ToolTip|Qt.WindowType.FramelessWindowHint|Qt.WindowType.WindowDoesNotAcceptFocus|Qt.WindowType.WindowTransparentForInput)
        self.image=pixmap;self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground);self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.resize(pixmap.size());self.move(position);app=QApplication.instance()
        if not hasattr(app,'_popup_ghosts'):app._popup_ghosts=[]
        app._popup_ghosts.append(self);self.show();self.group=QParallelAnimationGroup(self)
        for name,start,end in ((b'windowOpacity',1.,0.),(b'pos',position,position+QPoint(0,4))):
            animation=QPropertyAnimation(self,name,self.group);animation.setDuration(DURATION);animation.setStartValue(start);animation.setEndValue(end);animation.setEasingCurve(QEasingCurve.Type.OutCubic);self.group.addAnimation(animation)
        def finish():
            if self in app._popup_ghosts:app._popup_ghosts.remove(self)
            self.deleteLater()
        self.group.finished.connect(finish);self.group.start()
    def paintEvent(self,event):
        painter=QPainter(self);painter.drawPixmap(0,0,self.image)

class SmoothMenu(NativeMenu):
    def showEvent(self,event):
        super().showEvent(event)
        if reduced_motion():return
        self._fade=QParallelAnimationGroup(self);position=self.pos()
        for name,start,end in ((b'windowOpacity',0.,1.),(b'pos',position+QPoint(0,-4),position)):
            animation=QPropertyAnimation(self,name,self._fade);animation.setDuration(DURATION);animation.setStartValue(start);animation.setEndValue(end);animation.setEasingCurve(QEasingCurve.Type.OutCubic);self._fade.addAnimation(animation)
        self._fade.start()
    def hideEvent(self,event):
        if hasattr(self,'_fade'):self._fade.stop()
        if not reduced_motion():PopupGhost(self.grab(),self.pos())
        self.setWindowOpacity(1);super().hideEvent(event)

def text_context_menu(widget,point):
    native=widget.createStandardContextMenu();menu=SmoothMenu(widget);native.setParent(menu);menu.addActions(native.actions());menu._source=native
    menu.aboutToHide.connect(lambda:QTimer.singleShot(DURATION,menu.deleteLater));menu.popup(widget.mapToGlobal(point))
