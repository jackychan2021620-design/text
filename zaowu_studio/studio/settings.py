import json
import sys
from pathlib import Path
from PySide6.QtCore import QTimer,QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QTabWidget,QWidget,QFormLayout,
    QLineEdit,QComboBox,QCheckBox,QFileDialog)
from .widgets import label,button,Fields,document,confirm,error,info,scroll
from .model import f
from .ai import AIWorker,api_key,save_api_key,endpoint

PROFILE_FIELDS=[f('name','门店名称'),f('city','所在城市'),f('area','位置与服务范围','long'),
 f('channels','当前账号与购买 / 咨询入口','long'),f('goal','当前最重要的经营目标','long'),
 f('constraints','时间与交付限制','long')]

def autorun_enabled():
    if sys.platform!='win32':return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,r'Software\Microsoft\Windows\CurrentVersion\Run') as key:
            winreg.QueryValueEx(key,'ZaowuContentStudio')
        return True
    except OSError:return False

def set_autorun(enabled):
    if sys.platform!='win32':return
    import winreg
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER,r'Software\Microsoft\Windows\CurrentVersion\Run') as key:
        if enabled:
            command='"'+sys.executable+'"'
            if not getattr(sys,'frozen',False):command+=' "'+str(Path(__file__).resolve().parents[1]/'launch.py')+'"'
            winreg.SetValueEx(key,'ZaowuContentStudio',0,winreg.REG_SZ,command)
        else:
            try:winreg.DeleteValue(key,'ZaowuContentStudio')
            except FileNotFoundError:pass

