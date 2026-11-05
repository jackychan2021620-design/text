"""Deterministic, configurable launch heuristics; not a calibrated outcome model."""
import json
import math
from .provenance import scope_unknown

LEVELS=('非常适合','适合','直接放弃')
DEFAULTS={'min_peers':5,'high_pct':60,'low_pct':25}
RULE_VERSION='three-tier-v1'

def validate_rules(rules):
    result=DEFAULTS|rules
    try:
        n=float(result['min_peers']);high=float(result['high_pct']);low=float(result['low_pct'])
        if not all(math.isfinite(v) for v in (n,high,low)) or not n.is_integer() or not 3<=n<=1000 or not 0<=low<high<=100:raise ValueError()
    except (TypeError,ValueError,OverflowError):raise ValueError('分档门槛需满足：同类样本数3～1000，0≤较弱门槛＜较好门槛≤100')
    return {'min_peers':int(n),'high_pct':high,'low_pct':low}

def valid_peer(p):
    return p.get('period_days')==90 and p.get('confirmed')==1 and not scope_unknown(p.get('notes')) and p.get('creators') is not None and p['creators']>0 and p.get('sellers') is not None and 0<=p['sellers']<=p['creators'] and p.get('sales') is not None and p['sales']>=0 and not (p['sellers']==0 and p['sales']>0)

def percentile(value,values):
    # Midranks keep tied products at the same neutral percentile, rather than
    # incorrectly declaring every identical item the best in the category.
    return 100*(sum(v<value for v in values)+.5*sum(v==value for v in values))/len(values)

def grade(snapshot,peers,shape,rules=None):
    rules=validate_rules(rules or {});pending=[]
    base={'规则版本':RULE_VERSION,'规则':rules,'等级':None,'状态':'待补数据','理由':'','同类有效样本数':0}
    if not snapshot:base['理由']='尚无90天采集记录，请先补充数据。';return base
    s=snapshot
    if s.get('period_days')!=90:pending.append('90天统计口径')
    if not s.get('confirmed'):pending.append('人工核对')
    if scope_unknown(s.get('notes')):pending.append('确认带货人数周期')
    for key,name in [('creators','带货人数'),('sellers','出单人数'),('sales','总销量')]:
        if s.get(key) is None:pending.append(name)
    if s.get('creators')==0:pending.append('有效的带货人数')
    if pending:base['理由']='需补齐：'+'、'.join(pending)+'。';return base
    if not valid_peer(s):base['理由']='出单人数、销量或统计口径不一致，请先核对。';return base
    # This explicit exclusion uses verified zero outcomes, not a missing-data zero.
    if s['sales']==0 and s['sellers']==0:
        return base|{'等级':'直接放弃','状态':'已分档','理由':'已有人带货，但90天没有出单人数和销量。'}
    valid=[p for p in peers if valid_peer(p)];base['同类有效样本数']=len(valid)
    if len(valid)<rules['min_peers']:
        base['理由']=f'同类有效商品仅{len(valid)}个，需至少{rules["min_peers"]}个；请补充相同分类的90天数据。';return base
    coverage=percentile(s['sellers']/s['creators'],[p['sellers']/p['creators'] for p in valid])
    demand=percentile(s['sales'],[p['sales'] for p in valid])
    per=lambda p:p['sales']/p['sellers'] if p['sellers'] else 0
    capacity=percentile(per(s),[per(p) for p in valid])
    ranks={'达人出单率':coverage,'总销量':demand,'出单达人人均销量':capacity}
    if shape=='数据不足':return base|{'同类百分位':ranks,'理由':'需补齐销量曲线，至少7个有序数据点。'}
    hi=rules['high_pct'];lo=rules['low_pct'];sustained=shape in ('稳定销售型','持续增长型','多次高峰型')
    if min(ranks.values())>=hi and sustained:
        level='非常适合';reason=f'出单覆盖、总销量及出单人均销量均达同类前{100-hi:g}%，走势为{shape}。'
    elif max(ranks.values())<=lo and shape in ('持续衰退型','低销量型'):
        level='直接放弃';reason=f'三项指标均在同类后{lo:g}%，且走势为{shape}。'
    else:
        level='适合'
        strongest=max(ranks,key=ranks.get)
        reason=f'{strongest}超过约{ranks[strongest]:.0f}%同类，走势为{shape}，尚未达到优先档条件。'
    return base|{'等级':level,'状态':'已分档','理由':reason,'同类百分位':ranks}

def rules_text(rules=None):
    r=validate_rules(rules or {})
    return f'''初版经验规则（可在设置中调整，需结合真实测试结果校准）
非常适合：达人出单率、总销量、出单达人人均销量均超过同类{r['high_pct']:g}%，且走势稳定、增长或多次高峰。
适合：数据完整、样本足够，未命中最高档或放弃条件。
直接放弃：三项均处同类后{r['low_pct']:g}%，且走势衰退或低销量；或已有推广但90天无人出单且销量为零。
同类至少{r['min_peers']}个有效商品。并列采用中位排名，单次爆发不单独作为放弃理由。
缺数据、曲线不足或周期不一致先补齐，不硬分档。不计算个人爆单概率。
本档位表达本轮市场测试优先级，不保证出单或盈利。'''

def render(results):
    if not results:return '暂无可推荐商品，请先建立图书、商品链接并采集数据。'
    blocks=[]
    for item in results:
        a=item['分析'];book=' '.join(str(item['图书']).split());name=f'《{book}》 · 商品#{item["商品ID"]}'
        conclusion='档次：'+a['等级'] if a.get('等级') else '暂不分档'
        blocks.append(name+'\n'+conclusion+'\n理由：'+a.get('理由','请补充数据。'))
    return '\n\n'.join(blocks)
