"""Read only a user-opened Xiaohongshu note. No login extraction or script eval."""
import hashlib
import json
import re
import tempfile
import threading
from dataclasses import dataclass,field
from pathlib import Path
from urllib.parse import urlparse,urlunparse

import requests
from PySide6.QtCore import QThread,Signal
from PySide6.QtGui import QImageReader

NOTE_HOSTS={'xiaohongshu.com','www.xiaohongshu.com','xhslink.com','xhslink.cn'}

def shared_url(text):
    for match in re.findall(r'https?://[^\s<>"\u3000]+',text):
        url=match.rstrip('。，、；;！!？?）》】')
        parsed=urlparse(url)
        if parsed.hostname not in NOTE_HOSTS:continue
        if parsed.username or parsed.password or parsed.port not in (None,80,443):continue
        if parsed.hostname in ('xhslink.cn','xhslink.com'):
            if not parsed.path.strip('/'):continue
        elif not re.search(r'/(?:explore|discovery/item)/[a-fA-F0-9]{24}(?:/|$)',parsed.path):continue
        return urlunparse(parsed._replace(scheme='https',netloc=parsed.hostname,fragment=''))
    raise ValueError('没有找到小红书笔记链接。请粘贴“复制链接”得到的整段分享文字，并保留链接参数。')

def note_id(url):
    parsed=urlparse(url)
    if parsed.hostname not in NOTE_HOSTS:return ''
    match=re.search(r'/(?:explore|discovery/item)/([a-fA-F0-9]{24})(?:/|$)',parsed.path)
    return match[1].lower() if match else ''

def media_url(url):
    if not isinstance(url,str):raise ValueError('图片地址格式错误')
    if url.startswith('//'):url='https:'+url
    parsed=urlparse(url)
    host=parsed.hostname or ''
    allowed=host.endswith('.xhscdn.com') or host=='xhscdn.com' or host=='ci.xiaohongshu.com'
    if not allowed or parsed.username or parsed.password or parsed.port not in (None,80,443) or parsed.scheme not in ('http','https'):
        raise ValueError('图片地址不属于支持的小红书图片域名')
    return urlunparse(parsed._replace(scheme='https',netloc=host,fragment=''))

@dataclass
class Note:
    note_id:str
    title:str
    text:str
    url:str
    images:list[str]=field(default_factory=list)
    kind:str='normal'

def parse_note(payload,url):
    if isinstance(payload,str):
        try:payload=json.loads(payload)
        except ValueError as exc:raise ValueError('页面尚未提供可读取的笔记数据。请确认已打开笔记，必要时在窗口内登录。') from exc
    if not isinstance(payload,dict) or payload.get('error'):
        raise ValueError('当前页面没有完整笔记数据。请先在窗口内完成登录 / 验证，再点击读取；不会绕过平台限制。')
    current_id=note_id(url)
    if not current_id:raise ValueError('尚未进入具体笔记页面，请等待短链接跳转完成')
    raw=payload.get('note',payload)
    actual_id=str(raw.get('noteId') or raw.get('id') or '').lower()
    if actual_id!=current_id:raise ValueError('页面数据与当前链接不一致，未导入其他笔记')
    text=str(raw.get('desc') or '')
    title=str(raw.get('title') or text.split('\n')[0][:80]).strip()
    if not title or not text:raise ValueError('未读取到完整标题和正文，可能需要登录或笔记已不可见')
    if len(text)>100000:raise ValueError('笔记文本过长，未导入')
    rows=raw.get('imageList') or []
    if not isinstance(rows,list) or len(rows)>100:raise ValueError('图片列表异常或超过100张，未截断导入')
    urls=[]
    for index,image in enumerate(rows,1):
        if not isinstance(image,dict):raise ValueError(f'第{index}张图片信息不完整')
        source=image.get('urlDefault') or image.get('url')
        if not source:
            variants=image.get('infoList') or []
            source=next((v.get('url') for v in variants if isinstance(v,dict) and v.get('imageScene')=='WB_DFT' and v.get('url')),None)
            source=source or next((v.get('url') for v in variants if isinstance(v,dict) and v.get('url')),None)
        if not source:raise ValueError(f'第{index}张图片缺少可读取地址，不能标记为完整导入')
        urls.append(media_url(source))
    kind=str(raw.get('type') or 'normal')
    if not urls:raise ValueError('未取得笔记图片列表；当前只支持图文笔记和视频封面，不下载视频流')
    return Note(current_id,title,text,url,urls,kind)

