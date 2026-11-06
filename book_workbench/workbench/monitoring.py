"""Public HTML reader and durable >=100-like events. No private or signed APIs.
Live Douyin compatibility is unverified until public pages can be fetched.
"""
import json
import math
import re
import time
import uuid
from datetime import datetime,timezone
from html.parser import HTMLParser
from urllib.parse import urlparse,urljoin,parse_qs,unquote,quote
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

def published_time(value):
    if isinstance(value,bool) or value is None:return ''
    try:
        if isinstance(value,str) and not re.fullmatch(r'\d+(?:\.\d+)?',value.strip()):
            parsed=datetime.fromisoformat(value.strip().replace('Z','+00:00'))
            if not parsed.tzinfo:parsed=parsed.replace(tzinfo=timezone.utc)
        else:
            stamp=float(value)
            if not math.isfinite(stamp):return ''
            if stamp>1e14:stamp/=1e6
            elif stamp>1e11:stamp/=1000
            parsed=datetime.fromtimestamp(stamp,timezone.utc)
        if not 2000<=parsed.year<=2100:return ''
        return parsed.astimezone(timezone.utc).isoformat(timespec='seconds')
    except (ValueError,TypeError,OverflowError,OSError):return ''


def visible_likes(value):
    """Return estimate plus a conservative lower bound for the 100-like test."""
    if isinstance(value,bool) or value is None:return None
    if isinstance(value,int) and value>=0:return {'likes':value,'likes_lower_bound':value,'likes_exact':True,'likes_display':str(value)}
    if not isinstance(value,str):return None
    text=value.strip().replace(',','').replace('，','').replace('点赞','').replace('赞','').strip()
    match=re.fullmatch(r'(\d+(?:\.\d+)?)(万|亿|[kKwW])?(\+)?',text)
    if not match:return None
    number,unit,plus=match.groups();scale={'万':10000,'亿':100000000,'k':1000,'w':10000}.get((unit or '').lower(),1)
    estimate=float(number)*scale
    if not math.isfinite(estimate):return None
    if not unit and '.' not in number:return {'likes':int(estimate),'likes_lower_bound':int(estimate),'likes_exact':True,'likes_display':text}
    decimals=len(number.partition('.')[2]);step=scale/(10**decimals)
    lower=estimate if plus else max(0,estimate-step/2)
    return {'likes':int(estimate),'likes_lower_bound':math.floor(lower),'likes_exact':False,'likes_display':'约'+text}


def is_hot(video):
    bound=video.get('likes_lower_bound',video.get('likes'))
    return isinstance(bound,(int,float)) and not isinstance(bound,bool) and bound>=THRESHOLD


def product_names(video):
    names=[]
    stack=[(video[k],0,k not in ('anchor_info','anchors','commerce_info')) for k in ('promotions','promotion','product_info','commerce_info','cart_products','anchor_info','anchors') if video.get(k)];visited=0
    generic={'购物','小黄车','查看商品','精选好书','商品橱窗','商品','抖音电商'}
    while stack and visited<1000:
        item,depth,evidence=stack.pop();visited+=1
        if depth>7:continue
        if isinstance(item,str):
            if len(item)<100000:
                try:stack.append((json.loads(item),depth+1,evidence))
                except (ValueError,TypeError):pass
            continue
        if isinstance(item,list):stack.extend((x,depth+1,evidence) for x in item[:50]);continue
        if not isinstance(item,dict):continue
        explicit=item.get('product_title') or item.get('product_name') or item.get('promotion_title')
        title=explicit or (item.get('title') if evidence or any(item.get(k) for k in ('product_id','promotion_id','sku_id')) else None)
        # A generic anchor caption is not a book. Explicit product fields or
        # a product container establish the evidence; captions stay separate.
        if isinstance(title,str) and title.strip() and title.strip() not in generic and title.strip() not in names:names.append(title.strip()[:500])
        for key in ('extra','product','product_info','products','promotion','promotions','goods','items','detail','info'):
            if item.get(key):stack.append((item[key],depth+1,evidence or key in ('product','product_info','products','promotion','promotions','goods')))
    return names


def parse_page(html,url,expected_owner=''):
    return parse_documents(documents(html),url,expected_owner)

