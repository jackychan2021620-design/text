'''Single-product, configurable launch heuristics; peers only supply context.'''
import math
from .provenance import scope_unknown

LEVELS=('非常适合','适合','直接放弃')
DEFAULTS={'high_rate':20,'high_sales':1000,'high_per_seller':20,'high_sellers':5,
          'low_rate':5,'low_sales':100,'low_per_seller':5,'min_peers':5}
RULE_VERSION='single-book-v2'

def validate_rules(rules):
    result=DEFAULTS|{k:v for k,v in rules.items() if k in DEFAULTS}
    try:
        result={k:float(v) for k,v in result.items()}
        if not all(math.isfinite(v) and v>0 for v in result.values()):raise ValueError()
        if not 0<result['low_rate']<result['high_rate']<=100:raise ValueError()
        if not result['low_sales']<result['high_sales'] or not result['low_per_seller']<result['high_per_seller']:raise ValueError()
        for k in ('high_sales','low_sales','high_sellers','min_peers'):
            if not result[k].is_integer():raise ValueError()
            result[k]=int(result[k])
        if not 3<=result['min_peers']<=1000:raise ValueError()
    except (TypeError,ValueError,OverflowError):
        raise ValueError('分档门槛需为正数；较弱门槛小于优先门槛，出单率不超过100%，销量及人数为整数；参考排名样本数3～1000')
    return result

def valid_peer(p):
    return p.get('period_days')==90 and p.get('confirmed')==1 and not scope_unknown(p.get('notes')) and p.get('creators') is not None and p['creators']>0 and p.get('sellers') is not None and 0<=p['sellers']<=p['creators'] and p.get('sales') is not None and p['sales']>=0 and not (p['sellers']==0 and p['sales']>0) and not (p['sellers']>0 and p['sales']<p['sellers'])

def percentile(value,values):
    return 100*(sum(v<value for v in values)+.5*sum(v==value for v in values))/len(values)

def grade(snapshot,peers,shape,rules=None):
    r=validate_rules(rules or {});pending=[]
    base={'规则版本':RULE_VERSION,'规则':r,'等级':None,'状态':'待补数据','理由':'','同类有效样本数':0}
    if not snapshot:return base|{'理由':'尚无90天采集记录，请先补充数据。'}
    s=snapshot
    if s.get('period_days')!=90:pending.append('90天统计口径')
    if not s.get('confirmed'):pending.append('人工核对')
    if scope_unknown(s.get('notes')):pending.append('确认带货人数周期')
    for key,name in [('creators','带货人数'),('sellers','出单人数'),('sales','总销量')]:
        if s.get(key) is None:pending.append(name)
    if s.get('creators')==0:pending.append('有效的带货人数')
    if pending:return base|{'理由':'需补齐：'+'、'.join(pending)+'。'}
    if not valid_peer(s):return base|{'理由':'出单人数、销量或统计口径不一致，请先核对。'}
    valid=[p for p in peers if valid_peer(p)];base['同类有效样本数']=len(valid)
    rate=s['sellers']/s['creators']*100;per=s['sales']/s['sellers'] if s['sellers'] else 0
    if len(valid)>=r['min_peers']:
        base['同类百分位']={'达人出单率':percentile(rate,[p['sellers']/p['creators']*100 for p in valid]),
                         '总销量':percentile(s['sales'],[p['sales'] for p in valid]),
                         '出单达人人均销量':percentile(per,[p['sales']/p['sellers'] if p['sellers'] else 0 for p in valid])}
    metrics=f"出单率{rate:.1f}%、90天销量{s['sales']:g}、出单人均{per:.1f}本"
    if s['sales']==0 and s['sellers']==0:
        level='直接放弃';reason='已有人带货，但90天出单人数和销量均为零。'
    elif rate>=r['high_rate'] and s['sales']>=r['high_sales'] and per>=r['high_per_seller'] and s['sellers']>=r['high_sellers'] and shape in ('稳定销售型','持续增长型','多次高峰型'):
        level='非常适合';reason=metrics+f'，走势为{shape}，达到优先试测门槛。'
    elif rate<r['low_rate'] and s['sales']<r['low_sales'] and per<r['low_per_seller'] and shape in ('持续衰退型','低销量型'):
        level='直接放弃';reason=metrics+f'，三项均偏弱且为{shape}。'
    else:
        level='适合'
        if shape=='数据不足':reason=metrics+'；曲线不足，先小量试测，暂不升最高档。'
        elif shape in ('持续衰退型','低销量型'):reason=metrics+f'；走势为{shape}，控制试测规模。'
        else:reason=metrics+f'，走势为{shape}，可小量试测。'
    return base|{'等级':level,'状态':'已分档','理由':reason}

def rules_text(rules=None):
    r=validate_rules(rules or {})
    return f'''单本书经验规则（可在设置中调整，未经经营结果校准）
非常适合：90天达人出单率≥{r['high_rate']:g}%、总销量≥{r['high_sales']:g}、出单人均销量≥{r['high_per_seller']:g}本、出单人数≥{r['high_sellers']:g}人，且走势稳定、增长或多次高峰。
适合：核心数据有效，未命中优先档或放弃条件，建议小量试测。曲线不足仍可分到此档，但不升最高档。
直接放弃：三项分别低于{r['low_rate']:g}%、{r['low_sales']:g}本、{r['low_per_seller']:g}本，且走势衰退或低销量；或90天已有带货但无人出单且销量明确为零。
单本书即可分档，不要求同类商品。至少{r['min_peers']}个有效同类商品才附加参考排名，排名不改变档位。
核心数据缺失、口径不一致或带货人数周期不明时，仅说明缺项，不把缺值当作零。
档位表达市场试测优先级，不保证出单或盈利，不推算个人爆单概率。'''

def render(results):
    if not results:return '暂无可推荐商品，请先建立图书、商品链接并采集数据。'
    blocks=[]
    for item in results:
        a=item['分析'];book=' '.join(str(item['图书']).split());name=f'《{book}》 · 商品#{item["商品ID"]}'
        conclusion='档次：'+a['等级'] if a.get('等级') else '暂不分档'
        blocks.append(name+'\n'+conclusion+'\n理由：'+a.get('理由','请补充数据。'))
    return '\n\n'.join(blocks)
