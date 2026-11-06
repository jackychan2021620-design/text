import json
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QTextEdit,QDialogButtonBox,QPlainTextEdit
from .ai import AIWorker,SYSTEM,api_key
from .widgets import label,button,document,confirm,error

TASKS={
 '拍摄与发布方案':'仅根据已读取文案、已有文字观察和本店服务，制定可执行的拍摄与发笔记方案。明确写出“未分析图片画面”。列出要拍什么、机位、顺序、道具、文字结构和本地咨询引导；没有画面依据时将构图作为待验证建议，不声称逐图拆解。',
 '看图拍摄方案':'结合实际附图和笔记文案逐张分析，先按原顺序写出每张图片实际展示的内容、景别、构图与作用。再结合造物手作真实产品，给出可执行的拍摄清单（拍什么、机位、光线、道具、可用素材与补拍）、建议发布图片顺序、标题方向和正文结构、面向汕头顾客的咨询引导。不能把原作者作品或评价冒充本店；看不清的部分明确说明，不根据图片推断曝光或成交。',
 '案例拆解':'分析给定案例，按：目标顾客、开头机制、证据、本地相关性、制作负担、可测试选题。区分已知和未知，不根据点赞认定获客有效。',
 '选题计划':'结合当前业务、参考案例、真实产品、历史反馈与时间上限，提出未来两周最多4条选题。严格返回 JSON 对象 {"items":[...]}。每条字段 topic,audience,hypothesis,angle,missing,platform,plan_date 为字符串；offer_id,reference_id 为资料中存在的整数编号或null。platform只能取小红书、抖音、美团、其他。plan_date为YYYY-MM-DD。明确参考依据、待验证假设、补拍清单与制作负担。没有案例时在hypothesis写明缺口，不冒充已验证。',
 '素材检查':'检查当前选题和选中素材的文字描述，列出可复用内容及最少补拍清单，优先减少制作时间。未发送图片视频，不得声称识别画面。',
 '内容草稿':'为当前选题生成可编辑草稿。只返回 JSON 对象，字段 title,cover,body,script,cta 均为字符串。根据实际平台选用图文或视频表达，资料缺失使用【待确认：具体问题】占位。价格、服务和案例只能来自所选真实产品资料。不要编造顾客反馈。',
 '咨询辅助':'根据真实产品服务和用户当前问题生成回复草稿，先列出尚需确认的信息，不冒充已确认价格和交付，不索取个人联系方式。',
 '效果复盘':'结合真实反馈，分别列出观察事实、待验证解释、下一轮可执行调整。比较传播与本地相关需求，标记未记录数据，小样本不推断因果。只提出最多3个动作，考虑耗时。',
}

def parse_draft(text):
    raw=text.strip()
    if raw.startswith('```'):
        lines=raw.splitlines()
        if lines[-1].strip()=='```':raw='\n'.join(lines[1:-1])
    try:data=json.loads(raw)
    except ValueError as exc:raise ValueError('回复不是有效草稿结构。可继续要求 AI 返回指定 JSON，或手动复制正文。') from exc
    keys=('title','cover','body','script','cta')
    if not isinstance(data,dict) or any(not isinstance(data.get(k),str) for k in keys):raise ValueError('草稿字段不完整，尚未应用')
    return {k:data[k] for k in keys}

def parse_plan(text):
    raw=text.strip()
    if raw.startswith('```'):raw='\n'.join(raw.splitlines()[1:-1])
    try:data=json.loads(raw)
    except ValueError as exc:raise ValueError('选题计划格式不完整，请要求 AI 返回指定 JSON') from exc
    items=data.get('items') if isinstance(data,dict) else None
    if not isinstance(items,list) or not 1<=len(items)<=4:raise ValueError('一次计划应包含1～4个选题')
    required=('topic','audience','hypothesis','angle','missing','platform','plan_date')
    result=[]
    for item in items:
        if not isinstance(item,dict) or any(not isinstance(item.get(k),str) for k in required):raise ValueError('选题字段不完整')
        row={k:item[k] for k in required}
        for key in ('offer_id','reference_id'):
            value=item.get(key)
            if value is not None and (not isinstance(value,int) or isinstance(value,bool)):raise ValueError('关联资料编号无效')
            row[key]=value
        result.append(row)
    return result

