"""Transparent descriptive heuristics, never personal success probabilities."""
import statistics
from .provenance import scope_unknown,curve_source
from .grading import grade,valid_peer

def ratio(a,b):
    return a/b if a is not None and b is not None and b>0 else None

def trend(values,relative=False):
    if len(values)<7:return '数据不足'
    mean=statistics.mean(values)
    if mean<1 and not relative:return '低销量型'
    peaks=[i for i,x in enumerate(values) if x>mean*2 and (i==0 or values[i-1]<=mean*2)]
    if len(peaks)>=2:return '多次高峰型'
    if len(peaks)==1:return '单次爆发型'
    n=max(2,len(values)//3);first=statistics.mean(values[:n]);last=statistics.mean(values[-n:])
    if last>first*1.25:return '持续增长型'
    if last<first*.75:return '持续衰退型'
    return '稳定销售型'

def product(snapshot, peers=(),rules=None):
    if not snapshot:return grade(None,peers,'数据不足',rules)
    s=snapshot;c=s['creators'];o=s['sellers'];sales=s['sales']
    import json
    curve=json.loads(s['curve'] or '[]') if isinstance(s['curve'],str) else (s['curve'] or [])
    unknown=scope_unknown(s.get('notes'));denominator=None if unknown else c
    rate=ratio(o,denominator);per_seller=ratio(sales,o);per_creator=ratio(sales,denominator);shape=trend(curve,relative=curve_source(s.get('notes'))=='相对走势')
    result={'达人出单率':rate,'出单达人人均销量':per_seller,'参与达人人均销量':per_creator,'销量趋势':shape,'曲线来源':{'相对走势':'相对走势0–100，不代表销量','读图估算':'读图估算，仅趋势参考'}.get(curve_source(s.get('notes')),'用户录入或未提供曲线')}
    decision=grade(s,peers,shape,rules);result.update(decision)
    ranks=decision.get('同类百分位',{})
    result.update({'市场需求':f'同类销量百分位 {ranks["总销量"]:.0f}%' if ranks else '同类有效样本或数据不足，暂不排名',
        '创作者出单覆盖面':f'{rate:.1%}（历史覆盖面）' if rate is not None else '带货人数口径待核对',
        '销量容量':sales,'爆单潜力':f'历史曲线为{shape}，不推算个人爆单概率',
        '新创作者进入风险':'缺少粉丝、流量分布与投放成本数据',
        '综合建议':decision['理由'],'不确定因素':decision['理由'] if not decision['等级'] else '经验门槛未经经营验证；同类样本非随机，分档不保证出单或盈利'})
    return result

def review(ad, peers, analysis, min_spend=100, min_orders=5, target_ratio=1):
    spend=ad.get('spend');orders=ad.get('orders');gmv=ad.get('actual_gmv');r=ratio(gmv,spend)
    if spend is None or spend==0:conclusion='暂不能判断';reason='没有有效广告消耗，不能判定素材失败'
    elif spend<min_spend or (orders is not None and 0<orders<min_orders):conclusion='继续观察';reason='测试样本不足，补充数据后再判断'
    elif orders is None or gmv is None:conclusion='继续观察';reason='订单或实际GMV未知，不能完整评估'
    elif orders==0:conclusion='暂缓投入';reason='已达到设置的消耗门槛，但没有成交'
    elif r is not None and r>=target_ratio:conclusion='继续投入';reason='消耗、订单和实际GMV/消耗达到设置门槛；不代表盈利'
    else:conclusion='优化后再测';reason='已有成交但实际GMV/消耗未达到设置门槛'
    good=[p for p in peers if ratio(p.get('actual_gmv'),p.get('spend')) is not None and p.get('orders') and p['spend']>=min_spend and p['orders']>=min_orders and ratio(p['actual_gmv'],p['spend'])>=target_ratio]
    book='同书存在达到门槛的视频，可保留新素材测试；本条视频表现不能否定整本书' if good else '同书尚缺稳定证据，保留小规模验证，不凭单条视频否定整本书'
    if analysis.get('销量趋势')=='持续衰退型':book+='；商品呈衰退趋势，应优先重新核对需求'
    return {'当前视频处理建议':conclusion,'理由':reason,'同一本书是否继续更新视频':book,'实际GMV/广告消耗':r,
        '同书其他视频样本数':len(peers),'商品分析':analysis,
        '门槛':{'最低消耗':min_spend,'最低订单':min_orders,'目标GMV/消耗':target_ratio},
        '不确定因素':'门槛是可调整的经营规则，不是统计显著性；投放口径、周期、账号、品类不同不可直接归因。GMV/消耗不是佣金收益率。'}
