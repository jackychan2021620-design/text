from dataclasses import dataclass

BUSINESSES=('DIY散客','鲜花花束','活动沙龙')
PLATFORMS=('小红书','抖音','美团','其他')
STAGES=('选题','素材','草稿','待发布','已发布','已复盘')

@dataclass(frozen=True)
class Field:
    key: str
    label: str
    kind: str='text'
    options: tuple=()
    required: bool=False
    hint: str=''

def f(key,label,kind='text',options=(),required=False,hint=''):
    return Field(key,label,kind,options,required,hint)

B=f('business','所属业务','choice',BUSINESSES,True)
TABLES={
 'offers':('产品与服务',[
    B,f('name','产品或服务名称',required=True),f('audience','适合谁 / 什么场景'),
    f('price','真实价格与计价方式',hint='如尚未确认，请留空；AI 不会补造价格'),
    f('includes','顾客买到什么','long'),f('conditions','预约、交付和服务范围','long'),
    f('proof','已有优势与真实证据','long'),f('questions','顾客常问 / 犹豫的问题','long'),f('booking','咨询及购买路径','long')]),
 'references':('参考案例',[
    B,f('title','案例名称',required=True),f('platform','来源平台','choice',PLATFORMS),f('url','原文链接'),
    f('source_date','观察日期','date'),f('excerpt','原文摘录 / 视频内容描述','long',required=True,hint='保存链接不会自动读取受限平台；请粘贴实际看到的内容'),
    f('audience','吸引谁'),f('hook','标题 / 首图 / 开头的切入'),f('proof','展示了什么证据','long'),
    f('mechanism','值得测试的表达方式','long'),f('local_fit','与汕头顾客的相关性','long'),
    f('signals','实际看到的公开反馈','long',hint='注明日期；点赞不等于曝光或成交'),
    f('effort','制作负担','choice',('低：现有素材可做','中：需要少量补拍','高：需要重新制作'))]),
 'learnings':('经验与长期记忆',[
    B,f('title','结论标题',required=True),f('level','依据等级','choice',('待验证解释','观察事实','本店已验证')),
    f('body','结论及适用条件','long',required=True),f('basis','证据和来源','long'),
    f('share_ai','允许在相关 AI 任务中使用','bool')]),
}

PIECE_FIELDS=[B,f('topic','选题名称',required=True),f('platform','发布平台','choice',PLATFORMS),
 f('plan_date','计划日期','date'),f('audience','希望谁看到'),f('hypothesis','准备验证什么','long'),
 f('offer_id','关联产品 / 服务','offer'),f('reference_id','参考案例','reference'),
 f('angle','借鉴的表达方式','long'),f('missing','还需要补拍什么','long'),
 f('title','发布标题'),f('cover','封面文字'),f('body','正文','long'),f('script','视频脚本 / 镜头顺序','long'),
 f('cta','下一步如何咨询或购买'),f('published_date','实际发布日期','optional_date'),f('published_url','发布链接')]

FEEDBACK_FIELDS=[f('observed_date','采集日期','date'),
 f('impressions','曝光次数','metric',hint='平台没提供就留空'),f('views','阅读 / 播放次数','metric'),
 f('clicks','点击次数','metric'),f('saves','收藏次数','metric'),
 f('local_inquiries','可确认来自本地的咨询','metric'),f('qualified_inquiries','相关业务咨询','metric'),
 f('orders','可归因订单','metric'),f('contribution','订单贡献毛利合计（元）','money_optional'),
 f('spend','内容投放花费（元）','money_optional'),f('minutes','制作及运营耗时（分钟）','metric'),
 f('facts','观察到的事实','long'),f('explanation','待验证的解释','long'),f('next_action','下一条保留 / 调整什么','long')]