class SettingsDialog(QDialog):
    def __init__(self,window):
        super().__init__(window);self.window=window;self.store=window.store;self.worker=None;self.pending_close=False
        self.setWindowTitle('设置 · 造物手作');self.resize(700,760)
        layout=QVBoxLayout(self);layout.setContentsMargins(24,22,24,22)
        layout.addWidget(label('让工作台了解你的生意','heading'))
        tabs=QTabWidget();layout.addWidget(tabs,1)
        body=QWidget();profile_layout=QVBoxLayout(body)
        values=json.loads(self.store.setting('profile','{}'))
        self.profile=Fields(self.store,PROFILE_FIELDS,values);profile_layout.addWidget(self.profile)
        budget=QFormLayout();self.weekly=QLineEdit(self.store.setting('weekly_minutes','120'));self.research=QLineEdit(self.store.setting('research_minutes','60'))
        budget.addRow('每周内容运营预算（分钟）',self.weekly);budget.addRow('每两周案例研究预算（分钟）',self.research);profile_layout.addLayout(budget)
        self.background=QCheckBox('关闭窗口后留在托盘（默认关闭）');self.background.setChecked(self.store.setting('background','0')=='1');profile_layout.addWidget(self.background)
        self.autorun=QCheckBox('登录 Windows 时启动（默认关闭）');self.autorun.setEnabled(sys.platform=='win32');self.autorun.setChecked(autorun_enabled());profile_layout.addWidget(self.autorun)
        tabs.addTab(scroll(body),'门店与时间')
        ai=QWidget();ai_layout=QVBoxLayout(ai);form=QFormLayout()
        self.base=QLineEdit(self.store.setting('api_base','https://api.deepseek.com'))
        self.key=QLineEdit();self.key.setEchoMode(QLineEdit.EchoMode.Password);self.key.setPlaceholderText('留空保留已有 Key')
        self.persist=QCheckBox('保存到系统安全凭据库');self.persist.setChecked(sys.platform=='win32')
        self.model=QComboBox()
        if self.store.setting('model'):self.model.addItem(self.store.setting('model'))
        form.addRow('官方 API 地址',self.base);form.addRow('API Key',self.key);form.addRow('',self.persist);form.addRow('从服务获取的模型',self.model);ai_layout.addLayout(form)
        self.test_button=button('测试连接并获取模型',self.test,True);ai_layout.addWidget(self.test_button)
        self.ai_status=label('未配置 Key 时仍可整理资料、手动创作和记录效果。','muted',True);ai_layout.addWidget(self.ai_status)
        ai_layout.addWidget(document('''### 数据由你控制

每次 AI 请求前都展示完整发送文本。模型只能提出建议，不能修改资料、发布或投放。

Key 使用独立的系统凭据条目，不写入 SQLite。安全凭据库不可用时可只在本次运行使用。

当前 DeepSeek 接入仅使用文字。照片、视频不会上传；自动网页抓取、图片识别与自动剪辑尚未接入。

模型从官方接口返回后选择，未写死模型名。连接测试只验证模型列表；聊天生成需要另行验证。'''),1)
        tabs.addTab(ai,'AI 连接')
        vision=QWidget();vl=QVBoxLayout(vision);vf=QFormLayout()
        self.vision_provider=QComboBox();self.vision_provider.addItems(('阿里云百炼 / Qwen 视觉','OpenAI 视觉'))
        self.vision_base=QLineEdit(self.store.setting('vision_base','https://dashscope.aliyuncs.com/compatible-mode/v1'))
        if 'api.openai.com' in self.vision_base.text():self.vision_provider.setCurrentIndex(1)
        self.vision_provider.currentIndexChanged.connect(lambda i:self.vision_base.setText('https://api.openai.com/v1' if i else 'https://dashscope.aliyuncs.com/compatible-mode/v1'))
        self.vision_key=QLineEdit();self.vision_key.setEchoMode(QLineEdit.EchoMode.Password);self.vision_key.setPlaceholderText('此处填写看图服务的 Key，与 DeepSeek 分开')
        self.vision_model=QLineEdit(self.store.setting('vision_model'));self.vision_model.setPlaceholderText('填写服务商控制台中可用的视觉模型 ID')
        self.vision_persist=QCheckBox('保存到系统安全凭据库');self.vision_persist.setChecked(sys.platform=='win32')
        vf.addRow('看图服务',self.vision_provider);vf.addRow('官方接口',self.vision_base);vf.addRow('看图 API Key',self.vision_key);vf.addRow('视觉模型 ID',self.vision_model);vf.addRow('',self.vision_persist);vl.addLayout(vf)
        self.vision_test_button=button('测试图片连接（会调用模型）',self.test_vision,True);vl.addWidget(self.vision_test_button)
        self.vision_status=label('测试只发送软件图标，不发送门店资料。视觉服务需要单独配置；没有配置时仍可收藏图片并使用文案分析。','muted',True);vl.addWidget(self.vision_status)
        vl.addWidget(document('''### 真正看图后再给拍摄方案

“看图拍摄方案”会按原笔记顺序发送已收藏的全部图片，并预览图片数量、发送清单和文字。确认后才调用视觉模型。

模型 ID 以服务商控制台和权限为准，不根据名字猜测。阿里云官方 Qwen3-VL 仓库给出的兼容地址为本页默认地址。

Qwen 官方参考：https://github.com/QwenLM/Qwen3-VL 。当前工作台不会把 DeepSeek 文字接口冒充看图接口。
'''),1);tabs.addTab(vision,'图片分析')
        data=QWidget();data_layout=QVBoxLayout(data)
        data_layout.addWidget(label('资料保存在：'+str(self.store.root),'muted',True))
        data_layout.addWidget(button('备份整个工作台资料',self.backup))
        data_layout.addWidget(button('恢复资料备份',self.restore))
        data_layout.addWidget(button('打开本地资料目录',lambda:QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.store.root)))))
        data_layout.addWidget(document('''### 保留你的积累

当前工作台使用独立资料目录，不读取或覆盖旧经营系统数据库。

自动 SQLite 备份每天一份，启动和每小时检查，保留最近30份。手工“备份整个工作台资料”会生成含素材的 ZIP。

备份不含系统凭据，换电脑后需重新输入 Key。资料目前没有加密，请妥善保存备份。

卸载默认保留资料。升级安装替换程序文件，不覆盖用户资料。
'''),1);tabs.addTab(data,'资料与备份')
        self.notice=label('','muted',True);layout.addWidget(self.notice)
        row=QHBoxLayout();row.addStretch();row.addWidget(button('关闭',self.reject));row.addWidget(button('保存设置',self.save,True));layout.addLayout(row)

    def test(self):
        if self.worker and self.worker.isRunning():return
        key=self.key.text().strip() or self.window.runtime_key or api_key()
        self.worker=AIWorker(self.base.text().strip(),key,parent=self)
        self.worker.models.connect(self.got_models);self.worker.failed.connect(self.ai_status.setText)
        self.worker.completed.connect(lambda _:self.test_button.setEnabled(True))
        self.test_button.setEnabled(False);self.ai_status.setText('正在测试连接…');self.worker.start()

    def got_models(self,models):
        current=self.model.currentText();self.model.clear();self.model.addItems(models)
        if current in models:self.model.setCurrentText(current)
        self.ai_status.setText('已从服务获取模型。请选择模型，再保存设置。')

    def save(self):
        try:
            base=endpoint(self.base.text().strip());weekly=int(self.weekly.text());research=int(self.research.text())
            if not 1<=weekly<=10080 or not 1<=research<=10080:raise ValueError('时间预算应为1～10080分钟')
            key=self.key.text().strip()
            if key:
                if self.persist.isChecked():save_api_key(key)
                self.window.runtime_key=key
            vision_base=endpoint(self.vision_base.text().strip(),vision=True)
            vision_key=self.vision_key.text().strip()
            if vision_key:
                if self.vision_persist.isChecked():save_api_key(vision_key,vision=True)
                self.window.runtime_vision_key=vision_key
            set_autorun(self.autorun.isChecked())
            values={'profile':json.dumps(self.profile.values(),ensure_ascii=False),'weekly_minutes':weekly,'research_minutes':research,
                    'api_base':base,'model':self.model.currentText(),'background':int(self.background.isChecked()),
                    'vision_base':vision_base,'vision_model':self.vision_model.text().strip()}
            with self.store.transaction():
                for k,v in values.items():self.store.db.execute('INSERT INTO settings VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(k,str(v)))
            self.key.clear();self.vision_key.clear();self.notice.setText('设置已保存。');self.window.refresh()
        except Exception as exc:self.notice.setText(str(exc))

    def test_vision(self):
        if self.worker and self.worker.isRunning():return
        model=self.vision_model.text().strip()
        if not model:self.vision_status.setText('请先填写服务商控制台中可用的视觉模型 ID。');return
        import base64
        from .ui import ROOT
        raw=(ROOT/'resources'/'brand.png').read_bytes()
        messages=[{'role':'user','content':[{'type':'text','text':'请简短描述测试图的形状和颜色。'},
            {'type':'image_url','image_url':{'url':'data:image/png;base64,'+base64.b64encode(raw).decode('ascii')}}]}]
        key=self.vision_key.text().strip() or getattr(self.window,'runtime_vision_key','') or api_key(vision=True)
        self.worker=AIWorker(self.vision_base.text().strip(),key,model,messages,self,vision=True)
        chunks=[]
        def receive(text):chunks.append(text);self.vision_status.setText(''.join(chunks))
        self.worker.delta.connect(receive);self.worker.failed.connect(self.vision_status.setText)
        def completed(ok):
            self.vision_test_button.setEnabled(True)
            if ok:self.vision_status.setText('图像请求已收到回复，请检查描述是否符合左侧软件图标。\n'+''.join(chunks))
        self.worker.completed.connect(completed);self.vision_test_button.setEnabled(False);self.vision_status.setText('正在发送软件图标测试…');self.worker.start()

    def backup(self):
        path,_=QFileDialog.getSaveFileName(self,'保存完整资料包','造物工作台备份.zip','ZIP (*.zip)')
        if path:
            try:self.store.export_bundle(path);info(self,'完整资料包已保存，包含数据库和素材，不包含 API Key。')
            except Exception as exc:error(self,exc)

    def restore(self):
        path,_=QFileDialog.getOpenFileName(self,'选择工作台备份','','工作台备份 (*.zip *.sqlite3)')
        if path and confirm(self,'将替换当前资料库。恢复前会创建安全备份；素材仅追加，不删除当前文件。确认继续？'):
            try:
                safety=self.store.restore_bundle(path) if path.lower().endswith('.zip') else self.store.restore(path)
                self.window.refresh();info(self,'恢复完成。恢复前备份：'+str(safety)+'\n请重启以加载全部设置。')
            except Exception as exc:error(self,exc)

    def reject(self):
        if self.worker and self.worker.isRunning():self.worker.cancel();QTimer.singleShot(300,self.reject);return
        super().reject()

    def closeEvent(self,event):
        if self.worker and self.worker.isRunning():self.worker.cancel();event.ignore();QTimer.singleShot(300,self.reject)
        else:event.accept()
