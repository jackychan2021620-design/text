from __future__ import annotations
import csv
import hashlib
import json
import os
import shutil
import sqlite3
import uuid
import tempfile
import zipfile
import re
from contextlib import contextmanager,closing
from datetime import date,datetime,timedelta
from decimal import Decimal,InvalidOperation,ROUND_HALF_UP
from pathlib import Path
from .model import BUSINESSES,PLATFORMS,STAGES,TABLES,PIECE_FIELDS,FEEDBACK_FIELDS

def data_dir():
    if os.environ.get('ZAOWU_STUDIO_DATA_DIR'):
        return Path(os.environ['ZAOWU_STUDIO_DATA_DIR']).expanduser().resolve()
    return Path(os.environ.get('LOCALAPPDATA',Path.home()/'.local'/'share'))/'ZaowuContentStudio'

def now(): return datetime.now().isoformat(timespec='seconds')

def money(value):
    try:
        n=Decimal(str(value))
        if not n.is_finite() or abs(n)>999999999: raise ValueError('金额超出范围')
        return int((n*100).quantize(Decimal('1'),rounding=ROUND_HALF_UP))
    except InvalidOperation as exc: raise ValueError('请输入有效金额') from exc

def display_money(value): return '未记录' if value is None else f'¥{value/100:,.2f}'

def validate(fields,values):
    out={}
    for field in fields:
        v=values.get(field.key)
        if field.kind in ('metric','money_optional','offer','reference'):
            if v is None or v=='': v=None
            else:
                try:
                    n=Decimal(str(v))
                    if not n.is_finite() or n!=n.to_integral_value() or abs(n)>99999999999 or (n<0 and field.key!='contribution'):
                        raise ValueError()
                    v=int(n)
                except (ValueError,InvalidOperation): raise ValueError(field.label+'：数值格式不正确')
        elif field.kind=='bool':
            if v not in (None,False,True,0,1): raise ValueError('布尔值无效')
            v=int(bool(v))
        else:
            v=str(v or '').strip()
            if field.required and not v: raise ValueError('请填写'+field.label)
            if len(v)>50000: raise ValueError(field.label+'过长')
            if field.kind=='choice' and v not in field.options: raise ValueError('请选择'+field.label)
            if field.kind in ('date','optional_date') and v:
                if date.fromisoformat(v).isoformat()!=v: raise ValueError('日期格式应为 YYYY-MM-DD')
            if field.kind=='date' and not v: raise ValueError('请填写'+field.label)
        out[field.key]=v
    return out