class AIDialog(QDialog):
    def __init__(self,window,task,context,apply=None,history_run=None):
        super().__init__(window)
        self.window=window;self.store=window.store;self.task=task;self.context=context;self.apply_callback=apply
        self.worker=None;self.run_id=None;self.buffer='';self.ok=False;self.history=[];self.pending_close=False
        self.setWindowTitle('AI · '+task);self.resize(800,790)
        layout=QVBoxLayout(self);layout.setContentsMargins(26,22,26,22)
        top=QHBoxLayout();top.addWidget(label(task,'heading'),1);top.addWidget(label(context.get('business',''),'badge'));layout.addLayout(top)
        layout.addWidget(label('使用当前任务相关资料。每次发送前可核查完整内容，输出由你确认后使用。','muted',True))
        self.view=document();layout.addWidget(self.view,1)
        self.status=label('','muted',True);layout.addWidget(self.status)
        self.input=QTextEdit();self.input.setAcceptRichText(False);self.input.setFixedHeight(92)
        self.input.setPlaceholderText('补充要求或继续修改（请勿输入客户姓名、电话、微信号）');layout.addWidget(self.input)
        actions=QHBoxLayout();self.send=button('核查资料并生成',self.generate,True);self.stop=button('停止',self.cancel);self.stop.setEnabled(False)
        actions.addWidget(self.send);actions.addWidget(self.stop);actions.addStretch()
        self.apply=button('检查并加入选题' if task=='选题计划' else '检查并应用草稿',self.apply_result);self.apply.setVisible(apply is not None);self.apply.setEnabled(False)
        self.remember=button('保存为经验记忆',self.save_memory);self.remember.setEnabled(False)
        actions.addWidget(self.remember);actions.addWidget(self.apply);actions.addWidget(button('关闭',self.reject));layout.addLayout(actions)
        self.timer=QTimer(self);self.timer.setInterval(180);self.timer.timeout.connect(self.flush)
        if history_run:
            self.buffer=history_run['output'];self.view.setMarkdown(self.buffer)
            self.status.setText('历史记录 · '+history_run['status']);self.ok=history_run['status']=='已完成'
            self.remember.setEnabled(self.ok)
            self.send.hide();self.input.hide();self.stop.hide()
        else:self.view.setMarkdown('### 本次任务\n\n'+TASKS[task]+'\n\n尚未发送任何资料。')

    def generate(self):
        if self.worker and self.worker.isRunning():return
        vision=self.task=='看图拍摄方案'
        key=(self.window.runtime_vision_key or api_key(vision=True)) if vision else (self.window.runtime_key or api_key())
        model=self.store.setting('vision_model' if vision else 'model')
        if not key or not model:error(self,'请先在“门店与设置 → 图片分析”配置视觉服务的 Key 和模型。图片收藏与文案方案不需要看图模型。' if vision else '请先在设置中输入 API Key，获取可用模型并保存。');return
        text=self.input.toPlainText().strip() or TASKS[self.task]
        content=text
        if vision:
            from .vision import prepare_images
            try:
                reference_id=self.context.get('reference',{}).get('id')
                if not reference_id:raise ValueError('请从已收藏图文案例打开看图分析')
                parts,manifest=prepare_images(self.store,reference_id)
            except Exception as exc:error(self,exc);return
            self.context['reference_media']={'pixel_input':True,'images':manifest,'note':'会发送清单中的全部图片像素，长边最多1024；原图仍保存在本机'}
            content=[{'type':'text','text':text}]+parts
        messages=[{'role':'system','content':SYSTEM+'\n任务资料：\n'+json.dumps(self.context,ensure_ascii=False)}]+self.history+[{'role':'user','content':content}]
        from .vision import redact_images
        safe_messages=redact_images(messages)
        if len(json.dumps(safe_messages,ensure_ascii=False))>100000:error(self,'资料与对话较长，请保存结果后重新打开任务。');return
        dialog=QDialog(self);dialog.setWindowTitle('确认本次发送内容');dialog.resize(740,640)
        layout=QVBoxLayout(dialog)
        layout.addWidget(label(f'将向已配置的视觉服务发送 {len(manifest)} 张参考图片和以下文字。图片清单包含尺寸与哈希，预览不展开 Base64。' if vision else '以下文字将发送到 DeepSeek，本次不发送图片像素。请核查自由文本是否包含私人信息。','muted',True))
        preview=QPlainTextEdit();preview.setReadOnly(True);preview.setPlainText(json.dumps(safe_messages,ensure_ascii=False,indent=2));layout.addWidget(preview)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept);buttons.rejected.connect(dialog.reject);layout.addWidget(buttons)
        if not dialog.exec():return
        self.run_id=self.store.start_run(self.task,self.context['business'],{'context':self.context,'messages':safe_messages})
        self.buffer='';self.ok=False;self.pending_user=text;self.input.clear();self.apply.setEnabled(False);self.remember.setEnabled(False)
        base=self.store.setting('vision_base','https://dashscope.aliyuncs.com/compatible-mode/v1') if vision else self.store.setting('api_base','https://api.deepseek.com')
        self.worker=AIWorker(base,key,model,messages,self,vision=vision)
        self.worker.delta.connect(self.receive);self.worker.failed.connect(self.status.setText);self.worker.completed.connect(self.complete)
        self.send.setEnabled(False);self.stop.setEnabled(True);self.status.setText('正在生成…');self.timer.start();self.worker.start()

    def receive(self,text):self.buffer+=text

    def flush(self):
        bar=self.view.verticalScrollBar();position=bar.value();bottom=bar.maximum()-position<35
        self.view.setMarkdown(self.buffer)
        bar.setValue(bar.maximum() if bottom else position)
        if self.run_id:self.store.update_run(self.run_id,self.buffer,'生成中')

    def complete(self,ok):
        self.timer.stop();self.flush();self.ok=ok
        if self.run_id:self.store.update_run(self.run_id,self.buffer,'已完成' if ok else '未完成')
        if ok:
            self.history.extend([{'role':'user','content':self.pending_user},{'role':'assistant','content':self.buffer}])
            self.status.setText('已保存。可以继续提出修改要求；未自动更改任何内容。')
        self.send.setEnabled(True);self.stop.setEnabled(False);self.apply.setEnabled(ok and self.apply_callback is not None)
        self.remember.setEnabled(ok)
        if self.pending_close:QTimer.singleShot(100,self.reject)

    def apply_result(self):
        if not self.ok:return
        try:
            draft=parse_plan(self.buffer) if self.task=='选题计划' else parse_draft(self.buffer)
            if self.apply_callback(draft):self.accept()
        except Exception as exc:error(self,exc)

    def save_memory(self):
        from .model import TABLES
        from .widgets import EditDialog
        values={'title':self.task+' · 请确认结论','body':self.buffer,'level':'待验证解释','basis':'AI 生成内容，尚待人工核实；不构成验证证据','share_ai':0}
        dialog=EditDialog(self.store,'保存为待验证记忆',TABLES['learnings'][1],values,self.context['business'],self,lambda v:self.store.save('learnings',v))
        dialog.exec()

    def cancel(self):
        if self.worker:self.worker.cancel()
        self.status.setText('正在停止，网络读取结束后保留部分结果。')

    def reject(self):
        if self.worker and self.worker.isRunning():
            self.pending_close=True;self.cancel();QTimer.singleShot(300,self.reject);return
        super().reject()

    def closeEvent(self,event):
        if self.worker and self.worker.isRunning():self.pending_close=True;self.cancel();event.ignore();QTimer.singleShot(300,self.reject)
        else:event.accept()