def parse_documents(docs,url,expected_owner='',partial=False):
    nodes=[node for doc in docs for node in walk(doc)]
    owner=expected_owner or identity(url);nickname='';aliases={owner} if owner else set()
    target=re.search(r'/(?:share/)?video/(\d{5,30})',urlparse(url).path)
    if not owner and target:
        for item in nodes:
            if str(item.get('aweme_id') or item.get('awemeId') or '')==target[1]:
                author=item.get('author') or item.get('authorInfo') or {}
                if isinstance(author,dict):owner=str(author.get('sec_uid') or author.get('secUid') or author.get('uid') or '')
                if owner:break
    aliases.add(owner)
    # Bind only a canonical user URL or the explicitly shared video's author.
    # Login viewer/userInfo on a generic feed must never bind a monitored account.
    for node in nodes:
        profile=node.get('userInfo') or node.get('user_info')
        if isinstance(profile,dict):
            profile=profile.get('user',profile);ids=owner_ids(profile)
            if owner and owner in ids:aliases.update(ids);nickname=profile.get('nickname') or nickname
    videos={};profile_url=''
    for item in nodes:
        video_id=item.get('aweme_id') or item.get('awemeId')
        if not video_id or not re.fullmatch(r'\d{5,30}',str(video_id)):continue
        author=item.get('author') or item.get('authorInfo') or {'uid':item.get('author_user_id')}
        if not owner or not aliases.intersection(owner_ids(author)):continue
        aliases.update(owner_ids(author))
        sec=author.get('sec_uid') or author.get('secUid')
        if sec:profile_url='https://www.douyin.com/user/'+quote(str(sec),safe='')
        stats=item.get('statistics') or {}
        if not isinstance(stats,dict):
            if not partial:continue
            stats={}
        likes=stats.get('digg_count',stats.get('diggCount'))
        count=visible_likes(likes)
        if partial and count is None:count=visible_likes(stats.get('digg_count_display'))
        if not partial and (count is None or not count['likes_exact']):continue
        if count is None:count={'likes':None,'likes_lower_bound':None,'likes_exact':False,'likes_display':'未显示'}
        published=published_time(item.get('create_time',item.get('createTime')) or item.get('publish_time'))
        names=product_names(item);title=item.get('desc') or item.get('description') or ''
        if not isinstance(title,str):title=''
        videos[str(video_id)]={'id':str(video_id),'title':title[:1000],
            'url':'https://www.douyin.com/video/'+str(video_id),**count,'published':published,
            'products':names,'book_status':'挂车商品字段' if names else '文案书名，挂车未确认' if re.search(r'《[^》]+》',title) else '挂车书名未显示',
            'book_hints':list(dict.fromkeys(re.findall(r'《([^》]{1,100})》',title))),
            'checked':now()}
        nickname=nickname or (author.get('nickname','') if isinstance(author,dict) else '')
    if not owner:raise ValueError('未读取到账号身份；可能需要登录或页面未提供公开资料')
    if not videos:raise ValueError('未读取到该账号带明确点赞数的作品；可能需要登录、页面动态加载或格式变化。未记为检查成功')
    return {'owner':owner,'nickname':nickname,'url':url,'videos':list(videos.values()),'checked':now(),
            'coverage':'仅本次公开页面返回的作品，不能代表账号全量作品','profile_url':profile_url,'owner_aliases':sorted(aliases)}

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
            account['error']=result['error'];account['error_code']=result.get('error_code','public_page');self.save(value);return []
        if account['owner'] and account['owner']!=result['owner'] and account['owner'] not in result.get('owner_aliases',[]):
            if result.get('identity_verified') and account.get('identity_version')!='target-v2':
                archive={k:account.get(k) for k in ('owner','name','videos','last_success','alerted','unread')};archive['alerted']=list(account['alerted'])
                account.setdefault('archived_unverified',[]).append(archive);account['videos']={};account['unread']=[]
            else:raise ValueError('链接返回的账号与原记录不一致，未覆盖已有数据')
        if result.get('identity_verified'):account['identity_version']='target-v2'
        account.update(owner=result['owner'],name=result['nickname'] or account['name'],last_success=result['checked'],error='',error_code='',coverage=result['coverage'])
        if result.get('profile_url'):account['resolved_url']=public_url(result['profile_url'])
        events=[]
        for video in result['videos']:
            previous=account['videos'].get(video['id'],{});merged=previous|video
            for key in ('products','published','book_hints'):
                if not video.get(key) and previous.get(key):merged[key]=previous[key]
            if not video.get('products') and previous.get('products'):merged['book_status']=previous['book_status']
            if video.get('likes') is None and previous.get('likes') is not None:
                for key in ('likes','likes_lower_bound','likes_exact','likes_display','likes_checked'):merged[key]=previous.get(key,previous.get('likes') if key=='likes_lower_bound' else None)
            elif video.get('likes') is not None:merged['likes_checked']=video['checked']
            if video.get('likes') is None and previous.get('likes') is not None:merged['likes_checked']=previous.get('likes_checked') or previous.get('checked')
            if result.get('source_kind')=='detail':merged['details_checked']=video['checked']
            account['videos'][video['id']]=merged
            if is_hot(video) and video['id'] not in account['alerted']:
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
                pending=sorted((v for v in account['videos'].values() if not is_hot(v) and v['id'] not in seen),key=lambda v:v.get('checked',''))[:3]
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
