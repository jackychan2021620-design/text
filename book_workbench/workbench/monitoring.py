"""Public HTML reader and durable >=100-like events. No private or signed APIs.
Live Douyin compatibility is unverified until public pages can be fetched.
"""
import json
import re
import time
import uuid
from datetime import datetime,timezone
from html.parser import HTMLParser
from urllib.parse import urlparse,urljoin,parse_qs,unquote
import requests
from PySide6.QtCore import QThread,Signal

HOSTS={'douyin.com','www.douyin.com','v.douyin.com','www.iesdouyin.com'}
SEEDS=['https://v.douyin.com/zZoup5HEVkM/','https://v.douyin.com/McJQd_lnLSw/','https://v.douyin.com/s2gZbbXRc0o/']
KEY='douyin-monitor:v1'
THRESHOLD=100

def now():return datetime.now(timezone.utc).isoformat(timespec='seconds')

def public_url(value):
    matches=re.findall(r'https://[^\s<>"\u201c\u201d]+',value)
    if len(matches)!=1:raise ValueError('每次请粘贴一个抖音账号或视频分享链接')
    url=matches[0].rstrip('，。；）)');u=urlparse(url)
    if u.scheme!='https' or u.hostname not in HOSTS or u.port not in (None,443) or u.username or u.password or not u.path.strip('/'):
        raise ValueError('仅支持抖音官方 HTTPS 分享链接')
    return url

def identity(url):
    u=urlparse(url);query=parse_qs(u.query)
    if query.get('sec_uid'):return query['sec_uid'][0]
    m=re.search(r'/user/([^/?]+)',u.path)
    return m[1] if m else ''

class Scripts(HTMLParser):
    def __init__(self):super().__init__();self.current=None;self.blocks=[]
    def handle_starttag(self,tag,attrs):
        if tag=='script':self.current=[dict(attrs),[]]
    def handle_data(self,data):
        if self.current:self.current[1].append(data)
    def handle_endtag(self,tag):
        if tag=='script' and self.current:self.blocks.append((self.current[0],''.join(self.current[1])));self.current=None

def documents(html):
    parser=Scripts();parser.feed(html);out=[]
    for attrs,text in parser.blocks:
        candidate=None
        if attrs.get('id')=='RENDER_DATA':candidate=unquote(text)
        elif attrs.get('type') in ('application/json','application/ld+json'):candidate=text
        else:
            match=re.search(r'(?:window\.)?_ROUTER_DATA\s*=\s*',text)
            if match:
                try:out.append(json.JSONDecoder().raw_decode(text[match.end():].lstrip())[0])
                except (ValueError,RecursionError):pass
        if candidate:
            try:out.append(json.loads(candidate))
            except (ValueError,RecursionError):pass
    return out

def walk(value):
    stack=[(value,0)];count=0
    while stack:
        item,depth=stack.pop();count+=1
        if depth>25 or count>100000:raise ValueError('公开页面数据过于复杂，未处理')
        if isinstance(item,dict):yield item;stack.extend((v,depth+1) for v in item.values() if isinstance(v,(dict,list)))
        elif isinstance(item,list):stack.extend((v,depth+1) for v in item if isinstance(v,(dict,list)))

def owner_ids(author):
    if not isinstance(author,dict):return set()
    return {str(author[k]) for k in ('uid','sec_uid','secUid') if author.get(k)}

def product_names(video):
    names=[]
    # Only explicit product attachments count as shopping evidence. A title
    # mentioning a book is retained separately and never called a verified cart.
    sources=[video.get('promotions'),video.get('promotion'),video.get('product_info')]
    for source in sources:
        for item in (source if isinstance(source,list) else [source]):
            if not isinstance(item,dict):continue
            title=item.get('title') or item.get('product_title') or item.get('product_name')
            if isinstance(title,str) and title.strip() and title.strip() not in names:names.append(title.strip()[:500])
    return names

def parse_page(html,url,expected_owner=''):
    docs=documents(html);nodes=[node for doc in docs for node in walk(doc)]
    owner=expected_owner or identity(url);nickname=''
    # Profile-specific containers establish identity; unrelated recommendation
    # authors cannot determine which account is being monitored.
    for node in nodes:
        profile=node.get('userInfo') or node.get('user_info')
        if isinstance(profile,dict):
            profile=profile.get('user',profile)
            ids=owner_ids(profile)
            if ids and (not owner or owner in ids):
                owner=owner or str(profile.get('secUid') or profile.get('sec_uid') or profile.get('uid'));nickname=profile.get('nickname') or nickname
    videos={}
    for item in nodes:
        video_id=item.get('aweme_id') or item.get('awemeId')
        if not video_id or not re.fullmatch(r'\d{5,30}',str(video_id)):continue
        author=item.get('author') or item.get('authorInfo')
        if not owner or owner not in owner_ids(author):continue
        stats=item.get('statistics') or {};likes=stats.get('digg_count',stats.get('diggCount'))
        # Compact counts (e.g. 1.2万), hidden counts and nulls are not exact counts.
        if isinstance(likes,bool) or not isinstance(likes,int) or likes<0:continue
        timestamp=item.get('create_time',item.get('createTime'));published=''
        if isinstance(timestamp,(int,float)) and not isinstance(timestamp,bool):
            try:published=datetime.fromtimestamp(timestamp,timezone.utc).isoformat(timespec='seconds')
            except (ValueError,OverflowError,OSError):pass
        names=product_names(item);title=item.get('desc') or item.get('description') or ''
        if not isinstance(title,str):title=''
        videos[str(video_id)]={'id':str(video_id),'title':title[:1000],
            'url':'https://www.douyin.com/video/'+str(video_id),'likes':likes,'published':published,
            'products':names,'book_status':'挂车商品名，需核对具体版本' if names else '挂车书名待确认',
            'book_hints':list(dict.fromkeys(re.findall(r'《([^》]{1,100})》',title))),
            'checked':now()}
        nickname=nickname or (author.get('nickname','') if isinstance(author,dict) else '')
    if not owner:raise ValueError('未读取到账号身份；可能需要登录或页面未提供公开资料')
    if not videos:raise ValueError('未读取到该账号带明确点赞数的作品；可能需要登录、页面动态加载或格式变化。未记为检查成功')
    return {'owner':owner,'nickname':nickname,'url':url,'videos':list(videos.values()),'checked':now(),
            'coverage':'仅本次公开页面返回的作品，不能代表账号全量作品'}