class Store:
    def __init__(self,root=None):
        self.root=Path(root) if root else data_dir()
        self.root.mkdir(parents=True,exist_ok=True)
        self.path=self.root/'studio.sqlite3'
        self.db=sqlite3.connect(self.path,timeout=15)
        self.db.row_factory=sqlite3.Row
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.execute('PRAGMA journal_mode=WAL')
        self.migrate()

    def migrate(self):
        version=self.db.execute('PRAGMA user_version').fetchone()[0]
        if version>1: raise ValueError('资料版本较新，请更新软件')
        for table,(_,fields) in TABLES.items():
            columns=[f'"{f.key}" '+('INTEGER' if f.kind=='bool' else 'TEXT') for f in fields]
            self.db.execute(f'CREATE TABLE IF NOT EXISTS "{table}" (id INTEGER PRIMARY KEY,{",".join(columns)},updated_at TEXT NOT NULL)')
        columns=[]
        for f in PIECE_FIELDS:
            kind='INTEGER' if f.kind in ('offer','reference') else 'TEXT'
            ref=' REFERENCES offers(id) ON DELETE SET NULL' if f.kind=='offer' else ' REFERENCES "references"(id) ON DELETE SET NULL' if f.kind=='reference' else ''
            columns.append(f'"{f.key}" {kind}{ref}')
        self.db.execute(f'CREATE TABLE IF NOT EXISTS pieces (id INTEGER PRIMARY KEY,{",".join(columns)},stage TEXT NOT NULL DEFAULT "选题",version INTEGER NOT NULL DEFAULT 1,updated_at TEXT NOT NULL)')
        columns=[f'"{f.key}" '+('INTEGER' if f.kind in ('metric','money_optional') else 'TEXT') for f in FEEDBACK_FIELDS]
        self.db.execute(f'CREATE TABLE IF NOT EXISTS feedback (id INTEGER PRIMARY KEY,piece_id INTEGER NOT NULL REFERENCES pieces(id) ON DELETE CASCADE,{",".join(columns)},created_at TEXT NOT NULL)')
        self.db.executescript('''
          CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY,value TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS assets (id INTEGER PRIMARY KEY,business TEXT NOT NULL,name TEXT NOT NULL,path TEXT NOT NULL,kind TEXT NOT NULL,description TEXT NOT NULL DEFAULT '',created_at TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS piece_assets (piece_id INTEGER NOT NULL REFERENCES pieces(id) ON DELETE CASCADE,asset_id INTEGER NOT NULL REFERENCES assets(id) ON DELETE RESTRICT,PRIMARY KEY(piece_id,asset_id));
          CREATE TABLE IF NOT EXISTS ai_runs (id INTEGER PRIMARY KEY,task TEXT NOT NULL,business TEXT NOT NULL,context TEXT NOT NULL,output TEXT NOT NULL DEFAULT '',status TEXT NOT NULL,created_at TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS audit (id INTEGER PRIMARY KEY,action TEXT NOT NULL,entity TEXT NOT NULL,row_id INTEGER,created_at TEXT NOT NULL);
          CREATE INDEX IF NOT EXISTS piece_workflow ON pieces(business,stage,plan_date);
          CREATE INDEX IF NOT EXISTS feedback_piece ON feedback(piece_id,observed_date,id);
          PRAGMA user_version=1;
        ''')
        self.db.commit()

    @contextmanager
    def transaction(self):
        token='t'+uuid.uuid4().hex
        self.db.execute('SAVEPOINT '+token)
        try:
            yield
            self.db.execute('RELEASE '+token)
        except Exception:
            self.db.execute('ROLLBACK TO '+token)
            self.db.execute('RELEASE '+token)
            raise

    def setting(self,key,default=''):
        r=self.db.execute('SELECT value FROM settings WHERE key=?',(key,)).fetchone()
        return r[0] if r else default

    def set_setting(self,key,value):
        with self.db: self.db.execute('INSERT INTO settings VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(key,str(value)))

    def rows(self,table,business=None):
        if table not in set(TABLES)|{'pieces','assets','ai_runs'}: raise ValueError('未知资料类型')
        where=' WHERE business=?' if business else ''
        return [dict(r) for r in self.db.execute(f'SELECT * FROM "{table}"'+where+' ORDER BY id DESC',(business,) if business else ())]

    def get(self,table,row_id):
        if table not in set(TABLES)|{'pieces','assets','ai_runs'}: raise ValueError('未知资料类型')
        r=self.db.execute(f'SELECT * FROM "{table}" WHERE id=?',(row_id,)).fetchone()
        if not r: raise ValueError('记录已不存在，请刷新')
        return dict(r)

    def audit(self,action,table,row_id):
        self.db.execute('INSERT INTO audit(action,entity,row_id,created_at) VALUES (?,?,?,?)',(action,table,row_id,now()))

    def save(self,table,values,row_id=None,expected_version=None):
        fields=PIECE_FIELDS if table=='pieces' else TABLES[table][1]
        values=validate(fields,values)
        if table=='learnings' and values['level']!='待验证解释' and not values['basis']:
            raise ValueError('观察事实或已验证结论需要填写证据和适用条件')
        if table=='pieces':
            for key,target in [('offer_id','offers'),('reference_id','references')]:
                if values[key] and self.get(target,values[key])['business']!=values['business']:
                    raise ValueError('关联资料不属于当前业务')
        values['updated_at']=now()
        with self.transaction():
            if row_id is None:
                keys=','.join('"'+k+'"' for k in values)
                row_id=self.db.execute(f'INSERT INTO "{table}" ({keys}) VALUES ({",".join("?" for _ in values)})',tuple(values.values())).lastrowid
            else:
                assignments=','.join('"'+k+'"=?' for k in values)
                condition='id=?'
                args=(*values.values(),row_id)
                if table=='pieces':
                    assignments+=',version=version+1'
                    if expected_version is not None:
                        condition+=' AND version=?'
                        args+= (expected_version,)
                cur=self.db.execute(f'UPDATE "{table}" SET {assignments} WHERE {condition}',args)
                if cur.rowcount!=1: raise ValueError('内容已经更新，请重新打开后再保存，避免覆盖修改')
            self.audit('save',table,row_id)
        return row_id

    def delete(self,table,row_id):
        if table not in set(TABLES)|{'pieces','assets','ai_runs'}: raise ValueError('未知资料类型')
        with self.transaction():
            self.db.execute(f'DELETE FROM "{table}" WHERE id=?',(row_id,))
            self.audit('delete',table,row_id)

    def advance(self,piece_id):
        p=self.get('pieces',piece_id)
        stage=p['stage']
        if stage=='选题':
            if not p['audience'] or not p['hypothesis']: raise ValueError('先写清楚希望谁看到，以及这条内容准备验证什么')
        elif stage=='素材':
            if not p['offer_id']: raise ValueError('请关联真实产品 / 服务，避免生成无依据的承诺')
            if not self.assets_for(piece_id) and not p['angle']: raise ValueError('请选择素材，或说明准备使用的表达方式')
        elif stage=='草稿':
            if not p['title'] or not (p['body'] or p['script']): raise ValueError('请完成标题以及正文或脚本')
            if not p['cta']: raise ValueError('请说明顾客下一步怎样咨询或购买')
            if any('【待确认' in p[key] for key in ('title','cover','body','script','cta')):raise ValueError('草稿还有待确认内容，请核实替换后再进入待发布')
        elif stage=='待发布':
            if not p['published_date']: raise ValueError('实际发布后填写发布日期，再确认已发布')
        elif stage=='已发布':
            feedback=self.latest_feedback(piece_id)
            if not feedback or not feedback['facts'] or not feedback['next_action']:
                raise ValueError('请先记录反馈事实及下一步调整，再完成复盘')
        else: return stage
        following=STAGES[STAGES.index(stage)+1]
        with self.transaction():
            self.db.execute('UPDATE pieces SET stage=?,version=version+1,updated_at=? WHERE id=?',(following,now(),piece_id))
            self.audit('advance:'+following,'pieces',piece_id)
        return following

    def next_piece(self,business=None):
        pieces=[p for p in self.rows('pieces',business) if p['stage']!='已复盘']
        return min(pieces,key=lambda p:(p['plan_date'] or '9999',-STAGES.index(p['stage']),p['id'])) if pieces else None

    def add_asset(self,source,business,description=''):
        if business not in BUSINESSES: raise ValueError('业务无效')
        source=Path(source)
        suffix=source.suffix.lower()
        kind='图片' if suffix in ('.jpg','.jpeg','.png','.webp','.bmp') else '视频' if suffix in ('.mp4','.mov','.mkv','.webm') else ''
        if not kind: raise ValueError('请选择常见图片或视频文件')
        if source.stat().st_size>300*1024*1024: raise ValueError('单个素材最大 300MB')
        with source.open('rb') as file: digest=hashlib.file_digest(file,'sha256').hexdigest()
        folder=self.root/'assets'
        folder.mkdir(exist_ok=True)
        target=folder/(digest+suffix)
        if not target.exists(): shutil.copy2(source,target)
        existing=self.db.execute('SELECT id FROM assets WHERE path=? AND business=?',(str(target),business)).fetchone()
        if existing: return existing[0]
        with self.db:
            return self.db.execute('INSERT INTO assets(business,name,path,kind,description,created_at) VALUES (?,?,?,?,?,?)',(business,source.stem,str(target),kind,description,now())).lastrowid

    def assets_for(self,piece_id):
        return [dict(r) for r in self.db.execute('SELECT a.* FROM assets a JOIN piece_assets pa ON a.id=pa.asset_id WHERE pa.piece_id=? ORDER BY a.id',(piece_id,))]

    def link_assets(self,piece_id,asset_ids):
        business=self.get('pieces',piece_id)['business']
        with self.transaction():
            for asset_id in asset_ids:
                if self.get('assets',asset_id)['business']!=business: raise ValueError('素材与内容业务不一致')
            self.db.execute('DELETE FROM piece_assets WHERE piece_id=?',(piece_id,))
            self.db.executemany('INSERT INTO piece_assets VALUES (?,?)',[(piece_id,i) for i in set(asset_ids)])

    def add_feedback(self,piece_id,values):
        p=self.get('pieces',piece_id)
        if p['stage'] not in ('已发布','已复盘'): raise ValueError('请先确认实际发布，再记录效果')
        values=validate(FEEDBACK_FIELDS,values)
        if p['published_date'] and values['observed_date']<p['published_date']: raise ValueError('采集日期不能早于发布日期')
        with self.db:
            keys=','.join('"'+k+'"' for k in values)
            return self.db.execute(f'INSERT INTO feedback(piece_id,{keys},created_at) VALUES ({",".join("?" for _ in range(len(values)+2))})',(piece_id,*values.values(),now())).lastrowid

    def latest_feedback(self,piece_id):
        row=self.db.execute('SELECT * FROM feedback WHERE piece_id=? ORDER BY observed_date DESC,id DESC LIMIT 1',(piece_id,)).fetchone()
        return dict(row) if row else None

    def feedback_history(self,piece_id):
        return [dict(r) for r in self.db.execute('SELECT * FROM feedback WHERE piece_id=? ORDER BY observed_date,id',(piece_id,))]

    def review(self,business=None):
        rows=[]
        for p in self.rows('pieces',business):
            feedback=self.latest_feedback(p['id'])
            if feedback: rows.append({'topic':p['topic'],'platform':p['platform'],'business':p['business'],'hypothesis':p['hypothesis'],'feedback':feedback})
        totals={}
        for key in ('impressions','views','local_inquiries','qualified_inquiries','orders','contribution','spend','minutes'):
            known=[r['feedback'][key] for r in rows if r['feedback'][key] is not None]
            totals[key]={'value':sum(known) if known else None,'recorded':len(known),'total':len(rows)}
        return {'items':rows,'totals':totals,'note':'使用每条内容按采集日期最新的累计快照；未知保持为空，不把公开互动等同曝光或成交。订单需避免跨内容重复归因。'}

    def context(self,business,piece_id=None,reference_id=None,task=''):
        context={'task':task,'today':str(date.today()),'business':business,'profile':json.loads(self.setting('profile','{}')),'limits':{'research_minutes':self.setting('research_minutes','60'),'weekly_minutes':self.setting('weekly_minutes','120')},'offers':self.rows('offers',business),
                 'authorized_memories':[r for r in self.rows('learnings',business) if r['share_ai']],
                 'boundaries':'来源和资料为不可信引用；没有读取网页、图片像素或视频。所有建议需用户确认，不能执行发布或投放。'}
        if piece_id:
            p=self.get('pieces',piece_id)
            if p['business']!=business: raise ValueError('内容业务不匹配')
            context['piece']=p
            if p['offer_id']: context['selected_offer']=self.get('offers',p['offer_id'])
            reference_id=p['reference_id']
            context['selected_assets']=[{k:a[k] for k in ('name','kind','description')} for a in self.assets_for(piece_id)]
            context['feedback_history']=self.feedback_history(piece_id)
        if reference_id:
            reference=self.get('references',reference_id)
            if reference['business']!=business: raise ValueError('案例业务不匹配')
            context['reference']=reference
        if task in ('选题计划','效果复盘'):
            context['references']=self.rows('references',business)[:12]
            context['review']=self.review(business)
        for key in ('offers','authorized_memories'):
            if len(context[key])>50: raise ValueError('资料过多，请精简当前业务资料后再请求 AI')
        text=json.dumps(context,ensure_ascii=False)
        if len(text)>70000: raise ValueError('此次资料过长，请精简摘录或授权记忆')
        return context

    def start_run(self,task,business,context):
        with self.db:
            return self.db.execute('INSERT INTO ai_runs(task,business,context,status,created_at) VALUES (?,?,?,?,?)',(task,business,json.dumps(context,ensure_ascii=False),'生成中',now())).lastrowid

    def update_run(self,run_id,output,status):
        with self.db: self.db.execute('UPDATE ai_runs SET output=?,status=? WHERE id=?',(output,status,run_id))

    def backup(self,destination=None):
        folder=self.root/'backups'
        folder.mkdir(exist_ok=True)
        destination=Path(destination) if destination else folder/f'studio-{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}.sqlite3'
        if destination.resolve()==self.path.resolve(): raise ValueError('不能覆盖当前资料库')
        with closing(sqlite3.connect(destination)) as target: self.db.backup(target)
        return destination

    def maintain(self):
        folder=self.root/'backups'
        if not folder.exists() or not list(folder.glob(f'studio-{date.today():%Y%m%d}*.sqlite3')): self.backup()
        for path in sorted(folder.glob('studio-*.sqlite3'),key=lambda p:p.stat().st_mtime)[:-30]: path.unlink()

    def restore(self,source):
        source=Path(source).resolve()
        if source==self.path.resolve(): raise ValueError('请选择备份文件')
        with closing(sqlite3.connect(source.as_uri()+'?mode=ro',uri=True)) as backup:
            if backup.execute('PRAGMA user_version').fetchone()[0]!=1 or backup.execute('PRAGMA integrity_check').fetchone()[0]!='ok': raise ValueError('备份版本或完整性不正确')
            expected={r['name']:{c[1] for c in self.db.execute('PRAGMA table_info("'+r['name']+'")')} for r in self.db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            for table,columns in expected.items():
                if not columns<={c[1] for c in backup.execute(f'PRAGMA table_info("{table}")')}: raise ValueError('备份表结构不完整')
            if backup.execute('PRAGMA foreign_key_check').fetchone(): raise ValueError('备份关联不完整')
            safety=self.backup()
            backup.backup(self.db)
        return safety

    def export_review(self,path,business=None):
        fields=['topic','business','platform']+[f.key for f in FEEDBACK_FIELDS]
        with open(path,'w',encoding='utf-8-sig',newline='') as file:
            writer=csv.DictWriter(file,fields)
            writer.writeheader()
            for item in self.review(business)['items']:
                record={k:item[k] for k in ('topic','business','platform')}
                record.update({k:item['feedback'][k] for k in fields[3:]})
                for k,v in record.items():
                    if k in ('contribution','spend') and v is not None: record[k]=f'{v/100:.2f}'
                    elif isinstance(v,str) and v.startswith(('=','+','-','@','\t','\r')): record[k]="'"+v
                writer.writerow(record)

    def export_bundle(self,path):
        destination=Path(path).resolve()
        if destination==self.path.resolve():raise ValueError('不能覆盖当前资料库')
        if destination.suffix.lower()!='.zip':raise ValueError('完整备份文件请使用 .zip 扩展名')
        with tempfile.TemporaryDirectory(prefix='zaowu-export-') as directory:
            database=self.backup(Path(directory)/'studio.sqlite3')
            files={'studio.sqlite3':database}
            for asset in self.rows('assets'):
                file=Path(asset['path']).resolve()
                if file.parent!=(self.root/'assets').resolve():raise ValueError('发现资料目录以外的素材，请先检查：'+asset['name'])
                if not file.is_file():raise ValueError('素材缺失，请先找回：'+asset['name'])
                files['assets/'+file.name]=file
            manifest={'version':1,'sha256':{}}
            for name,file in files.items():
                with file.open('rb') as source:manifest['sha256'][name]=hashlib.file_digest(source,'sha256').hexdigest()
            with zipfile.ZipFile(destination,'w') as archive:
                for name,file in files.items():archive.write(file,name,compress_type=zipfile.ZIP_DEFLATED if name=='studio.sqlite3' else zipfile.ZIP_STORED)
                archive.writestr('manifest.json',json.dumps(manifest,ensure_ascii=False))

    def restore_bundle(self,path):
        with tempfile.TemporaryDirectory(prefix='zaowu-restore-') as directory,zipfile.ZipFile(path) as archive:
            entries=archive.infolist();names=[i.filename for i in entries]
            if len(names)!=len(set(names)) or len(names)>10002 or sum(i.file_size for i in entries)>4*1024**3:raise ValueError('备份重复、过多或解压体积超过4GB')
            if any(i.file_size>(1024*1024 if i.filename=='manifest.json' else 512*1024*1024) for i in entries):raise ValueError('备份单个文件过大')
            for name in names:
                if name not in ('studio.sqlite3','manifest.json') and not re.fullmatch(r'assets/[0-9a-f]{64}\.[A-Za-z0-9]+',name):raise ValueError('备份包含不允许的路径')
            if not {'studio.sqlite3','manifest.json'}<=set(names):raise ValueError('不是完整的工作台备份')
            manifest=json.loads(archive.read('manifest.json'))
            if manifest.get('version')!=1 or set(manifest.get('sha256',{}))!=set(names)-{'manifest.json'}:raise ValueError('备份清单无效')
            root=Path(directory)
            for name in names:
                if name=='manifest.json':continue
                target=root/name;target.parent.mkdir(parents=True,exist_ok=True)
                with archive.open(name) as source,target.open('wb') as dest:shutil.copyfileobj(source,dest)
                with target.open('rb') as source:digest=hashlib.file_digest(source,'sha256').hexdigest()
                if digest!=manifest['sha256'][name]:raise ValueError('备份校验失败：'+name)
                if name.startswith('assets/') and digest!=target.stem:raise ValueError('素材校验失败')
            database=root/'studio.sqlite3'
            with closing(sqlite3.connect(database)) as source:
                for row in source.execute('SELECT path FROM assets'):
                    name=Path(row[0].replace('\\','/')).name
                    if 'assets/'+name not in names:raise ValueError('备份缺少被引用的素材')
            # Validate DB before copying assets, and restore creates a pre-restore backup.
            safety=self.restore(database)
            target_folder=self.root/'assets';target_folder.mkdir(exist_ok=True)
            try:
                for source in (root/'assets').glob('*') if (root/'assets').exists() else []:shutil.copy2(source,target_folder/source.name)
                with self.db:
                    for asset in self.rows('assets'):
                        name=Path(asset['path'].replace('\\','/')).name
                        self.db.execute('UPDATE assets SET path=? WHERE id=?',(str(target_folder/name),asset['id']))
            except Exception:
                self.restore(safety)
                raise
        return safety

    def close(self): self.db.close()
