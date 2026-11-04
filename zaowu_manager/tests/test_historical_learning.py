from conftest import record

def test_ai_retains_prior_period_lessons_and_anonymous_customer_ids(store):
    record(store,'reviews',date='2026-09-30',title='九月复盘',findings='过早投放无效',actions='先验证咨询转化')
    record(store,'campaigns',date='2026-10-01',title='投放实验',criterion='有效咨询10条',result='未达标，暂停')
    record(store,'customers',code='NEVER-SEND-USER-TEXT',category='高复购客户',consent=1)
    context=store.context('经营数据分析','2026-11-01','2026-11-04')
    assert context['historical_learning']['reviews'][0]['findings']=='过早投放无效'
    assert context['historical_learning']['experiments'][0]['result']=='未达标，暂停'
    customers=store.context('客户经营助手','2026-11-01','2026-11-04')['anonymous_customer_rollups']
    assert customers[0]['anonymous_code']=='客户-000001'
    assert 'NEVER-SEND-USER-TEXT' not in str(customers)
