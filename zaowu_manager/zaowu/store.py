from __future__ import annotations
import csv
import hashlib
import json
import os
import re
import shutil
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path

from .schema import BUSINESSES, FLOWERS, SALON, REALIZED, SCHEMAS

def data_dir():
    override = os.environ.get('ZAOWU_DATA_DIR')
    if override:
        return Path(override).expanduser().resolve()
    root = Path(os.environ.get('LOCALAPPDATA', Path.home() / '.local' / 'share'))
    return root / 'ZaowuGrowthManager'

def yuan(cents):
    return f'{Decimal(cents) / 100:,.2f}'

def fen(value):
    try:
        number = Decimal(str(value).replace(',', ''))
        if not number.is_finite() or number < 0 or number > 999999999:
            raise ValueError('金额应为 0～999999999 元')
        return int((number * 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
    except (InvalidOperation, TypeError) as exc:
        raise ValueError('金额格式不正确') from exc

class Store:
    def __init__(self, root=None):
        self.root = Path(root) if root else data_dir()
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / 'zaowu.sqlite3'
        self.db = sqlite3.connect(self.path, timeout=15)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA busy_timeout=15000')
        self.migrate()

    def migrate(self):
        version = self.db.execute('PRAGMA user_version').fetchone()[0]
        if version > 1:
            raise ValueError('数据库版本高于软件版本，请升级软件')
        with self.db:
            for table, (_, fields) in SCHEMAS.items():
                columns = []
                for field in fields:
                    kind = 'INTEGER' if field.kind in ('money','int','bool','product','customer') else 'REAL' if field.kind == 'number' else 'TEXT'
                    ref = ' REFERENCES products(id) ON DELETE RESTRICT' if field.kind == 'product' else ' REFERENCES customers(id) ON DELETE RESTRICT' if field.kind == 'customer' else ''
                    columns.append(f'"{field.key}" {kind}{ref}')
                self.db.execute(f'CREATE TABLE IF NOT EXISTS {table} (id INTEGER PRIMARY KEY, {", ".join(columns)}, updated_at TEXT NOT NULL)')
            self.db.executescript('''
              CREATE UNIQUE INDEX IF NOT EXISTS customer_code ON customers(code);
              CREATE INDEX IF NOT EXISTS order_date ON orders(date, business);
              CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS sessions (id INTEGER PRIMARY KEY, title TEXT NOT NULL, created_at TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY, session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE, role TEXT NOT NULL, content TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS audit (id INTEGER PRIMARY KEY, at TEXT NOT NULL, action TEXT NOT NULL, table_name TEXT NOT NULL, row_id INTEGER);
              CREATE TABLE IF NOT EXISTS reports (id INTEGER PRIMARY KEY, period TEXT NOT NULL, start TEXT NOT NULL, end TEXT NOT NULL, body TEXT NOT NULL, UNIQUE(period,start,end));
              PRAGMA user_version=1;
            ''')

    @contextmanager
    def transaction(self):
        self.db.execute('SAVEPOINT operation')
        try:
            yield
            self.db.execute('RELEASE operation')
        except Exception:
            self.db.execute('ROLLBACK TO operation')
            self.db.execute('RELEASE operation')
            raise

    def setting(self, key, default=''):
        row = self.db.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()
        return row[0] if row else default

    def set_setting(self, key, value):
        with self.db:
            self.db.execute('INSERT INTO settings VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (key,str(value)))

    def rows(self, table, filters=None):
        if table not in SCHEMAS:
            raise ValueError('未知数据类型')
        filters = filters or {}
        keys = {f.key for f in SCHEMAS[table][1]} | {'id'}
        if not filters.keys() <= keys:
            raise ValueError('未知筛选字段')
        where = ' AND '.join(f'"{k}"=?' for k in filters)
        return [dict(r) for r in self.db.execute(f'SELECT * FROM {table}' + (' WHERE '+where if where else '')+' ORDER BY id DESC',tuple(filters.values()))]

    def validate(self, table, values):
        out = {}
        for field in SCHEMAS[table][1]:
            v = values.get(field.key)
            if v is None:
                v = 0 if field.kind in ('money','int','bool','number') else None if field.kind in ('product','customer') else ''
            if field.kind in ('money','int','bool','product','customer'):
                if v == '' and field.kind in ('product','customer'):
                    v = None
                if v is not None:
                    n = Decimal(str(v))
                    if not n.is_finite() or n != n.to_integral_value() or n < 0 or n > 99999999999:
                        raise ValueError(f'{field.label}：应为非负整数')
                    v = int(n)
                if field.kind == 'bool' and v not in (0,1):
                    raise ValueError(f'{field.label}：应为 0 或 1')
            elif field.kind == 'number':
                v = float(v)
                if not 0 <= v <= 1e12:
                    raise ValueError(f'{field.label}：数值超出范围')
            else:
                v = str(v).strip()
                if len(v)>100000:
                    raise ValueError('文本过长')
                if field.required and not v:
                    raise ValueError(f'请填写{field.label}')
                if field.kind in ('date','optional_date') and v:
                    if date.fromisoformat(v).isoformat() != v:
                        raise ValueError('日期请使用 YYYY-MM-DD 格式')
                if field.kind == 'choice' and v not in field.options:
                    raise ValueError(f'{field.label}：请从选项中选择')
            out[field.key] = v
        if table == 'orders':
            statuses = FLOWERS if out['business']=='花束业务' else SALON if out['business']=='活动沙龙' else ('已付款','已完成','已取消')
            if out['status'] not in statuses:
                raise ValueError('订单状态与业务类型不匹配')
            if out['quantity'] < 1:
                raise ValueError('订单件数 / 组数至少为 1')
            if out['product_id']:
                product = self.db.execute('SELECT business FROM products WHERE id=?',(out['product_id'],)).fetchone()
                if not product or product[0] != out['business']:
                    raise ValueError('产品不属于当前业务')
        return out

    def save(self, table, values, row_id=None):
        if table not in SCHEMAS:
            raise ValueError('未知数据类型')
        values = self.validate(table, values)
        values['updated_at'] = datetime.now().isoformat(timespec='seconds')
        with self.transaction():
            if row_id is None:
                keys = ','.join(f'"{k}"' for k in values)
                cur = self.db.execute(f'INSERT INTO {table} ({keys}) VALUES ({",".join("?" for _ in values)})',tuple(values.values()))
                row_id = cur.lastrowid
                action = 'create'
            else:
                cur = self.db.execute(f'UPDATE {table} SET '+','.join(f'"{k}"=?' for k in values)+' WHERE id=?', (*values.values(),row_id))
                if cur.rowcount != 1:
                    raise ValueError('记录已不存在，请刷新')
                action = 'update'
            self.db.execute('INSERT INTO audit(at,action,table_name,row_id) VALUES (?,?,?,?)',(values['updated_at'],action,table,row_id))
        return row_id

    def delete(self, table, row_id):
        if table not in SCHEMAS:
            raise ValueError('未知数据类型')
        with self.transaction():
            self.db.execute(f'DELETE FROM {table} WHERE id=?',(row_id,))
            self.db.execute('INSERT INTO audit(at,action,table_name,row_id) VALUES (?,?,?,?)',(datetime.now().isoformat(),'delete',table,row_id))

    def summary(self, start, end, business=None):
        if date.fromisoformat(start)>date.fromisoformat(end):
            raise ValueError('开始日期不能晚于结束日期')
        all_rows = [r for r in self.rows('orders') if start<=r['date']<=end and (not business or r['business']==business)]
        orders = [r for r in all_rows if r['status'] in REALIZED]
        revenue = sum(r['revenue'] for r in orders)
        material = sum(r['material'] for r in orders)
        direct = sum(r['labor']+r['other'] for r in orders)
        contribution = revenue-material-direct
        fixed = sum(r['amount'] for r in self.rows('expenses') if start<=r['date']<=end)
        customers = {r['customer_id'] for r in orders if r['customer_id']}
        first_dates = {}
        for r in self.rows('orders'):
            if r['status'] in REALIZED and r['customer_id']:
                first_dates[r['customer_id']] = min(first_dates.get(r['customer_id'],r['date']),r['date'])
        trend = {}
        products = {}
        sources = {}
        channels = {}
        for r in orders:
            trend[r['date']] = trend.get(r['date'],0)+r['revenue']
            p = str(r['product_id'] or '未关联产品')
            bucket = products.setdefault(p,{'orders':0,'quantity':0,'revenue':0,'contribution':0})
            bucket['orders']+=1
            bucket['quantity']+=r['quantity']
            bucket['revenue']+=r['revenue']
            bucket['contribution']+=r['revenue']-r['material']-r['labor']-r['other']
            for name, target in [('source',sources),('channel',channels)]:
                key = r[name] or '待录入'
                target[key] = target.get(key,0)+1
        return dict(start=start,end=end,business=business or '全部业务',orders=len(orders),pipeline=len([r for r in all_rows if r['status']!='已取消']),revenue=revenue,material=material,direct=direct,contribution=contribution,margin=round(contribution/revenue*100,2) if revenue else None,fixed=fixed if not business else None,net_after_recorded_expenses=contribution-fixed if not business else None,customers=len(customers),unlinked_orders=sum(not r['customer_id'] for r in orders),new_customers=sum(start<=first_dates[c]<=end for c in customers),repeat_orders=sum(r['customer_kind']=='复购' for r in orders),aov=round(revenue/len(orders)) if orders else 0,by_business={b:sum(r['revenue'] for r in orders if r['business']==b) for b in BUSINESSES},trend=dict(sorted(trend.items())),products=products,sources=sources,channels=channels)

    def customer_stats(self, customer_id):
        rows = sorted((r for r in self.rows('orders') if r['customer_id']==customer_id and r['status'] in REALIZED),key=lambda r:r['date'])
        return {'AI匿名编号':f'客户-{customer_id:06d}','首次消费':rows[0]['date'] if rows else '暂无', '最近消费':rows[-1]['date'] if rows else '暂无','次数':len(rows),'累计消费':yuan(sum(r['revenue'] for r in rows)),'产品编号':', '.join(str(r['product_id']) for r in rows if r['product_id'])}

    def inventory_balance(self):
        balances = {}
        for row in self.rows('inventory'):
            key = f"{row['item']}（{row['unit']}）"
            balances[key] = balances.get(key,0) + row['quantity'] * (1 if row['movement'] in ('采购入库','盘盈') else -1)
        return balances

    def context(self, module, start, end, business=None):
        # Deliberate whitelist. No customer IDs, personal notes or raw orders.
        current = self.summary(start,end,business)
        days = (date.fromisoformat(end)-date.fromisoformat(start)).days+1
        prev_end = date.fromisoformat(start)-timedelta(days=1)
        prev_start = prev_end-timedelta(days=days-1)
        context = {'module':module,'money_unit':'分，100分=1元','current':current,'previous':self.summary(str(prev_start),str(prev_end),business),'products':[{k:r[k] for k in ('name','business','price','material','active')} for r in self.rows('products') if not business or r['business']==business],'authorized_memories':[{k:r[k] for k in ('category','title','body')} for r in self.rows('memories') if r['share_ai']]}
        permitted = {
         '营销策略制定':('campaigns','goals','tasks'), '内容创作助手':('contents','assets','campaigns'),
         '客户经营助手':(), '市场竞争分析':('competitors',), '经营复盘':('reviews','goals','tasks','campaigns'),
         '今日工作':('tasks','goals','campaigns'), 'AI经营助手':('goals','tasks','campaigns'),
        }
        for table in permitted.get(module,()):
            rows = self.rows(table)
            # Only business records relevant to selected interval; goals/tasks keep open items.
            rows = [r for r in rows if (not business or r.get('business',business)==business) and (start<=r.get('date',start)<=end or table in ('goals','tasks'))]
            context[table] = [{k:v for k,v in r.items() if k not in ('id','updated_at','path')} for r in rows[:100]]
            context[table+'_selection'] = f'最近录入最多100条，匹配记录共{len(rows)}条；超出部分未发送'
        if module=='今日工作':
            yesterday=date.today()-timedelta(days=1)
            context['yesterday']=self.summary(str(yesterday),str(yesterday),business)
        if module in ('今日工作','经营总览','经营数据分析','营销策略制定','经营复盘','AI经营助手'):
            previous_reviews=[r for r in self.rows('reviews') if r['date']<=end]
            previous_experiments=[r for r in self.rows('campaigns') if r['date']<=end and (not business or r['business']==business)]
            context['historical_learning']={
                'reviews':[{k:r[k] for k in ('date','period','title','findings','actions')} for r in previous_reviews[:10]],
                'experiments':[{k:r[k] for k in ('date','business','title','hypothesis','criterion','spent','exposures','visits','inquiries','conversions','result','status')} for r in previous_experiments[:20]],
                'selection':'最近录入的10条历史复盘结论和20条营销实验，包含本期及更早记录；不代表全部历史',
            }
        if module=='客户经营助手':
            context['customer_segments'] = {category:sum(r['category']==category for r in self.rows('customers')) for category in ('新客户','老客户','高复购客户','转介绍客户','企业客户')}
            context['promotion_consent_count'] = sum(r['consent'] for r in self.rows('customers'))
            context['anonymous_customer_rollups'] = [{
                'anonymous_code':f"客户-{r['id']:06d}", 'business':r['business'],
                'category':r['category'], 'promotion_consent':bool(r['consent']),
                'purchase_statistics':self.customer_stats(r['id'])
            } for r in self.rows('customers')[:100]]
            context['customer_selection']='最近录入的最多100名匿名客户，不发送手写客户编号、偏好及沟通备注'
        # Limit context size; never silently trim accounting totals.
        if len(json.dumps(context,ensure_ascii=False))>65000:
            raise ValueError('经营上下文超过安全长度，请缩短日期范围或减少授权记忆')
        return context

    def reports_due(self, today=None):
        today = today or date.today()
        week_end = today-timedelta(days=today.weekday()+1)
        month_end = today.replace(day=1)-timedelta(days=1)
        for period, start, end in [('每周',week_end-timedelta(days=6),week_end),('每月',month_end.replace(day=1),month_end)]:
            s = self.summary(str(start),str(end))
            body = json.dumps(s,ensure_ascii=False,indent=2)
            with self.db:
                self.db.execute('INSERT OR IGNORE INTO reports(period,start,end,body) VALUES (?,?,?,?)',(period,str(start),str(end),body))

    def new_session(self, title='新经营会话'):
        with self.db:
            return self.db.execute('INSERT INTO sessions(title,created_at) VALUES (?,?)',(title,datetime.now().isoformat())).lastrowid

    def add_message(self, session_id, role, content, status='complete'):
        with self.db:
            return self.db.execute('INSERT INTO messages(session_id,role,content,status,created_at) VALUES (?,?,?,?,?)',(session_id,role,content,status,datetime.now().isoformat())).lastrowid

    def messages(self, session_id):
        return [dict(r) for r in self.db.execute('SELECT * FROM messages WHERE session_id=? ORDER BY id',(session_id,))]

    def backup(self, destination=None):
        if destination:
            target = Path(destination)
        else:
            folder = self.root / 'backups'
            folder.mkdir(exist_ok=True)
            target = folder / f'zaowu-{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}.sqlite3'
        if target.resolve()==self.path.resolve():
            raise ValueError('不能覆盖当前数据库')
        with sqlite3.connect(target) as dst:
            self.db.backup(dst)
        return target

    def auto_backup(self):
        folder = self.root / 'backups'
        prefix = 'zaowu-'+date.today().strftime('%Y%m%d')
        if not folder.exists() or not any(folder.glob(prefix+'*.sqlite3')):
            self.backup()
        backups = sorted(folder.glob('zaowu-*.sqlite3'),key=lambda p:p.stat().st_mtime)
        for old in backups[:-30]:
            old.unlink()

    def restore(self, source):
        source = Path(source).resolve()
        if source==self.path.resolve():
            raise ValueError('请选择备份文件')
        # Read-only integrity and schema verification BEFORE touching current data.
        with sqlite3.connect(source.as_uri()+'?mode=ro',uri=True) as src:
            if src.execute('PRAGMA integrity_check').fetchone()[0]!='ok':
                raise ValueError('备份完整性检查失败')
            if src.execute('PRAGMA user_version').fetchone()[0]!=1:
                raise ValueError('不支持此备份版本')
            for table, (_,fields) in SCHEMAS.items():
                actual = {r[1] for r in src.execute(f'PRAGMA table_info({table})')}
                if not ({'id','updated_at'}|{f.key for f in fields})<=actual:
                    raise ValueError('备份数据库结构不完整')
            for table in ('settings','sessions','messages','audit','reports'):
                if not src.execute('SELECT 1 FROM sqlite_master WHERE type=? AND name=?',('table',table)).fetchone():
                    raise ValueError('备份缺少系统表')
            if src.execute('PRAGMA foreign_key_check').fetchone():
                raise ValueError('备份包含失效关联')
            safety = self.backup()
            src.backup(self.db)
        return safety

    def import_photo(self, path, title, business):
        path = Path(path)
        if path.suffix.lower() not in ('.jpg','.jpeg','.png','.webp','.bmp') or path.stat().st_size>20*1024*1024:
            raise ValueError('请选择 20MB 以下 JPG、PNG、WebP 或 BMP 图片')
        folder = self.root/'assets'
        folder.mkdir(exist_ok=True)
        target = folder / (hashlib.sha256(path.read_bytes()).hexdigest()+path.suffix.lower())
        if not target.exists():
            shutil.copy2(path,target)
        return self.save('assets',dict(date=str(date.today()),business=business,title=title,path=str(target),description=''))

    def export_file(self, table, target, filters=None, template=False):
        fields = SCHEMAS[table][1]
        header = ['id']+[f.key for f in fields]
        rows = []
        for r in ([] if template else self.rows(table,filters)):
            row = [r['id']]
            for field in fields:
                value = r[field.key]
                if field.kind=='money':
                    value = str(Decimal(value)/100)
                # Prevent spreadsheet formula injection without modifying stored data.
                if isinstance(value,str) and value.startswith(('=','+','-','@','\t','\r')):
                    value = "'"+value
                row.append(value)
            rows.append(row)
        if Path(target).suffix.lower()=='.xlsx':
            from openpyxl import Workbook
            wb = Workbook()
            ws = wb.active
            ws.title = table
            ws.append(header)
            for row in rows:
                ws.append(row)
            ws.freeze_panes='A2'
            wb.save(target)
        else:
            with open(target,'w',encoding='utf-8-sig',newline='') as fh:
                writer = csv.writer(fh)
                writer.writerow(header)
                writer.writerows(rows)
        return len(rows)

    def import_file(self, table, source, filters=None):
        # Atomic inserts only. IDs are deliberately not trusted as update instructions.
        if Path(source).stat().st_size>20*1024*1024:
            raise ValueError('导入文件不能超过 20MB')
        if Path(source).suffix.lower()=='.xlsx':
            from openpyxl import load_workbook
            wb = load_workbook(source,read_only=True,data_only=False)
            try:
                records = list(wb.active.values)
            finally:
                wb.close()
            if not records:
                raise ValueError('文件为空')
            header,*data = records
            records = [dict(zip(header,row)) for row in data if any(x is not None for x in row)]
        else:
            with open(source,encoding='utf-8-sig',newline='') as fh:
                reader = csv.DictReader(fh)
                header = reader.fieldnames or []
                records = list(reader)
        required = {f.key for f in SCHEMAS[table][1]}
        if not required<=set(header):
            raise ValueError('缺少字段：'+', '.join(sorted(required-set(header)))+'。请先导出模板。')
        if len(records)>10000:
            raise ValueError('单次最多导入 10000 行')
        with self.transaction():
            for index, record in enumerate(records,2):
                try:
                    for field in SCHEMAS[table][1]:
                        value = record.get(field.key)
                        if isinstance(value,str) and value.startswith("'") and value[1:].startswith(('=','+','-','@','\t','\r')):
                            value = value[1:]
                        if field.kind=='money':
                            value = fen(value if value not in (None,'') else 0)
                        if isinstance(value,datetime):
                            value = value.date().isoformat()
                        record[field.key] = value
                    if filters and any(record.get(k)!=v for k,v in filters.items()):
                        raise ValueError('文件中的业务与当前页面不一致')
                    self.save(table,record)
                except Exception as exc:
                    raise ValueError(f'第 {index} 行导入失败：{exc}；本次导入全部回滚') from exc
        return len(records)

    def close(self):
        self.db.close()
