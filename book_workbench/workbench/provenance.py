"""Keep audit annotations out of the business notes editor."""
PREFIXES=('【曲线读图估算】','【曲线手工录入】','【带货人数周期待确认】','【带货人数周期已核对】','【快照修订】')
UNKNOWN='【带货人数周期待确认】来自页面概览，截图未明确该指标统计周期；不用于计算90天达人出单率。'
CONFIRMED='【带货人数周期已核对】经营者确认带货人数与本次统计周期一致。'
def split_notes(value):
    lines=(value or '').splitlines()
    return '\n'.join(x for x in lines if not x.startswith(PREFIXES)),[x for x in lines if x.startswith(PREFIXES)]
def combine_notes(user,metadata):return '\n'.join([user.strip(),*metadata]).strip()
def scope_unknown(notes):return (notes or '').rfind('【带货人数周期待确认】')>(notes or '').rfind('【带货人数周期已核对】')
def curve_source(notes):return '读图估算' if (notes or '').rfind('【曲线读图估算】')>(notes or '').rfind('【曲线手工录入】') else '手工录入'
