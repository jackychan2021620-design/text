import base64
import hashlib
from pathlib import Path
from PySide6.QtCore import QByteArray,QBuffer,QIODevice,Qt,QSize
from PySide6.QtGui import QImageReader

def prepare_images(store,reference_id):
    images=store.reference_images(reference_id)
    if not images:raise ValueError('这个案例没有已收藏的图片，请先读取小红书链接')
    if len(images)>30:raise ValueError('当前单次最多分析30张，未自动截断图片；请先拆分案例')
    parts=[];manifest=[];total=0
    for row in images:
        if not row['path']:raise ValueError(f"第{row['position']}张图片未读到，请重新读取补齐，或先使用文案方案")
        path=Path(row['path']).resolve()
        if path.parent!=(store.root/'assets').resolve() or not path.is_file():raise ValueError('参考图片缺失或路径异常，请从完整备份恢复或重新读取')
        reader=QImageReader(str(path));dimension=reader.size()
        if not reader.canRead() or dimension.width()*dimension.height()>60_000_000:raise ValueError('图片无效或分辨率过大')
        reader.setScaledSize(dimension.scaled(QSize(1024,1024),Qt.AspectRatioMode.KeepAspectRatio))
        image=reader.read()
        if image.isNull():raise ValueError('无法解码参考图片')
        image=image.scaled(1024,1024,Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation)
        raw=QByteArray();buffer=QBuffer(raw);buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        if not image.save(buffer,'PNG'):raise ValueError('图片编码失败')
        content=bytes(raw);total+=len(content)
        if total>15*1024*1024:raise ValueError('本次图像数据超过15MB，未发送。请减少单篇图片量或另行压缩参考副本')
        parts.append({'type':'text','text':f"原笔记第{row['position']}张图片"})
        parts.append({'type':'image_url','image_url':{'url':'data:image/png;base64,'+base64.b64encode(content).decode('ascii')}})
        manifest.append({'position':row['position'],'width':image.width(),'height':image.height(),'bytes':len(content),'sha256':hashlib.sha256(content).hexdigest()})
    return parts,manifest

def redact_images(messages):
    output=[]
    for message in messages:
        content=message['content']
        if isinstance(content,list):
            content=[{'type':'image_url','image_url':{'url':'[图片像素将发送，预览和记录不保存Base64；见图片清单]'}} if part.get('type')=='image_url' else part for part in content]
        output.append(message|{'content':content})
    return output
