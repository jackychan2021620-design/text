"""Local transactional storage; independent product/video schedules and append-only histories."""
import hashlib
import json
import math
import os
import re
import shutil
import sqlite3
import tempfile
import zipfile
from datetime import date,datetime,timedelta
from pathlib import Path
from .model import SCHEMA
from . import analysis
from .grading import DEFAULTS,validate_rules

VERSION=1

def today():return date.today().isoformat()
def add_days(value,n):return (date.fromisoformat(value)+timedelta(days=n)).isoformat()
def data_dir():
    return Path(os.environ.get('BOOK_WORKBENCH_DATA_DIR') or (str(Path(os.environ.get('LOCALAPPDATA',Path.home()/'.local/share'))/'BookWorkbench')))

def encode(value):return json.dumps(value,ensure_ascii=False,allow_nan=False)

class Store:
    def __init__(self,root=None):
        self.root=Path(root or data_dir());self.root.mkdir(parents=True,exist_ok=True)
        (self.root/'assets').mkdir(exist_ok=True);(self.root/'backups').mkdir(exist_ok=True)
        self.path=self.root/'books.sqlite3';self.connect();self.migrate()
    def connect(self):
        self._analysis_token=None;self._analysis_cache={}
        self.db=sqlite3.connect(self.path);self.db.row_factory=sqlite3.Row
        self.db.execute('PRAGMA foreign_keys=ON');self.db.execute('PRAGMA journal_mode=WAL');self.db.execute('PRAGMA synchronous=FULL')
    def migrate(self):
        version=self.db.execute('PRAGMA user_version').fetchone()[0]
        if version>VERSION:raise ValueError('数据库版本较新，请升级应用')
        if version==0:
            statements=[]
            with self.db:
                for table,(_,fields) in SCHEMA.items():
                    columns=['id INTEGER PRIMARY KEY','created TEXT NOT NULL']
                    for key,_,kind,required in fields:
                        typ='REAL' if kind in ('number','percent') else 'INTEGER' if kind in ('integer','bool') or (isinstance(kind,str) and kind in SCHEMA) else 'TEXT'
                        foreign=f' REFERENCES {kind}(id) ON DELETE RESTRICT' if isinstance(kind,str) and kind in SCHEMA else ''
                        columns.append(f'{key} {typ}'+(' NOT NULL' if required else '')+foreign)
                    statements.append(f'CREATE TABLE {table} ({",".join(columns)});')
                self.db.executescript('BEGIN IMMEDIATE;'+''.join(statements)+'''
CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE snapshot_reminders(product_id INTEGER PRIMARY KEY REFERENCES product_links(id) ON DELETE CASCADE,due TEXT NOT NULL);
CREATE TABLE video_review_tasks(video_id INTEGER PRIMARY KEY REFERENCES video_tests(id) ON DELETE CASCADE,original_due TEXT NOT NULL,due TEXT NOT NULL,completed INTEGER NOT NULL DEFAULT 0);
CREATE TABLE video_review_reports(id INTEGER PRIMARY KEY, video_id INTEGER NOT NULL REFERENCES video_tests(id) ON DELETE RESTRICT, created TEXT NOT NULL, action TEXT NOT NULL, report TEXT NOT NULL, ad_id INTEGER REFERENCES advertising_records(id));
CREATE TABLE product_analyses(id INTEGER PRIMARY KEY,product_id INTEGER NOT NULL REFERENCES product_links(id) ON DELETE RESTRICT,snapshot_id INTEGER NOT NULL REFERENCES data_snapshots(id),created TEXT NOT NULL,result TEXT NOT NULL);
CREATE TABLE snapshot_images(id INTEGER PRIMARY KEY,snapshot_id INTEGER REFERENCES data_snapshots(id),ad_id INTEGER REFERENCES advertising_records(id),path TEXT NOT NULL,ocr_text TEXT);
CREATE TABLE ai_analysis_history(id INTEGER PRIMARY KEY,created TEXT NOT NULL,task TEXT NOT NULL,context TEXT NOT NULL,response TEXT NOT NULL,status TEXT NOT NULL);
CREATE TABLE entity_history(id INTEGER PRIMARY KEY,table_name TEXT NOT NULL,entity_id INTEGER NOT NULL,created TEXT NOT NULL,record TEXT NOT NULL);
CREATE INDEX snapshot_product ON data_snapshots(product_id,collected,id);
CREATE INDEX ad_video ON advertising_records(video_id,collected,id);
PRAGMA user_version=1;
COMMIT;
''')
        self.validate_db(self.db)
    @staticmethod
    def validate_db(db):
        if db.execute('PRAGMA user_version').fetchone()[0]!=VERSION:raise ValueError('不支持的数据库版本')
        expected=set(SCHEMA)|{'settings','snapshot_reminders','video_review_tasks','video_review_reports','product_analyses','snapshot_images','ai_analysis_history','entity_history'}
        tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not expected<=tables:raise ValueError('数据库表不完整')
        for table,(_,fields) in SCHEMA.items():
            cols={r[1] for r in db.execute(f'PRAGMA table_info({table})')}
            if not {'id','created',*(f[0] for f in fields)}<=cols:raise ValueError('数据库字段不完整')
        auxiliary={
            'settings':{'key','value'},'snapshot_reminders':{'product_id','due'},
            'video_review_tasks':{'video_id','original_due','due','completed'},
            'video_review_reports':{'id','video_id','created','action','report','ad_id'},
            'product_analyses':{'id','product_id','snapshot_id','created','result'},
            'snapshot_images':{'id','snapshot_id','ad_id','path','ocr_text'},
            'ai_analysis_history':{'id','created','task','context','response','status'},
            'entity_history':{'id','table_name','entity_id','created','record'}}
        for table,required in auxiliary.items():
            if not required<={r[1] for r in db.execute(f'PRAGMA table_info({table})')}:raise ValueError('数据库辅助表字段不完整')
        if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok' or db.execute('PRAGMA foreign_key_check').fetchall():raise ValueError('数据库完整性检查未通过')
    def close(self):self.db.close()
    @staticmethod
    def active_clause(table,alias='t'):
        if table in ('data_snapshots','advertising_records'):
            return f"NOT EXISTS(SELECT 1 FROM settings trash WHERE trash.key='deleted:{table}:'||{alias}.id)"
        if table=='product_analyses':
            return f"NOT EXISTS(SELECT 1 FROM settings trash WHERE trash.key='deleted:data_snapshots:'||{alias}.snapshot_id)"
        if table=='video_review_reports':
            return f"({alias}.ad_id IS NULL OR NOT EXISTS(SELECT 1 FROM settings trash WHERE trash.key='deleted:advertising_records:'||{alias}.ad_id))"
        return '1'
    def rows(self,table,include_deleted=False):
        if table not in set(SCHEMA)|{'video_review_reports','ai_analysis_history','product_analyses','entity_history'}:raise ValueError('未知表')
        where='1' if include_deleted else self.active_clause(table)
        return [dict(r) for r in self.db.execute(f'SELECT t.* FROM {table} t WHERE {where} ORDER BY t.id DESC')]
    def page(self,table,search='',category='',page=0,size=50):
        if table not in SCHEMA or page<0 or not 1<=size<=100:raise ValueError('无效的分页查询')
        joins={'books':'JOIN books b ON b.id=t.id',
               'product_links':'JOIN books b ON b.id=t.book_id',
               'data_snapshots':'JOIN product_links p ON p.id=t.product_id JOIN books b ON b.id=p.book_id',
               'video_tests':'JOIN product_links p ON p.id=t.product_id JOIN books b ON b.id=p.book_id',
               'advertising_records':'JOIN video_tests v ON v.id=t.video_id JOIN product_links p ON p.id=v.product_id JOIN books b ON b.id=p.book_id'}
        where=[self.active_clause(table)];params=[]
        if category:where.append('b.category=?');params.append(category)
        if search:
            fields=['t.id','b.name','b.author','b.category']+['t.'+k for k,_,kind,_ in SCHEMA[table][1] if kind not in ('image','file','curve') and k!='ocr_text']
            where.append('('+' OR '.join(f"instr(lower(COALESCE({f},'')),lower(?))>0" for f in fields)+')');params.extend([search]*len(fields))
        base=f'FROM {table} t {joins[table]} WHERE '+ ' AND '.join(where)
        total=self.db.execute('SELECT count(*) '+base,params).fetchone()[0]
        rows=[dict(r) for r in self.db.execute('SELECT t.* '+base+' ORDER BY t.id DESC LIMIT ? OFFSET ?',(*params,size,page*size))]
        return rows,total
    def history_page(self,table,page=0,size=50):
        if table not in ('video_review_reports','product_analyses','ai_analysis_history') or page<0 or not 1<=size<=100:raise ValueError('无效的历史查询')
        where=self.active_clause(table)
        total=self.db.execute(f'SELECT count(*) FROM {table} t WHERE {where}').fetchone()[0]
        return [dict(r) for r in self.db.execute(f'SELECT t.* FROM {table} t WHERE {where} ORDER BY t.id DESC LIMIT ? OFFSET ?',(size,page*size))],total
    def deleted_rows(self,table):
        if table not in ('data_snapshots','advertising_records'):raise ValueError('该档案没有回收站')
        return [dict(r) for r in self.db.execute(f'SELECT t.* FROM {table} t WHERE NOT ({self.active_clause(table)}) ORDER BY t.id DESC')]
    def refresh_snapshot_state(self,table,row):
        if table=='data_snapshots':
            latest=self.latest(table,'product_id',row['product_id'])
            if latest:
                self.db.execute('INSERT INTO snapshot_reminders VALUES (?,?) ON CONFLICT(product_id) DO UPDATE SET due=excluded.due',(row['product_id'],add_days(latest['collected'],15)))
            else:self.db.execute('DELETE FROM snapshot_reminders WHERE product_id=?',(row['product_id'],))
        else:
            # Historical reports remain intact, while a deleted evidence record
            # cannot count as a currently completed review or current advice.
            valid=self.db.execute(f"SELECT 1 FROM video_review_reports t WHERE t.video_id=? AND t.action='完成复盘' AND {self.active_clause('video_review_reports')} LIMIT 1",(row['video_id'],)).fetchone()
            self.db.execute('UPDATE video_review_tasks SET completed=? WHERE video_id=?',(int(bool(valid)),row['video_id']))
    def restore_deleted(self,table,id):
        if table not in ('data_snapshots','advertising_records'):raise ValueError('该档案没有回收站')
        row=self.get(table,id);id=row['id']
        with self.db:
            removed=self.db.execute('DELETE FROM settings WHERE key=?',(f'deleted:{table}:{id}',)).rowcount
            if removed:
                self.db.execute('INSERT INTO entity_history(table_name,entity_id,created,record) VALUES (?,?,?,?)',(table,id,datetime.now().isoformat(),encode({'action':'restore','record':row})))
                self.refresh_snapshot_state(table,row)
    def get(self,table,id):
        if table not in SCHEMA:raise ValueError('未知表')
        row=self.db.execute(f'SELECT * FROM {table} WHERE id=?',(id,)).fetchone()
        if not row:raise ValueError('记录不存在')
        return dict(row)
    def setting(self,key,default=''):
        r=self.db.execute('SELECT value FROM settings WHERE key=?',(key,)).fetchone();return r[0] if r else default
    def settings(self,values):
        with self.db:
            self.db.executemany('INSERT INTO settings VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',[(k,str(v)) for k,v in values.items()])
    def attach(self,path):
        source=Path(path)
        if not source.is_file() or source.stat().st_size>200*1024**2:raise ValueError('附件不存在或超过200MB')
        digest=hashlib.sha256(source.read_bytes()).hexdigest();suffix=source.suffix.lower()
        if len(suffix)>10 or not suffix[1:].isalnum():suffix='.bin'
        dest=self.root/'assets'/(digest+suffix)
        if not dest.exists():
            with tempfile.NamedTemporaryFile(dir=self.root,prefix='attachment-',delete=False) as temporary:staging=Path(temporary.name)
            try:
                shutil.copyfile(source,staging)
                if hashlib.sha256(staging.read_bytes()).hexdigest()!=digest:raise ValueError('附件在复制时发生变化，请重新选择')
                os.replace(staging,dest)
            finally:staging.unlink(missing_ok=True)
        return dest.relative_to(self.root).as_posix()
    def asset(self,value):
        p=(self.root/value).resolve()
        if p.parent!=(self.root/'assets').resolve() or not p.is_file():raise ValueError('附件路径不安全或文件已丢失')
        return p
    def normalize(self,table,values):
        result={}
        for key,label,kind,required in SCHEMA[table][1]:
            value=values.get(key)
            if isinstance(value,str) and key!='ocr_text':value=value.strip()
            if value is None or value=='':
                if required:raise ValueError(label+'不能为空（未知值请留空，仅非必填字段允许）')
                result[key]=None;continue
            if isinstance(kind,list):
                if value not in kind:raise ValueError(label+'选项无效')
            elif kind in ('number','percent','integer','bool') or kind in SCHEMA:
                try:
                    number=float(value)
                    if not math.isfinite(number) or number<0:raise ValueError()
                    if kind in ('integer','bool') or kind in SCHEMA:
                        if not number.is_integer():raise ValueError()
                        value=int(number)
                    else:value=number
                except (ValueError,TypeError,OverflowError):raise ValueError(label+'需要有效的非负数')
                if kind=='percent' and value>100:raise ValueError('比例应在0～100之间')
                if kind=='bool' and value not in (0,1):raise ValueError('确认值无效')
                if kind in SCHEMA:self.get(kind,value)
            elif kind=='date':date.fromisoformat(value)
            elif kind=='curve':
                vals=json.loads(value) if value.startswith('[') else [float(x.strip()) for x in value.replace('，',',').split(',')]
                if not isinstance(vals,list) or any(not isinstance(x,(float,int)) or not math.isfinite(x) or x<0 for x in vals):raise ValueError('曲线应为非负每日销量数组')
                value=encode(vals)
            elif kind in ('image','file'):
                if not value.startswith('assets/'):
                    value=self.attach(value)
                self.asset(value)
                if kind=='image':
                    from PySide6.QtGui import QImage
                    if QImage(str(self.asset(value))).isNull():raise ValueError('无法读取图片')
            result[key]=value
        if table=='data_snapshots':
            if not result['confirmed']:raise ValueError('请人工核对数据并勾选确认')
            if result['period_days']<=0:raise ValueError('统计周期必须大于0')
            if result['sellers'] is not None and result['creators'] is not None and result['sellers']>result['creators']:raise ValueError('出单人数不能超过带货人数')
        if table=='advertising_records' and result['screenshot'] and not result['confirmed']:raise ValueError('截图数据需要人工核对确认')
        return result
    def save(self,table,values,id=None):
        if id and table in ('data_snapshots','advertising_records'):raise ValueError('快照不可覆盖，请新增更正快照保留历史')
        result=self.normalize(table,values)
        with self.db:
            if id:
                self.get(table,id)
                self.db.execute(f'UPDATE {table} SET '+','.join(k+'=?' for k in result)+' WHERE id=?',(*result.values(),id))
            else:
                cols=['created',*result];vals=[datetime.now().isoformat(timespec='seconds'),*result.values()]
                id=self.db.execute(f'INSERT INTO {table} ({",".join(cols)}) VALUES ({",".join("?" for _ in cols)})',vals).lastrowid
            self.db.execute('INSERT INTO entity_history(table_name,entity_id,created,record) VALUES (?,?,?,?)',(table,id,datetime.now().isoformat(),encode(result)))
            if table=='data_snapshots':
                latest=self.latest('data_snapshots','product_id',result['product_id'])
                due=add_days(latest['collected'],15)
                self.db.execute('INSERT INTO snapshot_reminders VALUES (?,?) ON CONFLICT(product_id) DO UPDATE SET due=excluded.due',(result['product_id'],due))
                self.db.execute('INSERT INTO product_analyses(product_id,snapshot_id,created,result) VALUES (?,?,?,?)',(result['product_id'],id,today(),encode(self.analyze(result['product_id']))))
            if table=='video_tests':
                due=result['review_override'] or add_days(result['ad_started'] or result['published'],5)
                old=self.db.execute('SELECT * FROM video_review_tasks WHERE video_id=?',(id,)).fetchone()
                if not old:self.db.execute('INSERT INTO video_review_tasks VALUES (?,?,?,0)',(id,due,due))
                else:
                    previous=json.loads(self.db.execute("SELECT record FROM entity_history WHERE table_name='video_tests' AND entity_id=? ORDER BY id DESC LIMIT 1 OFFSET 1",(id,)).fetchone()[0])
                    if any(previous.get(k)!=result[k] for k in ('review_override','ad_started','published')):
                        self.db.execute('UPDATE video_review_tasks SET due=?,completed=0 WHERE video_id=?',(due,id))
                        self.log_review(id,'修改复盘日期',{'新日期':due,'原始日期':old['original_due']})
            if table in ('data_snapshots','advertising_records') and result['screenshot']:
                self.db.execute('INSERT INTO snapshot_images(snapshot_id,ad_id,path,ocr_text) VALUES (?,?,?,?)',(id if table=='data_snapshots' else None,id if table=='advertising_records' else None,result['screenshot'],result['ocr_text']))
        return id
    def delete(self,table,id):
        row=self.get(table,id);id=row['id']
        if table in ('data_snapshots','advertising_records'):
            with self.db:
                key=f'deleted:{table}:{id}'
                if self.db.execute('SELECT 1 FROM settings WHERE key=?',(key,)).fetchone():return
                self.db.execute('INSERT INTO settings VALUES (?,?)',(key,encode({'deleted_at':datetime.now().isoformat()})))
                self.db.execute('INSERT INTO entity_history(table_name,entity_id,created,record) VALUES (?,?,?,?)',(table,id,datetime.now().isoformat(),encode({'action':'move_to_trash','record':row})))
                self.refresh_snapshot_state(table,row)
            return
        with self.db:
            self.db.execute('INSERT INTO entity_history(table_name,entity_id,created,record) VALUES (?,?,?,?)',(table,id,today(),encode({'deleted':row})))
            self.db.execute(f'DELETE FROM {table} WHERE id=?',(id,))
    def latest(self,table,key,id):
        if (table,key) not in [('data_snapshots','product_id'),('advertising_records','video_id')]:raise ValueError('不支持的查询')
        r=self.db.execute(f'SELECT t.* FROM {table} t WHERE t.{key}=? AND {self.active_clause(table)} ORDER BY t.collected DESC,t.id DESC LIMIT 1',(id,)).fetchone()
        return dict(r) if r else None
    def analyze(self,id):
        token=(self.db.total_changes,encode(self.grading_rules()))
        if token!=self._analysis_token:
            books={b['id']:b for b in self.rows('books')};products=self.rows('product_links')
            snapshots={r['product_id']:dict(r) for r in self.db.execute(f"SELECT * FROM (SELECT t.*,row_number() OVER(PARTITION BY product_id ORDER BY collected DESC,id DESC) rank FROM data_snapshots t WHERE {self.active_clause('data_snapshots')}) WHERE rank=1")}
            categories={};by_product={}
            for p in products:
                s=snapshots.get(p['id']);category=books[p['book_id']]['category'];by_product[p['id']]=category
                if category and s and s['period_days']==90:categories.setdefault(category,[]).append(s)
            rules=self.grading_rules()
            self._analysis_cache={p['id']:analysis.product(snapshots.get(p['id']),categories.get(by_product[p['id']],[]),rules) for p in products}
            self._analysis_token=token
        if id not in self._analysis_cache:self.get('product_links',id)
        return dict(self._analysis_cache[id])
    def grading_rules(self):
        return validate_rules({k:self.setting('grade_'+k,str(v)) for k,v in DEFAULTS.items()})
    def grading_results(self,book_id=None):
        out=[]
        for p in self.rows('product_links'):
            if book_id is not None and p['book_id']!=book_id:continue
            b=self.get('books',p['book_id']);a=self.analyze(p['id'])
            out.append({'商品ID':p['id'],'图书':b['name'],'分类':b['category'],'分析':a})
        return out
    def snapshot_diff(self,id):
        ss=[dict(r) for r in self.db.execute(f'SELECT t.* FROM data_snapshots t WHERE t.product_id=? AND {self.active_clause("data_snapshots")} ORDER BY t.collected DESC,t.id DESC LIMIT 2',(id,))]
        if len(ss)<2:return {'说明':'需要至少两次快照'}
        return {'当前':ss[0],'上次':ss[1],'滚动指标差值':{k:ss[0][k]-ss[1][k] if ss[0][k] is not None and ss[1][k] is not None else None for k in ('creators','sellers','sales')},'说明':'滚动窗口进入和退出数据同时变化，差值不等于15天实际销量；不同周期不可直接比较'}
    def compare(self,ids,order='稳定出单机会'):
        if not 2<=len(set(ids))<=10:raise ValueError('请选择2～10个不同商品')
        items=[]
        for id in ids:
            p=self.get('product_links',id);s=self.latest('data_snapshots','product_id',id);a=self.analyze(id)
            metric={'稳定出单机会':a.get('达人出单率'),'爆单容量':a.get('出单达人人均销量'),'新创作者进入机会':a.get('参与达人人均销量')}[order]
            items.append({'商品':p,'图书':self.get('books',p['book_id'])['name'],'快照':s,'分析':a,'排序值':metric,'理由':order+'的描述性代理指标：'+{'稳定出单机会':'达人出单率','爆单容量':'出单达人人均销量','新创作者进入机会':'参与达人人均销量'}[order]+'；不同类别、周期不可直接推断，粉丝与流量结构未知'})
        return sorted(items,key=lambda r:(r['排序值'] is not None,r['排序值'] or 0),reverse=True)
    def video_comparison(self,book_id):
        out=[]
        for v in self.rows('video_tests'):
            if self.get('product_links',v['product_id'])['book_id']!=book_id:continue
            ad=self.latest('advertising_records','video_id',v['id']) or {};task=dict(self.db.execute('SELECT * FROM video_review_tasks WHERE video_id=?',(v['id'],)).fetchone())
            report=self.db.execute(f"SELECT t.report FROM video_review_reports t WHERE t.video_id=? AND t.action='完成复盘' AND {self.active_clause('video_review_reports')} ORDER BY t.id DESC LIMIT 1",(v['id'],)).fetchone()
            out.append({'视频':v,'广告':ad,'实际GMV/消耗':analysis.ratio(ad.get('actual_gmv'),ad.get('spend')),'消耗状态':'有消耗' if ad.get('spend') else '无有效消耗数据','任务':task,'复盘':json.loads(report[0]) if report else None})
        return out
    def log_review(self,id,action,report,ad_id=None):
        self.db.execute('INSERT INTO video_review_reports(video_id,created,action,report,ad_id) VALUES (?,?,?,?,?)',(id,datetime.now().isoformat(timespec='seconds'),action,encode(report),ad_id))
    def defer(self,id,days):
        if days not in (2,3):raise ValueError('仅支持延后2或3天')
        task=self.db.execute('SELECT * FROM video_review_tasks WHERE video_id=?',(id,)).fetchone()
        due=add_days(max(today(),task['due']),days)
        with self.db:
            self.log_review(id,'延后提醒',{'原提醒日期':task['due'],'新日期':due})
            self.db.execute('UPDATE video_review_tasks SET due=?,completed=0 WHERE video_id=?',(due,id))
        return due
    def review(self,id):
        v=self.get('video_tests',id);p=self.get('product_links',v['product_id']);ad=self.latest('advertising_records','video_id',id) or {}
        peers=[r['广告'] for r in self.video_comparison(p['book_id']) if r['视频']['id']!=id]
        result=analysis.review(ad,peers,self.analyze(p['id']),float(self.setting('min_spend','100')),int(self.setting('min_orders','5')),float(self.setting('target_ratio','1')))
        # Similar category/account evidence is retained separately, never merged into same-book sample.
        category=self.get('books',p['book_id'])['category'];similar=[]
        for other in self.rows('video_tests'):
            op=self.get('product_links',other['product_id']);ob=self.get('books',op['book_id'])
            if other['id']!=id and other['account']==v['account'] and ob['category']==category:
                similar.append({'视频':other['id'],'图书':ob['name'],'广告':self.latest('advertising_records','video_id',other['id'])})
        result['同账号同类历史']=similar;result['同书对比']=self.video_comparison(p['book_id'])
        # Avoid recursive historical report expansion.
        for item in result['同书对比']:item.pop('复盘',None)
        return result
    def complete_review(self,id,notes=''):
        r=self.review(id);r['人工复盘备注']=notes;r['下一次复盘时间']='本轮已完成；如需补充数据可延后2或3天重新开启提醒'
        ad=self.latest('advertising_records','video_id',id)
        with self.db:
            self.log_review(id,'完成复盘',r,ad['id'] if ad else None)
            self.db.execute('UPDATE video_review_tasks SET completed=1 WHERE video_id=?',(id,))
        return r
    def reminders(self,on=None):
        on=on or today();out={'商品15天':[],'视频5天':[]}
        for table,key,label in [('snapshot_reminders','product_id','商品15天'),('video_review_tasks','video_id','视频5天')]:
            for row in self.db.execute(f'SELECT * FROM {table}'):
                r=dict(row)
                if r.get('completed'):continue
                days=(date.fromisoformat(r['due'])-date.fromisoformat(on)).days
                r.update(剩余天数=days,分组='已逾期' if days<0 else '今日' if days==0 else '即将到期' if days<=3 else '待办')
                if label=='商品15天':
                    p=self.get('product_links',r[key]);r['名称']=self.get('books',p['book_id'])['name']+f' · 商品#{p["id"]}'
                else:
                    v=self.get('video_tests',r[key]);p=self.get('product_links',v['product_id']);r['名称']=self.get('books',p['book_id'])['name']+' · '+v['code']+' '+v['name']
                out[label].append(r)
            out[label].sort(key=lambda r:r['due'])
        return out
    def context(self,book_id=None):
        result= {'图书':self.rows('books'),'商品':[{'档案':p,'分析':self.analyze(p['id'])} for p in self.rows('product_links')],
        '快照':self.rows('data_snapshots'),'视频':self.rows('video_tests'),'广告':self.rows('advertising_records'),
        '复盘':self.rows('video_review_reports'),'提醒':self.reminders(),
        '分档规则':self.grading_rules(),'历史限制':'累计广告快照按采集日取最新，不相加；比较需考虑周期、账号、品类、投放环境、视频数量；相关性不等于因果'}
        result['快照']=[{k:v for k,v in row.items() if k not in ('ocr_text','screenshot','curve')} for row in result['快照']]
        result['广告']=[{k:v for k,v in row.items() if k not in ('ocr_text','screenshot')} for row in result['广告']]
        if book_id is not None:
            self.get('books',book_id)
            result['图书']=[b for b in result['图书'] if b['id']==book_id]
            result['商品']=[p for p in result['商品'] if p['档案']['book_id']==book_id]
            products={p['档案']['id'] for p in result['商品']}
            result['快照']=[r for r in result['快照'] if r['product_id'] in products]
            result['视频']=[v for v in result['视频'] if v['product_id'] in products]
            videos={v['id'] for v in result['视频']}
            result['广告']=[a for a in result['广告'] if a['video_id'] in videos]
            result['复盘']=[r for r in result['复盘'] if r['video_id'] in videos]
            result['提醒']['商品15天']=[r for r in result['提醒']['商品15天'] if r['product_id'] in products]
            result['提醒']['视频5天']=[r for r in result['提醒']['视频5天'] if r['video_id'] in videos]
            result['范围说明']='仅所选图书及其商品、视频；不包含其他图书历史，跨书比较资料不足'
        return result
    def backup(self,target):
        target=Path(target)
        if target.resolve()==self.path.resolve() or self.root/'assets' in target.resolve().parents:raise ValueError('备份目标不能覆盖数据库或附件')
        with tempfile.TemporaryDirectory() as tmp:
            dbpath=Path(tmp)/'books.sqlite3'
            dest=sqlite3.connect(dbpath);self.db.backup(dest);dest.close()
            files={'books.sqlite3':dbpath}
            for p in (self.root/'assets').iterdir():
                if p.is_file() and not p.is_symlink():files['assets/'+p.name]=p
            hashes={name:hashlib.sha256(p.read_bytes()).hexdigest() for name,p in files.items()}
            target.parent.mkdir(parents=True,exist_ok=True)
            staging=target.with_name(target.name+'.tmp')
            with zipfile.ZipFile(staging,'w',zipfile.ZIP_DEFLATED) as z:
                for name,p in files.items():z.write(p,name)
                z.writestr('manifest.json',encode({'version':VERSION,'sha256':hashes}))
            os.replace(staging,target)
    def daily_backup(self):
        target=self.root/'backups'/('auto-'+today()+'.zip')
        if not target.exists():self.backup(target)
        for p in sorted((self.root/'backups').glob('auto-*.zip'),reverse=True)[30:]:p.unlink()
    def restore(self,source):
        with tempfile.TemporaryDirectory() as tmp:
            tmp=Path(tmp)
            with zipfile.ZipFile(source) as z:
                entries=z.infolist();names=[i.filename for i in entries]
                if len(names)!=len(set(names)) or len(names)>10000 or sum(i.file_size for i in entries)>2*1024**3:raise ValueError('备份重复文件、过大或条目过多')
                for i in entries:
                    path=Path(i.filename)
                    if path.is_absolute() or '..' in path.parts or '\\' in i.filename or not (i.filename in ('manifest.json','books.sqlite3') or re.fullmatch(r'assets/[0-9a-f]{64}\.[a-z0-9]{1,9}',i.filename)):raise ValueError('备份路径不安全')
                manifest=json.loads(z.read('manifest.json'))
                hashes=manifest['sha256']
                if manifest['version']!=VERSION or set(names)!=(set(hashes)|{'manifest.json'}) or 'books.sqlite3' not in hashes:raise ValueError('备份清单不完整')
                for name,digest in hashes.items():
                    raw=z.read(name)
                    if hashlib.sha256(raw).hexdigest()!=digest:raise ValueError('备份哈希校验失败')
                    p=tmp/name;p.parent.mkdir(exist_ok=True,parents=True);p.write_bytes(raw)
            candidate=sqlite3.connect(tmp/'books.sqlite3')
            try:
                self.validate_db(candidate)
                for table,(_,fields) in SCHEMA.items():
                    for key,_,kind,_ in fields:
                        if kind in ('image','file'):
                            for row in candidate.execute(f'SELECT {key} FROM {table} WHERE {key} IS NOT NULL'):
                                if row[0] not in hashes or not row[0].startswith('assets/'):raise ValueError('备份附件缺失')
            finally:candidate.close()
            safety=self.root/'backups'/('before-restore-'+datetime.now().strftime('%Y%m%d%H%M%S%f')+'.zip');self.backup(safety)
            for name in hashes:
                if name.startswith('assets/'):
                    dest=self.root/name
                    if dest.exists() and hashlib.sha256(dest.read_bytes()).hexdigest()!=hashes[name]:raise ValueError('本地附件同名冲突')
                    if not dest.exists():shutil.copyfile(tmp/name,dest)
            self.db.execute('PRAGMA wal_checkpoint(TRUNCATE)');self.close()
            try:
                staged=self.root/'restore-staged.sqlite3';shutil.copyfile(tmp/'books.sqlite3',staged);os.replace(staged,self.path)
            finally:self.connect()
        return safety