# Execute only this fixed script in the page that the user opened. Never evaluate
# the page's script source, inspect cookies, or serialize the full account state.
EXTRACT_JS=r'''(() => {
  try {
    const match=location.pathname.match(/\/(?:explore|discovery\/item)\/([a-f0-9]{24})/i);
    if (!match) return JSON.stringify({error:'not-a-note'});
    const state=window.__INITIAL_STATE__;
    const map=state && state.note && state.note.noteDetailMap;
    if (!map) return JSON.stringify({error:'no-note-state'});
    const id=match[1].toLowerCase();
    const item=map[id];
    const note=item && item.note;
    if (!note) return JSON.stringify({error:'no-matching-note'});
    return JSON.stringify({note:{noteId:note.noteId || note.id,title:note.title,
      desc:note.desc,type:note.type,imageList:(note.imageList || []).map(i => ({
        urlDefault:i.urlDefault,url:i.url,infoList:(i.infoList || []).map(v=>({url:v.url,imageScene:v.imageScene}))
      }))}});
  } catch (_) { return JSON.stringify({error:'page-not-ready'}); }
})()'''

class ImageWorker(QThread):
    progress=Signal(int,int)
    ready=Signal(object)
    failed=Signal(str)

    def __init__(self,note,parent=None):
        super().__init__(parent);self.note=note;self.cancelled=threading.Event()
        self.temporary=tempfile.TemporaryDirectory(prefix='zaowu-xhs-');self.results=[]

    def cancel(self):self.cancelled.set()

    def run(self):
        try:
            stored_bytes=0
            for index,url in enumerate(self.note.images):
                if self.cancelled.is_set():break
                result={'position':index+1,'url':url,'path':None,'error':''}
                try:
                    current=media_url(url)
                    for redirect in range(5):
                        response=requests.get(current,headers={'Referer':'https://www.xiaohongshu.com/','User-Agent':'ZaowuContentStudio/0.3'},stream=True,timeout=(10,20),allow_redirects=False)
                        if response.status_code in (301,302,303,307,308):
                            from urllib.parse import urljoin
                            try:target=media_url(urljoin(current,response.headers.get('Location','')))
                            finally:response.close()
                            current=target;continue
                        break
                    else:raise ValueError('图片跳转次数过多')
                    with response:
                        if response.status_code!=200:raise ValueError(f'图片服务器返回 HTTP {response.status_code}')
                        if not response.headers.get('Content-Type','').lower().startswith('image/'):raise ValueError('服务器没有返回图片')
                        path=Path(self.temporary.name)/f'{index+1}.download'
                        size=0
                        with path.open('wb') as file:
                            for chunk in response.iter_content(65536):
                                if self.cancelled.is_set():raise ValueError('读取已停止')
                                size+=len(chunk)
                                if size>25*1024*1024:raise ValueError('单张图片超过25MB')
                                file.write(chunk)
                    reader=QImageReader(str(path))
                    dimension=reader.size()
                    if not reader.canRead() or dimension.width()*dimension.height()>60_000_000:raise ValueError('图片格式不支持或分辨率过大')
                    image=reader.read()
                    if image.isNull():raise ValueError('图片不能完整解码')
                    # Canonical PNG keeps all decoded pixels, strips external metadata,
                    # and makes stored references portable without codec assumptions.
                    target=path.with_suffix('.png')
                    if not image.save(str(target),'PNG'):raise ValueError('图片保存失败')
                    decoded_size=target.stat().st_size
                    if decoded_size>60*1024*1024 or stored_bytes+decoded_size>300*1024*1024:
                        target.unlink(missing_ok=True)
                        raise ValueError('图片解码后体积过大，已标记缺失以免占满磁盘')
                    stored_bytes+=decoded_size
                    path.unlink(missing_ok=True);result['path']=str(target)
                except requests.RequestException:
                    result['error']='网络或证书验证失败，未获取此图片'
                except (OSError,ValueError) as exc:result['error']=str(exc)
                self.results.append(result);self.progress.emit(index+1,len(self.note.images))
            if self.cancelled.is_set():self.failed.emit('已停止读取，尚未保存为参考案例。')
            else:self.ready.emit(self.results)
        except Exception:self.failed.emit('读取图片时发生异常，尚未保存案例。')

    def cleanup(self):self.temporary.cleanup()
