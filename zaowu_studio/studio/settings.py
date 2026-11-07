import json
import sys
from pathlib import Path
from PySide6.QtCore import QTimer,QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QTabWidget,QWidget,QFormLayout,
    QLineEdit,QComboBox,QCheckBox,QFileDialog)
from .widgets import label,button,Fields,document,confirm,error,info,scroll,fit_window
from .model import f
from .ai import AIWorker,api_key,save_api_key,endpoint,configured_vision_key

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
        super().__init__(window);self.window=window;self.store=window.store;self.worker=None;self.vision_worker=None;self.pending_close=False
        self.setWindowTitle('设置 · 造物手作');fit_window(self,700,760)
        self.auto_save_model=False;self.test_seconds=0;self.credential_notice=''
        layout=QVBoxLayout(self);layout.setContentsMargins(24,22,24,22)
        layout.addWidget(label('让工作台了解你的生意','heading'))
        tabs=QTabWidget();self.tabs=tabs;layout.addWidget(tabs,1)
        body=QWidget();profile_layout=QVBoxLayout(body)
        values=json.loads(self.store.setting('profile','{}'))
        self.profile=Fields(self.store,PROFILE_FIELDS,values);profile_layout.addWidget(self.profile)
        budget=QFormLayout();self.weekly=QLineEdit(self.store.setting('weekly_minutes','120'));self.research=QLineEdit(self.store.setting('research_minutes','60'))
        budget.addRow('每周内容运营预算（分钟）',self.weekly);budget.addRow('每两周案例研究预算（分钟）',self.research);profile_layout.addLayout(budget)
        self.background=QCheckBox('关闭窗口后留在托盘（默认关闭）');self.background.setChecked(self.store.setting('background','0')=='1');profile_layout.addWidget(self.background)
        self.autorun=QCheckBox('登录 Windows 时启动（默认关闭）');self.autorun.setEnabled(sys.platform=='win32');self.autorun.setChecked(autorun_enabled());profile_layout.addWidget(self.autorun)
        tabs.addTab(scroll(body),'门店与时间')
        ai=QWidget();ai_layout=QVBoxLayout(ai);form=QFormLayout()
        ai_layout.addWidget(label('原来的 DeepSeek API Key 可以继续使用。用于选题、文案、咨询和复盘；保存后会自动验证并获取模型。','muted',True))
        self.base=QLineEdit(self.store.setting('api_base','https://api.deepseek.com'))
        self.key=QLineEdit();self.key.setEchoMode(QLineEdit.EchoMode.Password);self.key.setPlaceholderText('留空保留已有 Key')
        self.persist=QCheckBox('保存到系统安全凭据库');self.persist.setChecked(sys.platform=='win32')
        self.model=QComboBox();self.model.setEditable(True);self.model.setMinimumContentsLength(14)
        if self.store.setting('model'):self.model.addItem(self.store.setting('model'))
        form.addRow('官方 API 地址',self.base);form.addRow('API Key',self.key);form.addRow('',self.persist);form.addRow('从服务获取的模型',self.model);ai_layout.addLayout(form)
        test_row=QHBoxLayout();self.test_button=button('测试连接并获取模型',self.test,True);test_row.addWidget(self.test_button)
        self.cancel_button=button('取消测试',self.cancel_test);self.cancel_button.setEnabled(False);test_row.addWidget(self.cancel_button);ai_layout.addLayout(test_row)
        self.ai_status=label('未配置 Key 时仍可整理资料、手动创作和记录效果。','muted',True);ai_layout.addWidget(self.ai_status)
        ai_layout.addWidget(document('''### 数据由你控制

每次 AI 请求前都展示完整发送文本。模型只能提出建议，不能修改资料、发布或投放。

Key 使用独立的系统凭据条目，不写入 SQLite。安全凭据库不可用时可只在本次运行使用。

原来的 Key 保留在本页。配置好“图片识别”后，软件会自动把图片观察交给 DeepSeek 整理拍摄与发布方案，不用来回切换。

模型从官方接口返回后选择，未写死模型名。连接测试只验证模型列表；聊天生成需要另行验证。'''),1)
        tabs.addTab(scroll(ai),'DeepSeek 文字')
        vision=QWidget();vl=QVBoxLayout(vision);vf=QFormLayout()
        vl.addWidget(label('只需配置一次：保留原 DeepSeek Key，在这里另填图片识别服务的 Key 和模型，测试后保存。日常只点“生成拍摄与发布方案”。','muted',True))
        self.vision_provider=QComboBox();self.vision_provider.addItems(('阿里云百炼 / Qwen 视觉（推荐）','OpenAI 视觉'))
        self.vision_base=QLineEdit(self.store.setting('vision_base','https://dashscope.aliyuncs.com/compatible-mode/v1'))
        if 'api.openai.com' in self.vision_base.text():self.vision_provider.setCurrentIndex(1)
        self.vision_provider.currentIndexChanged.connect(lambda i:self.vision_base.setText('https://api.openai.com/v1' if i else 'https://dashscope.aliyuncs.com/compatible-mode/v1'))
        self.vision_key=QLineEdit();self.vision_key.setEchoMode(QLineEdit.EchoMode.Password);self.vision_key.setPlaceholderText('此处填写看图服务的 Key，与 DeepSeek 分开')
        self.vision_model=QLineEdit(self.store.setting('vision_model'));self.vision_model.setPlaceholderText('复制控制台中支持图片输入的模型 ID')
        self.vision_persist=QCheckBox('保存到系统安全凭据库');self.vision_persist.setChecked(sys.platform=='win32')
        vf.addRow('看图服务',self.vision_provider);vf.addRow('官方接口',self.vision_base);vf.addRow('看图 API Key',self.vision_key);vf.addRow('视觉模型 ID',self.vision_model);vf.addRow('',self.vision_persist);vl.addLayout(vf)
        open_console=button('打开服务商控制台，获取 Key 和模型',lambda:QDesktopServices.openUrl(QUrl('https://platform.openai.com/' if self.vision_provider.currentIndex() else 'https://bailian.console.aliyun.com/')));vl.addWidget(open_console)
        test_row=QHBoxLayout();self.vision_test_button=button('测试图片连接（会调用模型）',self.test_vision,True);test_row.addWidget(self.vision_test_button)
        self.vision_cancel_button=button('取消测试',self.cancel_vision_test);self.vision_cancel_button.setEnabled(False);test_row.addWidget(self.vision_cancel_button);vl.addLayout(test_row)
        self.vision_status=label('测试只发送软件图标，不发送门店资料。视觉服务需要单独配置；没有配置时仍可收藏图片并使用文案分析。','muted',True);vl.addWidget(self.vision_status)
        vl.addWidget(document('''### 配好一次，每天只需一个入口

“生成拍摄与发布方案”会自动完成：识别全部参考图片 → 交给 DeepSeek 整理拍摄清单、发布顺序、标题和正文。开始前只确认一次发送资料。

图片发给本页配置的服务；DeepSeek 接收图片观察文字和门店资料。两个 Key 分开保存，各服务按实际调用量计费。同一方案窗口内修改或重试会复用已完成的图片观察。

模型 ID 以服务商控制台和权限为准，不根据名字猜测。阿里云官方 Qwen3-VL 仓库给出的兼容地址为本页默认地址。

Qwen 官方参考：https://github.com/QwenLM/Qwen3-VL 。当前工作台不会把 DeepSeek 文字接口冒充看图接口。
'''),1);tabs.addTab(scroll(vision),'图片识别')
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
        row=QHBoxLayout();row.addStretch();row.addWidget(button('关闭',self.reject));self.save_button=button('保存设置',self.save,True);row.addWidget(self.save_button);layout.addLayout(row)
        self.key.textChanged.connect(self.key_edited)
        self.test_timer=QTimer(self);self.test_timer.setInterval(1000);self.test_timer.timeout.connect(self.test_tick)

    def key_edited(self,text):
        if text.strip():self.ai_status.setText('已输入 DeepSeek Key。点击“保存设置”会自动验证；也可先点击“测试连接”。')

    def test_tick(self):
        self.test_seconds+=1
        self.ai_status.setText(f'正在验证 DeepSeek Key… {self.test_seconds} 秒。网络超时会明确提示，可以继续编辑或取消。')

    def cancel_test(self):
        if self.worker:self.worker.cancel()
        self.test_timer.stop();self.auto_save_model=False
        self.ai_status.setText('测试已取消。网络请求结束前仍可编辑其他设置，最迟在超时后退出。')

    def test(self):
        if self.worker and self.worker.isRunning():return
        key=self.key.text().strip() or self.window.runtime_key or api_key()
        if not key:self.ai_status.setText('请先在上方输入原来的 DeepSeek API Key。');return
        self.tested_key=key
        self.worker=AIWorker(self.base.text().strip(),key,parent=self)
        self.worker.models.connect(self.got_models);self.worker.failed.connect(self.test_failed)
        self.worker.completed.connect(self.test_finished)
        self.test_button.setEnabled(False);self.cancel_button.setEnabled(True);self.test_seconds=0;self.test_timer.start();self.ai_status.setText('正在验证 DeepSeek Key…');self.worker.start()

    def test_finished(self,ok):
        self.test_timer.stop();self.test_button.setEnabled(True);self.cancel_button.setEnabled(False)
        if not ok:self.auto_save_model=False
        if self.pending_close:QTimer.singleShot(50,self.reject)

    def test_failed(self,message):
        self.ai_status.setText(message);self.notice.setText('DeepSeek 连接未完成：'+message)

    def got_models(self,models):
        if self.worker and self.worker.cancelled.is_set():return
        current_key=self.key.text().strip() or self.window.runtime_key or self.tested_key
        if current_key!=self.tested_key:
            self.auto_save_model=False;self.ai_status.setText('测试期间 Key 已更改，请再次保存以验证当前 Key。');return
        current=self.model.currentText();self.model.clear();self.model.addItems(models)
        if current in models:self.model.setCurrentText(current)
        self.ai_status.setText('已从服务获取模型。请选择模型，再保存设置。')
        if self.auto_save_model:
            self.store.set_setting('model',self.model.currentText());self.auto_save_model=False
            self.ai_status.setText('DeepSeek 连接成功，Key 和模型已配置。可以使用文字功能。')
            self.notice.setText('设置已保存。'+self.credential_notice)

    def save(self):
        try:
            base=endpoint(self.base.text().strip());weekly=int(self.weekly.text());research=int(self.research.text())
            if not 1<=weekly<=10080 or not 1<=research<=10080:raise ValueError('时间预算应为1～10080分钟')
            vision_base=endpoint(self.vision_base.text().strip(),vision=True)
            vision_key=self.vision_key.text().strip()
            deepseek_key=self.key.text().strip() or self.window.runtime_key or api_key()
            if vision_key and vision_key==deepseek_key:raise ValueError('DeepSeek Key 应填在“DeepSeek 文字”标签。图片识别需要对应服务的 Key。')
            old_vision_base=self.store.setting('vision_base','https://dashscope.aliyuncs.com/compatible-mode/v1')
            credential_base=self.store.setting('vision_key_base',old_vision_base)
            if vision_base!=old_vision_base and not vision_key:raise ValueError('切换图片识别服务后，请输入新服务对应的 Key，再保存。')
            key=self.key.text().strip();self.credential_notice=''
            if key:
                self.window.runtime_key=key
                if self.persist.isChecked():
                    try:save_api_key(key)
                    except Exception:self.credential_notice='系统凭据保存未成功，Key 已在本次运行中生效，重启后需重新输入。'
            if vision_key:
                self.window.runtime_vision_key=vision_key;self.window.runtime_vision_base=vision_base
                if self.vision_persist.isChecked():
                    try:save_api_key(vision_key,vision=True);credential_base=vision_base
                    except Exception:self.credential_notice+=' 看图 Key 仅在本次运行生效。'
            set_autorun(self.autorun.isChecked())
            values={'profile':json.dumps(self.profile.values(),ensure_ascii=False),'weekly_minutes':weekly,'research_minutes':research,
                    'api_base':base,'model':self.model.currentText(),'background':int(self.background.isChecked()),
                    'vision_base':vision_base,'vision_key_base':credential_base,'vision_model':self.vision_model.text().strip()}
            with self.store.transaction():
                for k,v in values.items():self.store.db.execute('INSERT INTO settings VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(k,str(v)))
            self.key.clear();self.vision_key.clear();self.notice.setText('设置已保存。'+self.credential_notice);self.window.refresh()
            if key:
                self.auto_save_model=True;self.test()
        except Exception as exc:self.notice.setText(str(exc))

    def test_vision(self):
        if self.vision_worker and self.vision_worker.isRunning():return
        typed=self.vision_key.text().strip()
        if typed and typed==(self.key.text().strip() or self.window.runtime_key or api_key()):self.vision_status.setText('这是正在使用的 DeepSeek Key，请填到“DeepSeek 文字”；此处需要看图服务对应的 Key。');return
        if self.vision_base.text().strip()!=self.store.setting('vision_base','https://dashscope.aliyuncs.com/compatible-mode/v1') and not typed:
            self.vision_status.setText('切换服务商后，请输入新服务商的 Key 再测试。');return
        model=self.vision_model.text().strip()
        if not model:self.vision_status.setText('请先填写服务商控制台中可用的视觉模型 ID。');return
        import base64
        from .ui import ROOT
        raw=(ROOT/'resources'/'brand.png').read_bytes()
        messages=[{'role':'user','content':[{'type':'text','text':'请简短描述测试图的形状和颜色。'},
            {'type':'image_url','image_url':{'url':'data:image/png;base64,'+base64.b64encode(raw).decode('ascii')}}]}]
        key=typed or configured_vision_key(self.window,self.vision_base.text().strip())
        if not key:self.vision_status.setText('请先填写本页所选服务的图片识别 API Key。');return
        tested_base=self.vision_base.text().strip();tested_model=model
        self.vision_worker=AIWorker(self.vision_base.text().strip(),key,model,messages,self,vision=True)
        chunks=[]
        def receive(text):chunks.append(text);self.vision_status.setText(''.join(chunks))
        self.vision_worker.delta.connect(receive);self.vision_worker.failed.connect(self.vision_status.setText)
        def completed(ok):
            self.vision_test_button.setEnabled(True);self.vision_cancel_button.setEnabled(False)
            current_key=self.vision_key.text().strip() or configured_vision_key(self.window,self.vision_base.text().strip())
            if ok and (current_key!=key or self.vision_base.text().strip()!=tested_base or self.vision_model.text().strip()!=tested_model):
                self.vision_status.setText('测试期间配置已变化，请重新测试当前配置。');return
            if ok:self.vision_status.setText('已收到图像回复，请核对是否描述了绿色底、浅色四瓣图标；符合后点击“保存设置”。\n'+''.join(chunks))
        self.vision_worker.completed.connect(completed);self.vision_test_button.setEnabled(False);self.vision_cancel_button.setEnabled(True);self.vision_status.setText('正在发送软件图标测试…网络超时会明确提示，可以取消。');self.vision_worker.start()

    def cancel_vision_test(self):
        if self.vision_worker:self.vision_worker.cancel()
        self.vision_status.setText('已请求停止图片测试，网络读取结束后退出。')

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
        self.test_timer.stop()
        active=[w for w in (self.worker,self.vision_worker) if w and w.isRunning()]
        if active:
            self.pending_close=True
            for worker in active:worker.cancel()
            self.hide();QTimer.singleShot(300,self.reject);return
        super().reject()

    def closeEvent(self,event):
        if any(w and w.isRunning() for w in (self.worker,self.vision_worker)):self.reject();event.ignore()
        else:super().closeEvent(event)