def fetch_page(url,session=None):
    url=public_url(url);deadline=time.monotonic()+25
    own=session is None;session=session or requests.Session()
    try:
        for _ in range(6):
            if time.monotonic()>deadline:raise ValueError('抖音页面读取超时，旧数据已保留')
            with session.get(url,timeout=(5,8),allow_redirects=False,stream=True) as response:
                if response.status_code in (301,302,303,307,308):
                    target=response.headers.get('Location')
                    if not target:raise ValueError('抖音分享链接未返回跳转地址')
                    url=public_url(urljoin(url,target));continue
                if response.status_code!=200:raise ValueError(f'公开页面访问失败 HTTP {response.status_code}；旧数据已保留')
                raw=bytearray()
                for chunk in response.iter_content(65536):
                    raw.extend(chunk)
                    if len(raw)>10*1024**2 or time.monotonic()>deadline:raise ValueError('公开页面过大或读取超时，旧数据已保留')
                return bytes(raw).decode('utf-8',errors='replace'),url
        raise ValueError('分享链接跳转次数过多')
    finally:
        if own:session.close()

class MonitorStore:
    """Settings-backed state is transactionally included in existing backups."""
    def __init__(self,store):self.store=store
    def load(self):
        raw=self.store.setting(KEY)
        if not raw:return {'accounts':[],'enabled':False}
        value=json.loads(raw)
        if not isinstance(value,dict) or not isinstance(value.get('accounts'),list):raise ValueError('账号监测资料无法读取，请先备份')
        return value
    def save(self,value):self.store.settings({KEY:json.dumps(value,ensure_ascii=False,allow_nan=False)})
    def seed(self):
        if self.store.setting(KEY):return
        value=self.load()
        for index,url in enumerate(SEEDS):value['accounts'].append(self.new_account(url,'待核实账号 '+str(index+1)))
        self.save(value)
    @staticmethod
    def new_account(url,name=''):
        return {'id':uuid.uuid4().hex,'url':public_url(url),'name':name or '待核实账号','owner':'','videos':{},'last_attempt':'','last_success':'','error':'尚未检查','unread':[],'alerted':[]}
    def add(self,url):
        value=self.load();url=public_url(url)
        if any(a['url']==url for a in value['accounts']):raise ValueError('这个账号链接已经添加')
        value['accounts'].append(self.new_account(url));self.save(value)
    def remove(self,id):
        value=self.load();value['accounts']=[a for a in value['accounts'] if a['id']!=id];self.save(value)
    def apply(self,id,result):
        value=self.load();account=next((a for a in value['accounts'] if a['id']==id),None)
        if account is None:return []
        account['last_attempt']=now()
        if result.get('error'):
            account['error']=result['error'];self.save(value);return []
        if account['owner'] and account['owner']!=result['owner']:raise ValueError('链接返回的账号与原记录不一致，未覆盖已有数据')
        account.update(owner=result['owner'],name=result['nickname'] or account['name'],last_success=result['checked'],error='',coverage=result['coverage'])
        events=[]
        for video in result['videos']:
            account['videos'][video['id']]=video
            if video['likes']>=THRESHOLD and video['id'] not in account['alerted']:
                account['alerted'].append(video['id']);account['unread'].append(video['id']);events.append(video)
        self.save(value);return events
    def mark_read(self,id):
        value=self.load()
        for a in value['accounts']:
            if a['id']==id:a['unread']=[]
        self.save(value)

class MonitorWorker(QThread):
    result=Signal(str,object)
    def __init__(self,accounts,parent=None):super().__init__(parent);self.accounts=accounts
    def run(self):
        for account in self.accounts:
            if self.isInterruptionRequested():break
            try:
                html,url=fetch_page(account['url']);data=parse_page(html,url,account.get('owner',''))
                self.result.emit(account['id'],data)
                # Revisit a small rotating batch of known videos that have not
                # reached the threshold and disappeared from the profile page.
                seen={v['id'] for v in data['videos']}
                pending=sorted((v for v in account['videos'].values() if v['likes']<THRESHOLD and v['id'] not in seen),key=lambda v:v.get('checked',''))[:3]
                for video in pending:
                    if self.isInterruptionRequested():break
                    try:
                        html,url=fetch_page(video['url']);extra=parse_page(html,url,data['owner'])
                        extra['videos']=[v for v in extra['videos'] if v['id']==video['id']]
                        if extra['videos']:self.result.emit(account['id'],extra)
                    except (ValueError,requests.RequestException):
                        self.result.emit(account['id'],{'error':'部分旧视频复查未完成；已有数据保留，后续重试'})
            except requests.RequestException:self.result.emit(account['id'],{'error':'无法连接抖音公开页面，请检查网络或代理；旧数据已保留'})
            except (ValueError,TypeError,KeyError) as exc:self.result.emit(account['id'],{'error':str(exc)})
